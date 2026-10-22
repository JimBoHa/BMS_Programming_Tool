"""Explicit asynchronous COV receipt recording in the existing field store.

Receipt timestamps never become an inferred controller clock. A bounded queue
keeps SQLite work out of notification/ACK callbacks; loss and storage faults
remain explicit rather than turning into fabricated trend values.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

from .file_access import open_regular, try_lock
from .observability import ObservabilityStore, _integer, _text


def _utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


class _WriterLock:
    """One COV evidence writer per field store; OS releases lock after exit."""

    def __init__(self, path):
        self.fd = None
        try:
            self.fd = open_regular(path, writable=True, create=True)
            if hasattr(os, "fchmod"):
                os.fchmod(self.fd, 0o600)
            try_lock(self.fd)
        except (OSError, ValueError) as exc:
            self.close()
            raise ValueError(
                "COV recording ownership unavailable: another writer or invalid lock file."
            ) from exc

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class CovObservations:
    def __init__(self, store: ObservabilityStore, *, queue_limit=64, max_events=5000):
        if store.source_kind != "field":
            raise ValueError("COV observations require a field observation store.")
        self.store = store
        self.max_events = _integer(max_events, "max_events", 1, 100000)
        self.queue = asyncio.Queue(maxsize=_integer(queue_limit, "queue_limit", 1, 256))
        self.states = {}
        self.worker = None
        self.closed = False
        self.busy = False
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cov_recordings(
                    source TEXT PRIMARY KEY REFERENCES observation_sources(source) ON DELETE CASCADE,
                    monitor TEXT NOT NULL UNIQUE,metadata TEXT NOT NULL,started_at TEXT NOT NULL,
                    ended_at TEXT,state TEXT NOT NULL,received INTEGER NOT NULL DEFAULT 0,
                    recorded INTEGER NOT NULL DEFAULT 0,dropped INTEGER NOT NULL DEFAULT 0,
                    discarded INTEGER NOT NULL DEFAULT 0,events_evicted INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,last_received_at TEXT
                );
                CREATE TABLE IF NOT EXISTS cov_receipts(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL REFERENCES cov_recordings(source) ON DELETE CASCADE,
                    event TEXT NOT NULL,received_at TEXT NOT NULL,recorded_at TEXT NOT NULL,
                    evidence TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS cov_receipts_by_source ON cov_receipts(source,sequence);
                CREATE TABLE IF NOT EXISTS cov_sample_links(
                    receipt INTEGER NOT NULL REFERENCES cov_receipts(sequence) ON DELETE CASCADE,
                    sample INTEGER REFERENCES trend_samples(sequence) ON DELETE SET NULL
                );
            """)
        self.ownership = None
        self.needs_recovery = False
        # A reader must never end a different live process's recordings.
        try:
            probe = _WriterLock(self.store.directory / "cov-recording.lock")
        except ValueError:
            pass
        else:
            try:
                self._recover()
            finally:
                probe.close()

    def _recover(self):
        # Called only while the exclusive process lock is held. No subscription
        # resumes; an unclosed previous writer has an explicitly unknown tail.
        with self._connect() as db:
            for row in db.execute(
                "SELECT source FROM cov_recordings WHERE ended_at IS NULL"
            ).fetchall():
                source = row[0]
                stamp = _utc()
                db.execute(
                    "UPDATE cov_recordings SET state='interrupted',ended_at=?,last_error=? WHERE source=?",
                    (
                        stamp,
                        "Previous process ended without a durable recording closure; tail loss is unknown.",
                        source,
                    ),
                )
                db.execute(
                    "UPDATE observation_sources SET ended=1,ended_at=clock,ended_recorded_at=?,ended_by='cov-recorder',ended_note='Interrupted recording; unknown tail loss' WHERE source=?",
                    (stamp, source),
                )
                self._insert(
                    db,
                    source,
                    "interrupted",
                    stamp,
                    {
                        "gap": "Unknown uncommitted tail after restart.",
                        "subscriptions_resumed": False,
                    },
                )

            self._retain(db)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.store.db, timeout=0.1)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _insert(self, db, source, event, stamp, evidence):
        return db.execute(
            "INSERT INTO cov_receipts(source,event,received_at,recorded_at,evidence) VALUES(?,?,?,?,?)",
            (source, event, stamp, _utc(), json.dumps(evidence, allow_nan=False)),
        ).lastrowid

    def _begin(self, state, metadata):
        if self.needs_recovery:
            self._recover()
            self.needs_recovery = False
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute("SELECT COUNT(*) FROM observation_sources").fetchone()[0]
                >= self.store.max_sources
            ):
                raise ValueError(
                    "Field observation source capacity reached; retire an ended source first."
                )
            encoded = json.dumps(metadata, sort_keys=True, allow_nan=False)
            stamp = _utc()
            db.execute(
                "INSERT INTO observation_sources(source,clock,digest) VALUES(?,?,?)",
                (state["source"], stamp, hashlib.sha256(encoded.encode()).hexdigest()),
            )
            db.execute(
                "INSERT INTO observation_provenance(source,metadata) VALUES(?,?)",
                (state["source"], encoded),
            )
            db.execute(
                "INSERT INTO cov_recordings(source,monitor,metadata,started_at,state) VALUES(?,?,?,?,'recording')",
                (state["source"], state["monitor"], encoded, stamp),
            )
            self._insert(db, state["source"], "recording_started", stamp, metadata)

    async def begin(self, job):
        if self.closed:
            raise ValueError("COV recorder is closed.")
        if self.worker is not None and self.worker.done():
            raise ValueError(
                "COV recording worker stopped; explicitly restart the application before recording."
            )
        for key, old in list(self.states.items()):
            if len(self.states) < 32:
                break
            if old.get("ended_persisted"):
                del self.states[key]
        if len(self.states) >= 256:
            raise ValueError("Recording runtime capacity reached; close completed monitors first.")
        state = {
            "source": "cov/" + job["id"],
            "monitor": job["id"],
            "active": True,
            "received": 0,
            "recorded": 0,
            "dropped": 0,
            "discarded": 0,
            "persisted_dropped": 0,
            "persisted_discarded": 0,
            "last_error": None,
            "fault": False,
            "pending_end": None,
        }
        metadata = {
            "acquisition_kind": "bacnet-cov",
            "source_store_id": self.store.identity()["store_id"],
            "clock_basis": "receipt",
            "source_clock": None,
            "source_clock_status": "Not supplied by COV; receipt time only.",
            "monitor_id": job["id"],
            "config": job["config"].model_dump(),
            "process_id": job["process_id"],
            "connector_config": job["connector_config"],
        }
        if self.ownership is None:
            self.ownership = _WriterLock(self.store.directory / "cov-recording.lock")
            self.needs_recovery = True
        operation = asyncio.create_task(asyncio.to_thread(self._begin, state, metadata))
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            await operation
            state["active"] = False
            await asyncio.to_thread(
                self._write,
                state,
                "recording_ended",
                {"reason": "Recording start cancelled before controller subscription."},
            )
            raise
        self.states[job["id"]] = state
        if self.worker is None:
            self.worker = asyncio.create_task(self._run(), name="bms-cov-recording-worker")
            self.worker.add_done_callback(self._worker_done)
        return state

    def _worker_done(self, task):
        if self.closed:
            return
        reason = "Recording worker stopped unexpectedly; durable tail is uncertain."
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                reason += " " + str(error)[:500]
        for state in self.states.values():
            if state["active"]:
                state.update(active=False, fault=True, last_error=reason)

    def submit(self, state, event, evidence):
        if state is None or not state["active"] or self.closed:
            return
        if event == "notification":
            state["received"] += 1
        try:
            self.queue.put_nowait((state, event, evidence))
        except asyncio.QueueFull:
            state["dropped"] += 1
            state["last_error"] = "COV recording queue full; evidence omitted and counted."

    def discarded(self, state, reason):
        if state is not None and state["active"]:
            state["discarded"] += 1
            state["last_discarded"] = str(reason)[:500]

    def end(self, state, reason):
        if state is not None and not state.get("end_requested"):
            state["end_requested"] = True
            state["active"] = False
            state["pending_end"] = copy.deepcopy(reason)

    @staticmethod
    def _samples(evidence):
        quality = "unknown"
        flags = next(
            (
                p["value"]
                for p in evidence["values"]
                if p["property_id"] == 111 and p["decode_status"] == "decoded"
            ),
            None,
        )
        if (
            isinstance(flags, list)
            and len(flags) == 4
            and all(type(v) in (bool, int) and v in (0, 1) for v in flags)
        ):
            quality = "fault" if flags[1] else "unreliable" if any(flags) else "unknown"
        result = []
        for value in evidence["values"]:
            if (
                value["property_id"] != 85
                or value["array_index"] is not None
                or value["decode_status"] != "decoded"
            ):
                continue
            scalar = value["value"]
            kind = value.get("native_datatype")
            if kind == "BinaryPV" and type(scalar) is int and scalar in (0, 1):
                scalar = bool(scalar)
            if kind not in {"Real", "Double", "Boolean", "Unsigned", "Signed", "BinaryPV"} or not (
                type(scalar) is bool or type(scalar) in (int, float) and math.isfinite(scalar)
            ):
                continue
            result.append(("present-value", scalar, quality))
        # Multiple scalar representations of one point in one notification
        # are ambiguous; keep the whole notification as evidence only.
        return result if len(result) <= 1 else []

    def _gaps(self, db, state):
        for field in ("dropped", "discarded"):
            pending = state[field] - state["persisted_" + field]
            if pending:
                self._insert(
                    db,
                    state["source"],
                    field,
                    _utc(),
                    {
                        "count": pending,
                        "total": state[field],
                        "reason": state.get("last_discarded")
                        if field == "discarded"
                        else state.get("last_error"),
                    },
                )

    def _retain(self, db):
        rows = db.execute(
            "SELECT source,COUNT(*) AS n FROM cov_receipts WHERE sequence < COALESCE((SELECT sequence FROM cov_receipts ORDER BY sequence DESC LIMIT 1 OFFSET ?),0) GROUP BY source",
            (self.max_events - 1,),
        ).fetchall()
        for row in rows:
            db.execute(
                "UPDATE cov_recordings SET events_evicted=events_evicted+? WHERE source=?",
                (row["n"], row["source"]),
            )
        db.execute(
            "DELETE FROM cov_receipts WHERE sequence < COALESCE((SELECT sequence FROM cov_receipts ORDER BY sequence DESC LIMIT 1 OFFSET ?),0)",
            (self.max_events - 1,),
        )
        self.store._retain(db)

    def _write(self, state, event, evidence):
        stamp = evidence.get("received_at", _utc())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._gaps(db, state)
            identifier = self._insert(db, state["source"], event, stamp, evidence)
            if event == "notification":
                previous = db.execute(
                    "SELECT last_received_at FROM cov_recordings WHERE source=?", (state["source"],)
                ).fetchone()[0]
                if previous is not None and stamp <= previous:
                    self._insert(
                        db,
                        state["source"],
                        "receipt_clock_not_increasing",
                        stamp,
                        {
                            "previous_receipt": previous,
                            "current_receipt": stamp,
                            "source_clock": None,
                        },
                    )
                for signal, value, quality in self._samples(evidence):
                    sample = db.execute(
                        "INSERT INTO trend_samples(source,signal,clock,value,value_type,quality,unit,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            state["source"],
                            signal,
                            stamp,
                            json.dumps(value),
                            "boolean" if type(value) is bool else "number",
                            quality,
                            "",
                            _utc(),
                        ),
                    ).lastrowid
                    db.execute(
                        "INSERT INTO cov_sample_links(receipt,sample) VALUES(?,?)",
                        (identifier, sample),
                    )
                db.execute(
                    "UPDATE observation_sources SET clock=?,digest=? WHERE source=?",
                    (
                        stamp,
                        hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest(),
                        state["source"],
                    ),
                )
                db.execute(
                    "UPDATE cov_recordings SET recorded=recorded+1,last_received_at=? WHERE source=?",
                    (stamp, state["source"]),
                )
            db.execute(
                "UPDATE cov_recordings SET received=?,dropped=?,discarded=?,last_error=? WHERE source=?",
                (
                    state["received"],
                    state["dropped"],
                    state["discarded"],
                    state.get("last_error"),
                    state["source"],
                ),
            )
            if event == "recording_ended":
                db.execute(
                    "UPDATE cov_recordings SET ended_at=?,state=? WHERE source=?",
                    (_utc(), "storage_failed" if state["fault"] else "ended", state["source"]),
                )
                db.execute(
                    "UPDATE observation_sources SET ended=1,ended_at=clock,ended_recorded_at=?,ended_by='cov-recorder',ended_note=? WHERE source=?",
                    (_utc(), json.dumps(evidence)[:1000], state["source"]),
                )
            self._retain(db)
        return state["dropped"], state["discarded"]

    async def _commit(self, state, event, evidence):
        self.busy = True
        try:
            snapshot = copy.deepcopy(state)
            dropped, discarded = await asyncio.to_thread(self._write, snapshot, event, evidence)
            state.update(persisted_dropped=dropped, persisted_discarded=discarded)
            if event == "notification":
                state["recorded"] += 1
            if event == "recording_ended":
                state["ended_persisted"] = True
        except Exception as exc:
            state.update(
                active=False,
                fault=True,
                last_error="COV recording storage failed: " + str(exc)[:500],
            )
            state["dropped"] += event == "notification"
            # No retry of the failed notification. If even end evidence cannot
            # be saved, restart will explicitly identify its unknown tail.
        finally:
            self.busy = False

    async def _run(self):
        while (
            not self.closed
            or not self.queue.empty()
            or any(s["pending_end"] is not None for s in self.states.values())
        ):
            try:
                state, event, evidence = await asyncio.wait_for(self.queue.get(), 0.1)
                try:
                    if state["fault"]:
                        state["dropped"] += event == "notification"
                    else:
                        await self._commit(state, event, evidence)
                finally:
                    self.queue.task_done()
            except TimeoutError:
                pass
            if self.queue.empty():
                for state in list(self.states.values()):
                    if state["pending_end"] is not None:
                        evidence, state["pending_end"] = state["pending_end"], None
                        await self._commit(state, "recording_ended", evidence)
                    elif not state["fault"] and (
                        state["dropped"] != state["persisted_dropped"]
                        or state["discarded"] != state["persisted_discarded"]
                    ):
                        await self._commit(state, "gap_summary", {})

    async def flush(self):
        await self.queue.join()
        while self.busy or any(
            s["pending_end"] is not None
            or not s["fault"]
            and (
                s["dropped"] != s["persisted_dropped"] or s["discarded"] != s["persisted_discarded"]
            )
            for s in self.states.values()
        ):
            await asyncio.sleep(0.01)

    async def close(self):
        self.closed = True
        for state in self.states.values():
            if not state.get("ended_persisted"):
                self.end(state, {"reason": "Recorder shutdown", "source_clock": None})
        try:
            if self.worker is not None:
                try:
                    await asyncio.shield(self.worker)
                except asyncio.CancelledError:
                    if not self.worker.cancelled():
                        await self.worker
                        raise
                except Exception:
                    pass  # explicit fault state already recorded by worker callback
        finally:
            if self.ownership is not None:
                self.ownership.close()
                self.ownership = None

    def recordings(self):
        with self._connect() as db:
            rows = db.execute(
                "SELECT r.*,(SELECT COUNT(*) FROM cov_receipts e WHERE e.source=r.source) AS events_retained,(SELECT COUNT(*) FROM cov_sample_links l JOIN cov_receipts e ON e.sequence=l.receipt WHERE e.source=r.source AND l.sample IS NULL) AS samples_evicted FROM cov_recordings r ORDER BY started_at DESC LIMIT 4096"
            ).fetchall()
        return [
            dict(row) | {"metadata": json.loads(row["metadata"]), "auto_resume": False}
            for row in rows
        ]

    def events(self, monitor, *, after=0, limit=100):
        monitor = _text(monitor, "monitor", 80)
        _integer(after, "after", 0, 2**63 - 1)
        _integer(limit, "limit", 1, 1000)
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM cov_receipts WHERE source=? AND sequence>? ORDER BY sequence LIMIT ?",
                ("cov/" + monitor, after, limit),
            ).fetchall()
        return [
            dict(row)
            | {
                "evidence": json.loads(row["evidence"]),
                "acquisition_kind": "bacnet-cov",
                "clock_basis": "receipt",
                "source_clock": None,
            }
            for row in rows
        ]
