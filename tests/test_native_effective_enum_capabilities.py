"""Effective Enum capability evidence is local, typed and source-specific."""

import copy
import hashlib

import pytest
from bms_tool.app import create_app
from bms_tool.moi_effective_enum import EffectiveEnumCompiler
from bms_tool.moi_enum_defaults import MoiEnumDefaults
from fastapi.testclient import TestClient

from .test_moi_effective_enum import enum_files
from .test_moi_parameters import parameters_source
from .test_native_backup_capabilities import BASE, operations, source


@pytest.mark.parametrize("cid", [528, 529])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("transport", ["direct", "routed", "serial"])
def test_actual_effective_enum_qualification_is_independent_of_captured_transport(
    tmp_path, cid, compressed, transport
):
    metadata = {"connector_config": {"local_address": "127.0.0.1:47918"}}
    if transport == "routed":
        metadata["target"] = {"address": "10", "router": "127.0.0.1:47919", "dnet": 200}
    elif transport == "serial":
        metadata["connector_config"] = {"transport": "mstp", "serial_port": "/dev/authored-only"}
    files = enum_files(cid=cid, compressed=compressed)
    storage, records, request = source(tmp_path, files, **metadata)
    before = copy.deepcopy(storage.load(request["capture_id"]))
    folder = storage.directory / request["capture_id"]
    digests = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    report = records.capabilities(request)
    rows, evidence = operations(report), report["qualification"]
    assert report["capability_profile"] == "native-backup-operation-capabilities/12"
    assert len(rows) == len(report["operations"]) == 24
    assert rows["enum-default-copy"]["status"] == "source-qualified"
    assert rows["effective-enum-compile"]["status"] == "source-qualified"
    assert "1 have captured fixed numeric storage" in rows["effective-enum-compile"]["basis"]
    assert (
        "membership and state meanings remain unverified" in rows["effective-enum-compile"]["basis"]
    )
    assert "No Enum field transfer is prepared" in rows["effective-enum-compile"]["next_step"]
    assert evidence["archive_enum_default_count"] == evidence["effective_enum_default_count"] == 1
    assert evidence["effective_enum_fixed_storage_count"] == 1
    assert evidence["effective_enum_unknown_storage_count"] == 0
    assert evidence["effective_enum_default_error"] is None
    assert evidence["recorded_identity_verified"] and not evidence["enum_semantics_verified"]
    assert evidence["captured_plain_ipv4"] is (transport != "serial")
    assert rows["general-logic"]["status"] == "unavailable"
    assert rows["physical-acceptance"]["status"] == "not-inferred"
    assert rows["enum-default-transfer"]["status"] == (
        "transport-unavailable" if transport == "serial" else "preflight-required"
    )
    assert (
        not report["controller_queries"] and not report["field_actions"] and not report["can_apply"]
    )
    assert not report["current_identity_verified"]
    assert storage.load(request["capture_id"]) == before and storage.receipts() == []
    assert digests == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}


@pytest.mark.parametrize(
    "fault",
    ["unknown-saved", "bad-crc", "wrong-type", "unverified", "device", "name", "model", "vendor"],
)
def test_readable_archive_enum_copy_does_not_require_effective_compiler_success(tmp_path, fault):
    files, metadata = enum_files(), {}
    if fault == "unknown-saved":
        files[11], files[12] = b"Opaque saved directory", b"Opaque saved values"
    elif fault == "bad-crc":
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    elif fault == "wrong-type":
        static = bytearray(files[11])
        static[-7] = 18
        files[11] = bytes(static)
    elif fault == "unverified":
        metadata["source_identity_matches"] = False
    elif fault == "device":
        metadata["device"] = "device,5137"
    else:
        metadata["identity"] = {
            "object-name": "Wrong" if fault == "name" else "Authored controller",
            "model-name": "Wrong" if fault == "model" else "UNLISTED-MODEL",
            "vendor-identifier": 99 if fault == "vendor" else 5,
        }
    storage, records, request = source(tmp_path, files, **metadata)
    report = records.capabilities(request)
    rows, evidence = operations(report), report["qualification"]
    assert rows["enum-default-copy"]["status"] == "source-qualified"
    assert rows["effective-enum-compile"]["status"] == "unsupported-source"
    assert evidence["archive_enum_default_count"] == 1
    assert evidence["effective_enum_default_count"] == 0
    assert evidence["effective_enum_fixed_storage_count"] == 0
    assert evidence["effective_enum_unknown_storage_count"] == 0
    assert isinstance(evidence["effective_enum_default_error"], str)
    assert evidence["effective_enum_default_error"]
    assert not evidence["enum_semantics_verified"]
    assert records.records(request)["records"] and storage.receipts() == []


@pytest.mark.parametrize("cid", [528, 529])
def test_local_uint32_compilation_without_a_selected_slot_is_not_a_verified_state_domain(
    tmp_path, cid
):
    _, records, request = source(tmp_path, enum_files(cid=cid, slot=False))
    report = records.capabilities(request)
    evidence = report["qualification"]
    assert operations(report)["effective-enum-compile"]["status"] == "source-qualified"
    assert evidence["effective_enum_default_count"] == 1
    assert evidence["effective_enum_fixed_storage_count"] == 0
    assert evidence["effective_enum_unknown_storage_count"] == 1
    assert evidence["effective_enum_default_error"] is None
    assert not evidence["enum_semantics_verified"]


def test_a_valid_saved_merge_without_any_enum_field_does_not_qualify_enum_compilation(tmp_path):
    _, records, request = source(tmp_path, dict(zip((3, 11, 12), parameters_source(), strict=True)))
    report = records.capabilities(request)
    evidence = report["qualification"]
    assert operations(report)["saved-settings"]["status"] == "source-qualified"
    assert operations(report)["effective-enum-compile"]["status"] == "unsupported-source"
    assert evidence["archive_enum_default_count"] == evidence["effective_enum_default_count"] == 0
    assert evidence["effective_enum_default_error"] is None


def test_token_admitted_effective_enum_analysis_never_creates_a_copy_or_field_intent(
    tmp_path, monkeypatch
):
    storage, _, request = source(tmp_path, enum_files())
    before = copy.deepcopy(storage.load(request["capture_id"]))
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Capability analysis invoked an Enum copy/compiler export or field operation")

    for method in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, method, forbidden)
    for cls, methods in (
        (MoiEnumDefaults, ("preview", "export")),
        (EffectiveEnumCompiler, ("compile",)),
    ):
        for method in methods:
            monkeypatch.setattr(cls, method, forbidden)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE, json=request).status_code == 403
        response = client.post(BASE, json=request, headers=headers)
        assert response.status_code == 200, response.text
        assert operations(response.json())["effective-enum-compile"]["status"] == "source-qualified"
        assert client.post(BASE, json=request | {"apply": True}, headers=headers).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]
    assert storage.load(request["capture_id"]) == before and storage.receipts() == []
