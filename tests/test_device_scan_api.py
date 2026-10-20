"""Scan and named inventory HTTP workflows against a real BACnet UDP device."""

import asyncio

import httpx
import pytest
from bacpypes3.object import ProgramObject
from bms_tool.app import create_app
from bms_tool.bacnet_read import close_application

from .test_connections import application, free_udp


@pytest.mark.parametrize("exposes_program", [True, False])
async def test_ip_scan_then_named_details_use_real_udp_without_device_writes(
    tmp_path, exposes_program
):
    port = free_udp()
    device = 4190801
    server = application(port, device)
    server.device_object.objectName = "North zone controller"
    server.device_object.description = "Zone description, not a program name"
    server.device_object.vendorName = "Independent UDP fixture"
    server.device_object.modelName = "VAV test controller"
    server.device_object.firmwareRevision = "6.2-test"
    server.device_object.applicationSoftwareVersion = "Application version 10.1"
    if exposes_program:
        server.add_object(
            ProgramObject(
                objectIdentifier=("program", 17),
                objectName="Cooling only sequence",
                description="Real exposed Program object",
                programState="idle",
                programChange="ready",
            )
        )
    requests = []
    original = server.indication

    async def observed(request):
        requests.append(type(request).__name__)
        await original(request)

    server.indication = observed
    app = create_app(tmp_path / "http-scans")
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
                assert (await client.get("/api/bacnet/ip-scan-profile")).status_code == 200
                assert (await client.get("/api/bacnet/device-details/profile")).json()["read_only"]
                opened = await client.post(
                    "/api/bacnet/connect",
                    headers=headers,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                )
                assert opened.status_code == 200, opened.text
                discovered = await client.post(
                    "/api/bacnet/scan-ip",
                    headers=headers,
                    json={
                        "mode": "single",
                        "ip": "127.0.0.1",
                        "udp_port": port,
                        "timeout_seconds": 1.0,
                    },
                )
                assert discovered.status_code == 200, discovered.text
                rows = discovered.json()["devices"]
                assert len(rows) == 1 and rows[0]["device_instance"] == device
                assert rows[0]["address"] == f"127.0.0.1:{port}"
                details = await client.post(
                    "/api/bacnet/device-details",
                    headers=headers,
                    json={"address": rows[0]["address"], "device": rows[0]["device"]},
                )
                assert details.status_code == 200, details.text
                result = details.json()
                assert result["identity_verified"]
                assert result["properties"]["object-name"] == "North zone controller"
                assert result["properties"]["model-name"] == "VAV test controller"
                assert (
                    result["properties"]["application-software-version"]
                    == "Application version 10.1"
                )
                assert result["program_names"] == (
                    ["Cooling only sequence"] if exposes_program else []
                )
                assert result["programs_status"] == (
                    "exposed" if exposes_program else "not_exposed"
                )
                assert "Zone description, not a program name" not in result["program_names"]
                assert (
                    await client.post("/api/bacnet/disconnect", json={}, headers=headers)
                ).status_code == 200
                assert not (await client.get("/api/bacnet/status")).json()["commands"]
    finally:
        close_application(server)
        await asyncio.sleep(0.05)
    assert requests and set(requests) <= {"WhoIsRequest", "ReadPropertyRequest"}


async def test_scan_and_device_detail_http_guards_do_not_open_an_interface(tmp_path):
    app = create_app(tmp_path / "http-scan-guards")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            for endpoint, body in (
                ("/api/bacnet/scan-ip", {"mode": "single", "ip": "127.0.0.1"}),
                ("/api/bacnet/device-details", {"address": "127.0.0.1", "device": "device,17"}),
            ):
                for unsafe in (
                    {},
                    headers | {"Origin": "https://untrusted.example"},
                    headers | {"Host": "untrusted.example"},
                ):
                    assert (
                        await client.post(endpoint, json=body, headers=unsafe)
                    ).status_code == 403
                response = await client.post(endpoint, json=body, headers=headers)
                assert response.status_code == 422, response.text
            for invalid in (
                {"mode": "range", "start_ip": "192.0.2.10", "end_ip": "192.0.2.1"},
                {"mode": "single", "ip": "example.com"},
                {"mode": "single", "ip": "192.0.2.1", "udp_port": True},
                {
                    "mode": "range",
                    "start_ip": "192.0.2.1",
                    "end_ip": "192.0.2.2",
                    "cursor_ip": "192.0.2.3",
                },
            ):
                assert (
                    await client.post("/api/bacnet/scan-ip", json=invalid, headers=headers)
                ).status_code == 422
            assert not (await client.get("/api/bacnet/status")).json()["connected"]
