"""Real owned BACnet peers reject lossy integer preflight without a write packet."""

import asyncio

import pytest
from bms_tool.connections import Bacnet
from bms_tool.storage import Store

from .test_bacnet_command_scalars import DoubleAnalogValue, track_write_packets
from .test_connections import application, free_udp, point


@pytest.mark.parametrize("double", [False, True])
async def test_native_analog_preflight_refuses_integer_loss_but_retains_explicit_float32_profile(
    tmp_path, double
):
    port = free_udp()
    server = application(port, 4190091)
    if double:
        server.device_object.vendorIdentifier = 64201
        obj = DoubleAnalogValue(
            objectIdentifier=("analog-value", 1),
            objectName="Synthetic double point",
            presentValue=12.5,
            units="no-units",
            outOfService=False,
            statusFlags=[0, 0, 0, 0],
        )
    else:
        obj = point()
    server.add_object(obj)
    writes = track_write_packets(server)
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{port}"
        await client.discover(target, 4190091, 4190091)
        await asyncio.sleep(0)
        for value in (2**53 + 1, -(2**53 + 1), 10**1000):
            with pytest.raises(ValueError, match="binary64|finite numeric"):
                await client.plan_write(target, "analog-value,1", value)
            assert client.plans == {} and client.commands == {} and writes == []
        exact = await client.plan_write(target, "analog-value,1", 2**60)
        assert exact["value"] == exact["requested_value"] == 2**60
        native = await client.plan_write(target, "analog-value,1", 2**53 + 2)
        assert native["requested_value"] == 2**53 + 2
        assert native["value"] == (2**53 + 2 if double else 2**53)
        assert float(obj.presentValue) == 12.5 and writes == [] and client.commands == {}
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.05)
