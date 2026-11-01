"""Explicit, source-bound standard monitoring choices on an open serial bus."""

import asyncio
import copy
import time
from typing import Literal

from bacpypes3.primitivedata import ObjectIdentifier
from bacpypes3.vendor import get_vendor_info
from pydantic import Field, model_validator

from .controller_read_context import ControllerReadContext, check_connector_context
from .device_details import DeviceDetails, _InterfaceChanged, _utc


class MonitoringChoicesRequest(ControllerReadContext):
    kind: Literal["value", "trend-log"]
    offset: int = Field(default=0, ge=0, le=100000, strict=True)
    limit: int = Field(default=16, ge=1, le=16, strict=True)

    @model_validator(mode="after")
    def explicit_serial_source(self):
        if self.controller_target is None or self.controller_target.transport != "direct-mstp":
            raise ValueError(
                "Serial monitoring choices require an explicit selected direct-MS/TP source."
            )
        return self


class ControllerMonitoringChoices:
    def __init__(self, bacnet, store):
        self.bacnet = bacnet
        self.path = DeviceDetails(bacnet, store, request_gap=0.02)

    async def read(self, request):
        options = MonitoringChoicesRequest.model_validate(request)
        check_connector_context(options, self.bacnet.config)
        target = options.controller_target
        report = {
            "profile": "selected-serial-monitoring-choices/1",
            "target": target.model_dump(),
            "connector_config": copy.deepcopy(options.expected_connector_config),
            "kind": options.kind,
            "offset": options.offset,
            "total": None,
            "next_offset": None,
            "rows": [],
            "identity_verified": False,
            "complete": False,
            "read_only": True,
            "errors": [],
            "warnings": [],
            "started_at": _utc(),
            "scope": "Observed standard object-list choices and names at an exact serial source; no physical I/O inventory, native program read or controller write.",
        }
        staged, visited = [], []
        deadline = time.monotonic() + self.path.operation_timeout - 3 * self.path.timeout - 0.2
        try:
            async with asyncio.timeout(self.path.operation_timeout):
                async with self.path._path(target) as session:
                    check_connector_context(options, session["config"])

                    async def identity(obj):
                        actual = await self.path._read(session, obj, "object-identifier")
                        if actual != ObjectIdentifier(obj):
                            raise ValueError(
                                "Selected serial monitoring identity changed; reopen the controller."
                            )

                    await identity(target.device)
                    count = await self.path._read(session, target.device, "object-list", 0)
                    if (
                        isinstance(count, bool)
                        or not isinstance(count, int)
                        or not 1 <= count <= 100000
                        or options.offset > count
                    ):
                        raise ValueError(
                            "The selected controller did not expose a bounded object-list page."
                        )
                    report["total"] = int(count)
                    for index in range(
                        options.offset + 1, min(count, options.offset + options.limit) + 1
                    ):
                        if time.monotonic() > deadline:
                            break
                        oid = await self.path._read(session, target.device, "object-list", index)
                        if (
                            not isinstance(oid, ObjectIdentifier)
                            or not 0 <= oid[1] <= 4194302
                            or str(oid) in visited
                        ):
                            raise ValueError(
                                "Invalid or duplicate object identity in the selected serial page."
                            )
                        visited.append(str(oid))
                        schema = get_vendor_info(0).get_object_class(int(oid[0]))
                        eligible = (
                            int(oid[0]) == 20
                            if options.kind == "trend-log"
                            else bool(schema and schema.get_property_type("present-value"))
                        )
                        if not eligible:
                            continue
                        obj = str(oid)
                        await identity(obj)
                        name = ""
                        try:
                            value = await self.path._read(session, obj, "object-name")
                            if not isinstance(value, str) or len(str(value).encode("utf-8")) > 4096:
                                raise ValueError("Object name exceeds the bounded text profile.")
                            name = str(value)
                        except _InterfaceChanged:
                            raise
                        except (ValueError, TimeoutError) as failure:
                            report["warnings"].append(f"{obj} name unavailable: {failure}")
                        await identity(obj)
                        staged.append({"object": obj, "name": name, "index": index})
                    after = await self.path._read(session, target.device, "object-list", 0)
                    await identity(target.device)
                    check_connector_context(options, self.bacnet.config)
                    self.path._guard(session)
                    if after != count:
                        raise ValueError("Selected serial object-list changed; reload its choices.")
                    end = options.offset + len(visited)
                    report.update(
                        rows=staged,
                        identity_verified=True,
                        next_offset=end if end < count else None,
                        complete=end == min(count, options.offset + options.limit),
                    )
                    if not report["complete"]:
                        report["warnings"].append(
                            "The page deadline ended early; read the next page explicitly."
                        )
        except (ValueError, TimeoutError) as failure:
            report["errors"].append(str(failure) or "Serial monitoring choices timed out.")
        report["finished_at"] = _utc()
        return report
