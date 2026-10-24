"""Bounded local router advertisements over independently framed loopback UDP."""

import asyncio
import copy
import struct

import httpx
import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.router_discovery import RouterDiscovery, RouterDiscoveryRequest
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_ip_discovery import WireTap


def bvlc(payload):
    return b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload


class RouterPeer(asyncio.DatagramProtocol):
    def __init__(self):
        self.frames, self.errors = [], []
        self.networks = [[2001, 2201], [2001, 3001]]
        self.extra = []
        self.drop = False
        self.received = asyncio.Event()

    def connection_made(self, transport):
        self.transport = transport
        self.port = transport.get_extra_info("sockname")[1]

    def datagram_received(self, data, source):
        try:
            # Exactly one local network-layer request, without a DNET/SNET,
            # remote/global broadcast destination, application service or write.
            assert data == b"\x81\x0b\x00\x07\x01\x80\x00"
            self.frames.append(bytes(data))
            self.received.set()
            if self.drop:
                return
            for networks in self.networks:
                self.transport.sendto(
                    bvlc(
                        b"\x01\x80\x01" + b"".join(struct.pack(">H", value) for value in networks)
                    ),
                    source,
                )
            for payload in self.extra:
                self.transport.sendto(bvlc(payload), source)
        except Exception as exc:
            self.errors.append(exc)


@pytest.fixture
async def router_link(tmp_path, monkeypatch):
    transport, peer = await asyncio.get_running_loop().create_datagram_endpoint(
        RouterPeer, local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    server = client.app.nsap.local_adapter.clientPeer.server
    tap = WireTap(server.local_transport, mirror_broadcast=True)
    monkeypatch.setattr(server, "local_transport", tap)
    service = RouterDiscovery(client, client.store)
    try:
        yield service, client, peer, tap
    finally:
        client.close()
        transport.close()
        assert not peer.errors


async def test_router_advertisements_merge_exact_source_networks_and_restore_hooks(router_link):
    service, client, peer, tap = router_link
    config = copy.deepcopy(client.config)
    result = await service.discover(udp_port=peer.port, timeout_seconds=1.0)
    assert result["complete"] and not result["truncated"]
    assert len(peer.frames) == len(tap.frames) == 1
    assert tap.frames[0]["destination"] == ("127.255.255.255", peer.port)
    assert result["routers"] == [
        {
            "router": f"127.0.0.1:{peer.port}",
            "networks": [2001, 2201, 3001],
            "responses": 2,
            "first_received_at": result["routers"][0]["first_received_at"],
            "last_received_at": result["routers"][0]["last_received_at"],
            "truncated": False,
        }
    ]
    assert client.config == config and not client.commands
    assert "process_npdu" not in client.app.nsap.__dict__ and not client.lock.locked()


async def test_invalid_networks_routed_announcements_and_wrong_udp_sources_are_excluded(
    router_link,
):
    service, client, peer, _ = router_link
    peer.networks += [[0, 2001], [65535]]
    peer.extra = [b"\x01\x88\x07\xd1\x01\x07\x01\x07\xd1"]
    rogue, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    task = asyncio.create_task(service.discover(udp_port=peer.port, timeout_seconds=1.0))
    try:
        await peer.received.wait()
        target = client.app.nsap.local_adapter.clientPeer.server.local_transport.get_extra_info(
            "sockname"
        )
        rogue.sendto(bvlc(b"\x01\x80\x01\x27\x0f"), target)
        result = await task
        assert result["routers"][0]["networks"] == [2001, 2201, 3001]
        assert result["invalid_responses"] == 2
        assert result["ignored_sources"] >= 2
    finally:
        rogue.close()


async def test_empty_and_bounded_partial_router_reports_remain_explicit(router_link):
    service, _, peer, _ = router_link
    result = await service.discover(udp_port=peer.port, timeout_seconds=1.0, max_networks=1)
    assert result["truncated"] and result["routers"][0]["truncated"]
    assert result["routers"][0]["networks"] == [2001]
    peer.drop = True
    result = await service.discover(udp_port=peer.port, timeout_seconds=1.0)
    assert result["complete"] and not result["routers"] and result["warnings"]


async def test_cancellation_and_interface_change_retire_observer_without_late_sends(router_link):
    service, client, peer, tap = router_link
    peer.drop = True
    task = asyncio.create_task(service.discover(udp_port=peer.port, timeout_seconds=5.0))
    await peer.received.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(tap.frames) == 1 and "process_npdu" not in client.app.nsap.__dict__
    assert not client.lock.locked()
    peer.received.clear()
    task = asyncio.create_task(service.discover(udp_port=peer.port, timeout_seconds=5.0))
    await peer.received.wait()
    client.config = {**client.config, "instance": 12345}
    with pytest.raises(ValueError, match="changed"):
        await task
    assert len(tap.frames) == 2 and "process_npdu" not in client.app.nsap.__dict__


async def test_unknown_or_point_to_point_subnet_fails_before_transmission(router_link, monkeypatch):
    import bms_tool.router_discovery as module

    service, _, _, tap = router_link

    def unknown(*args):
        raise ValueError("Unknown test subnet")

    monkeypatch.setattr(module, "_bound_network", unknown)
    with pytest.raises(ValueError, match="Unknown test subnet"):
        await service.discover()
    assert not tap.frames


@pytest.mark.parametrize(
    "updates",
    [
        {"udp_port": True},
        {"udp_port": "47808"},
        {"udp_port": 0},
        {"timeout_seconds": 0.5},
        {"timeout_seconds": 6.0},
        {"max_routers": 129},
        {"max_networks": 129},
    ],
)
def test_router_query_limits_are_strict(updates):
    with pytest.raises(ValueError):
        RouterDiscoveryRequest(**updates)


async def test_router_api_requires_session_and_an_open_interface(tmp_path):
    app = create_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        uri = "/api/bacnet/discover-routers"
        assert (await client.post(uri, json={})).status_code == 403
        headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
        result = await client.post(uri, json={}, headers=headers)
        assert result.status_code == 422 and "Connect" in result.text
        assert not (await client.get("/api/session")).json()["field_network_open"]


async def test_actual_http_router_discovery_uses_the_existing_interface(
    router_link, tmp_path, monkeypatch
):
    _, _, peer, _ = router_link
    app = create_app(tmp_path / "router-api")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            assert (
                await client.post(
                    "/api/bacnet/connect",
                    headers=headers,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                )
            ).status_code == 200
            server = app.state.bacnet.app.nsap.local_adapter.clientPeer.server
            tap = WireTap(server.local_transport, mirror_broadcast=True)
            monkeypatch.setattr(server, "local_transport", tap)
            response = await client.post(
                "/api/bacnet/discover-routers",
                headers=headers,
                json={"udp_port": peer.port, "timeout_seconds": 1.0},
            )
            assert response.status_code == 200, response.text
            assert response.json()["routers"][0]["networks"] == [2001, 2201, 3001]
            assert len(tap.frames) == 1
            assert "process_npdu" not in app.state.bacnet.app.nsap.__dict__
    finally:
        app.state.bacnet.close()
