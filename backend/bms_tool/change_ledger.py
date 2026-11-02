"""Read-only, bounded projections of existing local change journals.

The ledger never drives a protocol adapter, creates a plan, resolves a receipt,
or treats unrelated operations as one transaction. Source readers retain their
own verification and recovery contracts.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import sqlite3
import time
from datetime import UTC, datetime
from typing import Literal

from bacpypes3.pdu import Address, IPv4Address
from pydantic import Field, field_validator, model_validator

from .models import StrictModel
from .native_input_ledger import input_reference
from .native_ledger_details import native_reference, recovery_lineage
from .native_point_name_ledger import point_name_reference

Source = Literal["audit", "native", "instance", "schedule", "bbmd", "event", "temco", "command"]
SOURCES = ("audit", "native", "instance", "schedule", "bbmd", "event", "temco", "command")
WINDOW = 16
MAX_CURSOR = 9223372036854775807
AUDIT_BYTES = 1024 * 1024
AUDIT_PREFIXES = (
    "project.",
    "caf.",
    "runtime.",
    "sedona.",
    "native.online.",
    "native.project.",
    "sensor-supply.",
    "temco.program.",
    "bacnet.write.",
    "bacnet.release",
    "bacnet.event_ack.",
)
LABELS = {
    "audit": "Recorded audit event",
    "native": "Native application transfer",
    "instance": "Device instance change",
    "schedule": "Schedule write",
    "bbmd": "BBMD administration",
    "event": "Event acknowledgement",
    "temco": "Temco program operation",
    "command": "Owned point command",
}
PATHS = {
    "native": "/bacnet/controller/native-application/receipts/",
    "instance": "/bacnet/device-instance/receipts/",
    "schedule": "/bacnet/schedules/writes/receipts/",
    "bbmd": "/bacnet/bbmd-admin/receipts/",
    "event": "/bacnet/events/ack/receipts/",
}


class RecordedTarget(StrictModel):
    address: str = Field(min_length=1, max_length=200)
    device: str = Field(default="", max_length=100)
    router: str | None = Field(default=None, max_length=200)
    dnet: int | None = Field(default=None, ge=1, le=65534, strict=True)
    interface_key: str | None = Field(default=None, max_length=4096)

    @field_validator("interface_key")
    @classmethod
    def flat_interface(cls, value):
        if value is None:
            return value
        try:
            body = _json(value)
        except (ValueError, RecursionError):
            raise ValueError("Invalid recorded interface identity.") from None
        if (
            not isinstance(body, dict)
            or len(body) > 20
            or any(
                len(k) > 64
                or not (v is None or type(v) in (str, int, bool))
                or isinstance(v, str)
                and len(v) > 200
                for k, v in body.items()
            )
        ):
            raise ValueError("Use a bounded flat interface configuration.")
        return value


class LedgerQuery(StrictModel):
    source: Literal["all", *SOURCES] = "all"
    text: str = Field(default="", max_length=200)
    outcome: Literal["all", "attention", "verified", "other"] = "all"
    selected_target: RecordedTarget | None = None
    before: dict[Source, str] = Field(default_factory=dict, max_length=8)
    exhausted: list[Source] = Field(default_factory=list, max_length=8)

    @field_validator("text")
    @classmethod
    def plain_query(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError("Use a single-line search.")
        return value.strip()

    @model_validator(mode="after")
    def cursor_bounds(self):
        if len(set(self.exhausted)) != len(self.exhausted) or set(self.before) & set(
            self.exhausted
        ):
            raise ValueError("Ledger cursors must identify each source once.")
        for source, value in self.before.items():
            if source in ("event", "temco", "command"):
                if (
                    not value
                    or len(value) > 128
                    or not all(c.isalnum() or c in "_-" for c in value)
                ):
                    raise ValueError("Invalid in-memory ledger cursor.")
            elif not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= MAX_CURSOR:
                raise ValueError("Invalid journal ledger cursor.")
        return self


def _text(value, maximum=240):
    return str(value)[:maximum] if isinstance(value, (str, int, float, bool)) else ""


def _json(raw):
    def reject(value):
        raise ValueError("Nonfinite journal value: " + value)

    return json.loads(raw, parse_constant=reject)


def _redacted(value, depth=0):
    if depth > 24:
        return "[nested evidence omitted]"
    if isinstance(value, dict):
        return {
            str(k): "[redacted]"
            if any(
                part in str(k).lower()
                for part in (
                    "password",
                    "credential",
                    "authorization",
                    "secret",
                    "token",
                    "api_key",
                )
            )
            else _redacted(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redacted(v, depth + 1) for v in value[:10000]]
    return value


def _endpoint(value):
    try:
        return str(IPv4Address(value))
    except (ValueError, TypeError):
        return _text(value, 200)


def _station(target):
    if not target or not target.get("address"):
        return None
    try:
        address = Address(target["address"])
        station = (address.addrType, address.addrNet, bytes(address.addrAddr).hex())
    except (ValueError, TypeError, AttributeError):
        station = ("opaque", _text(target.get("address"), 200))
    return (
        station,
        _endpoint(target.get("router")) if target.get("router") else None,
        target.get("dnet"),
    )


def _target(body):
    value = body.get("target")
    if not isinstance(value, dict):
        value = {"address": body.get("address")}
    address = _text(value.get("address"), 200)
    if not address:
        return None
    config = body.get("connector_config", body.get("config"))
    config = config if isinstance(config, dict) else {}
    identity = body.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    remote = ":" in address and "." not in address
    return {
        "address": address,
        "device": _text(value.get("device") or identity.get("device"), 100),
        "router": value.get("router", config.get("router") if remote else None),
        "dnet": value.get("dnet", config.get("dnet") if remote else None),
    }


def _interface(body):
    config = body.get("connector_config", body.get("config"))
    if not isinstance(config, dict) or not config:
        return None, "Original interface not recorded"
    digest = hashlib.sha256(
        json.dumps(config, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    if config.get("transport") == "mstp":
        label = f"MS/TP {_text(config.get('port'), 200)} · {_text(config.get('baudrate'))} baud · client MAC {_text(config.get('mac'))}"
    else:
        label = "BACnet/IP bind " + (_text(config.get("local_address"), 200) or "not recorded")
    return digest, label


def _matches(row, selected):
    if _station(row["target"]) != _station(selected.model_dump()):
        return False
    try:
        address = Address(selected.address)
        local_station = address.addrType == 2 and not hasattr(address, "addrTuple")
    except (ValueError, TypeError):
        local_station = False
    if local_station:
        # A bare serial MAC is reused across trunks; route fields alone cannot
        # bind it. Missing historical interface evidence never proves a match.
        if not selected.interface_key or not row["interface_sha256"]:
            return False
        expected = hashlib.sha256(
            json.dumps(_json(selected.interface_key), sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        return expected == row["interface_sha256"]
    return True


class ChangeLedger:
    def __init__(self, store, *, native, instances, schedules, bbmd, events, temco, bacnet):
        self.store, self.native, self.instances = store, native, instances
        self.schedules, self.bbmd, self.events = schedules, bbmd, events
        self.temco, self.bacnet = temco, bacnet

    def _heads(self, source, before):
        path = self.store.db
        if source == "bbmd":
            if self.bbmd is None:
                raise ValueError("BBMD administration journal is unavailable.")
            path = self.bbmd.journal.db
        table, key, path = {
            "audit": ("audit", "sequence", self.store.db),
            "native": ("application_transfers", "id", self.store.db),
            "instance": ("device_instance_changes", "id", self.store.db),
            "schedule": ("native_weekly_writes", "id", self.store.db),
            "bbmd": ("receipts", "id", path),
        }[source]
        # Read mode cannot create a missing source database or append evidence.
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25) as db:
            deadline = time.monotonic() + 0.25
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            where, params = [], []
            if before:
                where.append("rowid < ?")
                params.append(int(before))
            if source == "audit":
                where.append("(" + " OR ".join("operation LIKE ?" for _ in AUDIT_PREFIXES) + ")")
                params.extend(prefix + "%" for prefix in AUDIT_PREFIXES)
            sql = f"SELECT rowid,{key} FROM {table}"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY rowid DESC LIMIT ?"
            rows = db.execute(sql, [*params, WINDOW + 1]).fetchall()
        return rows[:WINDOW], str(rows[WINDOW - 1][0]) if len(rows) > WINDOW else None

    def _audit(self, identifier):
        if (
            not identifier.isascii()
            or not identifier.isdecimal()
            or not 1 <= int(identifier) <= MAX_CURSOR
        ):
            raise ValueError("Invalid audit record identifier.")
        with self.store.connect(timeout=0.25) as db:
            row = db.execute(
                "SELECT sequence,created,operation,previous_hash,entry_hash,"
                "CASE WHEN length(CAST(detail AS BLOB))<=? THEN detail ELSE NULL END AS detail "
                "FROM audit WHERE sequence=?",
                (AUDIT_BYTES, int(identifier)),
            ).fetchone()
            previous = db.execute(
                "SELECT entry_hash FROM audit WHERE sequence<? ORDER BY sequence DESC LIMIT 1",
                (int(identifier),),
            ).fetchone()
        if row is None or row["detail"] is None:
            raise ValueError("Audit record is unavailable or exceeds the ledger byte bound.")
        if not row["operation"].startswith(AUDIT_PREFIXES):
            raise ValueError("This audit event is outside the change ledger scope.")
        expected = hashlib.sha256(
            (row["previous_hash"] + row["created"] + row["operation"] + row["detail"]).encode()
        ).hexdigest()
        if expected != row["entry_hash"] or row["previous_hash"] != (
            previous[0] if previous else "0" * 64
        ):
            raise ValueError("Audit entry or predecessor reference failed integrity checking.")
        detail = _json(row["detail"])
        if not isinstance(detail, dict):
            raise ValueError("Audit record has no structured operation evidence.")
        return dict(row) | {"detail": detail}

    def _load(self, source, identifier, memory=None):
        if source == "audit":
            return self._audit(identifier)
        if source == "native":
            return self.native.storage.receipt(identifier, include_events=False)
        if source == "instance":
            return self.instances.journal.receipt(identifier)
        if source == "schedule":
            return _json(self.schedules.journal.receipt(identifier))
        if source == "bbmd":
            return self.bbmd.journal.get(identifier)
        if memory is None or identifier not in memory.get(source, {}):
            raise ValueError("The retained or session-scoped operation is no longer available.")
        return memory[source][identifier]

    def _summary(self, source, identifier, record):
        pending = False
        native_kind = None
        native_metadata = {}
        if source == "audit":
            body = record["detail"]
            label, state = record["operation"], body.get("status", "recorded")
            pending = bool(body.get("may_have_applied") and state != "verified")
            created = record["created"]
        elif source == "native":
            body = record["intent"]
            latest = record.get("latest_readback") or record.get("result") or body
            pending = record["pending"]
            labels = {
                "instance": "Native controller instance change",
                "name": "Native controller name change",
                "signal-default": "Native Real default transfer",
                "boolean-default": "Native Boolean default transfer",
                "wire-source": "Native wire source transfer",
                "input": "Native input configuration transfer",
                "point-name": "Native point-name transfer",
            }
            candidate = body.get("change_kind", "instance")
            native_kind = (
                candidate if isinstance(candidate, str) and candidate in labels else "unsupported"
            )
            label = labels.get(native_kind, "Native application transfer (unsupported operation)")
            selection = body.get("wire_edit" if native_kind == "wire-source" else "default_edit")
            native_metadata = native_reference(native_kind, selection)
            if native_kind == "input":
                native_metadata = input_reference(body)
            elif native_kind == "point-name":
                native_metadata = point_name_reference(body)
            recovery = recovery_lineage(body, native_kind, native_metadata)
            if recovery is not None:
                native_metadata["native_recovery"] = recovery
            state, created = latest["status"], body["created_at"]
        elif source == "instance":
            body = record["attempt"]
            pending = self.instances.pending(record)
            resolved = body.get("readback", {}).get("status") == "verified_new" or any(
                r.get("readback", {}).get("status") == "verified_new" for r in record["readbacks"]
            )
            state = "verified" if resolved else body["status"]
            label, created = LABELS[source], body["created_at"]
        else:
            body = record
            label = _text(body.get("operation")) if source == "bbmd" else LABELS[source]
            state = body.get("status", body.get("state", "unknown"))
            created = body.get("created_at", body.get("started_at", body.get("updated", "")))
            pending = bool(body.get("may_have_applied") and state != "verified")
            if source == "bbmd":
                state = body.get("outcome", "unknown")
                pending = bool(
                    body.get("active")
                    or body.get("dispatch_possible")
                    and state != "desired-state-observed"
                )
            elif source == "temco":
                pending = state not in ("complete", "restored", "preflight_failed")
            elif source == "command":
                pending = True  # Even a verified active override still requires owned release.
        outcome = (
            "attention"
            if pending
            else "verified"
            if state in ("verified", "complete", "restored", "desired-state-observed")
            and source != "audit"
            else "other"
        )
        target = _target(body)
        if source == "bbmd":
            target = {
                "address": _text(body.get("endpoint")),
                "device": "",
                "router": None,
                "dnet": None,
            }
        readback = body.get("readback")
        readback = readback if isinstance(readback, dict) else {}
        if source == "native":
            latest = record.get("latest_readback") or record.get("result") or {}
            readback = latest.get("readback") or latest
        elif source == "instance" and resolved:
            readback = {"status": "verified_new"}
        elif source == "bbmd" and state in ("desired-state-observed", "different-state-observed"):
            readback = {"status": state}
        elif source == "command" and state == "active" and "slot" in body:
            readback = {"status": "recorded priority-slot verification"}
        review = body.get("review")
        review = review if isinstance(review, dict) else {}
        interface_digest, interface_label = _interface(body)
        dispatch = (
            "possible"
            if pending and source != "command"
            else "entered"
            if body.get("dispatch_started") is True
            else "not entered"
            if body.get("dispatch_started") is False
            else "not recorded"
        )
        if source == "native":
            # Later observation resolves state, not whether the original attempt
            # entered dispatch. Prefer its retained result over the prior intent.
            attempt = record.get("result")
            possible = attempt.get("may_have_applied") if isinstance(attempt, dict) else None
            if type(possible) is not bool:
                possible = body.get("may_have_applied")
            if type(possible) is bool:
                dispatch = "possible" if possible else "not entered"
        return {
            "key": source + ":" + identifier,
            "source": source,
            "id": identifier,
            "label": _text(label),
            "native_change_kind": native_kind,
            "created_at": _text(created, 80),
            "state": _text(state, 100),
            "outcome": outcome,
            "kind": "audit"
            if source == "audit"
            else "ownership"
            if source == "command"
            else "receipt",
            "target": target,
            "object": _text(body.get("object_id", body.get("object")), 100),
            "local_source": _text(
                body.get("source_sha256", body.get("original_sha256", body.get("id", ""))), 100
            )
            if source == "audit"
            else "",
            "pending": pending,
            "integrity": "entry seal and previous-hash link"
            if source == "audit"
            else "source reader"
            if source not in ("command", "temco", "event")
            else "session snapshot"
            if source == "event"
            else "retained local snapshot",
            "detail_path": PATHS.get(source, "/changes/records/" + source + "/") + identifier,
            "session_scoped": source == "event",
            "interface_sha256": interface_digest,
            "interface_label": interface_label,
            "review_recorded": bool(body.get("review_sha256") or review.get("review_sha256")),
            "dispatch": dispatch,
            "readback": _text(readback.get("status"), 100) or "not recorded",
            **native_metadata,
        }

    def memory(self, request=None, *, only=None):
        # Called synchronously on the event loop before any disk work is awaited.
        # Never invoke status(), require(), or a protocol/credential method here.
        sources = {
            "event": self.events._receipts,
            "temco": self.temco.operations,
            "command": self.bacnet.commands,
        }
        result = {}
        for source, values in sources.items():
            if only is not None:
                result[source] = {only: copy.deepcopy(values[only])} if only in values else {}
                continue
            before = request.before.get(source)
            keys = sorted((k for k in values if not before or k < before), reverse=True)[
                : WINDOW + 1
            ]
            result[source] = {key: copy.deepcopy(values[key]) for key in keys}
        return result

    def query(self, request, memory):
        started = time.monotonic()
        rows, errors, coverage = [], [], []
        cursor, exhausted = request.before.copy(), set(request.exhausted)
        wanted = {s for s in SOURCES if request.source in ("all", s)}
        for source in SOURCES:
            if source not in wanted or source in exhausted:
                continue
            if time.monotonic() - started > 5:
                errors.append(
                    {
                        "source": source,
                        "error": "Ledger read budget reached; narrow the source filter.",
                    }
                )
                continue
            try:
                if source in memory:
                    keys = sorted(
                        (
                            key
                            for key in memory[source]
                            if not request.before.get(source) or key < request.before[source]
                        ),
                        reverse=True,
                    )
                    heads = [(key, key) for key in keys[:WINDOW]]
                    next_value = keys[WINDOW - 1] if len(keys) > WINDOW else None
                else:
                    heads, next_value = self._heads(source, request.before.get(source))
                visited, budget_reached = 0, False
                for position, identifier in heads:
                    if time.monotonic() - started > 5:
                        budget_reached = True
                        errors.append(
                            {
                                "source": source,
                                "error": "Ledger read budget reached; more records remain in the next window.",
                            }
                        )
                        break
                    visited += 1
                    cursor[source] = str(position)
                    identifier = str(identifier)
                    try:
                        if (
                            len(identifier) > 128
                            or not identifier.isascii()
                            or not all(c.isalnum() or c in "_-" for c in identifier)
                        ):
                            raise ValueError("Invalid retained record identifier.")
                        record = self._load(source, identifier, memory)
                        row = self._summary(source, identifier, record)
                    except (
                        ValueError,
                        KeyError,
                        TypeError,
                        AttributeError,
                        sqlite3.Error,
                        OSError,
                        UnicodeError,
                        RecursionError,
                    ):
                        errors.append(
                            {
                                "source": source,
                                "id": identifier,
                                "error": "This local source record could not be validated; inspect its original tool.",
                            }
                        )
                        continue
                    if request.selected_target and not _matches(row, request.selected_target):
                        continue
                    if request.outcome != "all" and row["outcome"] != request.outcome:
                        continue
                    if (
                        request.text.casefold()
                        not in json.dumps(row, ensure_ascii=False).casefold()
                    ):
                        continue
                    rows.append(row)
                more = bool(next_value or budget_reached)
                coverage.append({"source": source, "read": visited, "more": more})
                if not more:
                    exhausted.add(source)
                    cursor.pop(source, None)
            except (sqlite3.Error, ValueError, OSError, AttributeError, TypeError):
                errors.append(
                    {
                        "source": source,
                        "error": "Local journal is unavailable or exceeded its read budget.",
                    }
                )
                exhausted.add(source)
                cursor.pop(source, None)
        rows.sort(key=lambda r: (r["created_at"], r["key"]), reverse=True)
        # Exhausted sources stay exhausted on subsequent windows; they must not restart.
        return {
            "profile": "local-change-ledger/1",
            "read_only": True,
            "field_requests": 0,
            "captured_at": datetime.now(UTC).isoformat(),
            "rows": rows,
            "errors": errors,
            "coverage": coverage,
            "next_cursor": {"before": cursor, "exhausted": sorted(exhausted)}
            if wanted - exhausted
            else None,
            "window_per_source": WINDOW,
            "scope": "Bounded local record snapshots, not a batch transaction or current device-health check. Search covers this window; older windows may contain more matches.",
        }

    async def read(self, request):
        memory = self.memory(request)
        return await asyncio.to_thread(self.query, request, memory)

    async def detail(self, source, identifier):
        if source not in SOURCES or source in PATHS:
            raise ValueError("Use the existing source receipt endpoint for this record.")
        if (
            not identifier
            or len(identifier) > 128
            or not all(c.isalnum() or c in "_-" for c in identifier)
        ):
            raise ValueError("Invalid ledger record identifier.")
        memory = self.memory(only=identifier)
        record = await asyncio.to_thread(self._load, source, identifier, memory)
        return {
            "profile": "local-change-ledger-detail/1",
            "source": source,
            "id": identifier,
            "read_only": True,
            "redacted": True,
            "scope": "Filtered local evidence view. Secret/token fields are redacted; use original tools for recovery.",
            "record": _redacted(record),
        }
