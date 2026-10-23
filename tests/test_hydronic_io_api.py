"""Actual local authenticated HTTP, exact exported sources and no field access."""

import copy
import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.hardware_survey import analyze_archive, enrich_report
from bms_tool.hardware_workbench import canonical as survey_bytes
from bms_tool.hydronic_io import MAX_REQUEST, PROFILE
from bms_tool.plant_signals import PROFILE as PLANT_PROFILE
from bms_tool.plant_signals import ReviewKey, encoded
from fastapi.testclient import TestClient

from tests.test_hardware_survey import authored_archive
from tests.test_hardware_workbench_api import offline_report
from tests.test_hydronic_io import make_case, topology

PREFIX = "/api/hydronic-io"


def import_plant(client, headers, service, request):
    raw = service.plant.export_review(ReviewKey(**request["plant_review"]), "json")
    report = json.loads(raw)
    for source in report["sources"]:
        uploaded = client.post(
            "/api/plant-signals/sources/import",
            files={"file": ("original.json", source["source_json"].encode())},
            headers=headers,
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["id"] == source["id"]
    reviewed = client.post(
        "/api/plant-signals/review",
        json={"profile_sha256": PLANT_PROFILE["sha256"], "plan": report["plan"]},
        headers=headers,
    )
    assert reviewed.status_code == 200, reviewed.text
    body = copy.deepcopy(request)
    body["plant_review"] = {
        "id": reviewed.json()["id"],
        "content_sha256": reviewed.json()["content_sha256"],
    }
    return body


@pytest.mark.parametrize(
    "loop,arrangement",
    [
        ("primary-only", "headered"),
        ("primary-only", "dedicated"),
        ("primary-secondary", "headered"),
        ("primary-secondary", "dedicated"),
    ],
)
@pytest.mark.parametrize("network", [False, True])
def test_actual_http_four_layouts_exact_sealed_export_and_no_network(
    tmp_path, monkeypatch, loop, arrangement, network
):
    service, request, _ = make_case(
        tmp_path / "fixture", topology(loop, arrangement), network=network
    )
    app = create_app(tmp_path / "app")

    def forbidden(*args, **kwargs):
        raise AssertionError("Hydraulic planner must never open field transport")

    monkeypatch.setattr(app.state.bacnet, "connect", forbidden)
    monkeypatch.setattr(app.state.bacnet, "require", forbidden)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        profile = client.get(PREFIX + "/profile").json()
        assert profile["profile"] == PROFILE
        body = import_plant(client, headers, service, request)
        for route in (
            "derive",
            "derive/csv",
            "review",
            "reviews/export/json",
            "reviews/export/csv",
        ):
            assert client.post(PREFIX + "/" + route, json=body).status_code == 403
        derive_body = {"profile_sha256": body["profile_sha256"], "topology": body["topology"]}
        first = client.post(PREFIX + "/derive", json=derive_body, headers=headers)
        assert first.status_code == 200, first.text
        assert (
            first.content
            == client.post(PREFIX + "/derive", json=derive_body, headers=headers).content
        )
        assert first.headers["x-file-sha256"] == hashlib.sha256(first.content).hexdigest()
        csv_result = client.post(PREFIX + "/derive/csv", json=derive_body, headers=headers)
        assert csv_result.status_code == 200 and b"capacity_scope" in csv_result.content
        reviewed = client.post(PREFIX + "/review", json=body, headers=headers)
        assert reviewed.status_code == 200, reviewed.text
        report = reviewed.json()
        assert report["status"] == "declared-subset-consistent"
        assert reviewed.content == encoded(report) + b"\n"
        assert reviewed.headers["x-file-sha256"] == hashlib.sha256(reviewed.content).hexdigest()
        key = {"content_sha256": report["content_sha256"]}
        exported = client.post(PREFIX + "/reviews/export/json", json=key, headers=headers)
        assert exported.content == reviewed.content
        csv_result = client.post(PREFIX + "/reviews/export/csv", json=key, headers=headers)
        assert csv_result.status_code == 200 and b"source_canonical_sha256" in csv_result.content
        assert csv_result.headers["x-file-sha256"] == hashlib.sha256(csv_result.content).hexdigest()
        assert not client.get("/api/session").json()["field_network_open"]
        assert not client.get("/api/bacnet/status").json()["connected"]


@pytest.mark.parametrize(
    "strategy,required",
    [
        ("decoupler-flow", {"decoupler.flow", "secondary.flow"}),
        ("flow-difference", {"primary.flow", "secondary.flow"}),
        (
            "temperature-difference",
            {"primary.supply_temperature", "secondary.supply_temperature", "secondary.flow"},
        ),
    ],
)
def test_actual_http_strategy_dependencies_retain_required_secondary_flow(
    tmp_path, strategy, required
):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            PREFIX + "/derive",
            json={
                "profile_sha256": PROFILE["sha256"],
                "topology": topology("primary-secondary", "dedicated", strategy),
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        measured = {r["id"] for r in response.json()["roles"] if r["direction"] == "input"}
        assert measured == required | {"building.dp"}


@pytest.mark.parametrize(
    "change,code",
    [
        ("unit", "unit-mismatch"),
        ("mode", "numeric-mode-mismatch"),
        ("host", "physical-host-mismatch"),
        ("missing", "missing-binding"),
    ],
)
def test_http_binding_conflicts_and_missing_dependencies_remain_unresolved(tmp_path, change, code):
    service, request, _ = make_case(tmp_path / "fixture")
    with TestClient(create_app(tmp_path / "app")) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        body = import_plant(client, headers, service, request)
        point = next(b for b in body["bindings"] if b["role_id"] == "building.dp")
        if change == "unit":
            body["topology"]["units"]["pressure"] = "kPa"
        elif change == "mode":
            point["mode"] = "input-contact"
        elif change == "host":
            point["physical_host_id"] = "unknown"
        else:
            body["bindings"].remove(point)
        response = client.post(PREFIX + "/review", json=body, headers=headers)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["status"] == "unresolved"
        assert code in {r["code"] for r in report["diagnostics"]}
        assert not report["whole_application_fit_established"]


def test_strict_bounded_requests_duplicate_keys_stale_profiles_and_exact_choices(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        body = {"profile_sha256": PROFILE["sha256"], "topology": topology()}
        stale = body | {"profile_sha256": "0" * 64}
        assert client.post(PREFIX + "/derive", json=stale, headers=headers).status_code == 422
        body["topology"]["equally_sized_primary"] = 1
        assert client.post(PREFIX + "/derive", json=body, headers=headers).status_code == 422
        badheaders = headers | {"Content-Type": "application/json"}
        assert (
            client.post(
                PREFIX + "/derive",
                content=b'{"profile_sha256":1,"profile_sha256":2}',
                headers=badheaders,
            ).status_code
            == 422
        )
        assert (
            client.post(
                PREFIX + "/derive", content=b" " * (MAX_REQUEST + 1), headers=badheaders
            ).status_code
            == 422
        )
        assert client.post(PREFIX + "/derive", content=b"{}", headers=headers).status_code == 422


def test_actual_imported_survey_capacity_authority_deleted_report_refuses_export(tmp_path):
    service, request, _ = make_case(tmp_path / "fixture")
    with TestClient(create_app(tmp_path / "app")) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        body = import_plant(client, headers, service, request)
        imported = client.post(
            "/api/bacnet/hardware/import-report",
            files={
                "file": (
                    "authored.json",
                    survey_bytes(
                        enrich_report(offline_report(), analyze_archive(authored_archive()))
                    ),
                )
            },
            headers=headers,
        )
        assert imported.status_code == 200, imported.text
        survey = imported.json()
        # Select the exact explicit model evidence from the immutable imported report.
        body["physical_hosts"][0]["model"] = survey["identity"]["model"]
        original = json.loads(
            service.plant.export_review(ReviewKey(**request["plant_review"]), "json")
        )
        original["plan"]["hosts"][0]["declared_model"] = survey["identity"]["model"]
        viewed = client.post(
            "/api/plant-signals/review",
            json={"profile_sha256": PLANT_PROFILE["sha256"], "plan": original["plan"]},
            headers=headers,
        ).json()
        body["plant_review"] = {"id": viewed["id"], "content_sha256": viewed["content_sha256"]}
        body["physical_hosts"][0]["survey_reference"] = {
            "id": survey["id"],
            "content_sha256": survey["content_sha256"],
            "host": "base",
        }
        response = client.post(PREFIX + "/review", json=body, headers=headers)
        assert response.status_code == 200, response.text
        report = response.json()
        assert not report["capacity_reviews"][0]["capacity_review"]["survey_binding"][
            "occupancy_applied"
        ]
        assert (
            client.delete(
                "/api/bacnet/hardware/reports/" + survey["id"], headers=headers
            ).status_code
            == 200
        )
        assert (
            client.post(
                PREFIX + "/reviews/export/json",
                json={"content_sha256": report["content_sha256"]},
                headers=headers,
            ).status_code
            == 422
        )
