"""Actual PTY read services, explicit transport guards and durable serial evidence."""

import asyncio
import csv
import io
import json

import httpx
import pytest
from bms_tool.app import create_app
from bms_tool.device_details import DeviceDetailsRequest
from bms_tool.hardware_survey import HardwareSurvey, validate_report
from bms_tool.hardware_target import HardwareTargetRequest
from bms_tool.hardware_workbench import canonical
from bms_tool.storage import Store

from tests.mstp_survey_peer import SurveyWirePeer
from tests.test_hardware_workbench_api import offline_report, session, wait_job
from tests.test_mstp_connection import serial_path as serial_path

TARGET = {"transport": "direct-mstp", "address": "1", "device": "device,123"}


@pytest.mark.parametrize("address", ["0", "1", "127", "128", "254"])
def test_explicit_direct_serial_targets_allow_unicast_station_range(address):
    assert HardwareTargetRequest(**(TARGET | {"address": address})).address == address


@pytest.mark.parametrize(
    "change",
    [
        {"address": "255"},
        {"address": "256"},
        {"address": "-1"},
        {"address": "01"},
        {"address": "0x01"},
        {"address": "*"},
        {"address": "1:*"},
        {"address": "3101:1"},
        {"address": "127.0.0.1"},
        {"address": " 1"},
        {"device": "device,4194303"},
        {"device": "analog-input,1"},
        {"router": "127.0.0.1", "dnet": 3101},
    ],
)
def test_serial_targets_reject_broadcast_routing_ambiguity_and_wildcard_devices(change):
    with pytest.raises(ValueError):
        HardwareTargetRequest(**(TARGET | change))


def test_serial_opt_in_does_not_broaden_shared_device_details_or_infer_from_missing_transport():
    with pytest.raises(ValueError):
        DeviceDetailsRequest(**TARGET)
    with pytest.raises(ValueError):
        HardwareTargetRequest(address="1", device="device,123")
    old = offline_report()["target"]
    assert HardwareTargetRequest(**old).transport == "bacnet-ip"


async def test_real_pty_survey_archive_jobs_json_csv_and_restart_preserve_interface_identity(
    serial_path, tmp_path
):
    master, path = serial_path
    peer = SurveyWirePeer(master)
    app = create_app(tmp_path)
    base = "/api/bacnet/hardware"
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = await session(client)
            before = await client.post(base + "/survey", json=TARGET, headers=headers)
            assert before.status_code == 422
            opened = await client.post(
                "/api/bacnet/connect-mstp",
                json={"port": path, "mac": 0, "max_master": 1},
                headers=headers,
            )
            assert opened.status_code == 200, opened.text
            config = opened.json()
            peer.thread.start()
            try:
                started = await client.post(
                    base + "/survey",
                    json=TARGET | {"property_timeout": 0.8, "timeout_seconds": 30},
                    headers=headers,
                )
                assert started.status_code == 200, started.text
                assert started.json()["connector_config"] == config
                job = await wait_job(client, started.json()["id"])
                assert job["status"] == "complete", job
                report = job["report"]
                assert report["connector_config"] == config
                assert report["target"]["transport"] == "direct-mstp"
                assert report["identity"]["object"] == "device,123"
                assert report["inventory"]["complete"]
                analog, binary = report["inputs"]
                assert analog["present_value"] == -12.5 and analog["units"] == 64
                assert analog["reliability"] == 0 and analog["out_of_service"] is False
                assert (
                    binary["present_value"] == 1 and binary["sa_mac"] == 4 and binary["slot"] == 4
                )
                rows = list(
                    csv.DictReader(
                        io.StringIO(
                            (
                                await client.get(
                                    base + f"/reports/{report['id']}/export?format=csv"
                                )
                            ).content.decode("utf-8-sig")
                        )
                    )
                )
                assert (
                    rows[0]["transport"] == "direct-mstp"
                    and json.loads(rows[0]["connector_config"]) == config
                )
                assert (await client.get(base + f"/reports/{report['id']}/export")).json() == report
                started_archive = await client.post(
                    base + "/read-archive", json={"report_id": report["id"]}, headers=headers
                )
                assert started_archive.status_code == 200, started_archive.text
                archive_job = await wait_job(client, started_archive.json()["id"])
                assert archive_job["status"] == "complete", archive_job
                receipt = archive_job["archive"]["origin"]
                assert (
                    receipt["connector_config"] == config
                    and receipt["target"]["transport"] == "direct-mstp"
                )
                assert receipt["complete"] and not receipt["controller_writes"]
                source = await client.get(
                    base + f"/archives/{archive_job['archive_id']}/export?format=source"
                )
                assert source.content == peer.payload
                assert len(peer.atomic_offsets) >= 2
                assert set(peer.requests) == {
                    "ReadPropertyMultipleRequest",
                    "AtomicReadFileRequest",
                }
                assert (
                    not app.state.bacnet.commands
                    and not app.state.bacnet.app.asap.clientTransactions
                )
            finally:
                app.state.bacnet.close()
                peer.close()
    reopened = create_app(tmp_path)
    async with reopened.router.lifespan_context(reopened):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=reopened), base_url="http://testserver"
        ) as client:
            state = (await client.get(base + "/status")).json()
            assert len(state["reports"]) == 2 and len(state["archives"]) == 1
            assert not reopened.state.bacnet.status()["connected"]
            assert (await client.get(base + f"/jobs/{job['id']}")).json()[
                "connector_config"
            ] == config
            assert (await client.get(base + f"/reports/{report['id']}")).json() == report
            assert (
                await client.get(
                    base + f"/archives/{archive_job['archive_id']}/export?format=source"
                )
            ).content == peer.payload


async def test_actual_serial_read_property_fallback_preserves_native_types(serial_path, tmp_path):
    master, path = serial_path
    peer = SurveyWirePeer(master)
    peer.reject_rpm = True
    app = create_app(tmp_path)
    await app.state.bacnet.connect_mstp(path, 0, max_master=1)
    peer.thread.start()
    try:
        report = await HardwareSurvey(app.state.bacnet, Store(tmp_path)).survey(
            TARGET | {"property_timeout": 0.8, "timeout_seconds": 30}
        )
        assert report["status"] == "complete", report
        assert report["inputs"][0]["present_value"] == -12.5
        assert set(peer.requests) == {"ReadPropertyMultipleRequest", "ReadPropertyRequest"}
        assert any("rpm_fallback_reason" in row for row in report["inputs"][0]["properties"])
        assert validate_report(report)["connector_config"]["port"] == path
    finally:
        app.state.bacnet.close()
        peer.close()


@pytest.mark.parametrize("fault", ["wrong-source", "wrong-device", "interface-changed"])
async def test_actual_pty_rejects_wrong_source_device_and_interface_change(
    serial_path, tmp_path, fault
):
    master, path = serial_path
    peer = SurveyWirePeer(master)
    app = create_app(tmp_path)
    await app.state.bacnet.connect_mstp(path, 0, max_master=1)
    if fault == "wrong-source":
        peer.reply_source = 2
    elif fault == "wrong-device":
        peer.identity = "device,124"
    else:
        peer.on_request = lambda request: app.state.bacnet.config.update(max_info_frames=2)
    peer.thread.start()
    try:
        report = await HardwareSurvey(app.state.bacnet, Store(tmp_path)).survey(
            TARGET
            | {"property_timeout": 0.15 if fault == "wrong-source" else 0.8, "timeout_seconds": 5}
        )
        assert report["status"] == "error" and not report["identity"] and not report["inputs"]
        assert not report["candidates"]
        assert report["connector_config"]["max_info_frames"] == 1
        assert not app.state.bacnet.app.asap.clientTransactions
        request_count = len(peer.requests)
        await asyncio.sleep(0.2)
        assert len(peer.requests) == request_count
        assert set(peer.requests) <= {"ReadPropertyMultipleRequest", "ReadPropertyRequest"}
        if fault != "wrong-source":
            assert request_count == 1
    finally:
        app.state.bacnet.close()
        peer.close()


async def test_cancel_real_pending_serial_read_retains_partial_and_rejects_archive_after_interface_change(
    serial_path, tmp_path
):
    import threading

    master, path = serial_path
    peer = SurveyWirePeer(master)
    app = create_app(tmp_path)
    pending_binary = threading.Event()

    def hold_binary(request):
        if (
            getattr(request, "listOfReadAccessSpecs", None)
            and str(request.listOfReadAccessSpecs[0].objectIdentifier) == "binary-input,55"
        ):
            peer.drop = True
            pending_binary.set()

    peer.on_request = hold_binary
    base = "/api/bacnet/hardware"
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = await session(client)
            config = (
                await client.post(
                    "/api/bacnet/connect-mstp",
                    json={"port": path, "mac": 0, "max_master": 1},
                    headers=headers,
                )
            ).json()
            peer.thread.start()
            try:
                for bad in (
                    TARGET | {"address": "0"},
                    {"address": "1", "device": "device,123"},
                    TARGET | {"transport": "bacnet-ip", "address": "127.0.0.1"},
                ):
                    response = await client.post(base + "/survey", json=bad, headers=headers)
                    assert response.status_code == 422
                assert not peer.requests
                started = (
                    await client.post(
                        base + "/survey", json=TARGET | {"timeout_seconds": 20}, headers=headers
                    )
                ).json()
                assert await asyncio.to_thread(pending_binary.wait, 3)
                cancelled = await client.post(
                    base + f"/jobs/{started['id']}/cancel", json={}, headers=headers
                )
                assert cancelled.status_code == 200, cancelled.text
                job = cancelled.json()
                assert job["status"] == "cancelled"
                assert job["report"]["connector_config"] == config
                assert not job["report"]["inventory"]["complete"]
                assert job["report"]["inputs"][0]["present_value"] == -12.5
                assert not any(row["status"] == "candidate" for row in job["report"]["candidates"])
                assert not app.state.bacnet.app.asap.clientTransactions
                count = len(peer.requests)
                await asyncio.sleep(0.2)
                assert len(peer.requests) == count
                # The same healthy interface can perform another explicitly requested survey.
                peer.drop = False
                peer.on_request = None
                fresh = await client.post(base + "/survey", json=TARGET, headers=headers)
                report = (await wait_job(client, fresh.json()["id"]))["report"]
                assert report["inventory"]["complete"]
                # Change a real connector policy through its API. Saved serial evidence
                # must never silently migrate to that newly opened interface identity.
                changed = await client.post(
                    "/api/bacnet/connect-mstp",
                    json={"port": path, "mac": 0, "max_master": 1, "max_info_frames": 2},
                    headers=headers,
                )
                assert changed.status_code == 200, changed.text
                count = len(peer.requests)
                refused = await client.post(
                    base + "/read-archive", json={"report_id": report["id"]}, headers=headers
                )
                assert refused.status_code == 422 and "differs" in refused.text
                assert len(peer.requests) == count
                assert not app.state.bacnet.commands
            finally:
                app.state.bacnet.close()
                peer.close()


async def test_serial_deadline_retains_typed_partial_evidence(serial_path, tmp_path):
    master, path = serial_path
    peer = SurveyWirePeer(master)
    app = create_app(tmp_path)
    await app.state.bacnet.connect_mstp(path, 0, max_master=1)

    def drop_binary(request):
        if (
            getattr(request, "listOfReadAccessSpecs", None)
            and str(request.listOfReadAccessSpecs[0].objectIdentifier) == "binary-input,55"
        ):
            peer.drop = True

    peer.on_request = drop_binary
    peer.thread.start()
    try:
        result = await HardwareSurvey(app.state.bacnet, Store(tmp_path)).survey(
            TARGET | {"timeout_seconds": 1.5}
        )
        assert result["status"] == "partial"
        assert (
            result["identity"]["object"] == "device,123"
            and result["inputs"][0]["present_value"] == -12.5
        )
        assert result["connector_config"]["port"] == path
        assert any("time limit" in row.get("error", "") for row in result["errors"])
        assert all(row["status"] != "candidate" for row in result["candidates"])
        assert not app.state.bacnet.app.asap.clientTransactions
        validate_report(result)
    finally:
        app.state.bacnet.close()
        peer.close()


@pytest.mark.parametrize("routed", [False, True])
async def test_preexisting_ipv4_reports_jobs_and_archive_seals_reopen_without_transport_or_rewrites(
    tmp_path, routed
):
    import hashlib
    from pathlib import Path

    from bms_tool.hardware_survey import analyze_archive
    from bms_tool.hardware_workbench import digest

    from tests.test_hardware_survey import authored_archive

    directory = tmp_path / "hardware-workbench"
    directory.mkdir()
    old = offline_report()
    if routed:
        old["target"] = {
            "address": "3101:9",
            "device": "device,123",
            "router": "198.51.100.20",
            "dnet": 3101,
        }
    old.update(id="a" * 32, origin="live-read", saved_at="2026-01-01T00:00:00Z")
    old["content_sha256"] = digest(
        {
            key: value
            for key, value in old.items()
            if key not in ("content_sha256", "id", "saved_at")
        }
    )
    job = {
        "id": "b" * 32,
        "status": "complete",
        "kind": "survey",
        "target": old["target"],
        "report_id": old["id"],
        "report": old,
        "read_only": True,
    }
    archive = analyze_archive(authored_archive())
    archive.update(id="c" * 32, saved_at="2026-01-01T00:00:00Z")
    archive["origin"] = {
        "kind": "existing-controller-file",
        "target": old["target"],
        "complete": True,
        "sha256": hashlib.sha256(authored_archive()).hexdigest(),
    }
    paths = {}
    for kind, key, value in (
        ("report", old["id"], old),
        ("job", job["id"], job),
        ("archive", archive["id"], archive),
    ):
        path = directory / f"{kind}-{key}.json"
        # Authored exact pre-feature wrapper, with no transport/config fields.
        path.write_bytes(canonical({"sha256": digest(value), "data": value}))
        paths[path] = path.read_bytes()
    source = directory / ("source-" + archive["id"] + ".bin")
    source.write_bytes(authored_archive())
    paths[source] = source.read_bytes()
    for _ in range(2):
        app = create_app(tmp_path)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                base = "/api/bacnet/hardware"
                assert (await client.get(base + f"/reports/{old['id']}")).json() == old
                assert (await client.get(base + f"/jobs/{job['id']}")).json() == job
                assert (await client.get(base + f"/archives/{archive['id']}")).json() == archive
                assert (
                    await client.get(base + f"/archives/{archive['id']}/export?format=source")
                ).content == authored_archive()
                assert (await client.get(base + f"/reports/{old['id']}/export")).json()[
                    "content_sha256"
                ] == old["content_sha256"]
                assert (await client.get(base + "/status")).status_code == 200
                assert not app.state.bacnet.status()["connected"]
                assert validate_report(old)["target"]["transport"] == "bacnet-ip"
    assert all(Path(path).read_bytes() == original for path, original in paths.items())


async def test_queued_serial_job_does_not_migrate_before_first_read(serial_path, tmp_path):
    master, path = serial_path
    peer = SurveyWirePeer(master)
    app = create_app(tmp_path)
    await app.state.bacnet.connect_mstp(path, 0, max_master=1)
    peer.thread.start()
    try:
        workbench = app.state.hardware_workbench
        started = workbench.start("survey", TARGET)
        saved_config = started["connector_config"].copy()
        app.state.bacnet.config["max_info_frames"] = 2
        await workbench.tasks[started["id"]]
        job = workbench.job(started["id"])
        assert job["status"] == "error" and job["connector_config"] == saved_config
        assert not peer.requests and not app.state.bacnet.app.asap.clientTransactions
    finally:
        app.state.bacnet.close()
        peer.close()


async def test_changed_serial_link_during_archive_read_saves_no_partial_source(
    serial_path, tmp_path
):
    from bacpypes3.apdu import AtomicReadFileRequest

    master, path = serial_path
    peer = SurveyWirePeer(master)
    app = create_app(tmp_path)
    await app.state.bacnet.connect_mstp(path, 0, max_master=1)
    peer.thread.start()
    try:
        workbench = app.state.hardware_workbench
        survey = workbench.start("survey", TARGET)
        await workbench.tasks[survey["id"]]
        original = workbench.job(survey["id"])["report"]

        def change(request):
            if isinstance(request, AtomicReadFileRequest):
                app.state.bacnet.config["max_info_frames"] = 2

        peer.on_request = change
        job = workbench.start("archive-read", {"report_id": original["id"]})
        await workbench.tasks[job["id"]]
        completed = workbench.job(job["id"])
        assert completed["status"] == "error"
        assert workbench.report(original["id"]) == original
        assert not list(workbench.directory.glob("source-*.bin"))
        assert len(peer.atomic_offsets) == 1
        assert not app.state.bacnet.app.asap.clientTransactions
    finally:
        app.state.bacnet.close()
        peer.close()
