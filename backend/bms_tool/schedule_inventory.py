"""Finite standard Calendar/Schedule reads, separate from schedule execution.

Only ReadProperty is sent. Wildcard fields, AnyAtomic wire types and unresolved
device clocks are evidence; no local evaluator or proprietary mapping is guessed.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import secrets
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from bacpypes3.object import CalendarObject, DeviceObject, ScheduleObject
from bacpypes3.primitivedata import (
    ObjectIdentifier,
    Unsigned,
)
from pydantic import Field, field_validator

from .device_details import DeviceDetails, DeviceDetailsRequest, _InterfaceChanged
from .models import StrictModel
from .property_evidence import PropertyEvidence, ReadBudget

PROFILE = "native-calendar-schedule-inventory/1"
SCOPE = (
    "Explicit read-only standard BACnet Calendar(type6)/Schedule(type17) inventory over "
    "an already-open IPv4 interface and optional pinned router/DNET:MAC. Unsegmented "
    "single-attempt ReadProperty, bounded indexed arrays and explicit Object_List pages. "
    "Sequential observations are not an atomic/coherent backup. No edits, transfers, "
    "referenced-device crawling, schedule simulation or inferred device timezone. "
    "Physical JCI/manufacturer acceptance is unverified."
)
MAX_REPORTS, MAX_REPORT_BYTES, MAX_VALUE_BYTES = 16, 2 * 1024 * 1024, 16 * 1024
MAX_ENTRIES, MAX_REQUESTS = 32, 1024
CLASSES = {6: CalendarObject, 17: ScheduleObject, 8: DeviceObject}
COMMON = ("object-name", "description", "present-value")
SCHEDULE = (
    "effective-period",
    "schedule-default",
    "priority-for-writing",
    "list-of-object-property-references",
    "status-flags",
    "reliability",
    "out-of-service",
)
CLOCK = ("local-date", "local-time", "utc-offset", "daylight-savings-status")


def _utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class ScheduleReadRequest(DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    object_ids: list[str] | None = Field(default=None, min_length=1, max_length=16)
    object_list_offset: int = Field(default=0, ge=0, le=20000, strict=True)
    object_list_limit: int = Field(default=64, ge=1, le=256, strict=True)
    max_objects: int = Field(default=4, ge=1, le=16, strict=True)
    include_device_clock: bool = Field(default=False, strict=True)

    @field_validator("object_ids")
    @classmethod
    def schedule_types(cls, values):
        if values is None:
            return None
        result = []
        for value in values:
            obj = ObjectIdentifier(value)
            if int(obj[0]) not in (6, 17) or not 0 <= obj[1] <= 4194302:
                raise ValueError("Select explicit standard Calendar or Schedule objects only.")
            result.append(str(obj))
        if len(result) != len(set(result)):
            raise ValueError("Duplicate Calendar/Schedule selection.")
        return result


class ScheduleAction(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class ScheduleExport(StrictModel):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")


class ScheduleInventory:
    def __init__(
        self, bacnet, store=None, *, timeout=1.0, operation_timeout=15.0, request_gap=0.02
    ):
        self.bacnet, self.store = bacnet, store
        self.timeout, self.operation_timeout, self.request_gap = (
            timeout,
            operation_timeout,
            request_gap,
        )
        self.path = DeviceDetails(
            bacnet,
            store,
            timeout=timeout,
            operation_timeout=operation_timeout,
            request_gap=request_gap,
        )
        self.reader = PropertyEvidence(self.path)
        self.reports, self.cancelled = OrderedDict(), OrderedDict()
        self.active = None
        self.closed = False

    def status(self):
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "read_only": True,
            "auto_query": False,
            "active_operation": self.active["id"] if self.active else None,
            "limits": {
                "reports": MAX_REPORTS,
                "report_bytes": MAX_REPORT_BYTES,
                "value_bytes": MAX_VALUE_BYTES,
                "objects": 16,
                "object_list_page": 256,
                "array_entries": MAX_ENTRIES,
                "requests": MAX_REQUESTS,
                "request_seconds": self.timeout,
                "operation_seconds": self.operation_timeout,
            },
            "reports": [
                {
                    key: report[key]
                    for key in (
                        "id",
                        "target",
                        "started_at",
                        "finished_at",
                        "status",
                        "complete",
                        "evidence_sha256",
                    )
                }
                for report in self.reports.values()
            ],
        }

    def cancel(self, operation_id):
        ScheduleAction(operation_id=operation_id)
        self.cancelled[operation_id] = True
        while len(self.cancelled) > 64:
            self.cancelled.popitem(last=False)
        found = self.active is not None and self.active["id"] == operation_id
        if found:
            self.active["cancelled"] = True
            self.active["task"].cancel()
        return {"operation_id": operation_id, "cancel_requested": found, "field_writes": False}

    async def close(self):
        self.closed = True
        if self.active:
            task = self.active["task"]
            self.cancel(self.active["id"])
            if task is not asyncio.current_task():
                await asyncio.gather(task, return_exceptions=True)

    def _guard(self, session):
        self.reader.guard(session)

    @asynccontextmanager
    async def _wire(self, session, report, request):
        budget = ReadBudget(ignored_peers=report["ignored_transport_candidates"])
        try:
            async with self.reader.wire(session, budget, request) as evidence:
                yield evidence
        finally:
            report["ignored_transport_candidates"] = budget.ignored_peers

    async def _read(self, session, report, obj, prop, index=None):
        budget = ReadBudget(
            max_requests=MAX_REQUESTS,
            max_bytes=MAX_REPORT_BYTES - 128 * 1024,
            requests=report["requests"],
            retained_bytes=report["retained_property_bytes"],
            ignored_peers=report["ignored_transport_candidates"],
        )
        try:
            return await self.reader.read(
                session,
                budget,
                obj,
                prop,
                CLASSES[int(ObjectIdentifier(obj)[0])],
                index,
                timeout=self.timeout,
                request_gap=self.request_gap,
            )
        finally:
            report.update(budget.snapshot())

    async def _array(self, session, report, obj, prop, result, *, expected=None):
        count, count_row = await self._read(session, report, obj, prop, 0)
        result.update(status=count_row["status"], count_read=count_row)
        if not isinstance(count, Unsigned):
            return result
        if expected is not None and count != expected:
            result.update(
                status="invalid_count",
                error=f"Expected {expected} elements; native count is {count}.",
            )
        elif count > MAX_ENTRIES:
            result.update(
                status="limited",
                error=f"Only {MAX_ENTRIES} array entries are inspected; native count is {count}.",
            )
        else:
            result["status"] = "ok"
        for index in range(1, min(int(count), MAX_ENTRIES) + 1):
            _, row = await self._read(session, report, obj, prop, index)
            result["elements"].append(row)
        result["complete"] = (
            int(count) <= MAX_ENTRIES
            and (expected is None or count == expected)
            and all(r["status"] == "ok" for r in result["elements"])
        )
        if not result["complete"] and result["status"] == "ok":
            result["status"] = "partial"
        return result

    async def read(self, **arguments):
        options = ScheduleReadRequest(**arguments)
        if self.closed or self.active is not None:
            raise ValueError("Schedule inventory is closed or another read is active.")
        if options.operation_id in self.cancelled:
            raise ValueError("Operation was cancelled before admission; use a new operation ID.")
        app = self.bacnet.require()
        config = copy.deepcopy(self.bacnet.config)
        if config.get("transport") == "mstp" or config.get("bbmd_address"):
            raise ValueError(
                "Calendar/Schedule inspection requires plain IPv4 without BBMD or serial."
            )
        report = {
            "id": secrets.token_hex(16),
            "profile": PROFILE,
            "scope": SCOPE,
            "target": {
                key: getattr(options, key) for key in ("address", "device", "router", "dnet")
            },
            "connector_config": config,
            "started_at": _utc(),
            "finished_at": None,
            "identity_verified": False,
            "complete": False,
            "status": "reading",
            "requests": 0,
            "retained_property_bytes": 0,
            "ignored_transport_candidates": 0,
            "operation_id": options.operation_id,
            "objects": [],
            "device_clock": {},
            "inventory": {},
            "errors": [],
            "consistency": "Sequential live observations; no atomic/coherent backup or frozen schedule is established.",
            "source_clock_utc": None,
            "clock_basis": "Native fields stay raw; receipt clocks are local UTC. No IANA timezone is inferred from UTC offset/DST.",
        }
        active = {"id": options.operation_id, "task": asyncio.current_task(), "cancelled": False}
        self.active = active
        session = None
        try:
            async with asyncio.timeout(self.operation_timeout):
                async with self.path._path(options) as session:
                    if session["app"] is not app or session["config"] != config:
                        raise _InterfaceChanged(
                            "Schedule inventory interface changed before acquisition."
                        )
                    self.reader.pin(session, options.router)
                    actual, row = await self._read(
                        session, report, options.device, "object-identifier"
                    )
                    report["device_identity"] = row
                    if actual != ObjectIdentifier(options.device):
                        raise ValueError(
                            "Selected Device identity was not verified; no schedule properties read."
                        )
                    report["identity_verified"] = True
                    if options.include_device_clock:
                        for prop in CLOCK:
                            _, report["device_clock"][prop] = await self._read(
                                session, report, options.device, prop
                            )
                    selected = options.object_ids
                    if selected is None:
                        selected = []
                        count, row = await self._read(
                            session, report, options.device, "object-list", 0
                        )
                        inventory = {
                            "count_read": row,
                            "entries": [],
                            "next_offset": None,
                            "complete": False,
                            "offset": options.object_list_offset,
                            "limit": options.object_list_limit,
                        }
                        report["inventory"] = inventory
                        if not isinstance(count, Unsigned) or not 0 <= count <= 20000:
                            raise ValueError(
                                "Device Object_List count is unavailable or outside its profile."
                            )
                        if options.object_list_offset > count:
                            raise ValueError("Object_List offset exceeds its current native count.")
                        last = options.object_list_offset
                        for index in range(
                            last + 1, min(int(count), last + options.object_list_limit) + 1
                        ):
                            obj, row = await self._read(
                                session, report, options.device, "object-list", index
                            )
                            inventory["entries"].append(row)
                            last = index
                            if (
                                isinstance(obj, ObjectIdentifier)
                                and int(obj[0]) in (6, 17)
                                and obj[1] != 4194303
                            ):
                                name = str(obj)
                                if name in selected:
                                    raise ValueError(
                                        "Repeated Calendar/Schedule identity in live Object_List; repeat inventory."
                                    )
                                selected.append(name)
                                if len(selected) >= options.max_objects:
                                    break
                        inventory.update(
                            next_offset=last if last < count else None,
                            complete=last == count
                            and options.object_list_offset == 0
                            and all(r["status"] == "ok" for r in inventory["entries"]),
                        )
                    else:
                        report["inventory"] = {
                            "selection": list(selected),
                            "basis": "Explicit selection; Device Object_List membership not inferred.",
                        }
                    for obj in selected:
                        item = {
                            "object": obj,
                            "identity_verified": False,
                            "properties": {},
                            "complete": False,
                        }
                        report["objects"].append(item)
                        actual, row = await self._read(session, report, obj, "object-identifier")
                        item["properties"]["object-identifier"] = row
                        if actual != ObjectIdentifier(obj):
                            item["error"] = (
                                "Object identity not verified; its schedule/calendar fields were not read."
                            )
                            continue
                        item["identity_verified"] = True
                        props = COMMON + (
                            ("date-list",) if int(ObjectIdentifier(obj)[0]) == 6 else SCHEDULE
                        )
                        for prop in props:
                            _, item["properties"][prop] = await self._read(
                                session, report, obj, prop
                            )
                        if int(ObjectIdentifier(obj)[0]) == 17:
                            for prop, expected in (
                                ("weekly-schedule", 7),
                                ("exception-schedule", None),
                            ):
                                array = {
                                    "status": "reading",
                                    "count_read": None,
                                    "elements": [],
                                    "complete": False,
                                    "read_in_progress": True,
                                }
                                # Attach before awaiting so cancellation retains every
                                # completed index, including a partially read array.
                                item["properties"][prop] = array
                                await self._array(
                                    session, report, obj, prop, array, expected=expected
                                )
                                array["read_in_progress"] = False
                        item["complete"] = all(
                            row["status"] == "ok" and row.get("complete", True)
                            for row in item["properties"].values()
                        )
                        if len(_encoded(report)) > MAX_REPORT_BYTES - 128 * 1024:
                            raise ValueError(
                                "Inventory report evidence capacity reached; completed objects retained."
                            )
                    report["complete"] = (
                        all(item["complete"] for item in report["objects"])
                        and report["inventory"].get("complete", True)
                        and report["inventory"].get("next_offset") is None
                    )
                    report["status"] = "complete" if report["complete"] else "partial"
                    report["ignored_router_packets"] = session.get("ignored_router_packets", 0)
        except asyncio.CancelledError:
            changed = self.bacnet.app is not app or self.bacnet.config != config
            if not active["cancelled"] and not changed:
                raise
            report["status"] = "cancelled" if active["cancelled"] else "interface_changed"
            report["errors"].append(
                "Owned read cancelled; completed property evidence retained. No retry or device change."
            )
        except _InterfaceChanged as exc:
            report["status"] = "interface_changed"
            report["errors"].append(str(exc)[:1000])
        except TimeoutError:
            report["status"] = "timeout"
            report["errors"].append(
                "Finite operation deadline elapsed; completed property evidence retained."
            )
        except Exception as exc:
            report["status"] = "partial" if report["objects"] else "failed"
            report["errors"].append(str(exc)[:1000] or type(exc).__name__)
        finally:
            self.active = None
        if session is not None:
            report["ignored_router_packets"] = session.get("ignored_router_packets", 0)
        for item in report["objects"]:
            for row in item["properties"].values():
                if row.get("read_in_progress"):
                    row["read_in_progress"] = False
                    row["status"] = report["status"]
        report["finished_at"] = _utc()
        report["evidence_sha256"] = hashlib.sha256(_encoded(report)).hexdigest()
        self.reports[report["id"]] = copy.deepcopy(report)
        while len(self.reports) > MAX_REPORTS:
            self.reports.popitem(last=False)
        return report

    def detail(self, identifier):
        if identifier not in self.reports:
            raise ValueError(
                "Calendar/Schedule report not retained; export before restart or eviction."
            )
        return copy.deepcopy(self.reports[identifier])
