"""Durable, explicitly enabled alarm webhooks with conservative delivery evidence.

Creating routes never sends traffic. Process restart disables every route. A
receiver's HTTP receipt does not acknowledge an alarm or prove human receipt.
Ambiguous requests stop their route until an operator retries or discards them.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .file_access import open_regular, regular_file, try_lock
from .observability import ObservabilityStore, _clock, _integer, _text

EVENTS = frozenset({"activated", "returned", "acknowledged", "source-ended"})
STATES = frozenset(
    {"queued", "sending", "retry_wait", "delivered", "failed", "uncertain", "discarded", "gap"}
)
TERMINAL = ("delivered", "discarded", "gap")
MAX_PAYLOAD = 16384


def _json(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


def _number(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite from {low} to {high}.")
    return float(value)


def _route_id(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{32}", value):
        raise ValueError("A native outbox route identifier is required.")
    return value


def _url(value):
    value = _text(value, "Webhook URL", 2048)
    if any(char.isspace() for char in value) or "\\" in value:
        raise ValueError("Webhook URL cannot contain whitespace or backslashes.")
    try:
        parsed = urlsplit(value)
        checked = httpx.URL(value)
        port = parsed.port
    except (ValueError, httpx.InvalidURL) as exc:
        raise ValueError("Webhook URL is invalid.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "#" in value
        or checked.scheme != parsed.scheme
        or not checked.host
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("Webhook URL requires HTTP(S), a host, and no userinfo or fragment.")
    return str(checked)


class _OwnerLock:
    """One active service per database; the OS releases ownership after a crash."""

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
                "Outbox ownership unavailable: another service or invalid lock file."
            ) from exc

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class NotificationOutbox:
    def __init__(
        self,
        directory,
        observations: ObservabilityStore,
        *,
        max_routes=32,
        max_deliveries=10000,
        timeout_seconds=5,
        max_attempts=5,
        base_backoff_seconds=5,
        max_backoff_seconds=300,
        clock=None,
    ):
        self.observations = observations
        identity = observations.identity()
        self.source_kind = identity["source_kind"]
        self.source_store_id = identity["store_id"]
        self.max_routes = _integer(max_routes, "max_routes", 1, 256)
        self.max_deliveries = _integer(max_deliveries, "max_deliveries", 1, 100000)
        self.timeout = _number(timeout_seconds, "timeout_seconds", 0.01, 30)
        self.max_attempts = _integer(max_attempts, "max_attempts", 1, 10)
        self.base_backoff = _number(base_backoff_seconds, "base_backoff_seconds", 0.01, 3600)
        self.max_backoff = _number(
            max_backoff_seconds, "max_backoff_seconds", self.base_backoff, 86400
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._owner = uuid.uuid4().hex
        self._enabled = set()
        self._state_lock = threading.RLock()
        self._cycle_lock = asyncio.Lock()
        self._closed = False
        self._closing = False
        self._round_robin = 0
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.db = self.directory / "notification_outbox.sqlite3"
        try:
            if not regular_file(self.db.lstat()):
                raise ValueError(
                    "Outbox database must be a regular file, not a symlink or directory."
                )
        except FileNotFoundError:
            pass
        self._ownership = _OwnerLock(self.directory / "notification_outbox.lock")
        try:
            self._initialize()
            self.db.chmod(0o600)
        except BaseException:
            self._ownership.close()
            raise

    def _now(self):
        timestamp = _clock(self._clock())
        return timestamp, datetime.fromisoformat(timestamp).timestamp()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _initialize(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            schema = """
                CREATE TABLE IF NOT EXISTS notification_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notification_routes(
                    id TEXT PRIMARY KEY,name TEXT NOT NULL,url TEXT NOT NULL,
                    sources TEXT NOT NULL,events TEXT NOT NULL,bearer_env TEXT,url_env TEXT,
                    created_at TEXT NOT NULL,start_after INTEGER NOT NULL,cursor INTEGER NOT NULL,
                    timeout REAL NOT NULL,max_attempts INTEGER NOT NULL,
                    base_backoff REAL NOT NULL,max_backoff REAL NOT NULL,
                    last_error TEXT,source_problem TEXT
                );
                CREATE TABLE IF NOT EXISTS notification_deliveries(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,route_id TEXT NOT NULL,
                    record_key TEXT NOT NULL,kind TEXT NOT NULL,event_sequence INTEGER NOT NULL,
                    payload TEXT NOT NULL,payload_sha256 TEXT NOT NULL,idempotency_key TEXT NOT NULL,
                    state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,total_attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt REAL NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                    last_http_status INTEGER,last_error TEXT,operator_actor TEXT,operator_note TEXT,owner TEXT,
                    UNIQUE(route_id,record_key),FOREIGN KEY(route_id) REFERENCES notification_routes(id)
                );
                CREATE INDEX IF NOT EXISTS notification_route_order ON notification_deliveries(route_id,event_sequence,id);
            """
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(notification_routes)")}
            if "url_env" not in columns:
                db.execute("ALTER TABLE notification_routes ADD COLUMN url_env TEXT")
            for key, value in {
                "schema_version": "1",
                "source_store_id": self.source_store_id,
                "source_kind": self.source_kind,
            }.items():
                previous = db.execute(
                    "SELECT value FROM notification_metadata WHERE key=?", (key,)
                ).fetchone()
                if previous is not None and previous[0] != value:
                    raise ValueError(
                        "Outbox schema or bound observation source differs from persisted configuration."
                    )
                db.execute(
                    "INSERT OR IGNORE INTO notification_metadata(key,value) VALUES(?,?)",
                    (key, value),
                )
            for key in ("history_pruned", "history_pruned_through"):
                db.execute(
                    "INSERT OR IGNORE INTO notification_metadata(key,value) VALUES(?,'0')", (key,)
                )
            timestamp, _ = self._now()
            # Exclusive OS ownership proves no other service is still transmitting.
            db.execute(
                "UPDATE notification_deliveries SET state='uncertain',owner=NULL,updated_at=?,"
                "last_error='process_interrupted_during_request' WHERE state='sending'",
                (timestamp,),
            )

    def _open(self):
        if self._closed or self._closing:
            raise ValueError("Notification outbox is closed.")

    def _source_snapshot(self, after, limit):
        with self.observations.connect() as db:
            db.execute("BEGIN")
            markers = dict(
                db.execute(
                    "SELECT key,value FROM observation_metadata WHERE key IN ('source_kind','store_id')"
                )
            )
            if markers.get("source_kind") != self.source_kind:
                raise ValueError("Bound observation source_kind changed.")
            if markers.get("store_id") != self.source_store_id:
                raise ValueError("Bound observation logical store identity changed.")
            marker = db.execute(
                "SELECT seq FROM sqlite_sequence WHERE name='alarm_events'"
            ).fetchone()
            latest = marker[0] if marker else 0
            rows = [
                dict(row) | {"source_kind": self.source_kind}
                for row in db.execute(
                    "SELECT * FROM alarm_events WHERE sequence>? ORDER BY sequence LIMIT ?",
                    (after, limit),
                )
            ]
        return latest, rows

    def create_route(
        self,
        name,
        url=None,
        *,
        url_env=None,
        sources=None,
        events=None,
        bearer_env=None,
        start_after=None,
    ):
        self._open()
        name = _text(name, "Route name", 120)
        if (url is None) == (url_env is None):
            raise ValueError("Provide exactly one webhook URL or URL environment-variable NAME.")
        if url_env is not None:
            if not isinstance(url_env, str) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]{0,127}", url_env
            ):
                raise ValueError(
                    "url_env requires an environment-variable NAME, never its secret value."
                )
            url = ""
        else:
            url = _url(url)
        sources = [] if sources is None else sources
        events = sorted(EVENTS) if events is None else events
        if not isinstance(sources, list) or len(sources) > 256:
            raise ValueError("sources must be a list of at most 256 exact source names.")
        sources = sorted({_text(value, "Source filter", 200) for value in sources})
        if (
            not isinstance(events, list)
            or not events
            or any(type(value) is not str or value not in EVENTS for value in events)
        ):
            raise ValueError("events must contain known alarm event names.")
        events = sorted(set(events))
        if bearer_env is not None and (
            not isinstance(bearer_env, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", bearer_env)
        ):
            raise ValueError(
                "bearer_env requires an environment-variable NAME, never its secret value."
            )
        latest, _ = self._source_snapshot(0, 1)
        cursor = latest if start_after is None else _integer(start_after, "start_after", 0, latest)
        identifier = uuid.uuid4().hex
        timestamp, _ = self._now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute("SELECT COUNT(*) FROM notification_routes").fetchone()[0]
                >= self.max_routes
            ):
                raise ValueError("Notification route capacity reached.")
            db.execute(
                "INSERT INTO notification_routes(id,name,url,sources,events,bearer_env,url_env,created_at,start_after,cursor,"
                "timeout,max_attempts,base_backoff,max_backoff) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    name,
                    url,
                    _json(sources),
                    _json(events),
                    bearer_env,
                    url_env,
                    timestamp,
                    cursor,
                    cursor,
                    self.timeout,
                    self.max_attempts,
                    self.base_backoff,
                    self.max_backoff,
                ),
            )
        return self._route(identifier)

    def _route(self, identifier):
        identifier = _route_id(identifier)
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM notification_routes WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise ValueError("Notification route not found.")
        result = dict(row)
        if result["url_env"]:
            result["url"] = None
        result["sources"], result["events"] = json.loads(row["sources"]), json.loads(row["events"])
        with self._state_lock:
            result["enabled"] = identifier in self._enabled
        result["source_kind"] = self.source_kind
        return result

    def routes(self):
        with self.connect() as db:
            identifiers = [
                row[0]
                for row in db.execute("SELECT id FROM notification_routes ORDER BY created_at,id")
            ]
        return [self._route(identifier) for identifier in identifiers]

    def enable_route(self, identifier, enabled):
        self._open()
        if type(enabled) is not bool:
            raise ValueError("Route enabled must be boolean.")
        route = self._route(identifier)
        if enabled and route["source_problem"]:
            raise ValueError(
                "Observation source regressed; create a new route after reviewing the gap."
            )
        with self._state_lock:
            if enabled:
                self._enabled.add(identifier)
            else:
                self._enabled.discard(identifier)
        return self._route(identifier)

    def status(self):
        with self.connect() as db:
            counts = dict(
                db.execute("SELECT state,COUNT(*) FROM notification_deliveries GROUP BY state")
            )
            metadata = dict(db.execute("SELECT key,value FROM notification_metadata"))
            route_count = db.execute("SELECT COUNT(*) FROM notification_routes").fetchone()[0]
        source_error = None
        try:
            latest, _ = self._source_snapshot(0, 1)
        except (ValueError, OSError, sqlite3.Error):
            latest = None
            source_error = (
                "Bound alarm source is unavailable or its identity changed; dispatch is blocked."
            )
        with self._state_lock:
            enabled = sorted(self._enabled)
        return {
            "profile": "bms.alarm-webhook.v1",
            "source_kind": self.source_kind,
            "routes": route_count,
            "enabled_routes": enabled,
            "active_routes": len(enabled),
            "active": bool(enabled) and not self._closed,
            "closed": self._closed,
            "counts": {state: counts.get(state, 0) for state in sorted(STATES)},
            "latest_alarm_event_sequence": latest,
            "source_error": source_error,
            "history_pruned": int(metadata["history_pruned"]),
            "history_pruned_through": int(metadata["history_pruned_through"]),
            "limits": {"routes": self.max_routes, "deliveries": self.max_deliveries, "cycle": 100},
            "validation": "Webhook receipt only; no alarm acknowledgement or human receipt is inferred. Routes restart disabled.",
        }

    @staticmethod
    def _delivery_row(row):
        result = dict(row)
        result.pop("owner", None)
        result["error"] = result["last_error"]
        raw = result.pop("payload")
        if hashlib.sha256(raw.encode("utf-8")).hexdigest() != result["payload_sha256"]:
            result["payload"] = None
            result["payload_integrity"] = False
        else:
            result["payload"] = json.loads(raw)
            result["payload_integrity"] = True
        return result

    def delivery(self, identifier):
        identifier = _integer(identifier, "Delivery id", 1, 2**63 - 1)
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM notification_deliveries WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise ValueError("Notification delivery not found.")
        return self._delivery_row(row)

    def deliveries(self, *, route_id=None, state=None, after=0, limit=100):
        after = _integer(after, "after", 0, 2**63 - 1)
        limit = _integer(limit, "limit", 1, 1000)
        clauses, arguments = ["id>?"], [after]
        if route_id is not None:
            clauses.append("route_id=?")
            arguments.append(_route_id(route_id))
        if state is not None:
            if not isinstance(state, str) or state not in STATES:
                raise ValueError("Unknown notification state.")
            clauses.append("state=?")
            arguments.append(state)
        with self.connect() as db:
            remaining = db.execute(
                "SELECT COUNT(*) FROM notification_deliveries WHERE " + " AND ".join(clauses),
                arguments,
            ).fetchone()[0]
            total = db.execute(
                "SELECT COUNT(*) FROM notification_deliveries WHERE "
                + (" AND ".join(clauses[1:]) or "1"),
                arguments[1:],
            ).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM notification_deliveries WHERE "
                + " AND ".join(clauses)
                + " ORDER BY id LIMIT ?",
                [*arguments, limit],
            ).fetchall()
        result = [self._delivery_row(row) for row in rows]
        for row in result:
            row.pop("payload", None)
        return {
            "rows": result,
            "total": total,
            "next_after": result[-1]["id"] if len(result) < remaining else None,
        }

    def _operator(self, identifier, note, actor, *, retry):
        self._open()
        identifier = _integer(identifier, "Delivery id", 1, 2**63 - 1)
        note, actor = _text(note, "Operator note", 1000), _text(actor, "Operator", 120)
        timestamp, _ = self._now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM notification_deliveries WHERE id=?", (identifier,)
            ).fetchone()
            allowed = (
                {"failed", "uncertain"}
                if retry
                else {"queued", "retry_wait", "failed", "uncertain", "gap"}
            )
            if row is None or row["state"] not in allowed or (retry and row["kind"] != "event"):
                raise ValueError("Delivery state does not permit this operator action.")
            db.execute(
                "UPDATE notification_deliveries SET state=?,attempts=?,next_attempt=0,updated_at=?,"
                "operator_actor=?,operator_note=?,owner=NULL WHERE id=?",
                (
                    "queued" if retry else "discarded",
                    0 if retry else row["attempts"],
                    timestamp,
                    actor,
                    note,
                    identifier,
                ),
            )
        return self.delivery(identifier)

    def retry(self, identifier, note, *, actor="operator"):
        return self._operator(identifier, note, actor, retry=True)

    def discard(self, identifier, note, *, actor="operator"):
        return self._operator(identifier, note, actor, retry=False)

    def prune_completed(self, through_id, *, limit=1000):
        self._open()
        through_id = _integer(through_id, "through_id", 0, 2**63 - 1)
        limit = _integer(limit, "limit", 1, 1000)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM notification_deliveries WHERE id<=? AND state IN ('delivered','discarded','gap') ORDER BY id LIMIT ?",
                    (through_id, limit),
                )
            ]
            db.executemany(
                "DELETE FROM notification_deliveries WHERE id=?",
                [(identifier,) for identifier in ids],
            )
            if ids:
                db.execute(
                    "UPDATE notification_metadata SET value=CAST(value AS INTEGER)+? WHERE key='history_pruned'",
                    (len(ids),),
                )
                db.execute(
                    "UPDATE notification_metadata SET value=MAX(CAST(value AS INTEGER),?) WHERE key='history_pruned_through'",
                    (max(ids),),
                )
        return {"removed": len(ids), "through_id": max(ids) if ids else None}

    def _insert(self, db, route, key, sequence, kind, payload, timestamp):
        encoded = _json(payload)
        if len(encoded.encode("utf-8")) > MAX_PAYLOAD:
            raise ValueError("Alarm webhook payload exceeds its bounded profile.")
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        existing = db.execute(
            "SELECT payload_sha256 FROM notification_deliveries WHERE route_id=? AND record_key=?",
            (route["id"], key),
        ).fetchone()
        if existing:
            if existing[0] != digest:
                raise ValueError("Persisted event identity has conflicting payload evidence.")
            return False
        if (
            db.execute("SELECT COUNT(*) FROM notification_deliveries").fetchone()[0]
            >= self.max_deliveries
        ):
            return None
        token = hashlib.sha256(f"{route['id']}:{key}".encode()).hexdigest()
        db.execute(
            "INSERT INTO notification_deliveries(route_id,record_key,kind,event_sequence,payload,payload_sha256,"
            "idempotency_key,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                route["id"],
                key,
                kind,
                sequence,
                encoded,
                digest,
                token,
                "queued" if kind == "event" else "gap",
                timestamp,
                timestamp,
            ),
        )
        return True

    def _ingest(self, route, limit):
        latest, events = self._source_snapshot(route["cursor"], limit)
        timestamp, _ = self._now()
        count, gaps, capacity = 0, 0, False
        cursor = route["cursor"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if latest < cursor:
                payload = {
                    "schema": "bms.alarm-retention-gap.v1",
                    "source_kind": self.source_kind,
                    "reason": "source_history_regressed",
                    "previous_cursor": cursor,
                    "latest_sequence": latest,
                }
                result = self._insert(
                    db,
                    route,
                    f"regression:{cursor}:{latest}",
                    cursor,
                    "retention_gap",
                    payload,
                    timestamp,
                )
                if result is not None:
                    db.execute(
                        "UPDATE notification_routes SET source_problem='source_history_regressed',last_error='source_history_regressed' WHERE id=?",
                        (route["id"],),
                    )
                    gaps += int(result)
                else:
                    capacity = True
            else:
                candidates = []
                for event in events:
                    sequence = event["sequence"]
                    if sequence > cursor + 1:
                        candidates.append(("gap", cursor + 1, sequence - 1))
                    candidates.append(("event", sequence, event))
                    cursor = sequence
                if len(events) < limit and latest > cursor:
                    candidates.append(("gap", cursor + 1, latest))
                cursor = route["cursor"]
                for kind, first, value in candidates:
                    if kind == "gap":
                        payload = {
                            "schema": "bms.alarm-retention-gap.v1",
                            "source_kind": self.source_kind,
                            "reason": "source_events_unavailable",
                            "missing_from": first,
                            "missing_through": value,
                        }
                        result = self._insert(
                            db,
                            route,
                            f"gap:{first}:{value}",
                            value,
                            "retention_gap",
                            payload,
                            timestamp,
                        )
                        next_cursor = value
                        if result:
                            gaps += 1
                    else:
                        event = value
                        next_cursor = first
                        if event["event"] not in route["events"] or (
                            route["sources"] and event["source"] not in route["sources"]
                        ):
                            cursor = next_cursor
                            continue
                        payload = {
                            "schema": "bms.alarm-webhook.v1",
                            "route_id": route["id"],
                            "source_kind": self.source_kind,
                            "event": event,
                        }
                        result = self._insert(
                            db, route, f"event:{first}", first, "event", payload, timestamp
                        )
                        if result:
                            count += 1
                    if result is None:
                        capacity = True
                        break
                    cursor = next_cursor
                db.execute(
                    "UPDATE notification_routes SET cursor=?,last_error=? WHERE id=?",
                    (cursor, "delivery_capacity_reached" if capacity else None, route["id"]),
                )
        return count, gaps, capacity

    def _claim(self, route):
        timestamp, now = self._now()
        with self._state_lock:
            if route["id"] not in self._enabled or self._closing:
                return None
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute(
                    "SELECT source_problem FROM notification_routes WHERE id=?", (route["id"],)
                ).fetchone()[0]:
                    return None
                row = db.execute(
                    "SELECT * FROM notification_deliveries WHERE route_id=? AND kind='event' "
                    "AND state NOT IN ('delivered','discarded') ORDER BY event_sequence,id LIMIT 1",
                    (route["id"],),
                ).fetchone()
                if (
                    row is None
                    or row["state"] not in {"queued", "retry_wait"}
                    or row["next_attempt"] > now
                ):
                    return None
                if not self._delivery_row(row)["payload_integrity"]:
                    db.execute(
                        "UPDATE notification_deliveries SET state='failed',last_error='payload_integrity_mismatch',updated_at=? WHERE id=?",
                        (timestamp, row["id"]),
                    )
                    return None
                db.execute(
                    "UPDATE notification_deliveries SET state='sending',owner=?,attempts=attempts+1,total_attempts=total_attempts+1,updated_at=? WHERE id=?",
                    (self._owner, timestamp, row["id"]),
                )
                return dict(
                    db.execute(
                        "SELECT * FROM notification_deliveries WHERE id=?", (row["id"],)
                    ).fetchone()
                )

    def _finish(self, row, route, state, error=None, status=None):
        timestamp, now = self._now()
        if state == "retry_wait" and row["attempts"] >= route["max_attempts"]:
            state, error = "failed", "attempt_limit_reached"
        delay = min(route["max_backoff"], route["base_backoff"] * 2 ** max(0, row["attempts"] - 1))
        with self.connect() as db:
            db.execute(
                "UPDATE notification_deliveries SET state=?,next_attempt=?,updated_at=?,last_error=?,last_http_status=?,owner=NULL WHERE id=? AND state='sending' AND owner=?",
                (
                    state,
                    now + delay if state == "retry_wait" else 0,
                    timestamp,
                    error,
                    status,
                    row["id"],
                    self._owner,
                ),
            )
        return state

    async def _send(self, row, route):
        if route["url_env"]:
            try:
                url = _url(os.environ.get(route["url_env"], ""))
            except ValueError:
                return self._finish(row, route, "failed", "url_environment_unavailable_or_invalid")
        else:
            url = route["url"]
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": row["idempotency_key"],
            "X-BMS-Payload-SHA256": row["payload_sha256"],
        }
        if route["bearer_env"]:
            token = os.environ.get(route["bearer_env"], "")
            if not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token) or len(token) > 8192:
                return self._finish(
                    row, route, "failed", "bearer_environment_unavailable_or_invalid"
                )
            headers["Authorization"] = "Bearer " + token
        try:
            # Overall deadline also bounds peers that continuously trickle headers.
            async with asyncio.timeout(route["timeout"]):
                # The direct public transport avoids AsyncClient's full-URL INFO
                # log line without changing global logging for other clients.
                async with httpx.AsyncHTTPTransport(
                    trust_env=False,
                    retries=0,
                    limits=httpx.Limits(max_connections=1),
                ) as transport:
                    request = httpx.Request(
                        "POST", url, content=row["payload"].encode("utf-8"), headers=headers
                    )
                    response = await transport.handle_async_request(request)
                    try:
                        status = response.status_code
                    finally:
                        await response.aclose()
        except asyncio.CancelledError:
            self._finish(row, route, "uncertain", "request_cancelled_after_claim")
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return self._finish(row, route, "retry_wait", "connection_not_established")
        except (httpx.HTTPError, TimeoutError):
            return self._finish(row, route, "uncertain", "response_or_transmission_uncertain")
        except Exception:
            # Never persist exception text, receiver bodies or authentication values.
            return self._finish(row, route, "uncertain", "unexpected_transport_failure")
        if 200 <= status < 300:
            return self._finish(row, route, "delivered", status=status)
        if status in {408, 425, 429} or 500 <= status < 600:
            return self._finish(row, route, "retry_wait", "receiver_retryable_status", status)
        return self._finish(row, route, "failed", "receiver_rejected_or_redirected", status)

    async def cycle(self, limit=20):
        limit = _integer(limit, "limit", 1, 100)
        self._open()
        result = {
            "enqueued": 0,
            "gaps": 0,
            "capacity_blocked": 0,
            "attempted": 0,
            "delivered": 0,
            "uncertain": 0,
            "failed": 0,
            "retry_wait": 0,
        }
        async with self._cycle_lock:
            self._open()
            # This lock proves no request from this service is still running.
            # A previous cycle may have lost storage after transmitting and
            # failed to save its receipt/cancellation evidence. Never resend it.
            timestamp, _ = self._now()
            with self.connect() as db:
                reconciled = db.execute(
                    "UPDATE notification_deliveries SET state='uncertain',owner=NULL,updated_at=?,"
                    "last_error='abandoned_request_requires_review' WHERE state='sending' AND owner=?",
                    (timestamp, self._owner),
                ).rowcount
                result["uncertain"] += reconciled
            with self._state_lock:
                enabled = sorted(self._enabled)
            if not enabled:
                return result
            start = self._round_robin % len(enabled)
            enabled = enabled[start:] + enabled[:start]
            self._round_robin += 1
            quota = max(1, limit // len(enabled))
            routes = []
            for identifier in enabled:
                route = self._route(identifier)
                if route["source_problem"]:
                    continue
                count, gaps, capacity = self._ingest(route, quota)
                result["enqueued"] += count
                result["gaps"] += gaps
                result["capacity_blocked"] += int(capacity)
                routes.append(route)
            while result["attempted"] < limit:
                progress = False
                for route in routes:
                    if result["attempted"] >= limit:
                        break
                    row = self._claim(route)
                    if row is None:
                        continue
                    result["attempted"] += 1
                    state = await self._send(row, route)
                    result[state] += 1
                    progress = True
                if not progress:
                    break
        return result

    async def close(self):
        if self._closed:
            return
        with self._state_lock:
            self._closing = True
            self._enabled.clear()
        async with self._cycle_lock:
            try:
                timestamp, _ = self._now()
                with self.connect() as db:
                    db.execute(
                        "UPDATE notification_deliveries SET state='uncertain',owner=NULL,updated_at=?,last_error='shutdown_during_request' WHERE state='sending' AND owner=?",
                        (timestamp, self._owner),
                    )
            finally:
                self._closed = True
                self._ownership.close()
