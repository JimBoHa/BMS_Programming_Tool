"""Production BACpypes routed discovery against an independent raw UDP router."""

import asyncio
import copy
import socket
import struct

import pytest
from bacpypes3.apdu import ReadPropertyRequest
from bacpypes3.basetypes import ListOfAddressBinding
from bacpypes3.pdu import Address
from bms_tool.bacnet_read import close_application
from bms_tool.connections import Bacnet
from bms_tool.field_trends import FieldTrends
from bms_tool.routed_discovery import (
    MAX_OBSERVATIONS,
    ProbeTrunkRequest,
    RoutedDiscovery,
    RoutedScanRequest,
    RouterBindingsRequest,
    RouterNetworksRequest,
    RouterProbeRequest,
)
from bms_tool.storage import Store


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def bvlc(payload):
    return b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload


def iam(instance, mac, dnet=2105, *, vendor=5):
    # Application ObjectIdentifier/device, Unsigned480, Enumerated/noSegmentation,
    # Unsigned/vendor. These are independent literal BACnet wire encodings.
    body = b"\x10\x00\xc4" + ((8 << 22) | instance).to_bytes(4, "big")
    body += b"\x22\x01\xe0\x91\x03\x22" + struct.pack(">H", vendor)
    return b"\x01\x08" + struct.pack(">H", dnet) + bytes([len(mac)]) + mac + body


def binding(instance, dnet, mac):
    octet_tag = bytes([0x60 | len(mac)]) if len(mac) <= 4 else b"\x65" + bytes([len(mac)])
    return (
        b"\xc4"
        + ((8 << 22) | instance).to_bytes(4, "big")
        + b"\x22"
        + struct.pack(">H", dnet)
        + octet_tag
        + mac
    )


class RawRouter(asyncio.DatagramProtocol):
    """No BACpypes or Studio codec is used to inspect or produce peer packets."""

    def __init__(self):
        self.networks = [2105, 2205]
        self.devices = [(132079, b"\x4f", 2105), (132080, b"\x50", 2105)]
        self.bindings = [
            (132079, 2105, b"\x4f"),
            (4194303, 2105, b"\x51"),
            (132075, 2205, b"\x4b"),
            (505, 1001, b"\x7f\x00\x00\x01\xba\xc0"),
        ]
        self.frames, self.errors = [], []
        self.receipt_times = []
        self.extra_packets = []
        self.rogue = None
        self.drop = False
        self.response_transform = lambda value: value
        self.segmented_bindings = False
        self.segment_payload_size = 400
        self.segment_sends = []
        self.pending_segments = {}
        self.hold_segments = False
        self.segment_acked = asyncio.Event()
        self.identity_instance = 505
        self.identity_segmentation = 0
        self.require_identity = False
        self.identity_seen = False
        self.drop_bindings = False
        self.property_received = asyncio.Event()
        self.probe_devices = {
            (2105, b"\x07"): {
                "instance": 132007,
                "object-name": "Independent controller7",
                "vendor-identifier": 5,
                "model-name": "VMA1630 independent fixture",
                "firmware-revision": "7.0",
                "application-software-version": "1.2",
            }
        }
        self.probe_received = asyncio.Queue()
        self.probe_reject_props = set()
        self.probe_hold_props = set()
        self.hold_point_replies = False
        self.point_received = asyncio.Event()
        self.held_point_packets = []
        self.forwarding_stages = 1
        self.forwarded_hop_counts = []
        self.received = asyncio.Event()

    def connection_made(self, transport):
        self.transport = transport
        self.address = transport.get_extra_info("sockname")
        self.endpoint = f"{self.address[0]}:{self.address[1]}"

    def datagram_received(self, data, address):
        try:
            assert data[:2] == b"\x81\x0a", (
                "Must send Original-Unicast-NPDU, never a BVLC broadcast"
            )
            assert int.from_bytes(data[2:4], "big") == len(data)
            self.frames.append(data)
            self.receipt_times.append(asyncio.get_running_loop().time())
            self.received.set()
            if self.drop:
                return
            packet = data[4:]
            if packet == bytes.fromhex("018000"):
                response = b"\x01\x80\x01" + b"".join(struct.pack(">H", n) for n in self.networks)
                if self.rogue:
                    self.rogue.sendto(bvlc(b"\x01\x80\x01\x27\x0f"), address)
                self.transport.sendto(bvlc(response), address)
                return
            offset = 2
            dnet = mac = None
            if packet[1] & 0x20:
                dnet = int.from_bytes(packet[offset : offset + 2], "big")
                length = packet[offset + 2]
                mac = packet[offset + 3 : offset + 3 + length]
                offset += 3 + length
                hop_count = packet[offset]
                offset += 1
                remaining_hops = hop_count
                for _ in range(self.forwarding_stages):
                    if remaining_hops == 0:
                        return
                    remaining_hops -= 1
                self.forwarded_hop_counts.append(remaining_hops)
            apdu = packet[offset:]
            if apdu[0] & 0xF0 == 0x40:
                assert len(apdu) == 4 and apdu[0] == 0x40
                key = (address, apdu[1])
                segments = self.pending_segments[key]
                self.segment_acked.set()
                if self.hold_segments:
                    return
                following = apdu[2] + 1
                if following < len(segments):
                    self.transport.sendto(bvlc(segments[following]), address)
                    self.segment_sends.append(following)
                else:
                    del self.pending_segments[key]
                return
            if apdu[:2] == b"\x10\x08":
                if dnet is None:
                    body = iam(self.identity_instance, b"\x00")[6:]
                    body = body.replace(b"\x91\x03", bytes([0x91, self.identity_segmentation]))
                    self.transport.sendto(bvlc(b"\x01\x00" + body), address)
                    self.identity_seen = True
                    return
                assert mac == b"" and hop_count == 255
                cursor, limits = 2, []
                for context in (0, 1):
                    tag = apdu[cursor]
                    assert tag >> 4 == context and tag & 8
                    size = tag & 7
                    cursor += 1
                    limits.append(int.from_bytes(apdu[cursor : cursor + size], "big"))
                    cursor += size
                assert cursor == len(apdu)
                for instance, station, network in self.devices:
                    if network == dnet and limits[0] <= instance <= limits[1]:
                        self.transport.sendto(bvlc(iam(instance, station, network)), address)
                if self.rogue:
                    self.rogue.sendto(bvlc(iam(123, b"\x22", dnet)), address)
                for extra in self.extra_packets:
                    self.transport.sendto(bvlc(extra), address)
                return
            assert apdu[0] & 0xF0 == 0 and apdu[3] == 12
            self.property_received.set()
            invoke = apdu[2:3]
            if (
                dnet is not None
                and len(mac) == 1
                and apdu[4:] == bytes.fromhex("0c023fffff194b")
                and (dnet, mac) not in self.probe_devices
            ):
                return
            if (dnet, mac) in self.probe_devices:
                assert hop_count == 255 and packet[1] & 4
                assert len(apdu[4:]) == 7 and apdu[4] == 0x0C and apdu[9] == 0x19
                encoded_identifier = int.from_bytes(apdu[5:9], "big")
                assert encoded_identifier >> 22 == 8
                requested = encoded_identifier & 0x3FFFFF
                controller = self.probe_devices[(dnet, mac)]
                actual = controller["instance"]
                assert requested in (4194303, actual)
                property_number = apdu[10]
                name = {
                    75: "object-identifier",
                    77: "object-name",
                    120: "vendor-identifier",
                    70: "model-name",
                    44: "firmware-revision",
                    12: "application-software-version",
                }[property_number]
                self.probe_received.put_nowait((name, requested))
                if name in self.probe_hold_props:
                    return
                npdu = b"\x01\x08" + struct.pack(">H", dnet) + bytes([len(mac)]) + mac
                if name in self.probe_reject_props:
                    response = npdu + b"\x50" + invoke + b"\x0c\x91\x02\x91\x20"
                else:
                    oid = ((8 << 22) | actual).to_bytes(4, "big")
                    value = controller.get(name)
                    if name == "object-identifier":
                        payload = b"\xc4" + oid
                    elif name == "vendor-identifier":
                        payload = b"\x21" + bytes([value])
                    else:
                        string = b"\x00" + value.encode("utf-8")
                        payload = (
                            bytes([0x70 | len(string)])
                            if len(string) <= 4
                            else bytes([0x75, len(string)])
                        ) + string
                    response = (
                        npdu
                        + b"\x30"
                        + invoke
                        + b"\x0c\x0c"
                        + oid
                        + bytes([0x19, property_number, 0x3E])
                        + payload
                        + b"\x3f"
                    )
                if self.rogue:
                    self.rogue.sendto(bvlc(response), address)
                self.transport.sendto(bvlc(self.response_transform(response)), address)
                return
            if apdu[4:] == b"\x0c\x02\x00\x01\xf9\x19\x1e":
                if self.drop_bindings:
                    return
                if self.require_identity and not self.identity_seen:
                    return
                values = b"".join(binding(*row) for row in self.bindings)
                response = (
                    b"\x01\x00\x30" + invoke + b"\x0c" + apdu[4:] + b"\x3e" + values + b"\x3f"
                )
                if self.segmented_bindings:
                    assert apdu[0] & 2, "Client must advertise segmented ACK receive capability"
                    payload = response[5:]
                    chunks = [
                        payload[index : index + self.segment_payload_size]
                        for index in range(0, len(payload), self.segment_payload_size)
                    ]
                    segments = [
                        b"\x01\x00"
                        + bytes([0x3C if index + 1 < len(chunks) else 0x38])
                        + invoke
                        + bytes([index, 1, 12])
                        + chunk
                        for index, chunk in enumerate(chunks)
                    ]
                    self.pending_segments[(address, invoke[0])] = segments
                    self.transport.sendto(bvlc(segments[0]), address)
                    self.segment_sends.append(0)
                    return
            else:
                assert dnet == 2105 and mac == b"\x4f"
                assert apdu[4:] == bytes.fromhex("0c000000011955")
                # C-verified ReadProperty ACK fixture: analog-input1=12.5.
                response = (
                    b"\x01\x08\x08\x39\x01\x4f\x30"
                    + invoke
                    + bytes.fromhex("0c0c0000000119553e44414800003f")
                )
                self.point_received.set()
                if self.hold_point_replies:
                    self.held_point_packets.append((response, address))
                    return
            self.transport.sendto(bvlc(self.response_transform(response)), address)
        except Exception as exc:
            self.errors.append(exc)


@pytest.fixture
async def rig(tmp_path):
    loop = asyncio.get_running_loop()
    transport, peer = await loop.create_datagram_endpoint(RawRouter, local_addr=("127.0.0.1", 0))
    rogue, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    connector = Bacnet(Store(tmp_path))
    await connector.connect(f"127.0.0.1:{free_port()}")
    service = RoutedDiscovery(connector)
    try:
        yield service, connector, peer, rogue
        assert not peer.errors, peer.errors
    finally:
        connector.close()
        transport.close()
        rogue.close()
        await asyncio.sleep(0.05)


async def test_real_unicast_router_networks_then_one_network_scan_and_routed_live_read(rig):
    service, connector, peer, _ = rig
    original = copy.deepcopy(connector.config)
    networks = await service.networks(router=peer.endpoint, timeout_seconds=1.0)
    assert networks["networks"] == [2105, 2205]
    assert networks["complete"] and not networks["truncated"]
    assert peer.frames[0] == bvlc(bytes.fromhex("018000"))
    report = await service.scan(router=peer.endpoint, dnet=2105, timeout_seconds=1.0)
    assert [row["address"] for row in report["devices"]] == ["2105:79", "2105:80"]
    assert report["devices"][0]["device"] == "device,132079"
    assert report["devices"][0]["mstp_mac"] == 79
    assert report["complete"] and "exhaustive" in report["scope"]
    assert peer.frames[1] == bvlc(bytes.fromhex("0120083900ff100809001b3ffffe"))
    assert connector.config == original
    assert "process_npdu" not in connector.app.nsap.__dict__
    # Discovery does not silently change the commissioning path. Select the
    # router/network explicitly before ordinary controller point services.
    await connector.connect(**{**original, "router": peer.endpoint, "dnet": 2105})
    assert (await connector.read("2105:79", "analog-input,1"))["value"] == 12.5


async def test_rogue_router_and_wrong_network_never_become_scan_results(rig):
    service, _, peer, rogue = rig
    peer.rogue = rogue
    peer.extra_packets = [iam(124, b"\x23", 2205)]
    networks = await service.networks(router=peer.endpoint, timeout_seconds=1.0)
    assert networks["networks"] == [2105, 2205]
    assert networks["ignored_source_packets"] >= 1
    scan = await service.scan(router=peer.endpoint, dnet=2105, timeout_seconds=1.0)
    assert [row["device_instance"] for row in scan["devices"]] == [132079, 132080]
    assert scan["ignored_source_packets"] >= 1


async def test_scan_retains_duplicate_identity_conflicts_and_bounds_results(rig):
    service, _, peer, _ = rig
    peer.devices += [(132079, b"\x51", 2105), (132079, b"\x4f", 2105)]
    result = await service.scan(router=peer.endpoint, dnet=2105, timeout_seconds=1.0, max_devices=3)
    assert len(result["devices"]) == 3
    assert result["devices"][0]["responses"] == 2
    assert any("Conflicting" in row for row in result["warnings"])
    peer.devices += [(132081, b"\x52", 2105)]
    result = await service.scan(router=peer.endpoint, dnet=2105, timeout_seconds=1.0, max_devices=2)
    assert result["truncated"] and result["complete"] and len(result["devices"]) == 2


async def test_network_capacity_and_empty_window_are_explicit(rig):
    service, _, peer, _ = rig
    result = await service.networks(router=peer.endpoint, timeout_seconds=1.0, max_networks=1)
    assert result["networks"] == [2105] and result["truncated"]
    peer.drop = True
    result = await service.scan(router=peer.endpoint, dnet=2105, timeout_seconds=1.0)
    assert result["devices"] == [] and result["complete"] and result["responses"] == 0
    assert any("No matching" in value for value in result["warnings"])


async def test_cancel_and_interface_change_restore_observer_and_release_connection_lock(rig):
    service, connector, peer, _ = rig
    peer.drop = True
    pending = asyncio.create_task(
        service.scan(router=peer.endpoint, dnet=2105, timeout_seconds=3.0)
    )
    await asyncio.wait_for(peer.received.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not connector.lock.locked() and "process_npdu" not in connector.app.nsap.__dict__
    peer.received.clear()
    pending = asyncio.create_task(
        service.scan(router=peer.endpoint, dnet=2105, timeout_seconds=3.0)
    )
    await asyncio.wait_for(peer.received.wait(), 1)
    connector.config = {**connector.config, "instance": 4190002}
    with pytest.raises(ValueError, match="changed"):
        await pending
    assert not connector.lock.locked() and "process_npdu" not in connector.app.nsap.__dict__


async def test_real_binding_read_keeps_unknown_instance_and_wide_mac_as_cached_hints(rig):
    service, connector, peer, _ = rig
    result = await service.bindings(router=peer.endpoint, device=505)
    assert result["networks"] == [1001, 2105, 2205]
    unknown = result["bindings"][1]
    assert unknown["device_instance"] is None and unknown["device"] is None
    assert unknown["address"] == "2105:81" and unknown["mstp_mac"] == 81
    assert result["bindings"][-1]["mstp_mac"] is None
    assert all(row["cached"] and not row["live_verified"] for row in result["bindings"])
    assert not connector.app.asap.clientTransactions and not connector.app._requests
    limited = await service.bindings(router=peer.endpoint, device=505, max_bindings=1)
    assert limited["truncated"] and not limited["complete"] and limited["total_bindings"] == 4


async def test_fresh_interface_performs_exact_identity_preflight_then_real_segmented_binding_cache(
    rig,
):
    service, connector, peer, _ = rig
    assert await connector.app.device_info_cache.get_device_info(Address(peer.endpoint)) is None
    peer.bindings = [(132000 + number, 2105, bytes([number])) for number in range(161)]
    peer.segmented_bindings = True
    peer.require_identity = True
    result = await service.bindings(router=peer.endpoint, device=505)
    assert peer.frames[0] == bvlc(bytes.fromhex("010010080a01f91a01f9"))
    assert peer.identity_seen and result["router_identity"]["device_instance"] == 505
    assert result["router_identity"]["segmentation"] == "segmented-both"
    assert len(result["bindings"]) == 161 and result["total_bindings"] == 161
    assert len(peer.segment_sends) >= 5
    assert result["bindings"][-1]["address"] == "2105:160"
    await asyncio.sleep(0.02)
    assert not peer.pending_segments
    assert not connector.app.asap.clientTransactions and not connector.app._requests


async def test_raw_segmented_ack_also_works_with_no_peer_capability_cache(rig):
    _, connector, peer, _ = rig
    address = Address(peer.endpoint)
    assert await connector.app.device_info_cache.get_device_info(address) is None
    peer.bindings = [(132000 + number, 2105, bytes([number])) for number in range(161)]
    peer.segmented_bindings = True
    request = ReadPropertyRequest(
        objectIdentifier=("device", 505),
        propertyIdentifier="device-address-binding",
        destination=address,
    )
    reply = await asyncio.wait_for(connector.app.request(request), 2)
    assert len(reply.propertyValue.cast_out(ListOfAddressBinding)) == 161
    assert not peer.identity_seen and len(peer.segment_sends) >= 5
    await asyncio.sleep(0.02)
    assert not peer.pending_segments and not connector.app.asap.clientTransactions


async def test_binding_cancel_cleans_confirmed_request_without_late_retries(rig):
    service, connector, peer, _ = rig
    peer.drop_bindings = True
    pending = asyncio.create_task(service.bindings(router=peer.endpoint, device=505))
    await asyncio.wait_for(peer.property_received.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not connector.app.asap.clientTransactions and not connector.app._requests
    assert not connector.lock.locked()
    count = len(peer.frames)
    await asyncio.sleep(0.2)
    assert len(peer.frames) == count


@pytest.mark.parametrize("cancel_method", ["caller", "shutdown"])
async def test_binding_preinvoke_cancellation_cannot_transmit_property_after_return(
    rig,
    monkeypatch,
    cancel_method,
):
    service, connector, peer, _ = rig
    app = connector.app
    original = app.device_info_cache.get_device_info
    entered, release = asyncio.Event(), asyncio.Event()

    async def held(address):
        entered.set()
        await release.wait()
        return await original(address)

    monkeypatch.setattr(app.device_info_cache, "get_device_info", held)
    pending = asyncio.create_task(service.bindings(router=peer.endpoint, device=505))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        [transaction] = app.asap.clientTransactions
        assert transaction.invokeID is None
        assert transaction.segmentAPDU.apduInvokeID is not None
        if cancel_method == "caller":
            pending.cancel()
        else:
            close_application(app)
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not app.asap.clientTransactions and not app._requests
        assert not connector.lock.locked()
        assert peer.identity_seen and len(peer.frames) == 1
        assert not peer.property_received.is_set()
        release.set()
        await asyncio.sleep(0.1)
        assert len(peer.frames) == 1 and not peer.property_received.is_set()
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass


async def test_cancelling_identity_preflight_removes_observer_and_never_reads_property(rig):
    service, connector, peer, _ = rig
    peer.drop = True
    pending = asyncio.create_task(service.bindings(router=peer.endpoint, device=505))
    await asyncio.wait_for(peer.received.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.sleep(0)
    assert not connector.app._who_is_futures and not peer.property_received.is_set()
    assert not connector.lock.locked() and not connector.app._requests


async def test_cancel_during_actual_multi_segment_ack_retires_transaction(rig):
    service, connector, peer, _ = rig
    peer.bindings = [(132000 + number, 2105, bytes([number])) for number in range(161)]
    peer.segmented_bindings = peer.hold_segments = True
    pending = asyncio.create_task(service.bindings(router=peer.endpoint, device=505))
    await asyncio.wait_for(peer.segment_acked.wait(), 1)
    assert connector.app.asap.clientTransactions
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not connector.app.asap.clientTransactions and not connector.app._requests
    assert not connector.lock.locked()


async def test_wrong_router_identity_times_out_without_confirmed_property_request(rig):
    service, connector, peer, _ = rig
    peer.identity_instance = 506
    with pytest.raises(ValueError, match="no matching I-Am"):
        await service.bindings(router=peer.endpoint, device=505)
    await asyncio.sleep(0)
    assert not peer.property_received.is_set() and not connector.app._who_is_futures
    assert not connector.lock.locked()


async def test_invalid_advertised_segmentation_is_not_assumed_supported(rig):
    service, connector, peer, _ = rig
    peer.identity_segmentation = 9
    with pytest.raises(ValueError, match="invalid identity/capabilities"):
        await service.bindings(router=peer.endpoint, device=505)
    assert not peer.property_received.is_set() and not connector.lock.locked()


async def open_probe(connector, peer, *, dnet=2105):
    await connector.connect(**{**connector.config, "router": peer.endpoint, "dnet": dnet})


async def test_real_wildcard_probe_identifies_one_mac_and_reads_metadata_without_iam(rig):
    service, connector, peer, _ = rig
    await open_probe(connector, peer)
    report = await service.probe(router=peer.endpoint, dnet=2105, mac=7)
    assert report["device_instance"] == 132007 and report["address"] == "2105:7"
    assert report["device"] == "device,132007" and report["live_verified"]
    assert report["complete"] and not report["errors"]
    assert report["properties"]["vendor-identifier"] == 5
    assert report["properties"]["model-name"] == "VMA1630 independent fixture"
    assert not peer.identity_seen and len(peer.frames) == 6
    npdu = peer.frames[0][4:]
    assert npdu[:7] == bytes.fromhex("012408390107ff")
    assert npdu[11:] == bytes.fromhex("0c023fffff194b")
    assert "process_npdu" not in connector.app.nsap.__dict__
    assert "indication" not in connector.app.nsap.__dict__
    assert not connector.lock.locked() and not connector.app.asap.clientTransactions


async def test_probe_partial_metadata_is_explicit_and_does_not_invent_missing_values(rig):
    service, connector, peer, _ = rig
    await open_probe(connector, peer)
    peer.probe_reject_props = {"application-software-version"}
    report = await service.probe(router=peer.endpoint, dnet=2105, mac=7)
    assert not report["complete"] and report["live_verified"]
    assert len(report["properties"]) == 4
    assert "application-software-version" not in report["properties"]
    assert report["errors"][0]["property"] == "application-software-version"
    assert "unknown-property" in report["errors"][0]["error"]


async def test_probe_rejects_different_route_or_network_before_any_wire_request(rig):
    service, connector, peer, _ = rig
    with pytest.raises(ValueError, match="Open the selected"):
        await service.probe(router=peer.endpoint, dnet=2105, mac=7)
    await open_probe(connector, peer)
    with pytest.raises(ValueError, match="Open the selected"):
        await service.probe(router=peer.endpoint, dnet=2205, mac=7)
    assert not peer.frames and not connector.lock.locked()


async def test_probe_filters_wrong_udp_router_even_when_sadr_and_device_match(rig):
    service, connector, peer, rogue = rig
    await open_probe(connector, peer)
    peer.rogue = rogue
    report = await service.probe(router=peer.endpoint, dnet=2105, mac=7)
    assert report["complete"] and report["ignored_router_packets"] >= 1
    assert report["device_instance"] == 132007


async def test_selected_router_can_forward_through_two_logical_hops_for_scan_and_probes(rig):
    service, connector, peer, _ = rig
    # Independent router consumes one hop at each forwarding stage. A Hop1
    # packet expires at the second stage despite the same selected IP router.
    peer.forwarding_stages = 2
    scanned = await service.scan(router=peer.endpoint, dnet=2105, timeout_seconds=1.0)
    assert len(scanned["devices"]) == 2
    await open_probe(connector, peer)
    single = await service.probe(router=peer.endpoint, dnet=2105, mac=7)
    assert single["complete"] and single["device_instance"] == 132007
    page = await service.probe_range(router=peer.endpoint, dnet=2105, mac_low=7, mac_high=7)
    assert page["complete"] and len(page["devices"]) == 1
    assert len(peer.forwarded_hop_counts) == 8
    assert set(peer.forwarded_hop_counts) == {253}


async def test_probe_ignores_poisoned_route_cache_and_keeps_exact_selected_router(rig):
    service, connector, peer, rogue = rig
    await open_probe(connector, peer)
    wrong = rogue.get_extra_info("sockname")
    await connector.app.nsap.update_router_references(None, Address(wrong), [2105])
    report = await service.probe(router=peer.endpoint, dnet=2105, mac=7)
    assert report["complete"] and len(peer.frames) == 6


async def test_probe_cancel_during_metadata_retires_request_and_restores_hooks(rig):
    service, connector, peer, _ = rig
    await open_probe(connector, peer)
    peer.probe_hold_props = {"model-name"}
    pending = asyncio.create_task(service.probe(router=peer.endpoint, dnet=2105, mac=7))
    while True:
        name, _ = await asyncio.wait_for(peer.probe_received.get(), 1)
        if name == "model-name":
            break
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not connector.app.asap.clientTransactions and not connector.app._requests
    assert not connector.lock.locked()
    assert "process_npdu" not in connector.app.nsap.__dict__
    assert "indication" not in connector.app.nsap.__dict__


@pytest.mark.parametrize("mode", ["single", "page"])
async def test_inflight_field_trend_reply_for_unrelated_mac_survives_probe_hooks(
    rig, tmp_path, mode
):
    service, connector, peer, _ = rig
    await open_probe(connector, peer)
    peer.hold_point_replies = True
    trends = FieldTrends(
        connector,
        tmp_path / ("concurrent-field-" + mode),
        request_timeout=2.0,
        min_request_gap=0,
    )
    pending = None
    try:
        job = await trends.start(
            [
                {"signal": "supply_temp", "address": "2105:79", "object_id": "analog-input,1"},
            ]
        )
        await asyncio.wait_for(peer.point_received.wait(), 1)
        # The acquisition is genuinely in flight before the probe replaces
        # NSAP handlers. FieldTrends uses its own read lane, not bacnet.lock.
        assert connector.app.asap.clientTransactions
        assert len(peer.held_point_packets) == 1
        if mode == "single":
            peer.probe_hold_props = {"model-name"}
            pending = asyncio.create_task(service.probe(router=peer.endpoint, dnet=2105, mac=7))
            while True:
                name, _ = await asyncio.wait_for(peer.probe_received.get(), 1)
                if name == "model-name":
                    break
        else:
            peer.property_received.clear()
            pending = asyncio.create_task(
                service.probe_range(
                    router=peer.endpoint,
                    dnet=2105,
                    mac_low=1,
                    mac_high=32,
                )
            )
            await asyncio.wait_for(peer.property_received.wait(), 1)
        assert not pending.done() and connector.lock.locked()
        for packet, destination in peer.held_point_packets:
            peer.transport.sendto(bvlc(packet), destination)
        async with asyncio.timeout(1):
            while not trends.store.trends(source=job["source"]):
                await asyncio.sleep(0.01)
        rows = trends.store.trends(source=job["source"])
        assert len(rows) == 1 and rows[0]["value"] == 12.5
        assert rows[0]["quality"] == "unknown" and rows[0]["source_kind"] == "field"
        assert not trends.status()["jobs"][0]["failures"]
        await trends.stop(job["id"])
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not connector.app.asap.clientTransactions and not connector.app._requests
        assert not connector.lock.locked()
        assert "process_npdu" not in connector.app.nsap.__dict__
        assert "indication" not in connector.app.nsap.__dict__
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass
        await trends.close()


async def test_probe_wildcard_ack_value_cannot_disagree_with_actual_device_id(rig):
    service, connector, peer, _ = rig
    await open_probe(connector, peer)
    original_oid = b"\xc4" + ((8 << 22) | 132007).to_bytes(4, "big")
    wrong_oid = b"\xc4" + ((8 << 22) | 132008).to_bytes(4, "big")
    peer.response_transform = lambda packet: packet.replace(original_oid, wrong_oid)
    with pytest.raises(ValueError, match="differs from"):
        await service.probe(router=peer.endpoint, dnet=2105, mac=7)
    assert len(peer.frames) == 1 and not connector.lock.locked()


@pytest.mark.parametrize("change", [{"mac": True}, {"mac": 255}, {"mac": -1}, {"dnet": 65535}])
def test_probe_strict_mac_and_network_bounds(change):
    with pytest.raises(ValueError):
        RouterProbeRequest(**{"router": "127.0.0.1", "dnet": 2105, "mac": 7, **change})


async def test_real_mac_page_reports_one_identity_and_timeouts_as_unknown_with_actual_pacing(rig):
    service, connector, peer, _ = rig
    await open_probe(connector, peer)
    report = await service.probe_range(
        router=peer.endpoint,
        dnet=2105,
        mac_low=6,
        mac_high=8,
        per_mac_timeout_seconds=0.5,
    )
    assert [row["device_instance"] for row in report["devices"]] == [132007]
    assert [row["mac"] for row in report["no_response"]] == [6, 8]
    assert [row["outcome"] for row in report["attempts"]] == ["timeout", "identified", "timeout"]
    assert report["complete"] and not report["truncated"] and report["next_mac"] is None
    assert report["request"]["spacing_seconds"] == 0.1
    assert len(peer.frames) == 3 and all(
        right - left >= 0.099
        for left, right in zip(peer.receipt_times, peer.receipt_times[1:], strict=False)
    )
    assert not connector.app.asap.clientTransactions and not connector.app._requests
    assert not connector.lock.locked()


async def test_mac_page_deadline_retains_partial_evidence_and_explicit_resume_cursor(rig):
    service, connector, peer, _ = rig
    await open_probe(connector, peer)
    report = await service.probe_range(
        router=peer.endpoint,
        dnet=2105,
        mac_low=1,
        mac_high=4,
        per_mac_timeout_seconds=0.5,
        timeout_seconds=1.0,
    )
    assert len(report["attempts"]) == 1 and report["attempts"][0]["mac"] == 1
    assert not report["complete"] and report["truncated"] and report["next_mac"] == 2
    assert len(peer.frames) == 1 and not connector.app.asap.clientTransactions


async def test_mac_page_preserves_duplicate_device_instances_on_distinct_addresses(rig):
    service, connector, peer, _ = rig
    await open_probe(connector, peer)
    peer.probe_devices[(2105, b"\x08")] = peer.probe_devices[(2105, b"\x07")].copy()
    report = await service.probe_range(router=peer.endpoint, dnet=2105, mac_low=7, mac_high=8)
    assert [row["address"] for row in report["devices"]] == ["2105:7", "2105:8"]
    assert [row["device_instance"] for row in report["devices"]] == [132007, 132007]
    assert any("Duplicate Device" in row for row in report["warnings"])


async def test_mac_page_protocol_error_is_distinct_from_silence_and_advance_continues(rig):
    service, connector, peer, _ = rig
    await open_probe(connector, peer)
    peer.probe_reject_props = {"object-identifier"}
    report = await service.probe_range(
        router=peer.endpoint,
        dnet=2105,
        mac_low=7,
        mac_high=8,
        per_mac_timeout_seconds=0.5,
    )
    assert report["devices"] == []
    assert report["errors"][0]["mac"] == 7 and report["errors"][0]["outcome"] == "error"
    assert report["no_response"][0]["mac"] == 8
    assert report["complete"]


async def test_mac_page_cancel_stops_future_requests_and_restores_hooks(rig):
    service, connector, peer, _ = rig
    await open_probe(connector, peer)
    pending = asyncio.create_task(
        service.probe_range(router=peer.endpoint, dnet=2105, mac_low=1, mac_high=10)
    )
    await asyncio.wait_for(peer.received.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert len(peer.frames) == 1 and not connector.app.asap.clientTransactions
    assert not connector.app._requests and not connector.lock.locked()
    assert "process_npdu" not in connector.app.nsap.__dict__
    assert "indication" not in connector.app.nsap.__dict__
    await asyncio.sleep(0.2)
    assert len(peer.frames) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"mac_low": True},
        {"mac_low": -1},
        {"mac_high": 255},
        {"mac_low": 20, "mac_high": 19},
        {"mac_low": 0, "mac_high": 32},
        {"per_mac_timeout_seconds": 0.49},
        {"per_mac_timeout_seconds": 2.1},
        {"spacing_seconds": 0.099},
        {"spacing_seconds": True},
        {"timeout_seconds": 30.1},
    ],
)
def test_mac_page_strict_bounds(change):
    with pytest.raises(ValueError):
        ProbeTrunkRequest(
            **{
                "router": "127.0.0.1",
                "dnet": 2105,
                "mac_low": 1,
                "mac_high": 8,
                **change,
            }
        )


async def test_malformed_and_out_of_profile_iams_are_not_discovery_evidence(rig):
    service, _, peer, _ = rig
    valid = iam(132081, b"\x51")
    peer.extra_packets = [
        valid.replace(b"\x91\x03", b"\x91\x09"),  # Unknown segmentation.
        iam(4194303, b"\x52"),  # Reserved Device instance.
        iam(132082, b"\xff"),  # MS/TP broadcast cannot identify a device.
        valid + b"\x21\x00",  # Extra application tag.
        valid[:-1],  # Truncated vendor value.
    ]
    report = await service.scan(router=peer.endpoint, dnet=2105, timeout_seconds=1.0)
    assert [row["device_instance"] for row in report["devices"]] == [132079, 132080]
    assert report["invalid_responses"] == len(peer.extra_packets)
    assert any("Malformed" in value for value in report["warnings"])


async def test_packet_budget_ends_window_as_incomplete_without_retaining_excess(rig, monkeypatch):
    service, _, peer, _ = rig
    monkeypatch.setattr("bms_tool.routed_discovery.MAX_OBSERVATIONS", 2)
    peer.devices += [(132081, b"\x51", 2105), (132082, b"\x52", 2105)]
    report = await service.scan(router=peer.endpoint, dnet=2105, timeout_seconds=3.0)
    assert not report["complete"] and report["truncated"]
    assert len(report["devices"]) == 2 and report["responses"] == 2


async def test_busy_lock_never_transmits_and_does_not_release_someone_elses_lock(rig, monkeypatch):
    service, connector, peer, _ = rig
    monkeypatch.setattr("bms_tool.routed_discovery.LOCK_TIMEOUT_SECONDS", 0.02)
    await connector.lock.acquire()
    try:
        for operation in (
            service.networks(router=peer.endpoint),
            service.scan(router=peer.endpoint, dnet=2105),
            service.bindings(router=peer.endpoint, device=505),
        ):
            with pytest.raises(ValueError, match="busy"):
                await operation
            assert connector.lock.locked()
        assert not peer.frames
    finally:
        connector.lock.release()


async def test_udp_failure_during_window_restores_observer_and_releases_lock(rig):
    service, connector, peer, _ = rig
    peer.drop = True
    task = asyncio.create_task(service.networks(router=peer.endpoint, timeout_seconds=3.0))
    await asyncio.wait_for(peer.received.wait(), 1)
    app = connector.app
    for layer in app.link_layers.values():
        layer.server.local_transport.close()
    with pytest.raises(ValueError, match="stopped"):
        await task
    assert not connector.lock.locked() and "process_npdu" not in app.nsap.__dict__


async def test_adapter_send_failure_restores_existing_observer_and_lock(rig, monkeypatch):
    service, connector, peer, _ = rig
    app = connector.app
    original = app.nsap.process_npdu

    async def existing(adapter, packet):
        await original(adapter, packet)

    async def failed(packet):
        raise OSError("injected send failure")

    app.nsap.process_npdu = existing
    monkeypatch.setattr(app.nsap.local_adapter, "process_npdu", failed)
    with pytest.raises(OSError, match="injected"):
        await service.networks(router=peer.endpoint)
    assert app.nsap.__dict__["process_npdu"] is existing
    assert not connector.lock.locked() and not peer.frames


async def test_audit_failure_preserves_successful_wire_evidence(rig, monkeypatch):
    service, _, peer, _ = rig

    def failure(*arguments):
        raise OSError("disk full")

    monkeypatch.setattr(service.audit_store, "record", failure)
    result = await service.bindings(router=peer.endpoint, device=505)
    assert result["bindings"] and result["audit_error"]


@pytest.mark.parametrize("kind", ["object", "property", "array", "malformed"])
async def test_binding_ack_identity_and_malformed_value_rejected_and_retired(rig, kind):
    service, connector, peer, _ = rig

    def changed(response):
        if kind == "object":
            return response.replace(b"\x0c\x02\x00\x01\xf9", b"\x0c\x02\x00\x01\xfa")
        if kind == "property":
            return response.replace(b"\x19\x1e", b"\x19\x1f")
        if kind == "array":
            return response.replace(b"\x19\x1e\x3e", b"\x19\x1e\x29\x01\x3e")
        return response.replace(b"\x3e\xc4", b"\x3e\x74", 1)

    peer.response_transform = changed
    with pytest.raises(ValueError, match="mismatch|Malformed"):
        await service.bindings(router=peer.endpoint, device=505)
    assert not connector.app.asap.clientTransactions and not connector.app._requests
    assert not connector.lock.locked()


@pytest.mark.parametrize(
    "router",
    [
        "*",
        "*:*",
        "2105:*",
        "255.255.255.255",
        "224.1.2.3",
        "0.0.0.0",
        "localhost",
        "127.0.0.1/24",
        "127.0.0.1:0",
        "127.0.0.1:65536",
        "::1",
        "127.0.0.1 ",
    ],
)
def test_router_never_accepts_broadcast_hostname_prefix_or_invalid_port(router):
    with pytest.raises(ValueError):
        RouterNetworksRequest(router=router)


@pytest.mark.parametrize(
    "body",
    [
        {"dnet": True},
        {"dnet": 65535},
        {"dnet": 0},
        {"low": True},
        {"low": 30, "high": 20},
        {"max_devices": 257},
        {"timeout_seconds": False},
        {"timeout_seconds": 11.0},
    ],
)
def test_strict_scan_bounds(body):
    with pytest.raises(ValueError):
        RoutedScanRequest(**{"router": "127.0.0.1", "dnet": 2105, **body})


def test_unknown_binding_instance_cannot_be_requested_as_router_identity():
    with pytest.raises(ValueError):
        RouterBindingsRequest(router="127.0.0.1", device=4194303)
    assert MAX_OBSERVATIONS == 4096
