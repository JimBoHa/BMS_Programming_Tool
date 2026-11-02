"""One-attempt standard Calendar Date_List writes with independent source authority.

No retry, rollback, clock inference, native CAF compilation or physical acceptance.
The original numeric and String Schedule writers and journals stay independent.
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
from bacpypes3.object import CalendarObject, DeviceObject
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, TagList, Unsigned
from fastapi import APIRouter, Response
from pydantic import Field, field_validator

from .bacnet_exchange import confirmed_exchange
from .device_details import DeviceDetails, DeviceDetailsRequest
from .models import StrictModel
from .native_calendar_drafts import DATE_LIST, CalendarDraftExport, NativeCalendarDrafts
from .native_calendar_drafts import RULES_SHA256 as DRAFT_RULES_SHA256
from .native_schedule_library import decoded_row, digest, encoded, strict_json
from .native_schedule_wire import ScheduleWriteWire, apdu_bytes
from .property_evidence import PropertyEvidence, ReadBudget

PROFILE = "native-calendar-reviewed-date-list-write/1"
SCOPE = (
    "One existing standard Calendar Date_List over an already-open direct or explicitly "
    "routed plain IPv4 interface. Fresh identity, complete original value and static "
    "name/description checks, one unsegmented WriteProperty, durable intent and independent "
    "readback. Sequential checks are not compare-and-swap. No retries, rollback, new "
    "objects, exception/context/link editing, native CAF, clock evaluation or physical acceptance."
)
PLAN_SECONDS, MAX_PLANS, MAX_APDU = 30, 16, 480
MAX_REQUESTS, MAX_EVIDENCE_BYTES = 64, 1536 * 1024
JOURNAL_RECORDS, JOURNAL_BYTES, RECORD_BYTES = 64, 64 * 1024 * 1024, 8 * 1024 * 1024
MAX_RECEIPT_VALUES = 1000000
STATIC = ("object-identifier", "object-name", "description", "date-list")
RULES = {
    "profile": PROFILE,
    "draft_rules_sha256": DRAFT_RULES_SHA256,
    "operation": "Existing Calendar Date_List only; no array index or priority; one unsegmented service 15 attempt, maximum 480 APDU bytes and remote limit.",
    "source": "Regenerate complete stateless Calendar review from the immutable source; no arbitrary target override or legacy weekly authority.",
    "conflicts": "Fresh verified Device/Calendar IDs, exact old Date_List and captured name/description before review and dispatch; sequential checks are not CAS.",
    "dynamic": "Boolean Present_Value is an observation, not static equality or a proposed-value evaluation.",
    "review_lifetime": "A one-use review must remain within its 30-second monotonic lifetime at admission and immediately before dispatch, including after durable intent publication.",
    "revision": "Read actual protocol revision; old or proposed WeekNDay 7..9 requires known revision 18 or later. No inferred target compatibility.",
    "response": "Reuse scoped service-15 raw-ingress next-hop/source/invoke/service proof; protocol outcome and readback remain separate.",
    "uncertainty": "Every admitted dispatch may have applied, including Error, Reject, Abort or lost ACK. Intent without sealed result remains unresolved after restart.",
    "journal": "Independent bounded sealed Calendar intent/result BLOBs, full-sync SQLite commits, reserved result space and immutable results; no eviction or replay.",
    "stack": "bacpypes3/0.0.110",
}
RULES_SHA256 = digest(RULES)


def utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


def seal(body):
    result = copy.deepcopy(body)
    result["evidence_sha256"] = digest(result)
    return result


class CalendarPreview(CalendarDraftExport):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$", strict=True)
    operator_name: str = Field(min_length=1, max_length=48, strict=True)
    rationale: str = Field(min_length=1, max_length=240, strict=True)

    @field_validator("operator_name", "rationale")
    @classmethod
    def declaration(cls, value):
        value = value.strip()
        if not value or any(
            unicodedata.category(c).startswith("C") or unicodedata.category(c) in ("Zl", "Zp")
            for c in value
        ):
            raise ValueError("Enter a visible single-line operator declaration.")
        return value


class CalendarAction(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$", strict=True)


class CalendarApply(CalendarAction):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$", strict=True)
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)


class CalendarReconcile(CalendarAction):
    receipt_id: str = Field(pattern=r"^[0-9a-f]{32}$", strict=True)


def qualify_calendar_ranges(entries):
    """Qualify new field values; old local encodings and readback stay readable.

    BACnet DateRange endpoints are specific dates or wholly unspecified dates.
    Date/WeekNDay patterns retain their separate, broader native choices. This
    enforces the existing standard-Calendar write scope without changing sealed
    local encodings, journal formats or the rules used by older readback records.
    """
    for index, entry in enumerate(entries, 1):
        if entry["kind"] != "dateRange":
            continue
        endpoints = []
        for side in ("start", "end"):
            fields = entry[side]
            message = (
                f"Calendar date range entry {index} {side} requires a fully specified "
                "date with its matching weekday, or Any in all four fields."
            )
            if (
                type(fields) is not list
                or len(fields) != 4
                or any(type(value) is not int for value in fields)
            ):
                raise ValueError(message)
            if fields == [255, 255, 255, 255]:
                endpoints.append(None)
                continue
            if not 0 <= fields[0] <= 254:
                raise ValueError(message)
            try:
                endpoint = datetime(1900 + fields[0], fields[1], fields[2]).date()
            except (ValueError, OverflowError) as error:
                raise ValueError(message) from error
            if fields[3] != endpoint.isoweekday():
                raise ValueError(message)
            endpoints.append(endpoint)
        if all(value is not None for value in endpoints) and endpoints[0] > endpoints[1]:
            raise ValueError(f"Calendar date range entry {index} starts after its end date.")


class CalendarWriteJournal:
    """Bounded durable intent/result rows; no eviction or implicit deletion."""

    def __init__(self, store):
        self.store = store
        with store.connect(timeout=0.25) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS native_calendar_writes("
                "id TEXT PRIMARY KEY, intent BLOB, result BLOB, created TEXT NOT NULL)"
            )

    @staticmethod
    def _limits(db, size, *, replacing=0, adding=True, reserve=0):
        count, used, pending = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(COALESCE(LENGTH(intent),0)+COALESCE(LENGTH(result),0)),0), "
            "SUM(CASE WHEN intent IS NOT NULL AND result IS NULL THEN 1 ELSE 0 END) "
            "FROM native_calendar_writes"
        ).fetchone()
        used += (pending or 0) * RECORD_BYTES
        if (
            size > RECORD_BYTES
            or (adding and count >= JOURNAL_RECORDS)
            or used - replacing + size + reserve > JOURNAL_BYTES
        ):
            raise ValueError(
                "Calendar-write journal capacity reached; no automatic eviction is performed."
            )

    def intent(self, receipt):
        # A crash after this commit cannot establish whether dispatch occurred.
        raw = encoded(seal({**receipt, "journal_state": "intent_only", "may_have_applied": True}))
        self._checked(raw, receipt["id"])
        with self.store.connect(timeout=0.25) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            self._limits(db, len(raw), reserve=RECORD_BYTES)
            db.execute(
                "INSERT INTO native_calendar_writes(id,intent,result,created) VALUES(?,?,NULL,?)",
                (receipt["id"], raw, utc()),
            )
        return hashlib.sha256(raw).hexdigest()

    def result(self, receipt):
        receipt = copy.deepcopy(receipt)
        with self.store.connect(timeout=0.25) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT intent,result FROM native_calendar_writes WHERE id=?", (receipt["id"],)
            ).fetchone()
            if old and old[1] is not None:
                raise ValueError("A sealed Calendar-write result is immutable.")
            if old and old[0] is not None:
                self._bindings(self._checked(old[0], receipt["id"]), receipt)
                intent_sha = hashlib.sha256(old[0]).hexdigest()
                if receipt.get("intent_sha256", intent_sha) != intent_sha:
                    raise ValueError(
                        "Calendar-write result intent hash differs from retained intent."
                    )
                receipt["intent_sha256"] = intent_sha
            elif (
                receipt.get("intent_sha256") is not None or receipt.get("dispatch_started") is True
            ):
                raise ValueError(
                    "A dispatched Calendar result requires its retained original intent."
                )
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
                    "INSERT INTO native_calendar_writes(id,result,created) VALUES(?,?,?)",
                    (receipt["id"], raw, utc()),
                )
            else:
                db.execute(
                    "UPDATE native_calendar_writes SET result=? WHERE id=?", (raw, receipt["id"])
                )
        return raw

    @staticmethod
    def _bindings(intent, result):
        for key in (
            "id",
            "profile",
            "rules_sha256",
            "operation_id",
            "target",
            "object_id",
            "property",
            "array_index",
            "draft_id",
            "source_sha256",
            "review_sha256",
            "review",
            "native_request",
        ):
            if intent.get(key) != result.get(key):
                raise ValueError(
                    "Calendar result differs from its original intent source, target or request."
                )

    @staticmethod
    def _checked(raw, id):
        if type(raw) is not bytes or not raw or len(raw) > RECORD_BYTES:
            raise ValueError("Calendar-write journal requires a bounded nonempty BLOB body.")
        body = strict_json(raw, RECORD_BYTES, max_values=MAX_RECEIPT_VALUES)
        if (
            type(body) is not dict
            or body.get("id") != id
            or body.get("profile") != PROFILE
            or body.get("evidence_sha256")
            != digest({k: v for k, v in body.items() if k != "evidence_sha256"})
        ):
            raise ValueError("Calendar-write journal seal failed.")
        return body

    def receipt(self, id):
        if (
            type(id) is not str
            or len(id) != 32
            or any(char not in "0123456789abcdef" for char in id)
        ):
            raise ValueError("Invalid Calendar-write receipt identifier.")
        with self.store.connect(timeout=0.25) as db:
            lengths = db.execute(
                "SELECT LENGTH(intent),LENGTH(result) FROM native_calendar_writes WHERE id=?", (id,)
            ).fetchone()
            if lengths and any(size is not None and size > RECORD_BYTES for size in lengths):
                raise ValueError("Calendar-write journal record exceeds its byte bound.")
            row = db.execute(
                "SELECT intent,result FROM native_calendar_writes WHERE id=?", (id,)
            ).fetchone()
        if row is None:
            raise ValueError("Calendar-write receipt is unavailable.")
        raw = row[1] if row[1] is not None else row[0]
        body = self._checked(raw, id)
        if row[0] is not None:
            intent = self._checked(row[0], id)
            if row[1] is not None:
                self._bindings(intent, body)
        elif body.get("intent_sha256") is not None or body.get("dispatch_started") is True:
            raise ValueError("Calendar result has lost its original intent.")
        if (
            row[1] is not None
            and row[0] is not None
            and body.get("intent_sha256") != hashlib.sha256(row[0]).hexdigest()
        ):
            raise ValueError("Calendar-write result does not bind its retained intent bytes.")
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
                "SELECT id,created,result IS NULL AS unresolved FROM native_calendar_writes ORDER BY created DESC LIMIT ?",
                (JOURNAL_RECORDS,),
            ).fetchall()
            used = db.execute(
                "SELECT COALESCE(SUM(COALESCE(LENGTH(intent),0)+COALESCE(LENGTH(result),0)),0) FROM native_calendar_writes"
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


class NativeCalendarWrites:
    def __init__(
        self, bacnet, store, library, *, timeout=1.0, operation_timeout=15.0, request_gap=0.02
    ):
        self.bacnet, self.library = bacnet, library
        self.drafts = NativeCalendarDrafts(library)
        self.path = DeviceDetails(
            bacnet,
            store,
            timeout=timeout,
            operation_timeout=operation_timeout,
            request_gap=request_gap,
        )
        self.reader = PropertyEvidence(self.path)
        self.wire = ScheduleWriteWire(self.reader)
        self.journal = CalendarWriteJournal(store)
        self.timeout, self.operation_timeout, self.request_gap = (
            timeout,
            operation_timeout,
            request_gap,
        )
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
        CalendarAction(operation_id=operation_id)
        self.cancelled[operation_id] = True
        while len(self.cancelled) > 64:
            self.cancelled.popitem(last=False)
        retired = [
            token
            for token, plan in self.plans.items()
            if plan["body"]["operation_id"] == operation_id
        ]
        for token in retired:
            del self.plans[token]
        found = self.active is not None and self.active["id"] == operation_id
        if found:
            self.active["reason"] = reason
            self.active["task"].cancel()
        return {
            "operation_id": operation_id,
            "cancel_requested": found,
            "reviews_retired": len(retired),
            "note": "Cancellation cannot undo a transmitted Calendar write.",
        }

    async def close(self):
        self.plans.clear()
        if self.active:
            task = self.active["task"]
            self.cancel(self.active["id"], reason="interface_changed")
            if task is not asyncio.current_task():
                await asyncio.gather(task, return_exceptions=True)

    @asynccontextmanager
    async def _operation(self, operation_id):
        if self.active is not None or operation_id in self.cancelled:
            raise ValueError("Calendar operation is active or this operation ID was cancelled.")
        active = {
            "id": operation_id,
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

    def _same_pin(self, session, expected):
        actual = self._pin(session)
        return len(actual) == len(expected) and all(
            a is b for a, b in zip(actual, expected, strict=True)
        )

    def _reference(self, draft, expected_review_id):
        review = self.drafts.review(draft)
        if review["id"] != expected_review_id:
            raise ValueError("Calendar local draft or source changed; review it again.")
        captured = self.drafts.context(review["source"]["capture_id"], review["source"]["object"])[
            0
        ]
        self._static(captured, review["source"]["object"])
        config = self.bacnet.config or {}
        if config.get("transport") == "mstp" or config.get("bbmd_address"):
            raise ValueError(
                "Calendar writes require an already-open plain IPv4 interface without BBMD or serial."
            )
        self.bacnet.require()
        return review, captured, DeviceDetailsRequest(**captured["target"])

    def _static(self, report, object_id):
        _, props, _, _, _ = self.drafts._context(report, object_id)
        if set(props) != {*STATIC, "present-value"}:
            raise ValueError(
                "Calendar write requires the complete known identity/name/description/value context; unsupported properties remain deferred."
            )
        result = {}
        for prop in STATIC:
            value, raw = decoded_row(props[prop], object_id, prop)
            if prop in ("object-name", "description") and not isinstance(value, CharacterString):
                raise ValueError(
                    "Calendar name/description must have exact native String evidence."
                )
            result[prop] = raw.hex()
        return result

    async def _fresh(self, session, target, object_id, minimum_revision, report):
        budget = ReadBudget(max_requests=MAX_REQUESTS, max_bytes=MAX_EVIDENCE_BYTES)
        props = {}
        report.update(
            target=target.model_dump(),
            identity_verified=False,
            objects=[{"object": object_id, "identity_verified": False, "properties": props}],
            started_at=utc(),
            complete=False,
            failed_reads=[],
        )

        async def read(obj, prop, required=True):
            report["pending_read"] = {"object": obj, "property": prop, "requested_at": utc()}
            try:
                value, row = await self.reader.read(
                    session,
                    budget,
                    obj,
                    prop,
                    DeviceObject if obj == target.device else CalendarObject,
                    timeout=self.timeout,
                    request_gap=self.request_gap,
                )
            finally:
                report["budget"] = budget.snapshot()
                report["last_observed_at"] = utc()
            report.pop("pending_read", None)
            if row["status"] != "ok" or row.get("transport_evidence") is None:
                report["failed_reads"].append(row)
                if required:
                    raise ValueError(
                        "Fresh Calendar property unavailable: "
                        + prop
                        + ": "
                        + row.get("error", row["status"])
                    )
                return None, row
            return value, row

        identity, report["device_identity"] = await read(target.device, "object-identifier")
        if identity != ObjectIdentifier(target.device):
            raise ValueError("Fresh Device identity differs from captured Calendar source.")
        report["identity_verified"] = True
        maximum, report["remote_max_apdu"] = await read(target.device, "max-apdu-length-accepted")
        if not isinstance(maximum, Unsigned) or not 50 <= int(maximum) <= 65535:
            raise ValueError("Remote maximum APDU is unavailable or outside this profile.")
        revision, report["protocol_revision"] = await read(
            target.device, "protocol-revision", required=minimum_revision is not None
        )
        if revision is not None and not isinstance(revision, Unsigned):
            raise ValueError("Fresh protocol revision is not native Unsigned evidence.")
        revision = int(revision) if revision is not None else None
        if minimum_revision is not None and (revision is None or revision < minimum_revision):
            raise ValueError(
                "Calendar weekday pattern requires verified protocol revision 18 or later."
            )
        identity, props["object-identifier"] = await read(object_id, "object-identifier")
        if identity != ObjectIdentifier(object_id):
            raise ValueError("Fresh Calendar identity differs from captured source.")
        report["objects"][0]["identity_verified"] = True
        for prop in ("object-name", "description", "present-value", "date-list"):
            _, props[prop] = await read(object_id, prop)
        static = self._static(report, object_id)
        report.update(complete=True, finished_at=utc())
        return static, {"remote_max_apdu": int(maximum), "protocol_revision": revision}

    @staticmethod
    def _minimum_revision(review):
        return (
            18
            if any(
                entry["kind"] == "weekNDay" and 7 <= entry["fields"][1] <= 9
                for side in ("old", "new")
                for entry in review[side]["entries"]
            )
            else None
        )

    @staticmethod
    def _request(review, destination):
        qualify_calendar_ranges(review["new"]["entries"])
        tags = TagList.decode(PDU(bytes.fromhex(review["new"]["encoded_hex"])))
        value = DATE_LIST.decode(tags)
        if tags or bytes(value.encode().encode().pduData).hex() != review["new"]["encoded_hex"]:
            raise ValueError("Calendar replacement value did not retain its exact native tags.")
        request = WritePropertyRequest(
            objectIdentifier=ObjectIdentifier(review["source"]["object"]),
            propertyIdentifier="date-list",
            propertyValue=value,
            destination=destination,
        )
        size = len(request.encode().pduData) + 4
        if size > MAX_APDU:
            raise ValueError("Calendar replacement exceeds the 480-byte unsegmented write profile.")
        return request, size

    async def preview(self, **arguments):
        options = CalendarPreview(**arguments)
        review, captured, target = self._reference(
            options.draft.model_dump(), options.expected_review_id
        )
        # Refuse an invalid proposal before fresh field reads or plan allocation.
        # Reconcile intentionally uses the historical reference without new-write admission.
        if review["diff"]["changed"]:
            qualify_calendar_ranges(review["new"]["entries"])
        body = {
            "id": secrets.token_hex(16),
            "profile": PROFILE,
            "rules_sha256": RULES_SHA256,
            "scope": SCOPE,
            "operation_id": options.operation_id,
            "draft_id": review["id"],
            "native_draft": review,
            "source_sha256": review["source"]["source_sha256"],
            "target": target.model_dump(),
            "object_id": review["source"]["object"],
            "property": "date-list",
            "array_index": None,
            "operator_name": options.operator_name,
            "rationale": options.rationale,
            "operator_identity_policy": "User-declared text, not authenticated site/operator identity.",
            "created_at": utc(),
            "can_apply": False,
            "status": "deferred",
            "token": None,
            "automatic_retries": False,
            "reasons": [],
        }
        active = None
        try:
            async with self._operation(options.operation_id) as active:
                async with self.path._path(target) as session:
                    self.reader.pin(session, target.router)
                    pin, config = self._pin(session), copy.deepcopy(session["config"])
                    fresh = body["fresh"] = {}
                    static, capabilities = await self._fresh(
                        session, target, body["object_id"], self._minimum_revision(review), fresh
                    )
                    if static != self._static(captured, body["object_id"]):
                        raise ValueError(
                            "Captured Calendar configuration changed; capture and draft again."
                        )
                    body.update(
                        capabilities=capabilities,
                        static_native_sha256=digest(static),
                    )
                    if not review["diff"]["changed"]:
                        body.update(
                            status="no_change",
                            reasons=[
                                "Original and proposed Calendar tags match; no write is prepared."
                            ],
                        )
                    else:
                        request, size = self._request(review, session["target"])
                        body.update(
                            request_apdu_bytes=size,
                            request_service_body_hex=bytes(request.encode().pduData).hex(),
                        )
                        if size > capabilities["remote_max_apdu"]:
                            raise ValueError(
                                "Calendar replacement exceeds the remote APDU limit; no split or segmentation is attempted."
                            )
                        for old, plan in list(self.plans.items()):
                            if (
                                plan["body"]["target"] == body["target"]
                                and plan["body"]["object_id"] == body["object_id"]
                            ):
                                del self.plans[old]
                        if len(self.plans) >= MAX_PLANS:
                            raise ValueError(
                                "Calendar review capacity reached; existing reviews were not evicted."
                            )
                        body.update(
                            can_apply=True,
                            status="review_required",
                            expires_at=(
                                datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)
                            ).isoformat(),
                        )
                        body["review_sha256"] = digest(
                            {k: v for k, v in body.items() if k != "token"}
                        )
                        token = secrets.token_urlsafe(24)
                        self.plans[token] = {
                            "body": copy.deepcopy(body),
                            "pin": pin,
                            "config": config,
                            "created": time.monotonic(),
                        }
                        body["token"] = token
        except asyncio.CancelledError:
            if active is None or active["reason"] is None:
                raise
            body["status"] = active["reason"]
            body["reasons"].append("Preview cancelled; no Calendar write was sent.")
        except Exception as error:
            body["reasons"].append(str(error)[:500] or type(error).__name__)
        return body

    async def _readback(self, session, target, review, before, result):
        result.update(
            status="in_progress",
            observed_at=utc(),
            selected_value_matches=None,
            other_static_context_matches=None,
            evidence={},
        )
        try:
            static, capabilities = await self._fresh(
                session,
                target,
                review["source"]["object"],
                self._minimum_revision(review),
                result["evidence"],
            )
            desired = {**before, "date-list": "3e" + review["new"]["encoded_hex"] + "3f"}
            other = {**static, "date-list": before["date-list"]}
            result.update(
                status="match" if static == desired else "mismatch",
                selected_value_matches=static["date-list"] == desired["date-list"],
                other_static_context_matches=other == before,
                observed_static_sha256=digest(static),
                capabilities=capabilities,
            )
        except asyncio.CancelledError:
            result.update(
                status="unavailable",
                error="Readback interrupted; partial observations do not establish a complete Calendar match.",
            )
            raise
        except Exception as error:
            result.update(status="unavailable", error=str(error)[:500] or type(error).__name__)
        return result

    async def apply(self, **arguments):
        options = CalendarApply(**arguments)
        plan = self.plans.pop(options.token, None)
        if plan is None or not secrets.compare_digest(
            plan["body"]["review_sha256"], options.review_sha256
        ):
            raise ValueError("Calendar review token is invalid, changed or already used.")
        age = time.monotonic() - plan["created"]
        if not 0 <= age <= PLAN_SECONDS:
            raise ValueError("Calendar review expired; preview again.")
        body = plan["body"]
        review, _, target = self._reference(body["native_draft"]["request"], body["draft_id"])
        if (
            review != body["native_draft"]
            or body["profile"] != PROFILE
            or body["rules_sha256"] != RULES_SHA256
        ):
            raise ValueError(
                "Calendar source or active write authority changed; no write was sent."
            )
        receipt = {
            "id": secrets.token_hex(16),
            "profile": PROFILE,
            "rules_sha256": RULES_SHA256,
            "scope": SCOPE,
            "operation_id": options.operation_id,
            "target": target.model_dump(),
            "object_id": body["object_id"],
            "property": "date-list",
            "array_index": None,
            "draft_id": review["id"],
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
                            "Reviewed Calendar interface/socket/configuration changed; preview again."
                        )
                    static, capabilities = await self._fresh(
                        session,
                        target,
                        body["object_id"],
                        self._minimum_revision(review),
                        receipt.setdefault("fresh", {}),
                    )
                    if (
                        digest(static) != body["static_native_sha256"]
                        or capabilities != body["capabilities"]
                    ):
                        raise ValueError(
                            "Reviewed Calendar configuration or remote capabilities changed; no write sent."
                        )
                    request, size = self._request(review, session["target"])
                    if size != body["request_apdu_bytes"] or size > capabilities["remote_max_apdu"]:
                        raise ValueError(
                            "Reviewed Calendar write size changed or exceeds the remote limit."
                        )

                    def before_send(packet):
                        self.reader.guard(session)
                        if (
                            not self._same_pin(session, plan["pin"])
                            or asyncio.get_running_loop().time() >= active["deadline"]
                            or not 0 <= time.monotonic() - plan["created"] <= PLAN_SECONDS
                        ):
                            raise ValueError(
                                "Calendar interface, review lifetime or operation deadline changed before dispatch."
                            )
                        raw = apdu_bytes(packet)
                        if (
                            len(raw) != size
                            or len(raw) > min(MAX_APDU, capabilities["remote_max_apdu"])
                            or raw[0] not in (0, 2)
                            or raw[3] != 15
                            or raw[4:].hex() != body["request_service_body_hex"]
                        ):
                            raise ValueError(
                                "Actual Calendar write differs from its exact reviewed APDU."
                            )
                        receipt["native_request"] = {
                            "apdu_hex": raw.hex(),
                            "apdu_bytes": len(raw),
                            "apdu_sha256": hashlib.sha256(raw).hexdigest(),
                            "invoke_id": request.apduInvokeID,
                            "service_choice": 15,
                            "array_index": None,
                            "request_priority": None,
                        }
                        receipt["intent_sha256"] = self.journal.intent(receipt)
                        self.reader.guard(session)
                        if (
                            not self._same_pin(session, plan["pin"])
                            or asyncio.get_running_loop().time() >= active["deadline"]
                            or not 0 <= time.monotonic() - plan["created"] <= PLAN_SECONDS
                        ):
                            raise ValueError(
                                "Calendar interface, review lifetime or operation deadline changed while recording intent."
                            )
                        receipt.update(
                            dispatch_started=True,
                            may_have_applied=True,
                            protocol_status="unknown",
                            protocol_accepted=None,
                            status="unknown",
                        )

                    async with self.wire.receive(session, request) as proof:
                        receipt["transport_candidates"] = proof
                        try:
                            reply = await confirmed_exchange(
                                session["app"],
                                request,
                                single_attempt=True,
                                before_send=before_send,
                                response_timeout=self.timeout,
                            )
                        except ErrorRejectAbortNack as error:
                            reply = error
                        except TimeoutError:
                            reply = None
                            receipt["errors"].append(
                                "No validated response before the single-attempt deadline."
                            )
                        if reply is not None:
                            try:
                                receipt["response"] = self.wire.validate(
                                    reply, session, request, proof
                                )
                                receipt.update(
                                    protocol_status="accepted"
                                    if isinstance(reply, SimpleAckPDU)
                                    else "rejected",
                                    protocol_accepted=isinstance(reply, SimpleAckPDU),
                                )
                                if not isinstance(reply, SimpleAckPDU):
                                    receipt["errors"].append(
                                        "A negative protocol response does not prove unchanged Calendar configuration; inspect readback separately."
                                    )
                            except Exception as error:
                                receipt["errors"].append(
                                    "Calendar response unverified: "
                                    + (str(error)[:400] or type(error).__name__)
                                )
                    self.reader.guard(session)
                    await self._readback(session, target, review, static, receipt["readback"])
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
                "Calendar operation cancelled. A possible dispatch cannot be undone; reconcile explicitly before another attempt."
            )
        except Exception as error:
            receipt["status"] = "unknown" if receipt["dispatch_started"] else "not_sent"
            receipt["errors"].append(str(error)[:500] or type(error).__name__)
        if receipt["readback"]["status"] == "in_progress":
            receipt["readback"].update(
                status="unavailable",
                error="Readback did not finish; no complete state conclusion is available.",
            )
        receipt["finished_at"] = utc()
        try:
            raw = self.journal.result(receipt)
        except (ValueError, OSError, sqlite3.Error) as error:
            receipt["journal_error"] = (
                "Sealed result could not be persisted; any durable intent remains unresolved: "
                + str(error)[:300]
            )
            raw = encoded(seal(receipt))
        if caller_cancel:
            raise asyncio.CancelledError
        return raw

    async def reconcile(self, **arguments):
        options = CalendarReconcile(**arguments)
        original = self.journal.receipt(options.receipt_id)
        receipt = strict_json(original, RECORD_BYTES, max_values=MAX_RECEIPT_VALUES)
        saved = receipt.get("review", {}).get("native_draft")
        if type(saved) is not dict:
            raise ValueError("Calendar receipt lacks its original reviewed draft.")
        review, captured, target = self._reference(saved.get("request"), receipt.get("draft_id"))
        if (
            review != saved
            or receipt.get("target") != target.model_dump()
            or receipt.get("object_id") != review["source"]["object"]
            or receipt.get("property") != "date-list"
            or receipt.get("array_index") is not None
        ):
            raise ValueError(
                "Calendar receipt differs from its exact original source and property."
            )
        if receipt.get("profile") != PROFILE or receipt.get("rules_sha256") != RULES_SHA256:
            raise ValueError(
                "Calendar receipt active authority is unknown; passive evidence remains retained."
            )
        body = {
            "profile": PROFILE,
            "rules_sha256": RULES_SHA256,
            "scope": SCOPE,
            "operation_id": options.operation_id,
            "receipt_id": options.receipt_id,
            "receipt_sha256": hashlib.sha256(original).hexdigest(),
            "target": target.model_dump(),
            "object_id": review["source"]["object"],
            "property": "date-list",
            "array_index": None,
            "read_only": True,
            "writes_sent": 0,
            "observed_at": utc(),
            "readback": {},
        }
        active = None
        try:
            async with self._operation(options.operation_id) as active:
                async with self.path._path(target) as session:
                    self.reader.pin(session, target.router)
                    await self._readback(
                        session,
                        target,
                        review,
                        self._static(captured, review["source"]["object"]),
                        body["readback"],
                    )
        except asyncio.CancelledError:
            if active is None or active["reason"] is None:
                raise
            body["status"] = active["reason"]
        except Exception as error:
            body["readback"].update(
                status="unavailable", error=str(error)[:500] or type(error).__name__
            )
        return encoded(seal(body))


def calendar_write_router(service):
    router = APIRouter(prefix="/api/bacnet/calendars/writes")

    @router.get("/profile")
    def profile():
        return service.status()

    @router.post("/preview")
    async def preview(body: CalendarPreview):
        return Response(
            encoded(await service.preview(**body.model_dump())), media_type="application/json"
        )

    @router.post("/apply")
    async def apply(body: CalendarApply):
        return Response(await service.apply(**body.model_dump()), media_type="application/json")

    @router.post("/cancel")
    async def cancel(body: CalendarAction):
        return service.cancel(body.operation_id)

    @router.get("/receipts/{id}")
    def receipt(id: str):
        return Response(
            service.journal.receipt(id),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="calendar-write-{id}.json"'},
        )

    @router.post("/reconcile")
    async def reconcile(body: CalendarReconcile):
        return Response(await service.reconcile(**body.model_dump()), media_type="application/json")

    return router
