"""Native hardware engineering APIs never mutate files or open field transports."""

import hashlib

from bms_tool.app import create_app
from fastapi.testclient import TestClient

from tests.test_jci_hardware import definition


def open_definition(client, headers, raw):
    response = client.post(
        "/api/jci/hardware/open",
        files={"file": ("device-info.xml", raw)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_hardware_api_native_selection_migration_and_exact_original_export(tmp_path):
    original = definition()
    replacement = definition(revision=1, instance=4, maximum=120, default=75)
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        before = open_definition(client, headers, original)
        after = open_definition(client, headers, replacement)
        old_id, new_id = before["sha256"], after["sha256"]
        assert old_id == hashlib.sha256(original).hexdigest()
        assert before["measurement_system"] == "imperial"
        assert client.get(f"/api/jci/hardware/{old_id}").json() == before
        metric = client.get(f"/api/jci/hardware/{old_id}?system=metric").json()
        assert metric["points"][0]["value"]["parameters"]["units"] == 62
        selected = client.post(
            f"/api/jci/hardware/{old_id}/selection",
            json={"point_ids": ["temperature"], "system": "metric"},
            headers=headers,
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["can_apply"] is False
        assert selected.json()["points"][0]["value"]["parameters"]["default"] == 20
        plan = client.post(
            "/api/jci/hardware/migration",
            json={"old_sha": old_id, "new_sha": new_id, "point_ids": ["temperature"]},
            headers=headers,
        )
        assert plan.status_code == 200, plan.text
        assert plan.json()["can_apply"] is False
        assert plan.json()["changes"][0]["fields"]["instance"] == {"old": 0, "new": 4}
        assert plan.json()["changes"][0]["requires_rebinding"] is True
        for identifier, content in [(old_id, original), (new_id, replacement)]:
            exported = client.post(f"/api/jci/hardware/{identifier}/export", headers=headers)
            assert exported.status_code == 200 and exported.content == content
        assert client.get("/api/session").json()["field_network_open"] is False


def test_hardware_api_rejects_alias_ambiguity_unsafe_xml_and_unavailable_definitions(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/jci/hardware/open", files={"file": ("x.xml", definition())}
            ).status_code
            == 403
        )
        summary = open_definition(client, headers, definition())
        ambiguous = client.post(
            f"/api/jci/hardware/{summary['sha256']}/selection",
            json={"point_ids": ["temperature", "alternate"]},
            headers=headers,
        )
        assert ambiguous.status_code == 422
        assert "alias the same BACnet object" in ambiguous.text
        assert (
            client.get(f"/api/jci/hardware/{summary['sha256']}?system=guessed").status_code == 422
        )
        assert client.get("/api/jci/hardware/not-open").status_code == 422
        unsafe = b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><Interface>&a;</Interface>'
        assert (
            client.post(
                "/api/jci/hardware/open",
                files={"file": ("unsafe.xml", unsafe)},
                headers=headers,
            ).status_code
            == 422
        )
        assert client.get("/api/session").json()["field_network_open"] is False


def test_hardware_api_cache_evicts_oldest_after_sixteen_unique_definitions(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        identifiers = [
            open_definition(client, headers, definition(revision=revision))["sha256"]
            for revision in range(17)
        ]
        assert client.get(f"/api/jci/hardware/{identifiers[0]}").status_code == 422
        assert client.get(f"/api/jci/hardware/{identifiers[1]}").status_code == 200
        assert client.get(f"/api/jci/hardware/{identifiers[-1]}").status_code == 200
