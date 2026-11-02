"""Previous point names are new source-pinned edits, never receipt replays."""

import copy
import gzip
import secrets
import struct

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.mstp import header_crc
from bms_tool.native_applications import NativeApplications
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_point_name_recovery import PROFILE, NativePointNameRecovery
from bms_tool.native_point_names import PointNameCompiler, PointNamePreview, compile_point_name
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_point_names import (
    apply_args,
    edit_for,
    name_review,
    point_files,
)
from .test_native_signal_compiler import retained


def setup(
    path,
    *,
    compressed=True,
    encoding=0,
    outcome="verified",
    dispatched=True,
    changes=None,
    target=None,
    identity=None,
    previous="Authored input",
):
    storage = ApplicationStore(Store(path))
    files = point_files(compressed=compressed, encoding=encoding)
    if previous != "Authored input":
        files = files | {3: compile_point_name(files, edit_for(files, name=previous))[0]}
    metadata = {
        **({"target": target} if target else {}),
        **({"identity": identity} if identity else {}),
    }
    before = retained(storage, files, **metadata)
    edit = edit_for(files)
    output, compilation = compile_point_name(files, edit)
    parent_id = secrets.token_hex(16)
    intent = storage.intent(
        {
            "id": parent_id,
            "target": before["target"],
            "identity": before["identity"],
            "old_instance": 5136,
            "new_instance": 5136,
            "old_name": "Authored controller",
            "new_name": "Authored controller",
            "change_kind": "point-name",
            "operation_profile": "native-point-name-transfer/1",
            "point_name_confirmed": True,
            "application_transfer_confirmed": True,
            "backup_id": before["id"],
            "point_name_edit": edit,
            "compilation": compilation,
            "payload_sha256": sha(output),
            "native_payload_sha256": sha(MoiIdentity(output).data),
            **(changes or {}),
        }
    )
    if outcome != "intent-only":
        storage.finish(
            parent_id,
            {
                "intent_sha256": intent["evidence_sha256"],
                "status": outcome,
                "may_have_applied": dispatched,
            },
        )
    current_files = files | {3: output}
    current = retained(storage, current_files, **metadata)
    request = {
        "receipt_id": parent_id,
        "capture_id": current["id"],
        "snapshot_sha256": current["evidence_sha256"],
    }
    return (
        storage,
        NativePointNameRecovery(NativeBackupRecords(storage)),
        request,
        before,
        current_files,
    )


def current_source(storage, request, files, **metadata):
    current = retained(storage, files, **metadata)
    return request | {"capture_id": current["id"], "snapshot_sha256": current["evidence_sha256"]}


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("encoding", [0, 3, 4, 5])
def test_previous_name_proposal_keeps_exact_point_and_original_evidence(
    tmp_path, compressed, encoding
):
    storage, service, request, before, files = setup(
        tmp_path, compressed=compressed, encoding=encoding
    )
    original_receipt = storage.receipt(request["receipt_id"])
    report = service.prepare(request)
    assert report["profile"] == PROFILE and report["previous_name"] == "Authored input"
    assert report["recorded_after_name"] == report["current_name"] == "Changed input"
    assert report["origin"]["object_id"] == "analog-input,101"
    assert report["origin"]["original_backup_id"] == before["id"]
    assert report["origin"]["character_encoding"] == encoding
    assert report["read_only"] and report["new_review_required"] and not report["can_apply"]
    assert not report["field_actions"] and not report["controller_queries"]
    edit = {
        k: report["proposal"][k] for k in ("object_id", "record_ref", "encoded_sha256", "new_name")
    }
    output, _ = compile_point_name(files, edit)
    assert PointNameCompiler(files | {3: output}).fields()[0]["name"] == "Authored input"
    assert storage.receipt(request["receipt_id"]) == original_receipt
    assert (
        NativePointNameRecovery(NativeBackupRecords(ApplicationStore(Store(tmp_path)))).prepare(
            request
        )
        == report
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"change_kind": "name"},
        {"operation_profile": "future/2"},
        {"point_name_confirmed": False},
        {"application_transfer_confirmed": False},
        {"old_instance": True},
        {"new_instance": 5137},
        {"new_name": "different controller"},
        {"payload_sha256": "0" * 64},
        {"native_payload_sha256": "0" * 64},
        {"compilation": {}},
    ],
)
def test_inconsistent_parent_receipts_cannot_prepare_recovery(tmp_path, changes):
    _, service, request, _, _ = setup(tmp_path, changes=changes)
    with pytest.raises(ValueError):
        service.prepare(request)


@pytest.mark.parametrize(
    "outcome,dispatched", [("unknown", True), ("intent-only", True), ("verified", False)]
)
def test_pending_unverified_and_never_dispatched_outcomes_require_readback(
    tmp_path, outcome, dispatched
):
    _, service, request, _, _ = setup(tmp_path, outcome=outcome, dispatched=dispatched)
    with pytest.raises(ValueError):
        service.prepare(request)


@pytest.mark.parametrize(
    "which",
    ["route", "device", "identity", "unverified", "static", "opaque", "third-name", "reference"],
)
def test_changed_current_sources_refuse_without_changing_receipt(tmp_path, which):
    storage, service, request, _, files = setup(tmp_path)
    metadata = {}
    if which == "route":
        metadata["target"] = {"address": "3001:8", "router": "127.0.0.1:47999", "dnet": 3001}
    elif which == "device":
        metadata["device"] = "device,5137"
    elif which == "identity":
        metadata["identity"] = {
            "object-name": "different",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 5,
        }
    elif which == "unverified":
        metadata["source_identity_matches"] = False
    elif which == "static":
        files = files | {11: files[11].replace(b"saved", b"other")}
    elif which == "opaque":
        files = files | {
            3: gzip.compress(
                gzip.decompress(files[3]).replace(b"opaque footer", b"other footer"), mtime=0
            )
        }
    elif which == "third-name":
        files = files | {3: compile_point_name(files, edit_for(files, name="Third name"))[0]}
    else:
        files = files | {
            3: gzip.compress(
                gzip.decompress(files[3]).replace(b"controller/0-101", b"controller/0-999"), mtime=0
            )
        }
    request = current_source(storage, request, files, **metadata)
    parent = storage.receipt(request["receipt_id"])
    with pytest.raises(ValueError):
        service.prepare(request)
    assert storage.receipt(request["receipt_id"]) == parent


def changed_saved(files):
    old = struct.pack(">f", 3.5)
    new = struct.pack(">f", 17.25)
    return files | {
        12: files[12].replace(
            old + bytes([header_crc(old) ^ 255]), new + bytes([header_crc(new) ^ 255])
        )
    }


def test_other_current_saved_values_survive_while_already_previous_has_no_write_proposal(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    fresh = changed_saved(files)
    request = current_source(storage, request, fresh)
    report = service.prepare(request)
    proposal = {
        k: report["proposal"][k] for k in ("object_id", "record_ref", "encoded_sha256", "new_name")
    }
    restored, _ = compile_point_name(fresh, proposal)
    parsed = MoiIdentity(restored)
    assert parsed.reader.scalar(parsed.root, 900) == 17.25
    # Restore only the point name in the recorded application, preserving its
    # original merged image and the separately current saved File12.
    restored, _ = compile_point_name(files, edit_for(files, name="Authored input"))
    request = current_source(storage, request, fresh | {3: restored})
    already = service.prepare(request)
    assert (
        already["already_recorded"]
        and already["proposal"] is None
        and not already["new_review_required"]
    )


def test_prepare_http_is_token_admitted_local_and_strict(tmp_path):
    _, _, request, _, _ = setup(tmp_path)
    with TestClient(create_app(tmp_path)) as client:
        path = "/api/bacnet/controller/native-application/point-name/recovery/prepare"
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(path, json=request).status_code == 403
        result = client.post(path, headers=headers, json=request)
        assert result.status_code == 200, result.text
        assert result.json()["profile"] == PROFILE
        assert client.post(path, headers=headers, json=request | {"apply": True}).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]


async def test_real_new_point_name_recovery_transfers_and_retains_lineage(native_link):
    peer, _, _, service, target = native_link
    storage = service.storage
    _, plan = await name_review(native_link)
    original = await service.apply_point_name(**apply_args(plan))
    assert original["result"]["status"] == "verified"
    parent = original["intent"]["id"]
    parent_bytes = copy.deepcopy(storage.receipt(parent))
    capture = await service.capture(**target, operation_id="point-recovery-capture")
    request = {
        "receipt_id": parent,
        "capture_id": capture["id"],
        "snapshot_sha256": capture["snapshot_evidence_sha256"],
    }
    prepared = service.point_name_recovery.prepare(request)
    proposal = prepared["proposal"]
    peer.files = changed_saved(peer.files)
    reviewed = await service.preview_point_name(
        **target,
        **proposal,
        recovery_origin_sha256=prepared["origin_sha256"],
        operation_id="point-recovery-preview",
    )
    assert reviewed["recovery_origin"] == prepared["origin"]
    result = await service.apply_point_name(**apply_args(reviewed))
    assert result["result"]["status"] == "verified", result
    assert result["result"]["published_point_name"] == "Authored input"
    assert result["intent"]["recovery_origin_sha256"] == prepared["origin_sha256"]
    assert result["intent"]["recovery_origin"]["parent_receipt_id"] == parent
    actual = MoiIdentity(PointNameCompiler(peer.files).merged)
    assert actual.reader.scalar(actual.root, 900) == 17.25
    assert storage.receipt(parent) == parent_bytes
    writes = peer.events.count(("state", "start-restore"))
    restarted = NativeApplications(
        service.bacnet, service.store, service.instances, request_timeout=0.1, gap=0
    )
    readback = await restarted.reconcile(
        operation_id="point-recovery-readback", receipt_id=result["intent"]["id"]
    )
    assert readback["latest_readback"]["status"] == "verified"
    assert peer.events.count(("state", "start-restore")) == writes == 2
    assert storage.receipt(parent) == parent_bytes


def test_partial_preview_recovery_bindings_are_rejected():
    base = {
        "address": "127.0.0.1",
        "device": "device,5136",
        "capture_id": "a" * 32,
        "snapshot_sha256": "b" * 64,
        "operation_id": "point-preview",
        **edit_for(point_files()),
    }
    for patch in [{"recovery_parent_receipt": "c" * 32}, {"recovery_origin_sha256": "d" * 64}]:
        with pytest.raises(ValueError, match="both"):
            PointNamePreview(**base, **patch)


async def recovery_review(native_link):
    peer, _, _, service, target = native_link
    _, plan = await name_review(native_link)
    parent = await service.apply_point_name(**apply_args(plan))
    assert parent["result"]["status"] == "verified"
    capture = await service.capture(**target, operation_id="recovery-current-source")
    prepared = service.point_name_recovery.prepare(
        {
            "receipt_id": parent["intent"]["id"],
            "capture_id": capture["id"],
            "snapshot_sha256": capture["snapshot_evidence_sha256"],
        }
    )
    args = {
        **target,
        **prepared["proposal"],
        "recovery_origin_sha256": prepared["origin_sha256"],
        "operation_id": "recovery-guard-preview",
    }
    return peer, service, prepared, args


async def test_substituted_recovery_origin_refuses_before_controller_preview(native_link):
    peer, service, _, args = await recovery_review(native_link)
    events = copy.deepcopy(peer.events)
    with pytest.raises(ValueError, match="proposal changed"):
        await service.preview_point_name(**(args | {"recovery_origin_sha256": "0" * 64}))
    assert peer.events == events


async def test_parent_evidence_is_revalidated_before_a_new_durable_intent(native_link, monkeypatch):
    peer, service, _, args = await recovery_review(native_link)
    plan = await service.preview_point_name(**args)
    prepare = service.point_name_recovery.prepare

    def changed(request):
        report = prepare(request)
        return report | {"origin_sha256": "0" * 64}

    monkeypatch.setattr(service.point_name_recovery, "prepare", changed)
    count = peer.events.count(("state", "start-restore"))
    result = await service.apply_point_name(**apply_args(plan))
    assert result["result"]["status"] == "not_sent" and result["intent"] is None
    assert peer.events.count(("state", "start-restore")) == count == 1


async def test_uncertain_recovery_keeps_new_origin_and_reconciles_without_replay(native_link):
    peer, service, prepared, args = await recovery_review(native_link)
    plan = await service.preview_point_name(**args)
    peer.mode = "drop-end"
    result = await service.apply_point_name(**apply_args(plan))
    assert result["pending"] and result["result"]["may_have_applied"]
    assert result["intent"]["recovery_origin_sha256"] == prepared["origin_sha256"]
    receipt_id = result["intent"]["id"]
    before = service.storage.receipt(receipt_id)["result"]
    writes = peer.events.count(("state", "start-restore"))
    peer.mode = "normal"
    readback = await service.reconcile(
        operation_id="recovery-uncertain-readback", receipt_id=receipt_id
    )
    assert not readback["pending"] and readback["latest_readback"]["status"] == "verified"
    assert service.storage.receipt(receipt_id)["result"] == before
    assert peer.events.count(("state", "start-restore")) == writes == 2


@pytest.mark.parametrize("encoding", [0, 3, 4, 5])
def test_previous_unicode_name_keeps_its_original_character_encoding(tmp_path, encoding):
    _, service, request, _, files = setup(tmp_path, encoding=encoding, previous="Étage extérieur")
    report = service.prepare(request)
    assert report["previous_name"] == "Étage extérieur"
    edit = {
        k: report["proposal"][k] for k in ("object_id", "record_ref", "encoded_sha256", "new_name")
    }
    _, compilation = compile_point_name(files, edit)
    assert compilation["selected_edit"]["character_encoding"] == encoding


def test_archived_originals_and_current_capture_remain_eligible_after_restart(tmp_path):
    from bms_tool.native_backup_lifecycle import NativeBackupLifecycle

    storage, service, request, _, _ = setup(tmp_path)
    expected = service.prepare(request)
    for capture in storage.captures():
        NativeBackupLifecycle(storage).change(
            {
                "capture_id": capture["id"],
                "snapshot_sha256": capture["evidence_sha256"],
                "expected_revision": 0,
                "action": "archive",
            }
        )
    restarted = ApplicationStore(Store(tmp_path))
    assert not restarted.captures()
    assert NativePointNameRecovery(NativeBackupRecords(restarted)).prepare(request) == expected


def test_first_verified_historical_readback_survives_later_unknown_observation(tmp_path):
    storage, service, request, _, _ = setup(tmp_path, outcome="unknown")
    parent = request["receipt_id"]
    storage.resolve(parent, {"status": "verified", "published_point_name": "Changed input"})
    expected = service.prepare(request)
    assert expected["origin"]["verified_proof"]["kind"] == "readback-event"
    storage.resolve(
        parent, {"status": "unknown", "error": "authored later observation unavailable"}
    )
    assert service.prepare(request) == expected
