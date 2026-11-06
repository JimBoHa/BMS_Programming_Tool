"""Owned UDP direct/routed recovery transfers, unknown reconciliation and fresh parent refusal."""

import asyncio
import copy
import struct
import types

import pytest
from bacpypes3.primitivedata import Enumerated
from bms_tool.moi_identity import seal
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_binary_terminal import BinaryTerminalCompiler
from bms_tool.native_binary_terminal_recovery import NativeBinaryTerminalRecovery
from bms_tool.native_binary_terminal_recovery_transfer import KEYS, PROFILE
from bms_tool.native_inputs import InputPreview, NativeInputCompiler

from .test_controller_application import encoded
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_binary_terminal import edit as terminal_edit
from .test_native_binary_terminal import replaced
from .test_native_binary_terminal_recovery import saved_unsigned
from .test_native_binary_terminal_transfer import binary_peer, tick, with_counter
from .test_native_default_transfer import NativeRouter, real_slot
from .test_native_input_transfer import apply, preview


async def inverse(link, *, counters=False):
    peer, service = binary_peer(link)
    if counters:
        peer.files, first = with_counter(peer.files)
        peer.files, second = saved_unsigned(peer.files, 33, 90000)
        peer.recovery_counter_offsets = (first, second)
    _, parent = await preview(
        link, terminal_edit(BinaryTerminalCompiler(NativeInputCompiler(peer.files))), "parent"
    )
    original = await service.apply_input(**apply(parent, "parent"))
    assert original["result"]["status"] == "verified", original
    capture = await service.capture(**link[4], operation_id="capture-inverse")
    draft = NativeBinaryTerminalRecovery(NativeBackupRecords(service.storage)).prepare(
        {
            "receipt_id": original["intent"]["id"],
            "capture_id": capture["id"],
            "snapshot_sha256": capture["snapshot_evidence_sha256"],
        }
    )
    arguments = {
        **link[4],
        **draft["proposal"],
        "operation_id": "review-inverse",
        "binary_terminal_recovery_parent_receipt": original["intent"]["id"],
        "binary_terminal_recovery_origin_sha256": draft["origin_sha256"],
    }
    if counters:
        for offset, value in zip(peer.recovery_counter_offsets, (80, 90003), strict=True):
            tick(peer, offset, value)
    plan = await service.preview_binary_terminal_recovery(**arguments)
    return peer, service, original, draft, arguments, plan


@pytest.mark.parametrize("routed", [False, True])
async def test_fresh_inverse_transfer_retains_parent_lineage_and_complete_readback(
    native_link, routed
):
    transport = router = None
    if routed:
        host, port = native_link[4]["address"].rsplit(":", 1)
        endpoint = (host, int(port))
        transport, router = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: NativeRouter(endpoint), local_addr=("127.0.0.1", 0)
        )
        native_link[4].update(address="3001:7", router=router.endpoint, dnet=3001)
    try:
        peer, service, parent, draft, _, plan = await inverse(native_link)
        assert (
            plan["binary_terminal_recovery_profile"] == PROFILE
            and plan["binary_terminal_recovery_lineage_enforced"]
        )
        assert plan["binary_terminal_recovery_origin_sha256"] == draft["origin_sha256"]
        real_slot(peer.files, 4, struct.pack(">f", 9.25))
        result = await service.apply_input(**apply(plan, "inverse"))
        assert result["result"]["status"] == "verified", result
        intent = result["intent"]
        assert (
            intent["binary_terminal_recovery_profile"] == PROFILE
            and intent["binary_terminal_recovery_lineage_enforced"]
        )
        assert intent["binary_terminal_recovery_parent_receipt"] == parent["intent"]["id"]
        assert intent["binary_terminal_recovery_origin"] == draft["origin"]
        assert (
            BinaryTerminalCompiler(NativeInputCompiler(peer.files)).source()["inputs"][0]["slot"]
            == 1
        )
        current = NativeInputCompiler(peer.files).app
        assert current.reader.scalar(current.root, 900) == 9.25
        before = list(peer.events)
        observed = await service.reconcile(operation_id="inverse-readback", receipt_id=intent["id"])
        assert observed["events"][-1]["detail"]["status"] == "verified", observed
        assert [x for x in peer.events if x[0] == "write"] == [x for x in before if x[0] == "write"]
        with pytest.raises(ValueError):
            await service.apply_input(**apply(plan, "inverse-replay"))
        if router:
            assert router.requests and not router.errors
    finally:
        if transport:
            transport.close()


async def test_uncertain_inverse_keeps_lineage_and_reconciles_without_replay(native_link):
    peer, service, parent, _, _, plan = await inverse(native_link)
    peer.mode = "drop-end"
    result = await service.apply_input(**apply(plan, "inverse-uncertain"))
    assert result["result"]["status"] == "unknown"
    assert result["intent"]["binary_terminal_recovery_parent_receipt"] == parent["intent"]["id"]
    peer.mode = "normal"
    before = [x for x in peer.events if x[0] == "write"]
    observed = await service.reconcile(
        operation_id="inverse-after-unknown", receipt_id=result["intent"]["id"]
    )
    assert observed["events"][-1]["detail"]["status"] == "verified", observed
    assert [x for x in peer.events if x[0] == "write"] == before


async def test_parent_is_revalidated_before_new_intent_and_program_dispatch(
    native_link, monkeypatch
):
    peer, service, parent, _, _, plan = await inverse(native_link)
    original = service.storage.receipt

    def changed(receipt_id, *args, **kwargs):
        value = original(receipt_id, *args, **kwargs)
        if receipt_id == parent["intent"]["id"]:
            value = copy.deepcopy(value)
            value["result"]["native_sha256"] = "0" * 64
        return value

    monkeypatch.setattr(service.storage, "receipt", changed)
    before = [x for x in peer.events if x[0] == "write"]
    result = await service.apply_input(**apply(plan, "inverse-changed-parent"))
    assert result["result"]["status"] == "not_sent" and not result["result"]["may_have_applied"]
    assert [x for x in peer.events if x[0] == "write"] == before
    assert len(service.storage.receipts()) == 1


async def test_wrong_origin_refuses_review_before_field_reads(native_link):
    peer, service, _, _, arguments, _ = await inverse(native_link)
    before = list(peer.events)
    arguments |= {
        "operation_id": "wrong-origin-review",
        "binary_terminal_recovery_origin_sha256": "0" * 64,
    }
    with pytest.raises(ValueError):
        await service.preview_binary_terminal_recovery(**arguments)
    assert peer.events == before


@pytest.mark.parametrize(
    "confirmation",
    ["physical_wiring_confirmed", "input_change_confirmed", "application_transfer_confirmed"],
)
async def test_each_confirmation_is_still_required_for_a_lineage_bound_inverse(
    native_link, confirmation
):
    peer, service, _, _, _, plan = await inverse(native_link)
    before = list(peer.events)
    with pytest.raises(ValueError, match="Confirm"):
        await service.apply_input(**(apply(plan, "inverse-confirmation") | {confirmation: False}))
    assert peer.events == before and len(service.storage.receipts()) == 1


@pytest.mark.parametrize("key", sorted(KEYS))
async def test_resealed_plan_with_removed_recovery_evidence_refuses_before_field_work(
    native_link, key
):
    from bms_tool.moi_identity import seal

    peer, service, _, _, _, plan = await inverse(native_link)
    owned = service.plans[plan["token"]]
    del owned["body"][key]
    owned["digest"] = seal(owned["body"])
    request = apply(plan, "missing-lineage") | {"review_sha256": owned["digest"]}
    before = list(peer.events)
    with pytest.raises(ValueError, match="lineage"):
        await service.apply_input(**request)
    assert peer.events == before and len(service.storage.receipts()) == 1


@pytest.mark.parametrize("routed", [False, True])
async def test_counter_ticks_before_review_apply_and_after_restore_preserve_fresh_values(
    native_link, routed
):
    transport = router = None
    if routed:
        host, port = native_link[4]["address"].rsplit(":", 1)
        transport, router = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
        )
        native_link[4].update(address="3001:7", router=router.endpoint, dnet=3001)
    try:
        peer, service, _, draft, _, plan = await inverse(native_link, counters=True)
        assert draft["inverse_compilation"]["captured_counter_values"] == {"15": 77, "33": 90000}
        assert plan["compilation"]["captured_counter_values"] == {"15": 77, "33": 90000}
        first, second = peer.recovery_counter_offsets
        tick(peer, first, 999999)
        tick(peer, second, 1000000)
        real_slot(peer.files, 4, struct.pack(">f", 9.25))
        reinitialize = peer.do_ReinitializeDeviceRequest

        async def restore(self, request):
            await reinitialize(request)
            if str(request.reinitializedStateOfDevice) == "end-restore":
                tick(self, first, 1000001)
                tick(self, second, 1000002)

        peer.do_ReinitializeDeviceRequest = types.MethodType(restore, peer)
        result = await service.apply_input(**apply(plan, "counter-inverse"))
        assert result["result"]["status"] == "verified", result
        assert result["intent"]["compilation"]["captured_counter_values"] == {
            "15": 999999,
            "33": 1000000,
        }
        assert result["intent"]["binary_terminal_recovery_origin_sha256"] == draft["origin_sha256"]
        current = BinaryTerminalCompiler(NativeInputCompiler(peer.files)).source()["inputs"][0]
        assert current["slot"] == 1 and current["captured_counter_values"] == {
            "15": 1000001,
            "33": 1000002,
        }
        app = NativeInputCompiler(peer.files).app
        assert app.reader.scalar(app.root, 900) == 9.25
        runtime = result["result"]["preservation"]["runtime_counter_changes"]
        assert {row["property"] for row in runtime} == {15, 33}
        if router:
            assert router.requests and not router.errors
    finally:
        if transport:
            transport.close()


@pytest.mark.parametrize("fault", ["receipt", "backup", "selected-capture"])
async def test_removed_parent_or_retained_source_refuses_before_a_new_durable_intent(
    native_link, fault
):
    peer, service, parent, draft, _, plan = await inverse(native_link)
    if fault == "receipt":
        with service.storage.store.connect() as db:
            db.execute("DELETE FROM application_transfers WHERE id=?", (parent["intent"]["id"],))
    else:
        source = (
            parent["intent"]["backup_id"]
            if fault == "backup"
            else draft["origin"]["current_capture_id"]
        )
        (service.storage.directory / source / "file-3.bin").unlink()
    receipt_ids = {row["intent"]["id"] for row in service.storage.receipts()}
    writes = [event for event in peer.events if event[0] == "write"]
    result = await service.apply_input(**apply(plan, "missing-parent"))
    assert result["result"]["status"] == "not_sent" and not result["result"]["may_have_applied"]
    assert {row["intent"]["id"] for row in service.storage.receipts()} == receipt_ids
    assert [event for event in peer.events if event[0] == "write"] == writes


@pytest.mark.parametrize(
    "fault", ["all-keys", "ordinary-options", "legacy-namespace", "analog-namespace"]
)
async def test_lineage_cannot_be_removed_demoted_or_mixed_before_field_work(native_link, fault):
    peer, service, _, _, _, plan = await inverse(native_link)
    owned = service.plans[plan["token"]]
    if fault == "all-keys":
        for key in KEYS:
            del owned["body"][key]
    elif fault == "ordinary-options":
        owned["options"] = InputPreview(
            **owned["options"].model_dump(
                exclude={
                    "binary_terminal_recovery_parent_receipt",
                    "binary_terminal_recovery_origin_sha256",
                }
            )
        )
    elif fault == "legacy-namespace":
        owned["body"]["recovery_parent_receipt"] = "a" * 32
    else:
        owned["body"]["encoded_analog_recovery_parent_receipt"] = "a" * 32
    owned["digest"] = seal(owned["body"])
    request = apply(plan, "substituted-lineage") | {"review_sha256": owned["digest"]}
    before = list(peer.events)
    with pytest.raises(ValueError, match="lineage"):
        await service.apply_input(**request)
    assert peer.events == before and len(service.storage.receipts()) == 1


async def test_current_binary_configuration_change_refuses_before_new_program_dispatch(native_link):
    peer, service, _, _, _, plan = await inverse(native_link)
    peer.files = replaced(peer.files, {84: encoded(Enumerated(0))})
    writes = [event for event in peer.events if event[0] == "write"]
    result = await service.apply_input(**apply(plan, "changed-configuration"))
    assert result["result"]["status"] == "not_sent" and not result["result"]["may_have_applied"]
    assert [event for event in peer.events if event[0] == "write"] == writes
    assert len(service.storage.receipts()) == 1


async def test_changed_interface_retires_the_recovery_without_any_further_peer_access(native_link):
    peer, service, _, _, _, plan = await inverse(native_link)
    service.bacnet.config = {**service.bacnet.config, "interface": "changed"}
    before = list(peer.events)
    result = await service.apply_input(**apply(plan, "changed-interface"))
    assert result["result"]["status"] == "not_sent" and not result["result"]["may_have_applied"]
    assert peer.events == before and len(service.storage.receipts()) == 1
