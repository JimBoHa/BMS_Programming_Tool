"""Real UDP baseline/protected transfer and owned cancellation recovery."""

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest
from bms_tool.app import create_app
from bms_tool.operation_power import OperationPower, UnavailableProvider

from tests.test_operation_power import Provider
from tests.test_temco_transfer import (
    IDENTITY,
    INSTANCE,
    SOURCE,
    free_udp,
)
from tests.test_temco_transfer import (
    link as shared_link,
)

link = shared_link


@pytest.mark.parametrize("failure", [False, True])
async def test_original_and_protected_udp_packet_payloads_recovery_and_receipt_meaning_match(
    link, failure
):
    server, _, adapter, address = link
    comparisons = []
    original = bytes(server.images[3])
    provider = Provider()
    manager = OperationPower(provider)
    for managed in (False, True):
        server.setup()
        adapter.operation_power = manager if managed else None
        plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)
        assert not provider.calls  # No assertion during planning or user review.
        if failure:
            server.fail_package = 2
        requests_before, writes_before = len(server.requests), len(server.writes)

        def check_owned(command, slot, package, protected=managed):
            if protected:
                assert len(manager.status()["active"]) == 1
                assert manager.status()["active"][0]["request_active"]
                assert [r[0] for r in provider.calls] == ["open"]

        server.before_write = check_owned
        result = await adapter.apply(plan["token"])
        if failure:
            assert not result["ok"] and result["recovery"]["restored"]
            assert bytes(server.images[3]) == original
        else:
            assert result["ok"] and result["readback_verified"]
        comparisons.append(
            (
                server.requests[requests_before:],
                server.writes[writes_before:],
                {k: v for k, v in result.items() if k not in ("operation", "backup_id")},
            )
        )
        assert not adapter.status()["uncertain"]
    assert comparisons[0] == comparisons[1]
    assert [r[0] for r in provider.calls] == ["open", "close"]
    assert not manager.status()["active"]
    if destination := os.environ.get("BMS_POWER_PACKET_EVIDENCE"):

        def serialized(value):
            if isinstance(value, bytes):
                return {"bytes_hex": value.hex()}
            if isinstance(value, (list, tuple)):
                return [serialized(item) for item in value]
            if isinstance(value, dict):
                return {key: serialized(item) for key, item in value.items()}
            return value

        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        (root / ("recovery.json" if failure else "success.json")).write_text(
            json.dumps(
                {
                    "baseline": serialized(comparisons[0]),
                    "managed": serialized(comparisons[1]),
                    "provider_calls": provider.calls,
                    "qualification": "Actual emulator-decoded private commands and original write payload bytes plus receipts with random operation/backup IDs excluded. Not original full UDP packet capture or invoke-ID equality.",
                },
                indent=2,
            )
            + "\n"
        )


async def test_shutdown_and_repeated_caller_cancel_keep_power_through_shielded_original_restore(
    link, monkeypatch
):
    server, client, adapter, address = link
    provider = Provider()
    manager = OperationPower(provider)
    adapter.operation_power = manager
    original = bytes(server.images[3])
    plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)
    started, proceed = asyncio.Event(), asyncio.Event()
    recover = adapter._recover

    async def observed_recovery(*args):
        assert manager.status()["active"][0]["request_active"]
        started.set()
        await proceed.wait()
        result = await recover(*args)
        assert manager.status()["active"][0]["request_active"]
        assert [r[0] for r in provider.calls] == ["open"]
        return result

    monkeypatch.setattr(adapter, "_recover", observed_recovery)
    task = asyncio.create_task(adapter.apply(plan["token"]))

    def cancel(command, slot, package):
        assert manager.status()["active"][0]["request_active"]
        if command == 116 and package == 1:
            task.cancel()
            server.before_write = None

    server.before_write = cancel
    await asyncio.wait_for(started.wait(), 3)
    shutdown = await manager.close(wait_seconds=0)
    assert shutdown["pending_active"] and not shutdown["forced_release"]
    assert client.lock.locked() and [r[0] for r in provider.calls] == ["open"]
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bytes(server.images[3]) == original and server.descriptors[3][32] == 1
    assert not client.lock.locked() and not adapter.status()["uncertain"]
    assert [r[0] for r in provider.calls] == ["open", "close"]
    assert not manager.status()["active"]


async def test_invalid_or_consumed_plan_never_acquires_and_unavailable_protection_does_not_add_packets(
    link,
):
    server, _, adapter, address = link
    manager = OperationPower(UnavailableProvider())
    adapter.operation_power = manager
    with pytest.raises(ValueError, match="unknown"):
        await adapter.apply("absent")
    assert manager.status()["recent"] == [] and not server.requests
    plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)
    assert manager.status()["recent"] == []
    assert (await adapter.apply(plan["token"]))["ok"]
    assert manager.status()["recent"][0]["state"] == "unavailable"
    with pytest.raises(ValueError, match="consumed"):
        await adapter.apply(plan["token"])
    assert len(manager.status()["recent"]) == 1


async def test_actual_authenticated_app_only_admits_apply_and_releases_before_http_completion(
    link, tmp_path
):
    server, _, _, address = link
    provider = Provider()
    manager = OperationPower(provider)
    app = create_app(tmp_path / "power-http", operation_power=manager)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            status = (await client.get("/api/operation-power")).json()
            assert status["active"] == status["recent"] == [] and not provider.calls
            assert (
                await client.post(
                    "/api/bacnet/connect",
                    headers=headers,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                )
            ).status_code == 200
            target = {"address": address, "device_instance": INSTANCE, "slot": 3, **IDENTITY}
            assert (
                await client.post("/api/temco/transfer/inspect", json=target, headers=headers)
            ).status_code == 200
            plan = (
                await client.post(
                    "/api/temco/transfer/plan", json=target | {"source": SOURCE}, headers=headers
                )
            ).json()
            assert not provider.calls
            assert (
                await client.post("/api/temco/transfer/apply", json={"token": plan["token"]})
            ).status_code == 403
            assert not provider.calls

            def during_write(*args):
                assert manager.status()["active"][0]["request_active"]

            server.before_write = during_write
            response = await client.post(
                "/api/temco/transfer/apply", json={"token": plan["token"]}, headers=headers
            )
            assert response.status_code == 200 and response.json()["ok"]
            status = (await client.get("/api/operation-power")).json()
            assert not status["active"] and status["recent"][0]["cleanup_confirmed"]
            assert [r[0] for r in provider.calls] == ["open", "close"]
    assert app.state.power_shutdown == {
        "admission_closed": True,
        "pending_active": [],
        "forced_release": False,
    }
