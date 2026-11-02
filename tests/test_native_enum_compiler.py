"""Retained effective Enum source, review and file export never dispatch field work."""

import copy

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_enum_compiler import EffectiveEnumService
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_moi_effective_enum import enum_files
from .test_moi_enum_defaults import REF
from .test_native_signal_compiler import retained


def setup(path, **metadata):
    storage = ApplicationStore(Store(path))
    files = enum_files()
    manifest = retained(storage, files, **metadata)
    service = EffectiveEnumService(NativeBackupRecords(storage))
    source_request = {"capture_id": manifest["id"], "snapshot_sha256": manifest["evidence_sha256"]}
    return storage, service, source_request, files


def proposal(source, value=65535):
    (field,) = source["fields"]
    return {
        "capture_id": source["capture_id"],
        "snapshot_sha256": source["snapshot_sha256"],
        "source_sha256": source["source_sha256"],
        "record_ref": field["ref"],
        "encoded_sha256": field["encoded_sha256"],
        "value": value,
    }


@pytest.mark.parametrize("transport", ["ip", "serial"])
def test_effective_source_preview_export_restart_and_original_preservation(tmp_path, transport):
    metadata = (
        {"connector_config": {"transport": "mstp", "serial_port": "/dev/authored"}}
        if transport == "serial"
        else {}
    )
    storage, service, request, files = setup(tmp_path, **metadata)
    before = copy.deepcopy(storage.load(request["capture_id"]))
    source = service.source(request)
    (field,) = source["fields"]
    assert (
        field["archive_value"] == 1
        and field["effective_value"] == 513
        and field["maximum_code"] == 65535
    )
    assert source["saved_settings_merged"] and source["source_immutable"]
    assert (
        not source["controller_queries"]
        and not source["controller_write"]
        and not source["field_transfer_enabled"]
        and not source["enum_semantics_verified"]
        and not source["current_identity_verified"]
    )
    body = proposal(source)
    output, review = service.preview(body)
    assert (
        review["archive_value"] == 1
        and review["edit"]["before_value"] == 513
        and review["edit"]["after_value"] == 65535
    )
    assert (
        review["compilation"]["saved_storage"]["bytes"] == 2
        and not review["compilation"]["enum_semantics_verified"]
    )
    assert service.export(body | {"review_sha256": review["review_sha256"]}) == (output, review)
    reader = MoiIdentity(output)
    assert reader.reader.scalar(reader.reader.records[REF], 3113) == 65535
    assert reader.reader.scalar(reader.root, 900) == 3.5 and sha(output) == review["output_sha256"]
    assert (
        storage.load(request["capture_id"]) == before
        and before[1] == files
        and storage.receipts() == []
    )
    restarted = EffectiveEnumService(NativeBackupRecords(ApplicationStore(Store(tmp_path))))
    assert restarted.source(request) == source and restarted.preview(body) == (output, review)


@pytest.mark.parametrize(
    "key,value",
    [
        ("source_sha256", "0" * 64),
        ("encoded_sha256", "0" * 64),
        ("value", True),
        ("value", 1.0),
        ("value", "1"),
        ("value", -1),
        ("value", 65536),
        ("extra", True),
    ],
)
def test_invalid_stale_or_over_capacity_proposals_cannot_change_originals(tmp_path, key, value):
    storage, service, request, _ = setup(tmp_path)
    before = storage.load(request["capture_id"])
    body = proposal(service.source(request)) | {key: value}
    with pytest.raises(ValueError):
        service.preview(body)
    assert storage.load(request["capture_id"]) == before and storage.receipts() == []


@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_changed_original_files_invalidate_an_already_reviewed_compilation(tmp_path, file_id):
    storage, service, request, _ = setup(tmp_path)
    body = proposal(service.source(request))
    _, review = service.preview(body)
    path = storage.directory / request["capture_id"] / f"file-{file_id}.bin"
    path.write_bytes(b"authored changed original")
    with pytest.raises(ValueError):
        service.export(body | {"review_sha256": review["review_sha256"]})
    assert path.read_bytes() == b"authored changed original" and storage.receipts() == []


def test_changed_review_or_proposal_cannot_export_under_an_old_review(tmp_path):
    _, service, request, _ = setup(tmp_path)
    body = proposal(service.source(request))
    _, review = service.preview(body)
    for update in (
        {"review_sha256": "0" * 64},
        {"review_sha256": review["review_sha256"], "value": 2},
    ):
        with pytest.raises(ValueError):
            service.export(body | update)


def test_token_admitted_effective_enum_http_keeps_field_access_and_journals_unused(
    tmp_path, monkeypatch
):
    storage, service, request, _ = setup(tmp_path)
    before = copy.deepcopy(storage.load(request["capture_id"]))
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Local effective Enum compilation attempted field access")

    for method in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, method, forbidden)
    with TestClient(app) as client:
        base = "/api/bacnet/controller/native-application/enum-default-compiler"
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(base + "/source", json=request).status_code == 403
        source = client.post(base + "/source", headers=headers, json=request)
        assert source.status_code == 200, source.text
        body = proposal(source.json())
        preview = client.post(base + "/preview", headers=headers, json=body)
        assert preview.status_code == 200, preview.text
        review = preview.json()
        response = client.post(
            base + "/export",
            headers=headers,
            json=body | {"review_sha256": review["review_sha256"]},
        )
        assert response.status_code == 200, response.text
        assert (
            response.headers["X-Studio-Artifact-Sha256"]
            == sha(response.content)
            == review["output_sha256"]
        )
        assert response.headers["X-Studio-Review-Sha256"] == review["review_sha256"]
        assert response.headers["X-Studio-Snapshot-Sha256"] == request["snapshot_sha256"]
        assert (
            client.post(
                base + "/source", headers=headers, json=request | {"address": "127.0.0.1:1"}
            ).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]
    assert storage.load(request["capture_id"]) == before and storage.receipts() == []
