"""Durable actual COV receipts, asynchronous loss accounting and recovery."""

import asyncio
import sqlite3
import threading

import pytest
from bacpypes3.basetypes import PropertyValue
from bacpypes3.constructeddata import Any
from bacpypes3.primitivedata import OctetString, Real
from bms_tool.cov_observations import CovObservations
from bms_tool.observability import ObservabilityStore

from .test_bacnet_cov import network as network
from .test_bacnet_cov import notification, send, wait_for
from .test_bacnet_cov_routed import routed_cov as routed_cov


def attach(service, path, *, max_samples=100000, max_sources=256, **options):
    store = ObservabilityStore(
        path / "field", source_kind="field", max_samples=max_samples, max_sources=max_sources
    )
    service.recorder = CovObservations(store, **options)
    return service.recorder


@pytest.mark.parametrize("routed", [False, True])
async def test_explicit_optin_real_notifications_share_field_trends_with_receipt_provenance(
    network, routed_cov, tmp_path, routed
):
    server, analog, _, service, config = network
    if routed:
        _, server, analog, _, service, config, _ = routed_cov
    recorder = attach(service, tmp_path / ("routed" if routed else "direct"))
    idle = await service.start(**config)
    await wait_for(lambda: service.jobs[idle["id"]]["received"] > 0)
    await service.stop(idle["id"])
    assert recorder.recordings() == [] and recorder.worker is None
    started = await service.start(**config, record_observations=True)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["recording"]["recorded"] >= 1)
    analog.presentValue = 30
    await wait_for(lambda: job["recording"]["recorded"] >= 2)
    await service.renew(started["id"])
    await service.stop(started["id"])
    await recorder.flush()
    source = job["recording"]["source"]
    rows = recorder.store.trends(source=source)
    assert rows[0]["value"] == 12.5 and rows[-1]["value"] == 30
    assert all(
        row["quality"] == "unknown"
        and row["clock_basis"] == "receipt"
        and row["source_clock"] is None
        and row["source_kind"] == "field"
        for row in rows
    )
    assert rows[0]["receipt_at"] == rows[0]["clock"]
    events = recorder.events(started["id"])
    receipts = [event for event in events if event["event"] == "notification"]
    assert receipts[0]["evidence"]["process_id"] == started["process_id"]
    assert receipts[0]["evidence"]["values"][0]["native_datatype"] == "Real"
    assert receipts[0]["evidence"]["route"]["router"] == config.get("router")
    assert events[-1]["event"] == "recording_ended"
    assert recorder.store.list_sources()[0]["provenance"]["acquisition_kind"] == "bacnet-cov"
    assert recorder.store.list_sources()[0]["ended"]
    await recorder.close()
    reopened = CovObservations(ObservabilityStore(recorder.store.directory, source_kind="field"))
    try:
        assert reopened.worker is None and reopened.states == {}
        assert reopened.store.trends(source=source) == rows
        assert reopened.recordings()[0]["source"] == source
        assert (
            reopened.recordings()[0]["metadata"]["source_store_id"]
            == reopened.store.identity()["store_id"]
        )
        reopened.store.retire_source(source)
        assert reopened.recordings() == [] and reopened.events(started["id"]) == []
        assert reopened.store.trends() == []
    finally:
        await reopened.close()


async def test_queue_overflow_and_discarded_packets_are_counted_without_blocking_udp_callbacks(
    network, tmp_path, monkeypatch
):
    server, _, _, service, config = network
    recorder = attach(service, tmp_path, queue_limit=1)
    started = await service.start(**config, confirmed=False, record_observations=True)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["received"] > 0)
    await recorder.flush()  # a one-slot queue may omit the initial publication
    await send(server, notification(job))
    await wait_for(lambda: job["recording"]["recorded"] > 0)
    original = recorder._write
    entered, release = threading.Event(), threading.Event()

    def held(state, event, evidence):
        if event == "notification":
            entered.set()
            assert release.wait(2)
        return original(state, event, evidence)

    monkeypatch.setattr(recorder, "_write", held)
    try:
        await send(server, notification(job))
        assert await asyncio.to_thread(entered.wait, 1)
        initial = job["received"]
        for _ in range(10):
            await send(server, notification(job))
        await send(server, notification(job, initiatingDeviceIdentifier=("device", 4190099)))
        await wait_for(lambda: job["received"] >= initial + 10 and job["ignored"] > 0)
        assert job["recording"]["dropped"] > 0 and recorder.queue.qsize() <= 1
    finally:
        release.set()
    await service.stop(started["id"])
    await recorder.flush()
    events = recorder.events(started["id"])
    assert any(row["event"] == "dropped" for row in events)
    assert any(row["event"] == "discarded" for row in events)
    saved = recorder.recordings()[0]
    assert saved["dropped"] == job["recording"]["dropped"] and saved["discarded"] > 0


async def test_storage_failure_stops_recording_not_ack_or_monitor_and_does_not_retry_lost_notification(
    network, tmp_path, monkeypatch
):
    server, _, _, service, config = network
    recorder = attach(service, tmp_path)
    original = recorder._write

    def broken(state, event, evidence):
        if event == "notification":
            raise sqlite3.OperationalError("authored storage failure")
        return original(state, event, evidence)

    monkeypatch.setattr(recorder, "_write", broken)
    started = await service.start(**config, record_observations=True)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["recording"]["fault"] and not server.asap.clientTransactions)
    assert job["active"] and not job["recording"]["active"]
    assert "storage failed" in job["recording"]["last_error"]
    assert recorder.store.trends() == []
    await service.stop(started["id"])
    await recorder.flush()
    assert recorder.recordings()[0]["state"] == "storage_failed"
    assert not any(row["event"] == "notification" for row in recorder.events(started["id"]))
    assert recorder.recordings()[0]["recorded"] == 0


async def test_native_opaque_nonfinite_array_index_priority_and_receipt_clock_evidence(
    network, tmp_path
):
    server, _, _, service, config = network
    recorder = attach(service, tmp_path)
    started = await service.start(**config, confirmed=False, record_observations=True)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["recording"]["recorded"] > 0)
    count = len(recorder.store.trends())
    values = [
        PropertyValue(
            propertyIdentifier=512,
            propertyArrayIndex=2,
            priority=8,
            value=Any(OctetString(b"\x01\x00")),
        ),
        PropertyValue(propertyIdentifier="present-value", value=Any(Real(float("nan")))),
    ]
    await send(server, notification(job, listOfValues=values))
    await wait_for(lambda: job["recording"]["recorded"] > 1)
    await recorder.flush()
    assert len(recorder.store.trends()) == count
    events = [row for row in recorder.events(started["id"]) if row["event"] == "notification"]
    raw = events[-1]["evidence"]["values"][0]
    assert (
        raw["array_index"] == 2 and raw["priority"] == 8 and raw["value"]["type"] == "bacnet-opaque"
    )
    assert events[-1]["source_clock"] is None and events[-1]["clock_basis"] == "receipt"


async def test_retention_eviction_and_restart_interruption_are_explicit(network, tmp_path):
    _, analog, _, service, config = network
    recorder = attach(service, tmp_path, max_samples=1, max_events=100)
    started = await service.start(**config, record_observations=True)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["recording"]["recorded"] > 0)
    analog.presentValue = 20
    await wait_for(lambda: job["recording"]["recorded"] > 1)
    await recorder.flush()
    assert len(recorder.store.trends()) == 1 and recorder.recordings()[0]["samples_evicted"] > 0
    # Simulate abrupt recorder task loss: a fresh process sees an open durable
    # marker, does not resume anything, and qualifies its unknown receipt tail.
    recorder.worker.cancel()
    await asyncio.gather(recorder.worker, return_exceptions=True)
    recorder.closed = True
    recorder.ownership.close()  # process exit releases the OS lock
    recorder.ownership = None
    service.recorder = None  # the simulated previous writer must remain dead
    reopened = CovObservations(
        ObservabilityStore(recorder.store.directory, source_kind="field"), max_events=3
    )
    try:
        assert reopened.worker is None and reopened.states == {}
        assert reopened.recordings()[0]["state"] == "interrupted"
        assert any(row["event"] == "interrupted" for row in reopened.events(started["id"]))
        assert reopened.store.list_sources()[0]["ended"]
        assert reopened.recordings()[0]["events_retained"] <= 3
        assert reopened.recordings()[0]["events_evicted"] > 0
    finally:
        await reopened.close()


async def test_cancelled_recording_admission_joins_thread_and_never_subscribes(
    network, tmp_path, monkeypatch
):
    server, _, _, service, config = network
    recorder = attach(service, tmp_path)
    original = recorder._begin
    entered, release = threading.Event(), threading.Event()

    def held(state, metadata):
        entered.set()
        assert release.wait(2)
        original(state, metadata)

    monkeypatch.setattr(recorder, "_begin", held)
    operation = asyncio.create_task(service.start(**config, record_observations=True))
    assert await asyncio.to_thread(entered.wait, 1)
    operation.cancel()
    await asyncio.sleep(0.01)
    assert not operation.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert not server._cov_detections and recorder.worker is None
    assert recorder.recordings()[0]["state"] == "ended"


async def test_another_reader_cannot_interrupt_live_writer_or_record_concurrently(
    network, tmp_path
):
    _, _, _, service, config = network
    recorder = attach(service, tmp_path)
    started = await service.start(**config, record_observations=True)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["recording"]["recorded"] > 0)
    await recorder.flush()
    reader = CovObservations(ObservabilityStore(recorder.store.directory, source_kind="field"))
    try:
        assert reader.recordings()[0]["state"] == "recording"
        assert reader.recordings()[0]["ended_at"] is None
        with pytest.raises(ValueError, match="ownership unavailable"):
            await reader.begin(dict(job, id="cov-another-monitor"))
        assert reader.worker is None
        await service.stop(started["id"])
        await recorder.close()
        second = await reader.begin(dict(job, id="cov-another-monitor"))
        reader.end(second, {"reason": "ownership test complete"})
        await reader.flush()
        assert reader.recordings()[0]["state"] == "ended"
    finally:
        await reader.close()


@pytest.mark.parametrize("routed", [False, True])
async def test_finite_expiry_records_no_automatic_renewal_and_remote_outcome(
    network, routed_cov, tmp_path, routed
):
    _, _, _, service, config = network
    if routed:
        _, _, _, _, service, config, _ = routed_cov
    recorder = attach(service, tmp_path)
    now = [10.0]
    service.clock = lambda: now[0]
    started = await service.start(**config, record_observations=True)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["recording"]["recorded"] > 0)
    now[0] = 30
    await wait_for(lambda: not job["active"])
    await recorder.flush()
    end = recorder.events(started["id"])[-1]
    assert end["event"] == "recording_ended" and end["evidence"]["state"] == "expired"
    assert "not independently read back" in end["evidence"]["remote_outcome"]
    assert recorder.recordings()[0]["state"] == "ended"
    assert not any(row["event"] == "renewed" for row in recorder.events(started["id"]))


async def test_received_fault_flags_duplicate_values_and_backwards_receipt_clock(
    network, tmp_path, monkeypatch
):
    from bacpypes3.basetypes import StatusFlags

    server, _, _, service, config = network
    recorder = attach(service, tmp_path)
    started = await service.start(**config, confirmed=False, record_observations=True)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["recording"]["recorded"] > 0)
    monkeypatch.setattr("bms_tool.bacnet_cov._utc", lambda: "2025-01-01T00:00:00.000000+00:00")
    values = [
        PropertyValue(propertyIdentifier="present-value", value=Any(Real(17))),
        PropertyValue(propertyIdentifier="status-flags", value=Any(StatusFlags([0, 1, 0, 0]))),
    ]
    await send(server, notification(job, listOfValues=values))
    await wait_for(lambda: job["recording"]["recorded"] >= 2)
    assert recorder.store.trends()[-1]["quality"] == "fault"
    duplicate = values + [PropertyValue(propertyIdentifier="present-value", value=Any(Real(18)))]
    await send(server, notification(job, listOfValues=duplicate))
    await wait_for(lambda: job["recording"]["recorded"] >= 3)
    await recorder.flush()
    assert len(recorder.store.trends()) == 2
    evidence = recorder.events(started["id"])
    assert sum(row["event"] == "receipt_clock_not_increasing" for row in evidence) == 2
    assert (
        len([row for row in evidence if row["event"] == "notification"][-1]["evidence"]["values"])
        == 3
    )


async def test_source_capacity_rejects_before_subscribe_without_stopping_existing_monitor(
    network, tmp_path
):
    server, analog, _, service, config = network
    recorder = attach(service, tmp_path, max_sources=1)
    first = await service.start(**config, record_observations=True)
    job = service.jobs[first["id"]]
    await wait_for(lambda: job["recording"]["recorded"] > 0)
    with pytest.raises(ValueError, match="source capacity"):
        await service.start(**config, record_observations=True)
    assert sum(len(item.cov_subscriptions) for item in server._cov_detections.values()) == 1
    assert len(recorder.recordings()) == 1 and job["active"]
    analog.presentValue = 19
    await wait_for(lambda: job["recording"]["recorded"] > 1)


async def test_cancelled_close_joins_writer_before_releasing_ownership(
    network, tmp_path, monkeypatch
):
    server, _, _, service, config = network
    recorder = attach(service, tmp_path)
    started = await service.start(**config, confirmed=False, record_observations=True)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["recording"]["recorded"] > 0)
    entered, release = threading.Event(), threading.Event()
    original = recorder._write

    def held(state, event, evidence):
        if event == "notification":
            entered.set()
            assert release.wait(2)
        return original(state, event, evidence)

    monkeypatch.setattr(recorder, "_write", held)
    await send(server, notification(job))
    assert await asyncio.to_thread(entered.wait, 1)
    closing = asyncio.create_task(recorder.close())
    await asyncio.sleep(0.01)
    closing.cancel()
    await asyncio.sleep(0.01)
    assert not closing.done() and recorder.ownership is not None
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert recorder.worker.done() and recorder.ownership is None
    assert recorder.recordings()[0]["state"] == "ended"
