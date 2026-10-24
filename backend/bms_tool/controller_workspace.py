"""Model-independent, source-pinned BACnet controller workspace reads.

Object schemas select the decoder; controller model names never select point
inventories or substitute an application. Vendor application readers can report
their own capabilities through the registry without changing this common path.
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Protocol

from bacpypes3.object import Object
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import ObjectIdentifier, PropertyIdentifier, TagClass, TagList
from bacpypes3.vendor import get_vendor_info
from pydantic import Field, field_validator

from .device_details import DeviceDetails, DeviceDetailsRequest
from .property_evidence import PropertyEvidence, ReadBudget, _encoded, _utc, native_value


class ControllerInventoryRequest(DeviceDetailsRequest):
    offset: int = Field(default=0, ge=0, le=100000, strict=True)
    limit: int = Field(default=64, ge=1, le=128, strict=True)


class ControllerPropertiesRequest(DeviceDetailsRequest):
    object_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        min_length=1, max_length=16
    )
    properties: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=lambda: [
            "object-name",
            "description",
            "present-value",
            "units",
            "status-flags",
            "reliability",
            "out-of-service",
        ],
        min_length=1,
        max_length=16,
    )

    @field_validator("object_ids")
    @classmethod
    def identifiers(cls, values):
        result = [str(ObjectIdentifier(value)) for value in values]
        if len(set(result)) != len(result) or any(
            not 0 <= ObjectIdentifier(value)[1] <= 4194302 for value in result
        ):
            raise ValueError("Use distinct, actual object identifiers.")
        return result

    @field_validator("properties")
    @classmethod
    def property_ids(cls, values):
        result = [str(PropertyIdentifier(value)) for value in values]
        if len(set(result)) != len(result):
            raise ValueError("Duplicate property selection.")
        return result


class NativeApplicationReader(Protocol):
    id: str

    def capabilities(self, profile: dict) -> dict | None:
        """Return supported native operations, or None when not applicable."""

    async def read_application(self, target: dict, profile: dict) -> dict:
        """Read an actual native application with source and format evidence."""


class ControllerWorkspace:
    def __init__(self, bacnet, store, *, native_readers=(), timeout=0.8, operation_timeout=15):
        self.bacnet, self.store = bacnet, store
        self.path = DeviceDetails(
            bacnet, store, timeout=timeout, operation_timeout=operation_timeout, request_gap=0.02
        )
        self.reader = PropertyEvidence(self.path)
        self.native_readers: tuple[NativeApplicationReader, ...] = tuple(native_readers)
        self.timeout, self.operation_timeout = timeout, operation_timeout

    def _report(self, options, operation):
        return {
            "profile": "bacnet-controller-workspace/1",
            "operation": operation,
            "adapter": "bacnet-standard",
            "read_only": True,
            "target": {
                key: getattr(options, key) for key in ("address", "device", "router", "dnet")
            },
            "identity_verified": False,
            "complete": False,
            "errors": [],
            "started_at": _utc(),
            "finished_at": None,
        }

    async def _read(self, session, budget, obj, prop, index=None):
        schema = (
            get_vendor_info(session.get("vendor_identifier", 0)).get_object_class(
                int(ObjectIdentifier(obj)[0])
            )
            or Object
        )
        native, row = await self.reader.read(
            session, budget, obj, prop, schema, index, timeout=self.timeout, request_gap=0.02
        )
        if row["status"] == "ok" and prop in ("status-flags", "out-of-service"):
            tags = list(TagList.decode(PDU(bytes.fromhex(row["encoded_value"]["hex"]))))[1:-1]
            valid = len(tags) == 1 and tags[0].tag_class == TagClass.application
            if prop == "status-flags":
                valid = (
                    valid
                    and tags[0].tag_number == 8
                    and len(tags[0].tag_data) == 2
                    and tags[0].tag_data[0] == 4
                    and not (tags[0].tag_data[1] & 15)
                )
            else:
                valid = valid and tags[0].tag_number == 1 and tags[0].tag_lvt in (0, 1)
            if not valid:
                native = None
                row.pop("value", None)
                row.update(
                    status="invalid_native_value",
                    error="Native quality encoding is not exact four-bit StatusFlags or Boolean. Original evidence retained.",
                )
        if (
            prop == "vendor-identifier"
            and row["status"] == "ok"
            and isinstance(native, int)
            and 0 <= native <= 65535
        ):
            session["vendor_identifier"] = int(native)
        if row.get("error", "").startswith("No standard native datatype") and row.get(
            "encoded_value", {}
        ).get("complete"):
            try:
                tags = list(TagList.decode(PDU(bytes.fromhex(row["encoded_value"]["hex"]))))
                if (
                    len(tags) == 3
                    and tags[0].tag_class == TagClass.opening
                    and tags[-1].tag_class == TagClass.closing
                ):
                    tags = tags[1:-1]
                if len(tags) == 1 and tags[0].tag_class == TagClass.application:
                    value = tags[0].app_to_object()
                    candidate = {
                        **row,
                        "status": "ok",
                        "value": native_value(value, []),
                        "datatype": type(value).__name__,
                        "decoding": "primitive wire tag; property semantics unavailable",
                    }
                    candidate.pop("error", None)
                    growth = max(0, len(_encoded(candidate)) - len(_encoded(row)))
                    if (
                        len(_encoded(candidate)) <= 64 * 1024
                        and budget.retained_bytes + growth <= budget.max_bytes
                    ):
                        budget.retained_bytes += growth
                        native, row = value, candidate
            except (ValueError, TypeError, AttributeError):
                pass
        return native, row

    async def _identity(self, session, budget, options):
        value, row = await self._read(session, budget, options.device, "object-identifier")
        if value != ObjectIdentifier(options.device):
            raise ValueError(
                "Selected Device identity was not verified; repeat controller discovery."
            )
        return row

    def _finish(self, report, budget, session):
        report["finished_at"] = _utc()
        report["read_budget"] = budget.snapshot()
        if session:
            report["connector_config"] = session["config"]
            report["ignored_router_packets"] = session.get("ignored_router_packets", 0)
        return report

    async def profile(self, **arguments):
        options = DeviceDetailsRequest(**arguments)
        report = self._report(options, "capabilities")
        report["properties"] = {}
        session, budget = None, ReadBudget(max_requests=32, max_bytes=256 * 1024)
        try:
            async with asyncio.timeout(self.operation_timeout):
                async with self.path._path(options) as session:
                    self.reader.pin(session, options.router)
                    await self._identity(session, budget, options)
                    for prop in (
                        "object-name",
                        "vendor-identifier",
                        "vendor-name",
                        "model-name",
                        "firmware-revision",
                        "application-software-version",
                        "protocol-revision",
                        "protocol-services-supported",
                        "protocol-object-types-supported",
                        "object-list",
                    ):
                        _, row = await self._read(
                            session,
                            budget,
                            options.device,
                            prop,
                            0 if prop == "object-list" else None,
                        )
                        report["properties"][prop] = row
                    await self._identity(session, budget, options)
                    report["identity_verified"] = report["complete"] = True
        except (ValueError, TimeoutError) as exc:
            report["errors"].append(str(exc) or "Controller capability read timed out.")
        report["native_application_readers"] = [
            {"id": reader.id, **capability}
            for reader in self.native_readers
            if report["identity_verified"]
            and (capability := reader.capabilities(report)) is not None
        ]
        report["native_logic"] = {
            "available": any(
                item.get("logic_read") for item in report["native_application_readers"]
            ),
            "basis": "Native application support is reported by installed protocol/format adapters. BACnet object metadata is not an editable control program.",
        }
        return self._finish(report, budget, session)

    async def inventory(self, **arguments):
        options = ControllerInventoryRequest(**arguments)
        report = self._report(options, "object-inventory")
        report.update(objects=[], total=None, offset=options.offset, next_offset=None)
        session, budget = None, ReadBudget(max_requests=140, max_bytes=256 * 1024)
        deadline = time.monotonic() + self.operation_timeout - 3 * self.timeout - 0.2
        try:
            async with asyncio.timeout(self.operation_timeout):
                async with self.path._path(options) as session:
                    self.reader.pin(session, options.router)
                    await self._identity(session, budget, options)
                    await self._read(session, budget, options.device, "vendor-identifier")
                    count, evidence = await self._read(
                        session, budget, options.device, "object-list", 0
                    )
                    if (
                        evidence["status"] != "ok"
                        or not isinstance(count, int)
                        or not 1 <= count <= 100000
                    ):
                        raise ValueError(
                            "The controller did not expose a bounded object-list count."
                        )
                    report["total"] = int(count)
                    if options.offset > count:
                        raise ValueError("Object-list offset exceeds the current inventory.")
                    for index in range(
                        options.offset + 1, min(count, options.offset + options.limit) + 1
                    ):
                        if time.monotonic() > deadline:
                            break
                        obj, row = await self._read(
                            session, budget, options.device, "object-list", index
                        )
                        if (
                            row["status"] != "ok"
                            or not isinstance(obj, ObjectIdentifier)
                            or not 0 <= obj[1] <= 4194302
                        ):
                            raise ValueError(
                                "Object-list contains an unreadable or invalid object identifier."
                            )
                        schema = get_vendor_info(
                            session.get("vendor_identifier", 0)
                        ).get_object_class(int(obj[0]))
                        report["objects"].append(
                            {
                                "object": str(obj),
                                "index": index,
                                "object_type": int(obj[0]),
                                "type_name": str(obj[0]),
                                "standard_schema": schema.__name__ if schema else None,
                                "has_present_value": bool(
                                    schema and schema.get_property_type("present-value")
                                ),
                                "structured_group": int(obj[0]) in (11, 29),
                            }
                        )
                    after, _ = await self._read(session, budget, options.device, "object-list", 0)
                    await self._identity(session, budget, options)
                    if after != count:
                        raise ValueError("Controller object inventory changed; reload it.")
                    identifiers = [row["object"] for row in report["objects"]]
                    if len(set(identifiers)) != len(identifiers):
                        raise ValueError("Duplicate object identities in the inventory page.")
                    report["identity_verified"] = True
                    end = options.offset + len(identifiers)
                    report["next_offset"] = end if end < count else None
                    report["complete"] = end == min(count, options.offset + options.limit)
        except (ValueError, TimeoutError) as exc:
            report["errors"].append(str(exc) or "Controller inventory read timed out.")
        return self._finish(report, budget, session)

    async def properties(self, **arguments):
        options = ControllerPropertiesRequest(**arguments)
        report = self._report(options, "object-properties")
        report["objects"] = []
        session, budget = None, ReadBudget(max_requests=290, max_bytes=512 * 1024)
        deadline = time.monotonic() + self.operation_timeout - 2 * self.timeout - 0.1
        try:
            async with asyncio.timeout(self.operation_timeout):
                async with self.path._path(options) as session:
                    self.reader.pin(session, options.router)
                    await self._identity(session, budget, options)
                    await self._read(session, budget, options.device, "vendor-identifier")
                    for obj in options.object_ids:
                        if time.monotonic() > deadline:
                            break
                        actual, evidence = await self._read(
                            session, budget, obj, "object-identifier"
                        )
                        item = {
                            "object": obj,
                            "identity_verified": actual == ObjectIdentifier(obj),
                            "properties": {"object-identifier": evidence},
                        }
                        report["objects"].append(item)
                        if not item["identity_verified"]:
                            continue
                        for prop in options.properties:
                            if time.monotonic() > deadline:
                                break
                            _, row = await self._read(session, budget, obj, prop)
                            item["properties"][prop] = row
                    await self._identity(session, budget, options)
                    report["identity_verified"] = True
                    report["complete"] = len(report["objects"]) == len(options.object_ids) and all(
                        item["identity_verified"]
                        and all(prop in item["properties"] for prop in options.properties)
                        for item in report["objects"]
                    )
        except (ValueError, TimeoutError) as exc:
            report["errors"].append(str(exc) or "Controller property read timed out.")
        return self._finish(report, budget, session)
