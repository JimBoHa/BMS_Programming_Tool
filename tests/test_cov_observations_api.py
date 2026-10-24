"""Opt-in persistence over guarded HTTP and actual direct/routed UDP peers."""

import httpx
import pytest
from bms_tool.app import create_app

from .test_bacnet_cov import network as network
from .test_bacnet_cov import wait_for
from .test_bacnet_cov_routed import routed_cov as routed_cov
from .test_connections import free_udp


@pytest.mark.parametrize("routed", [False, True])
async def test_optin_durable_api_paging_interface_closure_and_restart_stays_off(
    network, routed_cov, tmp_path, routed
):
    _, _, _, _, config = network
    if routed:
        _, _, _, _, _, config, _ = routed_cov
    directory = tmp_path / "saved-api"
    app = create_app(directory)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            assert (await client.get("/api/bacnet/cov/recordings")).json() == []
            token = (await client.get("/api/session")).json()["token"]
            headers = {"X-Studio-Token": token}
            body = config | {"record_observations": True}
            assert (await client.post("/api/bacnet/cov/start", json=body)).status_code == 403
            assert (
                await client.post("/api/bacnet/cov/start", json=body, headers=headers)
            ).status_code == 422
            await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{free_udp()}"},
                headers=headers,
            )
            invalid = await client.post(
                "/api/bacnet/cov/start",
                json=config | {"record_observations": "yes"},
                headers=headers,
            )
            assert invalid.status_code == 422
            response = await client.post("/api/bacnet/cov/start", json=body, headers=headers)
            assert response.status_code == 200, response.text
            identifier = response.json()["id"]
            job = app.state.bacnet_cov.jobs[identifier]
            await wait_for(lambda: job["recording"]["recorded"] > 0)
            await app.state.bacnet_cov.recorder.flush()
            rows = (await client.get("/api/bacnet/cov/recordings")).json()
            assert rows[0]["metadata"]["config"]["router"] == config.get("router")
            assert rows[0]["metadata"]["process_id"] == job["process_id"]
            page = (
                await client.get(f"/api/bacnet/cov/recordings/{identifier}/events?limit=1")
            ).json()
            assert len(page) == 1 and page[0]["event"] == "recording_started"
            remaining = (
                await client.get(
                    f"/api/bacnet/cov/recordings/{identifier}/events?after={page[0]['sequence']}"
                )
            ).json()
            assert any(row["event"] == "notification" for row in remaining)
            assert all(
                row["clock_basis"] == "receipt" and row["source_clock"] is None for row in remaining
            )
            assert (
                await client.get(f"/api/bacnet/cov/recordings/{identifier}/events?limit=1001")
            ).status_code == 422
            source = job["recording"]["source"]
            refused = await client.post(
                "/api/field-trends/retire", json={"source": source}, headers=headers
            )
            assert refused.status_code == 422 and "End the field" in refused.text
            saved = (
                await client.get("/api/field-trends/samples", params={"source": source})
            ).json()
            assert saved and saved[0]["acquisition_kind"] == "bacnet-cov"
            assert saved[0]["quality"] == "unknown"
            await client.post("/api/bacnet/disconnect", json={}, headers=headers)
            await wait_for(lambda: not job["active"])
            await app.state.bacnet_cov.recorder.flush()
            events = app.state.bacnet_cov.recorder.events(identifier)
            assert events[-1]["event"] == "recording_ended"
            assert events[-1]["evidence"]["state"] == "interface_changed"
    reopened = create_app(directory)
    async with reopened.router.lifespan_context(reopened):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=reopened), base_url="http://testserver"
        ) as client:
            assert (await client.get("/api/bacnet/cov/status")).json()["jobs"] == []
            assert not reopened.state.bacnet.status()["connected"]
            assert reopened.state.bacnet_cov.recorder.worker is None
            assert (await client.get("/api/bacnet/cov/recordings")).json()[0]["state"] == "ended"
            assert (
                await client.get(f"/api/bacnet/cov/recordings/{identifier}/events")
            ).json() == events
