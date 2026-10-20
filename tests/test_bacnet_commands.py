"""Actual loopback BACnet commands, durable ownership and wire cancellation."""

import asyncio
import json

import pytest
from bacpypes3.apdu import APDU, ConfirmedRequestPDU, SimpleAckPDU
from bacpypes3.local.binary import BinaryValueObjectCmd
from bacpypes3.pdu import PDU
from bms_tool.bacnet_write import write_property
from bms_tool.connections import Bacnet
from bms_tool.storage import Store

from .test_connections import application, free_udp, point


def binary():
    return BinaryValueObjectCmd(
        objectIdentifier=("binary-value", 1),
        objectName="Isolated commandable binary",
        presentValue="inactive",
        outOfService=False,
        statusFlags=[0, 0, 0, 0],
    )


@pytest.mark.asyncio
async def test_binary_canonical_values_apply_readback_restart_and_release(tmp_path):
    port = free_udp()
    server = application(port, 4190074)
    server.add_object(binary())
    client = Bacnet(Store(tmp_path))
    target = f"127.0.0.1:{port}"
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        for requested in ("active", "inactive", True, False, 1, 0, 1.0, 0.0):
            expected = int(requested == "active") if type(requested) is str else int(requested)
            plan = await client.plan_write(target, "binary-value,1", requested)
            assert type(plan["value"]) is int and plan["value"] == expected
            assert plan["requested_value"] == requested
            result = await client.apply_write(plan["token"])
            assert result["slot"] == {"type": "enumerated", "value": expected}
            assert result["present_value"] == expected
            journal = json.loads(client.journal.read_text())
            entry = journal["commands"][result["command"]]
            assert type(entry["value"]) is int and entry["value"] == expected
            assert entry["requested_value"] == requested
            if requested == "active":
                saved = client.config.copy()
                client.close()
                await asyncio.sleep(0.05)
                client = Bacnet(Store(tmp_path))
                assert result["command"] in client.commands
                await client.connect(**saved)
            released = await client.release(result["command"])
            assert released["released"] and released["present_value"] == 0
            assert not client.commands
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_invalid_binary_scalar_refused_before_any_wire_write(tmp_path):
    port = free_udp()
    server = application(port, 4190075)
    obj = binary()
    server.add_object(obj)
    requests = []
    original = server.do_WritePropertyRequest

    async def counted(request):
        requests.append(request)
        await original(request)

    server.do_WritePropertyRequest = counted
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        for value in (2, -1, 0.5, "0", "1", "true", "Active", "active ", [], {}, None):
            with pytest.raises(ValueError, match="BinaryPV|finite scalar"):
                await client.plan_write(f"127.0.0.1:{port}", "binary-value,1", value)
        assert not requests and not client.plans and not client.commands
        assert int(obj.presentValue) == 0
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["apply", "release"])
async def test_cancelled_accepted_command_retires_write_only_and_keeps_ownership(
    tmp_path, operation
):
    port = free_udp()
    server = application(port, 4190076)
    binary_obj = binary()
    server.add_object(binary_obj)
    server.add_object(point())
    write_entered, acknowledge = asyncio.Event(), asyncio.Event()
    read_entered, read_release = asyncio.Event(), asyncio.Event()
    original_read = server.do_ReadPropertyRequest
    original_confirmation = server.asap.confirmation
    writes_seen = []

    async def wire(pdu):
        decoded = APDU.decode(PDU(bytes(pdu.pduData)))
        if isinstance(decoded, ConfirmedRequestPDU) and decoded.apduService == 15:
            writes_seen.append(decoded.apduInvokeID)
        await original_confirmation(pdu)

    async def held_read(request):
        if str(request.objectIdentifier[0]) == "analog-value":
            read_entered.set()
            await read_release.wait()
        await original_read(request)

    async def accepted_without_ack(request):
        obj = server.get_object_id(request.objectIdentifier)
        value = request.propertyValue.cast_out(
            obj.get_property_type(request.propertyIdentifier), null=True
        )
        await obj.write_property(
            request.propertyIdentifier, value, request.propertyArrayIndex, request.priority
        )
        write_entered.set()
        await acknowledge.wait()
        await server.response(SimpleAckPDU(context=request))

    client = Bacnet(Store(tmp_path))
    running = pending_read = None
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{port}"
        plan = await client.plan_write(target, "binary-value,1", "active")
        if operation == "release":
            previous = await client.apply_write(plan["token"])
        server.asap.confirmation = wire
        server.do_ReadPropertyRequest = held_read
        server.do_WritePropertyRequest = accepted_without_ack
        # Retries would be observable in this short test if cleanup failed.
        client.app.asap.apduTimeout = 80
        pending_read = asyncio.create_task(client.read(target, "analog-value,1"))
        await asyncio.wait_for(read_entered.wait(), 2)
        running = asyncio.create_task(
            client.apply_write(plan["token"])
            if operation == "apply"
            else client.release(previous["command"])
        )
        await asyncio.wait_for(write_entered.wait(), 2)
        assert len(client.app.asap.clientTransactions) == 2
        # Keep the unrelated read from reaching its own retry timeout.
        read_release.set()
        assert (await pending_read)["value"] == 12.5
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert not client.app.asap.clientTransactions and not client.app._requests
        assert not client.lock.locked()
        assert len(client.commands) == 1
        owned = next(iter(client.commands))
        assert owned in json.loads(client.journal.read_text())["commands"]
        assert int(binary_obj.presentValue) == (1 if operation == "apply" else 0)
        await asyncio.sleep(0.3)
        assert len(writes_seen) == 1, "Cancelled exchange must not retransmit."
        acknowledge.set()
        await asyncio.sleep(0.05)
        # Explicit recovery after restart may inspect/relinquish; cancellation
        # itself neither drops ownership nor generates an automatic null write.
        saved = client.config.copy()
        client.close()
        await asyncio.sleep(0.05)
        client = Bacnet(Store(tmp_path))
        await client.connect(**saved)
        assert (await client.release(owned))["released"]
        assert not client.commands
    finally:
        acknowledge.set()
        read_release.set()
        for task in (running, pending_read):
            if task is not None and not task.done():
                task.cancel()
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_actual_write_timeout_stops_retries_and_does_not_relinquish(tmp_path):
    port = free_udp()
    server = application(port, 4190077)
    obj = binary()
    server.add_object(obj)
    release = asyncio.Event()

    async def silent(request):
        value = request.propertyValue.cast_out(obj.get_property_type("present-value"))
        await obj.write_property(request.propertyIdentifier, value, priority=request.priority)
        await release.wait()

    server.do_WritePropertyRequest = silent
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        client.app.asap.apduTimeout = 1000
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                write_property(
                    client.app,
                    f"127.0.0.1:{port}",
                    "binary-value,1",
                    "present-value",
                    1,
                    priority=16,
                ),
                0.1,
            )
        assert int(obj.presentValue) == 1
        assert not client.app.asap.clientTransactions and not client.app._requests
    finally:
        release.set()
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_wrong_service_simple_ack_is_not_write_success(tmp_path):
    port = free_udp()
    server = application(port, 4190078)
    obj = binary()
    server.add_object(obj)

    async def wrong_service(request):
        ack = SimpleAckPDU(context=request)
        ack.apduService = 20  # ReinitializeDevice, not WriteProperty.
        await server.response(ack)

    server.do_WritePropertyRequest = wrong_service
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        with pytest.raises(ValueError, match="identity/service mismatch"):
            await write_property(
                client.app,
                f"127.0.0.1:{port}",
                "binary-value,1",
                "present-value",
                1,
                priority=16,
            )
        assert not client.app.asap.clientTransactions and not client.app._requests
        assert int(obj.presentValue) == 0
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_cancel_during_native_dispatch_lookup_cannot_send_later(tmp_path, monkeypatch):
    """Retire the SSM even before its own invokeID field has been populated."""
    port = free_udp()
    server = application(port, 4190079)
    obj = binary()
    server.add_object(obj)
    entered, proceed = asyncio.Event(), asyncio.Event()
    client = Bacnet(Store(tmp_path))
    task = None
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        original = client.app.device_info_cache.get_device_info
        lookups = 0

        async def held_lookup(address):
            nonlocal lookups
            lookups += 1
            if lookups == 2:  # First is datatype vendor lookup; second is dispatch.
                entered.set()
                await proceed.wait()
            return await original(address)

        monkeypatch.setattr(client.app.device_info_cache, "get_device_info", held_lookup)
        task = asyncio.create_task(
            write_property(
                client.app,
                f"127.0.0.1:{port}",
                "binary-value,1",
                "present-value",
                1,
                priority=16,
            )
        )
        await asyncio.wait_for(entered.wait(), 2)
        [transaction] = client.app.asap.clientTransactions
        assert transaction.invokeID is None
        assert transaction.segmentAPDU.apduInvokeID is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not client.app.asap.clientTransactions and not client.app._requests
        proceed.set()
        await asyncio.sleep(0.1)
        assert int(obj.presentValue) == 0, "An abandoned dispatch must never send later."
    finally:
        proceed.set()
        if task is not None and not task.done():
            task.cancel()
        client.close()
        server.close()
        await asyncio.sleep(0.05)
