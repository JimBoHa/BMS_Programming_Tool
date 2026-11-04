"""Immutable retained native archives support strict local connection-copy APIs."""

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_connection_copies import MoiConnectionCopies
from bms_tool.moi_identity import sha
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_connection_copies import NativeConnectionCopies, native_connection_router
from bms_tool.storage import Store
from fastapi.testclient import TestClient
from pydantic import ValidationError

from .test_moi_connection_copies import authored
from .test_moi_wire_sources import REF, A, D
from .test_native_signal_compiler import retained

BASE = "/api/bacnet/controller/native-application/inspection/connection-copy"


def setup(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    files = {
        3: authored(),
        11: b"Unknown saved selector schema",
        12: b"Opaque original saved values",
    }
    snapshot = retained(
        storage,
        files,
        identity={
            "object-name": "Authored native connection controller",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 5,
        },
    )
    record = MoiConnectionCopies(files[3]).wire.reader.records[REF]
    body = {
        "capture_id": snapshot["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
        "source_sha256": sha(files[3]),
        "diagram_ref": REF,
        "record_sha256": record["sha256"],
        "prototype_index": 0,
        "source_ref": None,
    }
    return storage, NativeConnectionCopies(NativeBackupRecords(storage)), files, body


def proposal(service, body):
    s = service.source(body)["selection"]
    return {
        **body,
        "source_ref": A,
        "target_ref": D,
        "property_sha256": s["property_sha256"],
        "metadata_property_sha256": s["metadata_property_sha256"],
        "prototype_old": s["prototype"]["old"],
        "connection_count": s["connection_count"],
    }


def filesystem(path):
    return {
        str(p.relative_to(path)): (sha(p.read_bytes()), p.stat().st_mode)
        for p in path.rglob("*")
        if p.is_file()
    }


def test_actual_raw_archive_and_unknown_saved_schema_remain_immutable_without_field_authority(
    tmp_path,
):
    storage, service, files, body = setup(tmp_path)
    before = filesystem(storage.directory)
    data = service.source(body)
    assert data["read_only"] and not data["controller_queries"] and not data["field_actions"]
    assert (
        not data["identity_verified"]
        and not data["field_transfer_enabled"]
        and not data["can_apply"]
        and not data["saved_settings_merged"]
    )
    assert data["selection"]["available"] and data["selection"]["targets"][0]["ref"] == D
    request = proposal(service, body)
    out, review = service.preview(request)
    assert service.export({**request, "review_sha256": review["review_sha256"]}) == (out, review)
    assert review["compilation"]["new"] == [0, 85, 3, 7000] and review["output_sha256"] == sha(out)
    assert storage.load(body["capture_id"])[1] == files and filesystem(storage.directory) == before
    assert not storage.receipts() and not review["controller_write"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("source_sha256", "0" * 64),
        ("record_sha256", "0" * 64),
        ("property_sha256", "0" * 64),
        ("metadata_property_sha256", "0" * 64),
        ("snapshot_sha256", "0" * 64),
        ("source_ref", D),
        ("target_ref", A),
        ("prototype_index", 1),
        ("prototype_old", [1, 85, 2, 7000]),
        ("connection_count", 2),
        ("review_sha256", "0" * 64),
    ],
)
def test_original_review_cannot_be_reused_for_another_archive_or_proposal(tmp_path, key, value):
    storage, service, _, body = setup(tmp_path)
    request = proposal(service, body)
    _, review = service.preview(request)
    request.update(review_sha256=review["review_sha256"])
    request[key] = value
    before = filesystem(storage.directory)
    with pytest.raises((ValueError, ValidationError)):
        service.export(request)
    assert filesystem(storage.directory) == before and not storage.receipts()


@pytest.mark.parametrize(
    "key,value",
    [
        ("prototype_index", True),
        ("connection_count", True),
        ("source_ref", 42),
        ("target_ref", ""),
        ("prototype_old", [False, 85, 2, 7000]),
        ("metadata_property_sha256", False),
        ("can_apply", True),
    ],
)
def test_exact_types_and_extra_field_refusal_survive_the_local_api(tmp_path, key, value):
    _, service, _, body = setup(tmp_path)
    request = proposal(service, body)
    request[key] = value
    with pytest.raises(ValidationError):
        service.preview(request)


def test_local_http_requires_token_and_binds_actual_export_to_source_review_and_compilation(
    tmp_path,
):
    storage, service, _, body = setup(tmp_path)
    request = proposal(service, body)
    before = filesystem(storage.directory)
    app = create_app(tmp_path)
    assert {route.path: route.methods for route in native_connection_router(service).routes} == {
        BASE + "/source": {"POST"},
        BASE + "/preview": {"POST"},
        BASE + "/export": {"POST"},
    }

    def forbidden(*args, **kwargs):
        pytest.fail("Native connection archive copy attempted a field operation")

    for name in ("require", "connect", "disconnect", "_read", "release"):
        setattr(app.state.bacnet, name, forbidden)
    with TestClient(app) as client:
        token = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for endpoint, value in (
            ("/source", body),
            ("/preview", request),
            ("/export", {**request, "review_sha256": "0" * 64}),
        ):
            assert client.post(BASE + endpoint, json=value).status_code == 403
        loaded = client.post(BASE + "/source", headers=token, json=body)
        assert loaded.status_code == 200, loaded.text
        assert loaded.json() == service.source(body)
        response = client.post(BASE + "/preview", headers=token, json=request)
        assert response.status_code == 200, response.text
        review = response.json()
        expected, actual = service.preview(request)
        assert review == actual
        exported = client.post(
            BASE + "/export",
            headers=token,
            json={**request, "review_sha256": review["review_sha256"]},
        )
        assert exported.status_code == 200 and exported.content == expected
        for header, value in {
            "X-Studio-Source-Sha256": body["source_sha256"],
            "X-Studio-Snapshot-Sha256": body["snapshot_sha256"],
            "X-Studio-Review-Sha256": review["review_sha256"],
            "X-Studio-Compilation-Sha256": review["compilation"]["compilation_sha256"],
            "X-Studio-Artifact-Sha256": sha(expected),
        }.items():
            assert exported.headers[header] == value
        extra = client.post(BASE + "/preview", headers=token, json={**request, "apply": True})
        assert extra.status_code == 422
        # The optional built-UI StaticFiles mount rejects unknown POSTs with 405;
        # without that mount, FastAPI returns 404. Neither registers an Apply API.
        missing = 405 if any(getattr(route, "name", None) == "web" for route in app.routes) else 404
        assert client.post(BASE + "/apply", headers=token, json={}).status_code == missing
        assert not client.get("/api/session").json()["field_network_open"]
    assert filesystem(storage.directory) == before and not storage.receipts()


def test_unqualified_continuation_schema_does_not_break_readonly_original_inspection(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    files = {3: authored(metadata=b""), 11: b"unknown", 12: b"original"}
    s = retained(storage, files)
    records = NativeBackupRecords(storage)
    source = records.source({"capture_id": s["id"], "snapshot_sha256": s["evidence_sha256"]})
    assert source["read_only"] and source["application"]["diagrams"]
    record = MoiConnectionCopies(files[3]).wire.reader.records[REF]
    service = NativeConnectionCopies(records)
    body = {
        "capture_id": s["id"],
        "snapshot_sha256": s["evidence_sha256"],
        "source_sha256": sha(files[3]),
        "diagram_ref": REF,
        "record_sha256": record["sha256"],
    }
    with pytest.raises(ValueError, match="align"):
        service.source(body)
    assert storage.load(s["id"])[1] == files
