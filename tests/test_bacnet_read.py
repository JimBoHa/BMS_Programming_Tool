"""Actual UDP regressions for cancelled reads and malformed acknowledgments."""

import asyncio

import pytest
from bacpypes3.apdu import APDU, ConfirmedRequestPDU, ReadPropertyACK
from bacpypes3.constructeddata import Any
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Real
from bms_tool.connections import Bacnet
from bms_tool.storage import Store

from .test_connections import application, free_udp, point


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_method", ["caller", "disconnect"])
async def test_preinvoke_read_cancellation_stops_dispatch_before_any_udp_packet(
    tmp_path, monkeypatch, cancel_method
):
    port = free_udp()
    server = application(port, 4190080)
    server.add_object(point())
    packets = []
    original_wire = server.asap.confirmation

    async def wire(pdu):
        decoded = APDU.decode(PDU(bytes(pdu.pduData)))
        if isinstance(decoded, ConfirmedRequestPDU):
            packets.append(decoded.apduService)
        await original_wire(pdu)

    server.asap.confirmation = wire
    client = Bacnet(Store(tmp_path))
    entered, release = asyncio.Event(), asyncio.Event()
    task = None
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        app = client.app
        original_lookup = app.device_info_cache.get_device_info
        lookups = 0

        async def held(address):
            nonlocal lookups
            lookups += 1
            if lookups == 2:
                entered.set()
                await release.wait()
            return await original_lookup(address)

        monkeypatch.setattr(app.device_info_cache, "get_device_info", held)
        task = asyncio.create_task(client.read(f"127.0.0.1:{port}", "analog-value,1"))
        await asyncio.wait_for(entered.wait(), 2)
        [transaction] = app.asap.clientTransactions
        assert transaction.invokeID is None
        assert transaction.segmentAPDU.apduInvokeID is not None
        if cancel_method == "caller":
            task.cancel()
        else:
            await client.disconnect()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not app.asap.clientTransactions and not app._requests
        release.set()
        await asyncio.sleep(0.1)
        assert not packets, "A cancelled dispatch cannot transmit later."
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_cancel_one_actual_read_retires_only_its_own_transaction(tmp_path):
    port = free_udp()
    server = application(port, 4190071)
    for number in (1, 2):
        obj = point()
        obj.objectIdentifier = ("analog-value", number)
        obj.objectName = f"Held point {number}"
        server.add_object(obj)
    original = server.do_ReadPropertyRequest
    entered = {number: asyncio.Event() for number in (1, 2)}
    release = {number: asyncio.Event() for number in (1, 2)}

    async def held(request):
        number = int(request.objectIdentifier[1])
        entered[number].set()
        await release[number].wait()
        await original(request)

    server.do_ReadPropertyRequest = held
    client = Bacnet(Store(tmp_path))
    first = second = None
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{port}"
        await client.discover(target)
        first = asyncio.create_task(client.read(target, "analog-value,1"))
        second = asyncio.create_task(client.read(target, "analog-value,2"))
        await asyncio.wait_for(entered[1].wait(), 2)
        await asyncio.wait_for(entered[2].wait(), 2)
        assert len(client.app.asap.clientTransactions) == 2
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert len(client.app.asap.clientTransactions) == 1
        assert sum(len(requests) for requests in client.app._requests.values()) == 1
        release[2].set()
        assert (await second)["value"] == 12.5
        assert not client.app.asap.clientTransactions and not client.app._requests
    finally:
        for event in release.values():
            event.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        client.close()
        await asyncio.sleep(0.05)
        server.close()


@pytest.mark.asyncio
async def test_operation_timeout_and_interface_close_retire_actual_wire_requests(tmp_path):
    port = free_udp()
    server = application(port, 4190072)
    server.add_object(point())
    entered, release = asyncio.Event(), asyncio.Event()

    async def silent(request):
        entered.set()
        await release.wait()

    server.do_ReadPropertyRequest = silent
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{port}"
        await client.discover(target)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(client.read(target, "analog-value,1"), 0.1)
        assert not client.app.asap.clientTransactions and not client.app._requests
        entered.clear()
        task = asyncio.create_task(client.read(target, "analog-value,1"))
        await asyncio.wait_for(entered.wait(), 2)
        app = client.app
        await client.disconnect()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not app.asap.clientTransactions and not app._requests
    finally:
        release.set()
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["object", "property", "array", "datatype"])
async def test_wire_ack_cannot_change_requested_identity(tmp_path, changed):
    port = free_udp()
    server = application(port, 4190073)

    async def altered(request):
        reply = ReadPropertyACK(
            objectIdentifier=("analog-value", 2)
            if changed == "object"
            else request.objectIdentifier,
            propertyIdentifier="cov-increment"
            if changed == "property"
            else request.propertyIdentifier,
            propertyValue=Any(CharacterString("bad real") if changed == "datatype" else Real(12.5)),
            context=request,
        )
        if changed == "array":
            reply.propertyArrayIndex = 1
        await server.response(reply)

    server.do_ReadPropertyRequest = altered
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{port}"
        await client.discover(target)
        expected = (
            "Malformed BACnet property value"
            if changed == "datatype"
            else "identity/property mismatch"
        )
        with pytest.raises(ValueError, match=expected):
            await client.read(target, "analog-value,1")
        assert not client.app.asap.clientTransactions and not client.app._requests
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.05)


def test_remote_point_services_require_the_explicit_opened_network_and_router(tmp_path):
    client = Bacnet(Store(tmp_path))
    for config in [
        None,
        {"router": None, "dnet": None},
        {"router": "127.0.0.1:47808", "dnet": 2002},
    ]:
        client.config = config
        with pytest.raises(ValueError, match="opened first"):
            client.target_address("2001:4")
    client.config = {"router": "127.0.0.1:47808", "dnet": 2001}
    assert str(client.target_address("2001:4")) == "2001:4"
    with pytest.raises(ValueError, match="differs"):
        client.target_address("2001:4@127.0.0.2:47808")


@pytest.mark.asyncio
async def test_standard_wildcard_device_read_accepts_the_actual_device_ack_identity(tmp_path):
    port = free_udp()
    server = application(port, 4190078)

    async def wildcard(request):
        # Independent response: the pinned dependency's server compares a
        # decoded numeric Device type with a string tuple in its wildcard branch.
        identity = ObjectIdentifier((8, 4190078))
        value = (
            identity
            if str(request.propertyIdentifier) == "object-identifier"
            else CharacterString("Independent wildcard endpoint")
        )
        await server.response(
            ReadPropertyACK(
                objectIdentifier=identity,
                propertyIdentifier=request.propertyIdentifier,
                propertyValue=Any(value),
                context=request,
            )
        )

    server.do_ReadPropertyRequest = wildcard
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{port}"
        reply = await client.read(target, "device,4194303", "object-identifier")
        assert reply["value"] == [8, 4190078]
        assert (await client.read(target, "device,4194303", "object-name"))[
            "value"
        ] == "Independent wildcard endpoint"
        assert not client.app.asap.clientTransactions
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.05)
