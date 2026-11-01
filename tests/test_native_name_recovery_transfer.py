"""A name recovery uses fresh native preflight and a separate one-use restore."""

import asyncio
import copy

import pytest
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_applications import NativeApplications

from .test_native_applications import apply_request
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_recovery import set_saved
from .test_native_default_transfer import NativeRouter, mutations
from .test_native_signal_compiler import signal_files


async def recovery_review(link, *, target=None):
    peer, _, _, service, direct = link
    target = target or direct
    peer.files = signal_files()
    capture = await service.capture(**target, operation_id="capture-before-name")
    plan = await service.preview(
        **target,
        operation_id="review-name-forward",
        capture_id=capture["id"],
        new_instance=5136,
        new_name="Renamed controller",
    )
    parent = await service.apply(**name_apply(plan))
    assert parent["result"]["status"] == "verified", parent
    capture = await service.capture(**target, operation_id="capture-name-recovery")
    prepared = service.name_recovery.prepare(
        {
            "receipt_id": parent["intent"]["id"],
            "capture_id": capture["id"],
            "snapshot_sha256": capture["snapshot_evidence_sha256"],
        }
    )
    proposal = prepared["proposal"] | {"recovery_origin_sha256": prepared["origin_sha256"]}
    plan = await service.preview_name_recovery(
        **target, operation_id="review-name-recovery", **proposal
    )
    return parent, capture, prepared, proposal, plan


def name_apply(plan):
    return apply_request(plan) | {"allocation_confirmed": False, "name_change_confirmed": True}


@pytest.mark.parametrize("routed", [False, True])
async def test_new_name_recovery_transfer_preserves_instance_and_other_fresh_values(
    native_link, routed
):
    peer, _, _, service, target = native_link
    transport = proxy = None
    if routed:
        host, port = target["address"].split(":")
        transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
        )
        target = target | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
    try:
        parent, _, prepared, _, plan = await recovery_review(native_link, target=target)
        assert plan["recovery_origin"] == prepared["origin"]
        peer.files = set_saved(peer.files, 17.5, second=True)
        fresh = copy.deepcopy(peer.files)
        start = len(mutations(peer))
        result = await service.apply(**name_apply(plan))
        assert result["result"]["status"] == "verified", result
        assert result["intent"]["id"] != parent["intent"]["id"]
        assert result["intent"]["recovery_origin"] == prepared["origin"]
        assert service.storage.load(result["intent"]["backup_id"])[1] == fresh
        assert service.storage.receipt(parent["intent"]["id"]) == parent
        assert peer.instance == 5136 and peer.metadata["object-name"] == "Authored controller"
        parsed = MoiIdentity(peer.files[3])
        assert parsed.reader.scalar(parsed.reader.records["controller/signal-11"], 3113) == 17.5
        assert result["result"]["preservation"]["application_identical_except_name"]
        changes = mutations(peer)[start:]
        assert (
            changes.count(("state", "start-restore"))
            == changes.count(("state", "end-restore"))
            == 1
        )
        assert all(row[1] == 3 for row in changes if row[0] == "write")
        with pytest.raises(ValueError, match="consumed"):
            await service.apply(**name_apply(plan))
        assert mutations(peer)[start:] == changes
        if proxy:
            assert not proxy.errors and len(proxy.requests) == len(proxy.responses)
    finally:
        if transport:
            transport.close()
            await asyncio.sleep(0.02)


@pytest.mark.parametrize(
    "change", ["name", "instance", "hash", "parent", "missing", "ordinary-route"]
)
async def test_changed_or_cross_kind_recovery_proposal_refuses_before_network(native_link, change):
    peer, _, _, service, target = native_link
    _, _, _, proposal, _ = await recovery_review(native_link)
    proposal = dict(proposal)
    if change == "name":
        proposal["new_name"] = "A different name"
    elif change == "instance":
        proposal["new_instance"] = 5137
    elif change == "hash":
        proposal["recovery_origin_sha256"] = "0" * 64
    elif change == "parent":
        proposal["recovery_parent_receipt"] = "0" * 32
    elif change == "missing":
        del proposal["snapshot_sha256"]
    before = list(peer.events)
    with pytest.raises(ValueError):
        await (service.preview if change == "ordinary-route" else service.preview_name_recovery)(
            **target, operation_id="reject-name-recovery", **proposal
        )
    assert peer.events == before


@pytest.mark.parametrize(
    "change", ["name", "directory", "parent-pending", "parent-backup", "confirmation"]
)
async def test_recovery_apply_rechecks_original_and_fresh_source_before_restore(
    native_link, change
):
    peer, _, store, service, _ = native_link
    parent, _, _, _, plan = await recovery_review(native_link)
    request = name_apply(plan)
    if change == "name":
        peer.metadata["object-name"] = "Different live name"
    elif change == "directory":
        peer.files[11] += b"changed"
    elif change == "parent-pending":
        with store.connect() as db:
            db.execute(
                "UPDATE application_transfers SET pending=1 WHERE id=?", (parent["intent"]["id"],)
            )
    elif change == "parent-backup":
        (service.storage.directory / parent["intent"]["backup_id"] / "file-3.bin").unlink()
    else:
        request["name_change_confirmed"] = False
    start = len(mutations(peer))
    try:
        result = await service.apply(**request)
    except ValueError:
        result = None
    if result:
        assert result["result"]["status"] == "not_sent", result
    assert not any(
        row[0] == "write" or row == ("state", "start-restore") for row in mutations(peer)[start:]
    )


async def test_lost_commit_restarts_and_reads_back_without_another_name_restore(native_link):
    peer, bacnet, store, service, _ = native_link
    parent, _, _, _, plan = await recovery_review(native_link)
    peer.mode = "drop-end"
    start = len(mutations(peer))
    uncertain = await service.apply(**name_apply(plan))
    assert uncertain["pending"] and uncertain["result"]["may_have_applied"]
    assert uncertain["intent"]["recovery_origin"]["parent_receipt_id"] == parent["intent"]["id"]
    restored = mutations(peer)[start:]
    await service.close()
    restarted = NativeApplications(bacnet, store, service.instances, request_timeout=0.1, gap=0)
    try:
        result = await restarted.reconcile(
            receipt_id=uncertain["intent"]["id"], operation_id="readback-name-restart"
        )
        assert not result["pending"] and result["latest_readback"]["status"] == "verified", result
        assert [
            row
            for row in mutations(peer)[start:]
            if row[0] == "write" or row[1] in ("start-restore", "end-restore")
        ] == restored
    finally:
        await restarted.close()
