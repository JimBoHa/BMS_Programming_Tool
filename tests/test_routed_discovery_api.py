"""Actual ASGI endpoints and independent UDP router; no building-network access."""

import httpx
from bms_tool.app import create_app

from .test_routed_discovery import free_port
from .test_routed_discovery import rig as rig


async def test_explicit_http_router_cache_scan_and_controller_read(rig, tmp_path):
    _, _, peer, _ = rig
    app = create_app(tmp_path / "http-workspace")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            profile = (await client.get("/api/bacnet/routed-profile")).json()
            assert not profile["connected"] and not peer.frames
            body = {"router": peer.endpoint, "timeout_seconds": 1.0}
            unopened = await client.post("/api/bacnet/router-networks", json=body, headers=headers)
            assert unopened.status_code == 422 and not peer.frames
            local = f"127.0.0.1:{free_port()}"
            opened = await client.post(
                "/api/bacnet/connect", json={"local_address": local}, headers=headers
            )
            assert opened.status_code == 200, opened.text
            network = await client.post("/api/bacnet/router-networks", json=body, headers=headers)
            assert network.status_code == 200, network.text
            assert network.json()["networks"] == [2105, 2205]
            cached = await client.post(
                "/api/bacnet/router-bindings",
                json={"router": peer.endpoint, "device": 505},
                headers=headers,
            )
            assert cached.status_code == 200, cached.text
            assert cached.json()["bindings"][1]["device_instance"] is None
            scan = await client.post(
                "/api/bacnet/scan-trunk", json={**body, "dnet": 2105}, headers=headers
            )
            assert scan.status_code == 200, scan.text
            report = scan.json()
            assert report["complete"] and len(report["devices"]) == 2
            assert report["devices"][0]["address"] == "2105:79"
            assert report["connector_config"]["local_address"] == local
            selected = await client.post(
                "/api/bacnet/connect",
                json={"local_address": local, "router": peer.endpoint, "dnet": 2105},
                headers=headers,
            )
            assert selected.status_code == 200, selected.text
            value = await client.post(
                "/api/bacnet/read",
                json={"address": "2105:79", "object_id": "analog-input,1"},
                headers=headers,
            )
            assert value.status_code == 200, value.text
            assert value.json()["value"] == 12.5
            probe = await client.post(
                "/api/bacnet/probe-controller",
                json={"router": peer.endpoint, "dnet": 2105, "mac": 7},
                headers=headers,
            )
            assert probe.status_code == 200, probe.text
            assert probe.json()["device"] == "device,132007"
            assert probe.json()["properties"]["vendor-identifier"] == 5
            page = await client.post(
                "/api/bacnet/probe-trunk",
                json={
                    "router": peer.endpoint,
                    "dnet": 2105,
                    "mac_low": 6,
                    "mac_high": 8,
                    "per_mac_timeout_seconds": 0.5,
                },
                headers=headers,
            )
            assert page.status_code == 200, page.text
            assert page.json()["devices"][0]["device_instance"] == 132007
            assert [row["mac"] for row in page.json()["no_response"]] == [6, 8]
            assert page.json()["complete"] and page.json()["next_mac"] is None
            assert not (await client.get("/api/bacnet/status")).json()["commands"]
    count = len(peer.frames)
    reopened = create_app(tmp_path / "http-workspace")
    async with reopened.router.lifespan_context(reopened):
        assert not reopened.state.routed_discovery.status()["connected"]
        assert len(peer.frames) == count


async def test_http_mutation_guard_and_strict_bounds_never_open_network(rig, tmp_path):
    _, _, peer, _ = rig
    app = create_app(tmp_path / "http-safety")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            requests = [
                ("router-networks", {"router": peer.endpoint}),
                ("router-bindings", {"router": peer.endpoint, "device": 505}),
                ("scan-trunk", {"router": peer.endpoint, "dnet": 2105}),
                ("probe-controller", {"router": peer.endpoint, "dnet": 2105, "mac": 7}),
                (
                    "probe-trunk",
                    {"router": peer.endpoint, "dnet": 2105, "mac_low": 1, "mac_high": 8},
                ),
            ]
            for path, body in requests:
                uri = "/api/bacnet/" + path
                assert (await client.post(uri, json=body)).status_code == 403
                for other in (
                    {"Host": "untrusted.example"},
                    {"Origin": "https://untrusted.example"},
                ):
                    response = await client.post(uri, json=body, headers={**headers, **other})
                    assert response.status_code == 403
            for body in (
                {"router": "localhost", "dnet": 2105},
                {"router": "255.255.255.255", "dnet": 2105},
                {"router": peer.endpoint, "dnet": True},
                {"router": peer.endpoint, "dnet": 65535},
                {"router": peer.endpoint, "dnet": 2105, "max_devices": 257},
                {"router": peer.endpoint, "dnet": 2105, "low": 10, "high": 9},
                {"router": peer.endpoint, "dnet": 2105, "write": True},
            ):
                response = await client.post("/api/bacnet/scan-trunk", json=body, headers=headers)
                assert response.status_code == 422, response.text
            assert not peer.frames and not app.state.routed_discovery.status()["connected"]


async def test_http_probe_strict_bounds_and_exact_opened_route_required(rig, tmp_path):
    _, _, peer, _ = rig
    app = create_app(tmp_path / "probe-security")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            for path, body in (
                ("probe-controller", {"mac": True}),
                ("probe-controller", {"mac": 255}),
                ("probe-controller", {"mac": 7, "device": 5007}),
                ("probe-trunk", {"mac_low": 0, "mac_high": 32}),
                ("probe-trunk", {"mac_low": 1, "mac_high": 8, "spacing_seconds": 0.09}),
                ("probe-trunk", {"mac_low": 1, "mac_high": 8, "per_mac_timeout_seconds": True}),
            ):
                response = await client.post(
                    "/api/bacnet/" + path,
                    json={"router": peer.endpoint, "dnet": 2105, **body},
                    headers=headers,
                )
                assert response.status_code == 422, response.text
            opened = await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{free_port()}"},
                headers=headers,
            )
            assert opened.status_code == 200
            for path, extra in (
                ("probe-controller", {"mac": 7}),
                ("probe-trunk", {"mac_low": 1, "mac_high": 8}),
            ):
                response = await client.post(
                    "/api/bacnet/" + path,
                    json={"router": peer.endpoint, "dnet": 2105, **extra},
                    headers=headers,
                )
                assert response.status_code == 422 and "Open the selected router" in response.text
            assert not peer.frames
