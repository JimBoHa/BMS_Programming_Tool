"""Owned UDP direct/routed recovery transfers, unknown reconciliation and fresh parent refusal."""

import asyncio
import copy
import struct

import pytest
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_inputs import NativeInputCompiler
from bms_tool.native_terminal_recovery import NativeTerminalRecovery
from bms_tool.native_terminal_recovery_transfer import PROFILE

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import NativeRouter, real_slot
from .test_native_input_transfer import apply, install_input_peer, preview
from .test_native_inputs import source
from .test_native_terminal_input import terminal_edit


async def inverse(link):
    peer, service = install_input_peer(link, initialize=False)
    peer.files = source(existing=True)
    _, parent = await preview(link, terminal_edit(NativeInputCompiler(peer.files)), "parent")
    original = await service.apply_input(**apply(parent, "parent"))
    assert original["result"]["status"] == "verified", original
    capture = await service.capture(**link[4], operation_id="capture-inverse")
    draft = NativeTerminalRecovery(NativeBackupRecords(service.storage)).prepare(
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
        "recovery_parent_receipt": original["intent"]["id"],
        "recovery_origin_sha256": draft["origin_sha256"],
    }
    plan = await service.preview_terminal_recovery(**arguments)
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
            plan["terminal_recovery_profile"] == PROFILE
            and plan["terminal_recovery_lineage_enforced"]
        )
        assert plan["recovery_origin_sha256"] == draft["origin_sha256"]
        real_slot(peer.files, 4, struct.pack(">f", 9.25))
        result = await service.apply_input(**apply(plan, "inverse"))
        assert result["result"]["status"] == "verified", result
        intent = result["intent"]
        assert (
            intent["terminal_recovery_profile"] == PROFILE
            and intent["terminal_recovery_lineage_enforced"]
        )
        assert intent["recovery_parent_receipt"] == parent["intent"]["id"]
        assert intent["recovery_origin"] == draft["origin"]
        assert NativeInputCompiler(peer.files).source()["inputs"][0]["slot"] == 1
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
    assert result["intent"]["recovery_parent_receipt"] == parent["intent"]["id"]
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
    arguments |= {"operation_id": "wrong-origin-review", "recovery_origin_sha256": "0" * 64}
    with pytest.raises(ValueError):
        await service.preview_terminal_recovery(**arguments)
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
