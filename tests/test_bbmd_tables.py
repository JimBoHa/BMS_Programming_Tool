"""Independent raw UDP peers, no BACpypes BVLC response encoders."""

import asyncio
import hashlib
import socket
import struct

import pytest
from bacpypes3.comm import ApplicationServiceElement, bind
from bms_tool.bbmd_tables import BbmdInspection, BbmdTables
from bms_tool.connections import Bacnet
from bms_tool.storage import Store
from pydantic import ValidationError

from .test_connections import free_udp
from .test_foreign_bacnet import RawPoint, bvlc, wait_until


def endpoint(address):
    return f"{address[0]}:{address[1]}"


def entry(ip, port, tail):
    return socket.inet_aton(ip) + struct.pack(">H", port) + tail


BDT = bvlc(
    3,
    entry("10.2.3.4", 47808, bytes.fromhex("ffffff00"))
    + entry("10.3.0.5", 47809, bytes.fromhex("ff00ff00"))
    + entry("10.3.0.6", 47808, bytes.fromhex("000000ff")),
)
FDT = bvlc(7, entry("10.4.5.6", 47900, struct.pack(">HH", 60, 89)))


class RawTables(asyncio.DatagramProtocol):
    def __init__(self):
        self.frames = []
        self.errors = []
        self.responses = {2: BDT, 6: FDT}
        self.delay = 0
        self.registration_delay = 0
        self.registration_extra = None
        self.before = None
        self.handles = []

    def connection_made(self, transport):
        self.transport = transport
        self.address = transport.get_extra_info("sockname")

    def later(self, delay, data, destination):
        self.handles.append(
            asyncio.get_running_loop().call_later(delay, self.transport.sendto, data, destination)
        )

    def datagram_received(self, data, address):
        try:
            self.frames.append((data, address, asyncio.get_running_loop().time()))
            assert data[0] == 0x81 and int.from_bytes(data[2:4], "big") == len(data)
            function = data[1]
            if function == 5:
                assert len(data) == 6
                if data[4:6] != b"\0\0":
                    if self.registration_extra is not None:
                        self.transport.sendto(self.registration_extra, address)
                    self.later(self.registration_delay, bvlc(0, b"\0\0"), address)
                return
            assert function in (2, 6) and len(data) == 4
            if self.before is not None:
                self.before(function, address)
            if self.responses[function] is not None:
                self.later(self.delay, self.responses[function], address)
        except Exception as exc:
            self.errors.append(exc)


class NativeManagement(ApplicationServiceElement):
    def __init__(self):
        super().__init__()
        self.packets = []
        self.read_bdt_future = None
        self.read_fdt_future = None

    async def confirmation(self, packet):
        self.packets.append(packet)


@pytest.fixture
async def wire(tmp_path):
    loop = asyncio.get_running_loop()
    transport, peer = await loop.create_datagram_endpoint(RawTables, local_addr=("127.0.0.1", 0))
    rogue, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = BbmdTables(client)
    try:
        yield peer, rogue, client, service
    finally:
        await service.close()
        client.close()
        for handle in peer.handles:
            handle.cancel()
        transport.close()
        rogue.close()
        await asyncio.sleep(0.02)
        assert not peer.errors


async def complete(service, started):
    await wait_until(lambda: not service.jobs[started["id"]]["active"], 3)
    return service.detail(started["id"])


async def test_exact_wire_tables_preserve_masks_and_leases_pacing_and_immutable_evidence(wire):
    peer, _, client, service = wire
    layer = client.app.nsap.local_adapter.clientPeer
    original = layer.multiplexer.confirmation
    assert service.status()["jobs"] == [] and peer.frames == []
    result = await complete(service, service.start(endpoint=endpoint(peer.address)))
    assert result["state"] == "complete"
    assert [frame[0] for frame in peer.frames] == [b"\x81\x02\x00\x04", b"\x81\x06\x00\x04"]
    assert peer.frames[1][2] - peer.frames[0][2] >= 0.09
    bdt, fdt = result["tables"]["bdt"], result["tables"]["fdt"]
    assert bdt["rows"][0]["mask"] == "255.255.255.0"
    assert bdt["rows"][1]["mask"] == "255.0.255.0" and not bdt["rows"][1]["mask_contiguous"]
    assert bdt["rows"][1]["mask_prefix_length"] is None
    assert not bdt["rows"][2]["mask_contiguous"]  # native netmask, never hostmask notation
    assert fdt["rows"][0]["ttl_seconds"] == 60 and fdt["rows"][0]["remaining_seconds"] == 89
    assert bytes.fromhex(bdt["response"]["raw_hex"]) == BDT
    assert bdt["response"]["sha256"] == hashlib.sha256(BDT).hexdigest()
    assert result["local_endpoint"] == client.config["local_address"]
    assert len(result["interface_id"]) == 24
    assert result["config"] == client.config and result["endpoint"] == endpoint(peer.address)
    result["endpoint"] = "changed"
    result["tables"]["bdt"]["rows"].clear()
    assert service.detail(result["id"])["endpoint"] == endpoint(peer.address)
    assert len(service.detail(result["id"])["tables"]["bdt"]["rows"]) == 3
    assert layer.multiplexer.confirmation == original and not client.commands


@pytest.mark.parametrize(
    "response,state",
    [
        (bvlc(3, b""), "ok"),
        (b"\x81\x03\x00\x04x", "malformed"),
        (bvlc(3, b"\0" * 9), "malformed"),
        (bvlc(3, b"\0" * 2570), "bounds_exceeded"),
        (bvlc(3, b"\0" * 6000), "bounds_exceeded"),
        (bvlc(0, b"\x00\x20"), "nack"),
        (None, "timeout"),
    ],
)
async def test_empty_malformed_oversize_native_nack_and_timeout_are_distinct(wire, response, state):
    peer, _, _, service = wire
    peer.responses[2] = response
    result = await complete(
        service, service.start(endpoint=endpoint(peer.address), tables=["bdt"], timeout_seconds=0.1)
    )
    table = result["tables"]["bdt"]
    assert table["state"] == state and table["rows"] == []
    assert result["tables"]["fdt"]["state"] == "not_requested"
    if response is not None:
        assert table["response"]["sha256"] == hashlib.sha256(response).hexdigest()
        assert table["response"]["raw_complete"] == (len(response) <= 4096)
        assert len(table["response"]["raw_hex"]) <= 8192
    if state == "nack":
        assert table["result_code"] == 0x20 and "unsupported" in table["reason"]
    if state == "timeout":
        assert "unknown" in table["reason"] and "response" not in table


async def test_rogue_peer_wrong_table_and_unattributed_results_preserve_native_handler(wire):
    peer, rogue, client, service = wire
    native = NativeManagement()
    bind(native, client.app.nsap.local_adapter.clientPeer)

    def before(function, address):
        if function == 2:
            rogue.sendto(bvlc(0, b"\x00\x20"), address)
            rogue.sendto(BDT, address)
            peer.transport.sendto(FDT, address)
            peer.transport.sendto(bvlc(0, b"\x00\x10"), address)
            peer.transport.sendto(bvlc(0, b"\x00\x00"), address)

    peer.before = before
    peer.delay = 0.03
    result = await complete(service, service.start(endpoint=endpoint(peer.address)))
    assert result["tables"]["bdt"]["rows"][0]["ip"] == "10.2.3.4"
    assert result["ignored_peers"] == 2
    assert [item["result_code"] for item in result["unattributed_results"]] == [0x10, 0]
    assert len(native.packets) == 5  # two rogue, one unrelated FDT, two Results
    assert native.elementService is client.app.nsap.local_adapter.clientPeer


async def test_no_table_ack_is_synthesized_from_generic_success_or_other_nack(wire):
    peer, _, client, service = wire
    bind(NativeManagement(), client.app.nsap.local_adapter.clientPeer)
    peer.responses[2] = None
    peer.before = lambda function, address: [
        peer.transport.sendto(bvlc(0, struct.pack(">H", code)), address)
        for code in [0, 0x40, 0x1234] * 4
    ]
    result = await complete(
        service, service.start(endpoint=endpoint(peer.address), tables=["bdt"], timeout_seconds=0.1)
    )
    assert result["tables"]["bdt"]["state"] == "timeout"
    assert len(result["unattributed_results"]) == 8 and result["unattributed_results_omitted"] == 4


async def test_native_table_owner_conflicts_refuse_or_end_without_stealing_ack(wire):
    peer, _, client, service = wire
    native = NativeManagement()
    bind(native, client.app.nsap.local_adapter.clientPeer)
    native.read_bdt_future = asyncio.get_running_loop().create_future()
    with pytest.raises(ValueError, match="native BVLC"):
        service.start(endpoint=endpoint(peer.address))
    assert not peer.frames
    native.read_bdt_future.cancel()
    native.read_bdt_future = None
    peer.delay = 0.15
    started = service.start(endpoint=endpoint(peer.address), tables=["bdt"])
    await wait_until(lambda: bool(peer.frames))
    native.read_fdt_future = asyncio.get_running_loop().create_future()
    result = await complete(service, started)
    await wait_until(lambda: bool(native.packets))
    assert result["state"] == "failed" and result["tables"]["bdt"]["rows"] == []
    native.read_fdt_future.cancel()


async def test_cancel_waiting_lock_timeout_interface_loss_and_shutdown_retire_owned_work(
    wire, monkeypatch
):
    import bms_tool.bbmd_tables as module

    peer, _, client, service = wire
    layer = client.app.nsap.local_adapter.clientPeer
    original = layer.multiplexer.confirmation
    peer.responses[2] = None
    started = service.start(endpoint=endpoint(peer.address))
    await wait_until(lambda: bool(peer.frames))
    cancelled = await service.cancel(started["id"])
    assert cancelled["state"] == "cancelled" and layer.multiplexer.confirmation == original
    assert not client.lock.locked() and not cancelled["active"]
    monkeypatch.setattr(module, "LOCK_WAIT", 0.05)
    await client.lock.acquire()
    try:
        expired = await complete(service, service.start(endpoint=endpoint(peer.address)))
        assert expired["state"] == "deadline" and len(peer.frames) == 1
    finally:
        client.lock.release()
    replacement = service.start(endpoint=endpoint(peer.address))
    await wait_until(lambda: len(peer.frames) == 2)
    client.close()
    changed = await complete(service, replacement)
    assert changed["state"] == "failed" and layer.multiplexer.confirmation == original
    assert not client.lock.locked()
    await service.close()
    assert all(job["task"].done() for job in service.jobs.values())


async def test_whole_operation_deadline_and_immediate_cancel_have_no_detached_dispatch(
    wire, monkeypatch
):
    import bms_tool.bbmd_tables as module

    peer, _, _, service = wire
    first = service.start(endpoint=endpoint(peer.address))
    with pytest.raises(ValueError, match="already running"):
        service.start(endpoint=endpoint(peer.address))
    await service.cancel(first["id"])
    assert not peer.frames and not service.jobs[first["id"]]["active"]
    peer.responses[2] = None
    monkeypatch.setattr(module, "OPERATION_SECONDS", 0.1)
    ended = await complete(
        service, service.start(endpoint=endpoint(peer.address), timeout_seconds=5.0)
    )
    assert ended["state"] == "deadline" and len(peer.frames) == 1
    for _ in range(18):
        await service.cancel(service.start(endpoint=endpoint(peer.address))["id"])
    assert len(service.jobs) == 16 and service.evicted == 4


async def test_foreign_registration_renewals_and_concurrent_point_reads_continue(wire):
    peer, _, client, service = wire
    peer.registration_delay = 0.05
    await client.connect(
        client.config["local_address"], bbmd_address=endpoint(peer.address), foreign_ttl=1
    )
    foreign = client.app.foreign_link
    # A late management NACK must not become a foreign renewal rejection.
    peer.registration_extra = bvlc(0, b"\x00\x20")
    await wait_until(lambda: foreign.attempts >= 2 and foreign._pending)
    peer.responses[2] = bvlc(0, b"\x00\x20")
    peer.delay = 0.15
    transport, point = await asyncio.get_running_loop().create_datagram_endpoint(
        RawPoint, local_addr=("127.0.0.1", 0)
    )
    try:
        started = service.start(endpoint=endpoint(peer.address))
        value = await client.read(endpoint(point.address), "analog-input,1")
        result = await complete(service, started)
        await wait_until(lambda: foreign.acknowledgements >= 2)
        assert value["value"] == 12.5 and not point.errors
        assert result["tables"]["bdt"]["state"] == "nack"
        assert result["tables"]["fdt"]["state"] == "ok"
        assert foreign.status()["registered"] and foreign.ignored_results >= 1
        assert client.status()["config"]["foreign_ttl"] == 1 and not client.commands
    finally:
        transport.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"endpoint": "example.com"},
        {"endpoint": "127.0.0.1/24"},
        {"endpoint": "::1"},
        {"endpoint": "224.0.0.1"},
        {"endpoint": "255.255.255.255"},
        {"endpoint": "0.0.0.0"},
        {"endpoint": "127.0.0.1:0"},
        {"endpoint": "127.0.0.1:65536"},
        {"endpoint": " 127.0.0.1"},
        {"tables": ["bdt", "bdt"]},
        {"tables": []},
        {"tables": ["write-bdt"]},
        {"timeout_seconds": True},
        {"timeout_seconds": 5.1},
    ],
)
def test_invalid_unbounded_or_write_requests_are_rejected(changes):
    with pytest.raises(ValidationError):
        BbmdInspection(**({"endpoint": "127.0.0.1"} | changes))


async def test_fdt_native_nack_and_known_local_broadcast_refusal(wire):
    peer, _, client, service = wire
    with pytest.raises(ValueError, match="own socket"):
        service.start(endpoint=client.config["local_address"])
    with pytest.raises(ValueError, match="network/broadcast"):
        service.start(endpoint="127.255.255.255")
    assert not peer.frames
    peer.responses[6] = bvlc(0, b"\x00\x40")
    result = await complete(service, service.start(endpoint=endpoint(peer.address), tables=["fdt"]))
    assert result["tables"]["fdt"]["state"] == "nack"
    assert result["tables"]["fdt"]["result_code"] == 0x40


async def test_socket_identity_replacement_is_detected_even_with_same_app_and_config(wire):
    peer, _, client, service = wire
    layer = client.app.nsap.local_adapter.clientPeer
    transport = layer.server.local_transport
    peer.responses[2] = None
    started = service.start(endpoint=endpoint(peer.address))
    await wait_until(lambda: bool(peer.frames))

    class Replacement:
        def __getattr__(self, name):
            return getattr(transport, name)

    try:
        layer.server.local_transport = Replacement()
        result = await complete(service, started)
        assert result["state"] == "failed" and "socket identity changed" in result["reason"]
        assert len(peer.frames) == 1 and result["tables"]["bdt"]["rows"] == []
    finally:
        layer.server.local_transport = transport


async def test_short_lived_native_owner_cannot_disappear_before_loss_of_ownership_is_recorded(wire):
    peer, _, client, service = wire

    class CompletingNative(NativeManagement):
        async def confirmation(self, packet):
            self.packets.append(packet)
            self.read_bdt_future.set_result(packet)
            self.read_bdt_future = None

    native = CompletingNative()
    bind(native, client.app.nsap.local_adapter.clientPeer)

    def before(function, address):
        native.read_bdt_future = asyncio.get_running_loop().create_future()

    peer.before = before
    result = await complete(service, service.start(endpoint=endpoint(peer.address), tables=["bdt"]))
    assert result["state"] == "failed" and "native BVLC" in result["reason"]
    assert len(native.packets) == 1 and native.read_bdt_future is None
    assert result["tables"]["bdt"]["rows"] == []
