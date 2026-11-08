"""Read the current JCI mapped point source without offering an unqualified write.

NAE source Instance Number (32589) is distinct from the local BACnet Object
Identifier. JCI's NAE55 PICS does not mark it writable. Native supervisory
configuration transfer has not been qualified by this application.
"""

from __future__ import annotations

import asyncio

from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned
from pydantic import Field, field_validator

from .device_details import DeviceDetailsRequest
from .property_evidence import ReadBudget

PROFILE = "metasys-source-mapping-inspection/1"
BLOCKER = (
    "Live source remapping is unavailable. JCI documents Instance Number as "
    "configuration-only and does not mark property 32589 writable in the NAE55 AI PICS. "
    "An independently verified NAE configuration-transfer adapter is required."
)
LIMITATIONS = [
    "This is a bounded observation, not an atomic configuration snapshot or a write review.",
    "The local object type does not prove the remote source object type or physical sensor.",
    "The remote address is retained as native evidence; no device or route is inferred from it.",
    "Metasys GUIDs, historian destinations, extensions and incoming links are not verified here.",
    "A field-controller CAF/MOI/File-3 transfer is not an NAE database transfer.",
]
CORE_PROPERTIES = ("object-identifier", "object-name", "32527", "32589")


class MetasysSourceMappingRequest(DeviceDetailsRequest):
    object_id: str = Field(min_length=1, max_length=80)

    @field_validator("object_id")
    @classmethod
    def mapped_point(cls, value):
        obj = ObjectIdentifier(value)
        if int(obj[0]) not in (0, 5) or not 0 <= obj[1] <= 4194302:
            raise ValueError(
                "This inspection supports explicit analog-input or binary-value points."
            )
        return str(obj)


class MetasysSourceMapping:
    def __init__(self, workspace):
        self.workspace = workspace

    async def inspect(self, **arguments):
        options = MetasysSourceMappingRequest(**arguments)
        ws = self.workspace
        report = ws._report(options, "metasys-source-mapping-inspection")
        report.update(
            profile=PROFILE,
            adapter="jci-mapped-point-read",
            object=options.object_id,
            mapping=None,
            mapping_observed=False,
            properties={},
            verification_properties={},
            vendor_checks=[],
            write_support={"available": False, "reason": BLOCKER},
            limitations=list(LIMITATIONS),
        )
        session, budget = None, ReadBudget(max_requests=24, max_bytes=256 * 1024)
        try:
            async with asyncio.timeout(ws.operation_timeout):
                async with ws.path._path(options) as session:
                    ws.reader.pin(session, options.router)
                    await ws._identity(session, budget, options, report, "before")
                    vendor, row = await ws._read(
                        session, budget, options.device, "vendor-identifier"
                    )
                    report["vendor_checks"].append(row)
                    if row["status"] != "ok" or not isinstance(vendor, Unsigned) or vendor != 5:
                        raise ValueError(
                            "A responding Johnson Controls Device (vendor 5) is required."
                        )
                    observed = {}
                    for prop in CORE_PROPERTIES + ("2564", "538"):
                        value, row = await ws._read(session, budget, options.object_id, prop)
                        report["properties"][prop] = row
                        observed[prop] = value
                        if prop == "object-identifier" and (
                            row["status"] != "ok" or value != ObjectIdentifier(options.object_id)
                        ):
                            raise ValueError("The selected mapped point identity was not verified.")
                    source = observed["32589"]
                    reference = observed["32527"]
                    if (
                        report["properties"]["32589"]["status"] != "ok"
                        or not isinstance(source, Unsigned)
                        or not 0 <= source <= 4194302
                        or report["properties"]["32527"]["status"] != "ok"
                        or not isinstance(reference, CharacterString)
                        or not str(reference).strip()
                        or report["properties"]["object-name"]["status"] != "ok"
                        or not isinstance(observed["object-name"], CharacterString)
                    ):
                        raise ValueError(
                            "A typed source instance, item reference and point name were not all read."
                        )
                    # Repeat the identity/reference/source in the same pinned path lease.
                    # Changes or a failed second read must never leave a 'verified' mapping.
                    for prop in CORE_PROPERTIES:
                        value, row = await ws._read(session, budget, options.object_id, prop)
                        report["verification_properties"][prop] = row
                        if (
                            row["status"] != "ok"
                            or type(value) is not type(observed[prop])
                            or value != observed[prop]
                        ):
                            raise ValueError(
                                "Point identity or source mapping changed during inspection; read again."
                            )
                    vendor_after, row = await ws._read(
                        session, budget, options.device, "vendor-identifier"
                    )
                    report["vendor_checks"].append(row)
                    if (
                        row["status"] != "ok"
                        or type(vendor_after) is not type(vendor)
                        or vendor_after != vendor
                    ):
                        raise ValueError("The selected Device vendor changed during inspection.")
                    await ws._identity(session, budget, options, report, "after")
                    report["mapping"] = {
                        "local_object": options.object_id,
                        "local_name": str(observed["object-name"]),
                        "item_reference": str(reference),
                        "source_instance": int(source),
                        "source_object_type": None,
                        "remote_object_name": str(observed["2564"])
                        if report["properties"]["2564"]["status"] == "ok"
                        and isinstance(observed["2564"], CharacterString)
                        else None,
                    }
                    report["identity_verified"] = report["mapping_observed"] = report[
                        "complete"
                    ] = True
        except (ValueError, TimeoutError) as exc:
            report["errors"].append(str(exc) or "Source mapping inspection timed out.")
        return ws._finish(report, budget, session)
