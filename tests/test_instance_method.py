"""Permission evidence blocks repeat writes without inventing a vendor protocol."""

import asyncio
import copy

import pytest
from bacpypes3.apdu import Error, SimpleAckPDU
from bms_tool.connections import Bacnet
from bms_tool.device_instance import DeviceInstances, encoded, seal
from bms_tool.instance_method import assess_method, permission_denied
from bms_tool.storage import Store

from .test_bacnet_events import assert_retired
from .test_connections import free_udp
from .test_device_instance import NEW, OLD, InstanceRouter, apply_request, clear_collision, options
from .test_device_instance import link as link


@pytest.mark.parametrize("vendor", [5, 42, 260])
async def test_denied_method_survives_restart_and_changed_proposal(link, monkeypatch, vendor):
    peer, client, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    peer.metadata["vendor-identifier"] = vendor
    peer.mode = "reject"
    plan = await service.preview(**options(address))
    assert plan["method_assessment"]["state"] == "unverified"
    assert plan["can_apply"] and not peer.wire_writes
    denied = await service.apply(**apply_request(plan))
    assert denied["protocol_error"] == {"class": "property", "code": "write-access-denied"}
    assert denied["status"] == "rejected" and permission_denied(denied)
    original = service.journal.receipt(denied["id"])

    restarted = DeviceInstances(client, client.store, timeout=0.1, request_gap=0)
    monkeypatch.setattr(restarted, "_collision", clear_collision)
    try:
        plan = await restarted.preview(**options(address, new_instance=NEW + 1))
        method = plan["method_assessment"]
        assert not plan["can_apply"] and not method["can_attempt"]
        assert method["state"] == "write_access_denied"
        assert method["evidence"][0]["receipt_id"] == denied["id"]
        assert "permanently read-only" in method["reason"]
        with pytest.raises(ValueError, match="blocked"):
            await restarted.apply(**apply_request(plan))
        # Readback remains available after an operator commissions externally.
        peer.instance = NEW
        observed = await restarted.reconcile(
            operation_id="external-transfer-readback", receipt_id=denied["id"]
        )
        assert observed["read_only"] and observed["readback"]["status"] == "verified_new"
        assert restarted.journal.receipt(denied["id"])["attempt"] == original["attempt"]
        assert len(peer.wire_writes) == 1
        assert_retired(client)
    finally:
        await restarted.close()


async def test_legacy_denial_blocks_without_rewriting_sealed_receipt(link, monkeypatch):
    peer, client, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    peer.mode = "reject"
    denied = await service.apply(**apply_request(await service.preview(**options(address))))
    # An older application stored only the exact native rejection text.
    legacy = copy.deepcopy(denied)
    legacy.pop("protocol_error")
    legacy.pop("method_assessment")
    raw = encoded(seal(legacy))
    with client.store.connect() as db:
        db.execute("UPDATE device_instance_changes SET result=? WHERE id=?", (raw, denied["id"]))
    plan = await service.preview(**options(address))
    assert not plan["can_apply"]
    with client.store.connect() as db:
        assert (
            db.execute(
                "SELECT result FROM device_instance_changes WHERE id=?", (denied["id"],)
            ).fetchone()[0]
            == raw
        )
    assert len(peer.wire_writes) == 1


async def test_denial_after_preview_blocks_a_second_service_before_dispatch(link, monkeypatch):
    peer, client, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    other = DeviceInstances(client, client.store, timeout=0.1, request_gap=0)
    monkeypatch.setattr(other, "_collision", clear_collision)
    try:
        stale = await other.preview(**options(address))
        peer.mode = "reject"
        denied = await service.apply(**apply_request(await service.preview(**options(address))))
        assert denied["status"] == "rejected"
        result = await other.apply(**apply_request(stale))
        assert result["status"] == "not_sent" and not result["may_have_applied"]
        assert "previously denied" in result["errors"][0]
        assert len(peer.wire_writes) == 1
        assert_retired(client)
    finally:
        await other.close()


async def test_denial_is_station_and_identity_specific(link, monkeypatch):
    peer, _, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    peer.mode = "reject"
    await service.apply(**apply_request(await service.preview(**options(address))))
    target = {"address": address, "router": None, "dnet": None}
    identity = {"device": f"device,{OLD}", **peer.metadata}
    assert not service._method(target, identity)["can_attempt"]
    # A different endpoint and a genuinely different firmware/metadata need
    # their own assessment; a model name alone never decides writability.
    other = {**target, "address": "127.0.0.2:47808"}
    assert service._method(other, identity)["can_attempt"]
    assert service._method(target, {**identity, "firmware-revision": "2.0"})["can_attempt"]
    assert len(peer.wire_writes) == 1


def test_only_explicit_validated_property_permission_error_is_used():
    denied = {
        "status": "rejected",
        "dispatch_started": True,
        "may_have_applied": False,
        "protocol_accepted": False,
        "errors": ["property: write-access-denied"],
    }
    assert permission_denied(denied)
    for change in [
        {"status": "unknown"},
        {"dispatch_started": False},
        {"may_have_applied": True},
        {"protocol_accepted": True},
        {"errors": ["property: value-out-of-range"]},
        {"errors": ["Write timed out: property: write-access-denied"]},
    ]:
        assert not permission_denied({**denied, **change})


async def test_literal_router_alias_cannot_bypass_denial_and_other_mac_is_independent(tmp_path):
    class DenyingRouter(InstanceRouter):
        def frame(self, reply, mac):
            if isinstance(reply, SimpleAckPDU):
                self.instances[mac] = OLD
                reply = Error(
                    service_choice=15,
                    errorClass="property",
                    errorCode="writeAccessDenied",
                    context=reply,
                )
            return super().frame(reply, mac)

    loop = asyncio.get_running_loop()
    routers, clients, services = [], [], []
    try:
        store = Store(tmp_path)
        for _ in range(2):
            _, router = await loop.create_datagram_endpoint(
                DenyingRouter, local_addr=("127.0.0.1", 0)
            )
            routers.append(router)
            client = Bacnet(store)
            await client.connect(f"127.0.0.1:{free_udp()}")
            clients.append(client)
            service = DeviceInstances(client, store, timeout=0.2, request_gap=0)
            services.append(service)
        denied = await services[0].apply(
            **apply_request(
                await services[0].preview(
                    **options("3001:7", router=routers[0].endpoint, dnet=3001)
                )
            )
        )
        assert denied["status"] == "rejected", denied
        plan = await services[1].preview(
            **options("3001:0x07", router=routers[1].endpoint, dnet=3001)
        )
        assert not plan["can_apply"]
        assert plan["method_assessment"]["evidence"][0]["receipt_id"] == denied["id"]
        with pytest.raises(ValueError, match="blocked"):
            await services[1].apply(**apply_request(plan))
        # Same device ID and metadata on a distinct station is not the denial's target.
        assert services[1]._method({**plan["target"], "address": "3001:8"}, plan["identity"])[
            "can_attempt"
        ]
        assert [len(router.writes) for router in routers] == [1, 0]
        assert all(not router.errors for router in routers)
        for client in clients:
            assert_retired(client)
    finally:
        for service in services:
            await service.close()
        for client in clients:
            client.close()
        for router in routers:
            await router.close()


@pytest.mark.parametrize(
    "model", ["MS-VMA1630-0", "MS-FEC2611-0", "FX-PCG2611-0", "UNLISTED-NEW-MODEL"]
)
def test_native_family_candidate_still_requires_captured_format_validation(model):
    identity = {"vendor-identifier": 5, "model-name": model}
    assert assess_method(identity)["can_attempt"]  # no fabricated read-only test
    assert assess_method(identity)["state"] == "unverified"
    denied = {"id": "a" * 32, "finished_at": "2026-01-01", "evidence_sha256": "b" * 64}
    result = assess_method(identity, denied)
    assert not result["can_attempt"] and not result["external_transfer_available"]
    assert result["native_application_adapter"] == "mce-native-application"
    assert not result["sources"]
    assert "Connected application transfer" in result["next_steps"][0]
    assert "actual protocol and application format" in result["next_steps"][1]
    other_vendor = assess_method({**identity, "vendor-identifier": 999}, denied)
    assert not other_vendor["can_attempt"] and not other_vendor["sources"]
