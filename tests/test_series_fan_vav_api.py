"""Actual local authenticated series-VAV authoring, source export and revisions."""

import hashlib
import itertools
import json

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.models import Program
from bms_tool.series_fan_vav import PROFILE, PROFILE_SHA, canonical
from fastapi.testclient import TestClient

from tests.test_series_fan_vav import choices

PREFIX = "/api/series-fan-vav-wizard"


@pytest.mark.parametrize("unit,flow", list(itertools.product(("degF", "degC"), ("cfm", "L/s"))))
@pytest.mark.parametrize("source_transport", [False, True])
def test_actual_preview_source_original_export_simulate_save_and_restart(
    tmp_path, monkeypatch, unit, flow, source_transport
):
    async def forbidden(*args, **kwargs):
        pytest.fail("Series-fan authoring attempted field access")

    for name in ("connect", "connect_mstp", "discover", "read", "apply_write", "release"):
        monkeypatch.setattr(Bacnet, name, forbidden)
    body = {"choices": choices(unit=unit, flow=flow).model_dump()}
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        catalog = client.get(PREFIX + "/catalog").json()
        assert catalog["profile"] == PROFILE and catalog["profile_sha256"] == PROFILE_SHA
        for action in ("preview", "export", "units"):
            assert client.post(PREFIX + "/" + action, json=body).status_code == 403
        response = client.post(
            PREFIX + "/preview",
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
        program = Program.model_validate(report["program"])
        assert report["can_create"] and program.digest() == report["program_sha256"]
        assert report["format"] == "bms.series-fan-vav-wizard-preview" and report["version"] == 1
        assert not report["native_compile"] and not report["controller_writes"]
        assert len(report["inputs"]) == 9 and len(report["outputs"]) == 24
        exported = client.post(PREFIX + "/export", json=body, headers=headers)
        assert exported.content == canonical(report)
        assert hashlib.sha256(exported.content).hexdigest() == exported.headers["X-File-SHA256"]
        simulated = client.post(
            "/api/simulation/step",
            json={"program": report["program"], "inputs": {}, "steps": 4},
            headers=headers,
        )
        assert simulated.status_code == 200, simulated.text
        outputs = simulated.json()["last"]["outputs"]
        assert (
            outputs["fan_ready"] and outputs["primary_damper"] > 0 and outputs["reheat_valve"] == 0
        )
        saved = client.post(
            "/api/projects",
            json={"program": report["program"], "expected_revision": 0},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        original = saved.json()
        assert original["revision"] == 1 and original["metadata"] == report["program"]["metadata"]
        assert not client.get("/api/session").json()["field_network_open"]
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/projects/authored-series-vav").json() == original
        assert not client.get("/api/session").json()["field_network_open"]


def test_actual_units_bind_original_choices_and_couple_abs_delta_inverse_temperature_and_flow_gains(
    tmp_path,
):
    value = choices(heating_kp=1000000, flow_kp=1000000)
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        result = client.post(
            PREFIX + "/units",
            json={"choices": value.model_dump(), "temperature_unit": "degC", "flow_unit": "L/s"},
            headers=headers,
        )
        assert result.status_code == 200, result.text
        converted = result.json()
        assert converted["profile_sha256"] == PROFILE_SHA
        for field in ("choices", "source_choices"):
            assert (
                hashlib.sha256(canonical(converted[field])).hexdigest()
                == converted[field + "_sha256"]
            )
        assert converted["choices"]["heating_kp"] == 1800000
        assert converted["choices"]["flow_kp"] > 2000000
        assert converted["choices"]["proof_seconds"] == value.proof_seconds
        assert converted["choices"]["occupied_default"] == value.occupied_default


@pytest.mark.parametrize(
    "patch",
    [
        {"choices": None},
        {"fan": "parallel"},
        {"heating": "electric"},
        {"flow_feedback": "position"},
        {"fan_proven_default": 1},
        {"close_seconds": 1.5},
        {"proof_seconds": 4},
        {"heating_kp": 1000001},
    ],
)
def test_invalid_or_unreviewed_branches_do_not_save_or_open_a_field_interface(tmp_path, patch):
    source = choices().model_dump()
    body = patch if "choices" in patch else {"choices": source | patch}
    with TestClient(create_app(tmp_path), raise_server_exceptions=False) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for action in ("preview", "export"):
            response = client.post(PREFIX + "/" + action, json=body, headers=headers)
            assert response.status_code == 422, response.text
        assert client.get("/api/projects").json() == []
        assert not client.get("/api/session").json()["field_network_open"]
