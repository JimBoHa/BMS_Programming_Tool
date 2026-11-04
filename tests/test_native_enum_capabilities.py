"""Actual retained Enum encodings qualify local copies, never semantic/field authority."""

import copy

import pytest
from bms_tool.app import create_app
from bms_tool.moi_enum_defaults import MoiEnumDefaults
from fastapi.testclient import TestClient

from .test_moi_enum_defaults import enum_source
from .test_native_backup_capabilities import BASE, operations, source


@pytest.mark.parametrize("cid", [528, 529])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("context", ["opaque-saved", "unverified", "serial"])
def test_actual_enum_codes_are_independent_of_saved_schema_identity_and_transport(
    tmp_path, cid, compressed, context
):
    files = {
        3: enum_source(cid=cid, compressed=compressed),
        11: b"Opaque schema",
        12: b"Opaque values",
    }
    metadata = {}
    if context == "unverified":
        metadata = {"source_identity_matches": False, "source_identity_error": "Authored mismatch"}
    if context == "serial":
        metadata = {"connector_config": {"transport": "mstp", "serial_port": "/dev/authored-only"}}
    storage, records, request = source(tmp_path, files, **metadata)
    before = copy.deepcopy(storage.load(request["capture_id"]))
    report = records.capabilities(request)
    rows, evidence = operations(report), report["qualification"]
    assert report["capability_profile"] == "native-backup-operation-capabilities/12"
    assert len(rows) == len(report["operations"]) == 24
    assert rows["enum-default-copy"]["status"] == "source-qualified"
    assert "membership and state meanings remain unverified" in rows["enum-default-copy"]["basis"]
    assert "no executable mapping, Enum field transfer" in rows["enum-default-copy"]["next_step"]
    assert evidence["archive_enum_default_count"] == 1
    assert (
        evidence["archive_enum_default_error"] is None and not evidence["enum_semantics_verified"]
    )
    assert rows["saved-settings"]["status"] == "unsupported-source"
    assert rows["default-transfer"]["status"] != "preflight-required"
    assert rows["boolean-default-transfer"]["status"] != "preflight-required"
    assert rows["wire-source-transfer"]["status"] != "preflight-required"
    assert rows["general-logic"]["status"] == "unavailable"
    assert rows["physical-acceptance"]["status"] == "not-inferred"
    assert (
        not report["controller_queries"] and not report["field_actions"] and not report["can_apply"]
    )
    assert not report["current_identity_verified"]
    assert storage.load(request["capture_id"]) == before and storage.receipts() == []


@pytest.mark.parametrize(
    "cid,value", [(530, b"\x91\x01"), (528, b"\x21\x01"), (529, b"\x31\x01"), (528, b"\x11")]
)
def test_an_enum_class_label_or_numeric_value_alone_does_not_qualify_a_copy(tmp_path, cid, value):
    files = {3: enum_source(cid=cid, value=value), 11: b"Opaque schema", 12: b"Opaque values"}
    _, records, request = source(tmp_path, files)
    report = records.capabilities(request)
    assert operations(report)["enum-default-copy"]["status"] == "unsupported-source"
    assert "No supported class 528/529" in operations(report)["enum-default-copy"]["basis"]
    assert report["qualification"]["archive_enum_default_count"] == 0
    assert not report["qualification"]["enum_semantics_verified"]


@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_any_altered_original_prevents_enum_capability_analysis(tmp_path, file_id):
    files = {3: enum_source(), 11: b"Opaque schema", 12: b"Opaque values"}
    storage, records, request = source(tmp_path, files)
    records.capabilities(request)
    path = storage.directory / request["capture_id"] / f"file-{file_id}.bin"
    path.write_bytes(b"authored altered original")
    with pytest.raises(ValueError):
        records.capabilities(request)
    assert path.read_bytes() == b"authored altered original" and storage.receipts() == []


def test_readable_enum_records_keep_a_strict_native_identity_error_visible(tmp_path):
    native = bytearray(enum_source(compressed=False))
    native[6:8] = (471).to_bytes(2, "little")
    files = {3: bytes(native), 11: b"Opaque schema", 12: b"Opaque values"}
    _, records, request = source(tmp_path, files)
    assert any(row["ref"] == "controller/enum-1" for row in records.records(request)["records"])
    report = records.capabilities(request)
    assert operations(report)["enum-default-copy"]["status"] == "unsupported-source"
    assert report["qualification"]["archive_enum_default_count"] == 0
    assert (
        "header and root Device class disagree"
        in report["qualification"]["archive_enum_default_error"]
    )
    assert not report["qualification"]["enum_semantics_verified"]


def test_token_admitted_enum_analysis_does_not_invoke_a_writer_or_field_interface(
    tmp_path, monkeypatch
):
    files = {3: enum_source(), 11: b"Opaque schema", 12: b"Opaque values"}
    storage, _, request = source(tmp_path, files)
    before = copy.deepcopy(storage.load(request["capture_id"]))
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Read-only Enum qualification invoked a field operation or writer")

    for method in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, method, forbidden)
    monkeypatch.setattr(MoiEnumDefaults, "preview", forbidden)
    monkeypatch.setattr(MoiEnumDefaults, "export", forbidden)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE, json=request).status_code == 403
        response = client.post(BASE, json=request, headers=headers)
        assert response.status_code == 200, response.text
        report = response.json()
        assert operations(report)["enum-default-copy"]["status"] == "source-qualified"
        assert not report["qualification"]["enum_semantics_verified"]
        assert (
            not report["can_apply"] and not client.get("/api/session").json()["field_network_open"]
        )
    assert storage.load(request["capture_id"]) == before and storage.receipts() == []
