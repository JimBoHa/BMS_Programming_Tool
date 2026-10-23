"""Source-qualified transport decisions and actual pre-dispatch integration."""

import asyncio
import copy
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from bms_tool.app import create_app
from bms_tool.hardware_target import HardwareTargetRequest
from bms_tool.hardware_workbench import HardwareWorkbench
from bms_tool.model_transport import (
    PROFILE,
    PROFILE_SHA,
    ModelQualification,
    catalog,
    observe,
    review,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError

from .test_connections import free_udp
from .test_hardware_survey import hardware_link as hardware_link

IP = {"local_address": "127.0.0.1:47808", "instance": 4190001}
SERIAL = {
    "transport": "mstp",
    "port": "/authored/tty",
    "mac": 5,
    "instance": 4190001,
    "baudrate": 38400,
    "max_master": 127,
    "max_info_frames": 1,
}


def qualification(model="MS-FAC4911-0", protocol="bacnet-ip", **changes):
    return {"profile_sha256": PROFILE_SHA, "model": model, "current_protocol": protocol, **changes}


def target(path="ip", **changes):
    return {
        "address": "127.0.0.1:47809",
        "device": "device,4190123",
        **(
            {"transport": "direct-mstp", "address": "44"}
            if path == "serial"
            else {"address": "3001:7", "router": "127.0.0.1:47809", "dnet": 3001}
            if path == "routed"
            else {}
        ),
        **changes,
    }


@pytest.mark.parametrize(
    "model,protocol,path,admitted,reason",
    [
        ("MS-FAC4911-0", "bacnet-ip", "ip", True, None),
        ("MS-FAC4911-0", "bacnet-mstp", "serial", False, "direct_mstp_not_documented"),
        ("MS-FAC4911-0", "bacnet-mstp", "routed", False, "protocol_not_documented_for_model"),
        ("MS-FAC4911-0", "bacnet-sc", "ip", False, "adapter_unavailable"),
        ("MS-FAC4911-0", "n2", "ip", False, "adapter_unavailable"),
        ("MS-FAC2611-0", "bacnet-mstp", "serial", True, None),
        ("MS-FAC2611-0", "bacnet-mstp", "routed", True, None),
        ("MS-FAC3613-0", "bacnet-mstp", "serial", True, None),
        ("MS-FAC3613-0", "bacnet-mstp", "routed", True, None),
        ("MS-FAC2611-0", "bacnet-ip", "ip", False, "protocol_not_documented_for_model"),
        ("MS-FAC3613-0", "n2", "serial", False, "adapter_unavailable"),
        ("MS-FAC4911-0", "unknown", "ip", False, "unresolved_current_protocol"),
        ("MS-FAC4911-0U", "bacnet-ip", "ip", False, "unresolved_model"),
        ("FAC4911", "bacnet-ip", "ip", False, "unresolved_model"),
        ("ms-fac4911-0", "bacnet-ip", "ip", False, "unresolved_model"),
        ("MS-FAC4911-0", "bacnet-ip", "routed", False, "path_not_qualified"),
    ],
)
def test_documented_exact_parts_paths_and_current_protocol_are_distinct(
    model, protocol, path, admitted, reason
):
    result = review(
        qualification(model, protocol),
        target(path),
        SERIAL if path == "serial" else IP,
        connected=True,
    )
    assert result["dispatch_admitted"] is admitted
    assert result["declaration"]["model"] == model
    assert result["native_compatibility_verified"] is False
    if reason:
        assert reason in [f["code"] for f in result["findings"]]
    else:
        assert result["findings"] == []


def test_generic_multioctet_route_is_retained_but_not_promoted_to_mstp():
    chosen = HardwareTargetRequest.model_validate(target("routed", address="3001:0x010203040506"))
    result = review(qualification("MS-FAC2611-0", "bacnet-mstp"), chosen, IP, connected=True)
    assert not result["dispatch_admitted"]
    assert result["target"] == chosen.model_dump()
    assert "routed_link_unresolved" in [r["code"] for r in result["findings"]]


@pytest.mark.parametrize("mac", [0, 128, 254])
def test_optional_transport_policy_does_not_silently_narrow_original_address_rules(mac):
    result = review(
        qualification("MS-FAC2611-0", "bacnet-mstp"),
        target("serial", address=str(mac)),
        SERIAL,
        connected=True,
    )
    assert result["dispatch_admitted"]
    assert "not additionally enforced" in PROFILE["semantics"]["addresses"]


@pytest.mark.parametrize(
    "config,connected,reason",
    [
        (None, False, "interface_not_open"),
        (IP, False, "interface_not_open"),
        (SERIAL, True, "interface_path_mismatch"),
    ],
)
def test_missing_or_wrong_open_interface_never_admits_read(config, connected, reason):
    result = review(qualification(), target(), config, connected=connected)
    assert not result["dispatch_admitted"] and reason in [r["code"] for r in result["findings"]]


@pytest.mark.parametrize(
    "address,configuration", [("5", SERIAL), ("44", SERIAL | {"baudrate": 123})]
)
def test_pure_review_reuses_original_serial_identity_including_own_station(address, configuration):
    result = review(
        qualification("MS-FAC2611-0", "bacnet-mstp"),
        target("serial", address=address),
        configuration,
        connected=True,
    )
    assert not result["dispatch_admitted"]
    assert "serial_identity_not_admitted" in [row["code"] for row in result["findings"]]


def test_profile_and_catalog_are_independently_bound_without_mutating_inputs():
    assert (
        PROFILE_SHA
        == hashlib.sha256(
            json.dumps(PROFILE, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    value = catalog()
    value["profile"]["models"].clear()
    assert len(PROFILE["models"]) == 3
    q, t, config = qualification(), target(), copy.deepcopy(IP)
    original = copy.deepcopy((q, t, config))
    result = review(q, t, config, connected=True)
    result["interface"]["config"]["local_address"] = "changed"
    assert (q, t, config) == original
    refused = review(qualification(profile_sha256="0" * 64), t, config, connected=True)
    assert not refused["dispatch_admitted"]


@pytest.mark.parametrize(
    "raw,status",
    [
        (None, "unresolved"),
        ("", "unresolved"),
        ("FAC4911", "different_text_unresolved"),
        ("MS-FAC4911-0", "exact_text_match"),
        ("MS-FAC3613-0", "different_text_unresolved"),
    ],
)
def test_raw_observations_remain_separate_from_part_identity(raw, status):
    admission = review(qualification(), target(), IP, connected=True)
    report = {
        "identity": {
            "object": "device,4190123",
            "model": raw,
            "vendor_id": 5,
            "firmware": "authored",
        },
        "target": admission["target"],
        "connector_config": IP,
    }
    original = copy.deepcopy(report)
    result = observe(admission, report)
    assert report == original and result["raw_identity"]["model"] == raw
    assert (
        result["model_text_status"] == status and result["native_compatibility_verified"] is False
    )
    assert result["target_matches_admission"] and result["config_matches_admission"]


@pytest.mark.parametrize(
    "value",
    [{"model": 4911}, {"current_protocol": "auto"}, {"profile_sha256": "bad"}, {"extra": True}],
)
def test_qualification_schema_refuses_coercion_or_unreviewed_fields(value):
    with pytest.raises(ValidationError):
        ModelQualification.model_validate(qualification(**value))


def test_actual_http_pure_review_and_refused_survey_make_no_native_calls(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    calls = []
    monkeypatch.setattr(
        app.state.bacnet, "require", lambda: calls.append("local-require") or object()
    )
    app.state.bacnet.config = copy.deepcopy(IP)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        value = client.get("/api/bacnet/hardware/model-transport/profile").json()
        assert value["profile_sha256"] == PROFILE_SHA
        body = {"qualification": qualification(protocol="bacnet-sc"), "target": target()}
        assert (
            client.post("/api/bacnet/hardware/model-transport/review", json=body).status_code == 403
        )
        reply = client.post(
            "/api/bacnet/hardware/model-transport/review", json=body, headers=headers
        )
        assert reply.status_code == 200 and not reply.json()["dispatch_admitted"] and not calls
        response = client.post(
            "/api/bacnet/hardware/survey",
            json=target() | {"model_qualification": body["qualification"]},
            headers=headers,
        )
        assert response.status_code == 422 and "adapter_unavailable" in response.text
        assert calls == ["local-require"] and app.state.hardware_workbench.jobs == {}
        assert not client.get("/api/session").json()["field_network_open"]


async def finished(workbench, job):
    await asyncio.wait_for(workbench.tasks[job["id"]], 10)
    return workbench.job(job["id"])


@pytest.mark.parametrize("raw_model", ["MS-FAC4911-0", "FAC4911"])
async def test_actual_udp_qualified_survey_keeps_original_report_and_retains_job_identity(
    hardware_link, raw_model
):
    server, client, _, options = hardware_link
    server.device_object.modelName = raw_model
    workbench = HardwareWorkbench(client, client.store, SimpleNamespace(captures=lambda: []))
    calls = []
    original = server.do_ReadPropertyMultipleRequest

    async def track(request):
        calls.append(type(request).__name__)
        await original(request)

    server.do_ReadPropertyMultipleRequest = track
    try:
        plain = await finished(workbench, workbench.start("survey", options))
        assert "model_transport_admission" not in plain
        job = await finished(
            workbench, workbench.start("survey", options | {"model_qualification": qualification()})
        )
        assert job["status"] == "complete", job
        assert job["model_transport_admission"]["dispatch_admitted"]
        observation = job["model_transport_observation"]
        assert observation["raw_identity"]["model"] == raw_model
        assert observation["model_text_status"] == (
            "exact_text_match" if raw_model.startswith("MS-") else "different_text_unresolved"
        )
        assert observation["target_matches_admission"] and observation["config_matches_admission"]
        saved = workbench.report(job["report_id"])
        assert (
            "model_transport_admission" not in saved and "model_transport_observation" not in saved
        )
        assert saved["profile"] == plain["report"]["profile"] == "bacnet-hardware-survey/1"
        assert (
            saved["identity"] == plain["report"]["identity"]
            and saved["target"] == plain["report"]["target"]
        )
        assert calls and not client.commands
    finally:
        await workbench.close()


async def test_config_change_before_worker_start_refuses_before_any_read(hardware_link):
    _, client, _, options = hardware_link
    workbench = HardwareWorkbench(client, client.store, SimpleNamespace(captures=lambda: []))
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("No native read may follow changed interface admission")

    workbench.surveys.survey = forbidden
    job = workbench.start("survey", options | {"model_qualification": qualification()})
    original = copy.deepcopy(client.config)
    try:
        client.config["instance"] += 1
        result = await finished(workbench, job)
        assert result["status"] == "error" and "changed before" in result["error"]
        assert not calls and not client.commands
    finally:
        client.config = original
        await workbench.close()


async def test_actual_http_qualified_read_job_export_and_restart_preserve_owned_evidence(
    hardware_link, tmp_path
):
    peer, _, _, options = hardware_link
    peer.device_object.modelName = "MS-FAC4911-0"
    seen = []
    original = peer.do_ReadPropertyMultipleRequest

    async def tracking(request):
        seen.append(type(request).__name__)
        await original(request)

    peer.do_ReadPropertyMultipleRequest = tracking
    state = tmp_path / "actual-http-model-path"
    app = create_app(state)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            opened = await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{free_udp()}"},
                headers=headers,
            )
            assert opened.status_code == 200, opened.text
            preview = await client.post(
                "/api/bacnet/hardware/model-transport/review",
                json={
                    "qualification": qualification(),
                    "target": target(address=options["address"]),
                },
                headers=headers,
            )
            assert preview.status_code == 200 and preview.json()["dispatch_admitted"] and not seen
            queued = await client.post(
                "/api/bacnet/hardware/survey",
                json=options | {"model_qualification": qualification()},
                headers=headers,
            )
            assert queued.status_code == 200, queued.text
            key = queued.json()["id"]
            await asyncio.wait_for(app.state.hardware_workbench.tasks[key], 10)
            response = await client.get("/api/bacnet/hardware/jobs/" + key)
            saved = response.json()
            assert (
                saved["status"] == "complete"
                and saved["model_transport_observation"]["model_text_status"] == "exact_text_match"
            )
            exported = await client.get("/api/bacnet/hardware/jobs/" + key + "/export")
            assert exported.status_code == 200 and json.loads(exported.content) == saved
            survey = (await client.get("/api/bacnet/hardware/reports/" + saved["report_id"])).json()
            assert (
                "model_transport_admission" not in survey
                and "model_transport_observation" not in survey
            )
            assert seen and not app.state.bacnet.commands
    restarted = create_app(state)
    async with restarted.router.lifespan_context(restarted):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://testserver"
        ) as client:
            assert (await client.get("/api/bacnet/hardware/jobs/" + key)).json() == saved
            assert not (await client.get("/api/session")).json()["field_network_open"]
