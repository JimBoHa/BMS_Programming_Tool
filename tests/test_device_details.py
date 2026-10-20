"""Actual loopback Device/Program metadata; no physical controllers or HTTP mocks."""

import asyncio
import copy
import hashlib
import json
import struct

import pytest
from bacpypes3.apdu import APDU, APCISequence, ReadPropertyACK, ReadPropertyRequest
from bacpypes3.app import Application
from bacpypes3.constructeddata import Any
from bacpypes3.errors import PropertyError
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.object import ProgramObject
from bacpypes3.pdu import PDU, Address
from bacpypes3.primitivedata import CharacterString, Null, ObjectIdentifier, Unsigned
from bms_tool.bacnet_read import close_application
from bms_tool.connections import Bacnet
from bms_tool.device_details import DeviceDetails, DeviceDetailsRequest
from bms_tool.storage import Store

from .test_connections import free_udp, point


def details_device(port, *, instance=4190090, programs=2, object_count=None, max_apdu=480):
    """Public authored UDP peer for backend/browser integration tests."""
    app = Application.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", instance),
                objectName="Independent Device Details",
                description="Device description is not a program name",
                vendorIdentifier=5,
                vendorName="Independent vendor",
                modelName="VMA1630 details fixture",
                firmwareRevision="7.0",
                applicationSoftwareVersion="version-only-1.2",
                protocolRevision=22,
                segmentationSupported="no-segmentation",
                maxApduLengthAccepted=max_apdu,
                systemStatus="operational",
                location="Test room",
            ),
            NetworkPortObject(
                f"127.0.0.1:{port}",
                objectIdentifier=("network-port", 1),
                objectName="Details IP port",
            ),
        ]
    )
    for number in range(1, programs + 1):
        app.add_object(
            ProgramObject(
                objectIdentifier=("program", number),
                objectName=f"Actual Program {number}",
                description=f"Exposed Program {number} description",
                programState="running",
                programChange="ready",
                statusFlags=[0, 0, 0, 0],
                outOfService=False,
            )
        )
    number = 1
    while object_count is not None and len(app.objectIdentifier) < object_count:
        obj = point()
        obj.objectIdentifier = ("analog-value", number)
        obj.objectName = f"Unrelated point {number}"
        app.add_object(obj)
        number += 1
    return app


class DetailsRouter(asyncio.DatagramProtocol):
    """Actual UDP router with independently checked literal NPDU framing."""

    def __init__(self, objects):
        self.objects = objects
        self.requests = []
        self.errors = []
        self.hold_property = None
        self.hold_mac = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release_point = asyncio.Event()
        self.rogue = None
        self.wrong_identity = False
        self.tasks = set()

    def connection_made(self, transport):
        self.transport = transport
        host, port = transport.get_extra_info("sockname")
        self.endpoint = f"{host}:{port}"

    def datagram_received(self, data, source):
        task = asyncio.create_task(self.reply(data, source))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def reply(self, data, source):
        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            packet = data[4:]
            assert packet[:2] == b"\x01\x24"  # one routed confirmed unicast, expecting reply
            dnet, mac_length = int.from_bytes(packet[2:4], "big"), packet[4]
            mac = packet[5 : 5 + mac_length]
            assert dnet == 3001 and mac in (b"\x07", b"\x09")
            assert packet[5 + mac_length] == 255
            request = APCISequence.decode(APDU.decode(PDU(packet[6 + mac_length :])))
            assert isinstance(request, ReadPropertyRequest), "Only ReadProperty is admitted."
            prop = str(request.propertyIdentifier)
            self.requests.append(
                (mac, str(request.objectIdentifier), prop, request.propertyArrayIndex)
            )
            if prop == self.hold_property and (self.hold_mac is None or mac == self.hold_mac):
                self.entered.set()
                await (self.release_point if mac == b"\x09" else self.release).wait()
            obj = self.objects.get_object_id(request.objectIdentifier)
            assert obj is not None
            value = await obj.read_property(request.propertyIdentifier, request.propertyArrayIndex)
            reply = ReadPropertyACK(
                objectIdentifier=ObjectIdentifier(("device", 4190091))
                if self.wrong_identity
                else request.objectIdentifier,
                propertyIdentifier=request.propertyIdentifier,
                propertyArrayIndex=request.propertyArrayIndex,
                propertyValue=Any(value),
            )
            reply.apduInvokeID = request.apduInvokeID
            reply.apduService = 12
            reply.apduSeg = reply.apduMor = False
            npdu = b"\x01\x08" + struct.pack(">H", dnet) + bytes([len(mac)]) + mac
            payload = npdu + bytes(reply.encode().encode().pduData)
            frame = b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload
            if self.rogue:
                self.rogue.sendto(frame, source)
                await asyncio.sleep(0.005)
            self.transport.sendto(frame, source)
        except Exception as exc:
            self.errors.append(exc)

    def close(self):
        self.release.set()
        self.release_point.set()
        for task in list(self.tasks):
            task.cancel()
        self.transport.close()


@pytest.fixture
async def details_link(tmp_path):
    port = free_udp()
    server = details_device(port)
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = DeviceDetails(client, client.store, timeout=0.1, operation_timeout=2, request_gap=0)
    try:
        yield server, client, service, f"127.0.0.1:{port}"
    finally:
        client.close()
        close_application(server)
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_real_device_and_actual_program_names_with_inventory_hash(details_link):
    server, client, service, address = details_link
    requests = []
    original = server.do_ReadPropertyRequest

    async def tracked(request):
        requests.append(
            (
                str(request.objectIdentifier),
                str(request.propertyIdentifier),
                request.propertyArrayIndex,
            )
        )
        await original(request)

    server.do_ReadPropertyRequest = tracked
    before = copy.deepcopy(client.config)
    result = await service.read(address=address, device="device,4190090")
    assert result["identity_verified"] and result["complete"]
    assert result["properties"]["object-name"] == "Independent Device Details"
    assert result["properties"]["application-software-version"] == "version-only-1.2"
    assert result["program_names"] == ["Actual Program 1", "Actual Program 2"]
    assert result["programs_status"] == "exposed" and result["programs_total"] == 2
    assert result["programs"][0]["object"] == "program,1"
    assert result["programs"][0]["state"] == 2  # Standard ProgramState.running.
    assert all(row["status"] == "ok" for row in result["property_status"].values())
    identifiers = [str(obj) for obj in server.device_object.objectList]
    assert result["object_list"] == {
        "total": 4,
        "read_count": 4,
        "complete": True,
        "method": "whole_array",
        "sha256": hashlib.sha256(
            json.dumps(identifiers, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    assert len([item for item in requests if item[1] == "object-list"]) == 3
    assert client.config == before and not client.commands
    assert not client.app._requests and not client.app.asap.clientTransactions


@pytest.mark.asyncio
async def test_84_objects_without_programs_explicitly_not_exposed(tmp_path):
    port = free_udp()
    server = details_device(port, programs=0, object_count=84)
    client = Bacnet(Store(tmp_path))
    requests = []
    original = server.do_ReadPropertyRequest

    async def tracked(request):
        requests.append((str(request.propertyIdentifier), request.propertyArrayIndex))
        await original(request)

    server.do_ReadPropertyRequest = tracked
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        result = await DeviceDetails(client, client.store, request_gap=0).read(
            address=f"127.0.0.1:{port}", device="device,4190090"
        )
        assert result["complete"] and result["programs_status"] == "not_exposed"
        assert result["programs"] == result["program_names"] == []
        assert result["programs_total"] == 0
        assert result["object_list"]["read_count"] == 84
        assert result["object_list"]["method"] == "whole_array"
        assert len([item for item in requests if item[0] == "object-list"]) == 3
    finally:
        client.close()
        close_application(server)
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_metadata_failure_keeps_identity_and_real_program_names(details_link):
    server, client, service, address = details_link
    original = server.do_ReadPropertyRequest

    async def optional_failure(request):
        if str(request.propertyIdentifier) == "location":
            await asyncio.sleep(1)
            return
        await original(request)

    server.do_ReadPropertyRequest = optional_failure
    result = await service.read(address=address, device="device,4190090")
    assert result["identity_verified"] and not result["complete"]
    assert result["property_status"]["location"]["status"] == "error"
    assert result["properties"]["location"] is None
    assert result["program_names"] == ["Actual Program 1", "Actual Program 2"]
    assert result["programs_status"] == "exposed"


@pytest.mark.asyncio
@pytest.mark.parametrize("alter", ["ack_object", "identifier_value"])
async def test_identity_cannot_be_overwritten_by_incorrect_ack(details_link, alter):
    server, client, service, address = details_link

    async def wrong(request):
        reply = ReadPropertyACK(
            objectIdentifier=ObjectIdentifier(("device", 4190091))
            if alter == "ack_object"
            else request.objectIdentifier,
            propertyIdentifier=request.propertyIdentifier,
            propertyValue=Any(ObjectIdentifier(("device", 4190091))),
            context=request,
        )
        await server.response(reply)

    server.do_ReadPropertyRequest = wrong
    result = await service.read(address=address, device="device,4190090")
    assert not result["identity_verified"] and not result["complete"]
    assert result["device"] == "device,4190090"
    assert result["properties"]["object-name"] is None
    assert result["programs_status"] == "not_read"
    assert result["errors"]


@pytest.mark.parametrize(
    "change",
    [
        {"address": "localhost"},
        {"address": "127.0.0.1/24"},
        {"address": "255.255.255.255"},
        {"address": "*"},
        {"address": "2001:7"},
        {"device": "device,4194303"},
        {"device": "analog-value,1"},
        {"router": "127.0.0.1"},
        {"address": "2001:7", "router": "127.0.0.1", "dnet": 2002},
        {"address": "2001:*", "router": "127.0.0.1", "dnet": 2001},
    ],
)
def test_invalid_targets_refused_without_discovery(change):
    with pytest.raises(ValueError):
        DeviceDetailsRequest(**({"address": "127.0.0.1", "device": "device,7"} | change))


@pytest.fixture
async def routed_details(tmp_path):
    objects = details_device(free_udp())
    objects.add_object(point())
    loop = asyncio.get_running_loop()
    transport, router = await loop.create_datagram_endpoint(
        lambda: DetailsRouter(objects), local_addr=("127.0.0.1", 0)
    )
    rogue, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = DeviceDetails(client, client.store, timeout=0.2, operation_timeout=3, request_gap=0)
    try:
        yield objects, client, service, router, rogue
    finally:
        client.close()
        router.close()
        rogue.close()
        close_application(objects)
        await asyncio.sleep(0.02)
        assert not router.errors


@pytest.mark.asyncio
async def test_routed_details_before_route_selection_pin_source_and_keep_real_owned_command(
    routed_details,
):
    objects, client, service, router, rogue = routed_details
    # Use the actual native object's advertised IP bind to own a separate local
    # point command; the details operation must leave that command/config alone.
    port = next(
        obj for obj in objects.objectIdentifier.values() if int(obj.objectIdentifier[0]) == 56
    )
    owned_address = f"127.0.0.1:{int.from_bytes(port.macAddress[-2:], 'big')}"
    plan = await client.plan_write(owned_address, "analog-value,1", 42.25)
    command = await client.apply_write(plan["token"])
    saved_config, saved_commands = copy.deepcopy(client.config), copy.deepcopy(client.commands)
    saved_journal = client.journal.read_bytes()
    router.rogue = rogue
    await client.app.nsap.update_router_references(
        None, Address(rogue.get_extra_info("sockname")), [3001]
    )
    result = await service.read(
        address="3001:7", device="device,4190090", router=router.endpoint, dnet=3001
    )
    assert result["identity_verified"] and result["complete"]
    assert result["program_names"] == ["Actual Program 1", "Actual Program 2"]
    assert result["ignored_router_packets"] > 0
    assert result["connector_config"] == saved_config and saved_config["dnet"] is None
    assert client.config == saved_config and client.commands == saved_commands
    assert client.journal.read_bytes() == saved_journal
    assert (
        "process_npdu" not in client.app.nsap.__dict__
        and "indication" not in client.app.nsap.__dict__
    )
    assert (await client.release(command["command"]))["present_value"] == 12.5


@pytest.mark.asyncio
async def test_wrong_routed_ack_cannot_replace_selected_identity(routed_details):
    _, client, service, router, _ = routed_details
    router.wrong_identity = True
    result = await service.read(
        address="3001:7", device="device,4190090", router=router.endpoint, dnet=3001
    )
    assert not result["identity_verified"] and result["device"] == "device,4190090"
    assert result["programs_status"] == "not_read"
    assert not client.app._requests and not client.app.asap.clientTransactions
    assert not client.lock.locked() and "process_npdu" not in client.app.nsap.__dict__


@pytest.mark.asyncio
async def test_routed_details_preserve_unrelated_inflight_normal_read_and_cancel_cleanup(
    routed_details,
):
    _, client, service, router, _ = routed_details
    await client.connect(**(client.config | {"router": router.endpoint, "dnet": 3001}))
    router.hold_property, router.hold_mac = "present-value", b"\x09"
    normal = asyncio.create_task(client.read("3001:9", "analog-value,1"))
    await asyncio.wait_for(router.entered.wait(), 2)
    router.entered.clear()
    router.hold_property, router.hold_mac = "model-name", b"\x07"
    details = asyncio.create_task(
        service.read(address="3001:7", device="device,4190090", router=router.endpoint, dnet=3001)
    )
    try:
        await asyncio.wait_for(router.entered.wait(), 2)
        assert client.lock.locked() and "process_npdu" in client.app.nsap.__dict__
        router.release_point.set()
        assert (await asyncio.wait_for(normal, 2))["value"] == 12.5
        details.cancel()
        with pytest.raises(asyncio.CancelledError):
            await details
        assert (
            not client.lock.locked()
            and not client.app._requests
            and not client.app.asap.clientTransactions
        )
        assert (
            "process_npdu" not in client.app.nsap.__dict__
            and "indication" not in client.app.nsap.__dict__
        )
    finally:
        router.release.set()
        router.release_point.set()
        for task in (normal, details):
            if not task.done():
                task.cancel()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_inventory", ["oversize", "changed"])
async def test_unverified_inventory_never_becomes_programs_not_exposed(details_link, bad_inventory):
    server, _, service, address = details_link
    original = server.do_ReadPropertyRequest
    counts = 0

    async def changed(request):
        nonlocal counts
        if str(request.propertyIdentifier) == "object-list" and request.propertyArrayIndex == 0:
            counts += 1
            value = (
                513 if bad_inventory == "oversize" else len(server.objectIdentifier) + (counts > 1)
            )
            await server.response(
                ReadPropertyACK(
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=request.propertyIdentifier,
                    propertyArrayIndex=0,
                    propertyValue=Any(Unsigned(value)),
                    context=request,
                )
            )
            return
        await original(request)

    server.do_ReadPropertyRequest = changed
    result = await service.read(address=address, device="device,4190090")
    assert result["identity_verified"] and not result["complete"]
    assert result["programs_status"] == (
        "limit_exceeded" if bad_inventory == "oversize" else "unavailable"
    )
    assert result["program_names"] == [] and not result["object_list"]["complete"]


@pytest.mark.asyncio
async def test_large_apdu_unsafe_array_uses_only_bounded_indexed_reads(tmp_path):
    port = free_udp()
    server = details_device(port, programs=0, object_count=90)
    original = server.do_ReadPropertyRequest
    indices = []

    async def tracked(request):
        if str(request.propertyIdentifier) == "object-list":
            indices.append(request.propertyArrayIndex)
        await original(request)

    server.do_ReadPropertyRequest = tracked
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        result = await DeviceDetails(client, client.store, request_gap=0).read(
            address=f"127.0.0.1:{port}", device="device,4190090"
        )
        assert result["complete"] and result["programs_status"] == "not_exposed"
        assert result["object_list"]["method"] == "indexed"
        assert indices == [0, *range(1, 91), 0] and None not in indices
    finally:
        client.close()
        close_application(server)
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_whole_deadline_retains_fields_and_cannot_claim_no_programs(details_link):
    server, client, service, address = details_link
    service.operation_timeout = 0.15
    original = server.do_ReadPropertyRequest

    async def hold(request):
        if str(request.propertyIdentifier) in ("model-name", "firmware-revision"):
            await asyncio.sleep(1)
            return
        await original(request)

    server.do_ReadPropertyRequest = hold
    result = await service.read(address=address, device="device,4190090")
    assert (
        result["identity_verified"]
        and result["properties"]["object-name"] == "Independent Device Details"
    )
    assert not result["complete"] and result["programs_status"] == "partial"
    assert not result["object_list"]["complete"]
    assert (
        not client.lock.locked()
        and not client.app._requests
        and not client.app.asap.clientTransactions
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_text", ["oversize", "null"])
async def test_invalid_metadata_scalar_is_explicit_error_not_fabricated_name(
    details_link, bad_text
):
    server, _, service, address = details_link
    original = server.do_ReadPropertyRequest
    server.device_object.segmentationSupported = "segmented-both"

    async def changed(request):
        if str(request.propertyIdentifier) == "description":
            await server.response(
                ReadPropertyACK(
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=request.propertyIdentifier,
                    propertyValue=Any(
                        CharacterString("x" * 4097) if bad_text == "oversize" else Null(())
                    ),
                    context=request,
                )
            )
            return
        await original(request)

    server.do_ReadPropertyRequest = changed
    result = await service.read(address=address, device="device,4190090")
    assert result["identity_verified"] and not result["complete"]
    assert result["properties"]["description"] is None
    assert result["property_status"]["description"]["status"] == "error"
    assert ("4096-byte" if bad_text == "oversize" else "NULL") in result["property_status"][
        "description"
    ]["error"]
    assert result["program_names"] == ["Actual Program 1", "Actual Program 2"]


@pytest.mark.asyncio
async def test_unknown_optional_property_remains_unsupported_and_audit_failure_visible(
    details_link, monkeypatch
):
    server, _, service, address = details_link
    original = server.do_ReadPropertyRequest

    async def unavailable(request):
        if str(request.propertyIdentifier) == "location":
            raise PropertyError(errorCode="unknownProperty")
        await original(request)

    server.do_ReadPropertyRequest = unavailable

    def fail_audit(*args):
        raise OSError("Test-owned audit failure")

    monkeypatch.setattr(service.store, "record", fail_audit)
    result = await service.read(address=address, device="device,4190090")
    assert result["identity_verified"] and result["audit_error"]
    assert result["properties"]["location"] is None
    assert result["property_status"]["location"]["status"] == "unsupported"
    assert result["program_names"] == ["Actual Program 1", "Actual Program 2"]


@pytest.mark.asyncio
async def test_program_result_cap_is_explicit_and_does_not_claim_complete(tmp_path):
    port = free_udp()
    server = details_device(port, programs=17)
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        result = await DeviceDetails(client, client.store, request_gap=0).read(
            address=f"127.0.0.1:{port}", device="device,4190090"
        )
        assert result["identity_verified"] and not result["complete"]
        assert result["programs_status"] == "limit_exceeded" and result["programs_truncated"]
        assert (
            result["programs_total"] == 17
            and len(result["program_names"]) == len(result["programs"]) == 16
        )
    finally:
        client.close()
        close_application(server)
        await asyncio.sleep(0.02)
