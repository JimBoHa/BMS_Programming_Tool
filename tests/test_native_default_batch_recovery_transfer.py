"""Previous batches require new lineage-bound reviews and actual complete readback."""

import copy

import pytest
from bms_tool.moi_default_batch import EffectiveDefaultBatchCompiler
from bms_tool.native_default_batch_recovery_transfer import PROFILE

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_batch_transfer import applying, review_native
from .test_native_default_transfer import mutations


async def original_and_proposal(link, target=None):
    peer, _, _, native, original_target = link
    target = target or original_target
    _, original_plan = await review_native(link, target=target)
    receipt = await native.apply_default_batch(**applying(original_plan))
    assert receipt["result"]["status"] == "verified"
    current = await native.capture(**target, operation_id="capture-previous-batch-transfer")
    snapshot, _ = native.storage.load(current["id"])
    prepared = native.default_batch_recovery.prepare(
        {
            "receipt_id": receipt["intent"]["id"],
            "capture_id": current["id"],
            "snapshot_sha256": snapshot["evidence_sha256"],
        }
    )
    arguments = {
        **target,
        **prepared["proposal"],
        "operation_id": "review-previous-batch-transfer",
        "recovery_parent_receipt": receipt["intent"]["id"],
        "recovery_origin_sha256": prepared["origin_sha256"],
    }
    return receipt, prepared, arguments


async def test_actual_previous_batch_has_a_new_confirmed_restore_and_complete_readback(native_link):
    peer, _, _, native, _ = native_link
    parent, prepared, args = await original_and_proposal(native_link)
    original = copy.deepcopy(native.storage.receipt(parent["intent"]["id"]))
    before = list(mutations(peer))
    plan = await native.preview_default_batch(**args)
    assert plan["recovery_profile"] == PROFILE
    assert plan["recovery_origin"] == prepared["origin"]
    result = await native.apply_default_batch(
        **applying(plan, operation_id="apply-previous-batch-transfer")
    )
    assert result["result"]["status"] == "verified" and not result["pending"]
    assert result["intent"]["recovery_origin"] == prepared["origin"]
    assert (
        mutations(peer).count(("state", "start-restore"))
        == before.count(("state", "start-restore")) + 1
    )
    fields = {r["field"]["ref"]: r for r in EffectiveDefaultBatchCompiler(peer.files).fields()}
    for row in prepared["origin"]["fields"]:
        f = fields[row["record_ref"]]["field"]
        assert (
            {"bits": f["effective_bits"]}
            if row["kind"] == "real"
            else {"value": f["effective_value"]}
        ) == row["previous"]
    assert native.storage.receipt(parent["intent"]["id"]) == original
    with pytest.raises(ValueError):
        await native.apply_default_batch(
            **applying(plan, operation_id="replay-previous-batch-transfer")
        )


@pytest.mark.parametrize("fault", ["origin", "value", "unpaired"])
async def test_contradictory_previous_batch_request_refuses_before_any_peer_query(
    native_link, fault
):
    peer, _, _, native, _ = native_link
    _, _, args = await original_and_proposal(native_link)
    if fault == "origin":
        args["recovery_origin_sha256"] = "a" * 64
    if fault == "value":
        args["changes"][0]["value_text"] = "99"
    if fault == "unpaired":
        args.pop("recovery_origin_sha256")
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        await native.preview_default_batch(**args)
    assert peer.events == before


async def test_other_fresh_saved_settings_remain_current_during_previous_batch_restore(native_link):
    import struct

    from .test_native_default_transfer import real_slot

    peer, _, _, native, _ = native_link
    _, prepared, args = await original_and_proposal(native_link)
    plan = await native.preview_default_batch(**args)
    real_slot(peer.files, 0, struct.pack(">f", 47))
    result = await native.apply_default_batch(
        **applying(plan, operation_id="apply-previous-preserve-fresh")
    )
    assert result["result"]["status"] == "verified"
    assert result["intent"]["recovery_origin"] == prepared["origin"]
    from bms_tool.moi_identity import MoiIdentity

    app = MoiIdentity(peer.files[3])
    assert app.reader.scalar(app.reader.records["controller/575_1.2_10"], 3113) == 47


async def test_changed_selected_live_value_refuses_previous_restore_without_dispatch(native_link):
    import struct

    from .test_native_default_transfer import real_slot

    peer, _, _, native, _ = native_link
    _, _, args = await original_and_proposal(native_link)
    plan = await native.preview_default_batch(**args)
    real_slot(peer.files, 17, struct.pack(">f", 19))
    before = mutations(peer).count(("state", "start-restore"))
    result = await native.apply_default_batch(
        **applying(plan, operation_id="refuse-previous-selected-drift")
    )
    assert result["result"]["status"] == "not_sent" and not result["pending"]
    assert mutations(peer).count(("state", "start-restore")) == before


async def test_original_evidence_is_reconstructed_again_before_durable_intent(native_link):
    peer, _, _, native, _ = native_link
    parent, _, args = await original_and_proposal(native_link)
    plan = await native.preview_default_batch(**args)
    path = native.storage.directory / parent["intent"]["backup_id"] / "file-3.bin"
    original = path.read_bytes()
    before = list(mutations(peer))
    count = len(native.storage.receipts())
    try:
        path.write_bytes(b"Changed original evidence")
        result = await native.apply_default_batch(
            **applying(plan, operation_id="refuse-changed-original-batch")
        )
        assert result["result"]["status"] == "not_sent" and result["intent"] is None
        assert len(native.storage.receipts()) == count
        assert mutations(peer).count(("state", "start-restore")) == before.count(
            ("state", "start-restore")
        )
    finally:
        path.write_bytes(original)


@pytest.mark.parametrize("fault", ["origin", "scope", "ordinary-injection"])
async def test_changed_or_forged_recovery_plan_refuses_before_peer_queries(native_link, fault):
    from bms_tool.moi_identity import seal

    peer, _, _, native, _ = native_link
    _, _, args = await original_and_proposal(native_link)
    if fault == "ordinary-injection":
        args.pop("recovery_parent_receipt")
        args.pop("recovery_origin_sha256")
    plan = await native.preview_default_batch(**args)
    held = native.plans[plan["token"]]
    if fault == "origin":
        held["body"]["recovery_origin"]["fields"][0]["previous"]["bits"] = "00000000"
    elif fault == "scope":
        held["body"]["recovery_scope"] = "Unsupported recovery"
    else:
        held["body"]["recovery_origin"] = None
    held["digest"] = seal(held["body"])
    request = applying(
        plan, operation_id="refuse-changed-batch-lineage", review_sha256=held["digest"]
    )
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        await native.apply_default_batch(**request)
    assert peer.events == before


@pytest.mark.parametrize("routed", [False, True])
async def test_lost_recovery_ack_readback_after_restart_needs_no_original_parent_files(
    native_link, routed
):
    import asyncio

    from bms_tool.native_applications import NativeApplications

    from .test_native_default_transfer import NativeRouter

    peer, bacnet, store, native, target = native_link
    transport = None
    if routed:
        address, port = target["address"].rsplit(":", 1)
        transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: NativeRouter((address, int(port))), local_addr=("127.0.0.1", 0)
        )
        target = {
            "address": "3001:7",
            "device": "device,5136",
            "router": proxy.endpoint,
            "dnet": 3001,
        }
    restarted = None
    original = None
    path = None
    try:
        parent, prepared, args = await original_and_proposal(native_link, target)
        plan = await native.preview_default_batch(**args)
        peer.mode = "drop-end"
        result = await native.apply_default_batch(
            **applying(plan, operation_id="lose-previous-batch-ack")
        )
        assert result["pending"] and result["result"]["status"] == "unknown"
        sent = list(mutations(peer))
        peer.mode = "normal"
        await native.close()
        path = native.storage.directory / parent["intent"]["backup_id"] / "file-3.bin"
        original = path.read_bytes()
        path.unlink()
        restarted = NativeApplications(bacnet, store, native.instances, request_timeout=0.1, gap=0)
        checked = await restarted.reconcile(
            operation_id="readback-previous-batch-after-restart", receipt_id=result["intent"]["id"]
        )
        assert not checked["pending"] and checked["latest_readback"]["status"] == "verified"
        assert checked["intent"]["recovery_origin"] == prepared["origin"]
        assert mutations(peer) == sent
        if routed:
            assert not proxy.errors
    finally:
        if path is not None and original is not None:
            path.write_bytes(original)
        if restarted is not None:
            await restarted.close()
        if transport:
            transport.close()


@pytest.mark.parametrize("flag", ["defaults_change_confirmed", "application_transfer_confirmed"])
async def test_recovery_requires_each_new_confirmation_before_any_peer_query(native_link, flag):
    peer, _, _, native, _ = native_link
    _, _, args = await original_and_proposal(native_link)
    plan = await native.preview_default_batch(**args)
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        await native.apply_default_batch(**applying(plan, **{flag: False}))
    assert peer.events == before
