"""Authored read-only BACnet peer over a real kernel TTY.

This peer uses upstream BACpypes service codecs, independently built legacy
MS/TP frame/CRC functions, and authored values. No Studio read service, serial
implementation, frame codec or hardware report generator supplies its replies.
"""

import os
import select
import threading
import time

from bacpypes3.apdu import (
    APDU,
    AtomicReadFileACK,
    AtomicReadFileRequest,
    ReadPropertyACK,
    ReadPropertyMultipleACK,
    ReadPropertyMultipleRequest,
    ReadPropertyRequest,
    RejectPDU,
)
from bacpypes3.basetypes import (
    AtomicReadFileACKAccessMethodChoice,
    AtomicReadFileACKAccessMethodStreamAccess,
    BinaryPV,
    DateTime,
    EngineeringUnits,
    FileAccessMethod,
    ReadAccessResult,
    ReadAccessResultElement,
    ReadAccessResultElementChoice,
    Reliability,
    StatusFlags,
)
from bacpypes3.constructeddata import Any
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    Null,
    ObjectIdentifier,
    Real,
    Unsigned,
)

from tests.test_hardware_survey import authored_archive, native_record


def crc(data, width, polynomial):
    mask = (1 << width) - 1
    value = mask
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (polynomial if value & 1 else 0)
    return value ^ mask


def wire(kind, destination, source, payload=b""):
    header = bytes((kind, destination, source)) + len(payload).to_bytes(2, "big")
    result = b"\x55\xff" + header + bytes([crc(header, 8, 0x81)])
    return result + payload + crc(payload, 16, 0x8408).to_bytes(2, "little") if payload else result


assert wire(1, 1, 0) == bytes.fromhex("55ff0101000000f5")
assert crc(bytes.fromhex("012230"), 16, 0x8408) == 0xBD10


class SurveyWirePeer:
    def __init__(self, fd):
        self.fd = fd
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.errors = []
        self.requests = []
        self.atomic_offsets = []
        self.reply_source = 1
        self.identity = "device,123"
        self.reject_rpm = False
        self.drop = False
        self.on_request = None
        self.received = threading.Event()
        self.payload = authored_archive() + native_record(
            999, 1, [(2390, CharacterString("Authored opaque application data " * 25))]
        )
        self.objects = ["device,123", "analog-input,56", "binary-input,55", "file,31"]

    def read(self, count):
        result = b""
        while len(result) < count and not self.stop.is_set():
            if select.select([self.fd], [], [], 0.01)[0]:
                result += os.read(self.fd, count - len(result))
        return result if len(result) == count else None

    def send(self, payload):
        for chunk in (payload[:3], payload[3:9], payload[9:]):
            if chunk and not self.stop.is_set():
                os.write(self.fd, chunk)
                time.sleep(0.002)

    def value(self, obj, prop, index):
        pid = int(prop)
        if str(obj) == "device,123":
            if pid == 76:
                assert index is not None
                return (
                    Unsigned(len(self.objects))
                    if index == 0
                    else ObjectIdentifier(self.objects[index - 1])
                )
            values = {
                75: ObjectIdentifier(self.identity),
                77: CharacterString("Authored controller"),
                28: CharacterString("Kernel TTY fixture"),
                70: CharacterString("FX-PCG2611-0"),
                120: Unsigned(5),
                44: CharacterString("test-1.0"),
                12: CharacterString("test application"),
                62: Unsigned(480),
            }
        elif str(obj) == "file,31":
            values = {
                77: CharacterString("Authored controller/Archive"),
                43: CharacterString(".moi"),
                42: Unsigned(len(self.payload)),
                41: FileAccessMethod("stream-access"),
                99: Boolean(True),
                71: DateTime("2026-01-05 12:00:00"),
            }
        else:
            analog = str(obj) == "analog-input,56"
            assert analog or str(obj) == "binary-input,55"
            values = {
                77: CharacterString("Fixture temperature" if analog else "Alarm"),
                28: CharacterString("Authored serial input"),
                31: CharacterString("UI IN1" if analog else "UI IN4"),
                85: Real(-12.5) if analog else BinaryPV("active"),
                103: Reliability("no-fault-detected"),
                111: StatusFlags([False, False, False, False]),
                81: Boolean(False),
                117: EngineeringUnits("degrees-fahrenheit"),
                519: Unsigned(1 if analog else 4),
                3645: Null(()) if analog else Unsigned(4),
                518: Enumerated(2) if analog else Unsigned(2),
            }
        assert pid in values, (str(obj), pid, index)
        return values[pid]

    def reply(self, npdu):
        assert npdu[:2] == b"\x01\x04", "Only local confirmed unicast read requests are allowed."
        decoded = APDU.decode(PDU(npdu[2:]))
        assert decoded.apduType == 0 and decoded.apduService in (6, 12, 14)
        request = ReadPropertyRequest.decode(decoded)
        self.requests.append(type(request).__name__)
        self.received.set()
        if self.on_request:
            self.on_request(request)
        if self.drop:
            return
        if isinstance(request, ReadPropertyMultipleRequest):
            if self.reject_rpm:
                response = RejectPDU(invoke_id=request.apduInvokeID, reason=9)
            else:
                results = []
                for access in request.listOfReadAccessSpecs:
                    entries = []
                    for ref in access.listOfPropertyReferences:
                        entry = ReadAccessResultElement(
                            propertyIdentifier=ref.propertyIdentifier,
                            readResult=ReadAccessResultElementChoice(
                                propertyValue=Any(
                                    self.value(
                                        access.objectIdentifier,
                                        ref.propertyIdentifier,
                                        ref.propertyArrayIndex,
                                    )
                                )
                            ),
                        )
                        if ref.propertyArrayIndex is not None:
                            entry.propertyArrayIndex = ref.propertyArrayIndex
                        entries.append(entry)
                    results.append(
                        ReadAccessResult(
                            objectIdentifier=access.objectIdentifier, listOfResults=entries
                        )
                    )
                response = ReadPropertyMultipleACK(context=request, listOfReadAccessResults=results)
        elif isinstance(request, ReadPropertyRequest):
            response = ReadPropertyACK(
                context=request,
                objectIdentifier=request.objectIdentifier,
                propertyIdentifier=request.propertyIdentifier,
                propertyValue=Any(
                    self.value(
                        request.objectIdentifier,
                        request.propertyIdentifier,
                        request.propertyArrayIndex,
                    )
                ),
            )
            if request.propertyArrayIndex is not None:
                response.propertyArrayIndex = request.propertyArrayIndex
        else:
            assert (
                isinstance(request, AtomicReadFileRequest)
                and str(request.fileIdentifier) == "file,31"
            )
            selection = request.accessMethod.streamAccess
            assert selection is not None and request.accessMethod.recordAccess is None
            start, count = int(selection.fileStartPosition), int(selection.requestedOctetCount)
            assert 0 <= start < len(self.payload) and 1 <= count <= 448
            self.atomic_offsets.append((start, count))
            block = self.payload[start : start + count]
            response = AtomicReadFileACK(
                context=request,
                endOfFile=start + len(block) == len(self.payload),
                accessMethod=AtomicReadFileACKAccessMethodChoice(
                    streamAccess=AtomicReadFileACKAccessMethodStreamAccess(
                        fileStartPosition=start, fileData=block
                    )
                ),
            )
        response.apduSeg = False
        response.apduMor = False
        encoded = response.encode()
        data = (
            bytes(encoded.encode().pduData)
            if not isinstance(encoded, PDU)
            else bytes(encoded.pduData)
        )
        self.send(wire(6, 0, self.reply_source, b"\x01\x00" + data))

    def run(self):
        try:
            while not self.stop.is_set():
                header = self.read(8)
                if header is None:
                    return
                assert header[:2] == b"\x55\xff" and crc(header[2:7], 8, 0x81) == header[7]
                count = int.from_bytes(header[5:7], "big")
                assert count <= 501
                tail = self.read(count + 2) if count else b""
                if tail is None:
                    return
                assert not count or crc(tail[:-2], 16, 0x8408) == int.from_bytes(
                    tail[-2:], "little"
                )
                kind, destination, source = header[2:5]
                assert source == 0 and destination == 1
                time.sleep((len(header) + len(tail)) * 10 / 38400 + 0.002)
                if kind == 1:
                    self.send(wire(2, 0, 1))
                elif kind == 0:
                    self.send(wire(0, 0, 1))
                else:
                    assert kind == 5
                    self.reply(tail[:-2])
        except Exception as exc:
            if not self.stop.is_set():
                self.errors.append(exc)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        assert not self.thread.is_alive()
        assert not self.errors, self.errors
