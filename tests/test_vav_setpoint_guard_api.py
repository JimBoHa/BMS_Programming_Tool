"""Real HTTP authoring, conversion and revision boundaries without field access."""

import json

import pytest
from bms_tool.app import create_app
from bms_tool.engine import Engine
from bms_tool.equipment_wizard import digest
from bms_tool.models import Program
from fastapi.testclient import TestClient

from tests.test_vav_setpoint_guard import guarded


@pytest.mark.parametrize("family", ["cooling-only", "inline-reheat", "parallel-fan-reheat"])
def test_catalog_profile_conversion_revision_reopen_export_and_no_field_connection(
    tmp_path, family
):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        source = guarded(equipment=family).model_dump()
        catalog = client.get("/api/equipment-wizard/catalog").json()["setpoint_guard"]
        assert catalog["unit_defaults"]["degF"] == source["setpoint_guard"]
        assert catalog["unit_defaults"]["degC"]["minimum_deadband"] == pytest.approx(25 / 9)
        assert digest(catalog["rules"]) == catalog["rules_sha256"]
        assert client.post("/api/equipment-wizard/preview", json=source).status_code == 403
        reply = client.post("/api/equipment-wizard/preview", json=source, headers=headers)
        assert reply.status_code == 200, reply.text
        preview = reply.json()
        assert preview["profile_sha256"] == catalog["profile_sha256"]
        assert not preview["native_compile"] and not preview["controller_writes"]
        provenance = preview["program"]["metadata"]["equipment_wizard"]["setpoint_guard"]
        assert provenance == {
            "choices": source["setpoint_guard"],
            "rules": catalog["rules"],
            "rules_sha256": catalog["rules_sha256"],
        }
        converted = client.post(
            "/api/equipment-wizard/units",
            json={"choices": source, "temperature_unit": "degC", "flow_unit": "L/s"},
            headers=headers,
        )
        assert converted.status_code == 200, converted.text
        assert converted.json()["source_choices"] == source
        assert converted.json()["choices"]["setpoint_guard"]["minimum_deadband"] == pytest.approx(
            25 / 9
        )
        saved = client.post(
            "/api/projects",
            json={"program": preview["program"], "expected_revision": 0},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        saved = saved.json()
        exported = client.post(
            "/api/export", json={"program": saved, "format": "json"}, headers=headers
        )
        assert exported.status_code == 200, exported.text
        restored = Program.model_validate(json.loads(exported.content))
        assert restored == Program.model_validate(saved)
        out = Engine(restored).step({"zone": 75})["outputs"]
        assert out["spguard_configuration_valid"] is True and out["damper"] == pytest.approx(52)
        assert not client.get("/api/session").json()["field_network_open"]
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/projects/vav-guard-test").json() == saved


@pytest.mark.parametrize(
    "changes",
    [
        {"setpoint_guard": {"minimum": 90, "maximum": 50, "minimum_deadband": 5}},
        {"setpoint_guard": {"minimum": 50, "maximum": 90, "minimum_deadband": True}},
        {"cooling_setpoint": 72},
        {"equipment": "dual-duct"},
        {"equipment": "fan-coil"},
    ],
)
def test_rejected_guard_creates_no_project_or_field_authority(tmp_path, changes):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        body = guarded().model_dump() | changes
        for endpoint, payload in [
            ("preview", body),
            ("units", {"choices": body, "temperature_unit": "degC", "flow_unit": "L/s"}),
        ]:
            assert (
                client.post(
                    "/api/equipment-wizard/" + endpoint, json=payload, headers=headers
                ).status_code
                == 422
            )
        assert client.get("/api/projects").json() == []
        assert not client.get("/api/session").json()["field_network_open"]


def test_cooling_only_narrow_range_survives_actual_units_and_preview_endpoints(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        body = guarded(
            equipment="cooling-only",
            setpoint_guard={"minimum": 72, "maximum": 74, "minimum_deadband": 5},
        ).model_dump()
        units = client.post(
            "/api/equipment-wizard/units",
            json={"choices": body, "temperature_unit": "degC", "flow_unit": "cfm"},
            headers=headers,
        )
        assert units.status_code == 200, units.text
        preview = client.post(
            "/api/equipment-wizard/preview", json=units.json()["choices"], headers=headers
        )
        assert preview.status_code == 200, preview.text
        result = preview.json()
        assert (
            "setpoint_guard.minimum_deadband"
            in result["program"]["metadata"]["equipment_wizard"]["inactive_choices"]
        )
        assert result["can_create"] and not result["controller_writes"]
        assert client.get("/api/projects").json() == []
        assert not client.get("/api/session").json()["field_network_open"]
