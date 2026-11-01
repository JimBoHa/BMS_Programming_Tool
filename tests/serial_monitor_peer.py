"""Read-only serial monitoring peer with independent frame/CRC construction."""

from datetime import datetime

from bacpypes3.apdu import APDU, ReadRangeACK, ReadRangeRequest
from bacpypes3.basetypes import (
    DateTime,
    EngineeringUnits,
    LogRecord,
    LogRecordLogDatum,
    Reliability,
    StatusFlags,
)
from bacpypes3.constructeddata import Any, ListOf
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import Boolean, CharacterString, ObjectIdentifier, Real, Unsigned

from .mstp_survey_peer import SurveyWirePeer, wire


class MonitoringWirePeer(SurveyWirePeer):
    def __init__(self, fd):
        super().__init__(fd)
        self.objects = ["device,123", "analog-input,1", "trend-log,1"]
        self.value_now = -0.0
        self.object_identity = "analog-input,1"
        self.device_checks = 0
        self.fail_device_after = None
        self.ranges = []
        self.name_missing = False

    def value(self, obj, prop, index):
        obj, pid = str(obj), int(prop)
        if pid == 75:
            if obj == "device,123":
                self.device_checks += 1
                return ObjectIdentifier(
                    "device,99"
                    if self.fail_device_after and self.device_checks >= self.fail_device_after
                    else self.identity
                )
            return ObjectIdentifier(self.object_identity if obj == "analog-input,1" else obj)
        if obj == "device,123" and pid in (70, 77):
            return CharacterString(
                "Unlisted serial monitor" if pid == 70 else "Authored serial controller"
            )
        if obj == "device,123":
            return super().value(ObjectIdentifier(obj), prop, index)
        assert obj in ("analog-input,1", "trend-log,1")
        if pid == 77 and self.name_missing:
            return Unsigned(17)  # Wrong native type; the name must stay unavailable.
        values = {
            77: CharacterString(
                "Serial temperature" if obj.startswith("analog") else "Serial temperature history"
            ),
            85: Real(self.value_now),
            103: Reliability("no-fault-detected"),
            111: StatusFlags([0, 0, 0, 0]),
            81: Boolean(False),
            117: EngineeringUnits("degrees-celsius"),
        }
        assert pid in values, (obj, pid, index)
        return values[pid]

    def reply(self, npdu):
        assert npdu[:2] == b"\x01\x04"
        decoded = APDU.decode(PDU(npdu[2:]))
        # All mutations and unrelated services fail the independent peer.
        assert decoded.apduType == 0 and decoded.apduService in (12, 26)
        if decoded.apduService == 12:
            return super().reply(npdu)
        request = ReadRangeRequest.decode(decoded)
        assert (
            str(request.objectIdentifier) == "trend-log,1"
            and str(request.propertyIdentifier) == "log-buffer"
        )
        self.requests.append(type(request).__name__)
        self.ranges.append(request)
        self.received.set()
        if self.on_request:
            self.on_request(request)
        if self.drop:
            return
        selection = request.range
        if selection.byPosition is not None:
            start, count = (
                int(selection.byPosition.referenceIndex) - 1,
                int(selection.byPosition.count),
            )
        elif selection.bySequenceNumber is not None:
            start, count = (
                int(selection.bySequenceNumber.referenceSequenceNumber) - 100,
                int(selection.bySequenceNumber.count),
            )
        else:
            assert selection.byTime is not None
            start = int(selection.byTime.referenceTime.time[2])
            count = int(selection.byTime.count)
        start = max(0, start)
        chosen = [
            LogRecord(
                timestamp=DateTime(datetime(2026, 10, 31, 12, 0, i)),
                logDatum=LogRecordLogDatum(realValue=-0.0 if i == 0 else i + 0.25),
                statusFlags=[0, 0, 0, 0],
            )
            for i in range(start, min(3, start + count, start + 2))
        ]
        response = ReadRangeACK(
            context=request,
            objectIdentifier=request.objectIdentifier,
            propertyIdentifier="log-buffer",
            resultFlags=[
                int(start == 0),
                int(start + len(chosen) >= 3),
                int(start + len(chosen) < min(3, start + count)),
            ],
            itemCount=len(chosen),
            itemData=Any(ListOf(LogRecord)(chosen)),
            **({"firstSequenceNumber": 100 + start} if chosen else {}),
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
