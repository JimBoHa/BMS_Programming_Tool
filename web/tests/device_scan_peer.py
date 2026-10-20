"""Authored loopback discovery packets and native Device/Program responses."""

import asyncio
import json
import socket
import sys

from bacpypes3.apdu import APDU, APCISequence, ReadPropertyRequest
from bacpypes3.errors import ExecutionError
from bacpypes3.pdu import PDU

from tests.test_connections import free_udp
from tests.test_device_details import DetailsRouter, details_device
from tests.test_ip_discovery import RawIpPeer
from tests.test_routed_discovery import bvlc, iam


class RichIpPeer(RawIpPeer):
    def __init__(self, applications):
        super().__init__()
        self.applications = applications
        self.instances = list(applications)
        self.pending = {}
        self.last_device = {}
        self.metadata_requests = []
        self.maximum_pending = 0
        self.upstream = {("127.0.0.1", port) for port, _ in applications.values()}

    def _receive(self):
        try:
            peek, source = self.socket.recvfrom(65536, socket.MSG_PEEK)
            packet = peek[4:]
            if source in self.upstream:
                frame, _, _, _ = self.socket.recvmsg(65536, 128)
                assert frame[:2] == b"\x81\x0a" and packet[:2] == b"\x01\x00"
                apdu = packet[2:]
                assert apdu[0] & 0xF0 in (0x30, 0x50, 0x60, 0x70)
                destination = self.pending.pop((source, apdu[1]), None)
                if destination:
                    self.socket.sendto(frame, destination)
                return
            if len(packet) >= 6 and packet[:2] == b"\x01\x04":
                frame, _, _, _ = self.socket.recvmsg(65536, 128)
                assert frame[:2] == b"\x81\x0a"
                request = APCISequence.decode(APDU.decode(PDU(packet[2:])))
                assert isinstance(request, ReadPropertyRequest), (
                    "Only read-only metadata is allowed"
                )
                if int(request.objectIdentifier[0]) == 8:
                    instance = int(request.objectIdentifier[1])
                    self.last_device[source] = instance
                else:
                    instance = self.last_device[source]
                port, _ = self.applications[instance]
                upstream = ("127.0.0.1", port)
                self.pending[(upstream, request.apduInvokeID)] = source
                self.maximum_pending = max(self.maximum_pending, len(self.pending))
                self.metadata_requests.append(
                    (instance, str(request.objectIdentifier), str(request.propertyIdentifier))
                )
                self.socket.sendto(frame, upstream)
                return
            super()._receive()
        except BlockingIOError:
            return
        except Exception as error:
            self.errors.append(error)


class NamedRouter(DetailsRouter):
    def __init__(self, objects):
        super().__init__(objects)
        self.discovery_requests = 0

    def datagram_received(self, data, source):
        try:
            packet = data[4:]
            if len(packet) >= 8 and packet[:2] == b"\x01\x20":
                assert data[:2] == b"\x81\x0a"
                assert int.from_bytes(packet[2:4], "big") == 3001
                assert packet[4] == 0 and packet[5] == 255
                assert packet[6:8] == b"\x10\x08"
                self.discovery_requests += 1
                for mac in (b"\x07", b"\x09"):
                    self.transport.sendto(bvlc(iam(4190090, mac, 3001)), source)
                return
            super().datagram_received(data, source)
        except Exception as error:
            self.errors.append(error)


async def main():
    count = int(sys.argv[1])
    applications, ports = {}, set()
    for index in range(count):
        port = free_udp()
        while port in ports:
            port = free_udp()
        ports.add(port)
        instance = 4190090 + index
        app = details_device(port, instance=instance, programs=2)
        app.device_object.objectName = f"Named Controller {index + 1:02}"
        if index == 0:
            app.device_object.objectName = "=Named Controller 01"
        applications[instance] = (port, app)
        await asyncio.sleep(0.01)
    first = RichIpPeer(applications)
    second_port = free_udp()
    second_app = details_device(second_port, instance=4190090, programs=0, object_count=84)
    second_app.device_object.objectName = "Duplicate ID at another address"
    original_second_read = second_app.do_ReadPropertyRequest

    async def optional_description(request):
        if (
            str(request.propertyIdentifier) == "description"
            and int(request.objectIdentifier[0]) == 8
        ):
            raise ExecutionError(errorClass="property", errorCode="unknown-property")
        await original_second_read(request)

    second_app.do_ReadPropertyRequest = optional_description
    second = RichIpPeer({4190090: (second_port, second_app)})
    router_port = free_udp()
    router_app = details_device(router_port, instance=4190090, programs=1)
    router_app.device_object.objectName = "Routed named controller"
    router_transport, router = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: NamedRouter(router_app), local_addr=("127.0.0.1", 0)
    )
    await asyncio.sleep(0.1)
    print(
        json.dumps({"first": first.port, "second": second.port, "router": router.endpoint}),
        flush=True,
    )
    try:
        await asyncio.to_thread(sys.stdin.readline)
    finally:
        first.close()
        second.close()
        router.close()
        for _, app in applications.values():
            app.close()
        second_app.close()
        router_app.close()
        await asyncio.sleep(0.05)
        assert not first.errors and not second.errors and not router.errors, [
            str(error) for error in first.errors + second.errors + router.errors
        ]
        print(
            json.dumps(
                {
                    "first_discovery": len(first.frames),
                    "second_discovery": len(second.frames),
                    "first_metadata": len(first.metadata_requests),
                    "second_metadata": len(second.metadata_requests),
                    "maximum_pending": max(first.maximum_pending, second.maximum_pending),
                    "routed_discovery": router.discovery_requests,
                    "routed_metadata": len(router.requests),
                }
            ),
            flush=True,
        )


asyncio.run(main())
