"""Alternate next hops cannot permit another uncertain station write."""

import asyncio
import copy
import hashlib
import json
import sqlite3

import pytest
from bms_tool.connections import Bacnet
from bms_tool.device_instance import PROFILE, DeviceInstances, InstanceJournal, encoded
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_device_instance import NEW, OLD, InstanceRouter, apply_request, options


class DeferredStation(dict):
    """Both literal routers reach one station whose ACKed update is delayed."""

    def __setitem__(self, key, value):
        if value != NEW:
            super().__setitem__(key, value)


async def test_two_literal_routers_and_separate_apps_cannot_repeat_an_uncertain_write(tmp_path):
    loop = asyncio.get_running_loop()
    routers, clients = [], []
    services = []
    shared = DeferredStation({7: OLD, 8: OLD})
    store = Store(tmp_path)
    try:
        for _ in range(2):
            _, router = await loop.create_datagram_endpoint(
                InstanceRouter, local_addr=("127.0.0.1", 0)
            )
            router.instances = shared
            routers.append(router)
            client = Bacnet(store)
            await client.connect(f"127.0.0.1:{free_udp()}")
            clients.append(client)
            services.append(DeviceInstances(client, store, timeout=0.2, request_gap=0))
        first = await services[0].apply(
            **apply_request(
                await services[0].preview(
                    **options("3001:7", router=routers[0].endpoint, dnet=3001)
                )
            )
        )
        assert first["status"] == "unknown" and first["readback"]["status"] == "verified_old"
        assert first["may_have_applied"] and shared[7] == OLD
        original = services[0].journal.receipt(first["id"])
        second = None
        try:
            plan = await services[1].preview(
                **options("3001:7", router=routers[1].endpoint, dnet=3001)
            )
        except ValueError as exc:
            assert "unresolved" in str(exc)
        else:
            # On the original code this reaches the same station a second time.
            # All endpoints are authored loopback peers, never field equipment.
            second = await services[1].apply(**apply_request(plan))
        assert second is None, "An alternate router admitted a second uncertain station write"
        assert [len(router.writes) for router in routers] == [1, 0]
        assert routers[1].queries == []
        assert services[0].journal.receipt(first["id"]) == original
        # Simulate the deferred original update completing, then resolve only by
        # an explicit readback through its unchanged original dispatch route.
        dict.__setitem__(shared, 7, NEW)
        result = await services[0].reconcile(
            operation_id="original-router-readback", receipt_id=first["id"]
        )
        assert result["readback"]["status"] == "verified_new"
        assert services[0].journal.receipt(first["id"])["attempt"] == original["attempt"]
        assert result["read_only"] and [len(router.writes) for router in routers] == [1, 0]
        services[1]._available({"address": "3001:7", "router": routers[1].endpoint, "dnet": 3001})
    finally:
        for service in services:
            await service.close()
        for client in clients:
            client.close()
        for router in routers:
            await router.close()
        assert all(not router.errors for router in routers)


def test_legacy_full_route_keys_remain_immutable_and_alias_check_is_transactional(tmp_path):
    store = Store(tmp_path)
    journal = InstanceJournal(store)
    target = {"address": "3001:7", "router": "127.0.0.1:50001", "dnet": 3001}
    old = {
        "profile": PROFILE,
        "id": "a" * 32,
        "target": target,
        "status": "unknown",
        "may_have_applied": True,
        "readback": {"status": "verified_old"},
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    original_raw = journal._raw(old)
    with store.connect() as db:
        # This is the unchanged historical schema and exact old target key.
        db.execute(
            "INSERT INTO device_instance_changes VALUES(?,NULL,?,?,?,1)",
            (old["id"], original_raw, old["created_at"], encoded(target).decode()),
        )
    alias = {**target, "router": "127.0.0.1:50002"}
    other = InstanceJournal(store)
    with pytest.raises(sqlite3.IntegrityError):
        other.intent({**copy.deepcopy(old), "id": "b" * 32, "target": alias})
    with store.connect() as db:
        rows = db.execute("SELECT result,station_key FROM device_instance_changes").fetchall()
        assert len(rows) == 1 and rows[0][0] == original_raw
        assert rows[0][1] == encoded(target).decode()
        assert "device_instance_station_pending" in {
            row[1] for row in db.execute("PRAGMA index_list(device_instance_changes)")
        }


def test_station_key_canonicalizes_network_mac_and_direct_default_port():
    from bms_tool.device_instance import station_key

    def routed(address, router="127.0.0.1:50001"):
        return station_key({"address": address, "router": router, "dnet": 3001})

    assert routed("3001:7") == routed("3001:0x07", "127.0.0.1:50002")
    assert routed("3001:0x01ab") == routed("3001:0x01AB")
    assert routed("3001:7") != routed("3001:8")
    assert station_key({"address": "127.0.0.1", "router": None, "dnet": None}) == station_key(
        {"address": "127.0.0.1:47808", "router": None, "dnet": None}
    )


def test_a_different_pending_station_keeps_its_own_new_intent_bytes_and_alias_guard(tmp_path):
    store = Store(tmp_path)
    journal = InstanceJournal(store)

    def attempt(identifier, network, review, request):
        return {
            "profile": PROFILE,
            "id": identifier,
            "target": {"address": f"{network}:7", "router": "127.0.0.1:50001", "dnet": network},
            "status": "not_sent",
            "dispatch_started": False,
            "may_have_applied": False,
            "readback": {"status": "not_read"},
            "created_at": "2026-01-01T00:00:00+00:00",
            "review_sha256": review,
            "request_apdu_sha256": hashlib.sha256(request).hexdigest(),
        }

    first = attempt("a" * 32, 2001, "a" * 64, b"authored first request")
    second = attempt("b" * 32, 3001, "b" * 64, b"authored different request")
    journal.intent(first)
    with store.connect() as db:
        first_raw = bytes(
            db.execute(
                "SELECT intent FROM device_instance_changes WHERE id=?", (first["id"],)
            ).fetchone()[0]
        )
    returned_digest = journal.intent(second)
    with store.connect() as db:
        actual_raw = bytes(
            db.execute(
                "SELECT intent FROM device_instance_changes WHERE id=?", (second["id"],)
            ).fetchone()[0]
        )
        assert (
            bytes(
                db.execute(
                    "SELECT intent FROM device_instance_changes WHERE id=?", (first["id"],)
                ).fetchone()[0]
            )
            == first_raw
        )
    actual = json.loads(actual_raw)
    assert actual["id"] == second["id"]
    assert actual["target"] == second["target"]
    assert actual["review_sha256"] == second["review_sha256"]
    assert actual["request_apdu_sha256"] == second["request_apdu_sha256"]
    expected = {
        **second,
        "status": "unknown",
        "may_have_applied": True,
        "dispatch_started": None,
        "journal_state": "intent_only",
    }

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

    expected_raw = canonical(
        {**expected, "evidence_sha256": hashlib.sha256(canonical(expected)).hexdigest()}
    )
    assert actual_raw == expected_raw
    assert returned_digest == hashlib.sha256(actual_raw).hexdigest()
    assert journal.receipt(second["id"])["intent"] == json.loads(expected_raw)
    alias = {**second, "id": "c" * 32, "target": {**second["target"], "router": "127.0.0.1:50002"}}
    with pytest.raises(sqlite3.IntegrityError):
        InstanceJournal(store).intent(alias)
