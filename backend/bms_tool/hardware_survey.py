"""Bounded, read-only BACnet hardware survey and offline JCI MOI evidence.

Configured models and exposed assignments are engineering evidence, never proof
of installed labels, physically unused wiring, or authorization to alter a point.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import io
import re
import zipfile
import zlib
from datetime import UTC, datetime

from bacpypes3.apdu import (
    ErrorRejectAbortNack,
    ReadPropertyACK,
    ReadPropertyMultipleACK,
    ReadPropertyMultipleRequest,
    ReadPropertyRequest,
)
from bacpypes3.basetypes import (
    BinaryPV,
    EngineeringUnits,
    PropertyReference,
    ReadAccessSpecification,
    Reliability,
    StatusFlags,
)
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    Null,
    ObjectIdentifier,
    PropertyIdentifier,
    Real,
    Tag,
    TagClass,
    TagList,
    TagNumber,
    Unsigned,
)
from pydantic import Field

from .bacnet_exchange import confirmed_exchange
from .bacnet_values import json_value
from .device_details import DeviceDetails
from .hardware_target import HardwareTargetRequest, serial_identity

PROFILE = "bacnet-hardware-survey/1"
ARCHIVE_PROFILE = "jci-moi-hardware-evidence/1"
BOUNDARY = (
    "Assignments are observed configuration, not a physical wiring inspection. "
    "Missing BACnet objects do not prove unused terminals. Native archive models are "
    "configured hardware and may differ from installed hardware. Candidate spare "
    "inputs require native point-assignment and physical wiring verification."
)
MAX_SOURCE = 2 * 1024 * 1024
MAX_EXPANDED = 8 * 1024 * 1024
MAX_RECORDS = 8192
MODEL_SOURCE = (
    "https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/"
    "PCX-Input/Output-Expansion-Modules-Catalog-Page/PCX-Series-point-type-counts-per-model"
)
PCG_SOURCE = (
    "https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/"
    "FX-PCG26-General-Purpose-Programmable-Controller-Installation-Guide/G/"
    "Terminal-wiring-guidelines-functions-ratings-and-requirements/"
    "Input/Output-Terminal-Blocks-ratings-and-requirements"
)
PICS_SOURCE = (
    "https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/"
    "FX-PC-Series-Controllers-Protocol-Implementation-Conformance-Statement"
)


def _utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


class HardwareSurveyRequest(HardwareTargetRequest):
    max_objects: int = Field(default=512, ge=1, le=4096, strict=True)
    max_inputs: int = Field(default=256, ge=1, le=1024, strict=True)
    timeout_seconds: float = Field(default=45, ge=0.1, le=180, allow_inf_nan=False)
    property_timeout: float = Field(default=1.5, ge=0.05, le=1.5, allow_inf_nan=False)


def model_capacity(model):
    """Only exact, documented models; no extrapolation from used slot numbers."""
    if not isinstance(model, str):
        return None
    name = model.upper().strip()
    if name == "FX-PCG2611-0":
        return {
            "universal_inputs": [1, 2, 3, 4, 5, 6],
            "binary_inputs": [7, 8],
            "voltage_input_range": "0–10 VDC",
            "source": PCG_SOURCE,
        }
    if name in {"FX-PCX3711-0", "FX-PCX3711"}:
        return {
            "universal_inputs": [1, 2, 3, 4],
            "binary_inputs": [],
            "voltage_input_range": "0–10 VDC",
            "source": MODEL_SOURCE,
        }
    if name in {"FX-PCX3721-0", "FX-PCX3721"}:
        return {
            "universal_inputs": [],
            "binary_inputs": list(range(1, 17)),
            "voltage_input_range": None,
            "source": MODEL_SOURCE,
        }
    return None


def _terminal(device_type, slot=None):
    match = re.fullmatch(r"\s*(UI|BI|CI)\s+IN\s*([0-9]{1,3})\s*", str(device_type or ""), re.I)
    if not match:
        return None, slot if type(slot) is int and 1 <= slot <= 255 else None
    number = int(match[2])
    if not 1 <= number <= 255:
        return None, None
    if slot is not None and slot != number:
        return None, None
    return match[1].upper(), number


def _host_key(point):
    host = point.get("host") or {}
    if host.get("kind") == "sa" and type(host.get("sa_mac")) is int:
        return ("sa", host["sa_mac"])
    if host.get("kind") in {"local", "local-inferred", "local-configured"}:
        return ("local", None)
    return None


def occupancy(report):
    """Return known hardware capacities and conservative candidate spare inputs."""
    modules = copy.deepcopy(report.get("modules", []))
    base_model = report.get("identity", {}).get("model")
    base_capacity = model_capacity(base_model)
    if base_capacity and not any(m.get("host") == "local" for m in modules):
        modules.insert(
            0,
            {
                "host": "local",
                "sa_mac": None,
                "configured_model": base_model,
                "capacity": base_capacity,
                "model_evidence": "Device model-name",
            },
        )
    points = report.get("inputs", [])
    inventory_complete = bool(report.get("inventory", {}).get("complete"))
    candidate_ok = (
        inventory_complete
        and (report.get("inputs_complete") is True or report.get("profile") == ARCHIVE_PROFILE)
        and not report.get("archive_comparison", {}).get("conflicts")
        and not report.get("archive_comparison", {}).get("unresolved")
    )
    object_ids = [p.get("object") for p in points]
    assignments = [
        (_host_key(p), p.get("slot"))
        for p in points
        if _host_key(p) is not None and p.get("slot") is not None
    ]
    ambiguous = len(object_ids) != len(set(object_ids)) or len(assignments) != len(set(assignments))
    candidates = []
    for module in modules:
        key = ("local", None) if module.get("host") == "local" else ("sa", module.get("sa_mac"))
        capacity = model_capacity(module.get("configured_model"))
        module["capacity"] = capacity
        assigned = [p for p in points if _host_key(p) == key]
        module["assigned_inputs"] = [p.get("object") for p in assigned]
        used = {p["slot"] for p in assigned if type(p.get("slot")) is int}
        uncertain = ambiguous or any(
            _host_key(p) is None
            or p.get("slot") is None
            or p.get("terminal_type") not in {"UI", "BI"}
            for p in points
        )
        if capacity is not None:
            uncertain = uncertain or any(
                p.get("slot")
                not in capacity[
                    "universal_inputs" if p.get("terminal_type") == "UI" else "binary_inputs"
                ]
                for p in assigned
            )
        module["occupied_slots"] = sorted(used)
        module["candidate_inputs"] = []
        if capacity is None:
            module["capacity_status"] = "unknown-model"
            continue
        module["capacity_status"] = "documented-configured-model"
        for kind, slots in [
            ("UI", capacity["universal_inputs"]),
            ("BI", capacity["binary_inputs"]),
        ]:
            for slot in slots:
                if slot in used:
                    continue
                item = {
                    "host": module.get("host", "sa"),
                    "sa_mac": module.get("sa_mac"),
                    "slot": slot,
                    "terminal": f"IN{slot}",
                    "terminal_type": kind,
                    "voltage_capable": kind == "UI",
                    "configured_model": module.get("configured_model"),
                    "status": "candidate" if candidate_ok and not uncertain else "unverified",
                    "reason": (
                        "No observed assignment; verify native configuration and wiring."
                        if candidate_ok and not uncertain
                        else "Inventory or host/slot evidence is incomplete; availability is unverified."
                    ),
                }
                module["candidate_inputs"].append(item)
                candidates.append(item)
    return {"modules": modules, "candidates": candidates, "boundary": BOUNDARY}


class HardwareSurvey:
    def __init__(self, bacnet, store):
        self.bacnet, self.store = bacnet, store

    async def _pace(self, details, session):
        details._guard(session)
        gap = details.request_gap - (asyncio.get_running_loop().time() - session["last_request"])
        if gap > 0:
            await asyncio.sleep(gap)
        details._guard(session)
        session["last_request"] = asyncio.get_running_loop().time()

    def _decode(self, prop, index, datatype, value):
        encoded = bytes(value.tagList.encode().pduData)
        result = {
            "property": str(PropertyIdentifier(prop)),
            "property_id": int(PropertyIdentifier(prop)),
            "index": index,
            "declared_type": datatype.__name__,
        }
        if len(encoded) > 4096:
            return {**result, "error": "Property exceeds 4096-byte field limit."}
        try:
            raw = value.cast_out(datatype)
            converted = str(raw) if isinstance(raw, ObjectIdentifier) else json_value(raw)
            if isinstance(converted, str) and len(converted.encode("utf-8")) > 4096:
                raise ValueError("Text exceeds field limit.")
            return {**result, "value": converted}
        except Exception as exc:
            return {
                **result,
                "error": "Declared-type mismatch: " + str(exc)[:240],
                "encoded_hex": encoded.hex(),
                "encoded_sha256": hashlib.sha256(encoded).hexdigest(),
            }

    async def _single(self, details, session, obj, field):
        prop, index, datatype = field
        request = ReadPropertyRequest(
            objectIdentifier=ObjectIdentifier(obj),
            propertyIdentifier=PropertyIdentifier(prop),
            destination=session["target"],
        )
        if index is not None:
            request.propertyArrayIndex = index
        await self._pace(details, session)
        try:
            ack = await asyncio.wait_for(
                confirmed_exchange(session["app"], request), details.timeout
            )
        except (ErrorRejectAbortNack, TimeoutError) as exc:
            return {
                "property": str(PropertyIdentifier(prop)),
                "property_id": int(PropertyIdentifier(prop)),
                "index": index,
                "error": str(exc)[:240] or "Property read timed out.",
            }
        details._guard(session)
        if (
            not isinstance(ack, ReadPropertyACK)
            or ack.pduSource != session["target"]
            or ack.apduInvokeID != request.apduInvokeID
            or ack.objectIdentifier != ObjectIdentifier(obj)
            or ack.propertyIdentifier != PropertyIdentifier(prop)
            or ack.propertyArrayIndex != index
        ):
            raise ValueError("ReadProperty response identity mismatch.")
        return self._decode(prop, index, datatype, ack.propertyValue)

    async def _many(self, details, session, obj, fields):
        if not 1 <= len(fields) <= 20:
            raise ValueError("Survey reads require 1 through 20 explicit properties.")
        keys = [(int(PropertyIdentifier(p)), i) for p, i, _ in fields]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate property/index requests are not permitted.")
        refs = []
        for prop, index, _ in fields:
            ref = PropertyReference(propertyIdentifier=PropertyIdentifier(prop))
            if index is not None:
                ref.propertyArrayIndex = index
            refs.append(ref)
        request = ReadPropertyMultipleRequest(
            listOfReadAccessSpecs=[
                ReadAccessSpecification(
                    objectIdentifier=ObjectIdentifier(obj), listOfPropertyReferences=refs
                )
            ],
            destination=session["target"],
        )
        await self._pace(details, session)
        try:
            ack = await asyncio.wait_for(
                confirmed_exchange(session["app"], request), details.timeout
            )
        except (ErrorRejectAbortNack, TimeoutError) as exc:
            # Only selected exact reads; no wildcard or network discovery fallback.
            result = []
            for field in fields:
                row = await self._single(details, session, obj, field)
                row["rpm_fallback_reason"] = str(exc)[:240] or "RPM timed out."
                result.append(row)
            return result
        details._guard(session)
        if (
            not isinstance(ack, ReadPropertyMultipleACK)
            or ack.pduSource != session["target"]
            or ack.apduInvokeID != request.apduInvokeID
            or len(ack.listOfReadAccessResults) != 1
        ):
            raise ValueError("ReadPropertyMultiple response source/invoke/object count mismatch.")
        access = ack.listOfReadAccessResults[0]
        if access.objectIdentifier != ObjectIdentifier(obj):
            raise ValueError("ReadPropertyMultiple object identity mismatch.")
        found = [
            (
                int(r.propertyIdentifier),
                int(r.propertyArrayIndex) if r.propertyArrayIndex is not None else None,
            )
            for r in access.listOfResults
        ]
        if len(found) != len(set(found)) or set(found) != set(keys):
            raise ValueError("ReadPropertyMultiple property/index identity mismatch.")
        lookup = dict(zip(found, access.listOfResults, strict=True))
        result = []
        for prop, index, datatype in fields:
            value = lookup[(int(PropertyIdentifier(prop)), index)].readResult
            if value.propertyAccessError is not None:
                error = value.propertyAccessError
                result.append(
                    {
                        "property": str(PropertyIdentifier(prop)),
                        "property_id": int(PropertyIdentifier(prop)),
                        "index": index,
                        "error": f"{error.errorClass}/{error.errorCode}",
                    }
                )
            elif value.propertyValue is not None:
                result.append(self._decode(prop, index, datatype, value.propertyValue))
            else:
                raise ValueError("ReadPropertyMultiple result lacks value and error.")
        return result

    async def survey(self, request, progress=None, *, expected_config=None):
        options = (
            request
            if isinstance(request, HardwareSurveyRequest)
            else HardwareSurveyRequest.model_validate(request)
        )
        details = DeviceDetails(self.bacnet, self.store, timeout=options.property_timeout)
        result = {
            "profile": PROFILE,
            "target": {
                k: getattr(options, k) for k in ("transport", "address", "device", "router", "dnet")
            },
            "connector_config": None,
            "identity": {},
            "read_only": True,
            "controller_writes": False,
            "status": "partial",
            "started_at": _utc(),
            "inventory": {"total": None, "read": 0, "complete": False, "objects": []},
            "inputs": [],
            "modules": [],
            "candidates": [],
            "errors": [],
            "boundary": BOUNDARY,
            "limits": options.model_dump(
                exclude={"transport", "address", "device", "router", "dnet"}
            ),
        }

        async def publish():
            result.update(occupancy(result))
            if progress:
                response = progress(copy.deepcopy(result))
                if inspect.isawaitable(response):
                    await response

        try:
            async with asyncio.timeout(options.timeout_seconds):
                async with details._path(options) as session:
                    if expected_config is not None and session["config"] != expected_config:
                        raise ValueError(
                            "Hardware job interface changed before its first read; start a new job explicitly."
                        )
                    result["connector_config"] = copy.deepcopy(session["config"])
                    fields = [
                        ("object-identifier", None, ObjectIdentifier),
                        ("object-name", None, CharacterString),
                        ("description", None, CharacterString),
                        ("model-name", None, CharacterString),
                        ("vendor-identifier", None, Unsigned),
                        ("firmware-revision", None, CharacterString),
                        ("application-software-version", None, CharacterString),
                        ("object-list", 0, Unsigned),
                    ]
                    rows = await self._many(details, session, options.device, fields)
                    result["identity_properties"] = rows
                    by_id = {row["property_id"]: row for row in rows}
                    if by_id[75].get("value") != options.device:
                        raise ValueError(
                            "Explicit Device identity could not be verified; survey stopped."
                        )
                    for prop, key in [
                        (75, "object"),
                        (77, "name"),
                        (28, "description"),
                        (70, "model"),
                        (120, "vendor_id"),
                        (44, "firmware"),
                        (12, "application_version"),
                    ]:
                        result["identity"][key] = by_id[prop].get("value")
                    count = by_id[76].get("value")
                    if type(count) is not int or not 1 <= count <= 100000:
                        raise ValueError(
                            "Device Object_List count is absent or outside bounded profile."
                        )
                    result["inventory"]["total"] = count
                    await publish()
                    maximum = min(count, options.max_objects)
                    for offset in range(1, maximum + 1, 20):
                        rows = await self._many(
                            details,
                            session,
                            options.device,
                            [
                                ("object-list", index, ObjectIdentifier)
                                for index in range(offset, min(maximum + 1, offset + 20))
                            ],
                        )
                        for row in rows:
                            if "value" not in row:
                                result["errors"].append({"stage": "inventory", **row})
                            else:
                                result["inventory"]["objects"].append(row["value"])
                        result["inventory"]["read"] = len(result["inventory"]["objects"])
                        await publish()
                    objects = result["inventory"]["objects"]
                    final_count = (
                        await self._many(
                            details, session, options.device, [("object-list", 0, Unsigned)]
                        )
                    )[0].get("value")
                    result["inventory"]["complete"] = (
                        len(objects) == count
                        and len(set(objects)) == count
                        and final_count == count
                        and options.device in objects
                    )
                    if not result["inventory"]["complete"]:
                        result["errors"].append(
                            {
                                "stage": "inventory",
                                "error": "Object_List is partial, duplicated, changed, or missing the Device.",
                            }
                        )
                    input_objects = [
                        obj
                        for obj in objects
                        if obj.startswith(("analog-input,", "binary-input,", "multi-state-input,"))
                    ]
                    result["input_total"] = len(input_objects)
                    for obj in input_objects[: options.max_inputs]:
                        analog = obj.startswith("analog-input,")
                        binary = obj.startswith("binary-input,")
                        fields = [
                            (p, None, CharacterString)
                            for p in ("object-name", "description", "device-type")
                        ]
                        fields.extend(
                            [
                                (
                                    "present-value",
                                    None,
                                    Real if analog else BinaryPV if binary else Unsigned,
                                ),
                                ("reliability", None, Reliability),
                                ("status-flags", None, StatusFlags),
                                ("out-of-service", None, Boolean),
                            ]
                        )
                        if analog:
                            fields.append(("units", None, EngineeringUnits))
                        jci = result["identity"].get("vendor_id") == 5
                        if jci:
                            fields.extend(
                                [
                                    (519, None, Unsigned),
                                    (3645, None, Unsigned),
                                    (518, None, Enumerated if analog else Unsigned),
                                ]
                            )
                        point = {
                            "object": obj,
                            "errors": [],
                            "properties": [],
                            "host": {"kind": "unknown"},
                            "sa_mac": None,
                            "slot": None,
                            "terminal_type": None,
                        }
                        result["inputs"].append(point)
                        rows = await self._many(details, session, obj, fields)
                        point["properties"] = rows
                        mapped = {r["property_id"]: r for r in rows}
                        for prop, key in [
                            (77, "name"),
                            (28, "description"),
                            (31, "device_type"),
                            (85, "present_value"),
                            (103, "reliability"),
                            (111, "status_flags"),
                            (81, "out_of_service"),
                            (117, "units"),
                            (519, "slot"),
                            (518, "setup_raw"),
                        ]:
                            if prop in mapped:
                                point[key] = mapped[prop].get("value")
                        point["terminal_type"], point["slot"] = _terminal(
                            point.get("device_type"), point.get("slot")
                        )
                        sab = mapped.get(3645, {})
                        if type(sab.get("value")) is int and 1 <= sab["value"] <= 254:
                            point["sa_mac"] = sab["value"]
                            point["host"] = {
                                "kind": "sa",
                                "sa_mac": sab["value"],
                                "evidence": "JCI SA Bus MAC Address property 3645",
                            }
                        elif jci and sab.get("encoded_hex") in {"4e004f", "00"}:
                            point["host"] = {
                                "kind": "local-inferred",
                                "sa_mac": None,
                                "evidence": "Observed unassigned/null SA host plus terminal metadata; confirm native assignment.",
                                "encoded_sa_mac": sab["encoded_hex"],
                            }
                        point["errors"] = [
                            {k: v for k, v in row.items() if k != "value"}
                            for row in rows
                            if "error" in row
                        ]
                        await publish()
                    result["inputs_complete"] = len(result["inputs"]) == len(input_objects)
                    if not result["inputs_complete"]:
                        result["errors"].append(
                            {"stage": "inputs", "error": "Input read limit reached."}
                        )
                    result["status"] = (
                        "complete"
                        if result["inventory"]["complete"] and result["inputs_complete"]
                        else "partial"
                    )
        except asyncio.CancelledError:
            result["status"] = "cancelled"
            result["finished_at"] = _utc()
            await publish()
            raise
        except TimeoutError:
            result["errors"].append(
                {
                    "stage": "survey",
                    "error": "Survey operation time limit reached; partial evidence retained.",
                }
            )
        except Exception as exc:
            result["errors"].append(
                {"stage": "survey", "error": str(exc)[:500] or type(exc).__name__}
            )
            if not result["identity"]:
                result["status"] = "error"
        result["finished_at"] = _utc()
        await publish()
        return result

    @staticmethod
    def analyze_archive(data, filename="Archive.moi"):
        return analyze_archive(data, filename)

    @staticmethod
    def enrich_report(report, evidence):
        return enrich_report(report, evidence)


async def read_fields(details, session, obj, fields):
    """Public, bounded exact read primitive for a caller-owned pinned session."""
    service = HardwareSurvey(details.bacnet, details.store)
    return await service._many(details, session, obj, fields)


def validate_report(report):
    """Validate imported survey structure and discard imported derived claims.

    A JSON import remains user-supplied evidence; validation is not a fresh
    online identity check or proof that physical terminals are unused.
    """
    if not isinstance(report, dict) or report.get("profile") != PROFILE:
        raise ValueError("Expected a hardware-survey JSON report.")
    for key in ("errors", "warnings"):
        if key in report and (not isinstance(report[key], list) or len(report[key]) > 4096):
            raise ValueError("Hardware report errors and warnings must be bounded lists.")
    for key in ("archive_comparison", "archive_evidence"):
        if key in report and not isinstance(report[key], dict):
            raise ValueError("Hardware archive comparison and evidence must be objects.")
    comparison = report.get("archive_comparison", {})
    for key in ("conflicts", "unresolved", "matched", "archive_only_inputs"):
        if key in comparison and (
            not isinstance(comparison[key], list) or len(comparison[key]) > 4096
        ):
            raise ValueError("Hardware archive comparison entries must be bounded lists.")
    archive = report.get("archive_evidence", {})
    native_inputs = archive.get("inputs", [])
    if (
        not isinstance(native_inputs, list)
        or len(native_inputs) > 1024
        or any(
            not isinstance(point, dict) or not isinstance(point.get("host", {}), dict)
            for point in native_inputs
        )
    ):
        raise ValueError("Native archive input evidence must be a bounded object list.")
    target = report.get("target")
    if not isinstance(target, dict):
        raise ValueError("Hardware survey requires an explicit target.")
    options = HardwareTargetRequest.model_validate(target)
    if options.transport == "direct-mstp":
        serial_identity(report.get("connector_config"), options)
    identity = report.get("identity")
    if not isinstance(identity, dict) or identity.get("object") != options.device:
        raise ValueError("Verified survey identity must match the target Device.")
    for key in ("name", "model", "description", "firmware", "application_version"):
        if identity.get(key) is not None and (
            not isinstance(identity[key], str) or len(identity[key].encode("utf-8")) > 4096
        ):
            raise ValueError("Hardware controller identity text is invalid.")
    inventory = report.get("inventory")
    if not isinstance(inventory, dict) or type(inventory.get("complete")) is not bool:
        raise ValueError("Hardware inventory requires an explicit completeness flag.")
    objects = inventory.get("objects", [])
    if not isinstance(objects, list) or len(objects) > 4096:
        raise ValueError("Hardware Object_List exceeds its bounded profile.")
    for obj in objects:
        if not isinstance(obj, str) or str(ObjectIdentifier(obj)) != obj:
            raise ValueError("Hardware Object_List has an invalid object identity.")
    if len(set(objects)) != len(objects):
        raise ValueError("Hardware Object_List has duplicate object identities.")
    if inventory["complete"]:
        if (
            type(inventory.get("total")) is not int
            or inventory["total"] != len(objects)
            or identity["object"] not in objects
        ):
            raise ValueError(
                "Complete inventory requires every unique advertised object including the Device."
            )
    inputs = report.get("inputs")
    modules = report.get("modules", [])
    if not isinstance(inputs, list) or len(inputs) > 1024:
        raise ValueError("Hardware input count exceeds its bounded profile.")
    if not isinstance(modules, list) or len(modules) > 256:
        raise ValueError("Hardware module count exceeds its bounded profile.")
    seen, assignments, module_hosts = set(), set(), set()
    for module in modules:
        if not isinstance(module, dict) or module.get("host") not in {"local", "sa"}:
            raise ValueError("Hardware module requires an explicit local or SA host.")
        mac = module.get("sa_mac")
        if module["host"] == "sa" and (type(mac) is not int or not 1 <= mac <= 254):
            raise ValueError("Hardware module requires a valid explicit SA MAC address.")
        if module["host"] == "local" and mac is not None:
            raise ValueError("Local module cannot claim an SA MAC address.")
        key = (module["host"], mac)
        if key in module_hosts:
            raise ValueError("Hardware module hosts are duplicated.")
        module_hosts.add(key)
        model = module.get("configured_model")
        if model is not None and (not isinstance(model, str) or len(model) > 240):
            raise ValueError("Hardware model name exceeds its bounded profile.")
        if module["host"] == "local" and model != identity.get("model"):
            raise ValueError("Local configured capacity model conflicts with controller identity.")
    for point in inputs:
        if not isinstance(point, dict):
            raise ValueError("Hardware inputs must be objects.")
        if (
            "errors" in point
            and (not isinstance(point["errors"], list) or len(point["errors"]) > 64)
            or "properties" in point
            and (
                not isinstance(point["properties"], list)
                or len(point["properties"]) > 64
                or any(not isinstance(row, dict) for row in point["properties"])
            )
        ):
            raise ValueError("Hardware input properties and errors must be bounded lists.")
        obj = point.get("object")
        if not isinstance(obj, str) or not re.fullmatch(
            r"(?:analog|binary|multi-state)-input,[0-9]{1,7}", obj
        ):
            raise ValueError("Hardware input requires an explicit physical BACnet input identity.")
        parsed = ObjectIdentifier(obj)
        if parsed[1] > 4194302 or str(parsed) != obj or obj in seen:
            raise ValueError("Hardware input identities are invalid or duplicated.")
        seen.add(obj)
        for key in ("name", "description", "device_type"):
            value = point.get(key)
            if value is not None and (
                not isinstance(value, str) or len(value.encode("utf-8")) > 4096
            ):
                raise ValueError("Hardware input text exceeds its bounded profile.")
        slot = point.get("slot")
        if slot is not None and (type(slot) is not int or not 1 <= slot <= 255):
            raise ValueError("Hardware input slot is invalid.")
        kind, derived_slot = _terminal(point.get("device_type"), slot)
        if (
            slot is not None
            and re.match(r"\s*(?:UI|BI|CI)\s+IN", point.get("device_type") or "", re.I)
            and derived_slot is None
        ):
            raise ValueError("Hardware slot conflicts with the terminal device-type label.")
        if point.get("terminal_type") not in (None, kind):
            raise ValueError("Hardware terminal type conflicts with the device-type label.")
        host = point.get("host")
        if not isinstance(host, dict) or host.get("kind") not in {
            "unknown",
            "sa",
            "local",
            "local-inferred",
            "local-configured",
        }:
            raise ValueError("Hardware input host evidence is invalid.")
        mac = host.get("sa_mac")
        if host["kind"] == "sa":
            if type(mac) is not int or not 1 <= mac <= 254 or point.get("sa_mac") != mac:
                raise ValueError("Hardware input SA MAC evidence is invalid or conflicting.")
        elif mac is not None or point.get("sa_mac") is not None:
            raise ValueError("Non-SA input cannot claim an SA MAC address.")
        host_key = _host_key(point)
        if host_key is not None and derived_slot is not None:
            assignment = (host_key, derived_slot)
            if assignment in assignments:
                raise ValueError("More than one input claims the same physical terminal.")
            assignments.add(assignment)
    advertised_inputs = {
        obj
        for obj in objects
        if obj.startswith(("analog-input,", "binary-input,", "multi-state-input,"))
    }
    if report.get("inputs_complete") is True and not advertised_inputs <= seen:
        raise ValueError("Complete input evidence must include every advertised physical input.")
    extras = seen - advertised_inputs
    if extras:
        archive = report.get("archive_evidence", {})
        native = {p.get("object"): p for p in archive.get("inputs", []) if isinstance(p, dict)}
        for point in inputs:
            if point["object"] not in extras:
                continue
            match = native.get(point["object"], {})
            record_hash = point.get("archive_record_sha256")
            if (
                archive.get("profile") != ARCHIVE_PROFILE
                or not isinstance(record_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", record_hash)
                or record_hash != match.get("record_sha256")
                or _host_key(point) != _host_key(match)
                or point.get("slot") != match.get("slot")
            ):
                raise ValueError(
                    "Unadvertised input needs matching native archive assignment evidence."
                )
    result = copy.deepcopy(report)
    result["target"] = options.model_dump()
    for point in result["inputs"]:
        point["terminal_type"], point["slot"] = _terminal(
            point.get("device_type"), point.get("slot")
        )
    result["read_only"], result["controller_writes"] = True, False
    result["boundary"] = BOUNDARY
    # Archive-only inputs are valid occupied assignments even if not BACnet-exposed.
    result["inputs_complete"] = report.get("inputs_complete") is True
    result.update(occupancy(result))
    return result


SELECTED = {
    28: "Description",
    31: "Device Type",
    44: "Firmware Version",
    70: "Model Name",
    75: "Object Identifier",
    518: "Setup",
    519: "Slot",
    2390: "Name",
    2577: "Device Reference",
    2858: "JCI MAC Address",
    3645: "SA Bus MAC Address",
    3676: "Requested Model Name",
    3925: "Library Part Id",
    32527: "Item Reference",
}
CLASSES = {
    194: "FEC",
    240: "AI HW Input",
    242: "BI HW Input",
    243: "CI HW Input",
    307: "Bus",
    598: "RIOM Dev",
    627: "Net Sensor Device",
    640: "Local Display",
    671: "RAI",
    673: "RBI",
    910: "SA Bus Device",
}


def _expect(tag, kind, number):
    if tag.tag_class != kind or tag.tag_number != number:
        raise ValueError("Native MOI context framing mismatch.")


def _scalar(tags):
    if len(tags) != 1 or tags[0].tag_class != TagClass.application:
        return None
    tag = tags[0]
    datatypes = {
        TagNumber.unsigned: Unsigned,
        TagNumber.enumerated: Enumerated,
        TagNumber.null: Null,
        TagNumber.objectIdentifier: ObjectIdentifier,
        TagNumber.characterString: CharacterString,
    }
    datatype = datatypes.get(tag.tag_number)
    if datatype is None:
        return None
    if datatype is CharacterString and (
        not tag.tag_data or tag.tag_data[0] not in (0, 3, 4, 5) or len(tag.tag_data) > 4096
    ):
        return None
    if datatype in (Unsigned, Enumerated) and not 1 <= len(tag.tag_data) <= 4:
        return None
    if datatype is Null and tag.tag_data:
        return None
    if datatype is ObjectIdentifier and len(tag.tag_data) != 4:
        return None
    value = datatype.decode(TagList(list(tags)))
    return {
        "type": datatype.__name__,
        "value": str(value) if isinstance(value, ObjectIdentifier) else json_value(value),
    }


def _native_records(data):
    records, errors = [], []
    pattern = rb"(?P<class>.{2})\x02\x00\x0e\x1c(?P<oid>.{4})\x0f\x1e"
    candidates, accepted_end = 0, 0
    for match in re.finditer(pattern, data, re.S):
        if match.start() < accepted_end:
            continue
        cid = int.from_bytes(match["class"], "little")
        oid = int.from_bytes(match["oid"], "big")
        if cid not in CLASSES or cid != oid >> 22:
            continue
        candidates += 1
        if candidates > MAX_RECORDS:
            raise ValueError("Native archive exceeds bounded record count.")
        start = match.start()
        pdu = PDUData(data[start + 4 : min(len(data), start + 1024 * 1024)])
        before = len(pdu.pduData)
        try:
            _expect(Tag.decode(pdu), TagClass.opening, 0)
            identity = Tag.decode(pdu)
            _expect(identity, TagClass.context, 1)
            if bytes(identity.tag_data) != match["oid"]:
                raise ValueError("Native object prefix identity mismatch.")
            _expect(Tag.decode(pdu), TagClass.closing, 0)
            _expect(Tag.decode(pdu), TagClass.opening, 1)
            properties, seen, count = [], set(), 0
            while True:
                tag = Tag.decode(pdu)
                if tag.tag_class == TagClass.closing and tag.tag_number == 1:
                    break
                _expect(tag, TagClass.context, 0)
                if not 1 <= len(tag.tag_data) <= 4:
                    raise ValueError("Native property identifier width invalid.")
                pid = int.from_bytes(tag.tag_data, "big")
                count += 1
                if count > 4096 or pid in seen:
                    raise ValueError("Duplicate or excessive native properties.")
                seen.add(pid)
                _expect(Tag.decode(pdu), TagClass.opening, 2)
                stack, tags = [2], []
                value_start = start + 4 + before - len(pdu.pduData)
                while stack:
                    value = Tag.decode(pdu)
                    if value.tag_class == TagClass.opening:
                        stack.append(value.tag_number)
                    elif value.tag_class == TagClass.closing:
                        if value.tag_number != stack.pop():
                            raise ValueError("Native value nesting mismatch.")
                        if not stack:
                            break
                    tags.append(value)
                    if len(tags) > 20000 or len(stack) > 64:
                        raise ValueError("Native value exceeds tag/depth limits.")
                if pid in SELECTED:
                    end = start + 4 + before - len(pdu.pduData)
                    properties.append(
                        {
                            "id": pid,
                            "name": SELECTED[pid],
                            "scalar": _scalar(tags),
                            "value_offset": value_start,
                            "tag_count": len(tags),
                            "encoded_value_sha256": hashlib.sha256(
                                data[value_start:end]
                            ).hexdigest(),
                        }
                    )
            end = start + 4 + before - len(pdu.pduData)
            accepted_end = end
            records.append(
                {
                    "native_class_id": cid,
                    "native_class_name": CLASSES[cid],
                    "native_instance": oid & 0x3FFFFF,
                    "offset": start,
                    "end_offset": end,
                    "property_count": count,
                    "record_sha256": hashlib.sha256(data[start:end]).hexdigest(),
                    "selected_properties": properties,
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "offset": start,
                    "native_class_id": cid,
                    "error": str(exc)[:240] or type(exc).__name__,
                }
            )
    return records, errors


def _caf_records(raw):
    """Read existing native CAF XML scalars without manufacturing CAF objects."""
    from xml.etree import ElementTree

    from .caf import CafArchive, Q

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as container:
            entries = container.infolist()
            if len(entries) != 1 or entries[0].file_size > MAX_EXPANDED:
                raise ValueError("Hardware CAF requires one XML entry no larger than 8 MiB.")
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid native CAF container.") from exc
    archive = CafArchive(raw)
    records, errors = [], []
    for reference, obj in archive.objects.items():
        cid_text = obj.get("classid", "")
        if not re.fullmatch(r"[0-9]{1,4}", cid_text) or int(cid_text) not in CLASSES:
            continue
        if len(records) >= MAX_RECORDS:
            raise ValueError("CAF hardware records exceed bounded profile.")
        cid = int(cid_text)
        selected = []
        for prop in obj:
            if prop.tag != Q + "property" or int(prop.get("id", "0")) not in SELECTED:
                continue
            pid = int(prop.get("id"))
            scalar = archive.scalar(prop)
            value = None
            if scalar is not None:
                kind, text, attrs = scalar["type"], scalar["text"], scalar["attributes"]
                if kind == "string" and not attrs and len(text.encode("utf-8")) <= 4096:
                    value = {"type": "CharacterString", "value": text}
                elif kind in {"unsignedByte", "unsignedShort", "unsignedLong", "unsigned", "enum"}:
                    allowed_attrs = set() if kind != "enum" else {"set"}
                    if set(attrs) <= allowed_attrs and re.fullmatch(r"[0-9]{1,10}", text):
                        maximum = {"unsignedByte": 255, "unsignedShort": 65535}.get(
                            kind, 4294967295
                        )
                        if int(text) <= maximum:
                            value = {
                                "type": "Enumerated" if kind == "enum" else "Unsigned",
                                "value": int(text),
                            }
                elif kind == "BACoid" and set(attrs) == {"id"}:
                    if re.fullmatch(r"[0-9]{1,4}", attrs["id"]) and re.fullmatch(
                        r"[0-9]{1,7}", text
                    ):
                        typ, instance = int(attrs["id"]), int(text)
                        if typ <= 1023 and instance <= 4194302:
                            value = {
                                "type": "ObjectIdentifier",
                                "value": str(ObjectIdentifier((typ, instance))),
                            }
            selected.append(
                {
                    "id": pid,
                    "name": SELECTED[pid],
                    "scalar": value,
                    "encoded_value_sha256": hashlib.sha256(ElementTree.tostring(prop)).hexdigest(),
                    "hash_scope": "Parsed CAF XML element serialization; source archive hash retains exact bytes.",
                }
            )
        item = next((p for p in selected if p["id"] == 32527), None)
        if item is None:
            selected.append(
                {
                    "id": 32527,
                    "name": "Item Reference",
                    "scalar": {"type": "CharacterString", "value": reference},
                    "evidence": "Explicit CAF object ref attribute; native property 32527 absent.",
                }
            )
        elif item["scalar"] is not None and item["scalar"]["value"] != reference:
            errors.append(
                {
                    "reference": reference,
                    "error": "CAF object reference conflicts with Item Reference property.",
                }
            )
        instance_text = obj.get("objectid", "")
        records.append(
            {
                "native_class_id": cid,
                "native_class_name": CLASSES[cid],
                "native_instance": int(instance_text)
                if re.fullmatch(r"[0-9]{1,10}", instance_text)
                else None,
                "offset": None,
                "end_offset": None,
                "caf_reference": reference,
                "property_count": len(obj),
                "selected_properties": selected,
                "record_sha256": hashlib.sha256(ElementTree.tostring(obj)).hexdigest(),
                "hash_scope": "Parsed CAF XML object serialization; source archive hash retains exact bytes.",
            }
        )
    return archive.xml, records, errors


def analyze_archive(data: bytes, filename: str = "Archive.moi"):
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_SOURCE:
        raise ValueError("Native archive requires 1 byte through 2 MiB.")
    if (
        not isinstance(filename, str)
        or not 1 <= len(filename) <= 240
        or any(c in filename for c in "\x00\r\n")
    ):
        raise ValueError("Archive filename is invalid.")
    raw, compression = data, "none"
    caf_records = None
    if raw.startswith(b"PK\x03\x04"):
        data, caf_records, caf_errors = _caf_records(raw)
        compression = "zip/xml"
    if data.startswith(b"\x1f\x8b"):
        compression = "gzip"
        decoder = zlib.decompressobj(31)
        try:
            data = decoder.decompress(data, MAX_EXPANDED + 1)
            if len(data) > MAX_EXPANDED or decoder.unconsumed_tail:
                raise ValueError("Expanded archive exceeds 8 MiB.")
            data += decoder.flush(MAX_EXPANDED + 1 - len(data))
        except zlib.error as exc:
            raise ValueError("Invalid compressed native archive.") from exc
        if len(data) > MAX_EXPANDED or not decoder.eof or decoder.unused_data:
            raise ValueError(
                "Compressed archive is incomplete, concatenated, or has trailing data."
            )
    result = {
        "profile": ARCHIVE_PROFILE,
        "source": {
            "filename": filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "compression": compression,
            "expanded_bytes": len(data),
            "expanded_sha256": hashlib.sha256(data).hexdigest(),
        },
        "recognized": caf_records is not None or data[2:6] == b"MOI\x00",
        "archive_format": "CAF" if caf_records is not None else "MOI",
        "identity": {},
        "modules": [],
        "inputs": [],
        "errors": [],
        "boundary": BOUNDARY,
        "read_only": True,
        "interpretation": "Narrow native configured hardware record inspector for MOI BACnet-tagged records and existing CAF XML scalars; not a CAF converter or controller compiler.",
    }
    if not result["recognized"]:
        result["errors"].append(
            {"error": "Expected native MOI marker is absent; no configured hardware inferred."}
        )
        result["native_records"] = []
        return result
    if caf_records is not None:
        records, result["errors"] = caf_records, caf_errors
    else:
        records, result["errors"] = _native_records(data)
    result["native_records"] = records
    modules_by_ref, base_records = {}, []
    for record in records:
        props = {
            p["id"]: p["scalar"]["value"]
            for p in record["selected_properties"]
            if p["scalar"] is not None
        }
        cid = record["native_class_id"]
        if cid == 194:
            base_records.append(props)
        if cid not in (598, 910):
            continue
        mac = props.get(2858, props.get(3645))
        model = props.get(3676) or props.get(70)
        if (
            type(mac) is not int
            or not 1 <= mac <= 254
            or (
                type(props.get(2858)) is int
                and type(props.get(3645)) is int
                and props[2858] != props[3645]
            )
        ):
            result["errors"].append(
                {
                    "offset": record["offset"],
                    "error": "Configured SA module lacks an explicit valid MAC address.",
                }
            )
            continue
        module = {
            "host": "sa",
            "sa_mac": mac,
            "configured_model": model,
            "name": props.get(2390),
            "description": props.get(28),
            "item_reference": props.get(32527),
            "capacity": model_capacity(model),
            "model_evidence": "Native configured module record",
            "record_sha256": record["record_sha256"],
            "native_class_id": cid,
            "native_instance": record["native_instance"],
            "installed_model_verified": False,
        }
        result["modules"].append(module)
        if isinstance(props.get(32527), str):
            modules_by_ref[props[32527]] = module
    if len(base_records) == 1:
        props = base_records[0]
        result["identity"] = {
            "object": props.get(75),
            "name": props.get(2390),
            "model": props.get(70),
            "item_reference": props.get(32527),
        }
    elif len(base_records) > 1:
        result["errors"].append(
            {"error": "Multiple native controller roots; identity is ambiguous."}
        )
    for record in records:
        if record["native_class_id"] not in (240, 242, 243, 671, 673):
            continue
        props = {
            p["id"]: p["scalar"]["value"]
            for p in record["selected_properties"]
            if p["scalar"] is not None
        }
        obj, reference = props.get(75), props.get(32527)
        if not isinstance(obj, str) or not obj.startswith(
            ("analog-input,", "binary-input,", "multi-state-input,")
        ):
            continue
        kind, slot = _terminal(props.get(31), props.get(519))
        host = {"kind": "unknown"}
        matches = [
            module
            for ref, module in modules_by_ref.items()
            if isinstance(reference, str) and reference.startswith(ref + ".")
        ]
        if len(matches) == 1:
            host = {
                "kind": "sa",
                "sa_mac": matches[0]["sa_mac"],
                "evidence": "Native point item-reference beneath configured module",
            }
        elif isinstance(reference, str) and isinstance(
            result["identity"].get("item_reference"), str
        ):
            root = result["identity"]["item_reference"]
            if re.fullmatch(re.escape(root) + r"/[0-9]+_[0-9]+", reference):
                host = {
                    "kind": "local-configured",
                    "sa_mac": None,
                    "evidence": "Native point item-reference directly beneath controller",
                }
        explicit_mac = props.get(3645)
        if type(explicit_mac) is int and 1 <= explicit_mac <= 254:
            if host["kind"] in {"sa", "local-configured"} and host.get("sa_mac") != explicit_mac:
                result["errors"].append(
                    {
                        "offset": record["offset"],
                        "object": obj,
                        "error": "Explicit SA address conflicts with native parent assignment.",
                    }
                )
                host = {"kind": "unknown"}
            else:
                host = {
                    "kind": "sa",
                    "sa_mac": explicit_mac,
                    "evidence": "Explicit native SA Bus MAC Address property 3645",
                }
        result["inputs"].append(
            {
                "object": obj,
                "name": props.get(2390),
                "description": props.get(28),
                "device_type": props.get(31),
                "slot": slot,
                "terminal_type": kind,
                "host": host,
                "sa_mac": host.get("sa_mac"),
                "setup_raw": props.get(518),
                "item_reference": reference,
                "native_class_id": record["native_class_id"],
                "record_sha256": record["record_sha256"],
                "errors": [],
            }
        )
    if len({m["sa_mac"] for m in result["modules"]}) != len(result["modules"]):
        result["errors"].append(
            {"error": "Duplicate configured SA module addresses; availability is ambiguous."}
        )
    if len({p["object"] for p in result["inputs"]}) != len(result["inputs"]):
        result["errors"].append(
            {"error": "Duplicate native input object identities; availability is ambiguous."}
        )
    result["inventory"] = {
        "complete": not result["errors"] and bool(result["identity"]) and bool(result["inputs"]),
        "scope": "Recognized native hardware records only; confirm native editor assignments.",
    }
    result.update(occupancy(result))
    return result


def enrich_report(report, evidence):
    if report.get("profile") != PROFILE or evidence.get("profile") != ARCHIVE_PROFILE:
        raise ValueError("Expected a hardware survey and native hardware archive evidence.")
    result = copy.deepcopy(report)
    comparison = {
        "archive_source": copy.deepcopy(evidence.get("source")),
        "identity_match": False,
        "matched": [],
        "conflicts": [],
        "unresolved": [],
        "configured_models_applied": False,
    }
    result["archive_comparison"] = comparison
    result["archive_evidence"] = copy.deepcopy(evidence)
    live_identity = report.get("identity", {}).get("object")
    archive_identity = evidence.get("identity", {}).get("object")
    comparison["identity_match"] = bool(live_identity and live_identity == archive_identity)
    if not comparison["identity_match"]:
        comparison["conflicts"].append(
            {"error": "Archive controller identity does not match the verified survey Device."}
        )
    live_model = report.get("identity", {}).get("model")
    archive_model = evidence.get("identity", {}).get("model")
    if live_model and archive_model and live_model != archive_model:
        comparison["conflicts"].append(
            {"error": "Live and native controller model identities differ."}
        )
    live_name = report.get("identity", {}).get("name")
    archive_name = evidence.get("identity", {}).get("name")
    if live_name and archive_name and live_name != archive_name:
        comparison["conflicts"].append({"error": "Live and native controller names differ."})
    if not live_model or not archive_model or not live_name or not archive_name:
        comparison["unresolved"].append(
            {"error": "Controller name/model corroboration is incomplete."}
        )
    if evidence.get("errors"):
        comparison["conflicts"].append(
            {"error": "Native archive has parse or ambiguity errors; model merge withheld."}
        )
    native = {p["object"]: p for p in evidence.get("inputs", [])}
    for point in report.get("inputs", []):
        match = native.get(point["object"])
        if match is None:
            comparison["unresolved"].append(
                {
                    "object": point["object"],
                    "error": "Live input absent from recognized native hardware records.",
                }
            )
            continue
        live_key, native_key = _host_key(point), _host_key(match)
        if (
            live_key is None
            or native_key is None
            or point.get("slot") is None
            or match.get("slot") is None
        ):
            comparison["unresolved"].append(
                {"object": point["object"], "error": "Host or terminal evidence is incomplete."}
            )
        elif (
            live_key != native_key
            or point.get("slot") != match.get("slot")
            or point.get("terminal_type") != match.get("terminal_type")
        ):
            comparison["conflicts"].append(
                {
                    "object": point["object"],
                    "error": "Live/native host or terminal assignments differ.",
                }
            )
        elif (point.get("name") and match.get("name") and point["name"] != match["name"]) or (
            point.get("setup_raw") is not None
            and match.get("setup_raw") is not None
            and point["setup_raw"] != match["setup_raw"]
        ):
            comparison["conflicts"].append(
                {
                    "object": point["object"],
                    "error": "Live/native point name or raw setup configuration differs.",
                }
            )
        else:
            comparison["matched"].append(point["object"])
    live_objects = {p["object"] for p in report.get("inputs", [])}
    comparison["archive_only_inputs"] = [
        p["object"] for p in evidence.get("inputs", []) if p["object"] not in live_objects
    ]
    if (
        comparison["identity_match"]
        and not comparison["conflicts"]
        and not comparison["unresolved"]
    ):
        comparison["configured_models_applied"] = True
        result["modules"] = copy.deepcopy(evidence.get("modules", []))
        # Include native-only assigned inputs conservatively, including non-exposed points.
        result["inputs"].extend(
            copy.deepcopy(p) for p in evidence.get("inputs", []) if p["object"] not in live_objects
        )
        for point in result["inputs"]:
            if point["object"] in native:
                point["archive_record_sha256"] = native[point["object"]].get("record_sha256")
    result.update(occupancy(result))
    return result


compare_report = enrich_report


def relocation_plan(report, source_object, destination_sa_mac, destination_slot):
    if report.get("profile") not in (PROFILE, ARCHIVE_PROFILE):
        raise ValueError("A hardware survey or native archive evidence report is required.")
    if (
        (
            destination_sa_mac is not None
            and (type(destination_sa_mac) is not int or not 1 <= destination_sa_mac <= 254)
        )
        or type(destination_slot) is not int
        or not 1 <= destination_slot <= 255
    ):
        raise ValueError(
            "Select a valid SA module address or local controller and destination slot."
        )
    plan = {
        "profile": "hardware-input-relocation-review/1",
        "read_only": True,
        "status": "blocked",
        "source_object": source_object,
        "destination": {
            "sa_mac": destination_sa_mac,
            "slot": destination_slot,
            "terminal": f"IN{destination_slot}",
        },
        "reasons": [],
        "required_checks": [
            "Confirm installed module labels and terminal wiring.",
            "Confirm the alarm source is electrically compatible with the destination binary input, including dry-contact requirements.",
            "Preserve polarity, fail state, delays, alarm settings, and all application references.",
            "Back up the native application and perform reassignment with a verified manufacturer-compatible authoring/download path.",
            "Rewire during an approved service window and validate alarm transitions and restored operation.",
        ],
        "native_program_modified": False,
        "controller_writes": False,
        "boundary": "Engineering review only; no native compiler, physical rewiring, download, or controller modification is performed.",
    }
    matching = [p for p in report.get("inputs", []) if p.get("object") == source_object]
    if len(matching) != 1:
        plan["reasons"].append("Source input is missing or ambiguous.")
        return plan
    source = matching[0]
    plan["source"] = copy.deepcopy(source)
    if (
        not source_object.startswith("binary-input,")
        or source.get("terminal_type") != "UI"
        or _host_key(source) is None
    ):
        plan["reasons"].append(
            "Source must be an identified binary input occupying a universal input."
        )
    derived = occupancy(report)
    modules = derived["modules"]
    source_key = _host_key(source)
    source_modules = [
        module
        for module in modules
        if (
            (module.get("host") == "local" and source_key == ("local", None))
            or (module.get("host") == "sa" and source_key == ("sa", module.get("sa_mac")))
        )
    ]
    if (
        len(source_modules) != 1
        or not source_modules[0].get("capacity")
        or source.get("slot") not in source_modules[0]["capacity"]["universal_inputs"]
        or not source_modules[0]["capacity"].get("voltage_input_range")
    ):
        plan["reasons"].append(
            "Source universal-input voltage capability requires a documented configured module model."
        )
    destination = [
        m
        for m in modules
        if (
            (destination_sa_mac is None and m.get("host") == "local")
            or (
                destination_sa_mac is not None
                and m.get("host") == "sa"
                and m.get("sa_mac") == destination_sa_mac
            )
        )
    ]
    if len(destination) != 1 or not destination[0].get("capacity"):
        plan["reasons"].append("Destination configured module capacity is unknown or ambiguous.")
    elif destination_slot not in destination[0]["capacity"]["binary_inputs"]:
        plan["reasons"].append("Destination is not a documented dedicated binary input.")
    else:
        plan["destination"]["configured_model"] = destination[0].get("configured_model")
    occupied = [
        p["object"]
        for p in report.get("inputs", [])
        if _host_key(p)
        == (("local", None) if destination_sa_mac is None else ("sa", destination_sa_mac))
        and p.get("slot") == destination_slot
    ]
    if occupied:
        plan["reasons"].append("Destination already has assigned inputs: " + ", ".join(occupied))
    if not any(
        candidate["sa_mac"] == destination_sa_mac
        and candidate["slot"] == destination_slot
        and candidate["terminal_type"] == "BI"
        and candidate["status"] == "candidate"
        for candidate in derived["candidates"]
    ):
        plan["reasons"].append(
            "Destination has no complete, unambiguous spare binary-input evidence."
        )
    if (
        not report.get("inventory", {}).get("complete")
        or (report.get("profile") == PROFILE and report.get("inputs_complete") is not True)
        or report.get("archive_comparison", {}).get("conflicts")
        or report.get("archive_comparison", {}).get("unresolved")
        or any(_host_key(p) is None or p.get("slot") is None for p in report.get("inputs", []))
    ):
        plan["reasons"].append("Complete, conflict-free assignment evidence is required.")
    if not plan["reasons"]:
        plan["status"] = "review-required"
        plan["freed_input"] = {
            "sa_mac": source.get("sa_mac"),
            "slot": source.get("slot"),
            "terminal_type": "UI",
            "voltage_capable": True,
            "status": "available-only-after-successful-reassignment-and-rewiring",
        }
    return plan
