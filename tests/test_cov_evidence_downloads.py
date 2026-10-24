"""Bounded additive snapshots over real native COV receipts; no field writes."""

import json
import math
import sqlite3
from contextlib import contextmanager

import httpx
from bacpypes3.basetypes import PropertyValue
from bacpypes3.constructeddata import Any
from bacpypes3.primitivedata import Real
from bms_tool.app import create_app

from .test_bacnet_cov import network as network
from .test_bacnet_cov import notification, send, wait_for
from .test_connections import free_udp


async def numeric_receipts(server, service, job):
    await wait_for(lambda: job["received"] > 0)
    for number in (-0.0, 1e-7, 1e20):
        previous = job["received"]
        await send(
            server,
            notification(
                job,
                listOfValues=[
                    PropertyValue(propertyIdentifier="present-value", value=Any(Real(number)))
                ],
            ),
        )
        await wait_for(lambda previous=previous: job["received"] > previous)
    await service.recorder.flush()


async def test_page_api_preserves_original_numeric_receipts_bounds_retention_and_restart(
    network, tmp_path
):
    server, analog, _, _, config = network
    analog.presentValue = 2.0
    app = create_app(tmp_path / "http")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            started = await client.post(
                "/api/bacnet/cov/start",
                headers=headers,
                json=config | {"confirmed": False, "record_observations": True},
            )
            assert started.is_success, started.text
            key = started.json()["id"]
            service = app.state.bacnet_cov
            job = service.jobs[key]
            await numeric_receipts(server, service, job)
            path = f"/api/bacnet/cov/recordings/{key}/page"
            response = await client.get(path)
            assert response.is_success, response.text
            raw = response.content
            page = json.loads(raw)
            expected = service.recorder.events(key)
            assert page["events"] == expected
            assert page["recording"]["monitor"] == key
            assert page["recording"]["metadata"]["monitor_id"] == key
            assert page["page"] == {
                "after": 0,
                "limit": 100,
                "count": len(expected),
                "first_sequence": expected[0]["sequence"],
                "last_sequence": expected[-1]["sequence"],
            }
            values = [
                row["evidence"]["values"][0]["value"]
                for row in expected
                if row["event"] == "notification"
            ]
            assert all(type(value) is float for value in values)
            assert values[0] == 2.0 and math.copysign(1, values[1]) == -1
            assert b"-0.0" in raw and b"2.0" in raw
            middle = (
                await client.get(path, params={"after": expected[1]["sequence"], "limit": 2})
            ).json()
            assert middle["events"] == expected[2:4]
            assert middle["page"]["after"] == expected[1]["sequence"]
            assert middle["retention"]["first_retained_sequence"] == expected[0]["sequence"]
            empty = (await client.get(path, params={"after": expected[-1]["sequence"]})).json()
            assert empty["events"] == [] and empty["page"]["first_sequence"] is None
            assert empty["retention"]["events_retained"] == len(expected)
            for params in ({"after": -1}, {"after": 2**63}, {"limit": 0}, {"limit": 1001}):
                assert (await client.get(path, params=params)).status_code == 422
            assert (await client.get("/api/bacnet/cov/recordings/missing/page")).status_code == 422
            assert (
                await client.get(path, headers={"Origin": "https://foreign.example"})
            ).status_code == 403
            assert not app.state.bacnet.commands
            await client.post("/api/bacnet/disconnect", headers=headers, json={})
            await service.recorder.flush()
            saved = (await client.get(path)).content
            assert (
                json.loads(raw) == page
            )  # Later counters/closure never rewrite the earlier response.
    restarted = create_app(tmp_path / "http")
    async with restarted.router.lifespan_context(restarted):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://testserver"
        ) as client:
            original = json.loads(saved)
            reopened = (await client.get(path, params={"limit": len(original["events"])})).json()
            # Shutdown may append a closure receipt; the prior receipt bodies
            # remain exact while current counters/boundaries can advance.
            assert reopened["events"] == original["events"]
            reopened_values = [
                row["evidence"]["values"][0]["value"]
                for row in reopened["events"]
                if row["event"] == "notification"
            ]
            assert all(type(value) is float for value in reopened_values)
            assert math.copysign(1, reopened_values[1]) == -1
            assert (
                reopened["retention"]["events_retained"] >= original["retention"]["events_retained"]
            )
            assert reopened["recording"]["metadata"] == original["recording"]["metadata"]
            assert not (await client.get("/api/session")).json()["field_network_open"]
            assert restarted.state.bacnet_cov.recorder.worker is None


async def test_metadata_receipts_and_retention_share_one_snapshot_during_concurrent_commit(
    network, tmp_path, monkeypatch
):
    from .test_cov_observations import attach

    _, _, _, service, config = network
    recorder = attach(service, tmp_path / "snapshot")
    started = await service.start(**config, confirmed=False, record_observations=True)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["received"] > 0)
    await recorder.flush()
    before = recorder.page(started["id"])
    with recorder._connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
    original_connect = recorder._connect
    changed = False

    class Connection:
        def __init__(self, db):
            self.db = db

        def execute(self, sql, args=()):
            cursor = self.db.execute(sql, args)
            if "AS samples_evicted FROM cov_recordings" not in sql:
                return cursor

            class Cursor:
                def fetchone(inner):
                    nonlocal changed
                    row = cursor.fetchone()
                    if not changed:
                        changed = True
                        with sqlite3.connect(recorder.store.db) as writer:
                            writer.execute(
                                "UPDATE cov_recordings SET recorded=recorded+1 WHERE monitor=?",
                                (started["id"],),
                            )
                            writer.execute(
                                "INSERT INTO cov_receipts(source,event,received_at,recorded_at,evidence) VALUES(?,?,?,?,?)",
                                (
                                    row["source"],
                                    "authored_concurrent",
                                    "2026-10-21T00:00:00+00:00",
                                    "2026-10-21T00:00:00+00:00",
                                    "{}",
                                ),
                            )
                    return row

            return Cursor()

    @contextmanager
    def connected():
        with original_connect() as db:
            yield Connection(db)

    monkeypatch.setattr(recorder, "_connect", connected)
    during = recorder.page(started["id"])
    assert changed
    assert during["recording"] == before["recording"]
    assert during["events"] == before["events"] and during["retention"] == before["retention"]
    after = recorder.page(started["id"])
    assert after["recording"]["recorded"] == before["recording"]["recorded"] + 1
    assert after["retention"]["events_retained"] == before["retention"]["events_retained"] + 1
    assert after["events"][-1]["event"] == "authored_concurrent"
