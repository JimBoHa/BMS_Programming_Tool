"""Guarded API, real read-only UDP tables and lifecycle teardown."""

import httpx
from bms_tool.app import create_app

from .test_bbmd_tables import endpoint
from .test_bbmd_tables import wire as wire
from .test_connections import free_udp
from .test_foreign_bacnet import wait_until


async def test_http_start_poll_export_cancel_shutdown_and_restart_never_query(wire, tmp_path):
    peer, _, _, _ = wire
    directory = tmp_path / "http"
    app = create_app(directory)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            state = (await client.get("/api/bacnet/bbmd-tables/status")).json()
            assert state["jobs"] == [] and state["auto_query"] is False and not peer.frames
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            body = {"endpoint": endpoint(peer.address)}
            assert (
                await client.post("/api/bacnet/bbmd-tables/start", json=body)
            ).status_code == 403
            assert (
                await client.post("/api/bacnet/bbmd-tables/start", json=body, headers=headers)
            ).status_code == 422
            await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{free_udp()}"},
                headers=headers,
            )
            invalid = await client.post(
                "/api/bacnet/bbmd-tables/start",
                json=body | {"tables": ["write-bdt"]},
                headers=headers,
            )
            assert invalid.status_code == 422 and not peer.frames
            created = await client.post("/api/bacnet/bbmd-tables/start", json=body, headers=headers)
            assert created.status_code == 200, created.text
            identifier = created.json()["id"]
            await wait_until(lambda: not app.state.bbmd_tables.jobs[identifier]["active"])
            exported = (await client.get(f"/api/bacnet/bbmd-tables/jobs/{identifier}")).json()
            assert exported["tables"]["bdt"]["rows"][1]["mask"] == "255.0.255.0"
            assert exported["tables"]["fdt"]["rows"][0]["remaining_seconds"] == 89
            assert len(peer.frames) == 2
            peer.responses[2] = None
            started = (
                await client.post("/api/bacnet/bbmd-tables/start", json=body, headers=headers)
            ).json()
            await wait_until(lambda: len(peer.frames) == 3)
            cancelled = await client.post(
                "/api/bacnet/bbmd-tables/cancel", json={"id": started["id"]}, headers=headers
            )
            assert cancelled.json()["state"] == "cancelled"
            layer = app.state.bacnet.app.nsap.local_adapter.clientPeer
            original = layer.multiplexer.confirmation
            last = (
                await client.post("/api/bacnet/bbmd-tables/start", json=body, headers=headers)
            ).json()
            await wait_until(lambda: len(peer.frames) == 4)
    assert app.state.bbmd_tables.detail(last["id"])["state"] == "cancelled"
    assert layer.multiplexer.confirmation == original
    assert not app.state.bacnet.lock.locked() and not app.state.bacnet.status()["connected"]
    assert all(job["task"].done() for job in app.state.bbmd_tables.jobs.values())
    count = len(peer.frames)
    fresh = create_app(directory)
    async with fresh.router.lifespan_context(fresh):
        assert fresh.state.bbmd_tables.status()["jobs"] == []
        assert len(peer.frames) == count and not fresh.state.bacnet.status()["connected"]
