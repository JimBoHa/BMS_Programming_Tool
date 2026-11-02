"""Local previous Enum proposals preserve numeric evidence, state context and originals."""

import copy
import gzip
import secrets
import struct

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_enum_compiler import EffectiveEnumService
from bms_tool.native_enum_recovery import NativeEnumRecovery
from bms_tool.native_enum_transfer import PROFILE as TRANSFER_PROFILE
from bms_tool.native_enum_transfer import compile_enum_default
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_moi_effective_enum import enum_files
from .test_moi_enum_defaults import REF
from .test_native_default_transfer import real_slot
from .test_native_enum_compiler import proposal
from .test_native_enum_transfer import add_enum_states_slot, enum_slot, enum_states_slot
from .test_native_signal_compiler import retained

BASE = "/api/bacnet/controller/native-application/enum-default/recovery/prepare"


def setup(
    path,
    *,
    cid=528,
    previous=513,
    after=65535,
    compressed=True,
    outcome="verified",
    possible=True,
    change=None,
    states_slot=False,
):
    storage = ApplicationStore(Store(path))
    files = enum_files(cid=cid, compressed=compressed, saved=previous)
    if states_slot:
        add_enum_states_slot(files, cid=cid)
    identity = {
        "device": "device,5136",
        "object-name": "Authored controller",
        "model-name": "UNLISTED-MODEL",
        "vendor-identifier": 5,
    }
    before = retained(storage, files, identity=identity)
    source = EffectiveEnumService(NativeBackupRecords(storage)).source(
        {"capture_id": before["id"], "snapshot_sha256": before["evidence_sha256"]}
    )
    edit = {
        k: v
        for k, v in proposal(source, after).items()
        if k in {"record_ref", "encoded_sha256", "value"}
    }
    output, compilation = compile_enum_default(files, edit)
    body = {
        "id": secrets.token_hex(16),
        "target": before["target"],
        "identity": identity,
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": identity["object-name"],
        "new_name": identity["object-name"],
        "change_kind": "enum-default",
        "operation_profile": TRANSFER_PROFILE,
        "enum_semantics_verified": False,
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
    current_files = files | {3: output}
    enum_slot(current_files, after)
    current = retained(storage, current_files, identity=identity)
    request = {
        "receipt_id": intent["id"],
        "capture_id": current["id"],
        "snapshot_sha256": current["evidence_sha256"],
    }
    return storage, NativeEnumRecovery(NativeBackupRecords(storage)), request, before, current_files


def current_source(storage, request, files, **metadata):
    original = storage.load(request["capture_id"])[0]
    metadata.setdefault("identity", original["identity"])
    metadata.setdefault("target", original["target"])
    source = retained(storage, files, **metadata)
    return request | {"capture_id": source["id"], "snapshot_sha256": source["evidence_sha256"]}


@pytest.mark.parametrize("cid", [528, 529])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("previous,after", [(0, 65535), (513, 65535), (65535, 0)])
def test_previous_enum_code_and_literal_encodings_remain_local_source_evidence(
    tmp_path, cid, compressed, previous, after
):
    storage, service, request, _, files = setup(
        tmp_path, cid=cid, compressed=compressed, previous=previous, after=after
    )
    original = copy.deepcopy(storage.receipt(request["receipt_id"]))
    report = service.prepare(request)
    origin = report["origin"]
    assert report["profile"] == "native-enum-default-recovery-draft/1"
    assert (
        report["previous_effective_value"] == previous and report["recorded_after_value"] == after
    )
    assert type(report["proposal"]["value"]) is int and report["proposal"]["value"] == previous
    assert origin["class_id"] == cid and origin["record_ref"] == REF
    assert origin["saved_storage"]["bytes"] == 2 and origin["states_text_encoded_sha256"]
    assert not origin["enum_semantics_verified"] and not report["enum_semantics_verified"]
    if previous == 0:
        assert (
            origin["previous_encoding_hex"] == "91002f"
            and origin["proposal_encoding_hex"] == "9200002f"
        )
    if after == 0:
        assert (
            origin["recorded_after_encoding_hex"] == "9200002f"
            and origin["current_encoding_hex"] == "91002f"
        )
    assert report["read_only"] and report["new_review_required"] and not report["can_apply"]
    assert not report["controller_queries"] and not report["field_actions"]
    assert (
        storage.receipt(request["receipt_id"]) == original
        and storage.load(request["capture_id"])[1] == files
    )
    restarted = NativeEnumRecovery(NativeBackupRecords(ApplicationStore(Store(tmp_path))))
    assert restarted.prepare(request) == report


def test_previous_enum_compilation_preserves_other_current_saved_values(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    real_slot(files, 4, struct.pack(">f", 9.25))
    request = current_source(storage, request, files)
    proposal = service.prepare(request)["proposal"]
    output, _ = compile_enum_default(
        files, {k: proposal[k] for k in ("record_ref", "encoded_sha256", "value")}
    )
    image = MoiIdentity(output)
    assert (
        image.reader.scalar(image.root, 900) == 9.25
        and image.reader.scalar(image.reader.records[REF], 3113) == 513
    )


def test_already_previous_enum_code_creates_no_field_proposal(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    enum_slot(files, 513)
    report = service.prepare(current_source(storage, request, files))
    assert (
        report["already_recorded"]
        and report["proposal"] is None
        and not report["new_review_required"]
    )
    assert not report["controller_queries"] and not report["can_apply"]


@pytest.mark.parametrize(
    "change",
    [
        "route",
        "device",
        "identity",
        "unverified",
        "directory",
        "application",
        "third-code",
        "state-metadata",
        "bad-crc",
    ],
)
def test_changed_or_unqualified_current_enum_source_refuses_previous_code(tmp_path, change):
    storage, service, request, _, files = setup(tmp_path, states_slot=change == "state-metadata")
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
        files[11] = b"Unknown directory"
    elif change == "application":
        files[3] = gzip.compress(
            MoiIdentity(files[3]).data.replace(b"opaque footer", b"unsafe footer"), mtime=0
        )
    elif change == "third-code":
        enum_slot(files, 42)
    elif change == "state-metadata":
        enum_states_slot(files, 292)
    else:
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    with pytest.raises(ValueError):
        service.prepare(current_source(storage, request, files, **metadata))


@pytest.mark.parametrize("outcome", ["unknown", "intent-only"])
def test_uncertain_enum_parent_requires_verified_reconciliation_and_preserves_first_proof(
    tmp_path, outcome
):
    storage, service, request, _, _ = setup(tmp_path, outcome=outcome)
    before = storage.receipt(request["receipt_id"], include_events=False)["result"]
    with pytest.raises(ValueError, match="Reconcile"):
        service.prepare(request)
    storage.resolve(request["receipt_id"], {"status": "verified"})
    first = service.prepare(request)
    storage.event(request["receipt_id"], "readback", {"status": "unresolved"})
    second = service.prepare(request)
    assert first["origin"]["verified_proof"] == second["origin"]["verified_proof"]
    assert first["origin"]["verified_proof"]["kind"] == "readback-event"
    assert storage.receipt(request["receipt_id"], include_events=False)["result"] == before


def test_no_dispatch_enum_refusal_cannot_gain_recovery_from_later_readback(tmp_path):
    storage, service, request, _, _ = setup(tmp_path, outcome="not_sent", possible=False)
    storage.resolve(request["receipt_id"], {"status": "verified"})
    with pytest.raises(ValueError, match="no possible"):
        service.prepare(request)


@pytest.mark.parametrize(
    "fault",
    [
        "kind",
        "profile",
        "name",
        "instance",
        "boolean-code",
        "float-code",
        "state-binding",
        "missing-state-binding",
        "storage",
        "payload",
    ],
)
def test_inconsistent_parent_enum_evidence_cannot_prepare_a_previous_value(tmp_path, fault):
    def change(body):
        if fault == "kind":
            body["change_kind"] = "boolean-default"
        elif fault == "profile":
            body["operation_profile"] = "future/99"
        elif fault == "name":
            body["new_name"] = "Other"
        elif fault == "instance":
            body["new_instance"] = 5336
        elif fault == "boolean-code":
            body["compilation"]["selected_edit"]["before_value"] = True
        elif fault == "float-code":
            body["compilation"]["selected_edit"]["before_value"] = 513.0
        elif fault == "state-binding":
            body["compilation"]["states_text_encoded_sha256"] = "0" * 64
        elif fault == "missing-state-binding":
            body["compilation"].pop("states_text_encoded_sha256")
        elif fault == "storage":
            body["compilation"]["saved_storage"]["bytes"] = 4
        else:
            body["native_payload_sha256"] = "0" * 64

    _, service, request, _, _ = setup(tmp_path, change=change)
    with pytest.raises(ValueError):
        service.prepare(request)


@pytest.mark.parametrize("key", [3, 11, 12])
def test_changed_original_enum_backup_cannot_reconstruct_a_previous_value(tmp_path, key):
    storage, service, request, before, _ = setup(tmp_path)
    (storage.directory / before["id"] / f"file-{key}.bin").write_bytes(b"Changed original")
    with pytest.raises(ValueError):
        service.prepare(request)


def test_local_enum_recovery_http_never_queries_a_controller_or_restores_authority(
    tmp_path, monkeypatch
):
    storage, service, request, _, _ = setup(tmp_path)
    expected = service.prepare(request)
    original = copy.deepcopy(storage.receipt(request["receipt_id"]))
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Local Enum recovery queried a field interface")

    for method in ("require", "connect", "disconnect", "_read", "release"):
        monkeypatch.setattr(app.state.bacnet, method, forbidden)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE, json=request).status_code == 403
        response = client.post(BASE, json=request, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == expected
        assert client.post(BASE, json=request | {"apply": True}, headers=headers).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]
    assert storage.receipt(request["receipt_id"]) == original and len(storage.receipts()) == 1
