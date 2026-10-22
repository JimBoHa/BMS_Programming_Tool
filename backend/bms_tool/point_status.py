"""Explicit native point/service-state evidence, separate from writes and polling."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import secrets
from collections import OrderedDict
from typing import Annotated

from bacpypes3 import object as standard
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import ObjectIdentifier, TagList, Unsigned
from pydantic import Field, field_validator

from .device_details import DeviceDetails, DeviceDetailsRequest, _InterfaceChanged
from .models import StrictModel
from .property_evidence import PropertyEvidence, ReadBudget, _encoded, _utc

PROFILE = "native-point-status/1"
POINT_CLASSES = {
    int(cls.objectType): cls
    for cls in (
        standard.AnalogInputObject,
        standard.AnalogOutputObject,
        standard.AnalogValueObject,
        standard.BinaryInputObject,
        standard.BinaryOutputObject,
        standard.BinaryValueObject,
        standard.MultiStateInputObject,
        standard.MultiStateOutputObject,
        standard.MultiStateValueObject,
        standard.AccumulatorObject,
    )
}
SCOPE = (
    "Explicit read-only standard analog/binary/multistate input/output/value and Accumulator point "
    "inspection on one verified Device over plain direct or pinned routed IPv4. Native values, "
    "units, reliability, status flags, service state and optional priority evidence remain distinct. "
    "Sequential reads do not prove coherent state, physical health, engineering scaling, "
    "effective command ownership or field signal/actuator acceptance. No discovery, polling or writes. "
    "Unsegmented single-attempt profile; BBMD/direct serial outside this profile; physical manufacturer acceptance unverified."
)
PROPERTIES = (
    "object-name",
    "description",
    "present-value",
    "units",
    "status-flags",
    "reliability",
    "out-of-service",
)
MAX_REPORTS, MAX_BYTES = 16, 2 * 1024 * 1024


class PointStatusRequest(DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    object_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        min_length=1, max_length=16
    )
    include_commandable: bool = Field(default=False, strict=True)

    @field_validator("object_ids")
    @classmethod
    def point_ids(cls, values):
        result = []
        for value in values:
            obj = ObjectIdentifier(value)
            if int(obj[0]) not in POINT_CLASSES or not 0 <= obj[1] <= 4194302:
                raise ValueError(
                    "Select exact supported analog/binary/multistate point or Accumulator identifiers."
                )
            result.append(str(obj))
        if len(result) != len(set(result)):
            raise ValueError("Duplicate point selection.")
        return result


class PointStatusCancel(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class PointStatusExport(StrictModel):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")


def _availability(row):
    if row["status"] == "ok":
        row["availability"] = "read"
    elif row["status"] == "native_error":
        error = row.get("native_error", {})
        row["availability"] = (
            "unsupported_property"
            if error.get("errorClass", {}).get("value") == 2
            and error.get("errorCode", {}).get("value") == 32
            else "native_rejected"
        )
    else:
        row["availability"] = "unknown"
    return row


class PointStatus:
    def __init__(
        self, bacnet, store=None, *, timeout=1.0, operation_timeout=15.0, request_gap=0.02
    ):
        self.bacnet = bacnet
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
            "auto_poll": False,
            "active_operation": self.active["id"] if self.active else None,
            "limits": {
                "objects": 16,
                "reports": MAX_REPORTS,
                "report_bytes": MAX_BYTES,
                "requests": 512,
                "priority_slots": 16,
                "encoded_property_bytes": 16 * 1024,
                "property_record_bytes": 64 * 1024,
                "native_depth": 16,
                "native_items": 4096,
                "operation_seconds": self.operation_timeout,
                "request_seconds": self.timeout,
            },
            "reports": [
                {
                    k: r[k]
                    for k in (
                        "id",
                        "target",
                        "started_at",
                        "finished_at",
                        "status",
                        "evidence_sha256",
                    )
                }
                for r in self.reports.values()
            ],
        }

    def cancel(self, operation_id):
        PointStatusCancel(operation_id=operation_id)
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

    def detail(self, identifier):
        if identifier not in self.reports:
            raise ValueError(
                "Point-status evidence not retained; export before restart or eviction."
            )
        return copy.deepcopy(self.reports[identifier])

    async def _read(self, session, budget, obj, prop, index=None):
        cls = (
            standard.DeviceObject
            if int(ObjectIdentifier(obj)[0]) == 8
            else POINT_CLASSES[int(ObjectIdentifier(obj)[0])]
        )
        native, row = await self.reader.read(
            session,
            budget,
            obj,
            prop,
            cls,
            index,
            timeout=self.timeout,
            request_gap=self.request_gap,
        )
        if row["status"] == "ok" and prop in ("status-flags", "out-of-service"):
            tags = list(TagList.decode(PDU(bytes.fromhex(row["encoded_value"]["hex"]))))[1:-1]
            valid = len(tags) == 1
            if prop == "status-flags":
                tag = tags[0] if tags else None
                valid = (
                    valid
                    and tag.tag_class == 0
                    and tag.tag_number == 8
                    and len(tag.tag_data) == 2
                    and tag.tag_data[0] == 4
                    and not (tag.tag_data[1] & 15)
                )
                if (
                    not valid
                    and tag is not None
                    and tag.tag_class == 0
                    and tag.tag_number == 8
                    and tag.tag_data
                    and tag.tag_data[0] <= 7
                ):
                    bit_count = (len(tag.tag_data) - 1) * 8 - tag.tag_data[0]
                    row["raw_status_flag_bit_count"] = max(0, bit_count)
                    row["raw_status_flag_bits_truncated"] = bit_count > 32
                    row["raw_status_flag_bits"] = [
                        (tag.tag_data[1 + n // 8] >> (7 - n % 8)) & 1
                        for n in range(min(32, max(0, bit_count)))
                    ]
            else:
                valid = (
                    valid
                    and tags[0].tag_class == 0
                    and tags[0].tag_number == 1
                    and tags[0].tag_lvt in (0, 1)
                )
            if not valid:
                # Native StatusFlags pads short bit strings to four fields;
                # Boolean normalizes nonzero LVT. Neither is raw evidence.
                row.pop("value", None)
                row.update(
                    status="invalid_native_value",
                    error="Native quality field encoding is not its exact standard four-bit StatusFlags or Boolean profile; original tag evidence retained without normalized value.",
                )
        return native, _availability(row)

    @staticmethod
    def _not_applicable(obj, prop):
        return {
            "object": obj,
            "property": prop,
            "status": "not_applicable",
            "availability": "outside_standard_type_profile",
            "reason": "No standard property datatype on this selected point class; proprietary behavior is not inferred.",
        }

    async def read(self, **arguments):
        options = PointStatusRequest(**arguments)
        if self.closed or self.active is not None:
            raise ValueError("Point-status inspection is closed or another read is active.")
        if options.operation_id in self.cancelled:
            raise ValueError("Operation cancelled before admission; use a new operation ID.")
        app = self.bacnet.require()
        config = copy.deepcopy(self.bacnet.config)
        if config.get("transport") == "mstp" or config.get("bbmd_address"):
            raise ValueError(
                "Point-status inspection requires plain IPv4 without BBMD or direct serial."
            )
        budget = ReadBudget(max_requests=512, max_bytes=MAX_BYTES - 128 * 1024)
        report = {
            "id": secrets.token_hex(16),
            "profile": PROFILE,
            "scope": SCOPE,
            "target": {k: getattr(options, k) for k in ("address", "device", "router", "dnet")},
            "connector_config": config,
            "operation_id": options.operation_id,
            "started_at": _utc(),
            "finished_at": None,
            "status": "reading",
            "complete": False,
            "identity_verified": False,
            "objects": [],
            "errors": [],
            "source_clock_utc": None,
            "clock_basis": "Local UTC receipt time only; no source clock was resolved.",
            "health_assessment": "Not established. Native indications and read outcomes are shown separately; a finite value is not proof of physical health or service.",
            "consistency": "Sequential property and priority-slot observations, not atomic state or command-ownership proof.",
        }
        active = {"id": options.operation_id, "task": asyncio.current_task(), "cancelled": False}
        self.active = active
        session = None
        try:
            async with asyncio.timeout(self.operation_timeout):
                async with self.path._path(options) as session:
                    if session["app"] is not app or session["config"] != config:
                        raise _InterfaceChanged(
                            "Point-status interface changed before acquisition."
                        )
                    self.reader.pin(session, options.router)
                    actual, row = await self._read(
                        session, budget, options.device, "object-identifier"
                    )
                    report["device_identity"] = row
                    if actual != ObjectIdentifier(options.device):
                        raise ValueError(
                            "Exact Device identity was not verified; no point fields read."
                        )
                    report["identity_verified"] = True
                    for obj in options.object_ids:
                        item = {
                            "object": obj,
                            "identity_verified": False,
                            "properties": {},
                            "complete": False,
                            "health_assessment": "Not established",
                        }
                        report["objects"].append(item)
                        actual, row = await self._read(session, budget, obj, "object-identifier")
                        item["properties"]["object-identifier"] = row
                        if actual != ObjectIdentifier(obj):
                            item["error"] = (
                                "Exact point identity not verified; remaining fields not read."
                            )
                            continue
                        item["identity_verified"] = True
                        cls = POINT_CLASSES[int(ObjectIdentifier(obj)[0])]
                        for prop in PROPERTIES:
                            if cls.get_property_type(prop) is None:
                                item["properties"][prop] = self._not_applicable(obj, prop)
                            else:
                                _, item["properties"][prop] = await self._read(
                                    session, budget, obj, prop
                                )
                        if options.include_commandable:
                            for prop in ("priority-array", "relinquish-default"):
                                if cls.get_property_type(prop) is None:
                                    item["properties"][prop] = self._not_applicable(obj, prop)
                                    continue
                                if prop == "relinquish-default":
                                    _, item["properties"][prop] = await self._read(
                                        session, budget, obj, prop
                                    )
                                    continue
                                array = {
                                    "status": "reading",
                                    "complete": False,
                                    "read_in_progress": True,
                                    "count_read": None,
                                    "elements": [],
                                    "meaning": "Observed slots only; no ownership or coherent effective-priority inference.",
                                }
                                item["properties"][prop] = array
                                count, row = await self._read(session, budget, obj, prop, 0)
                                array["count_read"] = row
                                if isinstance(count, Unsigned):
                                    for index in range(1, min(int(count), 16) + 1):
                                        _, row = await self._read(session, budget, obj, prop, index)
                                        array["elements"].append(row)
                                    array["complete"] = count == 16 and all(
                                        r["status"] == "ok" for r in array["elements"]
                                    )
                                    array["status"] = (
                                        "ok"
                                        if array["complete"]
                                        else "partial"
                                        if count == 16
                                        else "invalid_count"
                                    )
                                else:
                                    array["status"] = row["status"]
                                array["read_in_progress"] = False
                        item["complete"] = all(
                            r["status"] in ("ok", "not_applicable") and r.get("complete", True)
                            for r in item["properties"].values()
                        )
                    report["complete"] = all(item["complete"] for item in report["objects"])
                    report["status"] = "complete" if report["complete"] else "partial"
        except asyncio.CancelledError:
            changed = self.bacnet.app is not app or self.bacnet.config != config
            if not active["cancelled"] and not changed:
                raise
            report["status"] = "cancelled" if active["cancelled"] else "interface_changed"
            report["errors"].append(
                "Owned inspection interrupted; completed property/slot evidence retained."
            )
        except _InterfaceChanged as exc:
            report["status"] = "interface_changed"
            report["errors"].append(str(exc)[:1000])
        except TimeoutError:
            report["status"] = "timeout"
            report["errors"].append(
                "Finite operation deadline elapsed; completed evidence retained."
            )
        except Exception as exc:
            report["status"] = "partial" if report["objects"] else "failed"
            report["errors"].append(str(exc)[:1000] or type(exc).__name__)
        finally:
            self.active = None
        for item in report["objects"]:
            for row in item["properties"].values():
                if row.get("read_in_progress"):
                    row.update(read_in_progress=False, status=report["status"])
        report["read_budget"] = budget.snapshot()
        report["ignored_router_packets"] = (
            session.get("ignored_router_packets", 0) if session else 0
        )
        report["finished_at"] = _utc()
        report["evidence_sha256"] = hashlib.sha256(_encoded(report)).hexdigest()
        self.reports[report["id"]] = copy.deepcopy(report)
        while len(self.reports) > MAX_REPORTS:
            self.reports.popitem(last=False)
        return report
