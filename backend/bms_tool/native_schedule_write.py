"""Reviewed, one-attempt replacement of one existing native weekly day.

Fresh reads reduce stale-write risk. BACnet WriteProperty has no compare-and-swap
and a negative reply cannot prove unchanged remote configuration. No evaluator,
native CAF compilation, automatic retry, inverse write or output rollback exists
in this profile. All post-dispatch receipts preserve that uncertainty.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import secrets
import sqlite3
import time
import unicodedata
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from bacpypes3.apdu import ErrorRejectAbortNack, SimpleAckPDU, WritePropertyRequest
from bacpypes3.basetypes import DailySchedule
from bacpypes3.object import DeviceObject, ScheduleObject
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import ObjectIdentifier, TagList, Unsigned
from pydantic import Field, field_validator

from .bacnet_exchange import confirmed_exchange
from .device_details import DeviceDetails, DeviceDetailsRequest
from .models import StrictModel
from .native_schedule_library import (
    CONTEXT,
    NativeScheduleLibrary,
    WeeklyDayDraft,
    decoded_row,
    digest,
    encoded,
    identifier,
    source_report,
    strict_json,
)
from .native_schedule_library import (
    RULES_SHA256 as DRAFT_RULES_SHA256,
)
from .native_schedule_wire import ScheduleWriteWire, apdu_bytes
from .property_evidence import PropertyEvidence, ReadBudget
from .schedule_inventory import CLOCK

PROFILE = "native-schedule-reviewed-weekly-day-write/1"
SCOPE = (
    "One existing Schedule weekly-schedule index1..7 over an already-open plain IPv4 "
    "interface or explicitly pinned router/DNET:MAC. Fresh sequential native-tag checks, "
    "one unsegmented WriteProperty attempt, bounded readback and durable local intent. "
    "No compare-and-swap, retry, rollback, native CAF generation, schedule evaluation, "
    "new object, Calendar/exception/context/target edit or physical manufacturer acceptance."
)
PLAN_SECONDS, MAX_PLANS, MAX_APDU = 30, 16, 480
MAX_REQUESTS, MAX_EVIDENCE_BYTES = 128, 1536 * 1024
JOURNAL_RECORDS, JOURNAL_BYTES, RECORD_BYTES = 64, 64 * 1024 * 1024, 8 * 1024 * 1024
MAX_RECEIPT_VALUES = 1000000
STATIC_CONTEXT = tuple(
    key for key in CONTEXT if key not in ("present-value", "status-flags", "reliability")
)
RULES = {
    "profile": PROFILE,
    "draft_rules_sha256": DRAFT_RULES_SHA256,
    "stack": "bacpypes3/0.0.110",
    "operation": "Existing weekly-schedule index1..7 only; one unsegmented service15, no request priority or retries.",
    "conflicts": "Fresh exact static native tags and all seven days/exceptions; sequential observations, never CAS.",
    "dynamic_observations": "Present_Value, device clocks, status flags and reliability are typed observations, not static equality guards.",
    "responses": "Original-Unicast10, exact pinned next hop/socket/NPDU source/invoke/service; no reserved NPDU bits; server-origin Abort only.",
    "uncertainty": "Every admitted dispatch may have applied, including Error/Reject/Abort and matching readback after ACK loss.",
    "reviewed_sources": {
        "bacpypes3/apdu.py": "9e3cedc0f5f088cf500bd20e24ee6dca8f3eedfb0ad5626cd8d4639fa0c8cf7c",
        "bacpypes3/appservice.py": "2ef1294f0c7b0e217df65df5b34e0adb2547b1d7964a425e422b156af4ff9b87",
        "CCT18/LIT-12011147/PDF235-236,247-248": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
        "SCT19/LIT-12011964/PDF328-329": "a8bd468067d46ad3509fdd40c73dcef967a8a7d517b43c5bd4561af45fa794d4",
    },
}
RULES_SHA256 = digest(RULES)


def utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


def seal(body):
    result = copy.deepcopy(body)
    result["evidence_sha256"] = digest(result)
    return result


class WeeklyWritePreview(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    draft_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    operator_name: str = Field(min_length=1, max_length=48)
    rationale: str = Field(min_length=1, max_length=240)

    @field_validator("operator_name", "rationale")
    @classmethod
    def visible_declaration(cls, value):
        value = value.strip()
        if not value or any(
            unicodedata.category(char).startswith("C") or unicodedata.category(char) in ("Zl", "Zp")
            for char in value
        ):
            raise ValueError("Enter a visible single-line operator declaration.")
        return value


class WeeklyWriteApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WeeklyWriteCancel(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class WeeklyWriteReconcile(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    receipt_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class WeeklyWriteJournal:
    """Bounded durable intent/result rows; no eviction or implicit deletion."""

    def __init__(self, store):
        self.store = store
        with store.connect(timeout=0.25) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS native_weekly_writes("
                "id TEXT PRIMARY KEY, intent BLOB, result BLOB, created TEXT NOT NULL)"
            )

    @staticmethod
    def _limits(db, size, *, replacing=0, adding=True, reserve=0):
        count, used, pending = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(COALESCE(LENGTH(intent),0)+COALESCE(LENGTH(result),0)),0), "
            "SUM(CASE WHEN intent IS NOT NULL AND result IS NULL THEN 1 ELSE 0 END) "
            "FROM native_weekly_writes"
        ).fetchone()
        used += (pending or 0) * RECORD_BYTES
        if (
            size > RECORD_BYTES
            or (adding and count >= JOURNAL_RECORDS)
            or used - replacing + size + reserve > JOURNAL_BYTES
        ):
            raise ValueError(
                "Weekly-write journal capacity reached; no automatic eviction is performed."
            )

    def intent(self, receipt):
        # A crash after this commit cannot establish whether dispatch occurred.
        raw = encoded(seal({**receipt, "journal_state": "intent_only", "may_have_applied": True}))
        self._checked(raw, receipt["id"])
        with self.store.connect(timeout=0.25) as db:
            db.execute("BEGIN IMMEDIATE")
            self._limits(db, len(raw), reserve=RECORD_BYTES)
            db.execute(
                "INSERT INTO native_weekly_writes(id,intent,result,created) VALUES(?,?,NULL,?)",
                (receipt["id"], raw, utc()),
            )
        return hashlib.sha256(raw).hexdigest()

    def result(self, receipt):
        receipt = copy.deepcopy(receipt)
        with self.store.connect(timeout=0.25) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT intent,result FROM native_weekly_writes WHERE id=?", (receipt["id"],)
            ).fetchone()
            if old and old[1] is not None:
                raise ValueError("A sealed weekly-write result is immutable.")
            if old and old[0] is not None:
                self._checked(old[0], receipt["id"])
                intent_sha = hashlib.sha256(old[0]).hexdigest()
                if receipt.get("intent_sha256", intent_sha) != intent_sha:
                    raise ValueError(
                        "Weekly-write result intent hash differs from retained intent."
                    )
                receipt["intent_sha256"] = intent_sha
            raw = encoded(seal(receipt))
            self._checked(raw, receipt["id"])
            self._limits(
                db,
                len(raw),
                replacing=RECORD_BYTES if old and old[0] is not None else 0,
                adding=old is None,
            )
            if old is None:
                db.execute(
                    "INSERT INTO native_weekly_writes(id,result,created) VALUES(?,?,?)",
                    (receipt["id"], raw, utc()),
                )
            else:
                db.execute(
                    "UPDATE native_weekly_writes SET result=? WHERE id=?", (raw, receipt["id"])
                )
        return raw

    @staticmethod
    def _checked(raw, id):
        if type(raw) is not bytes or not raw or len(raw) > RECORD_BYTES:
            raise ValueError("Weekly-write journal requires a bounded nonempty BLOB body.")
        body = strict_json(raw, RECORD_BYTES, max_values=MAX_RECEIPT_VALUES)
        if (
            type(body) is not dict
            or body.get("id") != id
            or body.get("profile") != PROFILE
            or body.get("evidence_sha256")
            != digest({k: v for k, v in body.items() if k != "evidence_sha256"})
        ):
            raise ValueError("Weekly-write journal seal failed.")
        return body

    def receipt(self, id):
        if (
            type(id) is not str
            or len(id) != 32
            or any(char not in "0123456789abcdef" for char in id)
        ):
            raise ValueError("Invalid weekly-write receipt identifier.")
        with self.store.connect(timeout=0.25) as db:
            lengths = db.execute(
                "SELECT LENGTH(intent),LENGTH(result) FROM native_weekly_writes WHERE id=?", (id,)
            ).fetchone()
            if lengths and any(size is not None and size > RECORD_BYTES for size in lengths):
                raise ValueError("Weekly-write journal record exceeds its byte bound.")
            row = db.execute(
                "SELECT intent,result FROM native_weekly_writes WHERE id=?", (id,)
            ).fetchone()
        if row is None:
            raise ValueError("Weekly-write receipt is unavailable.")
        raw = row[1] if row[1] is not None else row[0]
        body = self._checked(raw, id)
        if row[0] is not None:
            self._checked(row[0], id)
        if (
            row[1] is not None
            and row[0] is not None
            and body.get("intent_sha256") != hashlib.sha256(row[0]).hexdigest()
        ):
            raise ValueError("Weekly-write result does not bind its retained intent bytes.")
        if row[1] is None:
            body.pop("evidence_sha256")
            snapshot = {
                key: body.get(key)
                for key in (
                    "status",
                    "dispatch_started",
                    "protocol_status",
                    "protocol_accepted",
                    "readback",
                )
            }
            body.update(
                status="unknown",
                may_have_applied=True,
                dispatch_started=None,
                protocol_status="unknown",
                protocol_accepted=None,
                readback={
                    "status": "unknown",
                    "reason": "Durable intent has no completed result; readback execution/outcome is unresolved.",
                },
                intent_snapshot=snapshot,
                intent_sha256=hashlib.sha256(raw).hexdigest(),
                journal_state="intent_only",
                errors=[
                    "Durable intent has no sealed result. Dispatch and remote outcome are unresolved; no automatic retry is permitted."
                ],
            )
            return encoded(seal(body))
        return raw

    def status(self):
        with self.store.connect(timeout=0.25) as db:
            rows = db.execute(
                "SELECT id,created,result IS NULL AS unresolved FROM native_weekly_writes ORDER BY created DESC LIMIT ?",
                (JOURNAL_RECORDS,),
            ).fetchall()
            used = db.execute(
                "SELECT COALESCE(SUM(COALESCE(LENGTH(intent),0)+COALESCE(LENGTH(result),0)),0) FROM native_weekly_writes"
            ).fetchone()[0]
        return {
            "records": [dict(row) for row in rows],
            "used_bytes": used,
            "reserved_result_bytes": sum(bool(row["unresolved"]) for row in rows) * RECORD_BYTES,
            "max_records": JOURNAL_RECORDS,
            "max_bytes": JOURNAL_BYTES,
            "record_bytes": RECORD_BYTES,
            "record_values": MAX_RECEIPT_VALUES,
            "record_depth": 64,
            "automatic_eviction": False,
        }


class NativeWeeklyDayWrites:
    def __init__(
        self, bacnet, store, library, *, timeout=1.0, operation_timeout=15.0, request_gap=0.02
    ):
        self.bacnet, self.store, self.library = bacnet, store, library
        self.path = DeviceDetails(
            bacnet,
            store,
            timeout=timeout,
            operation_timeout=operation_timeout,
            request_gap=request_gap,
        )
        self.reader = PropertyEvidence(self.path)
        self.wire = ScheduleWriteWire(self.reader)
        self.timeout, self.operation_timeout, self.request_gap = (
            timeout,
            operation_timeout,
            request_gap,
        )
        self.journal = WeeklyWriteJournal(store)
        self.plans, self.cancelled = OrderedDict(), OrderedDict()
        self.active = None

    def status(self):
        return {
            "profile": PROFILE,
            "rules": RULES,
            "rules_sha256": RULES_SHA256,
            "scope": SCOPE,
            "active_operation": self.active["id"] if self.active else None,
            "automatic_retries": False,
            "limits": {
                "plan_seconds": PLAN_SECONDS,
                "plans": MAX_PLANS,
                "apdu_bytes": MAX_APDU,
                "request_seconds": self.timeout,
                "operation_seconds": self.operation_timeout,
                "requests": MAX_REQUESTS,
                "evidence_bytes": MAX_EVIDENCE_BYTES,
            },
            "journal": self.journal.status(),
        }

    def cancel(self, operation_id, *, reason="cancelled"):
        WeeklyWriteCancel(operation_id=operation_id)
        self.cancelled[operation_id] = True
        while len(self.cancelled) > 64:
            self.cancelled.popitem(last=False)
        found = self.active is not None and self.active["id"] == operation_id
        if found:
            self.active["reason"] = reason
            self.active["task"].cancel()
        return {
            "operation_id": operation_id,
            "cancel_requested": found,
            "note": "Cancellation cannot undo a transmitted configuration write.",
        }

    async def close(self):
        self.plans.clear()
        if self.active:
            task = self.active["task"]
            self.cancel(self.active["id"], reason="interface_changed")
            if task is not asyncio.current_task():
                await asyncio.gather(task, return_exceptions=True)

    @asynccontextmanager
    async def _operation(self, id):
        if self.active is not None or id in self.cancelled:
            raise ValueError("Weekly write operation is active or this operation ID was cancelled.")
        active = {
            "id": id,
            "task": asyncio.current_task(),
            "reason": None,
            "deadline": asyncio.get_running_loop().time() + self.operation_timeout,
        }
        self.active = active
        try:
            async with asyncio.timeout(self.operation_timeout):
                yield active
        finally:
            if self.active is active:
                self.active = None

    def _reference(self, draft_id, *, saved_review=None):
        identifier(draft_id)
        raw = (
            self.library.export_review(draft_id) if saved_review is None else encoded(saved_review)
        )
        review = strict_json(raw, 256 * 1024)
        if type(review) is not dict or review.get("id") != draft_id:
            raise ValueError("Selected native draft identity changed.")
        regenerated = self.library._review(WeeklyDayDraft(**review["request"]), retain=False)
        if encoded(regenerated) != raw:
            raise ValueError("Retained native draft/source proof changed; review again.")
        report = source_report(self.library.source(review["source"]["capture_id"]))
        target = DeviceDetailsRequest(**report["target"])
        config = self.bacnet.config or {}
        if config.get("transport") == "mstp" or config.get("bbmd_address"):
            raise ValueError(
                "Weekly configuration writes require plain IPv4 without BBMD or serial."
            )
        self.bacnet.require()
        return review, report, target

    def _pin(self, session):
        self.reader.guard(session)
        layer = session["evidence_layer"]
        return (
            session["app"],
            session["evidence_adapter"],
            layer,
            layer.server,
            session["evidence_socket"],
            layer.server.local_protocol,
        )

    def _same_pin(self, session, pin):
        actual = self._pin(session)
        return len(actual) == len(pin) and all(
            left is right for left, right in zip(actual, pin, strict=True)
        )

    @staticmethod
    def _static(report, object_id):
        props, _, _ = NativeScheduleLibrary._weekly_context(report, object_id)

        def raw(row, prop, index=None):
            return decoded_row(row, object_id, prop, index)[1].hex()

        result = {key: raw(props[key], key) for key in STATIC_CONTEXT}
        for key in ("weekly-schedule", "exception-schedule"):
            result[key] = {
                "count": raw(props[key]["count_read"], key, 0),
                "elements": [raw(row, key, i) for i, row in enumerate(props[key]["elements"], 1)],
            }
        return result

    async def _fresh(self, session, target, object_id, *, report=None):
        budget = ReadBudget(max_requests=MAX_REQUESTS, max_bytes=MAX_EVIDENCE_BYTES)
        props = {}
        report = {} if report is None else report
        report.update(
            {
                "target": target.model_dump(),
                "identity_verified": False,
                "objects": [{"object": object_id, "identity_verified": False, "properties": props}],
                "observed_at": utc(),
                "device_clock": {},
                "complete": False,
                "failed_reads": [],
            }
        )

        async def read(obj, prop, index=None, *, required=True):
            report["pending_read"] = {
                "object": obj,
                "property": prop,
                "array_index": index,
                "requested_at": utc(),
            }
            try:
                value, row = await self.reader.read(
                    session,
                    budget,
                    obj,
                    prop,
                    DeviceObject if obj == target.device else ScheduleObject,
                    index,
                    timeout=self.timeout,
                    request_gap=self.request_gap,
                )
            finally:
                report["budget"] = budget.snapshot()
                report["last_observed_at"] = utc()
            report.pop("pending_read", None)
            if row["status"] != "ok" or row.get("transport_evidence") is None:
                report["failed_reads"].append(row)
            if required and (row["status"] != "ok" or row.get("transport_evidence") is None):
                raise ValueError(
                    "Fresh native property unavailable: "
                    + prop
                    + ": "
                    + row.get("error", row["status"])
                )
            return value, row

        identity, report["device_identity"] = await read(target.device, "object-identifier")
        if identity != ObjectIdentifier(target.device):
            raise ValueError("Fresh Device identity differs from captured selection.")
        report["identity_verified"] = True
        maximum, report["remote_max_apdu"] = await read(target.device, "max-apdu-length-accepted")
        if not isinstance(maximum, Unsigned) or not 50 <= int(maximum) <= 65535:
            raise ValueError(
                "Remote maximum APDU is unavailable/outside this numbered-byte profile."
            )
        identity, props["object-identifier"] = await read(object_id, "object-identifier")
        if identity != ObjectIdentifier(object_id):
            raise ValueError("Fresh Schedule identity differs from captured selection.")
        report["objects"][0]["identity_verified"] = True
        for prop in CONTEXT:
            _, props[prop] = await read(object_id, prop)
        for prop, expected in (("weekly-schedule", 7), ("exception-schedule", None)):
            count, row = await read(object_id, prop, 0)
            elements = []
            array = props[prop] = {
                "status": "reading",
                "complete": False,
                "count_read": row,
                "elements": elements,
            }
            if (
                not isinstance(count, Unsigned)
                or count > 32
                or (expected is not None and count != expected)
            ):
                raise ValueError("Fresh native array count is unsupported: " + prop)
            for i in range(1, int(count) + 1):
                elements.append((await read(object_id, prop, i))[1])
            # Re-read the count; this detects count changes, not all races.
            checked, end = await read(object_id, prop, 0)
            if checked != count:
                raise ValueError("Native array count changed during sequential reads.")
            array.update(
                {
                    "status": "ok",
                    "complete": True,
                    "count_read": row,
                    "count_after": end,
                    "elements": elements,
                }
            )
        NativeScheduleLibrary._weekly_context(report, object_id)
        # These clocks/PV are observations only. Unsupported clock properties
        # stay visible and do not become invented UTC/timezone equality guards.
        for prop in CLOCK:
            _, row = await read(target.device, prop, required=False)
            report["device_clock"][prop] = row
        report["budget"] = budget.snapshot()
        report["finished_at"] = utc()
        report["complete"] = True
        return report, self._static(report, object_id), int(maximum)

    @staticmethod
    def _request(review, destination):
        tags = TagList.decode(PDU(bytes.fromhex(review["new"]["encoded_hex"])))
        day = DailySchedule.decode(tags)
        if tags:
            raise ValueError("Replacement DailySchedule has trailing tags.")
        request = WritePropertyRequest(
            objectIdentifier=ObjectIdentifier(review["source"]["object"]),
            propertyIdentifier="weekly-schedule",
            propertyArrayIndex=review["source"]["day"],
            propertyValue=day,
            destination=destination,
        )
        # The native ClientSSM supplies the unsegmented four-byte request header
        # at dispatch. Its invoke/max-response fields have fixed encoded size.
        size = len(request.encode().pduData) + 4
        if size > MAX_APDU:
            raise ValueError("Replacement exceeds the480-byte unsegmented write profile.")
        return request, size

    async def preview(self, **arguments):
        options = WeeklyWritePreview(**arguments)
        review, captured, target = self._reference(options.draft_id)
        body = {
            "id": secrets.token_hex(16),
            "profile": PROFILE,
            "rules_sha256": RULES_SHA256,
            "scope": SCOPE,
            "operation_id": options.operation_id,
            "draft_id": options.draft_id,
            "draft_sha256": hashlib.sha256(
                self.library.export_review(options.draft_id)
            ).hexdigest(),
            "source_sha256": review["source"]["source_sha256"],
            "target": target.model_dump(),
            "object_id": review["source"]["object"],
            "day": review["source"]["day"],
            "operator_name": options.operator_name,
            "rationale": options.rationale,
            "operator_identity_policy": "User-declared text, not authenticated site/operator identity.",
            "created_at": utc(),
            "can_apply": False,
            "status": "deferred",
            "token": None,
            "reasons": [],
            "native_draft": review,
            "automatic_retries": False,
        }
        active = None
        pin, config = None, None
        try:
            async with self._operation(options.operation_id) as active:
                async with self.path._path(target) as session:
                    self.reader.pin(session, target.router)
                    pin, config = self._pin(session), copy.deepcopy(session["config"])
                    fresh = body["fresh"] = {}
                    _, static, maximum = await self._fresh(
                        session, target, body["object_id"], report=fresh
                    )
                    body["fresh"] = fresh
                    if static != self._static(captured, body["object_id"]):
                        raise ValueError(
                            "Captured native configuration changed; capture and draft again."
                        )
                    request, size = self._request(review, session["target"])
                    body.update(
                        request_apdu_bytes=size,
                        request_service_body_hex=bytes(request.encode().pduData).hex(),
                        remote_max_apdu=maximum,
                        static_native_sha256=digest(static),
                    )
                    if size > maximum:
                        raise ValueError(
                            "Replacement exceeds the remote maximum APDU; no segmentation/split is attempted."
                        )
                    if not review["diff"]["changed"]:
                        body["status"] = "no_change"
                        body["reasons"].append(
                            "Old and new native daily tags are identical; no write is prepared."
                        )
                    else:
                        body.update(can_apply=True, status="review_required")
        except asyncio.CancelledError:
            if active is None or active["reason"] is None:
                raise
            body["status"] = active["reason"]
            body["reasons"].append("Preview cancelled; no configuration write was sent.")
        except Exception as exc:
            body["reasons"].append(str(exc)[:500] or type(exc).__name__)
        if body["can_apply"]:
            body["expires_at"] = (datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)).isoformat()
            body["review_sha256"] = digest({k: v for k, v in body.items() if k != "token"})
            token = secrets.token_urlsafe(24)
            # A newer preview for this exact target/day retires older tokens.
            for old, plan in list(self.plans.items()):
                if (
                    plan["body"]["target"] == body["target"]
                    and plan["body"]["object_id"] == body["object_id"]
                    and plan["body"]["day"] == body["day"]
                ):
                    del self.plans[old]
            self.plans[token] = {
                "body": copy.deepcopy(body),
                "pin": pin,
                "config": config,
                "created": time.monotonic(),
            }
            while len(self.plans) > MAX_PLANS:
                self.plans.popitem(last=False)
            body["token"] = token
        return body

    async def _readback(self, session, target, review, before, *, result=None):
        result = {} if result is None else result
        result.update(
            {
                "status": "in_progress",
                "observed_at": utc(),
                "selected_day_matches": None,
                "other_static_context_matches": None,
                "evidence": {},
            }
        )
        try:
            fresh, static, _ = await self._fresh(
                session, target, review["source"]["object"], report=result["evidence"]
            )
            desired = copy.deepcopy(before)
            desired["weekly-schedule"]["elements"][review["source"]["day"] - 1] = (
                "3e" + review["new"]["encoded_hex"] + "3f"
            )
            selected = static["weekly-schedule"]["elements"][review["source"]["day"] - 1]
            other = copy.deepcopy(static)
            other["weekly-schedule"]["elements"][review["source"]["day"] - 1] = before[
                "weekly-schedule"
            ]["elements"][review["source"]["day"] - 1]
            result.update(
                status="match" if static == desired else "mismatch",
                selected_day_matches=selected
                == desired["weekly-schedule"]["elements"][review["source"]["day"] - 1],
                other_static_context_matches=other == before,
                evidence=fresh,
                observed_static_sha256=digest(static),
            )
        except asyncio.CancelledError:
            result.update(
                status="unavailable",
                error="Readback interrupted; partial dated observations do not establish a complete configuration match.",
            )
            raise
        except Exception as exc:
            result["status"] = "unavailable"
            result["error"] = str(exc)[:500] or type(exc).__name__
        return result

    async def apply(self, **arguments):
        options = WeeklyWriteApply(**arguments)
        plan = self.plans.pop(options.token, None)
        if plan is None or not secrets.compare_digest(
            plan["body"]["review_sha256"], options.review_sha256
        ):
            raise ValueError("Weekly-write token is invalid, changed or already used.")
        if time.monotonic() - plan["created"] > PLAN_SECONDS:
            raise ValueError("Weekly-write review expired; preview again.")
        body = plan["body"]
        review, _, target = self._reference(body["draft_id"])
        if review != body["native_draft"]:
            raise ValueError("Reviewed draft changed; no write sent.")
        receipt = {
            "id": secrets.token_hex(16),
            "profile": PROFILE,
            "rules_sha256": RULES_SHA256,
            "scope": SCOPE,
            "operation_id": options.operation_id,
            "target": target.model_dump(),
            "object_id": body["object_id"],
            "day": body["day"],
            "draft_id": body["draft_id"],
            "source_sha256": body["source_sha256"],
            "review_sha256": options.review_sha256,
            "review": body,
            "started_at": utc(),
            "finished_at": None,
            "status": "not_sent",
            "dispatch_started": False,
            "may_have_applied": False,
            "protocol_status": "not_sent",
            "protocol_accepted": False,
            "automatic_retries": False,
            "readback": {"status": "not_attempted"},
            "errors": [],
        }
        active, caller_cancel = None, False
        try:
            async with self._operation(options.operation_id) as active:
                async with self.path._path(target) as session:
                    self.reader.pin(session, target.router)
                    if (
                        not self._same_pin(session, plan["pin"])
                        or session["config"] != plan["config"]
                    ):
                        raise ValueError(
                            "Reviewed interface/socket/configuration changed; preview again."
                        )
                    fresh = receipt["fresh"] = {}
                    _, static, maximum = await self._fresh(
                        session, target, body["object_id"], report=fresh
                    )
                    receipt["fresh"] = fresh
                    if (
                        digest(static) != body["static_native_sha256"]
                        or maximum != body["remote_max_apdu"]
                    ):
                        raise ValueError(
                            "Reviewed native configuration or APDU limit changed; no write sent."
                        )
                    request, size = self._request(review, session["target"])
                    if size != body["request_apdu_bytes"] or size > maximum:
                        raise ValueError(
                            "Reviewed encoded write size changed/exceeds remote maximum."
                        )

                    def before_send(packet):
                        self.reader.guard(session)
                        if (
                            not self._same_pin(session, plan["pin"])
                            or asyncio.get_running_loop().time() >= active["deadline"]
                        ):
                            raise ValueError(
                                "Weekly-write interface/deadline changed before dispatch."
                            )
                        raw = apdu_bytes(packet)
                        if (
                            len(raw) != size
                            or len(raw) > min(MAX_APDU, maximum)
                            or raw[0] not in (0, 2)
                            or raw[3] != 15
                            or raw[4:].hex() != body["request_service_body_hex"]
                        ):
                            raise ValueError(
                                "Actual write APDU differs from reviewed bounded size."
                            )
                        receipt["native_request"] = {
                            "apdu_hex": raw.hex(),
                            "apdu_bytes": len(raw),
                            "apdu_sha256": hashlib.sha256(raw).hexdigest(),
                            "invoke_id": request.apduInvokeID,
                            "service_choice": 15,
                            "array_index": body["day"],
                            "request_priority": None,
                        }
                        receipt["intent_sha256"] = self.journal.intent(receipt)
                        self.reader.guard(session)
                        if (
                            not self._same_pin(session, plan["pin"])
                            or asyncio.get_running_loop().time() >= active["deadline"]
                        ):
                            raise ValueError(
                                "Weekly-write interface/deadline changed while recording intent."
                            )
                        receipt.update(
                            dispatch_started=True,
                            may_have_applied=True,
                            protocol_status="unknown",
                            status="unknown",
                        )

                    async with self.wire.receive(session, request) as proof:
                        receipt["transport_candidates"] = proof
                        try:
                            reply = await asyncio.wait_for(
                                confirmed_exchange(
                                    session["app"],
                                    request,
                                    single_attempt=True,
                                    before_send=before_send,
                                ),
                                self.timeout,
                            )
                        except ErrorRejectAbortNack as exc:
                            reply = exc
                        except TimeoutError:
                            reply = None
                            receipt["errors"].append(
                                "No validated protocol response before the single-attempt deadline."
                            )
                        if reply is not None:
                            try:
                                response = self.wire.validate(reply, session, request, proof)
                                receipt["response"] = response
                                receipt.update(
                                    protocol_status="accepted"
                                    if isinstance(reply, SimpleAckPDU)
                                    else "rejected",
                                    protocol_accepted=isinstance(reply, SimpleAckPDU),
                                )
                                if not isinstance(reply, SimpleAckPDU):
                                    receipt["errors"].append(
                                        "Native "
                                        + response["type"]
                                        + " received; inspect typed reason/error fields and independent readback. Rejection does not prove unchanged configuration."
                                    )
                            except Exception as exc:
                                receipt["errors"].append(
                                    "Protocol response unverified: "
                                    + (str(exc)[:400] or type(exc).__name__)
                                )
                    self.reader.guard(session)
                    receipt["readback"] = {"status": "in_progress", "started_at": utc()}
                    await self._readback(
                        session, target, review, static, result=receipt["readback"]
                    )
                    receipt["status"] = (
                        "protocol_accepted"
                        if receipt["protocol_accepted"]
                        else "protocol_rejected"
                        if receipt["protocol_status"] == "rejected"
                        else "unknown"
                    )
        except asyncio.CancelledError:
            caller_cancel = active is None or active["reason"] is None
            receipt["status"] = "unknown" if receipt["dispatch_started"] else "cancelled"
            receipt["errors"].append(
                "Operation cancelled. A dispatched write cannot be undone; reconcile explicitly before considering a fresh attempt."
            )
        except Exception as exc:
            receipt["status"] = "unknown" if receipt["dispatch_started"] else "not_sent"
            receipt["errors"].append(str(exc)[:500] or type(exc).__name__)
        if receipt["readback"]["status"] == "in_progress":
            receipt["readback"].update(
                status="unavailable",
                error="Readback was interrupted by cancellation, deadline or interface failure; no state conclusion is available.",
            )
        receipt["finished_at"] = utc()
        try:
            raw = self.journal.result(receipt)
        except (ValueError, OSError, sqlite3.Error) as exc:
            receipt["journal_error"] = (
                "Sealed result could not be persisted; durable intent, if recorded, remains unresolved: "
                + str(exc)[:300]
            )
            raw = encoded(seal(receipt))
        if caller_cancel:
            raise asyncio.CancelledError
        return raw

    async def reconcile(self, **arguments):
        options = WeeklyWriteReconcile(**arguments)
        receipt_raw = self.journal.receipt(options.receipt_id)
        receipt = strict_json(receipt_raw, RECORD_BYTES, max_values=MAX_RECEIPT_VALUES)
        saved = receipt.get("review", {}).get("native_draft")
        if type(saved) is not dict:
            raise ValueError("Receipt lacks its exact reviewed native draft.")
        review, _, target = self._reference(receipt["draft_id"], saved_review=saved)
        if (
            receipt.get("target") != target.model_dump()
            or receipt.get("object_id") != review["source"]["object"]
            or receipt.get("day") != review["source"]["day"]
        ):
            raise ValueError("Receipt target/day differs from its reviewed source.")
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "operation_id": options.operation_id,
            "receipt_id": options.receipt_id,
            "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "target": target.model_dump(),
            "read_only": True,
            "writes_sent": 0,
            "observed_at": utc(),
        }
        async with self._operation(options.operation_id):
            async with self.path._path(target) as session:
                self.reader.pin(session, target.router)
                before = self._static(
                    source_report(self.library.source(review["source"]["capture_id"])),
                    review["source"]["object"],
                )
                body["readback"] = await self._readback(session, target, review, before)
        return encoded(seal(body))
