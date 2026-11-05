"""Actual removable-edge witnesses, complete legacy projections and zero field access."""

import copy
from unittest.mock import patch

import pytest
from bms_tool.app import create_app
from bms_tool.moi_connection_copies import MoiConnectionCopies
from bms_tool.moi_connection_removal import MoiConnectionRemoval
from bms_tool.moi_effective_connection import EffectiveConnectionCompiler
from bms_tool.moi_effective_connection_removal import EffectiveConnectionRemovalCompiler
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_connection_removal import EffectiveConnectionRemovals, NativeConnectionRemovals
from bms_tool.native_removal_capabilities import PROFILE, removal_capabilities
from fastapi.testclient import TestClient

from .test_native_connection_copies import filesystem
from .test_native_connection_removal import removal_files, setup
from .test_native_signal_compiler import retained

OLD = [f"native-backup-operation-capabilities/{n}" for n in [11, 12, 13]]
ROWS = {"connection-removal-copy", "effective-connection-removal-compile"}
EXTRA = {
    "archive_connection_removal",
    "archive_connection_removal_error",
    "effective_connection_removal",
    "effective_connection_removal_error",
}


def source(tmp_path, **options):
    storage, _, files, query = setup(tmp_path, **options)
    return (
        storage,
        NativeBackupRecords(storage),
        files,
        {k: query[k] for k in ["capture_id", "snapshot_sha256"]},
    )


def assert_witness(service, query, witness, *, effective):
    snapshot, files = service.storage.load(query["capture_id"])
    from bms_tool.moi_identity import MoiIdentity, sha

    request = {
        **query,
        "source_sha256": sha(files[3]),
        "diagram_ref": witness["diagram_ref"],
        "record_sha256": MoiIdentity(files[3]).reader.records[witness["diagram_ref"]]["sha256"],
        "wire_index": witness["wire_index"],
    }
    compiler = (EffectiveConnectionRemovals if effective else NativeConnectionRemovals)(service)
    actual = compiler.source(request)
    selected, wire = actual["selection"], actual["selection"]["selected_wire"]
    assert selected["available"]
    assert witness["source_sha256"] == (
        actual["effective_sha256"] if effective else actual["source_sha256"]
    )
    for key in [
        "diagram_ref",
        "wire_index",
        "connection_count",
        "block_count",
        "continuation_metadata",
        "record_sha256",
        "property_sha256",
        "metadata_property_sha256",
    ]:
        assert witness[key] == selected[key]
    for key in ["old", "source_ref", "target_ref"]:
        assert witness[key] == wire[key]
    assert witness["native_fallback_or_retention_verified"] is False
    assert witness["field_transfer_enabled"] is False


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
@pytest.mark.parametrize("metadata", [False, True])
def test_literal_sources_project_to_all_complete_legacy_contracts_without_edit_compilation(
    tmp_path, compressed, extended, diagram_class, metadata
):
    storage, service, _, request = source(
        tmp_path,
        files=removal_files(
            compressed=compressed, extended=extended, diagram_class=diagram_class, metadata=metadata
        ),
    )
    before = filesystem(storage.directory)
    with (
        patch.object(
            MoiConnectionRemoval, "compile", side_effect=AssertionError("Removal compiled")
        ),
        patch.object(
            EffectiveConnectionRemovalCompiler,
            "compile",
            side_effect=AssertionError("Effective removal compiled"),
        ),
        patch.object(MoiConnectionCopies, "compile", side_effect=AssertionError("Append compiled")),
        patch.object(
            EffectiveConnectionCompiler,
            "compile",
            side_effect=AssertionError("Effective append compiled"),
        ),
    ):
        old = {
            profile: service.capabilities(request | {"capability_profile": profile})
            for profile in OLD
        }
        default = service.capabilities(request)
        current = service.capabilities(request | {"capability_profile": PROFILE})
    assert default == old[OLD[1]]
    assert [len(old[x]["operations"]) for x in OLD] == [22, 24, 25]
    assert current["capability_profile"] == PROFILE and len(current["operations"]) == 27
    assert len({r["id"] for r in current["operations"]}) == 27
    projected = copy.deepcopy(current)
    projected["capability_profile"] = OLD[2]
    projected["operations"] = [r for r in projected["operations"] if r["id"] not in ROWS]
    for key in EXTRA:
        del projected["qualification"][key]
    next(r for r in projected["operations"] if r["id"] == "general-logic")["basis"] = next(
        r for r in old[OLD[2]]["operations"] if r["id"] == "general-logic"
    )["basis"]
    assert projected == old[OLD[2]]
    assert all(EXTRA.isdisjoint(old[x]["qualification"]) for x in OLD)
    for effective, key in [
        (False, "archive_connection_removal"),
        (True, "effective_connection_removal"),
    ]:
        assert_witness(service, request, current["qualification"][key], effective=effective)
    assert current["can_apply"] is current["current_identity_verified"] is False
    assert (
        current["read_only"] and not current["field_actions"] and not current["controller_queries"]
    )
    assert filesystem(storage.directory) == before and not storage.receipts()


@pytest.mark.parametrize(
    "case,archive,effective",
    [
        ("occupied", True, True),
        ("empty", False, False),
        ("unknown", True, False),
        ("identity", True, False),
        ("vendor", True, False),
        ("no-continuation", True, True),
        ("misaligned-continuation", False, False),
        ("ambiguous-owner", False, False),
        ("cycle", True, True),
    ],
)
def test_removal_follows_actual_edges_not_addition_candidates_or_transport(
    tmp_path, case, archive, effective
):
    options = {"connector_config": {"transport": "mstp", "port": "authored-port"}}
    files = removal_files(metadata=case != "no-continuation")
    if case == "occupied":
        files = removal_files(wires=[(0, 85, 2, 7000), (1, 85, 3, 7000)])
    elif case == "empty":
        files = removal_files(wires=[])
    elif case == "unknown":
        files[11], files[12] = b"Unknown saved directory", b"Opaque saved values"
    elif case == "identity":
        options["source_identity_matches"] = False
    elif case == "vendor":
        options["identity"] = {
            "object-name": "Authored native wire controller",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 99,
        }
    elif case == "ambiguous-owner":
        files = removal_files(wires=[(0, 85, 2, 7000), (1, 85, 2, 7000)])
    elif case == "misaligned-continuation":
        from .test_moi_connection_copies import frames, packed, property_bytes
        from .test_moi_connection_removal import METADATA

        files = removal_files(compressed=False)
        records = []
        for width, body in frames(files[3]):
            if int.from_bytes(body[:2], "little") == 575:
                old = property_bytes(3384, b"".join(METADATA))
                assert body.count(old) == 1
                body = body.replace(old, property_bytes(3384, METADATA[0]), 1)
            records.append((width, body))
        files[3] = packed(files[3][:14], records)
    elif case == "cycle":
        files = removal_files(wires=[(0, 85, 0, 7000)])
    storage, service, _, request = source(tmp_path, files=files, **options)
    before = filesystem(storage.directory)
    result = service.capabilities(request | {"capability_profile": PROFILE})
    rows = {r["id"]: r for r in result["operations"]}
    for wanted, row, key, eff in [
        (archive, "connection-removal-copy", "archive_connection_removal", False),
        (effective, "effective-connection-removal-compile", "effective_connection_removal", True),
    ]:
        assert rows[row]["status"] == ("source-qualified" if wanted else "unsupported-source")
        assert (result["qualification"][key] is not None) is wanted
        if wanted:
            assert_witness(service, request, result["qualification"][key], effective=eff)
    if case == "occupied":
        assert rows["matching-connection-copy"]["status"] == "unsupported-source"
        assert rows["connection-removal-copy"]["status"] == "source-qualified"
    assert not result["can_apply"] and not result["current_identity_verified"]
    assert filesystem(storage.directory) == before and not storage.receipts()


def test_http_profile14_checks_session_source_strict_fields_and_never_enters_field_path(
    tmp_path, monkeypatch
):
    storage, _, _, body = source(tmp_path)
    before = filesystem(storage.directory)
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Local capability analysis attempted a field path or native intent")

    for name in ["require", "_read", "connect", "disconnect", "release"]:
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    with TestClient(app) as client:
        endpoint = "/api/bacnet/controller/native-application/inspection/capabilities"
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        body |= {"capability_profile": PROFILE}
        assert client.post(endpoint, json=body).status_code == 403
        response = client.post(endpoint, headers=headers, json=body)
        assert response.status_code == 200 and len(response.json()["operations"]) == 27
        for change in [
            {"capability_profile": "native-backup-operation-capabilities/999"},
            {"capability_profile": True},
            {"snapshot_sha256": "0" * 64},
            {"controller_write": True},
            {"diagram_ref": "invented-diagram"},
        ]:
            assert client.post(endpoint, headers=headers, json=body | change).status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False
    assert filesystem(storage.directory) == before and not storage.receipts()


def test_wrapper_refuses_other_profiles_and_new_witnesses_do_not_cache_between_snapshots(tmp_path):
    storage, service, files, request = source(tmp_path)
    snapshot, _, application = service.load(request)
    with pytest.raises(ValueError, match="explicit"):
        removal_capabilities(snapshot, files, application.summary(), capability_profile=OLD[2])
    first = service.capabilities(request | {"capability_profile": PROFILE})
    second = retained(storage, removal_files(wires=[]), identity=snapshot["identity"])
    result = service.capabilities(
        {
            "capture_id": second["id"],
            "snapshot_sha256": second["evidence_sha256"],
            "capability_profile": PROFILE,
        }
    )
    assert first["qualification"]["archive_connection_removal"] is not None
    assert result["qualification"]["archive_connection_removal"] is None
    assert result["capture_id"] != first["capture_id"]
