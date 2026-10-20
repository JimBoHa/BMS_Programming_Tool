"""Durable webhook evidence tested with real HTTP on loopback only."""

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from bms_tool.notification_outbox import NotificationOutbox
from bms_tool.observability import ObservabilityStore

BASE = datetime(2026, 1, 5, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.value = BASE

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


@pytest.fixture
async def factory(tmp_path):
    instances = []

    def create(*, directory=None, observations=None, **options):
        directory = directory or tmp_path / f"outbox-{len(instances)}"
        observations = observations or ObservabilityStore(
            tmp_path / f"observations-{len(instances)}"
        )
        service = NotificationOutbox(directory, observations, **options)
        instances.append(service)
        return service, observations

    yield create
    for service in reversed(instances):
        await service.close()


@pytest.fixture
async def sink():
    requests, behaviors, tasks = [], [], set()
    received, hold = asyncio.Event(), asyncio.Event()

    async def handle(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
            lines = raw.decode("latin-1").split("\r\n")
            headers = dict(line.split(": ", 1) for line in lines[1:] if line)
            body = await reader.readexactly(int(headers.get("Content-Length", "0")))
            requests.append({"request": lines[0], "headers": headers, "body": body})
            received.set()
            behavior = behaviors.pop(0) if behaviors else 204
            if behavior == "drop":
                return
            if behavior == "stall":
                await hold.wait()
                behavior = 204
            location = f"Location: {server_url}/redirect-target\r\n" if behavior == 302 else ""
            writer.write(
                f"HTTP/1.1 {behavior} Test\r\n{location}Content-Length: 0\r\nConnection: close\r\n\r\n".encode()
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    server_url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    yield {
        "url": server_url,
        "requests": requests,
        "behaviors": behaviors,
        "received": received,
        "hold": hold,
    }
    server.close()
    hold.set()
    for task in list(tasks):
        task.cancel()
    pending = list(tasks)
    if pending:
        done, waiting = await asyncio.wait(pending, timeout=1)
        assert not waiting, f"Loopback receiver tasks did not close: {waiting}"
        await asyncio.gather(*done, return_exceptions=True)
    await server.wait_closed()


def activate(store, source="sim", second=0):
    return store.record_scan(source, BASE + timedelta(seconds=second), {}, {"fault": True})


def returned(store, source="sim", second=1):
    return store.record_scan(source, BASE + timedelta(seconds=second), {}, {"fault": False})


def rows(service, **filters):
    return service.deliveries(**filters)["rows"]


async def test_real_loopback_receipts_preserve_original_events_and_never_acknowledge_alarms(
    factory, sink
):
    service, store = factory()
    route = service.create_route("Loopback receipt test", sink["url"], start_after=0)
    activate(store)
    returned(store)
    activate(store, second=2)
    store.end_source("sim", "Simulation ended", actor="Test")
    original = store.alarm_events()
    assert service.status()["active_routes"] == 0
    assert (await service.cycle())["attempted"] == 0
    assert not sink["requests"] and not rows(service)
    service.enable_route(route["id"], True)
    result = await service.cycle()
    assert result["enqueued"] == result["delivered"] == result["attempted"] == 4
    assert [json.loads(row["body"])["event"] for row in sink["requests"]] == original
    for received, delivery in zip(sink["requests"], rows(service), strict=True):
        body = received["body"]
        assert (
            hashlib.sha256(body).hexdigest()
            == received["headers"]["X-BMS-Payload-SHA256"]
            == delivery["payload_sha256"]
        )
        assert received["headers"]["Idempotency-Key"] == delivery["idempotency_key"]
        assert json.loads(body)["source_kind"] == "simulation"
        assert service.delivery(delivery["id"])["payload_integrity"]
        assert "payload" not in delivery
    assert len(store.alarms(unacknowledged=True)) == 2
    assert (await service.cycle())["attempted"] == 0
    assert len(sink["requests"]) == 4


async def test_new_routes_start_after_current_head_unless_history_is_explicit(factory, sink):
    service, store = factory()
    activate(store)
    route = service.create_route("Future events", sink["url"])
    assert (
        route["start_after"]
        == route["cursor"]
        == service.status()["latest_alarm_event_sequence"]
        == 1
    )
    returned(store)
    service.enable_route(route["id"], True)
    await service.cycle()
    assert [json.loads(row["body"])["event"]["sequence"] for row in sink["requests"]] == [2]


async def test_exact_source_and_event_filters_advance_only_deliberate_skips(factory, sink):
    service, store = factory()
    route = service.create_route(
        "Selected simulation", sink["url"], sources=["one"], events=["activated"], start_after=0
    )
    activate(store, "one")
    activate(store, "two")
    returned(store, "one")
    service.enable_route(route["id"], True)
    await service.cycle()
    assert len(sink["requests"]) == 1
    assert json.loads(sink["requests"][0]["body"])["event"]["source"] == "one"
    assert service.routes()[0]["cursor"] == 3


async def test_http_backoff_is_bounded_and_preserves_per_route_order_and_idempotency(factory, sink):
    clock = Clock()
    service, store = factory(clock=clock, max_attempts=2, base_backoff_seconds=2)
    route = service.create_route("Retry receipt", sink["url"], start_after=0)
    activate(store)
    returned(store)
    sink["behaviors"].extend([503, 503, 204, 204])
    service.enable_route(route["id"], True)
    assert (await service.cycle())["retry_wait"] == 1
    assert [row["state"] for row in rows(service)] == ["retry_wait", "queued"]
    assert (await service.cycle())["attempted"] == 0
    clock.advance(2)
    assert (await service.cycle())["failed"] == 1
    first = rows(service)[0]
    assert first["error"] == "attempt_limit_reached" and first["attempts"] == 2
    assert (await service.cycle())["attempted"] == 0
    service.retry(
        first["id"], "Receiver repaired; retry with the same idempotency key", actor="Test"
    )
    result = await service.cycle()
    assert result["delivered"] == 2
    receipts = sink["requests"]
    assert receipts[0]["body"] == receipts[1]["body"] == receipts[2]["body"]
    assert receipts[0]["headers"]["Idempotency-Key"] == receipts[2]["headers"]["Idempotency-Key"]
    assert [json.loads(row["body"])["event"]["sequence"] for row in receipts] == [1, 1, 1, 2]
    assert service.delivery(first["id"])["total_attempts"] == 3


async def test_ambiguous_receipt_blocks_later_events_until_explicit_operator_retry(factory, sink):
    service, store = factory()
    route = service.create_route("Ambiguous receipt", sink["url"], start_after=0)
    activate(store)
    returned(store)
    sink["behaviors"].append("drop")
    service.enable_route(route["id"], True)
    assert (await service.cycle())["uncertain"] == 1
    first = rows(service)[0]
    assert [row["state"] for row in rows(service)] == ["uncertain", "queued"]
    assert (await service.cycle())["attempted"] == 0
    service.retry(first["id"], "Reviewed receiver; duplicate delivery risk accepted")
    assert (await service.cycle())["delivered"] == 2
    assert sink["requests"][0]["body"] == sink["requests"][1]["body"]
    assert not store.alarms()[0]["acknowledged"]


async def test_operator_discard_releases_order_without_alarm_acknowledgement(factory, sink):
    service, store = factory()
    route = service.create_route("Discard receipt", sink["url"], start_after=0)
    activate(store)
    returned(store)
    sink["behaviors"].append(400)
    service.enable_route(route["id"], True)
    await service.cycle()
    first = rows(service)[0]
    assert first["state"] == "failed"
    discarded = service.discard(first["id"], "Receiver rejected; retained the local alarm evidence")
    assert discarded["state"] == "discarded"
    assert (await service.cycle())["delivered"] == 1
    assert not store.alarms()[0]["acknowledged"]
    with pytest.raises(ValueError, match="state"):
        service.retry(first["id"], "Cannot retry an explicitly discarded item")


async def test_route_configuration_persists_but_enablement_does_not_resume_after_restart(
    factory, sink
):
    clock = Clock()
    service, store = factory(clock=clock)
    route = service.create_route("Persistent route", sink["url"], start_after=0)
    activate(store)
    service.enable_route(route["id"], True)
    sink["behaviors"].append(503)
    await service.cycle()
    directory = service.directory
    await service.close()
    reopened, _ = factory(directory=directory, observations=store, clock=clock)
    assert reopened.routes()[0]["name"] == "Persistent route"
    assert not reopened.routes()[0]["enabled"]
    clock.advance(10)
    assert (await reopened.cycle())["attempted"] == 0
    assert len(sink["requests"]) == 1
    reopened.enable_route(route["id"], True)
    assert (await reopened.cycle())["delivered"] == 1


async def test_retention_gaps_are_visible_and_never_sent_as_fabricated_alarm_events(
    factory, sink, tmp_path
):
    store = ObservabilityStore(tmp_path / "bounded-events", max_alarm_events=2)
    for second in range(4):
        store.record_scan("sim", BASE + timedelta(seconds=second), {}, {"fault": second % 2 == 0})
    service, _ = factory(observations=store)
    route = service.create_route("Retained history", sink["url"], start_after=0)
    service.enable_route(route["id"], True)
    result = await service.cycle()
    assert result["gaps"] == 1 and result["delivered"] == 2
    history = rows(service)
    assert [row["kind"] for row in history] == ["retention_gap", "event", "event"]
    gap = service.delivery(history[0]["id"])
    assert gap["state"] == "gap"
    assert gap["payload"]["missing_from"] == 1 and gap["payload"]["missing_through"] == 2
    assert [json.loads(row["body"])["event"]["sequence"] for row in sink["requests"]] == [3, 4]
    assert service.status()["counts"]["gap"] == 1


async def test_pruned_all_source_events_still_produce_gap_from_original_highwater(factory, sink):
    service, store = factory()
    activate(store)
    returned(store)
    store.prune(before=BASE + timedelta(days=1))
    assert not store.alarm_events()
    route = service.create_route("Missing history", sink["url"], start_after=0)
    service.enable_route(route["id"], True)
    assert (await service.cycle())["gaps"] == 1
    assert service.status()["latest_alarm_event_sequence"] == 2
    assert service.routes()[0]["cursor"] == 2
    assert not sink["requests"]


async def test_capacity_never_advances_past_unqueued_event_and_history_pruning_is_explicit(
    factory, sink
):
    service, store = factory(max_deliveries=1)
    route = service.create_route("Capacity", sink["url"], start_after=0)
    activate(store)
    returned(store)
    service.enable_route(route["id"], True)
    result = await service.cycle()
    assert result["capacity_blocked"] == 1 and result["delivered"] == 1
    assert service.routes()[0]["cursor"] == 1
    assert (await service.cycle())["attempted"] == 0
    assert service.routes()[0]["cursor"] == 1
    first = rows(service)[0]
    assert service.prune_completed(first["id"])["removed"] == 1
    assert service.status()["history_pruned"] == 1
    assert (await service.cycle())["delivered"] == 1
    assert service.routes()[0]["cursor"] == 2
    assert [json.loads(row["body"])["event"]["sequence"] for row in sink["requests"]] == [1, 2]


async def test_environment_bearer_is_read_at_attempt_and_never_persisted_or_logged(
    factory, sink, monkeypatch, caplog
):
    service, store = factory()
    route = service.create_route(
        "Environment bearer", sink["url"], bearer_env="BMS_TEST_WEBHOOK_BEARER", start_after=0
    )
    activate(store)
    service.enable_route(route["id"], True)
    assert (await service.cycle())["failed"] == 1
    assert not sink["requests"]
    secret = "test.secret-value-for-loopback-only"
    monkeypatch.setenv("BMS_TEST_WEBHOOK_BEARER", secret)
    first = rows(service)[0]
    service.retry(first["id"], "Environment secret now configured")
    assert (await service.cycle())["delivered"] == 1
    assert sink["requests"][0]["headers"]["Authorization"] == "Bearer " + secret
    assert secret.encode() not in service.db.read_bytes()
    assert (
        secret
        not in json.dumps(service.status())
        + json.dumps(service.routes())
        + json.dumps(service.delivery(first["id"]))
        + caplog.text
    )


async def test_http_transport_does_not_log_full_endpoint_url_or_authentication(
    factory, sink, caplog
):
    caplog.set_level("INFO", logger="httpx")
    service, store = factory()
    route = service.create_route(
        "Endpoint privacy",
        sink["url"] + "/private-path-token?token=private-query-token",
        start_after=0,
    )
    activate(store)
    service.enable_route(route["id"], True)
    assert (await service.cycle())["delivered"] == 1
    assert "private-path-token" not in caplog.text
    assert "private-query-token" not in caplog.text
    if os.name != "nt":
        assert stat.S_IMODE(service.directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(service.db.stat().st_mode) == 0o600
        assert (
            stat.S_IMODE((service.directory / "notification_outbox.lock").stat().st_mode) == 0o600
        )


async def test_environment_url_is_resolved_only_at_attempt_and_never_persisted_returned_or_logged(
    factory, sink, monkeypatch, caplog
):
    caplog.set_level("INFO", logger="httpx")
    service, store = factory()
    route = service.create_route("Secret endpoint", url_env="BMS_TEST_WEBHOOK_URL", start_after=0)
    assert route["url"] is None and route["url_env"] == "BMS_TEST_WEBHOOK_URL"
    activate(store)
    service.enable_route(route["id"], True)
    assert (await service.cycle())["failed"] == 1
    assert not sink["requests"]
    endpoint = sink["url"] + "/private-environment-path?token=private-environment-query"
    monkeypatch.setenv("BMS_TEST_WEBHOOK_URL", endpoint)
    first = rows(service)[0]
    service.retry(first["id"], "Environment endpoint configured")
    assert (await service.cycle())["delivered"] == 1
    assert (
        "/private-environment-path?token=private-environment-query"
        in sink["requests"][0]["request"]
    )
    assert endpoint.encode() not in service.db.read_bytes()
    assert "private-environment-path" not in service.db.read_bytes().decode("latin-1")
    assert (
        "private-environment-query"
        not in json.dumps(service.routes())
        + json.dumps(service.delivery(first["id"]))
        + caplog.text
    )


async def test_receipt_persistence_failure_reconciles_to_uncertain_after_storage_recovers(
    factory, sink
):
    service, store = factory()
    route = service.create_route("Receipt storage fault", sink["url"], start_after=0)
    activate(store)
    service.enable_route(route["id"], True)
    with service.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_receipt BEFORE UPDATE OF state ON notification_deliveries WHEN NEW.state='delivered' BEGIN SELECT RAISE(ABORT,'simulated receipt storage fault'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="storage fault"):
        await service.cycle()
    first = rows(service)[0]
    assert first["state"] == "sending" and len(sink["requests"]) == 1
    with service.connect() as db:
        db.execute("DROP TRIGGER fail_receipt")
    assert (await service.cycle())["attempted"] == 0
    recovered = service.delivery(first["id"])
    assert recovered["state"] == "uncertain"
    assert recovered["error"] == "abandoned_request_requires_review"
    assert len(sink["requests"]) == 1
    service.retry(first["id"], "Reviewed receipt storage fault; explicit duplicate-risk retry")
    assert (await service.cycle())["delivered"] == 1


@pytest.mark.parametrize(
    "options",
    [{}, {"url": "http://127.0.0.1:1", "url_env": "EXTRA"}, {"url_env": "not an env name"}],
)
async def test_exactly_one_fixed_or_environment_endpoint_is_required(factory, options):
    service, _ = factory()
    with pytest.raises(ValueError):
        service.create_route("Ambiguous endpoint", **options)


async def test_redirects_and_environment_proxy_settings_are_never_followed(
    factory, sink, monkeypatch
):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    service, store = factory()
    route = service.create_route("No redirect", sink["url"], start_after=0)
    activate(store)
    sink["behaviors"].append(302)
    service.enable_route(route["id"], True)
    assert (await service.cycle())["failed"] == 1
    assert len(sink["requests"]) == 1
    assert rows(service)[0]["last_http_status"] == 302


async def test_overall_timeout_and_cancelled_requests_are_uncertain(factory, sink):
    service, store = factory(timeout_seconds=0.05)
    route = service.create_route("Deadline", sink["url"], start_after=0)
    activate(store)
    sink["behaviors"].append("stall")
    service.enable_route(route["id"], True)
    assert (await service.cycle())["uncertain"] == 1
    first = rows(service)[0]
    service.retry(first["id"], "Explicit retry for cancellation test")
    sink["received"].clear()
    sink["behaviors"].append("stall")
    pending = asyncio.create_task(service.cycle())
    await asyncio.wait_for(sink["received"].wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert service.delivery(first["id"])["state"] == "uncertain"
    assert service.delivery(first["id"])["last_error"] == "request_cancelled_after_claim"


async def test_another_live_owner_cannot_relabel_or_send_inflight_delivery(factory, sink):
    service, store = factory()
    route = service.create_route("Exclusive owner", sink["url"], start_after=0)
    activate(store)
    sink["behaviors"].append("stall")
    service.enable_route(route["id"], True)
    pending = asyncio.create_task(service.cycle())
    await asyncio.wait_for(sink["received"].wait(), 1)
    with pytest.raises(ValueError, match="ownership unavailable"):
        NotificationOutbox(service.directory, store)
    assert rows(service)[0]["state"] == "sending"
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending


async def test_cross_process_owner_lock_and_crash_recovery_are_conservative(factory, tmp_path):
    service, store = factory()
    script = (
        "import sys,os; from bms_tool.observability import ObservabilityStore; "
        "from bms_tool.notification_outbox import NotificationOutbox; "
        "store=ObservabilityStore(sys.argv[2]); "
        "out=NotificationOutbox(sys.argv[1],store); "
        "out.connect().__enter__()"
    )
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "backend")}
    result = subprocess.run(
        [sys.executable, "-c", script, str(service.directory), str(store.directory)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode != 0 and "ownership unavailable" in result.stderr
    route = service.create_route("Interrupted process", "http://127.0.0.1:1", start_after=0)
    activate(store)
    # Stage one queued event without opening any socket.
    service._ingest(route, 10)
    first = rows(service)[0]
    await service.close()
    crash_script = (
        "import sys,os; from bms_tool.observability import ObservabilityStore; "
        "from bms_tool.notification_outbox import NotificationOutbox; "
        "out=NotificationOutbox(sys.argv[1],ObservabilityStore(sys.argv[2])); "
        "db=out.connect(); connection=db.__enter__(); "
        "connection.execute(\"UPDATE notification_deliveries SET state='sending',owner='crashed-owner'\"); "
        "connection.commit(); os._exit(0)"
    )
    subprocess.run(
        [sys.executable, "-c", crash_script, str(service.directory), str(store.directory)],
        env=environment,
        check=True,
        timeout=5,
    )
    reopened, _ = factory(directory=service.directory, observations=store)
    assert reopened.delivery(first["id"])["state"] == "uncertain"
    assert reopened.delivery(first["id"])["error"] == "process_interrupted_during_request"
    assert reopened.status()["active_routes"] == 0


async def test_payload_corruption_is_visible_and_refused_before_network_send(factory, sink):
    service, store = factory()
    route = service.create_route("Integrity", sink["url"], start_after=0)
    activate(store)
    service._ingest(route, 10)
    first = rows(service)[0]
    with service.connect() as db:
        db.execute(
            "UPDATE notification_deliveries SET payload='corrupted' WHERE id=?", (first["id"],)
        )
    assert not service.delivery(first["id"])["payload_integrity"]
    assert service.delivery(first["id"])["payload"] is None
    service.enable_route(route["id"], True)
    assert (await service.cycle())["attempted"] == 0
    assert rows(service)[0]["state"] == "failed"
    assert rows(service)[0]["error"] == "payload_integrity_mismatch"
    assert not sink["requests"]


async def test_concurrent_cycles_claim_each_event_once_and_history_is_cursor_paged(factory, sink):
    service, store = factory()
    route = service.create_route("Concurrent local dispatch", sink["url"], start_after=0)
    activate(store)
    returned(store)
    service.enable_route(route["id"], True)
    await asyncio.gather(service.cycle(), service.cycle())
    assert len(sink["requests"]) == 2
    first = service.deliveries(limit=1)
    assert first["total"] == 2 and first["next_after"] == first["rows"][0]["id"]
    second = service.deliveries(after=first["next_after"], limit=1)
    assert second["total"] == 2 and second["next_after"] is None
    assert first["rows"][0]["id"] < second["rows"][0]["id"]


async def test_route_definitions_are_immutable_copies_and_disable_stops_future_attempts(
    factory, sink
):
    service, store = factory()
    route = service.create_route(
        "Immutable", sink["url"], events=["activated", "returned"], start_after=0
    )
    route["url"] = "http://127.0.0.1:1"
    route["events"].clear()
    assert service.routes()[0]["url"] == sink["url"]
    assert service.routes()[0]["events"] == ["activated", "returned"]
    activate(store)
    returned(store)
    service.enable_route(route["id"], True)
    sink["behaviors"].append("stall")
    pending = asyncio.create_task(service.cycle())
    await asyncio.wait_for(sink["received"].wait(), 1)
    service.enable_route(route["id"], False)
    first = rows(service)[0]
    with pytest.raises(ValueError, match="state"):
        service.discard(first["id"], "In-flight requests cannot be recalled")
    sink["hold"].set()
    assert (await pending)["delivered"] == 1
    assert [row["state"] for row in rows(service)] == ["delivered", "queued"]
    assert (await service.cycle())["attempted"] == 0
    assert len(sink["requests"]) == 1


async def test_source_kind_is_bound_to_persisted_source_and_not_mutable_runtime_label(
    factory, sink
):
    service, store = factory()
    route = service.create_route("Bound source", sink["url"], start_after=0)
    activate(store)
    store.source_kind = "field"
    service.enable_route(route["id"], True)
    await service.cycle()
    assert json.loads(sink["requests"][0]["body"])["source_kind"] == "simulation"
    with store.connect() as db:
        db.execute("UPDATE observation_metadata SET value='field' WHERE key='source_kind'")
    with pytest.raises(ValueError, match="source_kind changed"):
        await service.cycle()


async def test_source_sequence_regression_records_gap_and_blocks_existing_route(factory, sink):
    service, store = factory()
    route = service.create_route("Regressed source", sink["url"], start_after=0)
    activate(store)
    returned(store)
    service.enable_route(route["id"], True)
    await service.cycle()
    with store.connect() as db:
        db.execute("DELETE FROM alarm_events")
        db.execute("UPDATE sqlite_sequence SET seq=0 WHERE name='alarm_events'")
    result = await service.cycle()
    assert result["gaps"] == 1 and result["attempted"] == 0
    assert service.routes()[0]["source_problem"] == "source_history_regressed"
    assert service.delivery(rows(service)[-1]["id"])["payload"]["previous_cursor"] == 2
    service.enable_route(route["id"], False)
    with pytest.raises(ValueError, match="regressed"):
        service.enable_route(route["id"], True)
    assert len(sink["requests"]) == 2


async def test_same_path_database_replacement_is_not_mistaken_for_original_event_stream(
    factory, sink, tmp_path
):
    service, store = factory()
    route = service.create_route("Original event stream", sink["url"], start_after=0)
    activate(store)
    service.enable_route(route["id"], True)
    await service.cycle()
    replacement = ObservabilityStore(tmp_path / "replacement-source")
    activate(replacement, "different")
    returned(replacement, "different")
    os.replace(replacement.db, store.db)
    with pytest.raises(ValueError, match="logical store identity changed"):
        await service.cycle()
    assert len(sink["requests"]) == 1
    status = service.status()
    assert status["latest_alarm_event_sequence"] is None
    assert "dispatch is blocked" in status["source_error"]
    assert status["counts"]["delivered"] == 1
    assert rows(service)[0]["state"] == "delivered"


async def test_portable_workspace_copy_preserves_logical_identity_and_restarts_routes_disabled(
    factory, sink, tmp_path
):
    service, store = factory()
    route = service.create_route("Portable local workspace", sink["url"], start_after=0)
    activate(store)
    service.enable_route(route["id"], True)
    await service.cycle()
    original_identity = store.identity()
    await service.close()
    copied_outbox = tmp_path / "relocated-workspace" / "notifications"
    copied_observations = tmp_path / "relocated-workspace" / "observations"
    shutil.copytree(service.directory, copied_outbox)
    shutil.copytree(store.directory, copied_observations)
    relocated_store = ObservabilityStore(copied_observations)
    assert relocated_store.identity() == original_identity
    reopened, _ = factory(directory=copied_outbox, observations=relocated_store)
    assert not reopened.routes()[0]["enabled"]
    returned(relocated_store)
    assert (await reopened.cycle())["attempted"] == 0
    reopened.enable_route(route["id"], True)
    assert (await reopened.cycle())["delivered"] == 1
    assert [json.loads(row["body"])["event"]["sequence"] for row in sink["requests"]] == [1, 2]


async def test_gap_capacity_does_not_hide_missing_history_or_advance_cursor(
    factory, sink, tmp_path
):
    store = ObservabilityStore(tmp_path / "tiny-history", max_alarm_events=1)
    service, _ = factory(observations=store, max_deliveries=1)
    route = service.create_route("Capacity gap", sink["url"], start_after=0)
    activate(store)
    returned(store)
    service.enable_route(route["id"], True)
    result = await service.cycle()
    assert result["gaps"] == result["capacity_blocked"] == 1
    assert result["attempted"] == 0
    assert service.routes()[0]["cursor"] == 1
    gap = rows(service)[0]
    service.prune_completed(gap["id"])
    assert (await service.cycle())["delivered"] == 1
    assert json.loads(sink["requests"][0]["body"])["event"]["sequence"] == 2


async def test_explicit_pruning_keeps_unresolved_delivery_and_cursor_evidence(factory, sink):
    service, store = factory()
    route = service.create_route("Keep uncertain", sink["url"], start_after=0)
    activate(store)
    sink["behaviors"].append("drop")
    service.enable_route(route["id"], True)
    await service.cycle()
    first = rows(service)[0]
    assert service.prune_completed(first["id"])["removed"] == 0
    assert rows(service)[0]["state"] == "uncertain"
    assert service.routes()[0]["cursor"] == 1


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/no",
        "ftp://127.0.0.1/a",
        "https://user:password@example.invalid/x",
        "https://example.invalid/#",
        "http://",
        "http://example.invalid:0",
        "http://example.invalid:99999",
        "http://example.invalid/has space",
        "http://example.invalid\\bad",
        "https://example.invalid/\n",
    ],
)
async def test_invalid_webhook_urls_are_rejected_before_persistence(factory, url):
    service, _ = factory()
    with pytest.raises(ValueError):
        service.create_route("Invalid", url)
    assert not service.routes()


@pytest.mark.parametrize(
    "options",
    [
        {"sources": "sim"},
        {"events": []},
        {"events": ["alarm"]},
        {"bearer_env": "Bearer secret"},
        {"bearer_env": "BAD-NAME"},
        {"start_after": True},
    ],
)
async def test_route_filter_secret_reference_and_cursor_validation(factory, options):
    service, _ = factory()
    with pytest.raises(ValueError):
        service.create_route("Invalid", "http://127.0.0.1:1", **options)


async def test_nonregular_database_and_ownership_lock_files_are_rejected(tmp_path):
    store = ObservabilityStore(tmp_path / "observations")
    directory = tmp_path / "unsafe-outbox"
    directory.mkdir()
    lock = directory / "notification_outbox.lock"
    lock.symlink_to(tmp_path / "missing-target")
    with pytest.raises(ValueError, match="ownership unavailable"):
        NotificationOutbox(directory, store)
    lock.unlink()
    os.mkfifo(lock)
    with pytest.raises(ValueError, match="ownership unavailable"):
        NotificationOutbox(directory, store)
    lock.unlink()
    (directory / "notification_outbox.sqlite3").symlink_to(tmp_path / "missing-database")
    with pytest.raises(ValueError, match="regular file"):
        NotificationOutbox(directory, store)
