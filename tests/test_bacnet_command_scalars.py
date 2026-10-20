"""Scalar preflight against actual BACnet encoders and loopback devices."""

import asyncio
import json

import pytest
from bacpypes3.apdu import APDU, ConfirmedRequestPDU, SimpleAckPDU
from bacpypes3.basetypes import PriorityValue
from bacpypes3.local.analog import AnalogOutputObject, AnalogValueObjectCmd
from bacpypes3.local.cmd import Commandable
from bacpypes3.local.multistate import MultiStateOutputObject, MultiStateValueObject
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import Double, Null, Real, Unsigned
from bacpypes3.vendor import VendorInfo
from bms_tool.bacnet_write import write_property
from bms_tool.connections import Bacnet
from bms_tool.storage import Store

from .test_connections import application, free_udp, point

# Authored isolated vendor descriptors exercise an explicitly known Double and
# an unsupported analog datatype. They make no claim about any real product.
_scalar_test_vendor = VendorInfo(64201)


class DoubleAnalogValue(AnalogValueObjectCmd):
    _vendor_id = 64201
    presentValue: Double
    relinquishDefault: Double

    async def write_property(self, attr, value, index=None, priority=None):
        # The library's generic PriorityValue(Double(...)) tests Real first
        # (Double derives from Real), selecting the wrong choice. Our authored
        # Double device uses the explicit native Double choice so its actual
        # wire response models a controller with a genuine Double priority.
        if getattr(attr, "attr", attr) == "presentValue" and isinstance(value, Double):
            await super(Commandable, self).write_property(
                "priorityArray",
                PriorityValue(double=value),
                priority if priority is not None else 16,
            )
        else:
            await super().write_property(attr, value, index, priority)


class UnsupportedAnalogOutput(AnalogOutputObject):
    _vendor_id = 64201
    presentValue: Unsigned
    relinquishDefault: Unsigned


class CommandableMultiStateValue(Commandable, MultiStateValueObject):
    """Use the native commandable implementation with its unsigned MSV schema."""


def output(cls=AnalogOutputObject):
    return cls(
        objectIdentifier=("analog-output", 1),
        objectName="Isolated analog output",
        presentValue=12.5 if cls is AnalogOutputObject else 1,
        units="no-units",
        outOfService=False,
        statusFlags=[0, 0, 0, 0],
    )


def multistate(kind):
    cls = MultiStateOutputObject if kind == "multi-state-output" else CommandableMultiStateValue
    return cls(
        objectIdentifier=(kind, 1),
        objectName=f"Isolated {kind}",
        presentValue=1,
        numberOfStates=3,
        outOfService=False,
        statusFlags=[0, 0, 0, 0],
    )


def track_write_packets(server):
    packets = []
    original = server.asap.confirmation

    async def wire(pdu):
        decoded = APDU.decode(PDU(bytes(pdu.pduData)))
        if isinstance(decoded, ConfirmedRequestPDU) and decoded.apduService == 15:
            packets.append(bytes(pdu.pduData))
        await original(pdu)

    server.asap.confirmation = wire
    return packets


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted_without_ack", [False, True])
async def test_real32_wire_value_survives_verified_or_uncertain_restart_recovery(
    tmp_path, accepted_without_ack
):
    port = free_udp()
    server = application(port, 4190081)
    obj = point()
    server.add_object(obj)
    client = Bacnet(Store(tmp_path))
    accepted, acknowledge = asyncio.Event(), asyncio.Event()
    original_write = server.do_WritePropertyRequest
    task = None

    async def held_ack(request):
        value = request.propertyValue.cast_out(obj.get_property_type(request.propertyIdentifier))
        await obj.write_property(request.propertyIdentifier, value, priority=request.priority)
        accepted.set()
        await acknowledge.wait()
        await server.response(SimpleAckPDU(context=request))

    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{port}"
        plan = await client.plan_write(target, "analog-value,1", 123.456789)
        # Independent IEEE754 single-precision result for 42f6e9e0, also
        # independently checked by the production native encoder/readback.
        assert plan["value"] == 123.456787109375
        assert plan["requested_value"] == 123.456789
        if accepted_without_ack:
            server.do_WritePropertyRequest = held_ack
            task = asyncio.create_task(client.apply_write(plan["token"]))
            await asyncio.wait_for(accepted.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            [command] = client.commands
            assert "slot" not in client.commands[command]
        else:
            result = await client.apply_write(plan["token"])
            command = result["command"]
            assert result["present_value"] == result["slot"]["value"] == plan["value"]
        assert float(obj.presentValue) == plan["value"]
        saved = json.loads(client.journal.read_text())["commands"][command]
        assert saved["value"] == 123.456787109375
        assert saved["requested_value"] == 123.456789
        config = client.config.copy()
        client.close()
        acknowledge.set()
        await asyncio.sleep(0.05)
        server.do_WritePropertyRequest = original_write
        client = Bacnet(Store(tmp_path))
        await client.connect(**config)
        released = await client.release(command)
        assert released["released"] and released["present_value"] == 12.5
        assert not client.commands
    finally:
        acknowledge.set()
        if task is not None and not task.done():
            task.cancel()
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_invalid_analog_and_multistate_scalars_send_zero_write_frames(tmp_path):
    port = free_udp()
    server = application(port, 4190082)
    server.add_object(point())
    server.add_object(output())
    server.add_object(multistate("multi-state-output"))
    server.add_object(multistate("multi-state-value"))
    packets = track_write_packets(server)
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{port}"
        for kind in ("analog-value", "analog-output"):
            for value in ("123.456789", True, False, 1e40, 10**400, float("inf"), float("nan")):
                with pytest.raises(ValueError, match="Analog command"):
                    await client.plan_write(target, f"{kind},1", value)
        for kind in ("multi-state-value", "multi-state-output"):
            for value in ("1", True, False, 0, -1, 1.0, 1.5, 4, 10**400):
                with pytest.raises(ValueError, match="Multistate command"):
                    await client.plan_write(target, f"{kind},1", value)
        await asyncio.sleep(0.05)
        assert not packets and not client.plans and not client.commands
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["multi-state-output", "multi-state-value"])
async def test_actual_multistate_positive_integer_command_and_relinquish(tmp_path, kind):
    port = free_udp()
    server = application(port, 4190083)
    server.add_object(multistate(kind))
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        plan = await client.plan_write(f"127.0.0.1:{port}", f"{kind},1", 2)
        assert type(plan["value"]) is int and plan["value"] == plan["requested_value"] == 2
        result = await client.apply_write(plan["token"])
        assert result["present_value"] == result["slot"]["value"] == 2
        assert (await client.release(result["command"]))["present_value"] == 1
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_actual_known_double_preserves_precision_and_other_analog_type_refuses(tmp_path):
    port = free_udp()
    server = application(port, 4190084)
    server.device_object.vendorIdentifier = 64201
    server.add_object(
        DoubleAnalogValue(
            objectIdentifier=("analog-value", 1),
            objectName="Authored double test point",
            presentValue=12.5,
            units="no-units",
            outOfService=False,
            statusFlags=[0, 0, 0, 0],
        )
    )
    server.add_object(output(UnsupportedAnalogOutput))
    packets = track_write_packets(server)
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{port}"
        devices = await client.discover(target, 4190084, 4190084)
        assert devices[0]["vendor"] == 64201
        # The pinned native Who-Is collector schedules its cache update after
        # resolving the exact-instance discovery future. Let that task finish
        # so preflight has the actual known vendor descriptor, not fallback.
        await asyncio.sleep(0)
        plan = await client.plan_write(target, "analog-value,1", 123.456789)
        assert plan["value"] == plan["requested_value"] == 123.456789
        result = await client.apply_write(plan["token"])
        assert result["slot"] == {"type": "double", "value": 123.456789}
        assert result["present_value"] == 123.456789
        assert (await client.release(result["command"]))["present_value"] == 12.5
        written = len(packets)
        with pytest.raises(ValueError, match="known Real or Double"):
            await client.plan_write(target, "analog-output,1", 2)
        assert len(packets) == written
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_adjacent_real_takeover_cannot_be_verified_or_released_as_owned(tmp_path):
    port = free_udp()
    server = application(port, 4190085)
    obj = point()
    server.add_object(obj)
    original_write = server.do_WritePropertyRequest
    packets = track_write_packets(server)
    client = Bacnet(Store(tmp_path / "owner"))
    other = Bacnet(Store(tmp_path / "other"))
    first = True
    target = f"127.0.0.1:{port}"
    intended = 123.456787109375  # Native Real 0x42f6e9e0.
    adjacent = 123.45679473876953  # Native Real 0x42f6e9e1, exactly one ULP away.

    async def takeover_before_ack(request):
        nonlocal first
        if not first:
            return await original_write(request)
        first = False
        value = request.propertyValue.cast_out(Real)
        await obj.write_property(request.propertyIdentifier, value, priority=request.priority)
        # A separate actual UDP client takes the same priority before the
        # original client's ACK/readback, rather than a mocked read result.
        await write_property(
            other.app, target, "analog-value,1", "present-value", adjacent, priority=16
        )
        await server.response(SimpleAckPDU(context=request))

    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        await other.connect(f"127.0.0.1:{free_udp()}")
        plan = await client.plan_write(target, "analog-value,1", 123.456789)
        assert plan["value"] == intended
        server.do_WritePropertyRequest = takeover_before_ack
        with pytest.raises(ValueError, match="readback differs"):
            await client.apply_write(plan["token"])
        assert float(obj.presentValue) == adjacent
        [command] = client.commands
        assert "slot" not in client.commands[command]
        assert len(packets) == 2
        with pytest.raises(ValueError, match="cannot establish ownership"):
            await client.release(command)
        assert float(obj.presentValue) == adjacent
        assert len(packets) == 2, "Refused release cannot send a null command."
        assert command in json.loads(client.journal.read_text())["commands"]
        # Test-owned recovery is explicit: the second client clears its slot,
        # then the first can retire its retained uncertain ownership record.
        await write_property(
            other.app, target, "analog-value,1", "present-value", Null(()), priority=16
        )
        assert (await client.release(command))["released"]
        assert float(obj.presentValue) == 12.5 and not client.commands
    finally:
        client.close()
        other.close()
        server.close()
        await asyncio.sleep(0.05)
