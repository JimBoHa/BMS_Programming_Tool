"""Actual offline HTTP authoring without field interfaces or saved-source migration."""

import json

import pytest
from bms_tool.app import create_app
from bms_tool.equipment_wizard import FAN_PROFILE_SHA
from bms_tool.models import Program
from fastapi.testclient import TestClient

from tests.test_fan_coil_wizard import fan_choices


@pytest.mark.parametrize("fan", ["single-speed", "variable-speed"])
@pytest.mark.parametrize("policy", ["continuous-occupied", "cycle-on-demand"])
def test_actual_fan_preview_conversion_simulation_revision_and_export_stay_offline(
    tmp_path, fan, policy
):
    source = fan_choices(
        fan, policy, "shutdown-unit", setpoints="inputs", family="johnson-fx", model="Declared FX"
    ).model_dump()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        catalog = client.get("/api/equipment-wizard/catalog").json()
        assert catalog["fan_coil"]["profile_sha256"] == FAN_PROFILE_SHA
        assert all(
            catalog["fan_coil"]["defaults"][key] == ""
            for key in ("coils", "fan", "fan_policy", "condensate")
        )
        assert "fan_coil" not in catalog["defaults"]
        assert client.post("/api/equipment-wizard/preview", json=source).status_code == 403
        response = client.post("/api/equipment-wizard/preview", json=source, headers=headers)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["profile"] == catalog["fan_coil"]["profile"]
        assert report["profile_sha256"] == FAN_PROFILE_SHA
        program = Program.model_validate(report["program"])
        assert program.digest() == report["program_sha256"]
        assert report["can_create"] and not report["native_compile"]
        assert not report["controller_writes"] and not report["topology"]["airflow_feedback"]
        response = client.post(
            "/api/equipment-wizard/units",
            headers=headers,
            json={"choices": source, "temperature_unit": "degC", "flow_unit": "L/s"},
        )
        assert response.status_code == 200, response.text
        converted = response.json()
        assert converted["profile_sha256"] == FAN_PROFILE_SHA
        assert converted["source_choices"] == source
        assert converted["choices"]["fan_coil"] == source["fan_coil"]
        assert converted["choices"]["temperature_kp"] == 36
        assert converted["choices"]["temperature_ki"] == pytest.approx(0.18)
        for inputs, enabled, cooling in (({}, True, 40.2), ({"occupied": False}, False, 0)):
            response = client.post(
                "/api/simulation/step",
                json={"program": report["program"], "inputs": inputs, "steps": 1},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            result = response.json()["last"]["outputs"]
            assert result["fan_enable"] is enabled
            assert result["cooling_valve"] == pytest.approx(cooling)
        response = client.post(
            "/api/projects",
            headers=headers,
            json={"program": report["program"], "expected_revision": 0},
        )
        assert response.status_code == 200, response.text
        saved = response.json()
        response = client.post(
            "/api/export", json={"program": saved, "format": "json"}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert Program.model_validate(json.loads(response.content)) == Program.model_validate(saved)
        assert not client.get("/api/session").json()["field_network_open"]
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/projects/fan-authored").json() == saved
        assert not client.get("/api/session").json()["field_network_open"]


def test_strict_fan_choice_errors_do_not_save_or_open_network(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for patch in (
            {"coils": "two-pipe"},
            {"fan": "three-speed"},
            {"fan_policy": ""},
            {"condensate": ""},
            {"occupied_default": 1},
            {"fan_min": True},
            {"fan_min": 100, "fan_max": 100},
            {"native_actuator": "integrated"},
        ):
            source = fan_choices().model_dump()
            source["fan_coil"].update(patch)
            response = client.post("/api/equipment-wizard/preview", json=source, headers=headers)
            assert response.status_code == 422, response.text
        source = fan_choices().model_dump() | {"equipment": "cooling-only", "control": "position"}
        assert (
            client.post("/api/equipment-wizard/preview", json=source, headers=headers).status_code
            == 422
        )
        assert client.get("/api/projects").json() == []
        assert not client.get("/api/session").json()["field_network_open"]
