"""Native Device metadata for independent browser UDP peers that serve one station."""

from bacpypes3.apdu import APDU, APCISequence, ReadPropertyRequest
from bacpypes3.pdu import PDU

from .test_schedule_inventory import oid, text, unsigned


def device_property_reply(apdu, instance):
    if len(apdu) < 4 or apdu[0] >> 4 != 0 or apdu[3] != 12:
        return None
    request = APCISequence.decode(APDU.decode(PDU(apdu)))
    if not isinstance(request, ReadPropertyRequest) or request.objectIdentifier != (8, instance):
        return None
    prop = str(request.propertyIdentifier)
    index = request.propertyArrayIndex
    identifier = b"\xc4" + oid(8, instance)
    if prop == "object-list":
        value = unsigned(1) if index == 0 else identifier if index in (1, None) else None
    else:
        value = {
            "object-identifier": identifier,
            "object-name": text("Browser test station"),
            "description": text("Independent BACnet device"),
            "vendor-identifier": unsigned(999),
            "vendor-name": text("Test"),
            "model-name": text("Loopback"),
            "firmware-revision": text("1"),
            "application-software-version": text("1"),
            "protocol-revision": unsigned(18),
            "segmentation-supported": bytes.fromhex("9103"),
            "max-apdu-length-accepted": unsigned(480),
            "system-status": bytes.fromhex("9100"),
            "location": text("Test"),
        }.get(prop)
    if value is None:
        return bytes([0x50, request.apduInvokeID, 12]) + bytes.fromhex("91029120")
    reference = b"\x0c" + oid(8, instance) + unsigned(int(request.propertyIdentifier), 1)
    if index is not None:
        reference += unsigned(index, 2)
    return bytes([0x30, request.apduInvokeID, 12]) + reference + b"\x3e" + value + b"\x3f"
