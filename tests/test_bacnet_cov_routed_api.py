"""HTTP routed subscription against the actual UDP/virtual network fixture."""

import httpx
from bms_tool.app import create_app

from .test_bacnet_cov import wait_for
from .test_bacnet_cov_routed import routed_cov as routed_cov
from .test_connections import free_udp


async def test_http_routed_subscription_preserves_source_and_shutdown_cancellation(
    routed_cov, tmp_path
):
    _, field, _, _, _, config, _ = routed_cov
    app = create_app(tmp_path / "http-routed")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            started = await client.post("/api/bacnet/cov/start", headers=headers, json=config)
            assert started.status_code == 200, started.text
            identifier = started.json()["id"]
            await wait_for(lambda: app.state.bacnet_cov.jobs[identifier]["received"] > 0)
            detail = (await client.get(f"/api/bacnet/cov/jobs/{identifier}")).json()
            assert detail["events"][0]["route"]["next_hop"] == config["router"]
            assert detail["events"][0]["values"][0]["value"] == 12.5
    assert not field._cov_detections and not app.state.bacnet_cov._route_hooks
