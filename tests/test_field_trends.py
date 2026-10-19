"""Real loopback BACnet acquisition plus explicit failure/lifecycle semantics."""

import asyncio
import copy
from datetime import UTC, datetime, timedelta

import pytest
from bacpypes3.local.binary import BinaryValueObjectCmd
from bms_tool.connections import Bacnet, _unicast
from bms_tool.field_trends import FieldTrends, FieldTrendStart
from bms_tool.observability import ObservabilityStore
from bms_tool.storage import Store

from .test_connections import application, free_udp, point

BASE = datetime(2026, 1, 5, tzinfo=UTC)


def definition(signal="temperature", instance=1, **changes):
    return {
        "signal": signal,
        "address": "127.0.0.1:49999",
        "object_id": f"analog-value,{instance}",
        **changes,
    }


class Clock:
    def __init__(self):
        self.now = BASE

    def __call__(self):
        self.now += timedelta(microseconds=1)
        return self.now


class Connector:
    """Injected read peer; it cannot connect, discover, write or reconnect."""

    def __init__(self, responder=None):
        self.app = object()
        self.config = {
            "local_address": "127.0.0.1:49998",
            "instance": 4190001,
            "router": None,
            "dnet": None,
        }
        self.connected = True
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.cancelled = 0
        self.responder = responder

    def status(self):
        return {"connected": self.connected, "config": copy.deepcopy(self.config), "commands": []}

    def require(self):
        if not self.connected:
            raise ValueError("Connect a BACnet interface first.")
        return self.app

    def target_address(self, address):
        return _unicast(address)

    async def read(self, address, object_id, property_id="present-value", array_index=None):
        self.calls.append((address, object_id, property_id, array_index))
        self.active += 1
        self.max_active = max(self.active, self.max_active)
        try:
            await asyncio.sleep(0)
            if self.responder:
                value = self.responder(address, object_id, property_id, array_index)
                if asyncio.iscoroutine(value):
                    value = await value
            else:
                value = {
                    "present-value": 72.5,
                    "reliability": 0,
                    "status-flags": [0, 0, 0, 0],
                    "out-of-service": False,
                }[property_id]
            if isinstance(value, Exception):
                raise value
            return {"value": value}
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1

    async def connect(self, *args, **kwargs):
        raise AssertionError("Field trend service must never open/reconnect an interface.")

    async def write_property(self, *args, **kwargs):
        raise AssertionError("Field trend service must never write a point.")


async def wait_until(predicate, timeout=2):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(wait(), timeout)


def job(service, id):
    return next(row for row in service.status()["jobs"] if row["id"] == id)


@pytest.mark.asyncio
async def test_real_bacnet_read_values_verified_quality_and_restart_persistence(
    tmp_path, monkeypatch
):
    server_port = free_udp()
    server = application(server_port, 4190010)
    analog = point()
    analog.reliability = "no-fault-detected"
    server.add_object(analog)
    server.add_object(
        BinaryValueObjectCmd(
            objectIdentifier=("binary-value", 2),
            objectName="Loopback occupancy",
            presentValue="active",
            outOfService=False,
            statusFlags=[0, 0, 0, 0],
            reliability="no-fault-detected",
        )
    )
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = FieldTrends(client, tmp_path, clock=Clock(), min_request_gap=0)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Acquisition cannot connect, discover or write.")

    monkeypatch.setattr(client, "connect", forbidden)
    monkeypatch.setattr(client, "discover", forbidden)
    monkeypatch.setattr(client, "apply_write", forbidden)
    try:
        started = await service.start(
            [
                definition(address=f"127.0.0.1:{server_port}", unit="degF"),
                definition(
                    "occupied",
                    address=f"127.0.0.1:{server_port}",
                    object_id="binary-value,2",
                    value_type="boolean",
                ),
            ],
            verify_quality=True,
        )
        await wait_until(lambda: job(service, started["id"])["samples"] == 2)
        stopped = await service.stop(started["id"])
        assert not stopped["running"] and stopped["state"] == "stopped"
        rows = service.store.trends(source=started["source"])
        assert [row["value"] for row in rows] == [12.5, True]
        assert type(rows[1]["value"]) is bool
        assert all(row["quality"] == "good" and row["source_kind"] == "field" for row in rows)
        assert rows[0]["unit"] == "degF"
        assert rows[0]["clock"] == "2026-01-05T00:00:00.000001+00:00"
        assert rows[0]["recorded_at"] > rows[0]["clock"]
        assert not client.commands and analog.presentValue == 12.5
        assert service.store.alarms() == [] and service.store.alarm_events() == []
        assert service.store.list_sources()[0]["ended"]
        restarted = FieldTrends(client, tmp_path)
        try:
            assert restarted.status()["jobs"] == [] and restarted.status()["running_jobs"] == 0
            assert not restarted.status()["auto_resume"]
            assert restarted.store.trends() == rows
            assert [row["event"] for row in restarted.events()] == ["started", "stopped"]
        finally:
            await restarted.close()
    finally:
        await service.close()
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_construction_is_idle_start_requires_existing_interface_and_close_does_not_connect(
    tmp_path,
):
    connector = Connector()
    connector.connected = False
    service = FieldTrends(connector, tmp_path)
    assert service.status()["jobs"] == [] and service.store.trends() == [] and connector.calls == []
    with pytest.raises(ValueError, match="Connect"):
        await service.start([definition()])
    assert service.events() == []
    await service.close()
    connector.connected = True
    with pytest.raises(ValueError, match="closed"):
        await service.start([definition()])
    assert connector.calls == []


@pytest.mark.asyncio
async def test_default_unknown_quality_records_only_actual_sample_and_selected_property(tmp_path):
    connector = Connector(lambda *args: 72.5)
    service = FieldTrends(connector, tmp_path, clock=Clock(), min_request_gap=0)
    try:
        started = await service.start(
            [definition(property_id="priority-array", array_index=16, unit="percent")]
        )
        await wait_until(lambda: job(service, started["id"])["samples"] == 1)
        row = service.store.trends()[0]
        assert row["value"] == 72.5 and row["quality"] == "unknown" and row["unit"] == "percent"
        assert connector.calls == [("127.0.0.1:49999", "analog-value,1", "priority-array", 16)]
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_invalid_numeric_values_create_durable_failures_without_zero_or_stale_samples(
    tmp_path,
):
    invalid = [None, float("nan"), float("inf"), "72", {}, [], True, 10**1000]
    connector = Connector(lambda address, obj, prop, index: invalid[int(obj.split(",")[1]) - 1])
    service = FieldTrends(connector, tmp_path, clock=Clock(), min_request_gap=0)
    started = await service.start([definition(f"bad{i}", i + 1) for i in range(len(invalid))])
    await wait_until(lambda: job(service, started["id"])["failures"] == len(invalid))
    await service.stop(started["id"])
    assert service.store.trends() == []
    events = service.events(source=started["source"])
    assert len([row for row in events if row["event"] == "read-failed"]) == len(invalid)
    assert all(row["error"] for row in events if row["event"] == "read-failed")
    restarted = FieldTrends(connector, tmp_path)
    try:
        assert restarted.events() == events and restarted.store.trends() == []
    finally:
        await service.close()
        await restarted.close()


@pytest.mark.asyncio
async def test_explicit_boolean_mapping_and_partial_read_failure(tmp_path):
    values = [False, True, 0, 1, "active", "inactive", 2, 0.0, "true"]
    connector = Connector(lambda address, obj, prop, index: values[int(obj.split(",")[1]) - 1])
    service = FieldTrends(connector, tmp_path, clock=Clock(), min_request_gap=0)
    try:
        started = await service.start(
            [definition(f"binary{i}", i + 1, value_type="boolean") for i in range(len(values))]
        )
        await wait_until(lambda: job(service, started["id"])["failures"] == 3)
        rows = service.store.trends()
        assert [row["value"] for row in rows] == [False, True, False, True, True, False]
        assert all(type(row["value"]) is bool and row["quality"] == "unknown" for row in rows)
        assert job(service, started["id"])["running"]
        assert service.store.alarms() == []
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_quality_verification_is_conservative_and_metadata_failures_keep_known_values_unknown(
    tmp_path,
):
    cases = [
        (0, [0, 0, 0, 0], False, "good"),
        ("no-fault-detected", [False] * 4, False, "good"),
        (5, [0] * 4, False, "unreliable"),
        (0, [0, 1, 0, 0], False, "fault"),
        (0, [0, 0, 1, 0], False, "unreliable"),
        (0, [1, 0, 0, 0], False, "unreliable"),
        (0, [0] * 4, True, "unreliable"),
        (None, [0] * 4, False, "unknown"),
        ("invented-reliability", [0] * 4, False, "unknown"),
        (0, [0, 0, 0], False, "unknown"),
        (0, [0, 0, "inactive", 0], False, "unknown"),
        (0, [0] * 4, None, "unknown"),
        (ValueError("unknown-property reliability"), [0] * 4, False, "unknown"),
    ]

    def respond(address, obj, prop, index):
        reliability, flags, out, _ = cases[int(obj.split(",")[1]) - 1]
        return {
            "present-value": 42.25,
            "reliability": reliability,
            "status-flags": flags,
            "out-of-service": out,
        }[prop]

    connector = Connector(respond)
    service = FieldTrends(connector, tmp_path, clock=Clock(), min_request_gap=0)
    try:
        started = await service.start(
            [definition(f"p{i}", i + 1) for i in range(len(cases))], verify_quality=True
        )
        await wait_until(lambda: job(service, started["id"])["samples"] == len(cases))
        rows = service.store.trends()
        assert [row["quality"] for row in rows] == [case[3] for case in cases]
        assert all(row["value"] == 42.25 for row in rows)
        errors = [row for row in service.events() if row["event"] == "quality-unavailable"]
        assert len(errors) == 6
        assert not service.store.alarms() and not service.store.alarm_events()
    finally:
        await service.close()


@pytest.mark.parametrize("change", ["config", "application", "stopped"])
@pytest.mark.asyncio
async def test_interface_change_during_read_discards_that_result_and_never_reconnects(
    tmp_path, change
):
    connector = Connector()

    def respond(*args):
        if change == "config":
            connector.config["local_address"] = "127.0.0.1:49997"
        elif change == "application":
            connector.app = object()
        else:
            connector.connected = False
        return 72.5

    connector.responder = respond
    service = FieldTrends(connector, tmp_path, min_request_gap=0)
    try:
        started = await service.start([definition(), definition("other", 2)])
        await wait_until(lambda: not job(service, started["id"])["running"])
        assert job(service, started["id"])["state"] == "fault"
        assert len(connector.calls) == 1 and not service.store.trends()
        assert any(row["event"] == "job-failed" for row in service.events())
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_interface_fault_during_interval_stops_promptly_preserves_and_ends_source(tmp_path):
    connector = Connector()
    service = FieldTrends(connector, tmp_path, min_request_gap=0)
    try:
        started = await service.start([definition()], interval_seconds=3600)
        await wait_until(lambda: job(service, started["id"])["samples"] == 1)
        connector.connected = False
        await wait_until(lambda: not job(service, started["id"])["running"], timeout=1)
        assert len(connector.calls) == 1 and len(service.store.trends()) == 1
        assert service.store.list_sources()[0]["ended"]
    finally:
        await service.close()


@pytest.mark.parametrize(
    "clock_values",
    [
        [datetime(2026, 1, 5)],
        [BASE + timedelta(seconds=1), BASE],
        [BASE, BASE],
    ],
)
@pytest.mark.asyncio
async def test_invalid_frozen_or_backward_clock_stops_without_inventing_timestamps(
    tmp_path, clock_values
):
    times = iter(clock_values)
    connector = Connector()
    service = FieldTrends(connector, tmp_path, clock=lambda: next(times), min_request_gap=0)
    try:
        started = await service.start([definition(), definition("second", 2)])
        await wait_until(lambda: not job(service, started["id"])["running"])
        assert job(service, started["id"])["state"] == "fault"
        rows = service.store.trends()
        assert len(rows) == (0 if len(clock_values) == 1 else 1)
        if rows:
            assert rows[0]["clock"] == clock_values[0].isoformat(timespec="microseconds")
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_immediate_stop_before_task_runs_is_complete_and_retains_events(tmp_path):
    connector = Connector()
    service = FieldTrends(connector, tmp_path)
    started = await service.start([definition()])
    stopped = await service.stop(started["id"])
    assert stopped["state"] == "stopped" and not stopped["running"] and stopped["stopped_at"]
    assert connector.calls == []
    assert [row["event"] for row in service.events()] == ["started", "stopped"]
    assert await service.stop(started["id"]) == stopped
    await service.close()


@pytest.mark.asyncio
async def test_stop_cancels_inflight_read_and_timeout_keeps_other_point_values(tmp_path):
    entered = asyncio.Event()

    async def block(*args):
        entered.set()
        await asyncio.Event().wait()

    connector = Connector(block)
    service = FieldTrends(connector, tmp_path, min_request_gap=0)
    started = await service.start([definition()])
    await asyncio.wait_for(entered.wait(), 1)
    stopped = await asyncio.wait_for(service.stop(started["id"]), 1)
    assert not stopped["running"] and connector.cancelled == 1 and not service.store.trends()
    await service.close()

    async def selective(address, obj, prop, index):
        if obj == "analog-value,1":
            await asyncio.Event().wait()
        return 12.5

    timeout = FieldTrends(
        Connector(selective), tmp_path / "timeout", request_timeout=0.02, min_request_gap=0
    )
    try:
        started = await timeout.start([definition(), definition("second", 2)])
        await wait_until(lambda: job(timeout, started["id"])["samples"] == 1)
        assert timeout.store.trends()[0]["signal"] == "second"
        assert job(timeout, started["id"])["failures"] == 1
        assert (
            "TimeoutError"
            in next(row for row in timeout.events() if row["event"] == "read-failed")["error"]
        )
    finally:
        await timeout.close()


@pytest.mark.asyncio
async def test_all_jobs_share_one_sequential_read_lane(tmp_path):
    async def respond(*args):
        await asyncio.sleep(0.01)
        return 1.0

    connector = Connector(respond)
    service = FieldTrends(connector, tmp_path, clock=Clock(), min_request_gap=0)
    try:
        first = await service.start([definition(), definition("two", 2)])
        second = await service.start([definition("three", 3), definition("four", 4)])
        await wait_until(
            lambda: (
                job(service, first["id"])["samples"] == 2
                and job(service, second["id"])["samples"] == 2
            )
        )
        assert connector.max_active == 1
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_job_and_point_capacity_and_retained_definitions_are_bounded(tmp_path):
    service = FieldTrends(Connector(), tmp_path)
    try:
        for _ in range(8):
            await service.start([definition()])
        with pytest.raises(ValueError, match="eight"):
            await service.start([definition()])
    finally:
        await service.close()
    points = FieldTrends(Connector(), tmp_path / "points")
    try:
        for _ in range(4):
            await points.start([definition(f"p{i}", i + 1) for i in range(32)])
        with pytest.raises(ValueError, match="128"):
            await points.start([definition()])
    finally:
        await points.close()
    retained = FieldTrends(Connector(), tmp_path / "retained")
    try:
        for _ in range(34):
            started = await retained.start([definition()])
            await retained.stop(started["id"])
        assert len(retained.status()["jobs"]) == 32
    finally:
        await retained.close()


@pytest.mark.asyncio
async def test_audit_failure_cannot_prevent_stop_or_shutdown_of_all_jobs(tmp_path):
    class Audit:
        fail = False

        def record(self, *args):
            if self.fail:
                raise OSError("audit disk unavailable")

    audit = Audit()
    connector = Connector()
    service = FieldTrends(connector, tmp_path, audit_store=audit, min_request_gap=0)
    first = await service.start([definition()])
    second = await service.start([definition()])
    await wait_until(
        lambda: (
            job(service, first["id"])["samples"] == 1 and job(service, second["id"])["samples"] == 1
        )
    )
    audit.fail = True
    await service.close()
    assert service.status()["running_jobs"] == 0
    assert all(
        row["stopped_at"] and "audit" in row["last_error"].lower()
        for row in service.status()["jobs"]
    )
    assert all(row["ended"] for row in service.store.list_sources())


@pytest.mark.asyncio
async def test_storage_failure_is_visible_without_false_success_and_event_failure_stops_job(
    tmp_path, monkeypatch
):
    service = FieldTrends(Connector(), tmp_path, min_request_gap=0)
    monkeypatch.setattr(
        service.store,
        "record_scan",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("sample disk failure")),
    )
    try:
        started = await service.start([definition()])
        await wait_until(lambda: not job(service, started["id"])["running"])
        assert job(service, started["id"])["samples"] == 0 and service.store.trends() == []
        assert job(service, started["id"])["state"] == "fault"
        assert any("sample disk failure" in row["error"] for row in service.events())
    finally:
        await service.close()

    broken = FieldTrends(Connector(lambda *args: None), tmp_path / "broken", min_request_gap=0)
    original = broken._event

    def fail_event(job, event, **kwargs):
        if event in ("read-failed", "job-failed"):
            raise OSError("failure event disk unavailable")
        return original(job, event, **kwargs)

    monkeypatch.setattr(broken, "_event", fail_event)
    try:
        started = await broken.start([definition()])
        await wait_until(lambda: not job(broken, started["id"])["running"])
        assert job(broken, started["id"])["state"] == "fault"
        assert "could not be stored" in job(broken, started["id"])["last_error"]
    finally:
        await broken.close()


@pytest.mark.parametrize(
    "change",
    [
        {"points": []},
        {"points": [definition(), definition()]},
        {"interval_seconds": 4},
        {"interval_seconds": 3601},
        {"interval_seconds": True},
        {"verify_quality": "yes"},
        {"name": "line\nbreak"},
        {"points": [definition(object_id="invalid")]},
        {"points": [definition(property_id="invented-property")]},
        {"points": [definition(array_index=True)]},
        {"points": [definition(signal="bad/signal")]},
    ],
)
def test_start_model_bounds_and_types(change):
    with pytest.raises(ValueError):
        FieldTrendStart.model_validate({"points": [definition()], **change})


def test_field_store_source_kind_and_simulation_directory_remain_distinct(tmp_path):
    simulation = ObservabilityStore(tmp_path)
    simulation.record_scan("simulation/test", BASE, {"x": 1}, {"alarm": True})
    service = FieldTrends(Connector(), tmp_path)
    service.store.record_scan("field/test", BASE, {"x": 2}, qualities={"x": "unknown"})
    assert simulation.status()["source_kind"] == "simulation"
    assert simulation.trends()[0]["value"] == 1
    assert service.store.status()["source_kind"] == "field"
    assert service.store.list_sources()[0]["source_kind"] == "field"
    assert service.store.trends()[0]["source_kind"] == "field"
    assert service.store.alarms() == []
    with pytest.raises(ValueError, match="source_kind"):
        ObservabilityStore(tmp_path / "invalid", source_kind="unlabeled")
    for kwargs in ({"after": -1}, {"limit": True}, {"limit": 1001}, {"source": ""}):
        with pytest.raises(ValueError):
            service.events(**kwargs)


def test_persisted_source_kind_prevents_relabeling_and_legacy_evidence_migrates_as_simulation(
    tmp_path,
):
    simulation = ObservabilityStore(tmp_path / "simulation")
    simulation.record_scan("legacy", BASE, {"temperature": 72.5})
    with pytest.raises(ValueError, match="source_kind"):
        ObservabilityStore(tmp_path / "simulation", source_kind="field")
    assert ObservabilityStore(tmp_path / "simulation").trends()[0]["source_kind"] == "simulation"
    field = ObservabilityStore(tmp_path / "field", source_kind="field")
    with pytest.raises(ValueError, match="source_kind"):
        ObservabilityStore(tmp_path / "field")
    field.record_scan(
        "field/test", BASE, {"temperature": 12.5}, qualities={"temperature": "unknown"}
    )
    assert (
        ObservabilityStore(tmp_path / "field", source_kind="field").trends()[0]["source_kind"]
        == "field"
    )

    # Recreate the pre-source-kind schema state without altering its evidence.
    with simulation.connect() as db:
        db.execute("DROP TABLE observation_metadata")
    with pytest.raises(ValueError, match="legacy simulation"):
        ObservabilityStore(tmp_path / "simulation", source_kind="field")
    migrated = ObservabilityStore(tmp_path / "simulation")
    assert migrated.trends() == simulation.trends()
    with migrated.connect() as db:
        assert (
            db.execute("SELECT value FROM observation_metadata WHERE key='source_kind'").fetchone()[
                0
            ]
            == "simulation"
        )

    # A truly empty legacy database can be assigned field scope once.
    empty = ObservabilityStore(tmp_path / "empty")
    with empty.connect() as db:
        db.execute("DROP TABLE observation_metadata")
    migrated_field = ObservabilityStore(tmp_path / "empty", source_kind="field")
    assert migrated_field.status()["source_kind"] == "field"
    with pytest.raises(ValueError, match="source_kind"):
        ObservabilityStore(tmp_path / "empty")


@pytest.mark.asyncio
async def test_retirement_refuses_active_unknown_and_open_sources_then_explicitly_deletes_ended_data(
    tmp_path,
):
    service = FieldTrends(Connector(), tmp_path, clock=Clock(), min_request_gap=0)
    try:
        started = await service.start([definition()])
        await wait_until(lambda: job(service, started["id"])["samples"] == 1)
        with pytest.raises(ValueError, match="Stop"):
            await service.retire_source(started["source"])
        with pytest.raises(ValueError, match="not found"):
            await service.retire_source("field/unknown")
        service.store.record_scan("field/unended", BASE, {"test": 1}, qualities={"test": "unknown"})
        with pytest.raises(ValueError, match="End"):
            await service.retire_source("field/unended")
        assert len(service.store.trends(source=started["source"])) == 1
        await service.stop(started["id"])
        result = await service.retire_source(started["source"])
        assert result == {
            "source": started["source"],
            "source_kind": "field",
            "retired": True,
            "removed": {"samples": 1, "alarm_events": 0, "conditions": 0, "alarm_occurrences": 0},
        }
        assert not service.store.trends(source=started["source"])
        assert all(row["source"] != started["source"] for row in service.store.list_sources())
        events = service.events(source=started["source"])
        assert [row["event"] for row in events] == [
            "started",
            "stopped",
            "retirement-requested",
            "retired",
        ]
        assert events[-1]["detail"]["removed"]["samples"] == 1
        with pytest.raises(ValueError, match="not found"):
            await service.retire_source(started["source"])
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_retirement_after_restart_frees_bounded_source_capacity_without_automatic_deletion(
    tmp_path,
):
    connector = Connector()
    service = FieldTrends(connector, tmp_path, clock=Clock(), min_request_gap=0)
    started = await service.start([definition()])
    await wait_until(lambda: job(service, started["id"])["samples"] == 1)
    await service.close()
    restarted = FieldTrends(connector, tmp_path, clock=Clock(), min_request_gap=0)
    restarted.store.max_sources = 1
    try:
        blocked = await restarted.start([definition()])
        await wait_until(lambda: not job(restarted, blocked["id"])["running"])
        assert job(restarted, blocked["id"])["state"] == "fault"
        assert len(restarted.store.trends(source=started["source"])) == 1
        await restarted.retire_source(started["source"])
        successful = await restarted.start([definition()])
        await wait_until(lambda: job(restarted, successful["id"])["samples"] == 1)
        assert restarted.store.status()["sources"] == 1
        assert restarted.store.trends()[0]["source"] == successful["source"]
        assert any(row["event"] == "retired" for row in restarted.events(source=started["source"]))
    finally:
        await restarted.close()


@pytest.mark.parametrize(
    "failure_stage", ["audit-intent", "poll-intent", "audit-completion", "poll-completion"]
)
@pytest.mark.asyncio
async def test_retirement_intent_failures_preserve_data_and_completion_failures_report_committed_result(
    tmp_path, monkeypatch, failure_stage
):
    class Audit:
        operation = None

        def record(self, operation, detail):
            if operation == self.operation:
                raise OSError("injected audit failure")

    audit = Audit()
    service = FieldTrends(
        Connector(), tmp_path, audit_store=audit, clock=Clock(), min_request_gap=0
    )
    try:
        started = await service.start([definition()])
        await wait_until(lambda: job(service, started["id"])["samples"] == 1)
        await service.stop(started["id"])
        if failure_stage == "audit-intent":
            audit.operation = "field-trends.retirement.requested"
        elif failure_stage == "audit-completion":
            audit.operation = "field-trends.retired"
        else:
            original = service._source_event

            def fail_event(job_id, source, event, **kwargs):
                if event == (
                    "retirement-requested" if failure_stage == "poll-intent" else "retired"
                ):
                    raise OSError("injected poll-event failure")
                return original(job_id, source, event, **kwargs)

            monkeypatch.setattr(service, "_source_event", fail_event)
        if failure_stage.endswith("intent"):
            with pytest.raises(OSError):
                await service.retire_source(started["source"])
            assert len(service.store.trends(source=started["source"])) == 1
            assert service.store.list_sources()[0]["ended"]
        else:
            result = await service.retire_source(started["source"])
            assert result["retired"] and "committed" in result["audit_error"]
            assert service.store.trends() == [] and service.store.list_sources() == []
            restarted = FieldTrends(Connector(), tmp_path)
            try:
                assert not restarted.store.trends()
                assert any(row["event"] == "retirement-requested" for row in restarted.events())
            finally:
                await restarted.close()
    finally:
        await service.close()
