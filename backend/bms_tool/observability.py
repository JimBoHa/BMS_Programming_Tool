"""Durable, bounded simulation trends and alarm occurrences.

This service records observations; it never opens field connections or commands points.
Use a new source key after resetting a simulation clock. Scans are append-monotonic:
the identical latest scan is idempotent; conflicting or older scans are rejected.
Omitted alarm conditions retain their state. Every activation creates a fresh,
unacknowledged occurrence. Return and acknowledgement are independent events.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

QUALITIES = frozenset({"good", "unreliable", "stale", "fault", "unknown"})


def _text(value, name, maximum, *, empty=False):
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (not empty and not value.strip())
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError(f"{name} must be {'0' if empty else '1'}–{maximum} plain characters.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} must contain valid Unicode characters.") from exc
    return value


def _clock(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("A valid timezone-aware timestamp is required.") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A valid timezone-aware timestamp is required.")
    try:
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    except (ValueError, OverflowError) as exc:
        raise ValueError("Timestamp must be representable in UTC.") from exc


def _integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}.")
    return value


def _boolean_filter(value, name):
    if value is not None and type(value) is not bool:
        raise ValueError(f"{name} must be boolean or omitted.")
    return value


def _scalar(value):
    try:
        valid = type(value) is bool or (type(value) in (int, float) and math.isfinite(value))
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("Trend values must be finite numbers or booleans.")
    return value


class ObservabilityStore:
    """SQLite-backed observation store with bounded retention.

    Retention removes oldest samples/events. Only returned, acknowledged alarm
    occurrences can be evicted. Exhausting occurrence capacity rejects the whole
    scan, preserving unresolved alarms and avoiding partial observations.
    """

    def __init__(
        self,
        directory,
        *,
        max_samples=100_000,
        max_alarm_events=20_000,
        max_alarm_occurrences=10_000,
        max_sources=256,
        max_conditions=10_000,
        source_kind="simulation",
    ):
        if source_kind not in ("simulation", "field"):
            raise ValueError("source_kind must be simulation or field.")
        self.source_kind = source_kind
        self.max_samples = _integer(max_samples, "max_samples", 1, 1_000_000)
        self.max_alarm_events = _integer(max_alarm_events, "max_alarm_events", 1, 1_000_000)
        self.max_alarm_occurrences = _integer(
            max_alarm_occurrences, "max_alarm_occurrences", 1, 100_000
        )
        self.max_sources = _integer(max_sources, "max_sources", 1, 4096)
        self.max_conditions = _integer(max_conditions, "max_conditions", 1, 100_000)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = self.directory / "observability.sqlite3"
        with self.connect() as db:
            # Keep schema inspection and ALTER under the same cross-process lock.
            # executescript() would implicitly commit and race concurrent starts.
            db.execute("BEGIN IMMEDIATE")
            existing = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            db.execute(
                "CREATE TABLE IF NOT EXISTS observation_metadata("
                "key TEXT PRIMARY KEY,value TEXT NOT NULL)"
            )
            marker = db.execute(
                "SELECT value FROM observation_metadata WHERE key='source_kind'"
            ).fetchone()
            if marker is not None:
                if marker[0] != source_kind:
                    raise ValueError(
                        "Observation database source_kind differs from the requested kind. "
                        "Use separate simulation and field directories."
                    )
            else:
                # Older stores only supported simulation. An unmarked database
                # containing evidence must retain that meaning; a genuinely
                # empty/new store can be initialized for field acquisition.
                evidence = any(
                    table in existing
                    and db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None
                    for table in (
                        "observation_sources",
                        "trend_samples",
                        "alarm_occurrences",
                        "alarm_conditions",
                        "alarm_events",
                    )
                )
                stored_kind = "simulation" if evidence else source_kind
                if stored_kind != source_kind:
                    raise ValueError(
                        "An unmarked observation database contains legacy simulation evidence. "
                        "It cannot be reopened as field data."
                    )
                db.execute(
                    "INSERT INTO observation_metadata(key,value) VALUES('source_kind',?)",
                    (stored_kind,),
                )
            schema = """
                CREATE TABLE IF NOT EXISTS observation_sources(
                    source TEXT PRIMARY KEY, clock TEXT NOT NULL, digest TEXT NOT NULL,
                    ended INTEGER NOT NULL DEFAULT 0, ended_at TEXT, ended_recorded_at TEXT,
                    ended_by TEXT, ended_note TEXT, ended_alarms INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS trend_samples(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL, signal TEXT NOT NULL, clock TEXT NOT NULL,
                    value TEXT NOT NULL, value_type TEXT NOT NULL,
                    quality TEXT NOT NULL, unit TEXT NOT NULL, recorded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS trends_by_source_signal
                    ON trend_samples(source, signal, sequence);
                CREATE INDEX IF NOT EXISTS trends_by_clock ON trend_samples(clock);
                CREATE TABLE IF NOT EXISTS alarm_occurrences(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL, signal TEXT NOT NULL, message TEXT NOT NULL,
                    active INTEGER NOT NULL, acknowledged INTEGER NOT NULL,
                    activated_at TEXT NOT NULL, returned_at TEXT,
                    acknowledged_at TEXT, acknowledged_by TEXT, acknowledgement_note TEXT,
                    last_event_at TEXT NOT NULL, recorded_at TEXT NOT NULL, ended_at TEXT
                );
                CREATE INDEX IF NOT EXISTS alarms_by_source_signal
                    ON alarm_occurrences(source, signal, id);
                CREATE TABLE IF NOT EXISTS alarm_conditions(
                    source TEXT NOT NULL, signal TEXT NOT NULL,
                    active INTEGER NOT NULL, occurrence INTEGER,
                    PRIMARY KEY(source, signal),
                    FOREIGN KEY(occurrence) REFERENCES alarm_occurrences(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS alarm_events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    alarm_id INTEGER NOT NULL, source TEXT NOT NULL, signal TEXT NOT NULL,
                    event TEXT NOT NULL, clock TEXT NOT NULL, recorded_at TEXT NOT NULL,
                    actor TEXT NOT NULL, note TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_by_alarm ON alarm_events(alarm_id, sequence);
            """
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            for table, additions in {
                "observation_sources": {
                    "ended": "INTEGER NOT NULL DEFAULT 0",
                    "ended_at": "TEXT",
                    "ended_recorded_at": "TEXT",
                    "ended_by": "TEXT",
                    "ended_note": "TEXT",
                    "ended_alarms": "INTEGER NOT NULL DEFAULT 0",
                },
                "alarm_occurrences": {"ended_at": "TEXT"},
            }.items():
                columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                for name, definition in additions.items():
                    if name not in columns:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _event(db, alarm_id, source, signal, event, clock, recorded_at, actor="", note=""):
        db.execute(
            "INSERT INTO alarm_events(alarm_id,source,signal,event,clock,recorded_at,actor,note) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (alarm_id, source, signal, event, clock, recorded_at, actor, note),
        )

    def _retain(self, db):
        for table, maximum in (
            ("trend_samples", self.max_samples),
            ("alarm_events", self.max_alarm_events),
        ):
            db.execute(
                f"DELETE FROM {table} WHERE sequence < COALESCE("
                f"(SELECT sequence FROM {table} ORDER BY sequence DESC LIMIT 1 OFFSET ?),0)",
                (maximum - 1,),
            )
        excess = db.execute("SELECT COUNT(*) FROM alarm_occurrences").fetchone()[0]
        excess -= self.max_alarm_occurrences
        if excess > 0:
            db.execute(
                "DELETE FROM alarm_occurrences WHERE id IN ("
                "SELECT id FROM alarm_occurrences WHERE active=0 AND acknowledged=1 "
                "ORDER BY id LIMIT ?)",
                (excess,),
            )
            if db.execute("SELECT COUNT(*) FROM alarm_occurrences").fetchone()[0] > (
                self.max_alarm_occurrences
            ):
                raise ValueError(
                    "Alarm occurrence capacity reached. Return and acknowledge outstanding alarms."
                )

    def record_scan(self, source, clock, values, alarms=None, *, qualities=None, units=None):
        """Commit samples and alarm observations with this store's explicit source kind.

        alarms maps signal to bool or {"active": bool, "message": str}. qualities
        and units may name only sampled signals. Omitted alarms do not imply return.
        """
        source = _text(source, "source", 200)
        timestamp = _clock(clock)
        if not isinstance(values, dict) or len(values) > 4000:
            raise ValueError("values must be a dictionary of at most 4000 signals.")
        alarms = {} if alarms is None else alarms
        if not isinstance(alarms, dict) or len(alarms) > 256:
            raise ValueError("alarms must be a dictionary of at most 256 conditions.")
        if not values and not alarms:
            raise ValueError("A scan needs at least one sample or alarm observation.")
        qualities = {} if qualities is None else qualities
        units = {} if units is None else units
        for mapping, name in ((qualities, "qualities"), (units, "units")):
            if not isinstance(mapping, dict) or mapping.keys() - values.keys():
                raise ValueError(f"{name} must name only sampled signals.")
        samples = []
        for signal, value in values.items():
            signal = _text(signal, "signal", 200)
            value = _scalar(value)
            quality = qualities.get(signal, "good")
            if not isinstance(quality, str) or quality not in QUALITIES:
                raise ValueError("Unknown trend quality.")
            unit = _text(units.get(signal, ""), "unit", 80, empty=True)
            samples.append((signal, value, quality, unit))
        conditions = []
        for signal, condition in alarms.items():
            signal = _text(signal, "alarm signal", 200)
            if type(condition) is bool:
                active, message = condition, signal
            elif isinstance(condition, dict) and not condition.keys() - {"active", "message"}:
                active = condition.get("active")
                message = condition.get("message", signal)
            else:
                raise ValueError(
                    "Alarm conditions need a boolean active state and optional message."
                )
            if type(active) is not bool:
                raise ValueError("Alarm active state must be boolean.")
            message = _text(message, "alarm message", 500)
            conditions.append((signal, active, message))
        digest = hashlib.sha256(
            json.dumps(
                {"samples": sorted(samples), "alarms": sorted(conditions)},
                sort_keys=True,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        recorded_at = _clock(datetime.now(UTC))
        events = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT clock,digest,ended FROM observation_sources WHERE source=?", (source,)
            ).fetchone()
            if previous:
                if previous["ended"]:
                    raise ValueError("Simulation source has ended. Start a new recording source.")
                if timestamp < previous["clock"]:
                    raise ValueError(
                        "Out-of-order scan. Use a new source after resetting simulation."
                    )
                if timestamp == previous["clock"]:
                    if digest != previous["digest"]:
                        raise ValueError(
                            "Conflicting scan at an already recorded source timestamp."
                        )
                    return {
                        "source": source,
                        "source_kind": self.source_kind,
                        "duplicate": True,
                        "samples": 0,
                        "events": 0,
                        "clock": timestamp,
                    }
            elif db.execute("SELECT COUNT(*) FROM observation_sources").fetchone()[0] >= (
                self.max_sources
            ):
                raise ValueError("Simulation source capacity reached.")
            for signal, value, quality, unit in samples:
                db.execute(
                    "INSERT INTO trend_samples(source,signal,clock,value,value_type,quality,unit,"
                    "recorded_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        source,
                        signal,
                        timestamp,
                        json.dumps(value, allow_nan=False),
                        "boolean" if type(value) is bool else "number",
                        quality,
                        unit,
                        recorded_at,
                    ),
                )
            for signal, active, message in conditions:
                condition = db.execute(
                    "SELECT active,occurrence FROM alarm_conditions WHERE source=? AND signal=?",
                    (source, signal),
                ).fetchone()
                if active and (condition is None or not condition["active"]):
                    if (
                        condition is None
                        and db.execute("SELECT COUNT(*) FROM alarm_conditions").fetchone()[0]
                        >= self.max_conditions
                    ):
                        raise ValueError("Alarm condition capacity reached.")
                    result = db.execute(
                        "INSERT INTO alarm_occurrences(source,signal,message,active,acknowledged,"
                        "activated_at,last_event_at,recorded_at) VALUES(?,?,?,1,0,?,?,?)",
                        (source, signal, message, timestamp, timestamp, recorded_at),
                    )
                    alarm_id = result.lastrowid
                    db.execute(
                        "INSERT INTO alarm_conditions(source,signal,active,occurrence) VALUES(?,?,1,?) "
                        "ON CONFLICT(source,signal) DO UPDATE SET active=1,occurrence=excluded.occurrence",
                        (source, signal, alarm_id),
                    )
                    self._event(db, alarm_id, source, signal, "activated", timestamp, recorded_at)
                    events += 1
                elif not active and condition is not None and condition["active"]:
                    alarm_id = condition["occurrence"]
                    db.execute(
                        "UPDATE alarm_occurrences SET active=0,returned_at=?,last_event_at=? WHERE id=?",
                        (timestamp, timestamp, alarm_id),
                    )
                    db.execute(
                        "UPDATE alarm_conditions SET active=0 WHERE source=? AND signal=?",
                        (source, signal),
                    )
                    self._event(db, alarm_id, source, signal, "returned", timestamp, recorded_at)
                    events += 1
            db.execute(
                "INSERT INTO observation_sources(source,clock,digest) VALUES(?,?,?) "
                "ON CONFLICT(source) DO UPDATE SET clock=excluded.clock,digest=excluded.digest",
                (source, timestamp, digest),
            )
            self._retain(db)
        return {
            "source": source,
            "source_kind": self.source_kind,
            "duplicate": False,
            "samples": len(samples),
            "events": events,
            "clock": timestamp,
        }

    @staticmethod
    def _filters(source, signal, start, end, after, limit):
        clauses, arguments = [], []
        for name, value in (("source", source), ("signal", signal)):
            if value is not None:
                clauses.append(f"{name}=?")
                arguments.append(_text(value, name, 200))
        first = _clock(start) if start is not None else None
        last = _clock(end) if end is not None else None
        if first and last and first > last:
            raise ValueError("start must not follow end.")
        if first:
            clauses.append("clock>=?")
            arguments.append(first)
        if last:
            clauses.append("clock<=?")
            arguments.append(last)
        clauses.append("sequence>?")
        arguments.append(_integer(after, "after", 0, 2**63 - 1))
        arguments.append(_integer(limit, "limit", 1, 1000))
        return " AND ".join(clauses), arguments

    def trends(self, *, source=None, signal=None, start=None, end=None, after=0, limit=500):
        """Return ascending cursor-paged samples; date bounds are inclusive."""
        where, arguments = self._filters(source, signal, start, end, after, limit)
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM trend_samples WHERE {where} ORDER BY sequence LIMIT ?", arguments
            ).fetchall()
        result = []
        for row in rows:
            sample = dict(row)
            sample["value"] = json.loads(sample["value"])
            sample["source_kind"] = self.source_kind
            result.append(sample)
        return result

    def _alarm_row(self, row):
        alarm = dict(row)
        alarm["active"] = bool(alarm["active"])
        alarm["acknowledged"] = bool(alarm["acknowledged"])
        alarm["state"] = (
            "source-ended"
            if alarm["ended_at"] is not None
            else "active"
            if alarm["active"]
            else "returned"
        )
        alarm["source_kind"] = self.source_kind
        return alarm

    def alarms(self, *, source=None, signal=None, active=None, unacknowledged=None, limit=500):
        clauses, arguments = [], []
        for name, value in (("source", source), ("signal", signal)):
            if value is not None:
                clauses.append(f"{name}=?")
                arguments.append(_text(value, name, 200))
        if _boolean_filter(active, "active") is not None:
            clauses.append("active=?")
            arguments.append(int(active))
        if _boolean_filter(unacknowledged, "unacknowledged") is not None:
            clauses.append("acknowledged=?")
            arguments.append(int(not unacknowledged))
        arguments.append(_integer(limit, "limit", 1, 1000))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            return [
                self._alarm_row(row)
                for row in db.execute(
                    "SELECT * FROM alarm_occurrences" + where + " ORDER BY id DESC LIMIT ?",
                    arguments,
                )
            ]

    def alarm_events(
        self, *, source=None, signal=None, alarm_id=None, start=None, end=None, after=0, limit=500
    ):
        where, arguments = self._filters(source, signal, start, end, after, limit)
        if alarm_id is not None:
            where += " AND alarm_id=?"
            arguments.insert(-1, _integer(alarm_id, "alarm_id", 1, 2**63 - 1))
        with self.connect() as db:
            return [
                dict(row) | {"source_kind": self.source_kind}
                for row in db.execute(
                    f"SELECT * FROM alarm_events WHERE {where} ORDER BY sequence LIMIT ?", arguments
                )
            ]

    def acknowledge(self, alarm_id, note, *, actor="operator", clock=None):
        """Acknowledge an occurrence once, retaining operator and note.

        The default event timestamp is the source's latest simulation observation.
        An explicit timestamp must lie within the observed occurrence timeline.
        recorded_at independently preserves wall-clock receipt time. An identical
        repeated acknowledgement is idempotent; conflicting edits are rejected.
        """
        alarm_id = _integer(alarm_id, "alarm_id", 1, 2**63 - 1)
        note = _text(note, "acknowledgement note", 1000)
        actor = _text(actor, "actor", 120)
        timestamp = _clock(clock) if clock is not None else None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM alarm_occurrences WHERE id=?", (alarm_id,)).fetchone()
            if row is None:
                raise ValueError("Alarm occurrence not found.")
            if row["acknowledged"]:
                if (
                    row["acknowledged_by"] == actor
                    and row["acknowledgement_note"] == note
                    and (timestamp is None or timestamp == row["acknowledged_at"])
                ):
                    return self._alarm_row(row)
                raise ValueError("This alarm occurrence was already acknowledged.")
            head = db.execute(
                "SELECT clock FROM observation_sources WHERE source=?", (row["source"],)
            ).fetchone()["clock"]
            timestamp = timestamp or head
            if timestamp < row["last_event_at"] or timestamp > head:
                raise ValueError(
                    "Acknowledgement clock must be within the observed alarm timeline."
                )
            recorded_at = _clock(datetime.now(UTC))
            db.execute(
                "UPDATE alarm_occurrences SET acknowledged=1,acknowledged_at=?,acknowledged_by=?,"
                "acknowledgement_note=?,last_event_at=? WHERE id=?",
                (timestamp, actor, note, timestamp, alarm_id),
            )
            self._event(
                db,
                alarm_id,
                row["source"],
                row["signal"],
                "acknowledged",
                timestamp,
                recorded_at,
                actor,
                note,
            )
            result = db.execute(
                "SELECT * FROM alarm_occurrences WHERE id=?", (alarm_id,)
            ).fetchone()
            self._retain(db)
            return self._alarm_row(result)

    def prune(self, *, before=None):
        """Apply bounds and optionally discard older samples/events/resolved occurrences.

        Unresolved occurrences, condition state, and source clock markers survive.
        """
        timestamp = _clock(before) if before is not None else None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if timestamp:
                for table in ("trend_samples", "alarm_events"):
                    db.execute(f"DELETE FROM {table} WHERE clock<?", (timestamp,))
                db.execute(
                    "DELETE FROM alarm_occurrences WHERE active=0 AND acknowledged=1 "
                    "AND last_event_at<?",
                    (timestamp,),
                )
            self._retain(db)
        return self.status()

    def status(self):
        with self.connect() as db:
            counts = {
                name: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for name, table in (
                    ("samples", "trend_samples"),
                    ("alarm_events", "alarm_events"),
                    ("alarm_occurrences", "alarm_occurrences"),
                    ("sources", "observation_sources"),
                    ("conditions", "alarm_conditions"),
                )
            }
            counts["active_alarms"] = db.execute(
                "SELECT COUNT(*) FROM alarm_occurrences WHERE active=1"
            ).fetchone()[0]
            counts["unacknowledged_alarms"] = db.execute(
                "SELECT COUNT(*) FROM alarm_occurrences WHERE acknowledged=0"
            ).fetchone()[0]
            counts["ended_sources"] = db.execute(
                "SELECT COUNT(*) FROM observation_sources WHERE ended=1"
            ).fetchone()[0]
            counts["ended_alarms"] = db.execute(
                "SELECT COUNT(*) FROM alarm_occurrences WHERE ended_at IS NOT NULL"
            ).fetchone()[0]
            counts["open_sources"] = counts["sources"] - counts["ended_sources"]
        return counts | {
            "source_kind": self.source_kind,
            "limits": {
                "samples": self.max_samples,
                "alarm_events": self.max_alarm_events,
                "alarm_occurrences": self.max_alarm_occurrences,
                "sources": self.max_sources,
                "conditions": self.max_conditions,
            },
        }

    def list_sources(self):
        """List bounded source markers and retained evidence counts for selection."""
        with self.connect() as db:
            rows = db.execute("""
                SELECT s.source,s.clock,s.ended,s.ended_at,s.ended_recorded_at,
                    s.ended_by,s.ended_note,s.ended_alarms,
                    COALESCE(t.samples,0) AS samples,
                    COALESCE(a.occurrences,0) AS alarm_occurrences,
                    COALESCE(a.active_alarms,0) AS active_alarms,
                    COALESCE(a.unacknowledged_alarms,0) AS unacknowledged_alarms
                FROM observation_sources s
                LEFT JOIN (
                    SELECT source,COUNT(*) AS samples FROM trend_samples GROUP BY source
                ) t ON t.source=s.source
                LEFT JOIN (
                    SELECT source,COUNT(*) AS occurrences,SUM(active) AS active_alarms,
                        SUM(CASE WHEN acknowledged=0 THEN 1 ELSE 0 END) AS unacknowledged_alarms
                    FROM alarm_occurrences GROUP BY source
                ) a ON a.source=s.source
                ORDER BY s.clock DESC,s.source LIMIT 4096
            """).fetchall()
        return [self._source_row(row) for row in rows]

    def _source_row(self, row):
        source = dict(row)
        source.pop("digest", None)
        source["ended"] = bool(source["ended"])
        source["source_kind"] = self.source_kind
        return source

    def end_source(self, source, note, *, actor="operator"):
        """End a simulation source without falsely reporting a normal alarm return.

        Active occurrences become inactive with state source-ended and ended_at,
        retaining acknowledgement status and leaving returned_at unset. Each gets
        a source-ended event at the latest simulation clock, with actual receipt
        time, operator and note. Already returned occurrences are unchanged.
        Sources without active alarms retain the end metadata without inventing
        an alarm event. No samples or evidence are deleted by this operation.
        """
        source = _text(source, "source", 200)
        note = _text(note, "source ending note", 1000)
        actor = _text(actor, "actor", 120)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            head = db.execute(
                "SELECT * FROM observation_sources WHERE source=?", (source,)
            ).fetchone()
            if head is None:
                raise ValueError("Simulation source not found.")
            if head["ended"]:
                if head["ended_note"] == note and head["ended_by"] == actor:
                    return self._source_row(head)
                raise ValueError(
                    "Simulation source has already ended with a different note or actor."
                )
            timestamp = head["clock"]
            recorded_at = _clock(datetime.now(UTC))
            active = db.execute(
                "SELECT id,signal FROM alarm_occurrences WHERE source=? AND active=1 ORDER BY id",
                (source,),
            ).fetchall()
            for alarm in active:
                db.execute(
                    "UPDATE alarm_occurrences SET active=0,ended_at=?,last_event_at=? WHERE id=?",
                    (timestamp, timestamp, alarm["id"]),
                )
                self._event(
                    db,
                    alarm["id"],
                    source,
                    alarm["signal"],
                    "source-ended",
                    timestamp,
                    recorded_at,
                    actor,
                    note,
                )
            db.execute("UPDATE alarm_conditions SET active=0 WHERE source=?", (source,))
            db.execute(
                "UPDATE observation_sources SET ended=1,ended_at=?,ended_recorded_at=?,"
                "ended_by=?,ended_note=?,ended_alarms=? WHERE source=?",
                (timestamp, recorded_at, actor, note, len(active), source),
            )
            self._retain(db)
            return self._source_row(
                db.execute("SELECT * FROM observation_sources WHERE source=?", (source,)).fetchone()
            )

    def retire_source(self, source):
        """Explicitly delete a resolved source and all its retained observations.

        This destructive operation frees source/condition capacity and its clock
        marker. Active or unacknowledged occurrences prevent retirement.
        """
        source = _text(source, "source", 200)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute("SELECT 1 FROM observation_sources WHERE source=?", (source,)).fetchone()
                is None
            ):
                raise ValueError("Simulation source not found.")
            if (
                db.execute(
                    "SELECT 1 FROM alarm_occurrences WHERE source=? AND "
                    "(active=1 OR acknowledged=0) LIMIT 1",
                    (source,),
                ).fetchone()
                is not None
            ):
                raise ValueError("Return and acknowledge all alarms before retiring this source.")
            removed = {}
            for name, table in (
                ("samples", "trend_samples"),
                ("alarm_events", "alarm_events"),
                ("conditions", "alarm_conditions"),
                ("alarm_occurrences", "alarm_occurrences"),
            ):
                removed[name] = db.execute(
                    f"DELETE FROM {table} WHERE source=?", (source,)
                ).rowcount
            db.execute("DELETE FROM observation_sources WHERE source=?", (source,))
        return {
            "source": source,
            "source_kind": self.source_kind,
            "retired": True,
            "removed": removed,
        }
