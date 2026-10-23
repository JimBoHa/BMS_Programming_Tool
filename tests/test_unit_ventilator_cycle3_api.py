"""Actual local authenticated UV authoring, source/export and revision lifecycle."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.models import Program
from bms_tool.unit_ventilator_cycle3 import PROFILE, PROFILE_SHA, canonical
from fastapi.testclient import TestClient

from tests.test_unit_ventilator_cycle3 import choices

BASE = "/api/unit-ventilator-cycle3-wizard"


@pytest.mark.parametrize("unit", ["degF", "degC"])
@pytest.mark.parametrize("policy", ["disable-cooling", "shutdown-unit"])
@pytest.mark.parametrize("source_transport", [False, True])
def test_actual_http_author_original_export_simulate_save_restart_without_field_access(
    tmp_path, monkeypatch, unit, policy, source_transport
):
    async def forbidden(*args, **kwargs):
        pytest.fail("UV authoring attempted field access")

    for method in ("connect", "connect_mstp", "discover", "read", "apply_write", "release"):
        monkeypatch.setattr(Bacnet, method, forbidden)
    value = choices(unit=unit, condensate_policy=policy, zone_default=80, mixed_air_default=65)
    body = {"choices": value.model_dump()}
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        before_power = client.get("/api/operation-power").json()
        catalog = client.get(BASE + "/catalog")
        assert catalog.status_code == 200
        assert (
            catalog.json()["profile"] == PROFILE and catalog.json()["profile_sha256"] == PROFILE_SHA
        )
        assert catalog.json()["defaults"]["condensate_policy"] == ""
        for action in ("preview", "export", "units"):
            assert client.post(BASE + "/" + action, json=body).status_code == 403
        response = client.post(
            BASE + "/preview",
            json=body,
            headers=headers | ({"X-Studio-Program-Source": "true"} if source_transport else {}),
        )
        assert response.status_code == 200, response.text
        report = response.json()
        if source_transport:
            assert report["format"] == "bms.program-source-response/1"
            assert (
                hashlib.sha256(report["source_json"].encode()).hexdigest()
                == report["source_sha256"]
            )
            assert report["programs"][0]["path"] == ["program"]
            report = json.loads(report["source_json"])
        p = Program.model_validate(report["program"])
        assert p.digest() == report["program_sha256"]
        assert report["can_create"] and len(report["inputs"]) == 13 and len(report["outputs"]) == 29
        assert not report["native_compile"] and not report["controller_writes"]
        exported = client.post(BASE + "/export", json=body, headers=headers)
        assert exported.content == canonical(report)
        assert hashlib.sha256(exported.content).hexdigest() == exported.headers["X-File-SHA256"]
        assert b'"x":40.0' in exported.content
        simulated = client.post(
            "/api/simulation/step",
            json={"program": report["program"], "inputs": {}, "steps": 2},
            headers=headers,
        )
        assert simulated.status_code == 200, simulated.text
        out = simulated.json()["last"]["outputs"]
        assert (
            out["fan_ready"]
            and out["cooling_valve"] > 0
            and out["outdoor_damper"] > value.minimum_outdoor_position
        )
        saved = client.post(
            "/api/projects",
            json={"program": report["program"], "expected_revision": 0},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        original = saved.json()
        assert original["revision"] == 1 and original["metadata"] == report["program"]["metadata"]
        assert client.get("/api/session").json()["field_network_open"] is False
        after_power = client.get("/api/operation-power").json()
        assert (
            before_power["active"] == after_power["active"] == []
            and before_power["recent"] == after_power["recent"] == []
        )
        evidence = os.environ.get("BMS_UV_API_EVIDENCE")
        if evidence:
            dest = Path(evidence) / (unit + "-" + policy + "-" + str(source_transport))
            dest.mkdir(parents=True, exist_ok=False)
            for name, raw in (
                ("catalog.json", catalog.content),
                ("preview.json", response.content),
                ("export.json", exported.content),
                ("simulation.json", simulated.content),
                ("saved.json", saved.content),
            ):
                (dest / name).write_bytes(raw)
    with TestClient(create_app(tmp_path)) as client:
        restored = client.get("/api/projects/" + p.id)
        assert restored.json() == original
        restored_program = Program.model_validate_json(restored.content)
        restored_program.revision = 0
        assert restored_program.digest() == p.digest()
        assert not client.get("/api/session").json()["field_network_open"]


def test_actual_units_couple_all_abs_delta_inverse_gains_and_bind_original_choices(tmp_path):
    v = choices(heating_ki=1e-6, minimum_outdoor_position=100)
    with TestClient(create_app(tmp_path)) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        result = client.post(
            BASE + "/units", json={"choices": v.model_dump(), "temperature_unit": "degC"}, headers=h
        )
        assert result.status_code == 200, result.text
        x = result.json()
        assert x["profile_sha256"] == PROFILE_SHA
        for field in ("source_choices", "choices"):
            assert hashlib.sha256(canonical(x[field])).hexdigest() == x[field + "_sha256"]
        assert (
            x["choices"]["zone_default"] == (72 - 32) * 5 / 9
            and x["choices"]["entry_delta"] == 5 / 9
        )
        assert (
            x["choices"]["zone_limit_kp"] == 5 / (5 / 9)
            and x["choices"]["minimum_outdoor_position"] == 100
        )
        assert (
            x["choices"]["proof_seconds"] == v.proof_seconds
            and x["choices"]["airflow_proven_default"] == v.airflow_proven_default
        )
        adjacent = x["choices"] | {
            "entry_delta": 1.5000000000000007,
            "release_delta": 1.5000000000000004,
        }
        assert (
            client.post(BASE + "/preview", json={"choices": adjacent}, headers=h).status_code == 200
        )
        refused = client.post(
            BASE + "/units", json={"choices": adjacent, "temperature_unit": "degF"}, headers=h
        )
        assert refused.status_code == 422
        assert (
            adjacent["temperature_unit"] == "degC"
            and adjacent["entry_delta"] > adjacent["release_delta"]
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"condensate_policy": ""},
        {"fan": "variable-speed"},
        {"coils": "DX"},
        {"mixing_action": "warm-outdoor"},
        {"minimum_outdoor_position": True},
        {"proof_seconds": 1.5},
        {"FSCS": "open"},
        {"heating_available_default": 1},
    ],
)
def test_actual_http_rejects_unsupported_choices_without_invented_native_controls(tmp_path, patch):
    with TestClient(create_app(tmp_path)) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        original = choices().model_dump()
        for action in ("preview", "export", "units"):
            response = client.post(
                BASE + "/" + action,
                json={
                    "choices": original | patch,
                    **({"temperature_unit": "degC"} if action == "units" else {}),
                },
                headers=h,
            )
            assert response.status_code == 422, response.text
        assert not client.get("/api/session").json()["field_network_open"]


def test_actual_negative_zero_scientific_original_source_exports_units_and_saved_revisions(
    tmp_path,
):
    import math

    value = choices(heating_ki=-0.0, zone_limit_ki=-0.0, cooling_ki=1e-6)
    with TestClient(create_app(tmp_path)) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            BASE + "/preview",
            json={"choices": value.model_dump()},
            headers=h | {"X-Studio-Program-Source": "true"},
        )
        assert response.status_code == 200, response.text
        envelope = response.json()
        assert (
            hashlib.sha256(envelope["source_json"].encode()).hexdigest()
            == envelope["source_sha256"]
        )
        assert '"ki":-0.0' in envelope["source_json"] and "1e-06" in envelope["source_json"]
        report = json.loads(envelope["source_json"])
        assert math.copysign(1, report["choices"]["heating_ki"]) < 0
        original = client.post(BASE + "/export", json={"choices": value.model_dump()}, headers=h)
        assert (
            original.content == canonical(report)
            and hashlib.sha256(original.content).hexdigest() == original.headers["X-File-SHA256"]
        )
        assert b'"ki":-0.0' in original.content and b"1e-06" in original.content
        converted = client.post(
            BASE + "/units",
            json={"choices": value.model_dump(), "temperature_unit": "degC"},
            headers=h,
        )
        assert converted.status_code == 200, converted.text
        assert math.copysign(1, converted.json()["source_choices"]["heating_ki"]) < 0
        assert math.copysign(1, converted.json()["choices"]["heating_ki"]) < 0
        saved = client.post(
            "/api/projects", json={"program": report["program"], "expected_revision": 0}, headers=h
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        p = Program.model_validate(body)
        assert p.revision == 1
        p.revision = 0
        assert p.digest() == report["program_sha256"]
        assert (
            math.copysign(
                1, next(x for x in body["nodes"] if x["id"] == "uv_heating_loop")["params"]["ki"]
            )
            < 0
        )
        evidence = os.environ.get("BMS_UV_API_EVIDENCE")
        if evidence:
            dest = Path(evidence) / "negative-zero-scientific"
            dest.mkdir(parents=True, exist_ok=False)
            for name, raw in (
                ("preview.json", response.content),
                ("export.json", original.content),
                ("units.json", converted.content),
                ("saved.json", saved.content),
            ):
                (dest / name).write_bytes(raw)
