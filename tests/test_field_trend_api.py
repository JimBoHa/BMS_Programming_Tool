"""Production HTTP field sampling with a real isolated BACnet UDP device."""

import time

from bms_tool.app import create_app
from fastapi.testclient import TestClient

from .test_connections import application, free_udp, point


def test_http_field_sampling_reads_real_udp_then_retains_samples_without_restart_traffic(tmp_path):
    server_port = free_udp()
    target = f"127.0.0.1:{server_port}"
    with TestClient(create_app(tmp_path)) as client:
        server = client.portal.call(application, server_port, 4190025)

        def add_point():
            value = point()
            value.reliability = "no-fault-detected"
            server.add_object(value)

        client.portal.call(add_point)
        try:
            token = client.get("/api/session").json()["token"]
            headers = {"X-Studio-Token": token}
            job_config = {
                "points": [
                    {
                        "signal": "zone",
                        "address": target,
                        "object_id": "analog-value,1",
                        "unit": "degF",
                    }
                ],
                "interval_seconds": 5,
                "verify_quality": True,
                "name": "Loopback temperature",
            }
            assert client.post("/api/field-trends/start", json=job_config).status_code == 403
            assert (
                client.post("/api/field-trends/start", json=job_config, headers=headers).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/bacnet/connect",
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                    headers=headers,
                ).status_code
                == 200
            )
            response = client.post("/api/field-trends/start", json=job_config, headers=headers)
            assert response.status_code == 200, response.text
            job = response.json()
            deadline = time.monotonic() + 4
            samples = []
            while not samples and time.monotonic() < deadline:
                samples = client.get(
                    "/api/field-trends/samples", params={"source": job["source"]}
                ).json()
                time.sleep(0.02)
            assert len(samples) == 1
            assert samples[0]["source_kind"] == "field"
            assert samples[0]["quality"] == "good"
            assert samples[0]["value"] == 12.5 and samples[0]["unit"] == "degF"
            assert samples[0]["clock"] and samples[0]["recorded_at"]
            assert client.get("/api/observations/trends").json() == []
            stopped = client.post("/api/field-trends/stop", json={"id": job["id"]}, headers=headers)
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()["state"] == "stopped"
            assert not stopped.json()["running"]
            assert not client.get("/api/bacnet/status").json()["commands"]
            sources = client.get("/api/field-trends/sources").json()
            assert sources[0]["ended"] and sources[0]["source_kind"] == "field"
            events = client.get("/api/field-trends/events").json()
            assert [event["event"] for event in events] == ["started", "stopped"]
        finally:
            client.portal.call(server.close)
    with TestClient(create_app(tmp_path)) as client:
        status = client.get("/api/field-trends/status").json()
        assert status["jobs"] == [] and not status["auto_resume"]
        assert not client.get("/api/session").json()["field_network_open"]
        assert client.get("/api/field-trends/samples").json() == samples
        assert client.get("/api/field-trends/events").json() == events


def test_http_field_trend_validation_and_unknown_stop_have_no_network_side_effects(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for body in [
            {"points": []},
            {"points": [{"signal": "bad value", "address": "*", "object_id": "no-object"}]},
            {
                "points": [{"signal": "a", "address": "127.0.0.1", "object_id": "analog-input,1"}],
                "interval_seconds": 0,
            },
        ]:
            assert (
                client.post("/api/field-trends/start", json=body, headers=headers).status_code
                == 422
            )
        assert (
            client.post(
                "/api/field-trends/stop", json={"id": "unknown"}, headers=headers
            ).status_code
            == 422
        )
        assert client.get("/api/field-trends/samples?limit=1001").status_code == 422
        assert client.get("/api/field-trends/events?after=-1").status_code == 422
        assert client.get("/api/field-trends/status").json()["jobs"] == []
        assert not client.get("/api/bacnet/status").json()["connected"]
