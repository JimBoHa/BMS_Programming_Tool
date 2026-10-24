"""Authored UDP router with two trunks and duplicate-ID controllers for browser tests."""

import asyncio
import struct

from bacpypes3.apdu import (
    APDU,
    APCISequence,
    Error,
    IAmRequest,
    ReadPropertyRequest,
    SimpleAckPDU,
    WhoIsRequest,
    WritePropertyRequest,
)
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import ObjectIdentifier

from .test_device_instance import METADATA, NEW, OLD, read_reply


class GuidedRouter(asyncio.DatagramProtocol):
    def __init__(self, network=3001, *, stations=(7, 8), names=None):
        self.networks = [network, network + 1]
        self.instances = {(dnet, mac): OLD for dnet in self.networks for mac in stations}
        self.names = names or {}
        self.errors, self.writes = [], []

    def connection_made(self, transport):
        self.transport = transport
        host, port = transport.get_extra_info("sockname")
        self.endpoint = f"{host}:{port}"

    def send(self, payload, destination):
        self.transport.sendto(
            b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload, destination
        )

    def reply(self, reply, destination, dnet, mac):
        reply.apduSeg, reply.apduMor = False, False
        packet = reply.encode()
        if isinstance(packet, APDU):
            packet = packet.encode()
        self.send(
            b"\x01\x08" + struct.pack(">H", dnet) + b"\x01" + bytes([mac]) + bytes(packet.pduData),
            destination,
        )

    def datagram_received(self, data, source):
        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            packet = data[4:]
            if packet == b"\x01\x80\x00":
                self.send(
                    b"\x01\x80\x01"
                    + b"".join(struct.pack(">H", network) for network in self.networks),
                    source,
                )
                return
            assert packet[0] == 1 and packet[1] in (0x20, 0x24)
            dnet, length = int.from_bytes(packet[2:4], "big"), packet[4]
            assert dnet in self.networks and length in (0, 1) and packet[5 + length] == 255
            request = APCISequence.decode(APDU.decode(PDU(packet[6 + length :])))
            if isinstance(request, WhoIsRequest):
                assert length == 0
                for (network, mac), instance in self.instances.items():
                    if (
                        network == dnet
                        and request.deviceInstanceRangeLowLimit
                        <= instance
                        <= request.deviceInstanceRangeHighLimit
                    ):
                        self.reply(
                            IAmRequest(
                                iAmDeviceIdentifier=("device", instance),
                                maxAPDULengthAccepted=1476,
                                segmentationSupported="no-segmentation",
                                vendorID=5,
                            ),
                            source,
                            dnet,
                            mac,
                        )
                return
            mac = packet[5]
            assert (dnet, mac) in self.instances
            if isinstance(request, ReadPropertyRequest):
                metadata = {
                    **METADATA,
                    "object-name": self.names.get((dnet, mac), f"Authored {dnet} MAC {mac}"),
                }
                if str(request.propertyIdentifier) in ("object-identifier", *METADATA):
                    reply = read_reply(request, self.instances[dnet, mac], metadata)
                else:
                    reply = Error(
                        service_choice=12,
                        errorClass="property",
                        errorCode="unknownProperty",
                        context=request,
                    )
            else:
                assert isinstance(request, WritePropertyRequest)
                assert str(request.objectIdentifier) == f"device,{self.instances[dnet, mac]}"
                assert str(request.propertyIdentifier) == "object-identifier"
                assert request.priority is None and request.propertyArrayIndex is None
                assert request.propertyValue.cast_out(ObjectIdentifier) == ObjectIdentifier(
                    ("device", NEW)
                )
                self.instances[dnet, mac] = NEW
                self.writes.append((dnet, mac))
                print(f"WRITE {dnet}:{mac}", flush=True)
                reply = SimpleAckPDU(context=request)
            self.reply(reply, source, dnet, mac)
        except Exception as exc:
            self.errors.append(exc)
            print("PEER ERROR " + str(exc), flush=True)

    def close(self):
        self.transport.close()
