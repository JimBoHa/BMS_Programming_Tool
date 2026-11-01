"""Retained native archives remain inspectable without a connection or compiler."""

import hashlib
import types

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_signal_compiler import SignalCompilerService
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_signal_compiler import retained, signal_files

BASE = "/api/bacnet/controller/native-application/inspection"


def setup(tmp_path, *, unrecognized=False, unverified=False):
    storage = ApplicationStore(Store(tmp_path))
    files = signal_files()
    if unrecognized:
        files[11], files[12] = b"Unknown saved schema", b"Opaque saved values"
    capture = retained(
        storage,
        files,
        source_identity_matches=not unverified,
        source_identity_error="Authored acquisition mismatch" if unverified else None,
    )
    request = {"capture_id": capture["id"], "snapshot_sha256": capture["evidence_sha256"]}
    return storage, NativeBackupRecords(storage), request, files


@pytest.mark.parametrize("unrecognized", [False, True])
@pytest.mark.parametrize("unverified", [False, True])
def test_archive_inspection_is_independent_of_saved_schema_and_device_identity(
    tmp_path, unrecognized, unverified
):
    storage, service, request, files = setup(
        tmp_path, unrecognized=unrecognized, unverified=unverified
    )
    source = service.source(request)
    assert source["profile"] == "native-backup-record-inspection/1"
    assert source["sha256"] == hashlib.sha256(files[3]).hexdigest()
    assert source["snapshot_sha256"] == request["snapshot_sha256"]
    assert source["source_identity_matches"] is (not unverified)
    assert source["read_only"] and not source["controller_queries"] and not source["field_actions"]
    rows = service.records(request)
    assert rows["recognized_record_count"] == len(rows["records"]) == 9
    record = next(row for row in rows["records"] if row["ref"] == "controller")
    detail = service.records(request | {"record_id": record["id"], "query": "902"}, detail=True)
    assert detail["properties"][0]["scalar"] == {"datatype": "Integer", "value": -1}
    assert detail["sha256"] == source["sha256"]
    if unverified or unrecognized:
        with pytest.raises(ValueError):
            SignalCompilerService(storage).source(request["capture_id"])
    assert storage.load(request["capture_id"])[1] == files


@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_any_substituted_snapshot_file_prevents_inspection(tmp_path, file_id):
    storage, service, request, _ = setup(tmp_path)
    (storage.directory / request["capture_id"] / f"file-{file_id}.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        service.source(request)


def test_stale_manifest_and_redirected_capture_are_refused(tmp_path):
    storage, service, request, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="evidence changed"):
        service.records(request | {"snapshot_sha256": "0" * 64})
    folder = storage.directory / request["capture_id"]
    other = folder.with_name("owned-source-folder")
    folder.rename(other)
    folder.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="original storage folder"):
        service.source(request)


def test_http_inspection_is_token_guarded_local_and_returns_original_archive_values(tmp_path):
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    snapshot = retained(storage)
    body = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    with TestClient(app) as c:
        headers = {"X-Studio-Token": c.get("/api/session").json()["token"]}
        assert c.post(BASE + "/source", json=body).status_code == 403
        source = c.post(BASE + "/source", headers=headers, json=body)
        assert source.status_code == 200, source.text
        rows = c.post(BASE + "/records", headers=headers, json=body).json()
        root = next(row for row in rows["records"] if row["ref"] == "controller")
        detail = c.post(
            BASE + "/record", headers=headers, json=body | {"record_id": root["id"], "query": "900"}
        ).json()
        assert detail["properties"][0]["scalar"] == {"datatype": "Real", "value": 1.25}
        assert (
            detail["read_only"] and not detail["controller_queries"] and not detail["field_actions"]
        )
        assert not c.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize(
    "changes",
    [
        {"query": "x" * 257},
        {"limit": 129},
        {"offset": True},
        {"offset": -1},
        {"record_id": "../bad"},
        {"address": "127.0.0.1:1"},
    ],
)
def test_http_requests_reject_extra_target_and_invalid_pages(tmp_path, changes):
    app = create_app(tmp_path)
    snap = retained(app.state.native_applications.storage)
    body = {"capture_id": snap["id"], "snapshot_sha256": snap["evidence_sha256"]}
    with TestClient(app) as c:
        headers = {"X-Studio-Token": c.get("/api/session").json()["token"]}
        path = "/record" if "record_id" in changes else "/records"
        assert c.post(BASE + path, headers=headers, json=body | changes).status_code == 422
        assert not c.get("/api/session").json()["field_network_open"]


async def test_actual_native_backup_can_be_inspected_after_disconnect_without_any_wire_requests(
    native_link,
):
    peer, bacnet, _, native, target = native_link
    peer.files = signal_files()
    observed = []
    original = peer.indication

    async def watch(self, apdu):
        observed.append(type(apdu).__name__)
        await original(apdu)

    peer.indication = types.MethodType(watch, peer)
    captured = await native.capture(**target, operation_id="capture-for-archive-inspection")
    assert "ReinitializeDeviceRequest" in observed and "AtomicReadFileRequest" in observed
    snapshot, _ = native.storage.load(captured["id"])
    await bacnet.disconnect()
    before = list(observed)
    service = NativeBackupRecords(native.storage)
    body = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    source = service.source(body)
    records = service.records(body)
    for row in records["records"]:
        service.records(body | {"record_id": row["id"]}, detail=True)
    assert (
        source["application"]["record_count"] == 8
        and source["application"]["metadata_records"] == 1
    )
    assert observed == before
    assert not native.storage.receipts()
