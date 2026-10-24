"""Explicit, read-only BACnet GetEventInformation with owned transactions.

EventSummary is device evidence, not an unsolicited notification, local alarm,
delivery receipt, or acknowledgement command. Device clocks are kept raw.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import secrets
import time
from collections import OrderedDict
from datetime import UTC, datetime

from bacpypes3.apdu import (
    Error,
    ErrorPDU,
    ErrorRejectAbortNack,
    GetEventInformationACK,
    GetEventInformationRequest,
    RejectPDU,
    error_types,
)
from bacpypes3.errors import DecodingError, InvalidTag
from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field, model_validator

from .bacnet_exchange import confirmed_exchange
from .bacnet_values import json_value
from .device_details import DeviceDetails, DeviceDetailsRequest, _InterfaceChanged
from .models import StrictModel

PROFILE = "bacnet-get-event-information/1"
SCOPE = (
    "Explicit read-only GetEventInformation from the selected BACnet Device. "
    "Reported states and acknowledged-transition bits are device evidence, not "
    "notification delivery, operator receipt, subscriptions, or acknowledgement writes."
)
MAX_PAGES = 20
MAX_EVENTS = 500
MAX_PAGE_BYTES = 64 * 1024
MAX_REPORT_BYTES = 1024 * 1024
MAX_REPORTS = 16
MAX_ATTEMPTS = 32
CURSOR_SECONDS = 300
TRANSITIONS = ("to_offnormal", "to_fault", "to_normal")


class _GetEventInformationError(Error):
    # BACpypes3 0.0.110 registers the request/ACK but omits choice 29 from its
    # generic BACnet-Error decoder table. Without this, real service errors are
    # dropped and misleadingly appear to be timeouts. Preserve existing codecs.
    service_choice = GetEventInformationRequest.service_choice


error_types.setdefault(_GetEventInformationError.service_choice, _GetEventInformationError)


def _utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _error(report, status, message):
    text = str(message)
    report["errors"].append(
        {
            "status": status,
            "error": text[:2048],
            "error_truncated": len(text) > 2048,
            "received_at": _utc(),
        }
    )


class EventInventoryRequest(DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    pages_per_request: int = Field(default=1, ge=1, le=5, strict=True)
    report_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    cursor: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{32}$")

    @model_validator(mode="after")
    def paired_continuation(self):
        if (self.report_id is None) != (self.cursor is None):
            raise ValueError("Event continuation requires both report_id and its unused cursor.")
        return self


class EventCancelRequest(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class _EventFailure(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _summary(value, received_at):
    obj = value.objectIdentifier
    if not 0 <= int(obj[0]) <= 1023 or not 0 <= obj[1] <= 4194302:
        raise _EventFailure(
            "protocol_error", "EventSummary contains an invalid/wildcard object identifier."
        )
    raw = json_value(value)
    acknowledgements, enabled = list(value.acknowledgedTransitions), list(value.eventEnable)
    stamps, priorities = list(value.eventTimeStamps), list(value.eventPriorities)
    if any(len(items) != 3 for items in (acknowledgements, enabled, stamps, priorities)):
        raise _EventFailure(
            "protocol_error",
            "EventSummary requires three transition bits, timestamps, and priorities.",
        )
    if any(not 0 <= int(priority) <= 255 for priority in priorities):
        raise _EventFailure(
            "protocol_error", "EventSummary priorities exceed the standard 0..255 range."
        )
    clocks = []
    for transition, stamp in zip(TRANSITIONS, stamps, strict=True):
        if stamp._choice not in ("time", "sequenceNumber", "dateTime"):
            raise _EventFailure(
                "protocol_error",
                "EventSummary timestamp has no recognized BACnet TimeStamp choice.",
            )
        clocks.append(
            {
                "transition": transition,
                "raw": json_value(stamp),
                "source_clock_utc": None,
                "clock_status": "sequence-not-wall-clock"
                if stamp._choice == "sequenceNumber"
                else "raw-device-clock-no-timezone",
            }
        )
    return {
        "object_id": str(obj),
        "event_state": {"value": json_value(value.eventState), "name": str(value.eventState)},
        "notify_type": {"value": json_value(value.notifyType), "name": str(value.notifyType)},
        "acknowledged_transitions": dict(
            zip(TRANSITIONS, map(bool, acknowledgements), strict=True)
        ),
        "event_enable": dict(zip(TRANSITIONS, map(bool, enabled), strict=True)),
        "event_priorities": dict(zip(TRANSITIONS, map(int, priorities), strict=True)),
        "event_timestamps": clocks,
        "received_at": received_at,
        "quality": "not-supplied-by-EventSummary",
        "raw": raw,
    }


class EventInventory:
    def __init__(self, bacnet, store, *, timeout=1.5, operation_timeout=15.0, request_gap=0.05):
        self.bacnet, self.store = bacnet, store
        self.path = DeviceDetails(
            bacnet,
            store,
            timeout=timeout,
            operation_timeout=operation_timeout,
            request_gap=request_gap,
        )
        self.timeout, self.operation_timeout, self.request_gap = (
            timeout,
            operation_timeout,
            request_gap,
        )
        self._reports = OrderedDict()
        self._cancelled = OrderedDict()
        self._active = None

    def status(self):
        active = self._active
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "read_only": True,
            "auto_poll": False,
            "connected": self.bacnet.status()["connected"],
            "active_operation": None if active is None else active["operation_id"],
            "limits": {
                "request_seconds": self.timeout,
                "operation_seconds": self.operation_timeout,
                "request_gap_seconds": self.request_gap,
                "pages_per_request": 5,
                "pages_per_report": MAX_PAGES,
                "events": MAX_EVENTS,
                "page_bytes": MAX_PAGE_BYTES,
                "report_bytes": MAX_REPORT_BYTES,
                "reports": MAX_REPORTS,
                "attempts_per_report": MAX_ATTEMPTS,
                "cursor_seconds": CURSOR_SECONDS,
            },
        }

    def cancel(self, operation_id, *, reason="cancelled"):
        EventCancelRequest(operation_id=operation_id)
        self._cancelled[operation_id] = time.monotonic()
        self._cancelled.move_to_end(operation_id)
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
            "late_admission_prevented": True,
            "field_writes": False,
        }

    async def close(self, reason="interface_changed"):
        active = self._active
        if active is not None:
            self.cancel(active["operation_id"], reason=reason)
            if active["task"] is not asyncio.current_task():
                await asyncio.gather(active["task"], return_exceptions=True)

    def _entry(self, options, app):
        target = {key: getattr(options, key) for key in ("address", "device", "router", "dnet")}
        if options.report_id:
            entry = self._reports.get(options.report_id)
            if entry is None:
                raise ValueError("Event report expired or was evicted; start a new query.")
            if (
                entry["superseded"]
                or entry["cursor"] is None
                or not secrets.compare_digest(entry["cursor"], options.cursor)
            ):
                raise ValueError(
                    "Event cursor is stale, already used, or superseded; use the latest report."
                )
            if time.monotonic() - entry["updated"] > CURSOR_SECONDS:
                raise ValueError("Event continuation expired; start a fresh query.")
            if entry["app"] is not app or entry["config"] != self.bacnet.config:
                raise ValueError("Event interface changed; start a fresh query.")
            if entry["report"]["target"] != target:
                raise ValueError("Event cursor target/Device/route differs from its source report.")
            if entry["report"]["attempts"] >= MAX_ATTEMPTS:
                raise ValueError("Event report attempt limit reached; start a fresh query.")
            entry["cursor"] = None  # Claim before the first await; it cannot be replayed.
            return entry
        for previous in self._reports.values():
            if previous["app"] is app and previous["report"]["target"] == target:
                previous["superseded"] = True
                previous["cursor"] = None
        return {
            "app": app,
            "config": copy.deepcopy(self.bacnet.config),
            "updated": time.monotonic(),
            "cursor": None,
            "superseded": False,
            "report": {
                "id": secrets.token_hex(16),
                "profile": PROFILE,
                "scope": SCOPE,
                "source_kind": "bacnet-get-event-information",
                "read_only": True,
                "target": target,
                "connector_config": copy.deepcopy(self.bacnet.config),
                "started_at": _utc(),
                "finished_at": None,
                "identity_verified": False,
                "device_identity_reads": [],
                "attempts": 0,
                "events": [],
                "pages": [],
                "errors": [],
                "complete": False,
                "status": "not_read",
                "outcome": None,
                "next_cursor": None,
                "more_events": None,
                "ignored_router_packets": 0,
                "consistency": "Live device list, not an atomic snapshot; repeat after changes. Source order is preserved without assuming numeric sort order.",
                "timestamp_basis": "Event TimeStamp choices and wildcard fields are raw device evidence. Receipt timestamps are local UTC; no device timezone is inferred.",
                "acknowledgement_basis": "acknowledgedTransitions is the device's reported bit state. No operator receipt, alarm delivery, subscription, or acknowledgement action is inferred.",
            },
        }

    async def _page(self, session, anchor):
        self.path._guard(session)
        delay = self.request_gap - (asyncio.get_running_loop().time() - session["last_request"])
        if delay > 0:
            await asyncio.sleep(delay)
        self.path._guard(session)
        session["last_request"] = asyncio.get_running_loop().time()
        request = GetEventInformationRequest(destination=session["target"])
        if anchor is not None:
            request.lastReceivedObjectIdentifier = ObjectIdentifier(anchor)
        try:
            reply = await asyncio.wait_for(
                confirmed_exchange(session["app"], request), self.timeout
            )
        except ErrorRejectAbortNack as exc:
            if (
                exc.pduSource != session["target"]
                or exc.apduInvokeID != request.apduInvokeID
                or (isinstance(exc, ErrorPDU) and exc.apduService != request.apduService)
            ):
                raise _EventFailure(
                    "protocol_error", "Event rejection source/invoke identity mismatch."
                ) from exc
            unsupported = (isinstance(exc, RejectPDU) and int(exc.reason) == 9) or (
                isinstance(exc, ErrorPDU) and int(exc.reason) in (45, 67)
            )
            raise _EventFailure(
                "unsupported" if unsupported else "rejected",
                "GetEventInformation rejected: " + str(exc),
            ) from exc
        self.path._guard(session)
        if (
            not isinstance(reply, GetEventInformationACK)
            or reply.pduSource != session["target"]
            or reply.apduInvokeID != request.apduInvokeID
            or reply.apduService != request.apduService
        ):
            raise _EventFailure(
                "protocol_error",
                "GetEventInformation acknowledgement source/invoke/service mismatch.",
            )
        encoded = bytes(reply.encode().encode().pduData)
        if len(encoded) > MAX_PAGE_BYTES:
            raise _EventFailure(
                "limit_exceeded", "Event acknowledgement exceeds the 64 KiB page bound."
            )
        values = list(reply.listOfEventSummaries)
        if len(values) > MAX_EVENTS:
            raise _EventFailure(
                "limit_exceeded", "Event acknowledgement exceeds the 500-event report bound."
            )
        if reply.moreEvents is None:
            raise _EventFailure("protocol_error", "Event acknowledgement omits moreEvents.")
        return values, bool(reply.moreEvents), encoded, request.apduInvokeID

    async def read(self, **arguments):
        options = EventInventoryRequest(**arguments)
        app = self.bacnet.require()
        if self._active is not None:
            raise ValueError("An event acquisition is already running; cancel or wait for it.")
        if options.operation_id in self._cancelled:
            raise ValueError(
                "This operation was cancelled before admission; start with a new operation_id."
            )
        entry = self._entry(options, app)
        report = copy.deepcopy(entry["report"])
        report.update(
            complete=False,
            next_cursor=None,
            status="reading",
            outcome=None,
            identity_verified=False,
        )
        report["attempts"] += 1
        report.pop("evidence_sha256", None)
        active = {
            "operation_id": options.operation_id,
            "task": asyncio.current_task(),
            "cancel_reason": None,
        }
        self._active = active
        session, resumable = None, False
        try:
            async with asyncio.timeout(self.operation_timeout):
                async with self.path._path(options) as session:
                    if session["app"] is not entry["app"] or session["config"] != entry["config"]:
                        raise _InterfaceChanged("Event interface changed before the query started.")
                    identity = await self.path._read(session, options.device, "object-identifier")
                    if identity != ObjectIdentifier(options.device):
                        raise _EventFailure(
                            "identity_mismatch",
                            "Device identity differs from the explicitly selected Device.",
                        )
                    report["identity_verified"] = True
                    report["device_identity_reads"].append(
                        {"device": str(identity), "received_at": _utc()}
                    )
                    seen = {event["object_id"] for event in report["events"]}
                    anchor = report["pages"][-1]["last_object_id"] if report["pages"] else None
                    for _ in range(options.pages_per_request):
                        if len(report["pages"]) >= MAX_PAGES or len(report["events"]) >= MAX_EVENTS:
                            raise _EventFailure(
                                "limit_exceeded",
                                "Event report page/event limit reached; start a fresh bounded query.",
                            )
                        values, more, encoded, invoke = await self._page(session, anchor)
                        receipt = _utc()
                        events = [_summary(value, receipt) for value in values]
                        identifiers = [event["object_id"] for event in events]
                        if len(set(identifiers)) != len(identifiers) or seen.intersection(
                            identifiers
                        ):
                            raise _EventFailure(
                                "protocol_error",
                                "Repeated EventSummary object/cursor; the live event list changed or pagination failed. Restart the query.",
                            )
                        if more and not events:
                            raise _EventFailure(
                                "protocol_error",
                                "Empty event page claims moreEvents; its cursor cannot advance.",
                            )
                        if len(report["events"]) + len(events) > MAX_EVENTS:
                            raise _EventFailure(
                                "limit_exceeded",
                                "Event page would exceed the 500-event report bound; page not imported.",
                            )
                        page = {
                            "number": len(report["pages"]) + 1,
                            "request_anchor": anchor,
                            "last_object_id": identifiers[-1] if identifiers else anchor,
                            "event_count": len(events),
                            "more_events": more,
                            "received_at": receipt,
                            "invoke_id": invoke,
                            "acknowledgement_bytes": len(encoded),
                            "acknowledgement_sha256": hashlib.sha256(encoded).hexdigest(),
                            "hash_encoding": "BACpypes3 re-encoding of the decoded ACK; not a packet-capture hash",
                        }
                        if (
                            len(_json_bytes(report))
                            + len(_json_bytes(events))
                            + len(_json_bytes(page))
                            > MAX_REPORT_BYTES - 128 * 1024
                        ):
                            raise _EventFailure(
                                "limit_exceeded",
                                "Event report exceeds the 1 MiB result bound; page not imported.",
                            )
                        report["events"].extend(events)
                        report["pages"].append(page)
                        report["more_events"] = more
                        seen.update(identifiers)
                        anchor = page["last_object_id"]
                        if not more:
                            report.update(complete=True, status="complete", outcome="complete")
                            break
                    else:
                        resumable = True
                        report.update(status="partial", outcome="page_boundary")
        except _EventFailure as exc:
            report["outcome"] = exc.status
            report["status"] = "partial" if report["pages"] else exc.status
            _error(report, exc.status, exc)
        except TimeoutError:
            report["outcome"] = "timeout"
            report["status"] = "partial" if report["pages"] else "timeout"
            _error(
                report,
                "timeout",
                "Event request/operation deadline reached; completed pages retained.",
            )
            resumable = bool(report["more_events"])
        except _InterfaceChanged as exc:
            report["status"], report["outcome"] = "interrupted", "interface_changed"
            _error(report, "interface_changed", exc)
        except asyncio.CancelledError:
            changed = self.bacnet.app is not app
            if active["cancel_reason"] is None and not changed:
                raise
            reason = active["cancel_reason"] or "interface_changed"
            report["status"], report["outcome"] = (
                "cancelled" if reason == "cancelled" else "interrupted",
                reason,
            )
            _error(report, reason, "Event acquisition cancelled; owned exchanges retired.")
        except (ValueError, DecodingError, InvalidTag, TypeError, AttributeError) as exc:
            report["outcome"] = "protocol_error"
            report["status"] = "partial" if report["pages"] else "protocol_error"
            _error(report, "protocol_error", exc)
        finally:
            if self._active is active:
                self._active = None
        if session is not None:
            report["ignored_router_packets"] += session.get("ignored_router_packets", 0)
        if (
            resumable
            and report["more_events"]
            and len(report["pages"]) < MAX_PAGES
            and len(report["events"]) < MAX_EVENTS
            and report["attempts"] < MAX_ATTEMPTS
        ):
            entry["cursor"] = secrets.token_urlsafe(24)
            report["next_cursor"] = {
                "report_id": report["id"],
                "token": entry["cursor"],
                "last_received_object_identifier": report["pages"][-1]["last_object_id"],
                "expires_after_seconds": CURSOR_SECONDS,
            }
        elif resumable and report["more_events"]:
            report["outcome"] = "limit_exceeded"
            _error(
                report,
                "limit_exceeded",
                "Event report page/event/attempt bound reached; start a fresh query.",
            )
        report["finished_at"] = _utc()
        report["evidence_sha256"] = hashlib.sha256(_json_bytes(report)).hexdigest()
        entry["report"], entry["updated"] = copy.deepcopy(report), time.monotonic()
        self._reports[report["id"]] = entry
        self._reports.move_to_end(report["id"])
        while len(self._reports) > MAX_REPORTS:
            self._reports.popitem(last=False)
        try:
            self.store.record(
                "bacnet.events.read",
                {
                    "target": report["target"],
                    "report_id": report["id"],
                    "status": report["status"],
                    "outcome": report["outcome"],
                    "events": len(report["events"]),
                    "pages": len(report["pages"]),
                    "evidence_sha256": report["evidence_sha256"],
                },
            )
        except Exception:
            report["audit_error"] = (
                "Event evidence was read but its local audit entry could not be saved."
            )
            report.pop("evidence_sha256", None)
            report["evidence_sha256"] = hashlib.sha256(_json_bytes(report)).hexdigest()
            entry["report"] = copy.deepcopy(report)
        return report
