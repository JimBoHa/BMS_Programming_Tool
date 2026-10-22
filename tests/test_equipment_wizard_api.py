"""Production API boundaries; generated programs remain editable and unallocated."""

import json

from bms_tool.app import create_app
from bms_tool.models import Program
from fastapi.testclient import TestClient

from tests.test_equipment_wizard import choices


def test_preview_units_save_reopen_export_and_source_identity(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        catalog = client.get("/api/equipment-wizard/catalog").json()
        source = choices(
            equipment="parallel-fan-reheat",
            control="flow-feedback",
            family="johnson-metasys",
            model="declared-VMA1630",
            firmware="6.2",
            release_mode="10.2",
        ).model_dump()
        assert client.post("/api/equipment-wizard/preview", json=source).status_code == 403
        result = client.post("/api/equipment-wizard/preview", json=source, headers=headers)
        assert result.status_code == 200, result.text
        result = result.json()
        program = Program.model_validate(result["program"])
        assert program.digest() == result["program_sha256"]
        assert result["profile_sha256"] == catalog["profile_sha256"]
        assert program.metadata["equipment_wizard"]["choices_sha256"] == result["choices_sha256"]
        changed = client.post(
            "/api/equipment-wizard/units",
            json={"choices": source, "temperature_unit": "degC", "flow_unit": "L/s"},
            headers=headers,
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["source_choices"] == source
        assert changed.json()["choices"]["temperature_kp"] == 36.0
        assert changed.json()["choices"]["flow_min"] == 94.38948864
        # Existing project storage changes revision, not the generated topology/metadata.
        saved = client.post(
            "/api/projects",
            json={"program": result["program"], "expected_revision": 0},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        saved = saved.json()
        assert saved["revision"] == 1
        exported = client.post(
            "/api/export", json={"program": saved, "format": "json"}, headers=headers
        )
        assert exported.status_code == 200
        assert Program.model_validate(json.loads(exported.content)) == Program.model_validate(saved)
        assert saved["metadata"] == result["program"]["metadata"]
        assert not client.get("/api/session").json()["field_network_open"]
    with TestClient(create_app(tmp_path)) as client:
        reopened = client.get("/api/projects/wizard-authored").json()
        assert reopened == saved


def test_unsupported_coerced_and_bounded_choices_never_create_saved_project(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for changes in (
            {"native_download": True},
            {"temperature_kp": "20"},
            {"flow_default": True},
            {"equipment": "electric-staged"},
            {"project_id": "x" * 81},
        ):
            body = choices().model_dump() | changes
            assert (
                client.post("/api/equipment-wizard/preview", json=body, headers=headers).status_code
                == 422
            )
        assert (
            client.post(
                "/api/equipment-wizard/units",
                json={
                    "choices": choices().model_dump(),
                    "temperature_unit": "K",
                    "flow_unit": "cfm",
                },
                headers=headers,
            ).status_code
            == 422
        )
        assert client.get("/api/projects").json() == []
        assert not client.get("/api/session").json()["field_network_open"]
