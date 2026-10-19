"""Owned commands survive refusal; closing an idle interface remains explicit."""

import asyncio

import pytest
from bms_tool.connections import Bacnet
from bms_tool.storage import Store

from .test_connections import application, free_udp, point


@pytest.mark.asyncio
async def test_disconnect_refuses_owned_command_then_closes_after_actual_relinquish(
    tmp_path, monkeypatch
):
    server_port = free_udp()
    server = application(server_port, 4190027)
    server.add_object(point())
    store = Store(tmp_path)
    client = Bacnet(store)
    target = f"127.0.0.1:{server_port}"
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        plan = await client.plan_write(target, "analog-value,1", 42, 16)
        command = await client.apply_write(plan["token"])
        with pytest.raises(ValueError, match="Relinquish"):
            await client.disconnect()
        assert client.status()["connected"]
        assert command["command"] in client.commands
        assert (await client.read(target, "analog-value,1"))["value"] == 42
        await client.release(command["command"])
        pending = await client.plan_write(target, "analog-value,1", 50, 16)
        original_record = store.record

        def audit_failure(operation, detail):
            if operation == "bacnet.disconnected":
                raise OSError("Injected completion failure")
            return original_record(operation, detail)

        monkeypatch.setattr(store, "record", audit_failure)
        result = await client.disconnect()
        assert result["connected"] is False and not client.commands
        assert result["audit_error"].startswith("Interface closed;")
        assert pending["token"] not in client.plans
        with pytest.raises(ValueError, match="Connect"):
            await client.read(target, "analog-value,1")
        assert Bacnet(Store(tmp_path)).status()["connected"] is False
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.05)
