"""MCE command envelopes over the app's own BACnet connection.

Vendor 5/private service 54 carries a target ObjectIdentifier, command number,
typed argument group and request flags. No process launch or vendor SDK is used.
Command semantics belong to the application-transfer adapter, not this envelope.
"""

from bacpypes3.apdu import (
    ConfirmedPrivateTransferACK,
    ConfirmedPrivateTransferRequest,
)
from bacpypes3.constructeddata import Any
from bacpypes3.errors import InvalidTag
from bacpypes3.primitivedata import (
    ClosingTag,
    ContextTag,
    ObjectIdentifier,
    OpeningTag,
    TagClass,
    TagList,
    Unsigned,
)

from .application_files import ApplicationFiles
from .device_details import DeviceDetails, DeviceDetailsRequest
from .property_evidence import PropertyEvidence

VENDOR = 5
SERVICE = 54
CONTROLLER_INFO = 678
DEVICE_SELECTOR = ObjectIdentifier((8, 4194303))


def _integer(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("Native command integer is outside its encoding profile.")
    return value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")


def command_request(command, arguments, *, selector=DEVICE_SELECTOR):
    selector = ObjectIdentifier(selector)
    identifier = ((int(selector[0]) << 22) | selector[1]).to_bytes(4, "big")
    tags = [
        ContextTag(0, identifier),
        ContextTag(1, _integer(command, 65535)),
        OpeningTag(2),
    ]
    for value in arguments:
        tags.extend(value.encode())
    tags.extend([ClosingTag(2), ContextTag(5, b"\x00")])
    return ConfirmedPrivateTransferRequest(
        vendorID=VENDOR, serviceNumber=SERVICE, serviceParameters=Any(TagList(tags))
    )


def command_result(reply, command, *, selector=DEVICE_SELECTOR):
    if not isinstance(reply, ConfirmedPrivateTransferACK) or (
        int(reply.vendorID) != VENDOR or int(reply.serviceNumber) != SERVICE
    ):
        raise ValueError("Native reply is not a matching command acknowledgement.")
    if reply.resultBlock is None or reply.resultBlock.tagList is None:
        raise ValueError("Native reply omitted its command result group.")
    tags = list(reply.resultBlock.tagList)
    if len(tags) < 6:
        raise ValueError("Truncated native command reply.")

    def opening(t):
        return t.tag_class == TagClass.opening and t.tag_number == 2

    def closing(t):
        return t.tag_class == TagClass.closing and t.tag_number == 2

    if not opening(tags[0]) or not opening(tags[3]) or not all(closing(t) for t in tags[-2:]):
        raise ValueError("Native command reply group framing is inconsistent.")
    oid, code = tags[1], tags[2]
    expected = ObjectIdentifier(selector)
    expected = ((int(expected[0]) << 22) | expected[1]).to_bytes(4, "big")
    if (
        oid.tag_class != TagClass.context
        or oid.tag_number != 0
        or bytes(oid.tag_data) != expected
        or code.tag_class != TagClass.context
        or code.tag_number != 1
        or bytes(code.tag_data) != _integer(command, 65535)
    ):
        raise ValueError("Native reply target or command does not match its request.")
    stack = []
    for tag in tags[4:-2]:
        if tag.tag_class == TagClass.opening:
            stack.append(tag.tag_number)
        elif tag.tag_class == TagClass.closing:
            if not stack or stack.pop() != tag.tag_number:
                raise ValueError("Native reply has mismatched argument groups.")
        if len(stack) > 8:
            raise ValueError("Native reply has excessive nested argument groups.")
    if stack or len(tags) > 2048:
        raise ValueError("Native reply has excessive or unterminated arguments.")
    return TagList(tags[4:-2])


class MceWire:
    def __init__(self, path):
        self.path = path
        self.transport = ApplicationFiles(path, writable_files={3})

    async def exchange(self, session, command, arguments, *, before_send=None, timeout=4):
        request = command_request(command, arguments)
        reply = await self.transport.exchange(
            session, request, ConfirmedPrivateTransferACK, before_send=before_send
        )
        return command_result(reply, command)


async def controller_info(wire, session, device):
    from bacpypes3.primitivedata import CharacterString

    tags = await wire.exchange(session, CONTROLLER_INFO, [Unsigned(1)])
    if not 21 <= len(tags) <= 32 or any(t.tag_class != TagClass.application for t in tags):
        raise ValueError("Unsupported native controller-information response version.")
    try:
        if ObjectIdentifier.decode(TagList([tags[10]])) != ObjectIdentifier(device):
            raise ValueError(
                "Native controller information disagrees with the selected Device identity."
            )
        text = {}
        for name, index in [("name", 0), ("description", 1), ("application_name", 6)]:
            value = str(CharacterString.decode(TagList([tags[index]])))
            if len(value.encode()) > 512 or (name == "name" and not value):
                raise ValueError("Native controller information contains invalid text.")
            text[name] = value
        return {**text, "device": str(ObjectIdentifier(device)), "vendor_runtime_required": False}
    except (InvalidTag, TypeError, AttributeError, IndexError) as exc:
        raise ValueError("Unsupported native controller-information datatypes.") from exc


class MceController:
    def __init__(self, bacnet, store):
        self.path = DeviceDetails(bacnet, store)
        self.wire = MceWire(self.path)

    async def info(self, request):
        options = DeviceDetailsRequest.model_validate(request)
        async with self.path._path(options) as session:
            identity = await self.path._read(session, options.device, "object-identifier")
            vendor = await self.path._read(session, options.device, "vendor-identifier")
            if identity != ObjectIdentifier(options.device) or int(vendor) != VENDOR:
                raise ValueError("The selected station does not match this native protocol family.")
            PropertyEvidence.pin(session, options.router)
            actual = await controller_info(self.wire, session, options.device)
            return {
                **actual,
                "profile": "mce-connected-controller/1",
                "target": options.model_dump(),
                "identity_verified": True,
                "read_only": True,
            }
