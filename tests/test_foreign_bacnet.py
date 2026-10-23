"""BACnet foreign registration/discovery against independently encoded UDP peers."""

import asyncio
import socket
import struct
import time

import pytest
from bacpypes3.pdu import IPv4Address
from bms_tool.connections import Bacnet
from bms_tool.foreign_bacnet import create_foreign_application
from bms_tool.storage import Store

from tests.test_connections import application, point

# The NPDU/APDU payloads match the independently C-verified MS/TP fixtures;
# BVLC framing below is authored independently of the BACpypes codec.
I_AM_NPDU = bytes.fromhex("01001000c4023fef3c2201e091032203e7")
READ_VALUE_SUFFIX = bytes.fromhex("0c0c0000000119553e44414800003f")


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def bvlc(function, payload):
    return bytes([0x81, function]) + struct.pack(">H", len(payload) + 4) + payload


class RawPoint(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        self.address = transport.get_extra_info("sockname")
        self.reads = []
        self.errors = []

    def datagram_received(self, data, address):
        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            payload = data[4:]
            assert payload[:2] == b"\x01\x04" and payload[2] & 0xF0 == 0
            assert payload[5:] == bytes.fromhex("0c0c000000011955")
            self.reads.append(data)
            response = b"\x01\x00\x30" + payload[4:5] + READ_VALUE_SUFFIX
            self.transport.sendto(bvlc(10, response), address)
        except Exception as exc:
            self.errors.append(exc)


class RawBBMD(asyncio.DatagramProtocol):
    def __init__(self, point):
        self.point = point
        self.frames = []
        self.errors = []
        self.drop = False
        self.code = 0
        self.rogue = None
        self.destination = None
        self.malformed_first = False
        self.registration_result_delay = 0.0
        self.delayed_registration_results = set()
        self.iam_instances = [4190012]
        self.expected_whois = bytes.fromhex("010010080b3fef3c1b3fef3c")

    def connection_made(self, transport):
        self.transport = transport
        self.address = transport.get_extra_info("sockname")

    def connection_lost(self, exc):
        for handle in self.delayed_registration_results:
            handle.cancel()
        self.delayed_registration_results.clear()

    def datagram_received(self, data, address):
        try:
            assert data[0] == 0x81 and int.from_bytes(data[2:4], "big") == len(data)
            self.frames.append((data, address, time.monotonic()))
            self.destination = address
            if data[1] == 5:
                assert len(data) == 6
                ttl = int.from_bytes(data[4:6], "big")
                if ttl and not self.drop:
                    if self.malformed_first:
                        self.transport.sendto(bvlc(0, b"\x00\x00\x99\x99"), address)
                        asyncio.get_running_loop().call_later(
                            0.01,
                            self.transport.sendto,
                            bvlc(0, struct.pack(">H", self.code)),
                            address,
                        )
                    elif self.rogue is not None:
                        self.rogue.sendto(b"\x81\x00\x00\x06\x00\x00", address)
                        asyncio.get_running_loop().call_later(
                            0.01,
                            self.transport.sendto,
                            bvlc(0, struct.pack(">H", self.code)),
                            address,
                        )
                    elif self.registration_result_delay:
                        result = bvlc(0, struct.pack(">H", self.code))

                        def send_result():
                            self.delayed_registration_results.discard(handle)
                            self.transport.sendto(result, address)

                        handle = asyncio.get_running_loop().call_later(
                            self.registration_result_delay, send_result
                        )
                        self.delayed_registration_results.add(handle)
                    else:
                        self.transport.sendto(bvlc(0, struct.pack(">H", self.code)), address)
            elif data[1] == 9:
                assert data[4:] == self.expected_whois
                origin = socket.inet_aton(self.point.address[0]) + struct.pack(
                    ">H", self.point.address[1]
                )
                for instance in self.iam_instances:
                    payload = (
                        I_AM_NPDU[:5] + ((8 << 22) | instance).to_bytes(4, "big") + I_AM_NPDU[9:]
                    )
                    forwarded = bvlc(4, origin + payload)
                    if self.rogue is not None:
                        self.rogue.sendto(forwarded, address)
                    self.transport.sendto(forwarded, address)
            else:
                raise AssertionError("Unexpected BBMD function: " + data.hex())
        except Exception as exc:
            self.errors.append(exc)

    def registrations(self):
        return [int.from_bytes(frame[0][4:6], "big") for frame in self.frames if frame[0][1] == 5]


@pytest.fixture
async def peers():
    loop = asyncio.get_running_loop()
    point_transport, point = await loop.create_datagram_endpoint(
        RawPoint, local_addr=("127.0.0.1", 0)
    )
    bbmd_transport, bbmd = await loop.create_datagram_endpoint(
        lambda: RawBBMD(point), local_addr=("127.0.0.1", 0)
    )
    rogue_transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    try:
        yield bbmd, point, rogue_transport
    finally:
        bbmd_transport.close()
        point_transport.close()
        rogue_transport.close()
        await asyncio.sleep(0.02)
        assert not bbmd.errors and not point.errors


async def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for expected wire state")
        await asyncio.sleep(0.01)


async def test_actual_registration_broadcast_forwarded_discovery_unicast_read_and_deregistration(
    peers, tmp_path
):
    bbmd, point, rogue = peers
    bbmd.rogue = rogue
    client = Bacnet(Store(tmp_path))
    local = f"127.0.0.1:{free_port()}"
    remote = f"127.0.0.1:{bbmd.address[1]}"
    try:
        config = await client.connect(local, bbmd_address=remote, foreign_ttl=60)
        assert config["bbmd_address"] == remote and config["foreign_ttl"] == 60
        status = client.status()
        assert status["connected"] and status["foreign_device"]["registered"]
        assert status["foreign_device"]["ignored_results"] == 1
        devices = await client.discover_foreign(4190012, 4190012)
        assert len(devices) == 1 and devices[0]["address"] == f"127.0.0.1:{point.address[1]}"
        assert "4190012" in devices[0]["device"]
        assert (await client.read(devices[0]["address"], "analog-input,1"))["value"] == 12.5
        assert point.reads and not client.commands
        await client.disconnect()
        await wait_until(lambda: bbmd.registrations()[-1:] == [0])
        assert not client.status()["connected"]
    finally:
        client.close()


@pytest.mark.parametrize("registration_result_delay", [0.0, 0.05])
async def test_real_short_ttl_renewal_stops_after_disconnect_and_restart_does_not_register(
    peers, tmp_path, registration_result_delay
):
    bbmd, _, _ = peers
    bbmd.registration_result_delay = registration_result_delay
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(
            f"127.0.0.1:{free_port()}", bbmd_address=f"127.0.0.1:{bbmd.address[1]}", foreign_ttl=1
        )
        # Receipt at the peer precedes its result and the client's processing.
        # Keep the existing bound, but await both independent wire milestones.
        await wait_until(
            lambda: (
                bbmd.registrations().count(1) >= 2
                and client.status()["foreign_device"]["acknowledgements"] >= 2
            ),
            2,
        )
        assert client.status()["foreign_device"]["acknowledgements"] >= 2
        await client.disconnect()
        await wait_until(lambda: bbmd.registrations()[-1:] == [0])
        before = len(bbmd.frames)
        await asyncio.sleep(1.1)
        assert len(bbmd.frames) == before
        restarted = Bacnet(Store(tmp_path))
        assert restarted.config["foreign_ttl"] == 1 and restarted.app is None
        await asyncio.sleep(0.05)
        assert len(bbmd.frames) == before
    finally:
        client.close()


async def test_rejected_initial_registration_fails_without_leaking_socket_or_worker(
    peers, tmp_path
):
    bbmd, _, _ = peers
    bbmd.code = 0x0030
    client = Bacnet(Store(tmp_path))
    local_port = free_port()
    with pytest.raises(ValueError, match="rejected"):
        await client.connect(f"127.0.0.1:{local_port}", bbmd_address=f"127.0.0.1:{bbmd.address[1]}")
    await asyncio.sleep(0.03)
    assert client.app is None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", local_port))
    before = len(bbmd.frames)
    await asyncio.sleep(0.05)
    assert len(bbmd.frames) == before


async def test_renewal_rejection_invalidates_health_and_same_config_can_reconnect(peers, tmp_path):
    bbmd, _, _ = peers
    client = Bacnet(Store(tmp_path))
    try:
        saved = await client.connect(
            f"127.0.0.1:{free_port()}", bbmd_address=f"127.0.0.1:{bbmd.address[1]}", foreign_ttl=1
        )
        bbmd.code = 0x0030
        await wait_until(lambda: not client.status()["connected"], 2)
        assert "rejected" in client.status()["foreign_device"]["error"]
        with pytest.raises(ValueError, match="rejected"):
            client.require()
        bbmd.code = 0
        old = client.app
        await client.connect(**saved)
        assert client.app is not old and client.status()["connected"]
    finally:
        client.close()


async def test_invalid_foreign_settings_preserve_working_socket_and_owned_config_is_pinned(
    peers, tmp_path
):
    bbmd, _, _ = peers
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_port()}")
        old = client.app
        for settings in (
            {"bbmd_address": "*"},
            {"bbmd_address": "127.0.0.1:0"},
            {"bbmd_address": "5"},
            {"bbmd_address": "127.0.0.1", "foreign_ttl": True},
            {"bbmd_address": "127.0.0.1", "foreign_ttl": 65536},
            {"foreign_ttl": 5},
            {"bbmd_address": client.config["local_address"]},
        ):
            with pytest.raises(ValueError):
                await client.connect(client.config["local_address"], **settings)
            assert client.app is old and client.status()["connected"]
        with pytest.raises(ValueError, match="registered"):
            await client.discover_foreign(4190012, 4190012)
        saved = await client.connect(
            client.config["local_address"], bbmd_address=f"127.0.0.1:{bbmd.address[1]}"
        )
        client.commands["owned-fixture"] = {
            "address": "127.0.0.1:9",
            "object_id": "analog-output,1",
            "priority": 16,
            "status": "owned",
        }
        with pytest.raises(ValueError, match="Relinquish"):
            await client.connect(**{**saved, "foreign_ttl": 61})
        assert client.status()["connected"] and client.require() is client.app
        client.commands.clear()
    finally:
        client.close()


@pytest.mark.parametrize("ttl", [60, 65535])
async def test_malformed_same_bbmd_result_cannot_ack_registration_and_max_ttl_has_bounded_lease(
    peers, tmp_path, ttl
):
    bbmd, _, _ = peers
    bbmd.malformed_first = True
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(
            f"127.0.0.1:{free_port()}", bbmd_address=f"127.0.0.1:{bbmd.address[1]}", foreign_ttl=ttl
        )
        status = client.status()["foreign_device"]
        assert status["registered"] and status["ignored_results"] == 1
        assert status["lease_duration_seconds"] == min(ttl + 30, 65535)
        assert bbmd.registrations() == [ttl]
    finally:
        client.close()


async def test_foreign_discovery_result_bound_cleans_collector_and_requires_narrower_query(
    peers, tmp_path, monkeypatch
):
    import bms_tool.connections as connections

    bbmd, _, _ = peers
    bbmd.iam_instances = [4190012, 4190013, 4190014]
    bbmd.expected_whois = bytes.fromhex("010010080b3fef3c1b3fef3e")
    client = Bacnet(Store(tmp_path))
    monkeypatch.setattr(connections, "MAX_FOREIGN_DEVICES", 2)
    try:
        await client.connect(
            f"127.0.0.1:{free_port()}", bbmd_address=f"127.0.0.1:{bbmd.address[1]}"
        )
        with pytest.raises(ValueError, match="result limit"):
            await client.discover_foreign(4190012, 4190014)
        await asyncio.sleep(0)
        assert not client.app._who_is_futures and client.status()["connected"]
    finally:
        client.close()


async def test_actual_unavailable_local_address_bind_failure_cancels_endpoint_retries(peers):
    bbmd, _, _ = peers
    loop = asyncio.get_running_loop()
    old = loop.get_exception_handler()
    errors = []
    before = asyncio.all_tasks()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    try:
        with pytest.raises(ValueError, match="Could not bind"):
            await create_foreign_application(
                IPv4Address(f"192.0.2.250:{free_port()}"),
                IPv4Address(f"127.0.0.1:{bbmd.address[1]}"),
                60,
            )
        await asyncio.sleep(0.02)
        assert not [
            task
            for task in asyncio.all_tasks() - before
            if "retrying_create_datagram_endpoint" in task.get_coro().__qualname__
        ]
        assert not errors and not bbmd.frames
    finally:
        loop.set_exception_handler(old)


async def test_real_owned_priority_command_survives_foreign_session_restart_and_relinquishes(
    peers, tmp_path
):
    bbmd, _, _ = peers
    server_port = free_port()
    server = application(server_port, 4190012)
    server.add_object(point())
    client = Bacnet(Store(tmp_path))
    try:
        saved = await client.connect(
            f"127.0.0.1:{free_port()}", bbmd_address=f"127.0.0.1:{bbmd.address[1]}"
        )
        target = f"127.0.0.1:{server_port}"
        plan = await client.plan_write(target, "analog-value,1", 42.25, 16)
        result = await client.apply_write(plan["token"])
        assert result["present_value"] == 42.25
        client.close()
        await asyncio.sleep(0.03)
        client = Bacnet(Store(tmp_path))
        assert client.app is None and result["command"] in client.commands
        with pytest.raises(ValueError, match="Relinquish"):
            await client.connect(**{**saved, "bbmd_address": "127.0.0.1:9"})
        await client.connect(**saved)
        released = await client.release(result["command"])
        assert released["released"] and released["present_value"] == 12.5
        assert not client.commands
    finally:
        client.close()
        server.close()


async def test_missing_initial_ack_and_cancelled_connect_do_not_leave_registration_or_socket(
    peers, tmp_path
):
    bbmd, _, _ = peers
    bbmd.drop = True
    client = Bacnet(Store(tmp_path))
    local_port = free_port()
    with pytest.raises(ValueError, match="did not acknowledge"):
        await client.connect(f"127.0.0.1:{local_port}", bbmd_address=f"127.0.0.1:{bbmd.address[1]}")
    assert client.app is None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", local_port))
    bbmd.frames = []
    task = asyncio.create_task(
        client.connect(f"127.0.0.1:{local_port}", bbmd_address=f"127.0.0.1:{bbmd.address[1]}")
    )
    await wait_until(lambda: 60 in bbmd.registrations())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.03)
    assert client.app is None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", local_port))
    before = len(bbmd.frames)
    await asyncio.sleep(0.05)
    assert len(bbmd.frames) == before


async def test_real_ttl_plus_grace_expiration_after_lost_renewal_acks_fails_closed(peers, tmp_path):
    bbmd, _, _ = peers
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(
            f"127.0.0.1:{free_port()}", bbmd_address=f"127.0.0.1:{bbmd.address[1]}", foreign_ttl=1
        )
        bbmd.drop = True
        started = time.monotonic()
        await wait_until(lambda: not client.status()["foreign_device"]["worker_alive"], 32)
        assert 30 < time.monotonic() - started < 32
        status = client.status()["foreign_device"]
        assert not status["registered"] and status["lease_remaining_seconds"] == 0
        assert "expired" in status["error"] and bbmd.registrations().count(1) > 2
        with pytest.raises(ValueError, match="expired"):
            client.require()
    finally:
        client.close()


async def test_dead_udp_transport_is_not_reported_as_healthy_registration(peers, tmp_path):
    bbmd, _, _ = peers
    client = Bacnet(Store(tmp_path))
    try:
        saved = await client.connect(
            f"127.0.0.1:{free_port()}", bbmd_address=f"127.0.0.1:{bbmd.address[1]}"
        )
        client.app.foreign_link.server.local_transport.close()
        assert not client.status()["connected"]
        with pytest.raises(ValueError, match="registration"):
            client.require()
        await client.connect(**saved)
        assert client.status()["connected"]
    finally:
        client.close()


async def test_shutdown_stops_renewal_even_when_pending_command_audit_fails(
    peers, tmp_path, monkeypatch
):
    bbmd, _, _ = peers
    client = Bacnet(Store(tmp_path))
    await client.connect(
        f"127.0.0.1:{free_port()}", bbmd_address=f"127.0.0.1:{bbmd.address[1]}", foreign_ttl=1
    )
    client.commands["owned-fixture"] = {
        "address": "127.0.0.1:9",
        "object_id": "analog-output,1",
        "priority": 16,
        "status": "owned",
    }

    def fail(*args):
        raise OSError("synthetic audit disk error")

    monkeypatch.setattr(client.store, "record", fail)
    with pytest.raises(OSError, match="audit disk error"):
        client.close()
    assert client.app is None and client.commands
    await wait_until(lambda: bbmd.registrations()[-1:] == [0])
    before = len(bbmd.frames)
    await asyncio.sleep(1.1)
    assert len(bbmd.frames) == before
