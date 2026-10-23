"""Actual offline HTTP creation, conversion, simulation and archival boundaries."""

import json

import pytest
from bms_tool.app import create_app
from bms_tool.engine import Engine
from bms_tool.equipment_wizard import DUAL_PROFILE_SHA
from bms_tool.models import Program
from fastapi.testclient import TestClient

from tests.test_dual_duct_wizard import dual


@pytest.mark.parametrize("layout", ["none", "hot-cold", "hot-total", "cold-total"])
def test_native_network_stays_closed_while_dual_preview_units_simulate_save_export_reopen(
    tmp_path, layout
):
    source = dual(
        layout, setpoints="inputs", family="johnson-metasys", model="Declared VMA"
    ).model_dump()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        catalog = client.get("/api/equipment-wizard/catalog").json()
        assert catalog["dual_duct"]["profile_sha256"] == DUAL_PROFILE_SHA
        assert catalog["dual_duct"]["defaults"]["layout"] == ""
        assert "dual_duct" not in catalog["defaults"]
        assert client.post("/api/equipment-wizard/preview", json=source).status_code == 403
        response = client.post("/api/equipment-wizard/preview", json=source, headers=headers)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["profile_sha256"] == catalog["dual_duct"]["profile_sha256"]
        assert report["profile"] == catalog["dual_duct"]["profile"]
        program = Program.model_validate(report["program"])
        assert program.digest() == report["program_sha256"]
        assert report["can_create"] and report["native_compile"] is False
        result = client.post(
            "/api/equipment-wizard/units",
            headers=headers,
            json={"choices": source, "temperature_unit": "degC", "flow_unit": "L/s"},
        )
        assert result.status_code == 200, result.text
        converted = result.json()
        assert converted["profile_sha256"] == DUAL_PROFILE_SHA
        assert converted["source_choices"] == source
        assert converted["choices"]["dual_duct"]["hot_flow_max"] == pytest.approx(377.55795456)
        body = {"program": report["program"], "inputs": {}, "steps": 1}
        stepped = client.post("/api/simulation/step", json=body, headers=headers)
        assert stepped.status_code == 200, stepped.text
        assert stepped.json()["last"]["outputs"] == Engine(program).step()["outputs"]
        saved = client.post(
            "/api/projects",
            headers=headers,
            json={"program": report["program"], "expected_revision": 0},
        )
        assert saved.status_code == 200, saved.text
        saved = saved.json()
        response = client.post(
            "/api/export", json={"program": saved, "format": "json"}, headers=headers
        )
        assert response.status_code == 200
        assert Program.model_validate(json.loads(response.content)) == Program.model_validate(saved)
        assert not client.get("/api/session").json()["field_network_open"]
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/projects/dual-authored").json() == saved
        assert not client.get("/api/session").json()["field_network_open"]


def test_unknown_layout_and_illicit_native_allocation_do_not_make_any_saved_program(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for patch in (
            {"layout": "total-only"},
            {"layout": ""},
            {"hot_flow_default": True},
            {"native_actuator": "integrated"},
            {"total_flow_default": "600"},
        ):
            source = dual().model_dump()
            source["dual_duct"].update(patch)
            response = client.post("/api/equipment-wizard/preview", json=source, headers=headers)
            assert response.status_code == 422, response.text
        assert client.get("/api/projects").json() == []
        assert not client.get("/api/session").json()["field_network_open"]
