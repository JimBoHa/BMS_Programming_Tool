"""Reviewed, one-use BACnet AcknowledgeAlarm; never an automatic alarm response."""

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
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bacpypes3.apdu import (
    AcknowledgeAlarmRequest,
    ErrorPDU,
    ErrorRejectAbortNack,
    RejectPDU,
    SimpleAckPDU,
)
from bacpypes3.basetypes import DateTime, TimeStamp
from bacpypes3.errors import DecodingError, InvalidTag
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field, field_validator

from .bacnet_events import (
    MAX_EVENTS,
    MAX_PAGES,
    MAX_REPORT_BYTES,
    EventCancelRequest,
    _json_bytes,
    _summary,
)
from .bacnet_exchange import confirmed_exchange
from .bacnet_values import json_value
from .device_details import DeviceDetails, DeviceDetailsRequest
from .models import StrictModel

PROFILE = "bacnet-reviewed-event-acknowledgement/1"
SCOPE = "Explicit native AcknowledgeAlarm for an exactly retrieved, freshly checked transition. A protocol acceptance is not proof of human receipt, delivery, resolution, or physical correction."
TRANSITIONS = ("to_offnormal", "to_fault", "to_normal")
PLAN_SECONDS = 30
MAX_PLANS = 16


def _utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _sha(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


class EventAckPreview(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    report_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    object_id: str = Field(min_length=1, max_length=80)
    transition: Literal["to_offnormal", "to_fault", "to_normal"]
    operator_name: str = Field(min_length=1, max_length=48)
    process_id: int = Field(ge=0, le=4294967295, strict=True)
    acknowledgement_timezone: str = Field(min_length=1, max_length=128)

    @field_validator("object_id")
    @classmethod
    def actual_object(cls, value):
        obj = ObjectIdentifier(value)
        if not 0 <= int(obj[0]) <= 1023 or not 0 <= obj[1] <= 4194302:
            raise ValueError("Acknowledgement requires an actual event object identifier.")
        return str(obj)

    @field_validator("operator_name")
    @classmethod
    def declared_operator(cls, value):
        value = value.strip()
        if (
            not value
            or len(value.encode("utf-8")) > 48
            or any(
                unicodedata.category(char).startswith("C")
                or unicodedata.category(char) in ("Zl", "Zp")
                for char in value
            )
        ):
            raise ValueError(
                "Enter a visible single-line operator identity of at most 48 UTF-8 bytes."
            )
        return value

    @field_validator("acknowledgement_timezone")
    @classmethod
    def explicit_clock_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError(
                "Select an installed IANA timezone for the acknowledgement clock."
            ) from exc
        return value


class EventAckApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def transition_eligibility(row, transition):
    if row["acknowledged_transitions"].get(transition) is not False:
        return None, "This exact transition is not reported as unacknowledged."
    if row["notify_type"]["value"] not in (0, 1):
        return None, "Unknown/ack-notification Notify_Type is outside this acknowledgement profile."
    current = row["event_state"]["value"]
    if transition == "to_offnormal":
        if current not in (2, 3, 4, 5):
            return (
                None,
                "The exact historical offnormal state is not available from the current summary. Use an event notification/vendor tool that supplies that state.",
            )
        return int(current), None
    return (1 if transition == "to_fault" else 0), None


def _valid_timestamp(stamp):
    choice = stamp._choice
    if choice == "sequenceNumber":
        if not 0 <= int(stamp.sequenceNumber) <= 65535:
            raise ValueError("Event sequence timestamp exceeds Unsigned16.")
        return
    if choice == "dateTime":
        date, clock = tuple(stamp.dateTime.date), tuple(stamp.dateTime.time)
        year, month, day, weekday = date
        if year == 255 or not 1 <= month <= 12 or not 1 <= day <= 31:
            raise ValueError("Unset/wildcard event dates cannot identify an acknowledgement.")
        actual = datetime(1900 + year, month, day)
        if weekday not in (255, actual.weekday() + 1):
            raise ValueError("Event date weekday conflicts with its calendar date.")
    elif choice == "time":
        clock = tuple(stamp.time)
    else:
        raise ValueError("No supported native event TimeStamp choice was supplied.")
    if len(clock) != 4 or not all(
        0 <= value <= high for value, high in zip(clock, (23, 59, 59, 99), strict=True)
    ):
        raise ValueError("Unset/wildcard event times cannot identify an acknowledgement.")


class EventAcknowledgements:
    def __init__(
        self, bacnet, store, inventory, *, timeout=1.5, operation_timeout=15.0, request_gap=0.05
    ):
        self.bacnet, self.store, self.inventory = bacnet, store, inventory
        self.path = DeviceDetails(
            bacnet,
            store,
            timeout=timeout,
            operation_timeout=operation_timeout,
            request_gap=request_gap,
        )
        self.timeout, self.operation_timeout = timeout, operation_timeout
        self._plans, self._receipts, self._cancelled = OrderedDict(), OrderedDict(), OrderedDict()
        self._active = None

    def status(self):
        active = self._active
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "automatic_acknowledgement": False,
            "automatic_retries": False,
            "connected": self.bacnet.status()["connected"],
            "active_operation": None if active is None else active["operation_id"],
            "plan_seconds": PLAN_SECONDS,
            "operation_seconds": self.operation_timeout,
            "receipts": [
                {
                    key: value[key]
                    for key in ("id", "status", "may_have_applied", "finished_at", "target")
                }
                for value in reversed(self._receipts.values())
            ],
        }

    def receipt(self, identifier):
        if identifier not in self._receipts:
            raise ValueError(
                "Acknowledgement receipt is unavailable in this session; consult the local audit or exported receipt."
            )
        return copy.deepcopy(self._receipts[identifier])

    def cancel(self, operation_id, *, reason="cancelled"):
        EventCancelRequest(operation_id=operation_id)
        self._cancelled[operation_id] = True
        while len(self._cancelled) > 64:
            self._cancelled.popitem(last=False)
        active = self._active
        found = active is not None and active["operation_id"] == operation_id
        if found:
            active["cancel_reason"] = reason
            active["task"].cancel()
        return {
            "operation_id": operation_id,
            "cancel_requested": found,
            "note": "Cancellation cannot undo an acknowledgement already transmitted.",
        }

    async def close(self):
        self._plans.clear()
        active = self._active
        if active is not None:
            self.cancel(active["operation_id"], reason="interface_changed")
            if active["task"] is not asyncio.current_task():
                await asyncio.gather(active["task"], return_exceptions=True)

    @asynccontextmanager
    async def _operation(self, operation_id):
        if self._active is not None:
            raise ValueError("An acknowledgement preview/apply is already running.")
        if operation_id in self._cancelled:
            raise ValueError(
                "Acknowledgement operation cancelled before admission; use a new operation_id."
            )
        active = {
            "operation_id": operation_id,
            "task": asyncio.current_task(),
            "cancel_reason": None,
            "deadline": asyncio.get_running_loop().time() + self.operation_timeout,
        }
        self._active = active
        try:
            async with asyncio.timeout(self.operation_timeout):
                yield active
        finally:
            if self._active is active:
                self._active = None

    def _reference(self, request):
        app = self.bacnet.require()
        entry = self.inventory._reports.get(request.report_id)
        if entry is None or entry["superseded"]:
            raise ValueError("Query fresh event evidence before preparing an acknowledgement.")
        report = entry["report"]
        if report["evidence_sha256"] != request.report_sha256:
            raise ValueError("Displayed event report changed; query/review its latest evidence.")
        if entry["app"] is not app or entry["config"] != self.bacnet.config:
            raise ValueError("Event source interface/configuration changed; query again.")
        if not report["identity_verified"] or report["status"] not in ("complete", "partial"):
            raise ValueError("A verified acquired event page is required before acknowledgement.")
        row = next(
            (value for value in report["events"] if value["object_id"] == request.object_id), None
        )
        if row is None:
            raise ValueError("Selected event was not actually retrieved in the referenced report.")
        return (
            app,
            copy.deepcopy(entry["config"]),
            copy.deepcopy(report["target"]),
            copy.deepcopy(row),
        )

    async def _fresh(self, session, target, object_id):
        identity = await self.path._read(session, target["device"], "object-identifier")
        if identity != ObjectIdentifier(target["device"]):
            raise ValueError("Selected Device identity changed.")
        seen, pages, total_bytes, anchor = set(), [], 0, None
        for _ in range(MAX_PAGES):
            values, more, encoded, invoke = await asyncio.wait_for(
                self.inventory._page(session, anchor), self.timeout
            )
            rows = [_summary(value, _utc()) for value in values]
            ids = [value["object_id"] for value in rows]
            total_bytes += len(encoded) + len(_json_bytes(rows))
            if len(set(ids)) != len(ids) or seen.intersection(ids) or (more and not ids):
                raise ValueError(
                    "Fresh event pagination repeated or failed to advance; query again."
                )
            seen.update(ids)
            if len(seen) > MAX_EVENTS or total_bytes > MAX_REPORT_BYTES:
                raise ValueError("Fresh event verification exceeded its bounded result profile.")
            pages.append(
                {
                    "anchor": anchor,
                    "event_count": len(ids),
                    "more_events": more,
                    "received_at": _utc(),
                    "invoke_id": invoke,
                    "decoded_ack_sha256": hashlib.sha256(encoded).hexdigest(),
                }
            )
            for native, row in zip(values, rows, strict=True):
                if row["object_id"] == object_id:
                    return (
                        native,
                        row,
                        {
                            "device": str(identity),
                            "pages": pages,
                            "ignored_router_packets": session.get("ignored_router_packets", 0),
                        },
                    )
            if not more:
                raise ValueError("Selected event is no longer returned by the device; query again.")
            anchor = ids[-1]
        raise ValueError("Selected event was not found within the fresh-query page limit.")

    async def preview(self, **arguments):
        request = EventAckPreview(**arguments)
        app, config, target, original = self._reference(request)
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "can_apply": False,
            "status": "deferred",
            "target": target,
            "source_report_id": request.report_id,
            "source_report_sha256": request.report_sha256,
            "object_id": request.object_id,
            "transition": request.transition,
            "operator_name": request.operator_name,
            "acknowledgement_source": "BMS Studio / " + request.operator_name,
            "operator_identity_policy": "Operator identity is explicitly user declared, not authenticated or inferred from site credentials.",
            "process_id": request.process_id,
            "acknowledgement_timezone": request.acknowledgement_timezone,
            "clock_policy": "TimeOfAcknowledgment is current client time in the explicitly selected timezone at Apply, not the event source timestamp.",
            "created_at": _utc(),
            "expires_at": (datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)).isoformat(),
            "automatic_retries": False,
            "reasons": [],
            "token": None,
        }
        active = None
        try:
            async with self._operation(request.operation_id) as active:
                async with self.path._path(DeviceDetailsRequest(**target)) as session:
                    native, fresh, proof = await self._fresh(session, target, request.object_id)
                    body["fresh_event"], body["fresh_proof"] = fresh, proof
                    if fresh["raw"] != original["raw"]:
                        raise ValueError(
                            "Event state, timestamp, transition bits, or metadata changed since the displayed query. Query and review again."
                        )
                    state, reason = transition_eligibility(fresh, request.transition)
                    if reason:
                        raise ValueError(reason)
                    stamp = native.eventTimeStamps[TRANSITIONS.index(request.transition)]
                    _valid_timestamp(stamp)
                    body.update(
                        can_apply=True,
                        status="review_required",
                        event_state_acknowledged=state,
                        event_timestamp=json_value(stamp),
                    )
        except asyncio.CancelledError:
            if active is None or active["cancel_reason"] is None:
                raise
            body["status"] = active["cancel_reason"]
            body["reasons"].append("Preview cancelled; no acknowledgement was sent.")
        except (
            ValueError,
            TimeoutError,
            OSError,
            ErrorRejectAbortNack,
            DecodingError,
            InvalidTag,
            TypeError,
            AttributeError,
        ) as exc:
            body["reasons"].append(str(exc) or "Fresh acknowledgement preview timed out.")
        if body["can_apply"]:
            body["expires_at"] = (datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)).isoformat()
            token = secrets.token_urlsafe(24)
            body["review_sha256"] = _sha(
                {key: value for key, value in body.items() if key != "token"}
            )
            for old_token, plan in list(self._plans.items()):
                if (
                    plan["body"]["target"] == target
                    and plan["body"]["object_id"] == request.object_id
                    and plan["body"]["transition"] == request.transition
                ):
                    del self._plans[old_token]
            self._plans[token] = {
                "app": app,
                "config": config,
                "request": request,
                "body": copy.deepcopy(body),
                "created": time.monotonic(),
            }
            while len(self._plans) > MAX_PLANS:
                self._plans.popitem(last=False)
            body["token"] = token
        return body

    def _save_receipt(self, receipt):
        receipt["finished_at"] = _utc()
        try:
            self.store.record("bacnet.event_ack.result", receipt, lock_timeout=0.25)
        except Exception:
            receipt["audit_error"] = (
                "Acknowledgement outcome could not be appended to the local audit. A recorded dispatch intent, if present, remains unresolved."
            )
        receipt["evidence_sha256"] = _sha(receipt)
        self._receipts[receipt["id"]] = copy.deepcopy(receipt)
        while len(self._receipts) > 32:
            self._receipts.popitem(last=False)

    async def apply(self, **arguments):
        request = EventAckApply(**arguments)
        plan = self._plans.pop(request.token, None)
        if plan is None or not secrets.compare_digest(
            plan["body"]["review_sha256"], request.review_sha256
        ):
            raise ValueError("Acknowledgement review token is invalid, changed, or already used.")
        if time.monotonic() - plan["created"] > PLAN_SECONDS:
            raise ValueError("Acknowledgement review expired; preview again.")
        app, config, target, _ = self._reference(plan["request"])
        if app is not plan["app"] or config != plan["config"]:
            raise ValueError("Reviewed acknowledgement interface changed; query again.")
        body = plan["body"]
        receipt = {
            "id": secrets.token_hex(16),
            "profile": PROFILE,
            "scope": SCOPE,
            "status": "not_sent",
            "may_have_applied": False,
            "protocol_accepted": False,
            "dispatch_started": False,
            "automatic_retries": False,
            "requires_fresh_query": True,
            "started_at": _utc(),
            "finished_at": None,
            "target": target,
            "review_sha256": request.review_sha256,
            "review": copy.deepcopy(body),
            "errors": [],
            "phase": "freshness_guard",
        }
        active, caller_cancel, ack = None, False, None
        try:
            async with self._operation(request.operation_id) as active:
                async with self.path._path(DeviceDetailsRequest(**target)) as session:
                    native, fresh, proof = await self._fresh(session, target, body["object_id"])
                    receipt["fresh_event"], receipt["fresh_proof"] = fresh, proof
                    if fresh["raw"] != body["fresh_event"]["raw"]:
                        raise ValueError(
                            "Reviewed event changed or was acknowledged elsewhere; no acknowledgement sent."
                        )
                    state, reason = transition_eligibility(fresh, body["transition"])
                    if reason or state != body["event_state_acknowledged"]:
                        raise ValueError(reason or "Reviewed event state changed.")
                    stamp = native.eventTimeStamps[TRANSITIONS.index(body["transition"])]
                    _valid_timestamp(stamp)
                    now = datetime.now(UTC)
                    local = now.astimezone(ZoneInfo(body["acknowledgement_timezone"]))
                    clock = TimeStamp(
                        dateTime=DateTime(
                            date=(local.year - 1900, local.month, local.day, local.weekday() + 1),
                            time=(
                                local.hour,
                                local.minute,
                                local.second,
                                local.microsecond // 10000,
                            ),
                        )
                    )
                    ack = AcknowledgeAlarmRequest(
                        acknowledgingProcessIdentifier=body["process_id"],
                        eventObjectIdentifier=ObjectIdentifier(body["object_id"]),
                        eventStateAcknowledged=state,
                        timeStamp=stamp,
                        acknowledgmentSource=body["acknowledgement_source"],
                        timeOfAcknowledgment=clock,
                        destination=session["target"],
                    )
                    if len(ack.encode().pduData) + 4 > 128:
                        raise ValueError(
                            "Acknowledgement exceeds the 128-byte unsegmented profile; no request sent."
                        )
                    receipt["phase"] = "acknowledgement"
                    receipt["acknowledgement_clock"] = {
                        "utc": now.isoformat(),
                        "timezone": body["acknowledgement_timezone"],
                        "utc_offset_seconds": int(local.utcoffset().total_seconds()),
                        "fold": local.fold,
                    }

                    def before_send(packet):
                        self.path._guard(session)
                        if asyncio.get_running_loop().time() >= active["deadline"]:
                            raise TimeoutError("Acknowledgement operation expired before dispatch.")
                        receipt["native_request"] = json_value(ack)
                        receipt["request_apdu_sha256"] = hashlib.sha256(
                            bytes(packet.encode().pduData)
                        ).hexdigest()
                        self.store.record(
                            "bacnet.event_ack.dispatch_intent", receipt, lock_timeout=0.25
                        )
                        self.path._guard(session)
                        if asyncio.get_running_loop().time() >= active["deadline"]:
                            raise TimeoutError(
                                "Acknowledgement operation expired while recording dispatch intent."
                            )
                        receipt["dispatch_started"] = True
                        receipt["may_have_applied"] = True

                    reply = await asyncio.wait_for(
                        confirmed_exchange(app, ack, single_attempt=True, before_send=before_send),
                        self.timeout,
                    )
                    self.path._guard(session)
                    if (
                        not isinstance(reply, SimpleAckPDU)
                        or reply.pduSource != session["target"]
                        or reply.apduInvokeID != ack.apduInvokeID
                        or reply.apduService != ack.apduService
                    ):
                        raise ValueError(
                            "Acknowledgement response source/invoke/service/type mismatch."
                        )
                    receipt.update(
                        status="accepted",
                        protocol_accepted=True,
                        response_received_at=_utc(),
                        response={
                            "type": "SimpleACK",
                            "source": str(reply.pduSource),
                            "invoke_id": reply.apduInvokeID,
                            "service_choice": reply.apduService,
                        },
                    )
        except ErrorRejectAbortNack as exc:
            rejected = (
                isinstance(exc, (ErrorPDU, RejectPDU))
                and ack is not None
                and exc.pduSource == Address(target["address"])
                and exc.apduInvokeID == ack.apduInvokeID
                and (not isinstance(exc, ErrorPDU) or exc.apduService == ack.apduService)
            )
            receipt["status"] = (
                "rejected" if rejected else "unknown" if receipt["dispatch_started"] else "not_sent"
            )
            if rejected:
                receipt["may_have_applied"] = False
            receipt["failure_observed_at"] = _utc()
            receipt["response"] = {
                "type": type(exc).__name__,
                "source": str(exc.pduSource),
                "invoke_id": exc.apduInvokeID,
                "service_choice": getattr(exc, "apduService", None),
                "validated_rejection": rejected,
                "origin": "validated-native-rejection"
                if rejected
                else "unverified-native-or-local-protocol-failure",
                "reason": str(exc),
            }
            if isinstance(exc, ErrorPDU):
                receipt["response"]["native_error"] = {
                    "errorClass": json_value(exc.errorClass),
                    "errorCode": json_value(exc.errorCode),
                }
            elif isinstance(exc, RejectPDU):
                receipt["response"]["reject_reason"] = int(exc.apduAbortRejectReason)
            receipt["errors"].append(str(exc))
        except asyncio.CancelledError:
            caller_cancel = active is None or active["cancel_reason"] is None
            receipt["status"] = "unknown" if receipt["dispatch_started"] else "cancelled"
            receipt["errors"].append(
                "Cancelled; any transmitted acknowledgement cannot be undone. Re-query before another attempt."
            )
        except (
            ValueError,
            TimeoutError,
            OSError,
            sqlite3.Error,
            DecodingError,
            InvalidTag,
            TypeError,
            AttributeError,
        ) as exc:
            receipt["status"] = "unknown" if receipt["dispatch_started"] else "not_sent"
            receipt["errors"].append(
                str(exc)
                or "Acknowledgement deadline reached. Outcome may be unknown if dispatch began."
            )
        self._save_receipt(receipt)
        if caller_cancel:
            raise asyncio.CancelledError
        return receipt
