"""Actual loopback UDP/TCP tests; no building addresses or broadcast scans."""

import asyncio
import os
import select
import socket
import struct
import threading
import time
from argparse import Namespace

import pytest
from bacpypes3.app import Application
from bacpypes3.local.analog import AnalogValueObjectCmd
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.vlan import VirtualNetwork
from bms_tool.connections import Bacnet, _unicast, crc16, modbus_read
from bms_tool.storage import Store


@pytest.mark.skipif(os.name != "posix", reason="Real pseudoterminal test requires POSIX")
@pytest.mark.parametrize("corrupt", [False, True])
def test_real_serial_rtu_exchange_and_crc_rejection(monkeypatch, corrupt):
    """Exercise pyserial and an OS serial stream, including fragmented bytes."""
    master, slave = os.openpty()
    address = os.ttyname(slave)
    monkeypatch.setattr("bms_tool.connections.ports", lambda: [{"device": address}])
    errors = []

    def controller():
        try:
            request = b""
            deadline = time.monotonic() + 4
            while len(request) < 8 and time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    request += os.read(master, 8 - len(request))
            # Fixed RTU frames avoid generating a response with the CRC routine
            # under test. Read holding register zero; return decimal ten.
            assert request.hex() == "010300000001840a"
            response = bytes.fromhex("010302000a3843")
            if corrupt:
                response = response[:-1] + bytes([response[-1] ^ 1])
            for chunk in (response[:2], response[2:4], response[4:]):
                os.write(master, chunk)
                time.sleep(0.01)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=controller, daemon=True)
    thread.start()
    try:
        if corrupt:
            with pytest.raises(ValueError, match="CRC"):
                modbus_read("rtu", address, register=0, count=1)
        else:
            assert modbus_read("rtu", address, register=0, count=1)["values"] == [10]
        thread.join(timeout=5)
        assert not thread.is_alive() and not errors
    finally:
        os.close(master)
        os.close(slave)


def free_udp():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def application(port, instance):
    return Application.from_args(
        Namespace(
            address=f"127.0.0.1:{port}",
            instance=instance,
            name="Studio isolated test device",
            vendoridentifier=999,
            network=0,
            foreign=None,
            ttl=30,
            bbmd=None,
        )
    )


def point():
    return AnalogValueObjectCmd(
        objectIdentifier=("analog-value", 1),
        objectName="Loopback test value",
        presentValue=12.5,
        units="no-units",
        outOfService=False,
        statusFlags=[0, 0, 0, 0],
    )


@pytest.mark.asyncio
async def test_real_udp_discovery_read_command_and_release(tmp_path):
    server_port = free_udp()
    server = application(server_port, 4190010)
    server.add_object(point())
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{server_port}"
        devices = await client.discover(target)
        assert devices and "4190010" in devices[0]["device"]
        assert (await client.read(target, "analog-value,1"))["value"] == 12.5
        plan = await client.plan_write(target, "analog-value,1", 42.25, 16)
        result = await client.apply_write(plan["token"])
        assert result["present_value"] == 42.25 and result["slot"]["value"] == 42.25
        with pytest.raises(ValueError, match="occupied"):
            await client.plan_write(target, "analog-value,1", 99, 16)
        # An actual restart must retain ownership and permit recovery through the
        # same configured interface, without overwriting an unrelated priority.
        saved_config = client.config.copy()
        client.close()
        await asyncio.sleep(0.1)
        client = Bacnet(Store(tmp_path))
        assert result["command"] in client.commands
        await client.connect(**saved_config)
        released = await client.release(result["command"])
        assert released["present_value"] == 12.5 and released["released"]
        assert not client.commands
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_actual_npdu_routing_via_udp_to_virtual_field_network(tmp_path):
    # The virtual BACnet network is a data-link surrogate. This tests the real
    # DNET/DADR routing path over UDP; it does not emulate MS/TP token timing.
    name = "studio-test-" + str(free_udp())
    VirtualNetwork(name)
    router_port = free_udp()
    router = Application.from_object_list(
        [
            DeviceObject(objectIdentifier=("device", 4190011), objectName="Loopback router"),
            NetworkPortObject(
                f"127.0.0.1:{router_port}",
                objectIdentifier=("network-port", 1),
                objectName="IP port",
                networkNumber=100,
                networkNumberQuality="configured",
            ),
            NetworkPortObject(
                objectIdentifier=("network-port", 2),
                objectName="Virtual field port",
                macAddress=b"\x02",
                networkType="virtual",
                networkInterfaceName=name,
                networkNumber=2001,
                networkNumberQuality="configured",
                protocolLevel="bacnet-application",
            ),
        ]
    )
    field = Application.from_object_list(
        [
            DeviceObject(objectIdentifier=("device", 4190012), objectName="Virtual field VAV"),
            NetworkPortObject(
                objectIdentifier=("network-port", 1),
                objectName="Virtual port",
                macAddress=b"\x04",
                networkType="virtual",
                networkInterfaceName=name,
                protocolLevel="bacnet-application",
            ),
            point(),
        ]
    )
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(
            f"127.0.0.1:{free_udp()}", router=f"127.0.0.1:{router_port}", dnet=2001
        )
        result = await client.read("2001:4", "analog-value,1")
        assert result["value"] == 12.5
        devices = await client.discover("2001:4", 4190012, 4190012)
        assert devices and devices[0]["address"] == "2001:4"
        plan = await client.plan_write("2001:4", "analog-value,1", 42.25)
        commanded = await client.apply_write(plan["token"])
        assert commanded["present_value"] == 42.25
        assert (await client.release(commanded["command"]))["present_value"] == 12.5
    finally:
        client.close()
        field.close()
        router.close()
        await asyncio.sleep(0.1)


def test_modbus_tcp_real_socket_read():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve():
        conn, _ = listener.accept()
        with conn:
            frame = conn.recv(12)
            transaction, protocol, length, unit = struct.unpack(">HHHB", frame[:7])
            assert protocol == 0 and length == 6
            assert frame[7:] == struct.pack(">BHH", 3, 10, 2)
            response = struct.pack(">BBHH", 3, 4, 100, 65535)
            packet = struct.pack(">HHHB", transaction, 0, len(response) + 1, unit) + response
            # Deliberately fragmented TCP response must be assembled correctly.
            conn.sendall(packet[:4])
            conn.sendall(packet[4:])
        listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    result = modbus_read("tcp", "127.0.0.1", port=port, unit=7, register=10, count=2)
    thread.join(3)
    assert result["values"] == [100, 65535]


def test_modbus_crc_and_parameter_validation():
    assert crc16(bytes.fromhex("01030000000a")) == 0xCDC5
    with pytest.raises(ValueError, match="Invalid Modbus"):
        modbus_read("tcp", "127.0.0.1", register=-1)


@pytest.mark.parametrize("address", ["*", "*:*", "255.255.255.255", "2001:*"])
def test_commissioning_interface_refuses_broadcast(address):
    with pytest.raises(ValueError):
        _unicast(address)
