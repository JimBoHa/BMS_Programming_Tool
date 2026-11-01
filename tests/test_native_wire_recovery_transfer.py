"""A wire recovery uses a second owned-UDP transfer, never the original token."""

import asyncio
import struct

import pytest
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_applications import NativeApplications
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_wire_compiler import EffectiveWireService
from bms_tool.native_wire_transfer import WireTransferPreview

from .test_moi_wire_sources import REF, A, B
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import NativeRouter, mutations, real_slot
from .test_native_wire_compiler import BOOLEAN, proposal, query, wire_files
from .test_native_wire_recovery import FANOUT, IDENTITY
from .test_native_wire_transfer import applying


async def recovery_review(link, *, index=0, target=None, diagram_class=575):
    peer, _, _, native, original_target = link
    target = target or original_target
    peer.files = wire_files(target_class=538, wires=FANOUT, diagram_class=diagram_class)
    peer.metadata["object-name"] = IDENTITY["object-name"]
    peer.mode = "normal"

    async def no_collision(_):
        raise AssertionError("A recovery must not allocate or scan Device identities.")

    native.instances._collision = no_collision
    captured = await native.capture(**target, operation_id="capture-wire-original")
    snapshot, _ = native.storage.load(captured["id"])
    compiler = EffectiveWireService(NativeBackupRecords(native.storage))
    edit = proposal(
        compiler, query(compiler, snapshot, index=index), source_ref=B if index == 0 else A
    )
    original_plan = await native.preview_wire(**target, **edit, operation_id="review-wire-original")
    parent = await native.apply_wire(**applying(original_plan))
    assert parent["result"]["status"] == "verified", parent
    capture = await native.capture(**target, operation_id="capture-wire-recovery")
    prepared = native.wire_recovery.prepare(
        {
            "receipt_id": parent["intent"]["id"],
            "capture_id": capture["id"],
            "snapshot_sha256": capture["snapshot_evidence_sha256"],
        }
    )
    body = prepared["proposal"] | {"recovery_origin_sha256": prepared["origin_sha256"]}
    plan = await native.preview_wire(**target, **body, operation_id="review-wire-recovery")
    return parent, prepared, body, plan


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("diagram_class", [536, 575])
async def test_new_wire_restore_preserves_current_settings_identity_and_parent(
    native_link, routed, index, diagram_class
):
    peer, _, _, native, target = native_link
    transport = proxy = None
    if routed:
        host, port = target["address"].rsplit(":", 1)
        transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
        )
        target = target | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
    try:
        parent, prepared, _, plan = await recovery_review(
            native_link, index=index, target=target, diagram_class=diagram_class
        )
        assert prepared["origin"]["class_id"] == diagram_class
        assert plan["recovery_origin"] == prepared["origin"]
        real_slot(peer.files, 0, struct.pack(">f", 45))
        start = len(mutations(peer))
        result = await native.apply_wire(**applying(plan) | {"operation_id": "apply-wire-recovery"})
        assert result["result"]["status"] == "verified" and not result["pending"], result
        assert result["intent"]["id"] != parent["intent"]["id"]
        assert result["intent"]["recovery_origin"] == prepared["origin"]
        assert result["intent"]["recovery_origin_sha256"] == prepared["origin_sha256"]
        assert result["intent"]["payload_sha256"] != plan["payload_sha256"]
        assert native.storage.receipt(parent["intent"]["id"]) == parent
        image = MoiIdentity(peer.files[3])
        assert image.instance == 5136
        assert image.reader.diagram(REF)["connections"][index]["source_ref"] == (
            A if index == 0 else B
        )
        assert image.reader.scalar(image.reader.records[A], 3113) == 45
        assert image.reader.scalar(image.reader.records[B], 3113) == 17
        assert image.reader.scalar(image.reader.records[BOOLEAN], 3113) is True
        changes = mutations(peer)[start:]
        assert (
            changes.count(("state", "start-restore"))
            == changes.count(("state", "end-restore"))
            == 1
        )
        assert all(row[1] == 3 for row in changes if row[0] == "write")
        with pytest.raises(ValueError, match="consumed"):
            await native.apply_wire(**applying(plan))
        assert mutations(peer)[start:] == changes
        if proxy:
            assert not proxy.errors and not proxy.clients
            assert len(proxy.requests) == len(proxy.responses)
    finally:
        if transport:
            transport.close()
            await asyncio.sleep(0.02)


@pytest.mark.parametrize("change", ["source", "origin", "missing-origin"])
async def test_recovery_purpose_cannot_be_changed_or_unbound(native_link, change):
    peer, _, _, native, target = native_link
    _, _, body, _ = await recovery_review(native_link)
    if change == "source":
        body["wire_index"] = 1
    elif change == "origin":
        body["recovery_origin_sha256"] = "0" * 64
    else:
        del body["recovery_origin_sha256"]
    before = list(peer.events)
    with pytest.raises(ValueError):
        await native.preview_wire(**target, **body, operation_id="reject-wire-recovery")
    assert peer.events == before


@pytest.mark.parametrize("change", ["application", "parent-pending", "parent-backup"])
async def test_apply_revalidates_current_and_original_evidence_without_dispatch(
    native_link, change
):
    peer, _, store, native, _ = native_link
    parent, _, _, plan = await recovery_review(native_link)
    if change == "application":
        import gzip

        peer.files[3] = gzip.compress(
            MoiIdentity(peer.files[3]).data.replace(
                b"Opaque metadata retained", b"Unsafe metadata retained"
            ),
            mtime=0,
        )
    elif change == "parent-pending":
        with store.connect() as db:
            db.execute(
                "UPDATE application_transfers SET pending=1 WHERE id=?", (parent["intent"]["id"],)
            )
    else:
        (native.storage.directory / parent["intent"]["backup_id"] / "file-12.bin").write_bytes(
            b"tampered"
        )
    before = list(mutations(peer))
    result = await native.apply_wire(**applying(plan))
    assert result["result"]["status"] == "not_sent" and not result["result"]["may_have_applied"], (
        result
    )
    assert mutations(peer) == before and len(native.storage.receipts()) == 1


async def test_lost_commit_reconciles_after_restart_without_replay(native_link):
    peer, bacnet, store, native, _ = native_link
    _, prepared, _, plan = await recovery_review(native_link)
    peer.mode = "drop-end"
    result = await native.apply_wire(**applying(plan))
    assert result["pending"] and result["result"]["status"] == "unknown"
    assert result["intent"]["recovery_origin_sha256"] == prepared["origin_sha256"]
    before = list(mutations(peer))
    peer.mode = "normal"
    restarted = NativeApplications(bacnet, store, native.instances, request_timeout=0.1, gap=0)
    try:
        observed = await restarted.reconcile(
            operation_id="readback-wire-recovery", receipt_id=result["intent"]["id"]
        )
        assert not observed["pending"] and observed["latest_readback"]["status"] == "verified"
        assert observed["result"] == result["result"]
        assert observed["latest_readback"]["preservation"]["selected_wire"]["source_ref"] == A
        assert mutations(peer) == before
    finally:
        await restarted.close()


def test_recovery_admission_fields_are_paired(tmp_path):
    from pydantic import ValidationError

    from .test_native_wire_recovery import setup

    storage, service, request, _, _ = setup(tmp_path)
    report = service.prepare(request)
    target = storage.load(request["capture_id"])[0]["target"]
    body = (
        target
        | report["proposal"]
        | {
            "device": "device,5136",
            "operation_id": "admit-wire-recovery",
            "recovery_origin_sha256": report["origin_sha256"],
        }
    )
    assert WireTransferPreview.model_validate(body).recovery_parent_receipt == request["receipt_id"]
    for key in ("recovery_parent_receipt", "recovery_origin_sha256"):
        partial = {k: v for k, v in body.items() if k != key}
        with pytest.raises(ValidationError, match="Provide both"):
            WireTransferPreview.model_validate(partial)
