"""Actual local export/import/profile and native-host symbol evidence routes."""

import base64
import json
import re

import pytest
from bms_tool import iec
from bms_tool.app import create_app
from bms_tool.iec_symbols import symbol_profile
from bms_tool.models import Program
from bms_tool.source_profiles import source_profile
from fastapi.testclient import TestClient

from tests.test_iec_symbols import alias_graph, boolean_graph


@pytest.mark.parametrize("factory", [alias_graph, boolean_graph])
def test_actual_http_original_program_exports_imports_and_separate_symbol_status(tmp_path, factory):
    program = factory()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        status = client.get("/api/iec/status").json()
        assert status["source_generator"] == source_profile()
        assert status["symbol_generator"] == symbol_profile()
        for format, filename in [("st", "current.st"), ("plcopen", "current.xml")]:
            denied = client.post(
                "/api/export", json={"program": program.model_dump(), "format": format}
            )
            assert denied.status_code == 403
            exported = client.post(
                "/api/export",
                json={"program": program.model_dump(), "format": format},
                headers=headers,
            )
            assert exported.status_code == 200
            if format == "st":
                assert b"BMS_STUDIO_IR_V3" in exported.content
            else:
                assert b"iecSymbols=" in exported.content
            response = client.post(
                "/api/import",
                files={"file": (filename, exported.content, "application/octet-stream")},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            assert Program.model_validate(response.json()).digest() == program.digest()
        preview = client.post(
            "/api/conversion/preview", json={"program": program.model_dump()}, headers=headers
        )
        assert preview.status_code == 200
        for target in preview.json()["targets"]:
            if target["format"] in ("st", "plcopen"):
                assert target["symbol_generator"] == symbol_profile()
                assert target["source_generator"] == source_profile()
                assert target["editable_round_trip"]["exact"]
            else:
                assert "symbol_generator" not in target
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize(
    "change", ["unknown-symbol", "wrong-symbol-rules", "mixed-version", "duplicate"]
)
def test_http_forged_source_never_falls_back_or_saves_a_new_program(tmp_path, change):
    with TestClient(create_app(tmp_path), raise_server_exceptions=False) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        raw = client.post(
            "/api/export",
            json={"program": alias_graph().model_dump(), "format": "st"},
            headers=headers,
        ).content
        encoded = re.search(rb"BMS_STUDIO_IR_V3 ([A-Za-z0-9+/=]+)", raw)[1]
        document = json.loads(base64.b64decode(encoded))
        if change == "unknown-symbol":
            document["symbol_generator"]["id"] = "unknown/1"
        elif change == "wrong-symbol-rules":
            document["symbol_generator"]["rules_sha256"] = "0" * 64
        elif change == "mixed-version":
            raw = raw.replace(b"BMS_STUDIO_IR_V3", b"BMS_STUDIO_IR_V2")
        else:
            raw += raw
        if change in {"unknown-symbol", "wrong-symbol-rules"}:
            raw = raw.replace(encoded, base64.b64encode(json.dumps(document).encode()))
        response = client.post(
            "/api/import", files={"file": ("forged.st", raw, "text/plain")}, headers=headers
        )
        assert response.status_code == 422, response.text
        assert client.get("/api/projects").json() == []
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional unchanged pinned MatIEC/clang unavailable"
)
@pytest.mark.parametrize("factory", [alias_graph, boolean_graph])
def test_actual_http_compiled_verify_and_scenario_bind_table_once_not_each_frame(tmp_path, factory):
    program = factory()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        compiled = client.post(
            "/api/iec/compile", json={"program": program.model_dump()}, headers=headers
        )
        assert compiled.status_code == 200, compiled.text
        table = compiled.json()["symbol_table"]
        assert table["profile"] == symbol_profile()
        assert compiled.json()["program_sha256"] == program.digest()
        assert {row["id"] for row in table["nodes"]} == {node.id for node in program.nodes}
        for endpoint, extra in [
            ("verify", {"scans": 2}),
            ("scenario", {"duration": 2, "events": []}),
        ]:
            response = client.post(
                "/api/iec/" + endpoint,
                json={"program": program.model_dump(), **extra},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            value = response.json()
            assert value["symbol_table"] == table
            assert value["profile"]["symbol_generator"] == symbol_profile()
            assert value["matches_reference"] and len(value["rows"]) == 2
            assert all(
                "symbol_table" not in row and "symbol_generator" not in row for row in value["rows"]
            )
        assert not client.get("/api/session").json()["field_network_open"]
