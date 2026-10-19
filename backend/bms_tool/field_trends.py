"""Explicit, read-only BACnet polling with durable samples and failure evidence.

The service shares an already connected engineering interface. It never opens,
reconnects, discovers or writes a device. Job definitions remain in memory;
samples/events persist separately from simulation observations. Restart does
not resume field traffic. Quality is unknown until explicitly verified.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from bacpypes3.basetypes import PropertyIdentifier, Reliability
from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field, field_validator, model_validator

from .models import StrictModel
from .observability import ObservabilityStore, _clock, _text


class FieldTrendPoint(StrictModel):
    signal: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    address: str = Field(min_length=1, max_length=200)
    object_id: str = Field(min_length=1, max_length=100)
    property_id: str = Field(default="present-value", min_length=1, max_length=100)
    array_index: int | None = Field(default=None, ge=0, le=4294967295, strict=True)
    unit: str = Field(default="", max_length=80)
    value_type: Literal["number", "boolean"] = "number"

    @field_validator("address", "object_id", "property_id", "unit")
    @classmethod
    def plain_text(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError("Point fields cannot contain control characters.")
        value.encode("utf-8")
        return value

    @field_validator("object_id")
    @classmethod
    def object_identifier(cls, value):
        ObjectIdentifier(value)
        return value

    @field_validator("property_id")
    @classmethod
    def property_identifier(cls, value):
        PropertyIdentifier(value)
        return value


class FieldTrendStart(StrictModel):
    points: list[FieldTrendPoint] = Field(min_length=1, max_length=32)
    interval_seconds: float = Field(default=10, ge=5, le=3600, strict=True)
    verify_quality: bool = Field(default=False, strict=True)
    name: str = Field(default="", max_length=120)

    @field_validator("name")
    @classmethod
    def plain_name(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError("Job name cannot contain control characters.")
        value.encode("utf-8")
        return value

    @model_validator(mode="after")
    def unique_signals(self):
        if len({p.signal for p in self.points}) != len(self.points):
            raise ValueError("Field trend signals must be unique within a job.")
        return self


class InterfaceChanged(ValueError):
    pass


class AcquisitionClockError(ValueError):
    pass


class FieldPersistenceError(ValueError):
    pass


@dataclass
class _Job:
    id: str
    source: str
    config: FieldTrendStart
    connector_config: dict
    application: object
    started_at: str
    running: bool = True
    state: str = "running"
    stopped_at: str | None = None
    last_poll: str | None = None
    last_error: str | None = None
    last_clock: str | None = None
    polls: int = 0
    samples: int = 0
    failures: int = 0
    latest: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    task: asyncio.Task | None = None


def _scalar(value, value_type):
    # BACpypes Real/Unsigned/Boolean/Enumerated values subclass numeric types.
    # Convert accepted protocol values into actual JSON float/int/bool types.
    if value_type == "boolean":
        if type(value) is bool:
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value in ("active", "inactive"):
            return value == "active"
        raise ValueError("Boolean field value must be boolean or an explicit binary 0/1 state.")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Numeric field value must be a finite number.")
    try:
        if not math.isfinite(value):
            raise ValueError("Numeric field value must be a finite number.")
    except OverflowError as exc:
        raise ValueError("Numeric field value must be a finite number.") from exc
    return int(value) if isinstance(value, int) else float(value)


def _quality(reliability, flags, out_of_service):
    if isinstance(reliability, str):
        try:
            no_fault = int(Reliability(reliability)) == 0
        except ValueError as exc:
            raise ValueError(
                "Reliability response is not a recognized BACnet enumeration."
            ) from exc
    elif isinstance(reliability, int) and not isinstance(reliability, bool) and reliability >= 0:
        no_fault = reliability == 0
    else:
        raise ValueError("Reliability response is not a validated BACnet enumeration.")
    if not isinstance(flags, (list, tuple)) or len(flags) != 4:
        raise ValueError("Status flags must contain exactly four boolean/binary flags.")
    if any(not isinstance(flag, (bool, int)) or flag not in (0, 1) for flag in flags):
        raise ValueError("Status flags must contain exactly four boolean/binary flags.")
    if not isinstance(out_of_service, (bool, int)) or out_of_service not in (0, 1):
        raise ValueError("Out-of-service must be a boolean/binary value.")
    normalized = [bool(flag) for flag in flags]
    out = bool(out_of_service)
    if normalized[1]:
        return "fault"
    if not no_fault or out or any(normalized):
        return "unreliable"
    return "good"


class FieldTrends:
    def __init__(
        self,
        bacnet,
        directory,
        audit_store=None,
        *,
        clock=None,
        request_timeout=6.5,
        min_request_gap=0.05,
    ):
        if (
            type(request_timeout) not in (int, float)
            or not math.isfinite(request_timeout)
            or not 0.01 <= request_timeout <= 10
        ):
            raise ValueError("Read timeout must be 0.01..10 seconds.")
        if (
            type(min_request_gap) not in (int, float)
            or not math.isfinite(min_request_gap)
            or not 0 <= min_request_gap <= 1
        ):
            raise ValueError("Read gap must be 0..1 seconds.")
        self.bacnet = bacnet
        self.audit_store = audit_store
        self.store = ObservabilityStore(Path(directory) / "field", source_kind="field")
        self.clock = clock or (lambda: datetime.now(UTC))
        self.request_timeout = request_timeout
        self.min_request_gap = min_request_gap
        self._jobs = {}
        self._jobs_lock = asyncio.Lock()
        self._read_lock = asyncio.Lock()
        self._last_read = 0.0
        self._closed = False
        with self.store.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS field_poll_events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,source TEXT NOT NULL,signal TEXT,
                    event TEXT NOT NULL,clock TEXT,recorded_at TEXT NOT NULL,
                    error TEXT NOT NULL,detail TEXT NOT NULL
                )
            """)
            db.execute(
                "CREATE INDEX IF NOT EXISTS field_events_by_source ON field_poll_events(source,sequence)"
            )

    def _audit(self, operation, detail):
        if self.audit_store is not None:
            self.audit_store.record(operation, detail)

    def _event(self, job, event, *, signal=None, error="", clock=None, detail=None):
        self._source_event(
            job.id,
            job.source,
            event,
            signal=signal,
            error=error,
            clock=clock,
            detail=detail,
        )

    def _source_event(
        self, job_id, source, event, *, signal=None, error="", clock=None, detail=None
    ):
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO field_poll_events(job_id,source,signal,event,clock,recorded_at,error,detail) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    source,
                    signal,
                    event,
                    clock,
                    _clock(datetime.now(UTC)),
                    str(error)[:2000],
                    json.dumps(detail or {}, allow_nan=False),
                ),
            )
            db.execute(
                "DELETE FROM field_poll_events WHERE sequence < COALESCE((SELECT sequence FROM field_poll_events ORDER BY sequence DESC LIMIT 1 OFFSET 4999),0)"
            )

    def _check_interface(self, job):
        status = self.bacnet.status()
        if not status.get("connected"):
            raise InterfaceChanged("The BACnet interface stopped. Polling will not reconnect it.")
        if status.get("config") != job.connector_config or self.bacnet.app is not job.application:
            raise InterfaceChanged(
                "The BACnet interface configuration or application changed. Start a new trend job explicitly."
            )
        self.bacnet.require()

    async def start(self, points, interval_seconds=10, verify_quality=False, name=""):
        config = FieldTrendStart(
            points=points,
            interval_seconds=interval_seconds,
            verify_quality=verify_quality,
            name=name,
        )
        async with self._jobs_lock:
            if self._closed:
                raise ValueError("Field trend service is closed.")
            active = [job for job in self._jobs.values() if job.running]
            if (
                len(active) >= 8
                or sum(len(job.config.points) for job in active) + len(config.points) > 128
            ):
                raise ValueError(
                    "Field polling supports at most eight active jobs and 128 total active points."
                )
            application = self.bacnet.require()
            status = self.bacnet.status()
            if not status.get("connected") or not isinstance(status.get("config"), dict):
                raise ValueError(
                    "Connect the intended BACnet interface before starting field trends."
                )
            for point in config.points:
                self.bacnet.target_address(point.address)
            identifier = "poll-" + secrets.token_hex(12)
            job = _Job(
                identifier,
                "field/" + identifier,
                config,
                copy.deepcopy(status["config"]),
                application,
                _clock(datetime.now(UTC)),
            )
            self._audit(
                "field-trends.start.requested",
                {
                    "job": job.id,
                    "source": job.source,
                    "config": config.model_dump(),
                    "connector_config": job.connector_config,
                },
            )
            self._event(
                job,
                "started",
                detail={"config": config.model_dump(), "connector_config": job.connector_config},
            )
            if len(self._jobs) >= 32:
                retired = next(
                    (key for key, value in self._jobs.items() if not value.running), None
                )
                if retired is not None:
                    del self._jobs[retired]
            self._jobs[job.id] = job
            job.task = asyncio.create_task(self._run(job), name="bms-field-trends-" + job.id)
            return self._status(job)

    async def _read(self, job, point, property_id, array_index=None):
        async with self._read_lock:
            self._check_interface(job)
            delay = self.min_request_gap - (time.monotonic() - self._last_read)
            if delay > 0:
                await asyncio.sleep(delay)
                self._check_interface(job)
            try:
                response = await asyncio.wait_for(
                    self.bacnet.read(point.address, point.object_id, property_id, array_index),
                    self.request_timeout,
                )
            finally:
                self._last_read = time.monotonic()
            self._check_interface(job)
            if not isinstance(response, dict) or "value" not in response:
                raise ValueError("BACnet read did not return a value.")
            return response["value"]

    def _failure(self, job, point, error, event="read-failed", clock=None):
        message = str(error)[:2000] or type(error).__name__
        job.failures += 1
        job.last_error = message
        record = {
            "signal": point.signal if point else None,
            "event": event,
            "error": message,
            "recorded_at": _clock(datetime.now(UTC)),
        }
        job.errors = (job.errors + [record])[-50:]
        self._event(job, event, signal=record["signal"], error=message, clock=clock)

    async def _poll(self, job):
        self._check_interface(job)
        job.polls += 1
        job.last_poll = _clock(datetime.now(UTC))
        for point in job.config.points:
            try:
                value = _scalar(
                    await self._read(job, point, point.property_id, point.array_index),
                    point.value_type,
                )
                try:
                    acquired = _clock(self.clock())
                except (ValueError, OverflowError) as exc:
                    raise AcquisitionClockError(
                        "Acquisition clock must be timezone-aware and representable in UTC."
                    ) from exc
                if job.last_clock is not None and acquired <= job.last_clock:
                    raise AcquisitionClockError(
                        "Acquisition clock did not advance. Polling stopped without fabricating timestamps."
                    )
                quality = "unknown"
                if job.config.verify_quality:
                    try:
                        reliability = await self._read(job, point, "reliability")
                        flags = await self._read(job, point, "status-flags")
                        out_of_service = await self._read(job, point, "out-of-service")
                        quality = _quality(reliability, flags, out_of_service)
                    except InterfaceChanged:
                        raise
                    except Exception as exc:
                        self._failure(job, point, exc, "quality-unavailable", acquired)
                self._check_interface(job)
                try:
                    result = self.store.record_scan(
                        job.source,
                        acquired,
                        {point.signal: value},
                        qualities={point.signal: quality},
                        units={point.signal: point.unit},
                    )
                except Exception as exc:
                    self._failure(job, point, exc, "storage-failed", acquired)
                    raise FieldPersistenceError(
                        "Sample persistence failed; polling stopped: " + str(exc)[:1000]
                    ) from exc
                job.last_clock = acquired
                job.samples += result["samples"]
                job.latest[point.signal] = {
                    "value": value,
                    "quality": quality,
                    "clock": acquired,
                    "unit": point.unit,
                }
            except (InterfaceChanged, AcquisitionClockError, FieldPersistenceError):
                raise
            except Exception as exc:
                self._failure(job, point, exc)

    async def _run(self, job):
        reason = "Polling stopped explicitly."
        try:
            while job.running:
                await self._poll(job)
                # Observe interface shutdown/configuration changes promptly
                # while waiting, without issuing any additional device read.
                deadline = asyncio.get_running_loop().time() + job.config.interval_seconds
                while job.running:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    await asyncio.sleep(min(0.25, remaining))
                    self._check_interface(job)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            reason = str(exc)[:2000] or type(exc).__name__
            job.state = "fault"
            job.last_error = reason
            try:
                self._failure(job, None, reason, "job-failed")
            except Exception as evidence_error:
                job.last_error += (
                    "; failure evidence could not be stored: " + str(evidence_error)[:500]
                )
        finally:
            self._finish(job, reason)

    def _finish(self, job, reason):
        if job.stopped_at is not None:
            return
        job.running = False
        if job.state != "fault":
            job.state = "stopped"
        job.stopped_at = _clock(datetime.now(UTC))
        operations = [
            lambda: self._event(
                job,
                "stopped",
                error=reason if job.state == "fault" else "",
                detail={"reason": reason},
            )
        ]

        def end_source():
            with self.store.connect() as db:
                exists = db.execute(
                    "SELECT 1 FROM observation_sources WHERE source=?", (job.source,)
                ).fetchone()
            if exists:
                self.store.end_source(job.source, reason[:1000], actor="field-poller")

        operations.extend(
            [
                end_source,
                lambda: self._audit(
                    "field-trends.stopped",
                    {"job": job.id, "source": job.source, "state": job.state, "reason": reason},
                ),
            ]
        )
        for operation in operations:
            try:
                operation()
            except Exception as exc:
                job.state = "fault"
                job.last_error = (
                    (job.last_error or reason) + "; completion evidence failed: " + str(exc)[:500]
                )

    async def stop(self, id):
        async with self._jobs_lock:
            job = self._jobs.get(id)
            if job is None:
                raise ValueError("Field trend job not found; jobs do not resume after restart.")
            if job.running:
                try:
                    self._audit("field-trends.stop.requested", {"job": id, "source": job.source})
                except Exception as exc:
                    job.last_error = "Stop audit failed; polling still stopped: " + str(exc)[:500]
                job.running = False
                job.task.cancel()
                try:
                    await job.task
                except asyncio.CancelledError:
                    # A task cancelled before its first scheduling turn never
                    # enters _run's finally clause. Finish that job here.
                    self._finish(job, "Polling stopped explicitly before its first read.")
            return self._status(job)

    async def close(self):
        self._closed = True
        for id in list(self._jobs):
            await self.stop(id)

    async def retire_source(self, source):
        """Explicitly delete an ended source's samples and observation metadata.

        Active polling and open sources refuse retirement. Poll lifecycle/error
        events and the separate operation audit remain as action evidence. A
        failed completion record never implies committed deletion rolled back.
        """
        source = _text(source, "field source", 200)
        async with self._jobs_lock:
            if any(job.running and job.source == source for job in self._jobs.values()):
                raise ValueError("Stop the field trend job before retiring its source.")
            with self.store.connect() as db:
                head = db.execute(
                    "SELECT ended FROM observation_sources WHERE source=?", (source,)
                ).fetchone()
            if head is None:
                raise ValueError("Field observation source not found.")
            if not head["ended"]:
                raise ValueError("End the field observation source before retiring it.")
            detail = {"source": source, "scope": "saved-samples-and-source-metadata"}
            self._audit("field-trends.retirement.requested", detail)
            job_id = source.removeprefix("field/")
            self._source_event(job_id, source, "retirement-requested", detail=detail)
            result = self.store.retire_source(source)
            errors = []
            try:
                self._source_event(job_id, source, "retired", detail=result)
            except Exception as exc:
                errors.append(str(exc)[:500])
            try:
                self._audit("field-trends.retired", result)
            except Exception as exc:
                errors.append(str(exc)[:500])
            if errors:
                result["audit_error"] = (
                    "Source retirement committed; completion evidence failed: " + "; ".join(errors)
                )
            return result

    @staticmethod
    def _status(job):
        return {
            "id": job.id,
            "source": job.source,
            **job.config.model_dump(),
            "connector_config": copy.deepcopy(job.connector_config),
            "running": job.running,
            "state": job.state,
            "started_at": job.started_at,
            "stopped_at": job.stopped_at,
            "last_poll": job.last_poll,
            "last_error": job.last_error,
            "polls": job.polls,
            "samples": job.samples,
            "failures": job.failures,
            "latest": copy.deepcopy(job.latest),
            "recent_errors": copy.deepcopy(job.errors),
        }

    def status(self):
        return {
            "jobs": [self._status(job) for job in self._jobs.values()],
            "running_jobs": sum(job.running for job in self._jobs.values()),
            "store": self.store.status(),
            "auto_resume": False,
            "scope": "read-only-bacnet-field",
            "limits": {
                "active_jobs": 8,
                "points_per_job": 32,
                "active_points": 128,
                "retained_jobs": 32,
                "events": 5000,
                "interval_min": 5,
                "interval_max": 3600,
            },
        }

    def events(self, *, source=None, after=0, limit=100):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Events require a nonnegative cursor and limit 1..1000.")
        if source is not None and (not isinstance(source, str) or not 1 <= len(source) <= 200):
            raise ValueError("Invalid field source filter.")
        where, args = "sequence>?", [after]
        if source is not None:
            where += " AND source=?"
            args.append(source)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM field_poll_events WHERE " + where + " ORDER BY sequence LIMIT ?",
                [*args, limit],
            ).fetchall()
        return [
            dict(row) | {"detail": json.loads(row["detail"]), "source_kind": "field"}
            for row in rows
        ]
