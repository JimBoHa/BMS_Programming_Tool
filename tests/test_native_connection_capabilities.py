"""Actual connection witnesses and explicit legacy capability projections stay local."""

import copy
import gzip
from unittest.mock import patch

import pytest
from bacpypes3.primitivedata import Unsigned
from bms_tool.app import create_app
from bms_tool.moi_connection_copies import MoiConnectionCopies
from bms_tool.moi_effective_connection import EffectiveConnectionCompiler
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_connection_compiler import EffectiveConnectionService
from bms_tool.native_connection_copies import NativeConnectionCopies
from fastapi.testclient import TestClient

from .test_controller_application import encoded
from .test_moi_connection_copies import frames, packed, property_bytes
from .test_native_connection_compiler import connection_files, setup
from .test_native_connection_copies import filesystem
from .test_native_wire_compiler import wire_files

BASE = "/api/bacnet/controller/native-application/inspection/capabilities"
PROFILE = "native-backup-operation-capabilities/12"
LEGACY = "native-backup-operation-capabilities/11"
NEW = {"matching-connection-copy", "effective-connection-compile"}
EXTRA = {
    "archive_matching_connection",
    "archive_matching_connection_error",
    "effective_matching_connection",
    "effective_matching_connection_error",
}
OLD_GENERAL = "Installed native compilers cover typed identity, existing Real/Boolean defaults and a scoped existing-wire source archive copy, not arbitrary logic generation."


def source(tmp_path, files=None, **metadata):
    storage, _, files, query = setup(tmp_path, files, **metadata)
    return (
        storage,
        NativeBackupRecords(storage),
        files,
        {k: query[k] for k in ("capture_id", "snapshot_sha256")},
    )


def verify_witness(service, request, witness, files, *, effective):
    body = {
        **request,
        "source_sha256": service.envelope(service.storage.load(request["capture_id"])[0], files)[
            "sha256"
        ],
        "diagram_ref": witness["diagram_ref"],
        "record_sha256": MoiIdentity(files[3]).reader.records[witness["diagram_ref"]]["sha256"],
        "prototype_index": witness["prototype_index"],
        "source_ref": witness["source_ref"],
    }
    editor = EffectiveConnectionService(service) if effective else NativeConnectionCopies(service)
    result = editor.source(body)
    s = result["selection"]
    assert s["available"] and any(r["ref"] == witness["target_ref"] for r in s["targets"])
    assert s["prototype"]["old"] == witness["prototype_old"]
    assert s["record_sha256"] == witness["record_sha256"]
    assert (
        s["property_sha256"] == witness["property_sha256"]
        and s["metadata_property_sha256"] == witness["metadata_property_sha256"]
    )
    assert (
        s["connection_count"] == witness["connection_count"]
        and s["block_count"] == witness["block_count"]
    )


@pytest.mark.parametrize("case", ["matching", "unknown", "unverified", "full", "no-metadata"])
def test_new_rows_project_exactly_to_explicit_legacy22_evidence(tmp_path, case):
    files = wire_files() if case == "full" else connection_files(metadata=case != "no-metadata")
    metadata = {}
    if case == "unknown":
        files[11], files[12] = b"Unknown saved directory", b"Opaque values"
    if case == "unverified":
        metadata["source_identity_matches"] = False
    storage, service, files, request = source(tmp_path, files, **metadata)
    before = filesystem(storage.directory)
    # Eligibility may parse and merge captured values, but must never invoke either edit compiler.
    with (
        patch.object(
            MoiConnectionCopies,
            "compile",
            side_effect=AssertionError("capability attempted append compilation"),
        ),
        patch.object(
            EffectiveConnectionCompiler,
            "compile",
            side_effect=AssertionError("capability attempted effective compilation"),
        ),
    ):
        current = service.capabilities(request)
        legacy = service.capabilities({**request, "capability_profile": LEGACY})
    assert current["capability_profile"] == PROFILE and len(current["operations"]) == 24
    assert legacy["capability_profile"] == LEGACY and len(legacy["operations"]) == 22
    assert not (EXTRA & legacy["qualification"].keys())
    projected = copy.deepcopy(current)
    projected["capability_profile"] = LEGACY
    projected["operations"] = [r for r in projected["operations"] if r["id"] not in NEW]
    next(r for r in projected["operations"] if r["id"] == "general-logic")["basis"] = OLD_GENERAL
    for key in EXTRA:
        del projected["qualification"][key]
    assert projected == legacy
    q = current["qualification"]
    rows = {r["id"]: r for r in current["operations"]}
    original = case != "full"
    effective = case not in ("unknown", "unverified", "full")
    assert (q["archive_matching_connection"] is not None) == original
    assert (q["effective_matching_connection"] is not None) == effective
    for key, wanted in [
        ("matching-connection-copy", original),
        ("effective-connection-compile", effective),
    ]:
        assert rows[key]["status"] == ("source-qualified" if wanted else "unsupported-source")
    if original:
        verify_witness(service, request, q["archive_matching_connection"], files, effective=False)
    if effective:
        verify_witness(service, request, q["effective_matching_connection"], files, effective=True)
    assert not current["can_apply"] and not current["current_identity_verified"]
    assert (
        not current["field_actions"] and not current["controller_queries"] and current["read_only"]
    )
    assert filesystem(storage.directory) == before and not storage.receipts()


def test_effective_configuration_can_match_when_original_target_configuration_does_not(tmp_path):
    files = connection_files()
    raw = gzip.decompress(files[3])
    records = []
    for width, body in frames(raw):
        if (
            int.from_bytes(body[:2], "little") == 527
            and (int.from_bytes(body[6:10], "big") & 0x3FFFFF) == 13
        ):
            old = property_bytes(65000, encoded(Unsigned(1)))
            assert old in body
            body = body.replace(old, property_bytes(65000, encoded(Unsigned(2))), 1)
        records.append((width, body))
    files[3] = gzip.compress(packed(raw[:14], records), mtime=123)
    value = encoded(Unsigned(1))
    row = (
        ((2 << 22) | 13).to_bytes(4, "big")
        + (65000).to_bytes(2, "big")
        + b"\x4f\x18"
        + (527).to_bytes(2, "big")
        + b"\x1e"
        + value
        + b"\x1f"
        + b"\0" * 7
    )
    files[11] += (len(row) + 2).to_bytes(2, "big") + row
    storage, service, files, request = source(tmp_path, files)
    result = service.capabilities(request)
    q = result["qualification"]
    rows = {r["id"]: r for r in result["operations"]}
    assert (
        rows["matching-connection-copy"]["status"] == "unsupported-source"
        and q["archive_matching_connection"] is None
    )
    assert rows["effective-connection-compile"]["status"] == "source-qualified"
    verify_witness(service, request, q["effective_matching_connection"], files, effective=True)
    assert storage.load(request["capture_id"])[1] == files


@pytest.mark.parametrize("key", [3, 11, 12])
def test_every_original_digest_is_checked_before_any_capability_version(tmp_path, key):
    storage, service, _, request = source(tmp_path)
    (storage.directory / request["capture_id"] / f"file-{key}.bin").write_bytes(b"Changed original")
    for version in [PROFILE, LEGACY]:
        with pytest.raises(ValueError):
            service.capabilities({**request, "capability_profile": version})
    assert not storage.receipts()


def test_http_known_versions_tokens_and_strict_source_requests_never_query_controllers(tmp_path):
    storage, service, _, request = source(tmp_path)
    before = filesystem(storage.directory)
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Capability analysis attempted a field operation")

    for name in ["require", "connect", "disconnect", "_read", "release"]:
        setattr(app.state.bacnet, name, forbidden)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE, json=request).status_code == 403
        for version, count in [(PROFILE, 24), (LEGACY, 22)]:
            response = client.post(
                BASE, headers=headers, json={**request, "capability_profile": version}
            )
            assert response.status_code == 200, response.text
            assert response.json() == service.capabilities(
                {**request, "capability_profile": version}
            )
            assert len(response.json()["operations"]) == count
        for extra in [
            {"capability_profile": True},
            {"capability_profile": "native-backup-operation-capabilities/13"},
            {"can_apply": True},
            {"address": "127.0.0.1:47808"},
        ]:
            assert client.post(BASE, headers=headers, json={**request, **extra}).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]
    assert filesystem(storage.directory) == before and not storage.receipts()
