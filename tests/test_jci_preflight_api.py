import hashlib
import json

from bms_tool.app import create_app
from fastapi.testclient import TestClient

from tests.test_jci_hardware import definition
from tests.test_jci_preflight import application, inventory


def test_browser_preflight_and_report_export_keep_sources_and_never_open_field_network(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        caf = application()
        uploaded = client.post(
            "/api/caf", files={"file": ("authored.caf", caf.original)}, headers=headers
        ).json()
        identifier = uploaded["sha256"]
        empty = client.get(f"/api/caf/{identifier}/preflight")
        assert empty.status_code == 200
        assert empty.json()["can_deploy"] is False
        assert client.get("/api/jci/preflight/template").json()["toolchain"]["installed"] is None
        hardware = client.post(
            "/api/jci/hardware/open",
            files={"file": ("authored.xml", definition())},
            headers=headers,
        ).json()
        text = json.dumps(inventory(hardware_definition_sha256=hardware["sha256"]), indent=2)
        request = {
            "target_model": "MS-VMA1630-0",
            "target_firmware": "6.2",
            "inventory_text": text,
            "hardware_sha256": hardware["sha256"],
        }
        assert client.post(f"/api/caf/{identifier}/preflight", json=request).status_code == 403
        result = client.post(f"/api/caf/{identifier}/preflight", json=request, headers=headers)
        assert result.status_code == 200, result.text
        exported = client.post(
            f"/api/caf/{identifier}/preflight/export", json=request, headers=headers
        )
        assert exported.status_code == 200
        assert exported.json() == result.json()
        assert "attachment" in exported.headers["content-disposition"]
        assert (
            exported.json()["source"]["inventory_utf8_sha256"]
            == hashlib.sha256(text.encode()).hexdigest()
        )
        assert exported.json()["source"]["hardware"]["sha256"] == hardware["sha256"]
        assert client.get("/api/session").json()["field_network_open"] is False
        assert (
            client.post(
                f"/api/caf/{identifier}/export", json={"changes": []}, headers=headers
            ).content
            == caf.original
        )


def test_preflight_api_rejects_invalid_manifest_missing_archive_and_missing_hardware(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        identifier = client.post(
            "/api/caf", files={"file": ("authored.caf", application().original)}, headers=headers
        ).json()["sha256"]
        for body in (
            {"inventory_text": "{"},
            {"inventory_text": '{"made_up":true}'},
            {"hardware_sha256": "0" * 64},
            {"application_object_ref": "not-a-target"},
        ):
            response = client.post(f"/api/caf/{identifier}/preflight", json=body, headers=headers)
            assert response.status_code == 422, response.text
        assert client.get("/api/caf/not-open/preflight").status_code == 422
        oversized = client.post(
            f"/api/caf/{identifier}/preflight",
            json={"inventory_text": " " * (256 * 1024 + 1)},
            headers=headers,
        )
        assert oversized.status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False


def test_operation_rules_catalog_source_bound_api_and_independent_export_seal(tmp_path):
    from tests.test_jci_release_rules import verify_seal

    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        catalog = client.get("/api/jci/preflight/release-rules").json()
        assert catalog["format"] == "bms.jci-release-rule-catalog"
        assert "simulate" in catalog["operations"]
        caf = application()
        identifier = client.post(
            "/api/caf", files={"file": ("authored.caf", caf.original)}, headers=headers
        ).json()["sha256"]
        manifest = inventory()
        manifest["toolchain"]["version"] = "18.0"
        declarations = catalog["template"] | {
            "operation": "simulate",
            "source_tool_product": "CCT",
            "source_tool_release": "10.2",
            "caf_release_mode": "10.2",
            "active_release_mode": "10.4",
        }
        body = {"inventory_text": json.dumps(manifest), "release_review": declarations}
        assert client.post(f"/api/caf/{identifier}/preflight", json=body).status_code == 403
        response = client.post(f"/api/caf/{identifier}/preflight", json=body, headers=headers)
        assert response.status_code == 200, response.text
        report = response.json()
        review = report["release_review"]
        assert review["source"]["caf_sha256"] == hashlib.sha256(caf.original).hexdigest()
        assert review["source"]["declarations"] == declarations
        assert review["source"]["observed_appl_sw_version"] == "10.2"
        assert review["ruleset_sha256"] == catalog["ruleset_sha256"]
        assert review["status"] == "documented-conflict" and report["status"] == "blocked"
        verify_seal(review)
        exported = client.post(
            f"/api/caf/{identifier}/preflight/export", json=body, headers=headers
        )
        assert exported.json() == report
        verify_seal(json.loads(exported.content)["release_review"])
        assert client.get("/api/session").json()["field_network_open"] is False
        assert (
            client.post(
                f"/api/caf/{identifier}/export", json={"changes": []}, headers=headers
            ).content
            == caf.original
        )


def test_release_rule_api_strict_fields_channel_bounds_and_unknown_origin(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        identifier = client.post(
            "/api/caf", files={"file": ("authored.caf", application().original)}, headers=headers
        ).json()["sha256"]
        for invalid in (
            {"operation": "download-and-approve"},
            {"source_tool_release": "x" * 81},
            {"mixed_firmware_on_mstp": "true"},
            {"source_channel": "production-beta"},
            {"inferred_firmware_mode": "6.2"},
        ):
            response = client.post(
                f"/api/caf/{identifier}/preflight",
                json={"release_review": invalid},
                headers=headers,
            )
            assert response.status_code == 422
        result = client.post(
            f"/api/caf/{identifier}/preflight", json={"release_review": {}}, headers=headers
        ).json()
        assert result["release_review"]["status"] == "needs-evidence"
        assert result["release_review"]["source"]["declarations"]["caf_release_mode"] == ""
        assert not result["can_deploy"]
