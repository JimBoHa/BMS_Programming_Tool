"""Production BACnet/IP discovery against independently authored UDP packets."""

import asyncio
import copy
import socket
import struct
import sys
import time
from types import SimpleNamespace

import pytest
from bms_tool.connections import Bacnet
from bms_tool.ip_discovery import IpDiscovery, IpScanRequest
from bms_tool.storage import Store


def bvlc(function, payload):
    return bytes([0x81, function]) + struct.pack(">H", len(payload) + 4) + payload


def iam(instance=505, *, vendor=5, segmentation=3):
    return (
        b"\x01\x00\x10\x00\xc4"
        + ((8 << 22) | instance).to_bytes(4, "big")
        + b"\x22\x01\xe0\x91"
        + bytes([segmentation])
        + b"\x22"
        + struct.pack(">H", vendor)
    )


class RawIpPeer:
    """Real UDP and received destination IP, without a BACpypes peer codec."""

    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        self.socket.bind(("0.0.0.0", 0))
        self.port = self.socket.getsockname()[1]
        self.endpoint = f"127.0.0.1:{self.port}"
        self.destination_option = 7 if sys.platform == "darwin" else 8
        self.socket.setsockopt(socket.IPPROTO_IP, self.destination_option, 1)
        self.loop = asyncio.get_running_loop()
        self.loop.add_reader(self.socket.fileno(), self._receive)
        self.frames, self.errors = [], []
        self.instances = [505]
        self.extra_payloads = []
        self.drop = False
        self.drop_registration = False
        self.rogue = None
        self.after_request = None
        self.forwarded_origin = "192.0.2.77"
        self.forwarded_announcements = None
        self.extra_frames = []
        self.received = asyncio.Event()

    def _receive(self):
        try:
            packet, ancillary, _, source = self.socket.recvmsg(65536, 128)
            destination = None
            for level, kind, value in ancillary:
                if level == socket.IPPROTO_IP and kind == self.destination_option:
                    destination = socket.inet_ntoa(
                        value[:4] if sys.platform == "darwin" else value[8:12]
                    )
            assert packet[0] == 0x81 and int.from_bytes(packet[2:4], "big") == len(packet)
            self.frames.append(
                {
                    "data": packet,
                    "source": source,
                    "destination_ip": destination,
                    "time": self.loop.time(),
                }
            )
            if packet[1] == 5:
                assert len(packet) == 6
                if int.from_bytes(packet[4:6], "big") and not self.drop_registration:
                    self.socket.sendto(bvlc(0, b"\x00\x00"), source)
                return
            assert packet[1] in (9, 10, 11)
            assert packet[4:8] == b"\x01\x00\x10\x08", "No routed/global NPDU is permitted"
            self.received.set()
            if self.after_request:
                self.after_request()
            if self.drop:
                return
            if self.rogue:
                self.rogue.sendto(bvlc(10, iam(999)), source)
            announcements = (
                self.forwarded_announcements
                if packet[1] == 9 and self.forwarded_announcements is not None
                else [(self.forwarded_origin, self.port, instance) for instance in self.instances]
            )
            for origin_ip, origin_port, instance in announcements:
                payload = iam(instance)
                if packet[1] == 9:
                    origin = socket.inet_aton(origin_ip) + struct.pack(">H", origin_port)
                    self.socket.sendto(bvlc(4, origin + payload), source)
                else:
                    self.socket.sendto(bvlc(10, payload), source)
            for payload in self.extra_payloads:
                self.socket.sendto(bvlc(10, payload), source)
            for function, payload in self.extra_frames:
                self.socket.sendto(bvlc(function, payload), source)
        except BlockingIOError:
            return
        except Exception as exc:
            self.errors.append(exc)

    def close(self):
        self.loop.remove_reader(self.socket.fileno())
        self.socket.close()


class WireTap:
    """Record actual encoded sends; optionally mirror Darwin loopback broadcast.

    The production destination is attempted first. The explicit test-only
    mirror delivers identical BVLC bytes to a real local independent peer.
    """

    def __init__(self, transport, *, mirror_broadcast=False):
        self.transport = transport
        self.mirror_broadcast = mirror_broadcast
        self.frames = []

    def sendto(self, data, address):
        self.frames.append(
            {"data": bytes(data), "destination": address, "time": asyncio.get_running_loop().time()}
        )
        self.transport.sendto(data, address)
        if self.mirror_broadcast and address[0] == "127.255.255.255":
            self.transport.sendto(data, ("127.0.0.1", address[1]))

    def __getattr__(self, name):
        return getattr(self.transport, name)


@pytest.fixture
async def rig(tmp_path):
    peer = RawIpPeer()
    rogue = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rogue.bind(("127.0.0.1", 0))
    connector = Bacnet(Store(tmp_path))
    await connector.connect("127.0.0.1:0")
    service = IpDiscovery(connector)
    try:
        yield service, connector, peer, rogue
        assert not peer.errors, peer.errors
    finally:
        connector.close()
        peer.close()
        rogue.close()
        await asyncio.sleep(0.05)


async def test_real_single_unicast_is_not_routed_and_retains_actual_identity(rig):
    service, connector, peer, _ = rig
    original = copy.deepcopy(connector.config)
    report = await service.scan(
        mode="single", ip="127.0.0.1", udp_port=peer.port, timeout_seconds=1.0
    )
    assert report["complete"] and report["response_window_complete"]
    assert not report["truncated"] and report["next_ip"] is None
    assert len(report["devices"]) == 1
    row = report["devices"][0]
    assert row["address"] == peer.endpoint and row["device"] == "device,505"
    assert (
        row["vendor"] == 5 and row["max_apdu"] == 480 and row["segmentation"] == "no-segmentation"
    )
    assert row["source_scope"] == "direct-ip" and row["via_bbmd"] is None
    assert peer.frames[0]["data"] == bvlc(10, bytes.fromhex("0100100809001b3ffffe"))
    assert peer.frames[0]["destination_ip"] == "127.0.0.1"
    assert connector.config == original and not connector.lock.locked()
    layer = connector.app.nsap.local_adapter.clientPeer
    assert "confirmation" not in layer.__dict__


async def test_real_range_udp_destinations_pacing_and_unknown_hosts(rig, monkeypatch):
    service, connector, peer, _ = rig
    server = connector.app.nsap.local_adapter.clientPeer.server
    tap = WireTap(server.local_transport)
    monkeypatch.setattr(server, "local_transport", tap)
    report = await service.scan(
        mode="range",
        start_ip="127.0.0.1",
        end_ip="127.0.0.3",
        udp_port=peer.port,
        timeout_seconds=1.0,
    )
    assert [frame["destination"][0] for frame in tap.frames] == [
        "127.0.0.1",
        "127.0.0.2",
        "127.0.0.3",
    ]
    assert len(report["targets_sent"]) == 3 and report["targets_requested"] == 3
    assert len(report["devices"]) == 1 and report["devices"][0]["responses"] >= 1
    assert all(
        frame["data"] == bvlc(10, bytes.fromhex("0100100809001b3ffffe")) for frame in tap.frames
    )
    assert all(
        right["time"] - left["time"] >= 0.049
        for left, right in zip(tap.frames, tap.frames[1:], strict=False)
    )


async def test_local_broadcast_wire_with_real_udp_peer_and_loopback_delivery_mirror(
    rig, monkeypatch
):
    service, connector, peer, _ = rig
    server = connector.app.nsap.local_adapter.clientPeer.server
    tap = WireTap(server.local_transport, mirror_broadcast=True)
    monkeypatch.setattr(server, "local_transport", tap)
    profile = service.status()
    assert profile["local_broadcast"]["network"] == "127.0.0.0/8"
    report = await service.scan(mode="local", udp_port=peer.port, timeout_seconds=1.0)
    assert report["broadcast_scope"] == "local-subnet"
    assert peer.frames[0]["data"][:2] == b"\x81\x0b"
    assert tap.frames[0]["destination"] == ("127.255.255.255", peer.port)
    assert tap.frames[0]["data"] == peer.frames[0]["data"]
    assert len(report["devices"]) == 1


async def test_source_port_pin_malformed_iams_and_capability_conflicts(rig):
    service, _, peer, rogue = rig
    peer.rogue = rogue
    peer.instances = [505, 505, 506]
    peer.extra_payloads = [
        iam(505, vendor=7),
        iam(507, segmentation=9),
        iam(4194303),
        iam(508)[:-1],
        iam(509) + b"\x21\x00",
    ]
    report = await service.scan(
        mode="single", ip="127.0.0.1", udp_port=peer.port, timeout_seconds=1.0
    )
    assert [row["device_instance"] for row in report["devices"]] == [505, 506]
    assert report["devices"][0]["responses"] == 3
    assert report["devices"][0]["vendor"] == 5 and report["devices"][0]["conflicting_announcements"]
    assert report["invalid_responses"] == 4 and report["ignored_source_packets"] >= 1


async def test_result_cap_and_empty_window_keep_unknown_and_partial_explicit(rig):
    service, _, peer, _ = rig
    peer.instances = [505, 506]
    report = await service.scan(
        mode="single", ip="127.0.0.1", udp_port=peer.port, timeout_seconds=1.0, max_devices=1
    )
    assert (
        not report["complete"]
        and report["response_window_complete"]
        and report["truncated"]
        and len(report["devices"]) == 1
    )
    peer.drop = True
    empty = await service.scan(
        mode="single", ip="127.0.0.1", udp_port=peer.port, timeout_seconds=1.0
    )
    assert (
        empty["complete"]
        and empty["devices"] == []
        and any("unknown" in message for message in empty["warnings"])
    )


async def test_cancel_restores_existing_link_observer_and_no_late_packets(rig):
    service, connector, peer, _ = rig
    peer.drop = True
    layer = connector.app.nsap.local_adapter.clientPeer
    original = layer.confirmation

    async def previous(packet):
        await original(packet)

    layer.confirmation = previous
    pending = asyncio.create_task(
        service.scan(
            mode="range",
            start_ip="127.0.0.1",
            end_ip="127.0.0.20",
            udp_port=peer.port,
            timeout_seconds=2.0,
        )
    )
    await asyncio.wait_for(peer.received.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    count = len(peer.frames)
    assert not connector.lock.locked() and layer.__dict__["confirmation"] is previous
    assert not connector.app.asap.clientTransactions and not connector.app._requests
    await asyncio.sleep(0.15)
    assert len(peer.frames) == count


async def test_busy_lock_and_configuration_change_do_not_leak_observers(rig, monkeypatch):
    service, connector, peer, _ = rig
    monkeypatch.setattr("bms_tool.ip_discovery.LOCK_TIMEOUT_SECONDS", 0.02)
    await connector.lock.acquire()
    try:
        with pytest.raises(ValueError, match="busy"):
            await service.scan(mode="single", ip="127.0.0.1", udp_port=peer.port)
        assert connector.lock.locked() and not peer.frames
    finally:
        connector.lock.release()
    peer.after_request = lambda: setattr(
        connector, "config", {**connector.config, "instance": 4190002}
    )
    with pytest.raises(ValueError, match="changed"):
        await service.scan(mode="single", ip="127.0.0.1", udp_port=peer.port, timeout_seconds=1.0)
    assert not connector.lock.locked()
    assert "confirmation" not in connector.app.nsap.local_adapter.clientPeer.__dict__


@pytest.mark.parametrize(
    "change",
    [
        {"ip": "localhost"},
        {"ip": "224.0.0.1"},
        {"ip": "0.0.0.0"},
        {"ip": "255.255.255.255"},
        {"ip": "127.0.0.1/8"},
        {"ip": "127.0.0.1:47808"},
        {"udp_port": True},
        {"udp_port": 0},
        {"low": True},
        {"high": 4194303},
        {"low": 10, "high": 9},
        {"max_devices": 257},
        {"timeout_seconds": False},
        {"timeout_seconds": 10.1},
        {"start_ip": "127.0.0.2"},
    ],
)
def test_strict_single_bounds(change):
    with pytest.raises(ValueError):
        IpScanRequest(**{"mode": "single", "ip": "127.0.0.1", **change})


def test_range_limits_and_explicit_cursor_scope():
    value = IpScanRequest(
        mode="range", start_ip="192.168.0.0", end_ip="192.168.255.255", cursor_ip="192.168.1.0"
    )
    assert value.cursor_ip == "192.168.1.0"
    for change in (
        {"end_ip": "192.169.0.0"},
        {"cursor_ip": "192.167.255.255"},
        {"cursor_ip": "192.169.0.0"},
        {"end_ip": "192.167.255.255"},
    ):
        with pytest.raises(ValueError):
            IpScanRequest(
                **{
                    "mode": "range",
                    "start_ip": "192.168.0.0",
                    "end_ip": "192.168.255.255",
                    **change,
                }
            )


async def test_point_to_point_local_rejected_but_single_usable(rig, monkeypatch):
    service, _, peer, _ = rig
    monkeypatch.setattr(
        "bms_tool.ip_discovery.ifaddr.get_adapters",
        lambda: [SimpleNamespace(ips=[SimpleNamespace(ip="127.0.0.1", network_prefix=32)])],
    )
    with pytest.raises(ValueError, match="Point-to-point"):
        await service.scan(mode="local", udp_port=peer.port)
    report = await service.scan(
        mode="single", ip="127.0.0.1", udp_port=peer.port, timeout_seconds=1.0
    )
    assert len(report["devices"]) == 1


async def test_known_network_broadcast_range_entries_skipped_without_stalling_cursor(
    rig, monkeypatch
):
    service, connector, peer, _ = rig
    server = connector.app.nsap.local_adapter.clientPeer.server
    tap = WireTap(server.local_transport)
    monkeypatch.setattr(server, "local_transport", tap)
    monkeypatch.setattr(
        "bms_tool.ip_discovery.ifaddr.get_adapters",
        lambda: [SimpleNamespace(ips=[SimpleNamespace(ip="127.0.0.1", network_prefix=30)])],
    )
    report = await service.scan(
        mode="range",
        start_ip="127.0.0.0",
        end_ip="127.0.0.3",
        udp_port=peer.port,
        timeout_seconds=1.0,
    )
    assert [row["ip"] for row in report["skipped_targets"]] == ["127.0.0.0", "127.0.0.3"]
    assert [frame["destination"][0] for frame in tap.frames] == ["127.0.0.1", "127.0.0.2"]
    assert (
        report["page_targets_processed"] == 4 and report["complete"] and report["next_ip"] is None
    )


async def test_mismatched_configured_prefix_keeps_observed_network_for_unicast_guards(
    rig, monkeypatch
):
    service, connector, peer, _ = rig
    await connector.connect("127.0.0.1/16:0")
    server = connector.app.nsap.local_adapter.clientPeer.server
    tap = WireTap(server.local_transport)
    monkeypatch.setattr(server, "local_transport", tap)
    with pytest.raises(ValueError, match="differs from"):
        await service.scan(mode="local", udp_port=peer.port, timeout_seconds=1.0)
    with pytest.raises(ValueError, match="network/broadcast"):
        await service.scan(
            mode="single", ip="127.255.255.255", udp_port=peer.port, timeout_seconds=1.0
        )
    assert not tap.frames
    first = await service.scan(
        mode="range",
        start_ip="127.0.0.0",
        end_ip="127.0.0.1",
        udp_port=peer.port,
        timeout_seconds=1.0,
    )
    assert (
        first["bind_network"] == "127.0.0.0/8"
        and first["prefix_source"] == "operating-system-interface"
    )
    assert first["skipped_targets"] == [
        {"ip": "127.0.0.0", "reason": "known-local-network-or-broadcast-address"}
    ]
    assert first["complete"] and len(first["devices"]) == 1
    last = await service.scan(
        mode="range",
        start_ip="127.255.255.254",
        end_ip="127.255.255.255",
        udp_port=peer.port,
        timeout_seconds=1.0,
    )
    assert last["bind_network"] == "127.0.0.0/8" and last["complete"]
    assert last["skipped_targets"] == [
        {"ip": "127.255.255.255", "reason": "known-local-network-or-broadcast-address"}
    ]
    assert [frame["destination"][0] for frame in tap.frames] == ["127.0.0.1", "127.255.255.254"]


async def test_foreign_local_uses_registered_bbmd_and_retains_forwarded_origin(tmp_path):
    peer = RawIpPeer()
    connector = Bacnet(Store(tmp_path))
    try:
        await connector.connect("127.0.0.1:0", bbmd_address=peer.endpoint, foreign_ttl=60)
        service = IpDiscovery(connector)
        report = await service.scan(mode="local", udp_port=peer.port, timeout_seconds=1.0)
        assert report["broadcast_scope"] == "bbmd-network"
        row = report["devices"][0]
        assert row["ip"] == "192.0.2.77" and row["via_bbmd"] == peer.endpoint
        assert row["source_scope"] == "bbmd-forwarded"
        assert any(frame["data"][1] == 9 for frame in peer.frames)
        assert not any(frame["data"][1] == 11 for frame in peer.frames)
    finally:
        connector.close()
        await asyncio.sleep(0.05)
        peer.close()
    assert not peer.errors


async def test_explicit_range_cursor_preserves_original_scope_and_no_automatic_next_page(
    rig, monkeypatch
):
    service, connector, peer, _ = rig
    monkeypatch.setattr("bms_tool.ip_discovery.PAGE_HOSTS", 2)
    server = connector.app.nsap.local_adapter.clientPeer.server
    tap = WireTap(server.local_transport)
    monkeypatch.setattr(server, "local_transport", tap)
    body = {
        "mode": "range",
        "start_ip": "127.0.0.1",
        "end_ip": "127.0.0.4",
        "udp_port": peer.port,
        "timeout_seconds": 1.0,
    }
    first = await service.scan(**body)
    assert first["targets_requested"] == 4 and first["page_targets_requested"] == 2
    assert first["next_ip"] == "127.0.0.3" and not first["complete"] and first["truncated"]
    assert [frame["destination"][0] for frame in tap.frames] == ["127.0.0.1", "127.0.0.2"]
    await asyncio.sleep(0.1)
    assert len(tap.frames) == 2
    last = await service.scan(**body, cursor_ip=first["next_ip"])
    assert (
        last["request"]["start_ip"] == body["start_ip"]
        and last["request"]["end_ip"] == body["end_ip"]
    )
    assert last["next_ip"] is None and last["complete"] and last["targets_requested"] == 4
    assert [frame["destination"][0] for frame in tap.frames] == [
        "127.0.0.1",
        "127.0.0.2",
        "127.0.0.3",
        "127.0.0.4",
    ]


async def test_plain_interface_never_accepts_unconfigured_forwarded_evidence(rig):
    service, _, peer, _ = rig
    origin = socket.inet_aton("192.0.2.77") + struct.pack(">H", peer.port)
    peer.extra_frames = [(4, origin + iam(606))]
    report = await service.scan(
        mode="single", ip="127.0.0.1", udp_port=peer.port, timeout_seconds=1.0
    )
    assert [row["device_instance"] for row in report["devices"]] == [505]
    assert report["ignored_source_packets"] >= 1


async def test_foreign_forwarded_source_pin_and_self_endpoint_exclusion_not_instance_id(tmp_path):
    peer = RawIpPeer()
    connector = Bacnet(Store(tmp_path))
    rogue = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rogue.bind(("127.0.0.1", 0))
    try:
        await connector.connect(
            "127.0.0.1:0", instance=4190001, bbmd_address=peer.endpoint, foreign_ttl=60
        )
        own = connector.app.foreign_link.server.local_transport.get_extra_info("sockname")
        peer.forwarded_announcements = [
            (own[0], own[1], 4190001),
            ("192.0.2.77", peer.port, 4190001),
            ("192.0.2.78", peer.port, 4190001),
        ]
        peer.after_request = lambda: rogue.sendto(
            bvlc(4, socket.inet_aton("192.0.2.79") + struct.pack(">H", peer.port) + iam(606)),
            peer.frames[-1]["source"],
        )
        report = await IpDiscovery(connector).scan(
            mode="local", udp_port=peer.port, timeout_seconds=1.0
        )
        assert [row["ip"] for row in report["devices"]] == ["192.0.2.77", "192.0.2.78"]
        assert all(row["device_instance"] == 4190001 for row in report["devices"])
        assert report["ignored_self_packets"] == 1 and report["ignored_source_packets"] >= 1
        assert any("Duplicate" in message for message in report["warnings"])
    finally:
        connector.close()
        await asyncio.sleep(0.05)
        peer.close()
        rogue.close()
    assert not peer.errors


async def test_foreign_single_range_stay_original_unicast_and_ignore_unselected_forwarded_origin(
    tmp_path,
):
    peer = RawIpPeer()
    connector = Bacnet(Store(tmp_path))
    try:
        await connector.connect("127.0.0.1:0", bbmd_address=peer.endpoint, foreign_ttl=60)
        peer.extra_frames = [
            (4, socket.inet_aton("192.0.2.77") + struct.pack(">H", peer.port) + iam(606))
        ]
        report = await IpDiscovery(connector).scan(
            mode="range",
            start_ip="127.0.0.1",
            end_ip="127.0.0.1",
            udp_port=peer.port,
            timeout_seconds=1.0,
        )
        assert [row["device_instance"] for row in report["devices"]] == [505]
        assert peer.frames[-1]["data"][1] == 10 and not any(
            frame["data"][1] in (9, 11) for frame in peer.frames
        )
        assert report["ignored_source_packets"] >= 1
    finally:
        connector.close()
        await asyncio.sleep(0.05)
        peer.close()
    assert not peer.errors


async def test_foreign_lease_loss_aborts_and_restores_managed_link(tmp_path):
    peer = RawIpPeer()
    connector = Bacnet(Store(tmp_path))
    try:
        await connector.connect("127.0.0.1:0", bbmd_address=peer.endpoint, foreign_ttl=60)
        layer = connector.app.foreign_link
        peer.after_request = lambda: setattr(layer, "lease_expires", time.monotonic() - 1)
        with pytest.raises(ValueError, match="registration"):
            await IpDiscovery(connector).scan(mode="local", udp_port=peer.port, timeout_seconds=1.0)
        assert "confirmation" not in layer.__dict__ and not connector.lock.locked()
    finally:
        connector.close()
        await asyncio.sleep(0.05)
        peer.close()


async def test_packet_budget_and_operation_deadline_disclose_partial_results(rig, monkeypatch):
    service, connector, peer, _ = rig
    monkeypatch.setattr("bms_tool.ip_discovery.MAX_OBSERVATIONS", 2)
    peer.instances = [505, 506, 507, 508]
    bounded = await service.scan(
        mode="single", ip="127.0.0.1", udp_port=peer.port, timeout_seconds=1.0
    )
    assert len(bounded["devices"]) == 2 and bounded["truncated"] and not bounded["complete"]
    assert not bounded["response_window_complete"]
    monkeypatch.setattr("bms_tool.ip_discovery.MAX_OBSERVATIONS", 4096)
    monkeypatch.setattr("bms_tool.ip_discovery.OPERATION_SECONDS", 0.08)
    peer.instances = [505]
    partial = await service.scan(
        mode="range",
        start_ip="127.0.0.1",
        end_ip="127.0.0.20",
        udp_port=peer.port,
        timeout_seconds=1.0,
    )
    assert partial["truncated"] and not partial["complete"] and partial["next_ip"] is not None
    assert len(partial["targets_sent"]) < 20 and not connector.lock.locked()


async def test_udp_failure_and_audit_failure_preserve_cleanup_or_received_evidence(
    rig, monkeypatch
):
    service, connector, peer, _ = rig

    def fail(*args):
        raise OSError("injected audit failure")

    monkeypatch.setattr(service.store, "record", fail)
    report = await service.scan(
        mode="single", ip="127.0.0.1", udp_port=peer.port, timeout_seconds=1.0
    )
    assert report["devices"] and report["audit_error"]
    peer.after_request = lambda: (
        connector.app.nsap.local_adapter.clientPeer.server.local_transport.close()
    )
    with pytest.raises(ValueError, match="stopped"):
        await service.scan(mode="single", ip="127.0.0.1", udp_port=peer.port, timeout_seconds=1.0)
    assert (
        not connector.lock.locked()
        and "confirmation" not in connector.app.nsap.local_adapter.clientPeer.__dict__
    )
