"""Local native Enum copies bind all original files without field access."""

import copy

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_enum_copies import PROFILE, NativeEnumCopies
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_moi_enum_defaults import REF, enum_source
from .test_moi_enum_defaults import request as enum_request
from .test_native_signal_compiler import retained


def setup(path, *, verified=True, value=4294967295):
    storage = ApplicationStore(Store(path))
    files = {
        3: enum_source(),
        11: b"Opaque original static schema",
        12: b"Opaque original saved values",
    }
    manifest = retained(
        storage,
        files,
        source_identity_matches=verified,
        source_identity_error=None if verified else "Authored incomplete acquisition identity",
    )
    body = {
        "capture_id": manifest["id"],
        "snapshot_sha256": manifest["evidence_sha256"],
        **enum_request(files[3], value),
    }
    return storage, NativeEnumCopies(NativeBackupRecords(storage)), body, files


@pytest.mark.parametrize("verified", [False, True])
def test_preview_and_export_preserve_originals_without_saved_schema_or_field_authority(
    tmp_path, verified
):
    storage, service, request, files = setup(tmp_path, verified=verified)
    before = storage.load(request["capture_id"])
    output, review = service.preview(request)
    assert review["profile"] == PROFILE and review["request"] == request
    assert review["source_immutable"] and not review["controller_queries"]
    assert (
        not review["controller_write"]
        and not review["field_transfer_enabled"]
        and not review["enum_semantics_verified"]
    )
    assert review["source_identity_matches"] is verified
    assert review["edit"]["before_value"] == 1 and review["edit"]["after_value"] == 4294967295
    assert review["edit"]["unrelated_native_bytes_preserved"]
    assert sha(output) == review["output_sha256"]
    checked = MoiIdentity(output)
    assert checked.reader.scalar(checked.reader.records[REF], 3113) == 4294967295
    assert service.export(request | {"review_sha256": review["review_sha256"]}) == (output, review)
    assert (
        storage.load(request["capture_id"]) == before
        and before[1] == files
        and storage.receipts() == []
    )
    assert NativeEnumCopies(NativeBackupRecords(ApplicationStore(Store(tmp_path)))).preview(
        request
    ) == (output, review)


@pytest.mark.parametrize(
    "key,value",
    [
        ("snapshot_sha256", "0" * 64),
        ("source_sha256", "0" * 64),
        ("record_ref", "controller/other"),
        ("encoded_sha256", "0" * 64),
        ("value", True),
        ("value", 1.0),
        ("value", "1"),
        ("value", -1),
        ("value", 4294967296),
        ("repair", True),
    ],
)
def test_stale_and_untyped_requests_never_change_source(tmp_path, key, value):
    storage, service, request, _ = setup(tmp_path)
    before = storage.load(request["capture_id"])
    with pytest.raises(ValueError):
        service.preview(request | {key: value})
    assert storage.load(request["capture_id"]) == before and storage.receipts() == []


@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_any_changed_original_prevents_a_copy_even_when_file3_was_previously_reviewed(
    tmp_path, file_id
):
    storage, service, request, _ = setup(tmp_path)
    _, review = service.preview(request)
    path = storage.directory / request["capture_id"] / f"file-{file_id}.bin"
    path.write_bytes(b"authored changed original")
    with pytest.raises(ValueError):
        service.export(request | {"review_sha256": review["review_sha256"]})
    assert path.read_bytes() == b"authored changed original" and storage.receipts() == []


def test_changed_review_and_changed_code_are_not_exported_under_an_older_review(tmp_path):
    storage, service, request, _ = setup(tmp_path)
    _, review = service.preview(request)
    before = storage.load(request["capture_id"])
    for update in (
        {"review_sha256": "0" * 64},
        {"value": 2, "review_sha256": review["review_sha256"]},
    ):
        with pytest.raises(ValueError):
            service.export(request | update)
    assert storage.load(request["capture_id"]) == before


def test_local_http_is_token_admitted_exactly_bound_and_has_no_field_interface(tmp_path):
    storage, _, request, _ = setup(tmp_path)
    before = copy.deepcopy(storage.load(request["capture_id"]))
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Enum local copies attempted a field operation")

    for method in ("require", "_read", "connect", "disconnect", "release"):
        setattr(app.state.bacnet, method, forbidden)
    with TestClient(app) as client:
        base = "/api/bacnet/controller/native-application/inspection/enum-default"
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(base + "/preview", json=request).status_code == 403
        response = client.post(base + "/preview", headers=headers, json=request)
        assert response.status_code == 200, response.text
        review = response.json()
        response = client.post(
            base + "/export",
            headers=headers,
            json=request | {"review_sha256": review["review_sha256"]},
        )
        assert (
            response.status_code == 200
            and response.headers["X-Studio-Artifact-Sha256"]
            == sha(response.content)
            == review["output_sha256"]
        )
        assert response.headers["X-Studio-Review-Sha256"] == review["review_sha256"]
        assert response.headers["X-Studio-Snapshot-Sha256"] == request["snapshot_sha256"]
        assert (
            client.post(
                base + "/preview", headers=headers, json=request | {"apply": True}
            ).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]
    assert storage.load(request["capture_id"]) == before and storage.receipts() == []
