"""Read-only supply arithmetic with guarded manufacturer facts and declared loads.

Numeric budgets never establish installed hardware, wiring, common reference,
jumper settings, transient behavior or native controller configuration.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import Field, model_validator

from .models import StrictModel
from .storage import Conflict

FORMAT = "bms.sensor-supply-plan"
VERSION = 1
MAX_BYTES = 2 * 1024 * 1024
MAX_PLANS = 100
MAX_STORAGE = 32 * 1024 * 1024
SCOPE = "Engineering arithmetic only; installed models, wiring, COM, jumpers and startup behavior require separate verification. No controller writes or native configuration."
Number = Annotated[float, Field(ge=0, le=1000000, strict=True, allow_inf_nan=False)]
Voltage = Annotated[float, Field(ge=0.01, le=1000, strict=True, allow_inf_nan=False)]
Name = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^\S(?:[^\x00-\x1f]*\S)?$")]
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:+-]{1,80}$")]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def canonical(value):
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Supply plan requires bounded finite JSON values.") from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class Demand(StrictModel):
    amount: Number | None = None
    unit: Literal["mA", "W", "VA"] = "mA"
    basis: Literal["maximum", "typical", "published-unspecified", "user-estimate", "unknown"] = (
        "unknown"
    )

    @model_validator(mode="after")
    def known(self):
        if (self.amount is None) != (self.basis == "unknown"):
            raise ValueError(
                "Unknown demand requires no amount; a stated amount needs its actual rating basis."
            )
        return self


class LoadDomain(StrictModel):
    min_v: Voltage
    max_v: Voltage
    steady: Demand = Field(default_factory=Demand)
    startup: Demand = Field(default_factory=Demand)

    @model_validator(mode="after")
    def voltage_order(self):
        if self.min_v > self.max_v:
            raise ValueError("Load voltage range must be ordered.")
        return self


class LoadSpec(StrictModel):
    ac: LoadDomain | None = None
    dc: LoadDomain | None = None

    @model_validator(mode="after")
    def one_domain(self):
        if self.ac is None and self.dc is None:
            raise ValueError("A load requires an explicit AC or DC voltage specification.")
        return self


class Terminal(StrictModel):
    id: Key
    current_limit_ma: Number | None = None


class RailSpec(StrictModel):
    domain: Literal["ac", "dc"]
    nominal_v: Voltage
    current_limit_ma: Number | None = None
    source_output: bool = Field(default=True, strict=True)
    terminals: list[Terminal] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_terminals(self):
        if len({row.id for row in self.terminals}) != len(self.terminals):
            raise ValueError("Rail terminal identifiers must be unique.")
        return self


class Rail(StrictModel):
    id: Key
    name: Name
    unit_id: Name
    profile_id: str | None = Field(default=None, max_length=100)
    profile_sha256: Hash | None = None
    spec: RailSpec
    operating_min_v: Voltage | None = None
    operating_max_v: Voltage | None = None
    loads_complete: bool = Field(default=False, strict=True)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def declared_envelope(self):
        if (self.operating_min_v is None) != (self.operating_max_v is None):
            raise ValueError("Declare both operating voltage bounds or leave both unknown.")
        if (
            self.operating_min_v is not None
            and not self.operating_min_v <= self.spec.nominal_v <= self.operating_max_v
        ):
            raise ValueError("Declared rail range must include its nominal voltage.")
        if self.profile_id is None and self.profile_sha256 is not None:
            raise ValueError("User-declared rails cannot claim a manufacturer profile hash.")
        return self


class Load(StrictModel):
    id: Key
    name: Name
    rail_id: Key
    terminal_id: Key
    quantity: int = Field(default=1, ge=1, le=100, strict=True)
    profile_id: str | None = Field(default=None, max_length=100)
    profile_sha256: Hash | None = None
    spec: LoadSpec
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def no_fake_profile(self):
        if self.profile_id is None and self.profile_sha256 is not None:
            raise ValueError("User-declared loads cannot claim a manufacturer profile hash.")
        return self


class ReportReference(StrictModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    content_sha256: Hash


class SupplyPlan(StrictModel):
    format: Literal["bms.sensor-supply-plan"] = FORMAT
    version: Literal[1] = VERSION
    catalog_sha256: Hash
    name: Name
    source_report: ReportReference | None = None
    rails: list[Rail] = Field(default_factory=list, max_length=32)
    loads: list[Load] = Field(default_factory=list, max_length=256)

    @model_validator(mode="before")
    @classmethod
    def exact_version(cls, value):
        if isinstance(value, dict) and (
            type(value.get("version")) is not int or value.get("format") != FORMAT
        ):
            raise ValueError("Supply plan requires explicit format and integer version 1.")
        return value

    @model_validator(mode="after")
    def connections(self):
        if len({row.id for row in self.rails}) != len(self.rails) or len(
            {row.id for row in self.loads}
        ) != len(self.loads):
            raise ValueError("Rail and load identifiers must be unique within their category.")
        if len({row.unit_id.casefold() for row in self.rails}) != len(self.rails):
            raise ValueError(
                "One physical supply instance can appear only once; put shared terminals on the same rail."
            )
        rails = {row.id: row for row in self.rails}
        for load in self.loads:
            rail = rails.get(load.rail_id)
            if rail is None or load.terminal_id not in {
                terminal.id for terminal in rail.spec.terminals
            }:
                raise ValueError("Every load must select an existing rail and exact terminal.")
        return self


# Bibliographic facts only; proprietary manuals and source extracts stay outside the repository.
BASE = "https://docs.johnsoncontrols.com/bas/r/"
CAPTURE = "0f0712d5892751b2b75a47a7783a46793390394db91e79faf3dc00a17e42d2b7"
SOURCES = {
    "pcg26": {
        "document": "24-10143-160",
        "revision": "G",
        "date": "2024-01-05",
        "section": "PDF page 13, universal +15 V supply",
        "artifact": "publisher PDF",
        "sha256": "ec118dc20634d756b1a47af9699445b659d54abe8d824fae90bd54676c51ec4a",
        "url": BASE
        + "Facility-Explorer/en-US/FX-PCG26-General-Purpose-Programmable-Controller-Installation-Guide/G/Terminal-wiring-guidelines-functions-ratings-and-requirements/Input/Output-Terminal-Blocks-ratings-and-requirements",
    },
    "pcv16": {
        "document": "24-10143-357",
        "revision": "H",
        "date": "2019-03-22",
        "section": "PDF page 14, universal +15 V supply",
        "artifact": "publisher PDF",
        "sha256": "0247275ca05080ab30ff5ee10e046f3d4877e2629ca0079262e9e0f610addd36",
        "url": BASE
        + "Facility-Explorer/en-US/FX-PCV1615/1626/1628/1630-Programmable-VAV-Box-Controllers-Installation-Instructions/H/Input-and-Output-wiring-guidelines-tables",
    },
    "vma16": {
        "document": "24-10143-217",
        "revision": "K",
        "date": "2019-10-18",
        "section": "PDF page 8, universal +15 V supply",
        "artifact": "publisher PDF",
        "sha256": "789139c207dd93409c8b17fe6645772ed1365a4912ed1e5589d1db0a38f2c5ca",
        "url": BASE
        + "Metasys/en-US/VMA1615/1626/1628/1630-VAV-Controllers-Installation-Guide/K/Terminal-wiring-guidelines-functions-ratings-and-requirements/Input-and-Output-wiring-guidelines-tables",
    },
    "pcx3711": {
        "document": "24-10144-114",
        "revision": "G",
        "date": "2019-03-22",
        "section": "I/O wiring ratings and requirements table",
        "artifact": "publisher text extraction capture, 2026-10-21; not PDF bytes",
        "sha256": CAPTURE,
        "url": BASE
        + "Facility-Explorer/en-US/FX-PCX37-Expansion-Input/Output-Module-Installation-Instructions/G/I/O-wiring-ratings-and-requirements-table",
    },
    "pcx3721": {
        "document": "24-10144-203",
        "revision": "F",
        "date": "2019-03-22",
        "section": "Communications bus and supply power terminal blocks",
        "artifact": "publisher text extraction capture, 2026-10-21; not PDF bytes",
        "sha256": CAPTURE,
        "url": BASE
        + "Facility-Explorer/en-US/FX-PCX3721-Expansion-Input/Output-Module-Installation-Instructions/F/Cable-and-wire-length-guidelines/Communications-bus-and-supply-power-terminal-blocks-ratings-and-requirements",
    },
    "belimo": {
        "document": "22UTH-510X technical data sheet",
        "revision": "en-us",
        "date": "2026-08-26",
        "section": "Page 1, electrical data",
        "artifact": "primary publisher PDF text extraction capture, 2026-10-21; not PDF bytes",
        "sha256": CAPTURE,
        "url": "https://www.belimo.com/mam/general-documents/datasheets/en-us/belimo_22UTH-510X_datasheet_en-us.pdf",
    },
}


def _catalog():
    rails = []
    for model, source, limit in [
        ("FX-PCG2611-0", "pcg26", 100),
        ("FX-PCG2621-0", "pcg26", 100),
        ("FX-PCX3711-0", "pcx3711", 100),
        ("FX-PCV1615-0", "pcv16", 35),
        ("FX-PCV1630-0", "pcv16", 35),
        ("MS-VMA1615-0", "vma16", 35),
        ("MS-VMA1630-0", "vma16", 35),
    ]:
        rails.append(
            {
                "id": model + ":universal-15v",
                "name": model + " universal +15 V",
                "model": model,
                "source": SOURCES[source],
                "scope": "Shared total for active-input sensor supply. No independent per-terminal rating or rail voltage tolerance is established; SA/FC power and external 24 VAC are separate.",
                "spec": RailSpec(
                    domain="dc",
                    nominal_v=15.0,
                    current_limit_ma=float(limit),
                    terminals=[Terminal(id="+15V")],
                ).model_dump(),
            }
        )
    rails.append(
        {
            "id": "FX-PCX3721-0:sa-pwr-pass-through",
            "name": "FX-PCX3721-0 SA PWR (not a source)",
            "model": "FX-PCX3721-0",
            "source": SOURCES["pcx3721"],
            "scope": "SA PWR is a lead connection supplied by the SA bus supervisor, not a local 15 V source.",
            "spec": RailSpec(
                domain="dc", nominal_v=15.0, source_output=False, terminals=[Terminal(id="SA-PWR")]
            ).model_dump(),
        }
    )
    spec = LoadSpec(
        ac=LoadDomain(
            min_v=21.6,
            max_v=26.4,
            steady=Demand(amount=0.8, unit="VA", basis="published-unspecified"),
        ),
        dc=LoadDomain(
            min_v=13.5,
            max_v=26.4,
            steady=Demand(amount=0.4, unit="W", basis="published-unspecified"),
        ),
    ).model_dump()
    loads = [
        {
            "id": "Belimo:22UTH-510X:2026-08-26",
            "name": "Belimo 22UTH-510X combined humidity/temperature sensor",
            "model": "22UTH-510X",
            "source": SOURCES["belimo"],
            "scope": "One powered sensor with two signal outputs. Published consumption is not explicitly identified as maximum or startup demand; no inrush is stated.",
            "spec": spec,
        }
    ]
    for row in rails + loads:
        row["profile_sha256"] = digest(row)
    result = {"profile": "sensor-supply-catalog/1", "rails": rails, "loads": loads}
    result["sha256"] = digest(result)
    return result


CATALOG = _catalog()


def catalog():
    return copy.deepcopy(CATALOG)


def template():
    return SupplyPlan(
        format=FORMAT, catalog_sha256=CATALOG["sha256"], name="New supply budget", version=1
    ).model_dump()


def _profile(record, kind):
    if record.profile_id is None:
        return {"kind": "user-declared", "documented_in_manufacturer_source": False}
    source = next((row for row in CATALOG[kind] if row["id"] == record.profile_id), None)
    if (
        source is None
        or record.profile_sha256 != source["profile_sha256"]
        or canonical(record.spec.model_dump()) != canonical(source["spec"])
    ):
        raise ValueError(
            "Supply profile identifier, exact source hash or guarded specification changed."
        )
    return {
        "kind": "documented-profile",
        "documented_in_manufacturer_source": True,
        "installed_verified": False,
        "model": source["model"],
        "profile_sha256": source["profile_sha256"],
        "source": copy.deepcopy(source["source"]),
        "scope": source["scope"],
    }


def validate_plan(value, hardware=None):
    if len(canonical(value)) > MAX_BYTES:
        raise ValueError("Supply plan exceeds 2 MiB.")
    plan = SupplyPlan.model_validate(value)
    if plan.catalog_sha256 != CATALOG["sha256"]:
        raise ValueError(
            "Supply catalog source hash changed; review and rebind profiles explicitly."
        )
    for rail in plan.rails:
        _profile(rail, "rails")
    for load in plan.loads:
        _profile(load, "loads")
    if plan.source_report is not None:
        if (
            hardware is None
            or hardware.report(plan.source_report.id).get("content_sha256")
            != plan.source_report.content_sha256
        ):
            raise ValueError("Supply plan source survey hash does not match the saved report.")
    return plan


def _current(demand, rail):
    if demand.amount is None:
        return {
            "ma": None,
            "maximum_known": False,
            "basis": demand.basis,
            "method": "unknown demand",
        }
    voltage = rail.operating_min_v or rail.spec.nominal_v
    if demand.unit == "mA":
        amount, method, voltage_known = demand.amount, "explicit current", True
    elif demand.unit == "W" and rail.spec.domain == "dc":
        amount, method, voltage_known = (
            demand.amount / voltage * 1000,
            "DC watts / lowest declared voltage; nominal estimate if range unknown",
            rail.operating_min_v is not None,
        )
    elif demand.unit == "VA" and rail.spec.domain == "ac":
        amount, method, voltage_known = (
            demand.amount / voltage * 1000,
            "AC volt-amperes / lowest declared RMS voltage; nominal estimate if range unknown",
            rail.operating_min_v is not None,
        )
    else:
        return {
            "ma": None,
            "maximum_known": False,
            "basis": demand.basis,
            "method": "AC watts need power factor; mismatched W/VA domains are not converted",
        }
    return {
        "ma": amount,
        "maximum_known": demand.basis == "maximum" and voltage_known,
        "basis": demand.basis,
        "method": method,
    }


def evaluate(plan, hardware=None):
    plan = validate_plan(plan, hardware)
    rows = []
    for rail in plan.rails:
        issues, load_rows = [], []
        if not rail.spec.source_output:
            issues.append("This terminal is not a power source.")
        if not rail.loads_complete:
            issues.append("All existing/planned loads have not been declared included.")
        if rail.operating_min_v is None:
            issues.append(
                "Rail operating-voltage tolerance is unknown; nominal voltage is not a guaranteed envelope."
            )
        loads = [load for load in plan.loads if load.rail_id == rail.id]
        incompatible = not rail.spec.source_output
        for load in loads:
            spec = getattr(load.spec, rail.spec.domain)
            voltage_status = "incompatible"
            if spec is not None:
                low, high = rail.operating_min_v, rail.operating_max_v
                if low is not None:
                    voltage_status = (
                        "compatible" if spec.min_v <= low <= high <= spec.max_v else "incompatible"
                    )
                else:
                    voltage_status = (
                        "unknown-envelope"
                        if spec.min_v <= rail.spec.nominal_v <= spec.max_v
                        else "incompatible"
                    )
            incompatible |= voltage_status == "incompatible"
            steady = (
                _current(spec.steady, rail)
                if spec
                else {
                    "ma": None,
                    "maximum_known": False,
                    "method": "Unsupported supply domain",
                    "basis": "unknown",
                }
            )
            startup = _current(spec.startup, rail) if spec else copy.deepcopy(steady)
            for sample in (steady, startup):
                if sample["ma"] is not None:
                    sample["ma"] *= load.quantity
            load_rows.append(
                {
                    "id": load.id,
                    "name": load.name,
                    "quantity": load.quantity,
                    "terminal_id": load.terminal_id,
                    "spec": load.spec.model_dump(),
                    "notes": load.notes,
                    "voltage_status": voltage_status,
                    "steady": steady,
                    "startup": startup,
                    "provenance": _profile(load, "loads"),
                }
            )
        if not loads:
            issues.append("No loads are assigned to this rail.")
        budgets = []
        for terminal in [None, *rail.spec.terminals]:
            selected = (
                load_rows
                if terminal is None
                else [row for row in load_rows if row["terminal_id"] == terminal.id]
            )
            limit = rail.spec.current_limit_ma if terminal is None else terminal.current_limit_ma
            phases = {}
            for phase in ("steady", "startup"):
                total = math.fsum(
                    row[phase]["ma"] for row in selected if row[phase]["ma"] is not None
                )
                all_max = all(row[phase]["maximum_known"] for row in selected)
                status = (
                    "exceeded"
                    if limit is not None and total > limit
                    else "unknown-limit"
                    if limit is None
                    else "within-maximum"
                    if all_max
                    else "estimated-or-unknown-demand"
                )
                phases[phase] = {
                    "known_total_ma": total,
                    "limit_ma": limit,
                    "remaining_from_known_ma": None if limit is None else limit - total,
                    "all_maximum_demands_known": all_max,
                    "unknown_loads": sum(
                        row["quantity"] for row in selected if row[phase]["ma"] is None
                    ),
                    "maximum_unknown_loads": sum(
                        row["quantity"] for row in selected if not row[phase]["maximum_known"]
                    ),
                    "status": status,
                }
            budgets.append(
                {
                    "scope": "shared-total" if terminal is None else "terminal",
                    "terminal_id": None if terminal is None else terminal.id,
                    "phases": phases,
                }
            )
        exceeded = any(
            phase["status"] == "exceeded"
            for budget in budgets
            for phase in budget["phases"].values()
        )
        total = budgets[0]["phases"]
        complete = (
            bool(loads)
            and rail.loads_complete
            and rail.operating_min_v is not None
            and all(value["status"] == "within-maximum" for value in total.values())
            and all(row["voltage_status"] == "compatible" for row in load_rows)
        )
        if any(
            not row[phase]["maximum_known"] for row in load_rows for phase in ("steady", "startup")
        ):
            issues.append(
                "Maximum steady/startup current is not established for every load; typical or published consumption remains an estimate."
            )
        status = (
            "incompatible"
            if incompatible
            else "over-budget"
            if exceeded
            else "within-declared-limits"
            if complete
            else "incomplete"
        )
        rows.append(
            {
                "id": rail.id,
                "name": rail.name,
                "unit_id": rail.unit_id,
                "spec": rail.spec.model_dump(),
                "notes": rail.notes,
                "domain": rail.spec.domain,
                "nominal_v": rail.spec.nominal_v,
                "operating_range": {
                    "min_v": rail.operating_min_v,
                    "max_v": rail.operating_max_v,
                    "basis": "user-declared" if rail.operating_min_v is not None else "unknown",
                },
                "loads_complete_declaration": rail.loads_complete,
                "status": status,
                "issues": issues,
                "loads": load_rows,
                "budgets": budgets,
                "provenance": _profile(rail, "rails"),
                "terminal_scope": "Only explicitly stated per-terminal limits are checked; absent limits are not separate ratings.",
                "startup_scope": "Compares startup to the same continuous ceiling; no transient allowance is assumed.",
            }
        )
    states = {row["status"] for row in rows}
    status = (
        "incompatible"
        if "incompatible" in states
        else "over-budget"
        if "over-budget" in states
        else "within-declared-limits"
        if states == {"within-declared-limits"}
        else "incomplete"
    )
    return {
        "format": "bms.sensor-supply-report",
        "version": 1,
        "plan_sha256": digest(plan.model_dump()),
        "catalog_sha256": CATALOG["sha256"],
        "source_report": plan.source_report.model_dump() if plan.source_report else None,
        "status": status,
        "scope": SCOPE,
        "rails": rows,
        "controller_writes": False,
        "wiring_verified": False,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }


class PlanSave(StrictModel):
    plan: dict
    id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    expected_revision: int = Field(ge=0, strict=True)


class PlanBody(StrictModel):
    plan: dict


class PlanDelete(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)


class SupplyPlans:
    def __init__(self, store, hardware):
        self.store, self.hardware = store, hardware
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS sensor_supply_plans(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, content BLOB NOT NULL, sha256 TEXT NOT NULL)"
            )

    @staticmethod
    def _id(key):
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key):
            raise ValueError("Invalid saved supply plan identifier.")

    def _read(self, row):
        if row is None:
            raise ValueError("Saved supply plan not found.")
        data = row["content"]
        if (
            not isinstance(data, bytes)
            or len(data) > MAX_BYTES
            or hashlib.sha256(data).hexdigest() != row["sha256"]
        ):
            raise ValueError("Saved supply plan failed its content integrity guard.")
        try:
            plan = json.loads(data)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError("Saved supply plan contains invalid JSON.") from exc
        validate_plan(plan, self.hardware)
        return {key: row[key] for key in ("id", "revision", "created", "updated")} | {
            "plan": plan,
            "content_sha256": row["sha256"],
        }

    def list(self):
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM sensor_supply_plans ORDER BY updated DESC,id"
            ).fetchall()
        result = []
        for row in rows:
            metadata = {key: row[key] for key in ("id", "revision", "updated")}
            try:
                item = self._read(row)
                result.append(metadata | {"name": item["plan"]["name"], "available": True})
            except ValueError as exc:
                result.append(
                    metadata
                    | {"name": "Unavailable saved plan", "available": False, "error": str(exc)}
                )
        return result

    def load(self, key):
        self._id(key)
        with self.store.connect() as db:
            return self._read(
                db.execute("SELECT * FROM sensor_supply_plans WHERE id=?", (key,)).fetchone()
            )

    def save(self, body):
        plan = validate_plan(body.plan, self.hardware).model_dump()
        key = body.id or uuid.uuid4().hex
        self._id(key)
        data, stamp = canonical(plan), datetime.now(UTC).isoformat()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM sensor_supply_plans WHERE id=?", (key,)).fetchone()
            revision = prior["revision"] if prior else 0
            if body.expected_revision != revision:
                raise Conflict("Supply plan revision changed; reopen before saving.")
            usage = db.execute(
                "SELECT COUNT(*) AS n,COALESCE(SUM(length(content)),0) AS bytes FROM sensor_supply_plans"
            ).fetchone()
            if (not prior and usage["n"] >= MAX_PLANS) or usage["bytes"] - (
                len(prior["content"]) if prior else 0
            ) + len(data) > MAX_STORAGE:
                raise ValueError(
                    "Supply plan storage capacity reached; delete an unused saved plan."
                )
            db.execute(
                "INSERT OR REPLACE INTO sensor_supply_plans VALUES(?,?,?,?,?,?)",
                (
                    key,
                    revision + 1,
                    prior["created"] if prior else stamp,
                    stamp,
                    data,
                    hashlib.sha256(data).hexdigest(),
                ),
            )
        self.store.record(
            "sensor-supply.save",
            {
                "id": key,
                "revision": revision + 1,
                "content_sha256": hashlib.sha256(data).hexdigest(),
            },
        )
        return self.load(key)

    def delete(self, key, expected_revision):
        self._id(key)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM sensor_supply_plans WHERE id=?", (key,)).fetchone()
            if prior is None:
                raise ValueError("Saved supply plan not found.")
            if type(expected_revision) is not int or prior["revision"] != expected_revision:
                raise Conflict("Supply plan revision changed; reopen before deleting.")
            db.execute("DELETE FROM sensor_supply_plans WHERE id=?", (key,))
        self.store.record("sensor-supply.delete", {"id": key})
        return {"deleted": key}


def supply_router(service):
    router = APIRouter(prefix="/api/sensor-supply")

    @router.get("/catalog")
    def get_catalog():
        return {"catalog": catalog(), "template": template(), "scope": SCOPE}

    @router.get("/plans")
    def plans():
        return service.list()

    @router.post("/validate")
    def validate(body: PlanBody):
        return {"plan": validate_plan(body.plan, service.hardware).model_dump()}

    @router.post("/evaluate")
    def calculation(body: PlanBody):
        return evaluate(body.plan, service.hardware)

    @router.post("/save")
    def save(body: PlanSave):
        return service.save(body)

    @router.get("/plans/{key}")
    def reopen(key: str):
        return service.load(key)

    @router.delete("/plans/{key}")
    def delete(key: str, body: PlanDelete):
        return service.delete(key, body.expected_revision)

    return router
