"""Identity text recovery proves original files without restoring a transfer."""

import copy
import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore, encoded
from bms_tool.native_applications import NativeApplications
from bms_tool.native_identity_text import (
    DOCUMENT_PROFILE,
    IMPORT_PROFILE,
    MAX_DOCUMENT,
    NativeIdentityText,
)
from bms_tool.storage import Store
from fastapi.testclient import TestClient

BASE = "/api/bacnet/controller/native-application/local-drafts/import"


@pytest.fixture(scope="module", params=["name", "instance"])
def source(tmp_path_factory, request):
    if request.param == "name":
        from .test_native_name_recovery import setup
    else:
        from .test_native_instance_recovery import setup
    path = tmp_path_factory.mktemp("identity-text-" + request.param)
    storage, _, options, *_ = setup(path)
    snapshot, files = storage.load(options["capture_id"])
    body = {
        "profile": DOCUMENT_PROFILE,
        "field_authority": False,
        "selection": {
            "connected_context": False,
            "interface_identity": '{"connected":false,"config":null,"epoch":7}',
            "address": "",
            "device": "",
            "router": None,
            "dnet": None,
            "change_kind": request.param,
        },
        "new_name": "  unfinished name 🌡  ",
        "new_instance_text": " 1e- ",
        "capture_id": snapshot["id"],
        "captured_target": {**snapshot["target"], "device": snapshot["device"]},
        "snapshot_sha256": snapshot["evidence_sha256"],
        "receipt_id": "a" * 32,
        "recovery_origin_sha256": "b" * 64,
    }
    return path, storage, snapshot, files, body


@pytest.fixture
def parts(source):
    path, storage, snapshot, files, body = source
    return path, storage, snapshot, files, copy.deepcopy(body)


def originals(storage):
    return {
        str(p.relative_to(storage.directory)): p.read_bytes()
        for p in storage.directory.rglob("*")
        if p.is_file()
    }


def test_exact_text_and_original_evidence_without_compilation_receipt_lookup_or_mutation(
    parts, monkeypatch
):
    _, storage, snapshot, _, body = parts
    before = originals(storage)
    receipts = storage.receipts(include_events=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Raw text must not compile or restore transfer/recovery authority")

    monkeypatch.setattr(storage, "intent", forbidden)
    monkeypatch.setattr(storage, "receipt", forbidden)
    monkeypatch.setattr(NativeApplications, "compile", forbidden)
    raw = json.dumps(body, ensure_ascii=False, indent=2).encode()
    result = NativeIdentityText(storage).import_document(raw)
    assert result["profile"] == IMPORT_PROFILE and result["document_profile"] == DOCUMENT_PROFILE
    assert result["document"] == body and result["file_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["local_source_verified"] is True
    proof = result["source_evidence_text"].encode()
    assert hashlib.sha256(proof).hexdigest() == body["snapshot_sha256"]
    assert json.loads(proof) == {k: v for k, v in snapshot.items() if k != "evidence_sha256"}
    for flag in (
        "field_authority",
        "controller_queries",
        "capture_mutations",
        "native_review_created",
        "recovery_prepared",
    ):
        assert result[flag] is False
    result["document"]["new_name"] = "changed"
    assert NativeIdentityText(storage).import_document(raw)["document"] == body
    assert originals(storage) == before
    monkeypatch.undo()
    assert storage.receipts(include_events=False) == receipts


@pytest.mark.parametrize(
    "case",
    [
        "profile",
        "authority",
        "numeric_false",
        "root_extra",
        "selection_extra",
        "connected",
        "kind",
        "interface_limit",
        "router",
        "dnet_bool",
        "dnet_float",
        "name_type",
        "name_limit",
        "number_type",
        "number_limit",
        "capture_id",
        "snapshot_shape",
        "snapshot_mismatch",
        "target_missing",
        "target_extra",
        "target_mismatch",
        "target_device",
        "receipt",
        "recovery",
        "raw_metadata",
        "raw_hash",
        "raw_filename",
    ],
)
def test_unknown_shapes_and_source_mismatch_are_refused_without_altering_files(parts, case):
    _, storage, _, _, body = parts
    before = originals(storage)
    if case == "profile":
        body["profile"] = "native-controller-instance-recovery-draft/1"
    elif case == "authority":
        body["field_authority"] = True
    elif case == "numeric_false":
        body["field_authority"] = 0
    elif case == "root_extra":
        body["token"] = "never-authorized"
    elif case == "selection_extra":
        body["selection"]["authority"] = True
    elif case == "connected":
        body["selection"]["connected_context"] = 1
    elif case == "kind":
        body["selection"]["change_kind"] = []
    elif case == "interface_limit":
        body["selection"]["interface_identity"] = "x" * 16385
    elif case == "router":
        body["selection"]["router"] = 5
    elif case == "dnet_bool":
        body["selection"]["dnet"] = True
    elif case == "dnet_float":
        body["selection"]["dnet"] = 1.5
    elif case == "name_type":
        body["new_name"] = None
    elif case == "name_limit":
        body["new_name"] = "🌡" * 65
    elif case == "number_type":
        body["new_instance_text"] = 42
    elif case == "number_limit":
        body["new_instance_text"] = "0" * 65537
    elif case == "capture_id":
        body["capture_id"] = "../file"
    elif case == "snapshot_shape":
        body["snapshot_sha256"] = None
    elif case == "snapshot_mismatch":
        body["snapshot_sha256"] = "f" * 64
    elif case == "target_missing":
        body["captured_target"] = None
    elif case == "target_extra":
        body["captured_target"]["write"] = True
    elif case == "target_mismatch":
        body["captured_target"]["address"] = "3001:9"
    elif case == "target_device":
        body["captured_target"]["device"] = "device,99"
    elif case == "receipt":
        body["receipt_id"] = "unknown"
    elif case == "recovery":
        body["recovery_origin_sha256"] = "g" * 64
    elif case == "raw_metadata":
        body["raw_imported"] = {"filename": "old.json", "file_sha256": "a" * 64, "plan": True}
    elif case == "raw_hash":
        body["raw_imported"] = {"filename": "old.json", "file_sha256": None}
    elif case == "raw_filename":
        body["raw_imported"] = {"filename": "x" * 1025, "file_sha256": "a" * 64}
    with pytest.raises(ValueError):
        NativeIdentityText(storage).import_document(encoded(body))
    assert originals(storage) == before


@pytest.mark.parametrize(
    "raw",
    [
        b'{"profile":1,"profile":2}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b'{"x":1e-999}',
        b"\xff",
        b'{"x":"\\ud800"}',
        b"[" * 65 + b"0" + b"]" * 65,
    ],
)
def test_strict_json_unicode_and_structure_limits(parts, raw):
    with pytest.raises(ValueError):
        NativeIdentityText(parts[1]).import_document(raw)


def test_old_bare_target_raw_provenance_and_empty_fields_remain_unreviewed(parts):
    _, storage, snapshot, _, body = parts
    body.update(
        captured_target=snapshot["target"],
        new_name="",
        new_instance_text="",
        raw_imported={"filename": "older.json", "file_sha256": "c" * 64},
    )
    assert NativeIdentityText(storage).import_document(encoded(body))["document"] == body
    body.update(capture_id=None, captured_target=None, snapshot_sha256=None)
    result = NativeIdentityText(storage).import_document(encoded(body))
    assert result["source_evidence_text"] is None and result["local_source_verified"] is False
    assert result["document"] == body
    body["captured_target"] = snapshot["target"]
    with pytest.raises(ValueError, match="incomplete"):
        NativeIdentityText(storage).import_document(encoded(body))


def test_maximum_ascii_fields_fit_and_oversize_never_truncates(parts):
    _, storage, _, _, body = parts
    body["new_name"] = "a" * 128
    body["new_instance_text"] = "0" * 65536
    body["selection"]["interface_identity"] = "x" * 16384
    raw = encoded(body)
    assert len(raw) < MAX_DOCUMENT
    assert NativeIdentityText(storage).import_document(raw)["document"] == body
    with pytest.raises(ValueError, match="byte bound"):
        NativeIdentityText(storage).import_document(b" " * (MAX_DOCUMENT + 1))


def test_corrupt_original_file_is_not_replaced_with_reference_metadata(parts, tmp_path):
    _, _, snapshot, files, body = parts
    storage = ApplicationStore(Store(tmp_path))
    copy_snapshot = storage.save(
        {
            k: v
            for k, v in snapshot.items()
            if k not in {"id", "files", "evidence_sha256", "captured_at"}
        },
        files,
    )
    body.update(capture_id=copy_snapshot["id"], snapshot_sha256=copy_snapshot["evidence_sha256"])
    original = storage.directory / copy_snapshot["id"] / "file-3.bin"
    original.write_bytes(original.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        NativeIdentityText(storage).import_document(encoded(body))


def test_routed_and_archived_originals_remain_exact_local_sources(parts, tmp_path):
    from bms_tool.native_backup_lifecycle import NativeBackupLifecycle

    _, _, snapshot, files, body = parts
    storage = ApplicationStore(Store(tmp_path))
    metadata = {
        k: v
        for k, v in snapshot.items()
        if k not in {"id", "files", "evidence_sha256", "captured_at"}
    }
    metadata["target"] = {"address": "3001:7", "router": "192.0.2.5", "dnet": 3001}
    routed = storage.save(metadata, files)
    NativeBackupLifecycle(storage).change(
        {
            "capture_id": routed["id"],
            "snapshot_sha256": routed["evidence_sha256"],
            "expected_revision": 0,
            "action": "archive",
        }
    )
    body.update(
        capture_id=routed["id"],
        snapshot_sha256=routed["evidence_sha256"],
        captured_target={**routed["target"], "device": routed["device"]},
    )
    before = originals(storage)
    result = NativeIdentityText(storage).import_document(encoded(body))
    assert (
        result["local_source_verified"]
        and result["document"]["captured_target"] == body["captured_target"]
    )
    assert (
        hashlib.sha256(result["source_evidence_text"].encode()).hexdigest()
        == routed["evidence_sha256"]
    )
    assert originals(storage) == before and storage.captures() == []


def test_real_local_http_requires_token_keeps_originals_and_interface_closed(parts):
    path, _, _, _, body = parts
    with TestClient(create_app(path)) as client:
        storage = client.app.state.native_applications.storage
        before = originals(storage)
        raw = encoded(body)
        assert client.post(BASE, files={"file": ("raw.json", raw)}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(BASE, headers=headers, files={"file": ("raw.json", raw)})
        assert response.status_code == 200, response.text
        assert response.json()["document"] == body
        assert (
            client.post(BASE, headers=headers, files={"file": ("bad.json", b"{}")}).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]
        assert originals(storage) == before
