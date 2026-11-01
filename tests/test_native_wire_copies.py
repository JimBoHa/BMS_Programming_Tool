"""Native backup wire service is immutable, offline and strictly source-bound."""

import hashlib
import types

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import sha
from bms_tool.moi_wire_sources import MoiWireSources
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_wire_copies import NativeWireCopies
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_moi_wire_sources import REF, B, source
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_signal_compiler import retained

BASE = "/api/bacnet/controller/native-application/inspection/wire-source"


def setup(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    files = {3: source(), 11: b"Unknown saved selectors", 12: b"Opaque saved values"}
    snapshot = retained(
        storage,
        files,
        identity={
            "object-name": "Authored native wire controller",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 5,
        },
    )
    record = MoiWireSources(files[3]).reader.records[REF]
    body = {
        "capture_id": snapshot["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
        "source_sha256": sha(files[3]),
        "diagram_ref": REF,
        "record_sha256": record["sha256"],
        "wire_index": 0,
    }
    return storage, NativeWireCopies(NativeBackupRecords(storage)), files, body


def preview_body(service, body):
    selection = service.source(body)["selection"]
    return body | {
        "property_sha256": selection["property_sha256"],
        "old": [0, 85, 2, 7000],
        "source_ref": B,
    }


def test_unknown_saved_schema_and_unverified_acquisition_do_not_grant_transfer_or_block_archive_copy(
    tmp_path,
):
    storage, service, files, body = setup(tmp_path)
    result = service.source(body)
    assert result["read_only"] and not result["controller_queries"] and not result["field_actions"]
    assert (
        not result["can_apply"]
        and not result["field_transfer_enabled"]
        and not result["saved_settings_merged"]
    )
    assert result["selection"]["available"]
    proposal = preview_body(service, body)
    output, review = service.preview(proposal)
    assert service.export(proposal | {"review_sha256": review["review_sha256"]})[0] == output
    assert storage.load(body["capture_id"])[1] == files
    assert not storage.receipts()
    assert not review["controller_write"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_ref", "controller/unknown"),
        ("wire_index", 1),
        ("old", [1, 85, 2, 7000]),
        ("record_sha256", "0" * 64),
        ("property_sha256", "0" * 64),
        ("source_sha256", "0" * 64),
        ("snapshot_sha256", "0" * 64),
    ],
)
def test_export_recomputes_entire_review_and_rejects_modified_proposal(tmp_path, field, value):
    _, service, _, body = setup(tmp_path)
    proposal = preview_body(service, body)
    _, review = service.preview(proposal)
    with pytest.raises(ValueError):
        service.export(proposal | {"review_sha256": review["review_sha256"], field: value})


@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_original_snapshot_checks_all_three_hashes_on_each_call(tmp_path, file_id):
    storage, service, _, body = setup(tmp_path)
    proposal = preview_body(service, body)
    _, review = service.preview(proposal)
    (storage.directory / body["capture_id"] / f"file-{file_id}.bin").write_bytes(b"Changed")
    for call in [
        lambda: service.source(body),
        lambda: service.preview(proposal),
        lambda: service.export(proposal | {"review_sha256": review["review_sha256"]}),
    ]:
        with pytest.raises(ValueError):
            call()


def test_http_strict_values_and_exact_export_headers_are_local_only(tmp_path):
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    files = {3: source(), 11: b"Unknown saved selectors", 12: b"Opaque saved values"}
    snapshot = retained(storage, files)
    editor = MoiWireSources(files[3])
    selection = editor.inspect(REF)
    body = {
        "capture_id": snapshot["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
        "source_sha256": sha(files[3]),
        "diagram_ref": REF,
        "record_sha256": selection["record_sha256"],
        "wire_index": 0,
    }
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE + "/source", json=body).status_code == 403
        response = client.post(BASE + "/source", json=body, headers=headers)
        assert response.status_code == 200, response.text
        proposal = body | {
            "property_sha256": selection["property_sha256"],
            "old": [0, 85, 2, 7000],
            "source_ref": B,
        }
        for change in [
            {"wire_index": True},
            {"old": [False, 85, 2, 7000]},
            {"address": "127.0.0.1:1"},
            {"source_ref": 1},
        ]:
            assert (
                client.post(BASE + "/preview", json=proposal | change, headers=headers).status_code
                == 422
            )
        review = client.post(BASE + "/preview", json=proposal, headers=headers).json()
        output = client.post(
            BASE + "/export",
            json=proposal | {"review_sha256": review["review_sha256"]},
            headers=headers,
        )
        assert output.status_code == 200, output.text
        assert (
            hashlib.sha256(output.content).hexdigest()
            == review["output_sha256"]
            == output.headers["X-Studio-Artifact-Sha256"]
        )
        assert output.headers["X-Studio-Review-Sha256"] == review["review_sha256"]
        assert output.headers["X-Studio-Snapshot-Sha256"] == snapshot["evidence_sha256"]
        assert not client.get("/api/session").json()["field_network_open"]
        assert not storage.receipts()


async def test_actual_capture_then_disconnected_graph_copy_sends_no_further_wire_actions(
    native_link,
):
    peer, bacnet, _, native, target = native_link
    peer.files = {3: source(), 11: b"Unknown selectors", 12: b"Opaque saved values"}
    seen = []
    original = peer.indication

    async def watch(self, apdu):
        seen.append(type(apdu).__name__)
        await original(apdu)

    peer.indication = types.MethodType(watch, peer)
    captured = await native.capture(**target, operation_id="capture-native-wire-source")
    snapshot, files = native.storage.load(captured["id"])
    await bacnet.disconnect()
    before = list(seen)
    service = NativeWireCopies(NativeBackupRecords(native.storage))
    editor = MoiWireSources(files[3])
    selection = editor.inspect(REF)
    body = {
        "capture_id": snapshot["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
        "source_sha256": sha(files[3]),
        "diagram_ref": REF,
        "record_sha256": selection["record_sha256"],
        "wire_index": 0,
    }
    proposal = preview_body(service, body)
    output, review = service.preview(proposal)
    assert service.export(proposal | {"review_sha256": review["review_sha256"]})[0] == output
    assert "ReinitializeDeviceRequest" in before and seen == before
    assert not native.storage.receipts()
