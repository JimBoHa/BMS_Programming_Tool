"""Explicit connection transfer analysis preserves complete older contracts."""

import copy
from unittest.mock import patch

import pytest
from bms_tool.app import create_app
from bms_tool.moi_connection_copies import MoiConnectionCopies
from bms_tool.moi_effective_connection import EffectiveConnectionCompiler
from bms_tool.native_backup_capabilities import CONNECTION_TRANSFER_PROFILE, PROFILE
from fastapi.testclient import TestClient

from .test_native_connection_capabilities import source
from .test_native_connection_compiler import connection_files
from .test_native_connection_copies import filesystem
from .test_native_wire_compiler import wire_files


@pytest.mark.parametrize(
    "case,status",
    [
        ("matching", "preflight-required"),
        ("no-metadata", "preflight-required"),
        ("unknown", "unsupported-source"),
        ("full", "unsupported-source"),
        ("unverified", "source-mismatch"),
        ("serial", "transport-unavailable"),
        ("bbmd", "transport-unavailable"),
    ],
)
def test_explicit13_projects_exactly_to_complete12_and_default_stays12(tmp_path, case, status):
    files = wire_files() if case == "full" else connection_files(metadata=case != "no-metadata")
    metadata = {}
    if case == "unknown":
        files[11], files[12] = b"Unknown saved directory", b"Opaque values"
    elif case == "unverified":
        metadata["source_identity_matches"] = False
    elif case in ("serial", "bbmd"):
        metadata["connector_config"] = {
            "local_address": "127.0.0.1:47810",
            **({"transport": "mstp"} if case == "serial" else {"bbmd_address": "127.0.0.1:47811"}),
        }
    storage, service, _, request = source(tmp_path, files, **metadata)
    before = filesystem(storage.directory)
    with (
        patch.object(
            MoiConnectionCopies,
            "compile",
            side_effect=AssertionError("Field analysis compiled an append"),
        ),
        patch.object(
            EffectiveConnectionCompiler,
            "compile",
            side_effect=AssertionError("Field analysis compiled saved values"),
        ),
    ):
        current = service.capabilities(request)
        explicit = service.capabilities(request | {"capability_profile": PROFILE})
        added = service.capabilities(request | {"capability_profile": CONNECTION_TRANSFER_PROFILE})
    assert current == explicit and current["capability_profile"] == PROFILE
    assert len(current["operations"]) == 24 and len(added["operations"]) == 25
    assert len({r["id"] for r in added["operations"]}) == 25
    row = next(r for r in added["operations"] if r["id"] == "matching-connection-transfer")
    assert row["status"] == status
    projected = copy.deepcopy(added)
    projected["capability_profile"] = PROFILE
    projected["operations"].remove(row)
    assert projected == current
    assert not added["can_apply"] and not added["current_identity_verified"]
    assert added["read_only"] and not added["field_actions"] and not added["controller_queries"]
    assert filesystem(storage.directory) == before and not storage.receipts()


def test_http_explicit13_requires_original_source_and_issues_no_field_action(tmp_path, monkeypatch):
    storage, _, _, request = source(tmp_path)
    before = filesystem(storage.directory)
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Capability analysis attempted a field operation")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    with TestClient(app) as client:
        path = "/api/bacnet/controller/native-application/inspection/capabilities"
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        body = request | {"capability_profile": CONNECTION_TRANSFER_PROFILE}
        assert client.post(path, json=body).status_code == 403
        response = client.post(path, json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert len(response.json()["operations"]) == 25
        assert (
            client.post(path, json=body | {"can_apply": True}, headers=headers).status_code == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]
    assert filesystem(storage.directory) == before and not storage.receipts()
