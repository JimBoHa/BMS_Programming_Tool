"""Strict Boolean recovery reads local evidence and preserves previous effective values."""

import copy
import gzip
import secrets
import struct

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_effective_boolean import EffectiveBooleanCompiler
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_boolean_compiler import EffectiveBooleanService
from bms_tool.native_boolean_recovery import NativeBooleanRecovery
from bms_tool.native_boolean_transfer import PROFILE as TRANSFER_PROFILE
from bms_tool.native_boolean_transfer import compile_boolean_default
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_boolean_compiler import query
from .test_native_boolean_copies import FIRST, SECOND, boolean_files
from .test_native_boolean_transfer import boolean_slot
from .test_native_default_transfer import real_slot
from .test_native_signal_compiler import retained

BASE = "/api/bacnet/controller/native-application/boolean-default/recovery/prepare"


def setup(tmp_path, *, ref=FIRST, outcome="verified", possible=True, change=None, compressed=True):
    storage = ApplicationStore(Store(tmp_path))
    files = boolean_files(compressed=compressed)
    identity = {
        "device": "device,5136",
        "object-name": "Authored controller",
        "model-name": "UNLISTED-MODEL",
        "vendor-identifier": 5,
    }
    before = retained(storage, files, identity=identity)
    source = EffectiveBooleanService(NativeBackupRecords(storage)).source(
        {"capture_id": before["id"], "snapshot_sha256": before["evidence_sha256"]}
    )
    value = not next(row["effective_value"] for row in source["fields"] if row["ref"] == ref)
    edit = {
        k: v
        for k, v in query(source, ref=ref, value=value).items()
        if k in {"record_ref", "encoded_sha256", "value"}
    }
    output, compilation = compile_boolean_default(files, edit)
    body = {
        "id": secrets.token_hex(16),
        "target": before["target"],
        "identity": identity,
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": identity["object-name"],
        "new_name": identity["object-name"],
        "change_kind": "boolean-default",
        "operation_profile": TRANSFER_PROFILE,
        "backup_id": before["id"],
        "default_edit": edit,
        "compilation": compilation,
        "payload_sha256": sha(output),
        "native_payload_sha256": sha(MoiIdentity(output).data),
    }
    if change:
        change(body)
    intent = storage.intent(body)
    if outcome != "intent-only":
        storage.finish(
            intent["id"],
            {
                "intent_sha256": intent["evidence_sha256"],
                "status": outcome,
                "may_have_applied": possible,
            },
        )
    current_files = {**files, 3: output}
    boolean_slot(current_files, ref, value)
    current = retained(storage, current_files, identity=identity)
    request = {
        "receipt_id": intent["id"],
        "capture_id": current["id"],
        "snapshot_sha256": current["evidence_sha256"],
    }
    return (
        storage,
        NativeBooleanRecovery(NativeBackupRecords(storage)),
        request,
        before,
        current_files,
    )


def current_source(storage, request, files, **metadata):
    old = storage.load(request["capture_id"])[0]
    metadata.setdefault("identity", old["identity"])
    metadata.setdefault("target", old["target"])
    source = retained(storage, files, **metadata)
    return {**request, "capture_id": source["id"], "snapshot_sha256": source["evidence_sha256"]}


@pytest.mark.parametrize("ref,previous,after", [(FIRST, True, False), (SECOND, False, True)])
@pytest.mark.parametrize("compressed", [False, True])
def test_previous_effective_boolean_and_literal_tags_remain_strict_local_evidence(
    tmp_path, ref, previous, after, compressed
):
    storage, service, request, before, files = setup(tmp_path, ref=ref, compressed=compressed)
    original = storage.receipt(request["receipt_id"])
    report = service.prepare(request)
    assert report["profile"] == "native-boolean-default-recovery-draft/1"
    assert (
        report["previous_effective_value"] is previous and report["recorded_after_value"] is after
    )
    assert report["proposal"]["value"] is previous
    assert report["proposal"]["record_ref"] == ref
    assert report["proposal"]["source_sha256"] == sha(files[3])
    assert report["origin"]["previous_tag"] == ("11" if previous else "10")
    assert report["origin"]["recorded_after_tag"] == ("11" if after else "10")
    assert report["read_only"] and report["new_review_required"]
    assert (
        not report["can_apply"] and not report["controller_queries"] and not report["field_actions"]
    )
    assert storage.receipt(request["receipt_id"]) == original and len(storage.receipts()) == 1
    assert storage.load(request["capture_id"])[1] == files
    archived = EffectiveBooleanCompiler(storage.load(before["id"])[1]).fields()
    assert next(row["archive_value"] for row in archived if row["ref"] == ref) is after


def test_other_current_saved_values_survive_the_new_local_compilation(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    boolean_slot(files, SECOND, True)
    real_slot(files, 4, struct.pack(">f", 9.25))
    request = current_source(storage, request, files)
    proposal = service.prepare(request)["proposal"]
    output, compiled = compile_boolean_default(
        files, {k: proposal[k] for k in ("record_ref", "encoded_sha256", "value")}
    )
    image = MoiIdentity(output)
    assert image.reader.scalar(image.root, 900) == 9.25
    assert image.reader.scalar(image.reader.records[SECOND], 3113) is True
    assert image.reader.scalar(image.reader.records[FIRST], 3113) is True
    assert compiled["selected_edit"]["before_tag"] == "10"
    assert compiled["selected_edit"]["after_tag"] == "11"


def test_already_recorded_prior_boolean_creates_no_transfer_or_live_claim(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    boolean_slot(files, FIRST, True)
    report = service.prepare(current_source(storage, request, files))
    assert report["already_recorded"] and report["proposal"] is None
    assert not report["new_review_required"] and not report["controller_queries"]


def test_recompressed_container_keeps_the_original_expanded_application_binding(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    files[3] = gzip.compress(MoiIdentity(files[3]).data, mtime=123)
    assert service.prepare(current_source(storage, request, files))["proposal"]["value"] is True


@pytest.mark.parametrize(
    "change", ["route", "device", "identity", "unverified", "directory", "application", "saved-2"]
)
def test_changed_or_unqualified_current_boolean_source_refuses(tmp_path, change):
    storage, service, request, _, files = setup(tmp_path)
    metadata = {}
    if change == "route":
        metadata["target"] = {"address": "3001:8", "router": "127.0.0.1:49000", "dnet": 3001}
    elif change == "device":
        metadata["device"] = "device,5137"
    elif change == "identity":
        metadata["identity"] = {
            "object-name": "Other",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 5,
        }
    elif change == "unverified":
        metadata["source_identity_matches"] = False
    elif change == "directory":
        files[11] = b"unknown saved directory"
    elif change == "application":
        files[3] = gzip.compress(
            MoiIdentity(files[3]).data.replace(b"opaque footer", b"unsafe footer"), mtime=0
        )
    else:
        boolean_slot(files, FIRST, 2)
    with pytest.raises(ValueError):
        service.prepare(current_source(storage, request, files, **metadata))


@pytest.mark.parametrize("outcome", ["unknown", "intent-only"])
def test_uncertain_original_requires_explicit_verified_reconciliation(tmp_path, outcome):
    storage, service, request, _, _ = setup(tmp_path, outcome=outcome)
    before = storage.receipt(request["receipt_id"], include_events=False)["result"]
    with pytest.raises(ValueError, match="Reconcile"):
        service.prepare(request)
    storage.resolve(request["receipt_id"], {"status": "verified"})
    first = service.prepare(request)
    storage.event(request["receipt_id"], "readback", {"status": "unresolved"})
    second = service.prepare(request)
    assert first["origin"]["verified_proof"] == second["origin"]["verified_proof"]
    assert second["origin"]["verified_proof"]["kind"] == "readback-event"
    assert storage.receipt(request["receipt_id"], include_events=False)["result"] == before


def test_no_dispatch_refusal_is_not_rewritten_by_a_later_matching_readback(tmp_path):
    storage, service, request, _, _ = setup(tmp_path, outcome="not_sent", possible=False)
    storage.resolve(request["receipt_id"], {"status": "verified"})
    with pytest.raises(ValueError, match="no possible"):
        service.prepare(request)


@pytest.mark.parametrize(
    "change",
    [
        "kind",
        "operation",
        "name",
        "instance",
        "edit-0",
        "edit-1",
        "before-1",
        "after-0",
        "tag",
        "payload",
    ],
)
def test_unsupported_and_numeric_boolean_aliases_cannot_qualify_original_intent(tmp_path, change):
    def mutate(body):
        if change == "kind":
            body["change_kind"] = "signal-default"
        elif change == "operation":
            body["operation_profile"] = "unknown"
        elif change == "name":
            body["new_name"] = "Other"
        elif change == "instance":
            body["new_instance"] = 5137
        elif change == "edit-0":
            body["default_edit"]["value"] = 0
        elif change == "edit-1":
            body["default_edit"]["value"] = 1
        elif change == "before-1":
            body["compilation"]["selected_edit"]["before_value"] = 1
        elif change == "after-0":
            body["compilation"]["selected_edit"]["after_value"] = 0
        elif change == "tag":
            body["compilation"]["selected_edit"]["before_tag"] = "10"
        else:
            body["native_payload_sha256"] = "0" * 64

    _, service, request, _, _ = setup(tmp_path, change=mutate)
    with pytest.raises(ValueError):
        service.prepare(request)


@pytest.mark.parametrize("side", ["original", "current"])
@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_original_and_current_file_integrity_remains_required(tmp_path, side, file_id):
    storage, service, request, before, _ = setup(tmp_path)
    capture = before["id"] if side == "original" else request["capture_id"]
    (storage.directory / capture / f"file-{file_id}.bin").write_bytes(b"Tampered")
    with pytest.raises(ValueError, match="integrity"):
        service.prepare(request)


def test_token_admitted_http_prepare_opens_no_interface_and_creates_no_intent(tmp_path):
    storage, _, request, _, _ = setup(tmp_path)
    original = copy.deepcopy(storage.receipt(request["receipt_id"]))
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(BASE, json=request).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        result = client.post(BASE, json=request, headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["proposal"]["value"] is True
        for change in [
            {"receipt_id": "bad"},
            {"snapshot_sha256": "bad"},
            {"operation_id": "not-a-field-action"},
        ]:
            assert client.post(BASE, json=request | change, headers=headers).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]
    assert storage.receipt(request["receipt_id"]) == original and len(storage.receipts()) == 1
