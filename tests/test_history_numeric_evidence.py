"""Server bytes already preserve native float evidence and immutable captures."""

import asyncio
import hashlib
import json
import math

import pytest
from bms_tool.app import create_app
from bms_tool.bacnet_read import close_application
from httpx import ASGITransport, AsyncClient

from .history_evidence_fixtures import PROFILES, numeric_peer
from .test_connections import free_udp


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def numbers(report, profile):
    if profile == "history":
        return [row["value"] for row in report["records"]]
    if profile == "history-multiple":
        return [row["channels"][0]["raw"]["value"] for row in report["records"]]
    return [
        row["notification"]["event_values"]["value"]["exceedingValue"]
        for row in report["records"]
        if row["datum_type"] == "notification"
    ]


@pytest.mark.parametrize("profile", PROFILES)
async def test_http_numeric_evidence_and_saved_capture_seals_survive_restart(profile, tmp_path):
    port = free_udp()
    peer = numeric_peer(profile, port)
    app = create_app(tmp_path)
    object_id, device_id = PROFILES[profile]
    prefix = f"/api/bacnet/{profile}"
    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://127.0.0.1"
            ) as client:
                headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
                response = await client.post(
                    "/api/bacnet/connect",
                    headers=headers,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                )
                assert response.is_success, response.text
                body = {
                    "address": f"127.0.0.1:{port}",
                    "object_id": object_id,
                    "device_timezone": "UTC",
                    "mode": "sequence",
                    "reference": 100,
                    "count": 10,
                    "page_size": 2,
                }
                if profile != "history":
                    body.update(device=device_id, operation_id="numeric-evidence-read")
                response = await client.post(prefix + "/read", json=body, headers=headers)
                assert response.is_success, response.text
                report = json.loads(response.content)
                assert report["complete"], report
                values = numbers(report, profile)
                assert all(type(value) is float for value in values)
                assert values[0] == 2.0 and math.copysign(1, values[1]) == -1
                assert 0 < values[2] < 1e-6 and values[3] >= 1e20
                assert b"-0.0" in response.content and b"2.0" in response.content
                if profile != "history":
                    assert (
                        report["evidence_sha256"]
                        == hashlib.sha256(
                            canonical({k: v for k, v in report.items() if k != "evidence_sha256"})
                        ).hexdigest()
                    )
                saved = await client.post(
                    prefix + "/save", json={"id": report["id"]}, headers=headers
                )
                assert saved.is_success, saved.text
                assert saved.json()["sha256"] == hashlib.sha256(canonical(report)).hexdigest()
                count = len(peer.requests)
        restarted = create_app(tmp_path)
        async with restarted.router.lifespan_context(restarted):
            async with AsyncClient(
                transport=ASGITransport(app=restarted), base_url="http://127.0.0.1"
            ) as reader:
                original = await reader.get(prefix + "/captures/" + report["id"])
                assert original.is_success, original.text
                reopened = json.loads(original.content)
                assert canonical(reopened) == canonical(report)
                assert math.copysign(1, numbers(reopened, profile)[1]) == -1
                assert not (await reader.get("/api/session")).json()["field_network_open"]
                assert len(peer.requests) == count
    finally:
        close_application(peer)
        await asyncio.sleep(0.02)
