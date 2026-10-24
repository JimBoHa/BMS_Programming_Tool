"""Session-guarded HTTP lifecycle against real BACnet UDP peers."""

import httpx
from bms_tool.app import create_app

from .test_bacnet_cov import network as network
from .test_bacnet_cov import wait_for
from .test_connections import free_udp


async def test_http_idle_security_start_notifications_renew_stop_export_and_shutdown(
    network, tmp_path
):
    server, analog, _, _, config = network
    app = create_app(tmp_path / "http")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            assert (await client.get("/api/bacnet/cov/status")).json()["jobs"] == []
            assert not (await client.get("/api/session")).json()["field_network_open"]
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            assert (await client.post("/api/bacnet/cov/start", json=config)).status_code == 403
            assert (
                await client.post("/api/bacnet/cov/start", json=config, headers=headers)
            ).status_code == 422
            opened = await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{free_udp()}"},
                headers=headers,
            )
            assert opened.status_code == 200
            assert (
                await client.post(
                    "/api/bacnet/cov/start", json=config | {"lifetime": 0}, headers=headers
                )
            ).status_code == 422
            started = await client.post("/api/bacnet/cov/start", json=config, headers=headers)
            assert started.status_code == 200, started.text
            identifier = started.json()["id"]
            await wait_for(lambda: app.state.bacnet_cov.jobs[identifier]["received"] > 0)
            detail = (await client.get(f"/api/bacnet/cov/jobs/{identifier}")).json()
            assert detail["events"][0]["values"][0]["value"] == 12.5
            renewed = await client.post(
                "/api/bacnet/cov/renew", json={"id": identifier}, headers=headers
            )
            assert renewed.status_code == 200 and renewed.json()["active"]
            stopped = await client.post(
                "/api/bacnet/cov/stop", json={"id": identifier}, headers=headers
            )
            assert stopped.status_code == 200 and stopped.json()["state"] == "stopped"
            assert not server._cov_detections
            await client.post("/api/bacnet/cov/start", json=config, headers=headers)
            assert analog.presentValue == 12.5 and not app.state.bacnet.commands
    assert not server._cov_detections and not app.state.bacnet_cov._hooks
    assert not app.state.bacnet.status()["connected"]
