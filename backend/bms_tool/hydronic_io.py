"""Source-qualified chilled-water hydraulic role planning, never plant control."""

from __future__ import annotations

import asyncio
import copy
import csv
import hashlib
import io
import json
import threading
from collections import OrderedDict, defaultdict
from typing import Annotated, Literal

from fastapi import APIRouter, Request, Response
from pydantic import Field, ValidationError, field_validator, model_validator

from . import physical_capacity as capacity
from .models import StrictModel
from .plant_signals import (
    Hash,
    Key,
    Name,
    NodeId,
    ReviewKey,
    digest,
    encoded,
    strict_json,
    verify_report,
)

MAX_REQUEST = 512 * 1024
MAX_REPORT = 24 * 1024 * 1024
SCOPE = (
    "Offline authored hydraulic I/O subset for parallel chilled-water plants. Exact portable "
    "PLANT sources, declared network links and per-physical-host electrical count witnesses only. "
    "No generated control Program, spare terminal determination, whole-application capacity, "
    "installed identity, wiring, safety, hydraulic simulation, native CAF, field traffic, "
    "Guideline36 or Title24 acceptance."
)
SOURCES = {
    "chilled-2025": {
        "document": "LIT-12014531",
        "edition": "1.0",
        "date": "2025-05-15",
        "sha256": "87298adc723f40cc5c0ff08d08822dbd7c931698e576b7c51b099f5a59c839d7",
        "pdf_pages": [5, 6, 7, 8, 34, 35, 36, 37, 49, 50, 51, 52, 53, 54],
        "tables": [28, 29, 32],
        "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Chilled-Water-Plant-for-Guideline-36-Application-Note/1.0",
    },
    "cpo10-2017": {
        "document": "LIT-12011575",
        "date": "2017-06-01",
        "pdf_pages": [13],
        "sha256": "4d55be500d3e4b07399a3bf4019ef93a55eabbc10d156bdafb1c0e7c363828a2",
    },
}
CONFLICTS = [
    {
        "id": "edition-variable-primary-secondary",
        "sources": ["chilled-2025", "cpo10-2017"],
        "meaning": "2017 CPO10 excludes a secondary loop with variable primary pumps. This separate 2025 chilled profile explicitly allows variable primary-secondary; no migration or universal hydraulic prohibition is inferred.",
    },
    {
        "id": "temperature-strategy-flow-staging",
        "sources": ["chilled-2025"],
        "meaning": "PDF35 describes temperature-based primary speed without flow meters; PDF36 still uses secondary flow for headered staging. This bounded profile always retains secondary staging flow, and headered primary staging retains primary flow.",
    },
    {
        "id": "table-classifications",
        "sources": ["chilled-2025"],
        "meaning": "PDF51 includes HX BI/command and bypass classifications inconsistent with names. HX and series-chiller bypass points are excluded. The primary-only common modulating bypass command follows PDF37 and CHWBYP-O control point in Table28, not suffix inference.",
    },
]
OUTSIDE = [
    "Whole-application CHW supply-temperature/setpoint and supervisory requests/reset mappings remain outside this hydraulic subset unless an individual measurement is selected here.",
    "Chiller/OEM safety, minimum/design flow data, balancing, isolation timing, pump/chiller proving behavior, failure handling and permissives require separate sequence and commissioning review.",
    "Condenser water, towers, heat exchangers, waterside economizers, series chillers, hot-water plants and constant-speed primary operation are outside this profile.",
    "Other application I/O occupancy is unknown. Count fit of this declared hydraulic subset never establishes spare channels or whole-plant fit.",
    "Network-linked values do not consume channels here. Upstream sensor and downstream actuator physical channels are outside this subset unless separately represented by a derived physical binding.",
]
MONITORS = Literal[
    "chiller-status",
    "chiller-alarm",
    "chiller-maintenance",
    "chiller-entering-temperature",
    "chiller-leaving-temperature",
    "chiller-flow",
    "primary-status",
    "primary-fault",
    "primary-lockout",
    "secondary-status",
    "secondary-fault",
    "secondary-lockout",
    "primary-supply-temperature",
    "primary-return-temperature",
    "secondary-supply-temperature",
    "secondary-return-temperature",
    "primary-flow",
    "secondary-flow",
    "decoupler-flow",
    "system-pressure",
]
UNITS = {
    "flow": ["gpm", "L/s", "m3/h"],
    "pressure": ["psi", "kPa", "bar"],
    "temperature": ["degF", "degC", "°F", "°C"],
    "command": ["%"],
}
PROFILE = {
    "id": "chilled-hydraulic-io-planner/1",
    "scope": SCOPE,
    "sources": SOURCES,
    "source_conflicts": CONFLICTS,
    "policy": {
        "layouts": "Parallel chillers; primary-only/primary-secondary times headered/dedicated primary pumps. Variable-speed pumps only.",
        "dedicated": "Exactly one primary pump per chiller is an explicit bounded authored assumption.",
        "headered": "Headered pumps must be explicitly declared equally sized; no different-size equivalence.",
        "direction": "Application-side Input measures/receives; Output commands/sends. Physical versus network transport does not reverse that direction.",
        "units": "Explicit authored interface vocabulary, not a claim that point tables prescribe these unit tokens. Original source unit text must match exactly; no alias normalization or conversion.",
        "capacity": "Only explicit physical bindings consume one channel each, grouped by exact declared controller/module and electrical mode. No inferred expansions, terminal numbering or occupied-channel subtraction.",
        "provenance": "Self-sealed PLANT source evidence and survey declarations are not authenticated manufacturer or installed-device proof.",
    },
    "units": UNITS,
    "limits": {
        "chillers": 8,
        "primary_pumps": 8,
        "secondary_pumps": 8,
        "physical_hosts": 32,
        "bindings": 256,
        "request_bytes": MAX_REQUEST,
        "report_bytes": MAX_REPORT,
        "session_reviews": 8,
        "session_review_bytes": 48 * 1024 * 1024,
    },
}
PROFILE["sha256"] = digest(PROFILE)


class Units(StrictModel):
    flow: Literal["gpm", "L/s", "m3/h"]
    pressure: Literal["psi", "kPa", "bar"]
    temperature: Literal["degF", "degC", "°F", "°C"]


class Topology(StrictModel):
    loop: Literal["primary-only", "primary-secondary"]
    primary_arrangement: Literal["headered", "dedicated"]
    chillers: int = Field(strict=True, ge=1, le=8)
    primary_pumps: int | None = Field(default=None, strict=True, ge=1, le=8)
    secondary_pumps: int | None = Field(default=None, strict=True, ge=1, le=8)
    primary_speed: Literal["variable"]
    equally_sized_primary: Literal[True] | None = None
    equally_sized_secondary: Literal[True] | None = None
    isolation_command: Literal["binary", "modulating"] | None = None
    primary_speed_measurement: (
        Literal["decoupler-flow", "flow-difference", "temperature-difference"] | None
    ) = None
    units: Units
    monitoring: list[MONITORS] = Field(default_factory=list, max_length=20)
    prove_on: list[Literal["chiller", "primary", "secondary"]] = Field(
        default_factory=list, max_length=3
    )

    @field_validator("equally_sized_primary", "equally_sized_secondary", mode="before")
    @classmethod
    def exact_boolean(cls, value):
        if value is not None and type(value) is not bool:
            raise ValueError("Equal-size declarations require exact Boolean true, never integer1.")
        return value

    @model_validator(mode="after")
    def choices(self):
        if len(set(self.monitoring)) != len(self.monitoring) or len(set(self.prove_on)) != len(
            self.prove_on
        ):
            raise ValueError("Monitoring/prove-on selections must be distinct.")
        if self.primary_arrangement == "headered":
            if (
                self.primary_pumps is None
                or self.equally_sized_primary is not True
                or self.isolation_command is None
            ):
                raise ValueError(
                    "Headered primary needs explicit count, equally-sized declaration and isolation command type."
                )
        elif any(
            x is not None
            for x in (self.primary_pumps, self.equally_sized_primary, self.isolation_command)
        ):
            raise ValueError(
                "Dedicated primary derives one pump per chiller; headered count/equal-size/isolation choices are irrelevant."
            )
        if self.loop == "primary-secondary":
            if (
                self.secondary_pumps is None
                or self.equally_sized_secondary is not True
                or self.primary_speed_measurement is None
            ):
                raise ValueError(
                    "Primary-secondary needs secondary count/equal-size and an explicit primary-speed measurement strategy."
                )
        elif (
            any(
                x is not None
                for x in (
                    self.secondary_pumps,
                    self.equally_sized_secondary,
                    self.primary_speed_measurement,
                )
            )
            or "secondary" in self.prove_on
            or any(x.startswith("secondary-") or x == "decoupler-flow" for x in self.monitoring)
        ):
            raise ValueError(
                "Primary-only cannot select secondary/decoupler strategies, pumps or monitoring."
            )
        return self


class DeriveRequest(StrictModel):
    profile_sha256: Hash
    topology: Topology


RoleId = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")]


class PhysicalHost(StrictModel):
    id: Key
    label: Name
    plant_host_id: Key
    kind: Literal["controller", "module"]
    model: str = Field(
        strict=True, min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f-\x9f]+$"
    )
    parent_controller_id: Key | None = None
    survey_reference: capacity.SurveyReference | None = None

    @field_validator("model")
    @classmethod
    def visible_model(cls, value):
        if not value.strip() or any(not char.isprintable() for char in value):
            raise ValueError("Physical model requires visible printable text; no blank model.")
        return value

    @model_validator(mode="after")
    def ownership(self):
        if (self.kind == "module") != (self.parent_controller_id is not None):
            raise ValueError(
                "A module needs one explicit parent controller; a controller cannot have one."
            )
        if self.survey_reference and self.survey_reference.host != (
            "sa" if self.kind == "module" else "base"
        ):
            raise ValueError(
                "Physical controller/module kind conflicts with exact base/SA survey host."
            )
        return self


class Binding(StrictModel):
    role_id: RoleId
    instance_id: Key
    node_id: NodeId
    transport: Literal["physical", "network"]
    physical_host_id: Key | None = None
    mode: capacity.Mode | None = None
    network_link_ids: list[Key] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def transport_fields(self):
        if self.transport == "physical":
            if self.physical_host_id is None or self.mode is None or self.network_link_ids:
                raise ValueError(
                    "Physical binding needs explicit host and electrical mode, without network links."
                )
        elif (
            self.physical_host_id is not None or self.mode is not None or not self.network_link_ids
        ):
            raise ValueError(
                "Network binding needs explicit link IDs and cannot consume physical capacity."
            )
        if len(set(self.network_link_ids)) != len(self.network_link_ids):
            raise ValueError("Network link identities must be distinct.")
        return self


class ReviewRequest(DeriveRequest):
    plant_review: ReviewKey
    capacity_catalog_sha256: Hash
    physical_hosts: list[PhysicalHost] = Field(default_factory=list, max_length=32)
    bindings: list[Binding] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def distinct(self):
        if len({x.id for x in self.physical_hosts}) != len(self.physical_hosts):
            raise ValueError("Physical host IDs must be distinct.")
        if len({x.role_id for x in self.bindings}) != len(self.bindings):
            raise ValueError("Each derived role accepts one binding.")
        if len({(x.instance_id, x.node_id) for x in self.bindings}) != len(self.bindings):
            raise ValueError(
                "An exact PLANT endpoint cannot bind different roles; shared hydraulic uses derive one shared role instead."
            )
        return self


class ExportKey(StrictModel):
    content_sha256: Hash


def _check_profile(value):
    if value != PROFILE["sha256"]:
        raise ValueError("Hydraulic profile changed; reload before deriving/reviewing.")


def derive(value):
    request = DeriveRequest.model_validate(value)
    _check_profile(request.profile_sha256)
    choice = request.topology
    primary_count = (
        choice.primary_pumps if choice.primary_arrangement == "headered" else choice.chillers
    )
    secondary_count = choice.secondary_pumps or 0
    roles, dependencies = {}, []

    def add(identifier, label, direction, value_type, unit, use, pages, table, subsystem):
        reason = {"use": use, "source": "chilled-2025", "pdf_pages": pages, "table": table}
        if identifier not in roles:
            roles[identifier] = {
                "id": identifier,
                "label": label,
                "direction": direction,
                "value_type": value_type,
                "unit": unit,
                "subsystem": subsystem,
                "reasons": [],
            }
        if reason not in roles[identifier]["reasons"]:
            roles[identifier]["reasons"].append(reason)
        return identifier

    def sensor(identifier, label, dimension, use, pages, table=28, subsystem="chiller"):
        return add(
            identifier,
            label,
            "input",
            "boolean" if dimension == "boolean" else "number",
            "" if dimension == "boolean" else getattr(choice.units, dimension),
            use,
            pages,
            table,
            subsystem,
        )

    def dependency(identifier, ids, pages):
        dependencies.append(
            {
                "id": identifier,
                "role_ids": sorted(ids),
                "source": "chilled-2025",
                "pdf_pages": pages,
                "meaning": "Engineering measurement/coordination requirements; not executable sequence edges.",
            }
        )

    for index in range(1, choice.chillers + 1):
        add(
            f"chiller.{index}.enable",
            f"Chiller{index} enable",
            "output",
            "boolean",
            "",
            "equipment-command",
            [50],
            28,
            "chiller",
        )
        if choice.primary_arrangement == "headered":
            modulating = choice.isolation_command == "modulating"
            add(
                f"chiller.{index}.isolation",
                f"Chiller{index} CHW isolation command",
                "output",
                "number" if modulating else "boolean",
                "%" if modulating else "",
                "headered-chiller-isolation",
                [34, 50],
                28,
                "chiller",
            )
    for subsystem, count, table, pages in (
        ("primary", primary_count, 29, [34, 35, 52]),
        ("secondary", secondary_count, 32, [36, 53]),
    ):
        for index in range(1, count + 1):
            for kind, typ, unit in (("enable", "boolean", ""), ("speed", "number", "%")):
                add(
                    f"{subsystem}.{index}.{kind}",
                    f"{subsystem.capitalize()} pump{index} {kind}",
                    "output",
                    typ,
                    unit,
                    "equipment-command",
                    pages,
                    table,
                    "pchwp" if subsystem == "primary" else "schwp",
                )
    pressure = sensor(
        "building.dp",
        "Building CHW differential pressure",
        "pressure",
        "primary-speed" if not secondary_count else "secondary-speed",
        [35] if not secondary_count else [36],
        28,
    )
    if not secondary_count:
        bypass = add(
            "plant.minimum_flow_bypass",
            "Common minimum-flow bypass command",
            "output",
            "number",
            "%",
            "minimum-flow-bypass",
            [37, 51],
            28,
            "chiller",
        )
        flow = sensor("primary.flow", "Primary CHW flow", "flow", "minimum-flow-bypass", [37, 52])
        dependency("minimum-flow-bypass", [bypass, flow], [37])
        dependency("primary-speed-control", [pressure], [35])
    else:
        secondary_flow = sensor(
            "secondary.flow",
            "Secondary CHW flow",
            "flow",
            "secondary-flow-staging",
            [36, 54],
            32,
            "schwp",
        )
        dependency("secondary-flow-staging", [secondary_flow], [36])
        dependency("secondary-speed-control", [pressure], [36])
        strategy = choice.primary_speed_measurement
        if strategy == "decoupler-flow":
            required = [
                sensor(
                    "decoupler.flow",
                    "Decoupler flow",
                    "flow",
                    "primary-speed-control",
                    [35, 52],
                    29,
                    "pchwp",
                )
            ]
        elif strategy == "flow-difference":
            required = [
                sensor(
                    "primary.flow", "Primary CHW flow", "flow", "primary-speed-control", [35, 52]
                ),
                sensor(
                    "secondary.flow",
                    "Secondary CHW flow",
                    "flow",
                    "primary-speed-control",
                    [35, 54],
                    32,
                    "schwp",
                ),
            ]
        else:
            required = [
                sensor(
                    "primary.supply_temperature",
                    "Primary CHW supply temperature",
                    "temperature",
                    "primary-speed-control",
                    [35, 51],
                ),
                sensor(
                    "secondary.supply_temperature",
                    "Secondary CHW supply temperature",
                    "temperature",
                    "primary-speed-control",
                    [35, 51, 54],
                    32,
                    "schwp",
                ),
            ]
        dependency("primary-speed-control", required, [35])
    if choice.primary_arrangement == "headered":
        flow = sensor("primary.flow", "Primary CHW flow", "flow", "primary-flow-staging", [34, 52])
        dependency("primary-flow-staging", [flow], [34])
    monitor_specs = {
        "chiller-status": ("chiller", choice.chillers, "status", "boolean", 28, [50]),
        "chiller-alarm": ("chiller", choice.chillers, "alarm", "boolean", 28, [50]),
        "chiller-maintenance": ("chiller", choice.chillers, "maintenance", "boolean", 28, [50]),
        "chiller-entering-temperature": (
            "chiller",
            choice.chillers,
            "entering_temperature",
            "temperature",
            28,
            [50],
        ),
        "chiller-leaving-temperature": (
            "chiller",
            choice.chillers,
            "leaving_temperature",
            "temperature",
            28,
            [50],
        ),
        "chiller-flow": ("chiller", choice.chillers, "flow", "flow", 28, [50]),
        "primary-status": ("primary", primary_count, "status", "boolean", 29, [52]),
        "primary-fault": ("primary", primary_count, "fault", "boolean", 29, [52]),
        "primary-lockout": ("primary", primary_count, "lockout", "boolean", 29, [52]),
        "secondary-status": ("secondary", secondary_count, "status", "boolean", 32, [53]),
        "secondary-fault": ("secondary", secondary_count, "fault", "boolean", 32, [53]),
        "secondary-lockout": ("secondary", secondary_count, "lockout", "boolean", 32, [53]),
    }
    selections = [(name, "optional-monitor") for name in sorted(choice.monitoring)] + [
        (name + "-status", "selected-prove-on") for name in sorted(choice.prove_on)
    ]
    for name, use in selections:
        if name in monitor_specs:
            group, count, suffix, dimension, table, pages = monitor_specs[name]
            for index in range(1, count + 1):
                sensor(
                    f"{group}.{index}.{suffix}",
                    f"{group.capitalize()}{index} {suffix.replace('_', ' ')}",
                    dimension,
                    use,
                    pages,
                    table,
                    {"chiller": "chiller", "primary": "pchwp", "secondary": "schwp"}[group],
                )
        elif name == "system-pressure":
            sensor("system.pressure", "System gauge pressure", "pressure", use, [52], 29, "pchwp")
        elif name == "decoupler-flow":
            sensor("decoupler.flow", "Decoupler flow", "flow", use, [52], 29, "pchwp")
        elif name.endswith("-flow"):
            group = name.split("-")[0]
            sensor(
                group + ".flow",
                group.capitalize() + " CHW flow",
                "flow",
                use,
                [52] if group == "primary" else [54],
                28 if group == "primary" else 32,
                "chiller" if group == "primary" else "schwp",
            )
        else:
            group, position, _ = name.split("-")
            sensor(
                group + "." + position + "_temperature",
                f"{group.capitalize()} CHW {position} temperature",
                "temperature",
                use,
                [51, 54] if group == "secondary" else [51],
                32 if group == "secondary" else 28,
                "schwp" if group == "secondary" else "chiller",
            )
    unresolved = [
        {
            "id": "unresolved-" + group + "-proving",
            "meaning": f"{group.capitalize()} prove-on source/strategy is not selected; safe enable/prove/failure sequencing is not established.",
        }
        for group in ("chiller", "primary", *(("secondary",) if secondary_count else ()))
        if group not in choice.prove_on
    ]
    result = {
        "format": "bms.chilled-hydraulic-role-plan/1",
        "profile_sha256": PROFILE["sha256"],
        "topology": choice.model_dump(),
        "equipment_counts": {
            "chillers": choice.chillers,
            "primary_pumps": primary_count,
            "secondary_pumps": secondary_count,
        },
        "roles": [roles[k] for k in sorted(roles)],
        "dependencies": sorted(dependencies, key=lambda x: x["id"]),
        "unresolved_sequence_assumptions": unresolved,
        "outside_subset_dependencies": copy.deepcopy(OUTSIDE),
        "source_conflicts": copy.deepcopy(CONFLICTS),
        "scope": SCOPE,
        "control_program_generated": False,
        "field_queries": False,
        "controller_writes": False,
    }
    result["content_sha256"] = digest(result)
    return result


def _safe(value):
    text = (
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        if isinstance(value, (dict, list))
        else str(value)
    )
    return (
        "'" + text
        if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n"))
        else text
    )


def csv_report(report):
    output = io.StringIO(newline="")
    fields = [
        "role_id",
        "label",
        "direction",
        "value_type",
        "unit",
        "subsystem",
        "reasons",
        "binding_status",
        "transport",
        "instance_id",
        "node_id",
        "physical_host_id",
        "mode",
        "network_link_ids",
        "profile_sha256",
        "role_plan_sha256",
        "plant_review_sha256",
        "hydraulic_review_sha256",
        "source_id",
        "program_id",
        "program_name",
        "revision_text",
        "source_canonical_sha256",
        "point_label",
        "plant_host_id",
        "physical_model",
        "physical_kind",
        "parent_controller_id",
        "capacity_catalog_sha256",
        "capacity_review_sha256",
        "capacity_status",
        "capacity_scope",
        "hardware_verified",
        "native_allocation_verified",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    plan = report.get("role_plan", report)
    bindings = {row["role_id"]: row for row in report.get("binding_results", [])}
    physical = {row["physical_host"]["id"]: row for row in report.get("capacity_reviews", [])}
    for role in plan["roles"]:
        binding = bindings.get(role["id"], {})
        row = {
            k: role[k] for k in ("label", "direction", "value_type", "unit", "subsystem", "reasons")
        }
        row.update(
            {
                k: binding.get(k, "")
                for k in (
                    "transport",
                    "instance_id",
                    "node_id",
                    "physical_host_id",
                    "mode",
                    "network_link_ids",
                )
            }
        )
        row.update(
            role_id=role["id"],
            binding_status=binding.get("status", "unbound"),
            profile_sha256=PROFILE["sha256"],
            role_plan_sha256=plan["content_sha256"],
            plant_review_sha256=report.get("plant_reference", {}).get("raw_sha256", ""),
            hydraulic_review_sha256=report.get("content_sha256", "")
            if "role_plan" in report
            else "",
            capacity_scope="declared hydraulic subset only; other application occupancy unknown",
            hardware_verified="false",
            native_allocation_verified="false",
        )
        point = binding.get("point") or {}
        host = physical.get(binding.get("physical_host_id"), {})
        declared = host.get("physical_host", {})
        witness = host.get("capacity_review", {})
        row.update(
            source_id=point.get("source_id", ""),
            program_id=point.get("program_id", ""),
            program_name=point.get("program_name", ""),
            revision_text=point.get("revision_text", ""),
            source_canonical_sha256=point.get("canonical_sha256", ""),
            point_label=point.get("label", ""),
            plant_host_id=point.get("host_id", ""),
            physical_model=declared.get("model", ""),
            physical_kind=declared.get("kind", ""),
            parent_controller_id=declared.get("parent_controller_id") or "",
            capacity_catalog_sha256=witness.get("catalog_sha256", ""),
            capacity_review_sha256=witness.get("content_sha256", ""),
            capacity_status=witness.get("status", ""),
        )
        writer.writerow({k: _safe(v) for k, v in row.items()})
    return output.getvalue().encode("utf-8")


class HydronicPlanner:
    def __init__(self, plant, hardware):
        self.plant, self.hardware = plant, hardware
        self.reviews = OrderedDict()
        self.lock = threading.RLock()

    def profile(self):
        return {
            "profile": copy.deepcopy(PROFILE),
            "capacity_catalog_sha256": capacity.CATALOG["catalog_sha256"],
            "topology_schema": Topology.model_json_schema(),
            "review_schema": ReviewRequest.model_json_schema(),
            "scope": SCOPE,
            "field_queries": False,
            "controller_writes": False,
        }

    def _authority(self, request):
        _check_profile(request.profile_sha256)
        if request.capacity_catalog_sha256 != capacity.CATALOG["catalog_sha256"]:
            raise ValueError(
                "Physical capacity catalog changed; reload before hydraulic review/export."
            )
        raw = self.plant.export_review(request.plant_review, "json")
        report, _ = verify_report(raw)
        return raw, report

    def review(self, value):
        request = ReviewRequest.model_validate(value)
        raw, plant = self._authority(request)
        role_plan = derive(
            {"profile_sha256": request.profile_sha256, "topology": request.topology.model_dump()}
        )
        roles = {row["id"]: row for row in role_plan["roles"]}
        endpoints = {
            (row["instance_id"], row["node_id"]): row for row in plant["analysis"]["io_schedule"]
        }
        hosts = {row["id"]: row for row in plant["plan"]["hosts"]}
        physical = {row.id: row for row in request.physical_hosts}
        diagnostics, results, demand_roles = [], [], defaultdict(lambda: defaultdict(list))

        def issue(code, message, **details):
            diagnostics.append({"code": code, "message": message, **details})

        if plant["analysis"]["errors"]:
            issue(
                "plant-unresolved",
                "Exact PLANT review has unresolved errors; no declared-subset consistency claim.",
            )
        controller_hosts = set()
        survey_hosts = set()
        for item in request.physical_hosts:
            if item.plant_host_id not in hosts:
                raise ValueError("Physical host references an absent exact PLANT host.")
            if item.kind == "controller":
                if item.plant_host_id in controller_hosts:
                    raise ValueError(
                        "One PLANT host cannot declare its base controller capacity more than once."
                    )
                controller_hosts.add(item.plant_host_id)
                declared = hosts[item.plant_host_id]["declared_model"]
                if declared and declared.strip().upper() != item.model.strip().upper():
                    raise ValueError(
                        "Physical controller model conflicts with its exact PLANT host declaration."
                    )
            else:
                parent = physical.get(item.parent_controller_id)
                if (
                    not parent
                    or parent.kind != "controller"
                    or parent.plant_host_id != item.plant_host_id
                ):
                    raise ValueError(
                        "Module needs an explicit controller parent on the same PLANT host."
                    )
            if item.survey_reference:
                ref = item.survey_reference
                key = (ref.id, ref.host, ref.sa_mac)
                if key in survey_hosts:
                    raise ValueError(
                        "The same exact survey host cannot contribute physical capacity twice."
                    )
                survey_hosts.add(key)
        for binding in request.bindings:
            role = roles.get(binding.role_id)
            if role is None:
                raise ValueError("Binding references a role absent from the selected topology.")
            point = endpoints.get((binding.instance_id, binding.node_id))
            row = {
                **binding.model_dump(),
                "status": "unresolved",
                "point": copy.deepcopy(point),
                "issues": [],
                "network_evidence": [],
            }
            results.append(row)

            def finding(code, row=row, role=role):
                row["issues"].append(code)
                issue(code, "Exact hydraulic role binding is unresolved.", role_id=role["id"])

            if point is None:
                finding("missing-endpoint")
                continue
            if point["direction"] != role["direction"]:
                finding("direction-mismatch")
            if point["value_type"] != role["value_type"]:
                finding("type-mismatch")
            if point["unit"] != role["unit"]:
                finding("unit-mismatch")
            if binding.transport == "physical":
                expected = "sensor" if role["direction"] == "input" else "command"
                if point["role"] != expected:
                    finding("physical-role-mismatch")
                item = physical.get(binding.physical_host_id)
                if item is None or item.plant_host_id != point["host_id"]:
                    finding("physical-host-mismatch")
                if not binding.mode.startswith(role["direction"] + "-"):
                    finding("mode-direction-mismatch")
                if (
                    role["value_type"] == "boolean"
                    and role["direction"] == "input"
                    and binding.mode not in ("input-contact",)
                ):
                    finding("boolean-mode-mismatch")
                if role["value_type"] == "number" and binding.mode in (
                    "input-contact",
                    "input-pulse",
                    "output-triac",
                    "output-fet",
                    "output-relay",
                ):
                    finding("numeric-mode-mismatch")
                if (
                    role["value_type"] == "boolean"
                    and role["direction"] == "output"
                    and binding.mode not in ("output-triac", "output-fet", "output-relay")
                ):
                    finding("boolean-mode-mismatch")
                if not row["issues"]:
                    demand_roles[item.id][binding.mode].append(role["id"])
            else:
                expected = (
                    "network-destination" if role["direction"] == "input" else "network-source"
                )
                if point["role"] != expected:
                    finding("network-role-mismatch")
                direction = "target" if role["direction"] == "input" else "source"
                wanted = {"instance_id": binding.instance_id, "node_id": binding.node_id}
                links = [
                    link
                    for link in plant["analysis"]["network_schedule"]
                    if link[direction] == wanted
                ]
                if {link["id"] for link in links} != set(binding.network_link_ids):
                    finding("network-link-set-mismatch")
                if any(link["status"] != "software_consistent" for link in links):
                    finding("network-link-unresolved")
                row["network_evidence"] = copy.deepcopy(links)
            row["status"] = "exact-declaration-consistent" if not row["issues"] else "unresolved"
        bound = {row.role_id for row in request.bindings}
        for role in role_plan["roles"]:
            if role["id"] not in bound:
                issue(
                    "missing-binding",
                    "Derived hydraulic role has no explicit exact PLANT endpoint binding.",
                    role_id=role["id"],
                )
        used = {row.physical_host_id for row in request.bindings if row.transport == "physical"}
        needed = used | {
            physical[id].parent_controller_id
            for id in used
            if id in physical and physical[id].kind == "module"
        }
        if set(physical) - needed:
            raise ValueError("Unused physical declarations cannot contribute inferred capacity.")
        reviews = []
        for host in sorted(request.physical_hosts, key=lambda x: x.id):
            demands, ownership = [], []
            for mode, ids in sorted(demand_roles[host.id].items()):
                for offset in range(0, len(ids), 64):
                    key = mode + "-" + str(offset // 64 + 1)
                    group = sorted(ids)[offset : offset + 64]
                    demands.append(
                        {
                            "id": key,
                            "label": "Declared hydraulic subset",
                            "mode": mode,
                            "quantity": len(group),
                        }
                    )
                    ownership.append({"demand_id": key, "role_ids": group})
            reviewed = capacity.evaluate(
                {
                    "catalog_sha256": request.capacity_catalog_sha256,
                    "model": host.model,
                    "demands": demands,
                    "survey_reference": host.survey_reference.model_dump()
                    if host.survey_reference
                    else None,
                },
                self.hardware,
            )
            model = reviewed["model_profile"]
            if model and model["kind"] != ("expansion" if host.kind == "module" else "controller"):
                issue(
                    "physical-kind-mismatch",
                    "Exact documented model kind conflicts with declared controller/module ownership.",
                    physical_host_id=host.id,
                )
            if reviewed["status"] not in ("count-mode-fit", "no-demand-declared"):
                issue(
                    "capacity-" + reviewed["status"],
                    "Declared hydraulic subset has shortfall or unknown model; other application occupancy remains unknown.",
                    physical_host_id=host.id,
                )
            reviews.append(
                {
                    "physical_host": host.model_dump(),
                    "role_demands": ownership,
                    "capacity_review": reviewed,
                    "capacity_scope": "declared hydraulic subset only; other application occupancy unknown",
                    "spare_channels_established": False,
                    "whole_application_fit_established": False,
                }
            )
        report = {
            "format": "bms.chilled-hydraulic-io-review/1",
            "profile": copy.deepcopy(PROFILE),
            "request": request.model_dump(),
            "role_plan": role_plan,
            "plant_reference": {
                "review": request.plant_review.model_dump(),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "profile_sha256": plant["profile"]["sha256"],
                "plan_sha256": plant["plan_sha256"],
                "original_review_json": raw.decode("utf-8"),
            },
            "binding_results": sorted(results, key=lambda x: x["role_id"]),
            "capacity_reviews": reviews,
            "diagnostics": diagnostics,
            "status": "unresolved" if diagnostics else "declared-subset-consistent",
            "logical_bindings_complete": len(bound) == len(roles)
            and all(row["status"] == "exact-declaration-consistent" for row in results)
            and not plant["analysis"]["errors"],
            "capacity_scope": "declared hydraulic subset only; other application occupancy unknown",
            "scope": SCOPE,
            "hardware_verified": False,
            "terminal_assignment_verified": False,
            "whole_application_fit_established": False,
            "native_allocation_verified": False,
            "control_program_generated": False,
            "field_queries": False,
            "controller_writes": False,
        }
        report["content_sha256"] = digest(report)
        body = encoded(report) + b"\n"
        if len(body) > MAX_REPORT:
            raise ValueError("Hydraulic review exceeds24MiB; no truncated report retained.")
        with self.lock:
            self.reviews[report["content_sha256"]] = body
            while len(self.reviews) > 8 or sum(map(len, self.reviews.values())) > 48 * 1024 * 1024:
                self.reviews.popitem(last=False)
        return body

    def export(self, key, kind):
        key = ExportKey.model_validate(key)
        with self.lock:
            body = self.reviews.get(key.content_sha256)
        if body is None:
            raise ValueError("Hydraulic review expired; review again before export.")
        report = strict_json(body, MAX_REPORT)
        if (
            report.get("content_sha256") != key.content_sha256
            or digest({k: v for k, v in report.items() if k != "content_sha256"})
            != key.content_sha256
            or encoded(report.get("profile")) != encoded(PROFILE)
        ):
            raise ValueError("Hydraulic retained review seal/profile failed; export refused.")
        request = ReviewRequest.model_validate(report["request"])
        if report["role_plan"] != derive(
            {"profile_sha256": request.profile_sha256, "topology": request.topology.model_dump()}
        ):
            raise ValueError("Hydraulic role plan differs from the bound source choices.")
        original, _ = self._authority(request)
        if hashlib.sha256(original).hexdigest() != report["plant_reference"]["raw_sha256"]:
            raise ValueError("Exact PLANT source changed; hydraulic export refused.")
        for host in request.physical_hosts:
            # Recheck current stored survey authority; return retained original dated bytes.
            capacity.evaluate(
                {
                    "catalog_sha256": request.capacity_catalog_sha256,
                    "model": host.model,
                    "demands": [],
                    "survey_reference": host.survey_reference.model_dump()
                    if host.survey_reference
                    else None,
                },
                self.hardware,
            )
        return body if kind == "json" else csv_report(report)


async def _body(request, model):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_REQUEST:
            raise ValueError("Hydraulic request exceeds512KiB.")
        raw.extend(chunk)
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise ValueError("Hydraulic requests require application/json.")
    try:
        return model.model_validate(strict_json(bytes(raw), MAX_REQUEST))
    except ValidationError as exc:
        raise ValueError(
            "Invalid hydraulic declaration: "
            + json.dumps(exc.errors(include_input=False, include_context=False))[:3000]
        ) from None


def _download(raw, name, kind):
    return Response(
        raw,
        media_type="application/json" if kind == "json" else "text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{name}.{kind}"',
            "X-File-SHA256": hashlib.sha256(raw).hexdigest(),
        },
    )


def hydronic_router(service):
    router = APIRouter(prefix="/api/hydronic-io")

    @router.get("/profile")
    def profile():
        return service.profile()

    @router.post("/derive")
    async def role_plan(request: Request):
        result = await asyncio.to_thread(derive, await _body(request, DeriveRequest))
        return _download(encoded(result) + b"\n", "hydraulic-role-plan", "json")

    @router.post("/derive/csv")
    async def role_csv(request: Request):
        result = await asyncio.to_thread(derive, await _body(request, DeriveRequest))
        return _download(csv_report(result), "hydraulic-role-plan", "csv")

    @router.post("/review")
    async def review(request: Request):
        raw = await asyncio.to_thread(service.review, await _body(request, ReviewRequest))
        return _download(raw, "hydraulic-io-review", "json")

    @router.post("/reviews/export/{kind}")
    async def export(kind: Literal["json", "csv"], request: Request):
        raw = await asyncio.to_thread(service.export, await _body(request, ExportKey), kind)
        return _download(raw, "hydraulic-io-review", kind)

    return router
