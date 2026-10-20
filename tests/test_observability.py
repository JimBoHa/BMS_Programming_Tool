"""Durable observation evidence, independent of live controller interfaces."""

import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from bms_tool.observability import ObservabilityStore

BASE = datetime(2026, 1, 5, tzinfo=UTC)
SOURCE = "simulation/" + "program" * 15 + "/session-abc123"


def clock(second=0):
    return BASE + timedelta(seconds=second)


def test_logical_stream_identity_survives_restart_move_and_concurrent_legacy_migration(tmp_path):
    directory = tmp_path / "original"
    store = ObservabilityStore(directory)
    store.record_scan("portable", clock(), {"temperature": 72})
    original = store.identity()
    assert ObservabilityStore(directory).identity() == original
    copied = tmp_path / "copied"
    shutil.copytree(directory, copied)
    assert ObservabilityStore(copied).identity() == original
    assert ObservabilityStore(tmp_path / "new-stream").identity() != original
    with store.connect() as db:
        db.execute("DELETE FROM observation_metadata WHERE key='store_id'")
    with ThreadPoolExecutor(max_workers=4) as workers:
        identities = list(workers.map(lambda _: ObservabilityStore(directory).identity(), range(4)))
    assert identities[0] != original
    assert all(identity == identities[0] for identity in identities)
    assert ObservabilityStore(directory).trends(source="portable")[0]["value"] == 72


def test_samples_survive_restart_preserve_boolean_units_quality_and_scope(tmp_path):
    store = ObservabilityStore(tmp_path)
    result = store.record_scan(
        SOURCE,
        clock(),
        {"temperature": 72.5, "occupied": True},
        qualities={"temperature": "unreliable"},
        units={"temperature": "°F"},
    )
    assert result["source_kind"] == "simulation"
    assert result["samples"] == 2
    reopened = ObservabilityStore(tmp_path)
    samples = reopened.trends(source=SOURCE)
    assert [(r["signal"], r["value"]) for r in samples] == [
        ("temperature", 72.5),
        ("occupied", True),
    ]
    assert type(samples[1]["value"]) is bool
    assert samples[0]["quality"] == "unreliable"
    assert samples[0]["unit"] == "°F"
    assert samples[0]["clock"] == "2026-01-05T00:00:00.000000+00:00"
    assert all(row["source_kind"] == "simulation" for row in samples)
    assert reopened.status()["sources"] == 1


def test_duplicate_scan_is_idempotent_and_conflicts_or_old_scans_do_not_write(tmp_path):
    store = ObservabilityStore(tmp_path)
    store.record_scan("sim", clock(2), {"a": 1, "b": True}, {"fault": True})
    duplicate = store.record_scan("sim", clock(2), {"b": True, "a": 1}, {"fault": True})
    assert duplicate["duplicate"]
    assert duplicate["samples"] == 0
    before = store.status()
    for time, values in ((clock(2), {"a": 2, "b": True}), (clock(1), {"a": 1})):
        with pytest.raises(ValueError, match="Conflicting|Out-of-order"):
            store.record_scan("sim", time, values, {"fault": False})
    assert store.status() == before
    # The same absolute timestamp in a different timezone is still the same scan.
    assert store.record_scan(
        "sim", "2026-01-04T16:00:02-08:00", {"a": 1, "b": True}, {"fault": True}
    )["duplicate"]


def test_alarm_ack_return_and_reactivation_are_distinct_occurrences(tmp_path):
    store = ObservabilityStore(tmp_path)
    store.record_scan(
        "sim", clock(), {"temp": 90}, {"high": {"active": True, "message": "High zone"}}
    )
    first = store.alarms()[0]
    assert first["active"] and not first["acknowledged"]
    assert first["message"] == "High zone"
    store.record_scan("sim", clock(1), {"temp": 91}, {"high": True})
    # Stable active conditions do not flood the event log.
    assert len(store.alarm_events()) == 1
    ack = store.acknowledge(first["id"], "Investigating zone", actor="Jim")
    assert ack["active"] and ack["acknowledged"]
    assert ack["acknowledged_at"] == clock(1).isoformat(timespec="microseconds")
    assert store.acknowledge(first["id"], "Investigating zone", actor="Jim") == ack
    with pytest.raises(ValueError, match="already acknowledged"):
        store.acknowledge(first["id"], "Investigating zone", actor="Jim", clock=clock())
    with pytest.raises(ValueError, match="already acknowledged"):
        store.acknowledge(first["id"], "Changed explanation", actor="Jim")
    store.record_scan("sim", clock(2), {"temp": 70}, {"high": False})
    returned = store.alarms()[0]
    assert returned["state"] == "returned" and returned["acknowledged"]
    store.record_scan("sim", clock(3), {"temp": 95}, {"high": True})
    second = store.alarms()[0]
    assert second["id"] != first["id"]
    assert second["active"] and not second["acknowledged"]
    assert [r["event"] for r in store.alarm_events(alarm_id=first["id"])] == [
        "activated",
        "acknowledged",
        "returned",
    ]
    assert store.alarms(active=True, unacknowledged=True) == [second]
    assert store.alarms(active=False, unacknowledged=False) == [returned]


def test_returned_alarm_remains_unacknowledged_and_missing_conditions_are_unchanged(tmp_path):
    store = ObservabilityStore(tmp_path)
    store.record_scan("sim", clock(), {}, {"fault": True, "other": True})
    store.record_scan("sim", clock(1), {}, {"fault": False})
    other, fault = store.alarms()
    assert other["active"]
    assert not fault["active"] and not fault["acknowledged"]
    reopened = ObservabilityStore(tmp_path)
    assert reopened.acknowledge(fault["id"], "Reviewed after return")["acknowledged"]
    assert len(reopened.alarms(unacknowledged=True)) == 1
    assert len(reopened.alarm_events()) == 4


def test_queries_are_bounded_filtered_and_cursor_paged_in_ingestion_order(tmp_path):
    store = ObservabilityStore(tmp_path)
    for second in range(4):
        store.record_scan(
            "one", clock(second), {"a": second, "b": -second}, {"alarm": second % 2 == 0}
        )
        store.record_scan("two", clock(second), {"a": 10 + second})
    first = store.trends(source="one", signal="a", limit=2)
    second = store.trends(source="one", signal="a", after=first[-1]["sequence"], limit=2)
    assert [r["value"] for r in first + second] == [0, 1, 2, 3]
    assert [
        r["value"] for r in store.trends(source="one", signal="a", start=clock(1), end=clock(2))
    ] == [1, 2]
    events = store.alarm_events(source="one", start=clock(1), limit=2)
    assert [r["event"] for r in events] == ["returned", "activated"]
    assert store.alarm_events(after=events[-1]["sequence"])[0]["event"] == "returned"
    for kwargs in (
        {"limit": 0},
        {"limit": 1001},
        {"limit": True},
        {"after": -1},
        {"start": clock(2), "end": clock(1)},
    ):
        with pytest.raises(ValueError):
            store.trends(**kwargs)
    with pytest.raises(ValueError):
        store.alarms(active=1)
    with pytest.raises(ValueError):
        store.alarm_events(alarm_id=0)


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), "72", None, {}, [], 10**1000]
)
def test_invalid_sample_batch_never_partially_writes(tmp_path, value):
    store = ObservabilityStore(tmp_path)
    with pytest.raises(ValueError, match="finite"):
        store.record_scan("sim", clock(), {"valid": 1, "bad": value}, {"alarm": True})
    assert store.status()["samples"] == 0
    assert store.status()["sources"] == 0
    assert store.alarms() == []


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "bad\nname"},
        {"clock": datetime(2026, 1, 1)},
        {"clock": "not-a-clock"},
        {"values": {"": 1}},
        {"values": {"x": 1}, "qualities": {"missing": "good"}},
        {"qualities": {"x": "maybe"}},
        {"units": {"x": 9}},
        {"alarms": {"a": 1}},
        {"alarms": {"a": {"active": True, "extra": "unknown"}}},
        {"alarms": {"a": {"active": True, "message": ""}}},
        {"values": {}, "alarms": {}},
        {"values": []},
    ],
)
def test_invalid_metadata_rejected_before_any_commit(tmp_path, changes):
    store = ObservabilityStore(tmp_path)
    arguments = {"source": "sim", "clock": clock(), "values": {"x": 1}, "alarms": {"a": True}}
    arguments.update(changes)
    with pytest.raises(ValueError):
        store.record_scan(**arguments)
    assert store.status()["samples"] == store.status()["alarm_occurrences"] == 0


def test_retention_keeps_newest_samples_and_events_and_preserves_unresolved_state(tmp_path):
    store = ObservabilityStore(tmp_path, max_samples=3, max_alarm_events=2)
    for second in range(5):
        store.record_scan("sim", clock(second), {"x": second}, {"alarm": second % 2 == 0})
    assert [r["value"] for r in store.trends()] == [2, 3, 4]
    assert [r["event"] for r in store.alarm_events()] == ["returned", "activated"]
    assert len(store.alarms(unacknowledged=True)) == 3
    status = store.prune(before=clock(10))
    assert status["samples"] == status["alarm_events"] == 0
    assert status["alarm_occurrences"] == 3
    assert status["active_alarms"] == 1
    # Pruning history cannot make an old scan valid again.
    with pytest.raises(ValueError, match="Out-of-order"):
        store.record_scan("sim", clock(2), {"x": 2})


def test_occurrence_capacity_rolls_back_whole_scan_until_resolved(tmp_path):
    store = ObservabilityStore(tmp_path, max_alarm_occurrences=1)
    store.record_scan("sim", clock(), {"x": 1}, {"alarm": True})
    first = store.alarms()[0]
    store.record_scan("sim", clock(1), {"x": 2}, {"alarm": False})
    before = store.status()
    with pytest.raises(ValueError, match="capacity"):
        store.record_scan("sim", clock(2), {"x": 3}, {"alarm": True})
    assert store.status() == before
    assert not store.alarms()[0]["active"]
    store.acknowledge(first["id"], "Reviewed")
    # Retrying the same failed timestamp works, proving its clock marker rolled back.
    store.record_scan("sim", clock(2), {"x": 3}, {"alarm": True})
    assert len(store.alarms()) == 1
    assert store.alarms()[0]["id"] != first["id"]
    assert store.alarms()[0]["active"]


def test_source_and_condition_quotas_roll_back_entire_scan(tmp_path):
    store = ObservabilityStore(tmp_path, max_sources=1, max_conditions=1)
    store.record_scan("sim", clock(), {"x": 1}, {"a": True})
    before = store.status()
    with pytest.raises(ValueError, match="source capacity"):
        store.record_scan("other", clock(), {"x": 2})
    with pytest.raises(ValueError, match="condition capacity"):
        store.record_scan("sim", clock(1), {"x": 2}, {"a": False, "b": True})
    assert store.status() == before
    assert store.alarms()[0]["active"]


def test_ack_validation_does_not_corrupt_event_evidence(tmp_path):
    store = ObservabilityStore(tmp_path)
    store.record_scan("sim", clock(2), {}, {"a": True})
    alarm = store.alarms()[0]
    for kwargs in (
        {"note": ""},
        {"note": "Reviewed", "clock": clock(1)},
        {"note": "Reviewed", "clock": clock(3)},
        {"note": "Reviewed", "actor": ""},
    ):
        with pytest.raises(ValueError):
            store.acknowledge(alarm["id"], **kwargs)
    with pytest.raises(ValueError, match="not found"):
        store.acknowledge(999, "Reviewed")
    assert len(store.alarm_events()) == 1
    assert not store.alarms()[0]["acknowledged"]


def test_concurrent_identical_scan_is_committed_once(tmp_path):
    store = ObservabilityStore(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda _: store.record_scan("sim", clock(), {"x": 1}, {"a": True}), range(8)
            )
        )
    assert sum(not result["duplicate"] for result in results) == 1
    assert store.status()["samples"] == 1
    assert len(store.alarm_events()) == 1


def test_list_and_retire_sources_frees_capacity_only_after_alarm_resolution(tmp_path):
    store = ObservabilityStore(tmp_path, max_sources=1, max_conditions=1)
    store.record_scan("sim", clock(1), {"x": 1}, {"a": True})
    source = store.list_sources()[0]
    assert source == {
        "source": "sim",
        "source_kind": "simulation",
        "clock": clock(1).isoformat(timespec="microseconds"),
        "samples": 1,
        "alarm_occurrences": 1,
        "active_alarms": 1,
        "unacknowledged_alarms": 1,
        "ended": False,
        "ended_at": None,
        "ended_recorded_at": None,
        "ended_by": None,
        "ended_note": None,
        "ended_alarms": 0,
    }
    with pytest.raises(ValueError, match="Return and acknowledge"):
        store.retire_source("sim")
    store.record_scan("sim", clock(2), {"x": 2}, {"a": False})
    with pytest.raises(ValueError, match="Return and acknowledge"):
        store.retire_source("sim")
    store.acknowledge(store.alarms()[0]["id"], "Resolved and reviewed")
    result = store.retire_source("sim")
    assert result["retired"]
    assert result["removed"] == {
        "samples": 2,
        "alarm_events": 3,
        "conditions": 1,
        "alarm_occurrences": 1,
    }
    assert store.list_sources() == []
    assert (
        store.status()["samples"] == store.status()["sources"] == store.status()["conditions"] == 0
    )
    # Explicit retirement permits a fresh simulation at an earlier timestamp.
    store.record_scan("sim", clock(), {"x": 3}, {"new": True})
    assert store.list_sources()[0]["active_alarms"] == 1
    with pytest.raises(ValueError, match="not found"):
        store.retire_source("missing")


def test_acknowledged_active_alarm_still_prevents_retirement(tmp_path):
    store = ObservabilityStore(tmp_path)
    store.record_scan("sim", clock(), {}, {"a": True})
    store.acknowledge(store.alarms()[0]["id"], "Reviewed while active")
    with pytest.raises(ValueError, match="Return and acknowledge"):
        store.retire_source("sim")
    assert store.list_sources()[0]["active_alarms"] == 1
    assert store.list_sources()[0]["unacknowledged_alarms"] == 0


def test_invalid_unicode_and_unrepresentable_utc_clock_are_validation_errors(tmp_path):
    store = ObservabilityStore(tmp_path)
    for source, time in (("bad\ud800", clock()), ("sim", "0001-01-01T00:00:00+01:00")):
        with pytest.raises(ValueError):
            store.record_scan(source, time, {"x": 1})
    assert store.status()["sources"] == 0


def test_end_source_distinguishes_ended_active_alarms_from_normal_returns(tmp_path):
    store = ObservabilityStore(tmp_path)
    store.record_scan("sim", clock(), {"x": 90}, {"still_active": True, "returned": True})
    store.record_scan("sim", clock(1), {"x": 95}, {"still_active": True, "returned": False})
    samples = store.trends()
    ended = store.end_source("sim", "Editor session was reset", actor="Jim")
    assert ended["ended"] is True and ended["ended_alarms"] == 1
    assert ended["ended_at"] == clock(1).isoformat(timespec="microseconds")
    assert ended["ended_note"] == "Editor session was reset" and ended["ended_by"] == "Jim"
    assert ended["ended_recorded_at"]
    alarms = {row["signal"]: row for row in store.alarms()}
    active, returned = alarms["still_active"], alarms["returned"]
    assert active["state"] == "source-ended" and not active["active"]
    assert active["returned_at"] is None and active["ended_at"] == ended["ended_at"]
    assert not active["acknowledged"]
    assert returned["state"] == "returned" and returned["ended_at"] is None
    assert returned["returned_at"] == ended["ended_at"]
    event = store.alarm_events()[-1]
    assert (event["event"], event["actor"], event["note"]) == (
        "source-ended",
        "Jim",
        "Editor session was reset",
    )
    assert event["clock"] == ended["ended_at"]
    assert event["recorded_at"] == ended["ended_recorded_at"]
    assert store.trends() == samples
    assert store.status()["ended_sources"] == store.status()["ended_alarms"] == 1
    assert store.status()["active_alarms"] == store.status()["open_sources"] == 0
    assert store.status()["unacknowledged_alarms"] == 2
    with pytest.raises(ValueError, match="acknowledge"):
        store.retire_source("sim")
    reopened = ObservabilityStore(tmp_path)
    assert reopened.list_sources()[0]["ended"] is True
    assert reopened.alarms() == store.alarms()
    acknowledged = reopened.acknowledge(active["id"], "Reviewed after source ended")
    assert acknowledged["state"] == "source-ended" and acknowledged["acknowledged"]
    reopened.acknowledge(returned["id"], "Reviewed normal return")
    assert reopened.retire_source("sim")["retired"]
    assert reopened.status()["ended_sources"] == 0


def test_source_ending_is_idempotent_and_refuses_all_further_recording(tmp_path):
    store = ObservabilityStore(tmp_path)
    store.record_scan("sim", clock(), {"x": 1}, {"a": True})
    ended = store.end_source("sim", "Simulation finished")
    events = store.alarm_events()
    assert store.end_source("sim", "Simulation finished") == ended
    assert store.alarm_events() == events
    for note, actor in (("Different explanation", "operator"), ("Simulation finished", "Jim")):
        with pytest.raises(ValueError, match="already ended"):
            store.end_source("sim", note, actor=actor)
    for time in (clock(), clock(1)):
        with pytest.raises(ValueError, match="source has ended"):
            store.record_scan("sim", time, {"x": 1}, {"a": True})
    assert store.status()["samples"] == 1
    assert store.status()["alarm_events"] == 2


def test_source_with_no_active_alarms_can_end_without_inventing_an_alarm(tmp_path):
    store = ObservabilityStore(tmp_path)
    store.record_scan("sim", clock(), {"x": 70}, {"a": False})
    ended = store.end_source("sim", "Closed completed run")
    assert ended["ended_alarms"] == 0
    assert store.alarms() == store.alarm_events() == []
    assert store.list_sources()[0]["ended_note"] == "Closed completed run"
    assert store.retire_source("sim")["retired"]


def test_ending_already_acknowledged_active_alarm_does_not_remove_acknowledgement(tmp_path):
    store = ObservabilityStore(tmp_path)
    store.record_scan("sim", clock(), {}, {"a": True})
    alarm = store.alarms()[0]
    store.acknowledge(alarm["id"], "Previously reviewed")
    store.end_source("sim", "Session ended")
    ended_alarm = store.alarms()[0]
    assert ended_alarm["acknowledged"] and ended_alarm["state"] == "source-ended"
    assert ended_alarm["acknowledgement_note"] == "Previously reviewed"
    assert store.retire_source("sim")["retired"]


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "unknown"},
        {"source": "bad\nname"},
        {"note": ""},
        {"note": "   "},
        {"note": "x" * 1001},
        {"actor": ""},
        {"actor": "bad\nactor"},
        {"actor": 7},
    ],
)
def test_invalid_source_end_is_transactional(tmp_path, changes):
    store = ObservabilityStore(tmp_path)
    store.record_scan("sim", clock(), {"x": 1}, {"a": True})
    before = store.status(), store.alarms(), store.alarm_events(), store.list_sources()
    arguments = {"source": "sim", "note": "Finished", "actor": "operator"} | changes
    with pytest.raises(ValueError):
        store.end_source(**arguments)
    assert (store.status(), store.alarms(), store.alarm_events(), store.list_sources()) == before


def test_source_end_event_failure_rolls_back_every_condition_and_source_marker(
    tmp_path, monkeypatch
):
    store = ObservabilityStore(tmp_path)
    store.record_scan("sim", clock(), {"x": 1}, {"a": True, "b": True})
    before = store.status(), store.alarms(), store.alarm_events(), store.list_sources()
    original = store._event
    calls = 0

    def fail_second_event(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("Simulated event failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "_event", fail_second_event)
    with pytest.raises(sqlite3.OperationalError):
        store.end_source("sim", "Finished")
    assert (store.status(), store.alarms(), store.alarm_events(), store.list_sources()) == before
    monkeypatch.setattr(store, "_event", original)
    assert store.end_source("sim", "Finished")["ended_alarms"] == 2


def test_source_ending_obeys_event_bounds_without_losing_unacknowledged_occurrences(tmp_path):
    store = ObservabilityStore(tmp_path, max_samples=1, max_alarm_events=1, max_sources=1)
    store.record_scan("sim", clock(), {"x": 1}, {"a": True, "b": True})
    store.end_source("sim", "Finished")
    assert store.status()["samples"] == store.status()["alarm_events"] == 1
    assert store.status()["ended_alarms"] == store.status()["unacknowledged_alarms"] == 2
    assert [row["state"] for row in store.alarms()] == ["source-ended", "source-ended"]
    assert store.alarm_events()[0]["event"] == "source-ended"
    with pytest.raises(ValueError, match="source capacity"):
        store.record_scan("new", clock(), {"x": 2})
    store.prune(before=clock(10))
    assert len(store.alarms()) == 2 and store.list_sources()[0]["ended"]


def old_observation_database(directory):
    """Create the original schema without any source-ending columns."""
    timestamp = clock().isoformat(timespec="microseconds")
    with sqlite3.connect(directory / "observability.sqlite3") as db:
        db.execute(
            "CREATE TABLE observation_sources(source TEXT PRIMARY KEY,clock TEXT NOT NULL,digest TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO observation_sources VALUES(?,?,?)", ("legacy", timestamp, "old-digest")
        )
        db.execute("""
            CREATE TABLE alarm_occurrences(
                id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT NOT NULL,signal TEXT NOT NULL,
                message TEXT NOT NULL,active INTEGER NOT NULL,acknowledged INTEGER NOT NULL,
                activated_at TEXT NOT NULL,returned_at TEXT,acknowledged_at TEXT,acknowledged_by TEXT,
                acknowledgement_note TEXT,last_event_at TEXT NOT NULL,recorded_at TEXT NOT NULL
            )
        """)
        db.execute(
            "INSERT INTO alarm_occurrences VALUES(1,?,?,?,1,0,?,NULL,NULL,NULL,NULL,?,?)",
            ("legacy", "high", "Old alarm", timestamp, timestamp, timestamp),
        )
        original_source = db.execute("SELECT * FROM observation_sources").fetchone()
        original_alarm = db.execute("SELECT * FROM alarm_occurrences").fetchone()
    return original_source, original_alarm


def test_source_end_schema_migration_preserves_old_evidence_and_is_restart_safe(tmp_path):
    original_source, original_alarm = old_observation_database(tmp_path)
    store = ObservabilityStore(tmp_path)
    with sqlite3.connect(store.db) as db:
        assert (
            db.execute("SELECT source,clock,digest FROM observation_sources").fetchone()
            == original_source
        )
        assert db.execute("SELECT * FROM alarm_occurrences").fetchone() == (*original_alarm, None)
    assert store.list_sources()[0]["ended"] is False
    assert store.alarms()[0]["state"] == "active"
    ended = store.end_source("legacy", "Old session no longer exists")
    assert ended["ended_alarms"] == 1
    reopened = ObservabilityStore(tmp_path)
    assert reopened.end_source("legacy", "Old session no longer exists") == ended
    assert reopened.alarms()[0]["state"] == "source-ended"
    reopened.acknowledge(reopened.alarms()[0]["id"], "Reviewed imported observation")
    assert reopened.retire_source("legacy")["retired"]


def test_concurrent_source_end_schema_migration_runs_once(tmp_path):
    old_observation_database(tmp_path)
    barrier = Barrier(4)

    def initialize(_):
        barrier.wait(timeout=10)
        return ObservabilityStore(tmp_path).list_sources()[0]["ended"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(initialize, range(4))) == [False] * 4
    with sqlite3.connect(tmp_path / "observability.sqlite3") as db:
        assert [row[1] for row in db.execute("PRAGMA table_info(observation_sources)")].count(
            "ended"
        ) == 1
        assert [row[1] for row in db.execute("PRAGMA table_info(alarm_occurrences)")].count(
            "ended_at"
        ) == 1
