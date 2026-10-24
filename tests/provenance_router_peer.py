"""Read-only loopback IP/router peer with acknowledged metadata-name changes."""

import asyncio
import json
import signal
import struct
import sys

from bacpypes3.apdu import APDU, APCISequence, Error, IAmRequest, ReadPropertyRequest, WhoIsRequest
from bacpypes3.pdu import PDU

from .test_device_instance import METADATA, OLD, read_reply


class ProvenanceRouter(asyncio.DatagramProtocol):
    def __init__(self):
        self.phase = "Old"
        self.requests = []
        self.errors = []
        self.writes = []

    def connection_made(self, transport):
        self.transport = transport
        host, port = transport.get_extra_info("sockname")
        self.endpoint = f"{host}:{port}"

    def send(self, payload, destination):
        self.transport.sendto(
            b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload, destination
        )

    def reply(self, reply, destination, routed):
        reply.apduSeg, reply.apduMor = False, False
        packet = reply.encode()
        if isinstance(packet, APDU):
            packet = packet.encode()
        prefix = (
            b"\x01\x00"
            if routed is None
            else b"\x01\x08" + struct.pack(">H", routed[0]) + b"\x01" + bytes([routed[1]])
        )
        self.send(prefix + bytes(packet.pduData), destination)

    def datagram_received(self, data, source):
        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            packet = data[4:]
            if packet == b"\x01\x80\x00":
                self.requests.append({"kind": "router-networks", "phase": self.phase})
                self.send(b"\x01\x80\x01" + struct.pack(">H", 3001), source)
                return
            assert packet[0] == 1
            routed = None
            if packet[1] & 0x20:
                network, length = int.from_bytes(packet[2:4], "big"), packet[4]
                assert network == 3001 and length in (0, 1) and packet[5 + length] == 255
                routed = (network, packet[5] if length else 7)
                assert routed[1] == 7
                offset = 6 + length
            else:
                assert packet[1] in (0, 4)
                offset = 2
            request = APCISequence.decode(APDU.decode(PDU(packet[offset:])))
            self.requests.append(
                {
                    "kind": type(request).__name__,
                    "phase": self.phase,
                    "routed": routed,
                    "source": list(source),
                }
            )
            if isinstance(request, WhoIsRequest):
                if (
                    request.deviceInstanceRangeLowLimit is None
                    or request.deviceInstanceRangeLowLimit
                    <= OLD
                    <= request.deviceInstanceRangeHighLimit
                ):
                    self.reply(
                        IAmRequest(
                            iAmDeviceIdentifier=("device", OLD),
                            maxAPDULengthAccepted=1476,
                            segmentationSupported="no-segmentation",
                            vendorID=5,
                        ),
                        source,
                        routed,
                    )
                return
            if not isinstance(request, ReadPropertyRequest):
                self.writes.append(type(request).__name__)
                raise AssertionError("Only Who-Is and ReadProperty are allowed")
            prop = str(request.propertyIdentifier)
            metadata = {
                **METADATA,
                "object-name": f"{self.phase} {'controller' if routed else 'router'} name",
            }
            self.requests[-1]["property"] = prop
            if prop in ("object-identifier", *METADATA):
                reply = read_reply(request, OLD, metadata)
            else:
                reply = Error(
                    service_choice=12,
                    errorClass="property",
                    errorCode="unknownProperty",
                    context=request,
                )
            self.reply(reply, source, routed)
        except Exception as exc:
            self.errors.append(f"{type(exc).__name__}: {exc}")
            print(json.dumps({"event": "error", "error": self.errors[-1]}), flush=True)


async def main():
    loop = asyncio.get_running_loop()
    _, peer = await loop.create_datagram_endpoint(ProvenanceRouter, local_addr=("127.0.0.1", 0))
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    print(json.dumps({"event": "ready", "endpoint": peer.endpoint}), flush=True)

    async def commands():
        reader = asyncio.StreamReader()
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        while not stop.is_set():
            line = await reader.readline()
            if not line:
                stop.set()
                return
            command = json.loads(line)
            if command["command"] == "phase":
                assert command["value"] in ("Old", "Current")
                peer.phase = command["value"]
                print(json.dumps({"event": "phase", "value": peer.phase}), flush=True)
            elif command["command"] == "stop":
                stop.set()
            else:
                raise ValueError("Unknown command")

    task = asyncio.create_task(commands())
    try:
        await stop.wait()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        peer.transport.close()
        await asyncio.sleep(0)
        print(
            json.dumps(
                {
                    "event": "stopped",
                    "requests": peer.requests,
                    "errors": peer.errors,
                    "writes": peer.writes,
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
