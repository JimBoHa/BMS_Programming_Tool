"""Actual HTTP foreign-device lifecycle with independent raw UDP BVLC peers."""

import httpx
from bms_tool.app import create_app

from tests.test_foreign_bacnet import free_port, wait_until
from tests.test_foreign_bacnet import peers as peers


async def test_http_registration_explicit_bbmd_discovery_read_and_disconnect(peers, tmp_path):
    bbmd, point, _ = peers
    app = create_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            assert not (await client.get("/api/session")).json()["field_network_open"]
            assert not bbmd.frames
            response = await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={
                    "local_address": f"127.0.0.1:{free_port()}",
                    "bbmd_address": f"127.0.0.1:{bbmd.address[1]}",
                    "foreign_ttl": 60,
                },
            )
            assert response.status_code == 200, response.text
            status = (await client.get("/api/bacnet/status")).json()
            assert status["connected"] and status["foreign_device"]["registered"]
            discovered = await client.post(
                "/api/bacnet/discover-foreign",
                headers=headers,
                json={"low": 4190012, "high": 4190012},
            )
            assert discovered.status_code == 200, discovered.text
            target = discovered.json()[0]["address"]
            assert target == f"127.0.0.1:{point.address[1]}"
            value = await client.post(
                "/api/bacnet/read",
                headers=headers,
                json={"address": target, "object_id": "analog-input,1"},
            )
            assert value.status_code == 200 and value.json()["value"] == 12.5
            closed = await client.post("/api/bacnet/disconnect", headers=headers)
            assert closed.status_code == 200 and not closed.json()["connected"]
            await wait_until(lambda: bbmd.registrations()[-1:] == [0])
            assert (await client.get("/api/bacnet/status")).json()["commands"] == []


async def test_http_foreign_validation_and_security_cannot_register_implicitly(peers, tmp_path):
    bbmd, _, _ = peers
    app = create_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            target = {
                "local_address": f"127.0.0.1:{free_port()}",
                "bbmd_address": f"127.0.0.1:{bbmd.address[1]}",
            }
            assert (await client.post("/api/bacnet/connect", json=target)).status_code == 403
            assert (
                await client.post(
                    "/api/bacnet/connect",
                    headers={**headers, "Origin": "https://foreign.example"},
                    json=target,
                )
            ).status_code == 403
            for extra in (
                {"foreign_ttl": True},
                {"foreign_ttl": "60"},
                {"foreign_ttl": 0},
                {"foreign_ttl": 65536},
                {"bbmd_address": "*"},
                {"bbmd_address": "127.0.0.1:0"},
            ):
                response = await client.post(
                    "/api/bacnet/connect", headers=headers, json={**target, **extra}
                )
                assert response.status_code == 422, (extra, response.text)
            for extra in ({"low": True}, {"low": "1"}, {"high": 4194303}, {"low": 2, "high": 1}):
                response = await client.post(
                    "/api/bacnet/discover-foreign", headers=headers, json=extra
                )
                assert response.status_code == 422, (extra, response.text)
            assert (
                not bbmd.frames
                and not (await client.get("/api/session")).json()["field_network_open"]
            )
