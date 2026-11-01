"""Production HTTP, kernel TTY and authored read-only MS/TP services."""

import copy
import math
import threading
import time

import pytest
from bms_tool.app import create_app
from fastapi.testclient import TestClient

from .serial_monitor_peer import MonitoringWirePeer
from .test_mstp_connection import serial_path as serial_path


def context(config):
    return {
        "controller_target": {
            "transport": "direct-mstp",
            "address": "1",
            "device": "device,123",
            "router": None,
            "dnet": None,
        },
        "expected_connector_config": config,
    }


def test_serial_monitoring_does_not_admit_native_backup_on_the_serial_interface(serial_client):
    client, headers, peer, app, _ = serial_client
    configured = client.post(
        "/api/bacnet/controller/native-application/credentials",
        headers=headers,
        json={"backup": "authored-backup", "restore": "authored-restore"},
    )
    assert configured.status_code == 200, configured.text
    before = list(peer.requests)
    response = client.post(
        "/api/bacnet/controller/native-application/capture",
        headers=headers,
        json={"address": "1", "device": "device,123", "operation_id": "serial_native_refused"},
    )
    assert response.status_code == 422 and "IPv4" in response.text, response.text
    assert peer.requests == before and not app.state.bacnet.app._requests


@pytest.fixture
def serial_client(serial_path, tmp_path):
    fd, path = serial_path
    peer = MonitoringWirePeer(fd)
    app = create_app(tmp_path)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        opened = client.post(
            "/api/bacnet/connect-mstp",
            headers=headers,
            json={"port": path, "mac": 0, "max_master": 1},
        )
        assert opened.status_code == 200, opened.text
        peer.thread.start()
        try:
            yield client, headers, peer, app, opened.json()
        finally:
            app.state.bacnet.close()
            peer.close()


@pytest.mark.parametrize("mode", ["sequence", "position", "time"])
def test_selected_serial_history_over_kernel_tty_keeps_full_source_and_exact_values(
    serial_client, mode
):
    client, headers, peer, app, config = serial_client
    body = {
        "address": "1",
        "object_id": "trend-log,1",
        "mode": mode,
        "count": 3,
        "page_size": 2,
        "device_timezone": "UTC",
        **context(config),
    }
    if mode == "time":
        body["reference_time"] = "2026-10-31T12:00:00Z"
    else:
        body["reference"] = 100 if mode == "sequence" else 1
    response = client.post("/api/bacnet/history/read", headers=headers, json=body)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["identity_verified"] and report["complete"] and not report["errors"]
    assert report["connector_config"] == config
    assert report["controller_target"]["transport"] == "direct-mstp"
    assert [r["value"] for r in report["records"]] == [-0.0, 1.25, 2.25]
    assert math.copysign(1, report["records"][0]["value"]) == -1
    assert len(peer.ranges) == 2
    assert set(peer.requests) == {"ReadPropertyRequest", "ReadRangeRequest"}
    assert not app.state.bacnet.app._requests
    before = list(peer.requests)
    saved = client.post("/api/bacnet/history/save", headers=headers, json={"id": report["id"]})
    assert saved.status_code == 200, saved.text
    loaded = client.get(f"/api/bacnet/history/captures/{report['id']}")
    assert loaded.status_code == 200 and loaded.json() == report
    assert peer.requests == before


def sampling_body(config):
    return {
        "name": "Authored serial poll",
        "interval_seconds": 5.0,
        "verify_quality": True,
        "points": [
            {"signal": "temperature", "address": "1", "object_id": "analog-input,1", "unit": "degC"}
        ],
        **context(config),
    }


def wait_job(client, id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = next(
            row for row in client.get("/api/field-trends/status").json()["jobs"] if row["id"] == id
        )
        if job["samples"] or job["failures"] or not job["running"]:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Serial poll did not finish its first cycle: {job}")


def test_selected_serial_poll_publishes_verified_quality_and_original_bus_context(serial_client):
    client, headers, peer, app, config = serial_client
    started = client.post("/api/field-trends/start", headers=headers, json=sampling_body(config))
    assert started.status_code == 200, started.text
    job = wait_job(client, started.json()["id"])
    assert job["samples"] == 1 and job["running"], job
    assert (
        client.post("/api/field-trends/stop", headers=headers, json={"id": job["id"]}).status_code
        == 200
    )
    rows = app.state.field_trends.store.trends(source=job["source"])
    assert len(rows) == 1 and rows[0]["quality"] == "good"
    assert math.copysign(1, rows[0]["value"]) == -1
    assert rows[0]["provenance"]["controller_target"] == context(config)["controller_target"]
    assert rows[0]["provenance"]["connector_config"] == config
    assert peer.device_checks == 2 and set(peer.requests) == {"ReadPropertyRequest"}
    assert not app.state.bacnet.commands and not app.state.bacnet.app._requests


@pytest.mark.parametrize("failure", ["device_after", "object"])
def test_serial_poll_discards_staged_samples_when_identity_changes(serial_client, failure):
    client, headers, peer, app, config = serial_client
    if failure == "device_after":
        peer.fail_device_after = 2
    else:
        peer.object_identity = "analog-input,2"
    started = client.post("/api/field-trends/start", headers=headers, json=sampling_body(config))
    assert started.status_code == 200, started.text
    job = wait_job(client, started.json()["id"])
    assert job["samples"] == 0 and not app.state.field_trends.store.trends(source=job["source"]), (
        job
    )
    assert job["last_error"] or job["recent_errors"]
    assert (
        client.post("/api/field-trends/stop", headers=headers, json={"id": job["id"]}).status_code
        == 200
    )
    assert not app.state.bacnet.commands


@pytest.mark.parametrize(
    "kind,object,name",
    [
        ("value", "analog-input,1", "Serial temperature"),
        ("trend-log", "trend-log,1", "Serial temperature history"),
    ],
)
def test_serial_choices_come_from_actual_indexed_object_list_and_names(
    serial_client, kind, object, name
):
    client, headers, peer, app, config = serial_client
    response = client.post(
        "/api/bacnet/controller/monitoring/choices",
        headers=headers,
        json={**context(config), "kind": kind},
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["identity_verified"] and report["complete"] and not report["errors"], report
    assert report["rows"] == [
        {"object": object, "name": name, "index": 2 if kind == "value" else 3}
    ]
    assert (
        report["target"] == context(config)["controller_target"]
        and report["connector_config"] == config
    )
    assert report["total"] == 3 and report["next_offset"] is None
    assert set(peer.requests) == {"ReadPropertyRequest"} and peer.device_checks == 2
    assert not app.state.bacnet.app._requests


def test_serial_choice_pages_do_not_invent_objects_outside_the_observed_page(serial_client):
    client, headers, peer, app, config = serial_client
    response = client.post(
        "/api/bacnet/controller/monitoring/choices",
        headers=headers,
        json={**context(config), "kind": "value", "offset": 0, "limit": 1},
    )
    report = response.json()
    assert response.status_code == 200 and report["identity_verified"], response.text
    assert report["rows"] == [] and report["next_offset"] == 1
    peer.fail_device_after = peer.device_checks + 2
    response = client.post(
        "/api/bacnet/controller/monitoring/choices",
        headers=headers,
        json={**context(config), "kind": "value", "offset": 1, "limit": 1},
    )
    report = response.json()
    assert response.status_code == 200 and not report["identity_verified"], response.text
    assert report["rows"] == [] and report["errors"]


@pytest.mark.parametrize(
    "change",
    [
        "own_mac",
        "broadcast",
        "leading_zero",
        "router",
        "port",
        "local_mac",
        "boolean_mac",
        "float_baudrate",
        "baudrate",
        "instance",
        "unpaired",
        "missing_marker",
        "limit",
        "offset",
        "unknown_field",
    ],
)
def test_bad_serial_choice_context_is_refused_before_any_application_request(serial_client, change):
    client, headers, peer, app, config = serial_client
    body = copy.deepcopy({**context(config), "kind": "value"})
    if change == "own_mac":
        body["controller_target"]["address"] = "0"
    elif change == "broadcast":
        body["controller_target"]["address"] = "255"
    elif change == "leading_zero":
        body["controller_target"]["address"] = "01"
    elif change == "router":
        body["controller_target"].update(router="127.0.0.1:47808", dnet=1)
    elif change in ("port", "local_mac", "baudrate", "instance"):
        key = "mac" if change == "local_mac" else change
        body["expected_connector_config"][key] = (
            "/dev/another"
            if change == "port"
            else 1
            if change == "local_mac"
            else 76800
            if change == "baudrate"
            else 41
        )
    elif change == "boolean_mac":
        body["expected_connector_config"]["mac"] = False
    elif change == "float_baudrate":
        body["expected_connector_config"]["baudrate"] = 38400.0
    elif change == "unpaired":
        body.pop("expected_connector_config")
    elif change == "missing_marker":
        body["controller_target"].pop("transport")
    elif change == "limit":
        body["limit"] = 17
    elif change == "offset":
        body["offset"] = True
    else:
        body["irrelevant"] = "ignored intent is forbidden"
    before = list(peer.requests)
    response = client.post("/api/bacnet/controller/monitoring/choices", headers=headers, json=body)
    assert response.status_code == 422, response.text
    assert peer.requests == before and not app.state.bacnet.commands


def test_serial_choice_token_and_acquisition_context_do_not_widen_other_read_profiles(
    serial_client,
):
    client, headers, peer, app, config = serial_client
    body = {**context(config), "kind": "value"}
    assert client.post("/api/bacnet/controller/monitoring/choices", json=body).status_code == 403
    for route in [
        "/api/bacnet/device-details",
        "/api/bacnet/controller/inventory",
        "/api/bacnet/controller/properties",
    ]:
        response = client.post(route, headers=headers, json=context(config)["controller_target"])
        assert response.status_code == 422, response.text
    assert not peer.requests


def test_serial_choices_keep_verified_object_identity_when_native_name_is_unavailable(
    serial_client,
):
    client, headers, peer, app, config = serial_client
    peer.name_missing = True
    response = client.post(
        "/api/bacnet/controller/monitoring/choices",
        headers=headers,
        json={**context(config), "kind": "value"},
    )
    report = response.json()
    assert response.status_code == 200 and report["identity_verified"], response.text
    assert report["rows"] == [{"object": "analog-input,1", "name": "", "index": 2}]
    assert report["warnings"] and not report["errors"]


def test_pending_serial_poll_cannot_resume_on_a_reopened_identical_configuration(serial_client):
    client, headers, peer, app, config = serial_client
    entered = threading.Event()

    def hold_present_value(request):
        if str(request.propertyIdentifier) == "present-value":
            peer.drop = True
            entered.set()

    peer.on_request = hold_present_value
    started = client.post("/api/field-trends/start", headers=headers, json=sampling_body(config))
    assert started.status_code == 200, started.text
    assert entered.wait(5), "The independent peer never received the requested value read."
    old_app = app.state.bacnet.app
    closed = client.post("/api/bacnet/disconnect", headers=headers, json={})
    assert closed.status_code == 200, closed.text
    peer.drop = False
    peer.on_request = None
    reopened = client.post(
        "/api/bacnet/connect-mstp",
        headers=headers,
        json={key: value for key, value in config.items() if key != "transport"},
    )
    assert reopened.status_code == 200 and reopened.json() == config, reopened.text
    assert app.state.bacnet.app is not old_app
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = next(
            row
            for row in client.get("/api/field-trends/status").json()["jobs"]
            if row["id"] == started.json()["id"]
        )
        if not job["running"]:
            break
        time.sleep(0.01)
    assert not job["running"] and not job["samples"], job
    assert not app.state.field_trends.store.trends(source=job["source"])
    assert not old_app._requests and not old_app.mstp_link.status()["worker_alive"]
    assert not app.state.bacnet.commands
