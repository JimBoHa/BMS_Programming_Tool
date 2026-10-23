"""Source-bound offline physical point counts, never terminal/native allocation.

Each UI/UO/CO is one physical resource with alternative modes. Model suffixes,
source conflicts and undocumented terminal numbering remain explicit.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import deque
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import Field, model_validator

from .models import StrictModel

FORMAT = "bms.jci-physical-capacity-review/1"
SCOPE = (
    "Offline documented counts and signal-family fit only. No terminal assignment, "
    "spare/wiring determination, load/power/frequency approval, native CAF allocation, "
    "firmware acceptance, field queries or controller writes."
)
BASE = "https://docs.johnsoncontrols.com/bas/r/"
SOURCES = {
    "fx-2024": {
        "document": "LIT-12011657",
        "revision": "2024-03-07",
        "date": "2024-03-07",
        "sections": "PDF 8 Table 2; 10–11 Table 5; 14–15 Tables 7/9/10; 24 Table 15",
        "artifact": "publisher PDF bytes",
        "sha256": "733063dc209b19212100a4957e3e7c05e00484b31b4886f8aeb5d4b65e2fa8af",
        "url": BASE
        + "Facility-Explorer/en-US/FX-PC-Series-Programmable-Controllers-and-Related-Products-Product-Bulletin",
    },
    "metasys-13": {
        "document": "LIT-12011042",
        "revision": "13.0",
        "date": "2023-09-06",
        "sections": "PDF 11–12 Table 5; 18–19 Table 13",
        "artifact": "publisher PDF bytes",
        "sha256": "3a65a6ffe84c8e453d814af07470638fd7a1b12965df52e859580a276d2386a3",
        "url": BASE
        + "Metasys/en-US/Metasys-System-Field-Equipment-Controllers-and-Related-Products-Product-Bulletin/13.0",
    },
    "pcv-h": {
        "document": "24-10143-357",
        "revision": "H",
        "date": "2019-03-22",
        "sections": "PDF 6 terminal functions; 27 Table 10 (family -x counts); publisher model applicability includes legacy -0",
        "artifact": "publisher PDF bytes",
        "sha256": "0247275ca05080ab30ff5ee10e046f3d4877e2629ca0079262e9e0f610addd36",
        "url": BASE
        + "Facility-Explorer/en-US/FX-PCV1615/1626/1628/1630-Programmable-VAV-Box-Controllers-Installation-Instructions/H",
    },
    "vma-k": {
        "document": "24-10143-217",
        "revision": "K",
        "date": "2019-10-18",
        "sections": "PDF 2 terminal functions; 19 Table 10 (family -x counts), restricted here to existing legacy -0 profiles",
        "artifact": "publisher PDF bytes",
        "sha256": "789139c207dd93409c8b17fe6645772ed1365a4912ed1e5589d1db0a38f2c5ca",
        "url": BASE + "Metasys/en-US/VMA1615/1626/1628/1630-VAV-Controllers-Installation-Guide/K",
    },
    "pcx37-binary": {
        "document": "24-10144-203 and 24-10144-181",
        "revision": "F / E",
        "date": "2019-03-22",
        "sections": "PCX3721 I/O terminal requirements; PCX3731 I/O wiring, technical specifications and source-power jumpers",
        "artifact": "publisher text-extraction capture 2026-10-22; not PDF bytes",
        "sha256": "245ce0d4bf66e1e26ad2e785d15cf912aead09d4bbb9903ae280bf46b9bfe9e3",
        "url": BASE
        + "Facility-Explorer/en-US/FX-PCX3721-Expansion-Input/Output-Module-Installation-Instructions/F/Wiring/Terminal-wiring-guidelines-functions-ratings-and-requirements/I/O-terminal-blocks-ratings-and-requirements",
        "supporting_urls": [
            BASE
            + "Facility-Explorer/en-US/FX-PCX3731-Input/Output-Module-Installation-Instructions/E/I/O-wiring-ratings-and-requirements",
            BASE
            + "Facility-Explorer/en-US/FX-PCX3731-Input/Output-Module-Installation-Instructions/E/Technical-specifications",
            BASE
            + "Facility-Explorer/en-US/FX-PCX3731-Input/Output-Module-Installation-Instructions/E/Setup-and-adjustments/Binary-Output-BO-source-power-selection-jumpers",
        ],
    },
    "pcx-installation": {
        "document": "24-10144-106 and 24-10144-114",
        "revision": "G",
        "date": "2019-03-22",
        "sections": "PCX17/27 wiring ratings; PCX37 I/O wiring ratings (UO modes, relay contacts, pulse requirements)",
        "artifact": "publisher text-extraction capture 2026-10-22; not PDF bytes",
        "sha256": "acedaece5e47a9fc812bd090c5ddfd300997f3e73afeb35f55a11c720819329c",
        "url": BASE
        + "Facility-Explorer/en-US/FX-PCX37-Expansion-Input/Output-Module-Installation-Instructions/G/I/O-wiring-ratings-and-requirements-table",
        "supporting_urls": [
            BASE
            + "Facility-Explorer/en-US/FX-PCX17-and-FX-PCX27-Expansion-Input/Output-Module-Installation-Instructions/G/Terminal-wiring-guidelines-functions-ratings-and-requirements/Wiring-ratings-and-requirements-table"
        ],
    },
}
MODE_LABELS = {
    "input-voltage": "Input voltage 0–10 VDC",
    "input-current": "Input current 4–20 mA",
    "input-resistance": "Resistive input (curve/range not reviewed)",
    "input-contact": "Maintained dry-contact input",
    "input-pulse": "Pulse-counter input (frequency/duty not reviewed)",
    "output-voltage": "Output voltage 0–10 VDC",
    "output-current": "Output current 4–20 mA",
    "output-triac": "24 VAC triac output (load not reviewed)",
    "output-fet": "24 VAC/DC FET output (load not reviewed)",
    "output-relay": "Relay output (contact/load rating not reviewed)",
}
POOL_MODES = {
    "UI": ["input-voltage", "input-current", "input-resistance", "input-contact"],
    "BI": ["input-contact", "input-pulse"],
    "AO": ["output-voltage", "output-current"],
    "BO": ["output-triac"],
    "UO": ["output-voltage", "output-current", "output-fet"],
    "CO": ["output-voltage", "output-triac"],
    "RO": ["output-relay"],
}


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _profile(model, counts, source, pages, *, vav=False, conflicts=(), notes=()):
    pools = []
    for kind, count in counts.items():
        modes = list(POOL_MODES[kind])
        if vav and kind == "UI":
            modes.remove("input-current")
        pools.append(
            {
                "id": kind,
                "count": count,
                "modes": modes,
                "shared_alternative_modes": len(modes) > 1,
                "terminal_identifiers": None,
                "numbering_status": "not-established-by-this-count-profile",
            }
        )
    return {
        "model": model,
        "kind": "controller" if "PCG" in model or vav else "expansion",
        "pools": pools,
        "external_point_count": sum(counts.values()),
        "source_ids": [source]
        + (
            ["pcx-installation"]
            if any(model.startswith("FX-PCX" + n + "-") for n in ["1711", "2711", "3711"])
            else ["pcx37-binary"]
            if any(model.startswith("FX-PCX" + n + "-") for n in ["3721", "3731"])
            else []
        ),
        "count_sections": pages,
        "conflicts": list(conflicts),
        "notes": list(notes),
        "onboard_features": ["integrated differential-pressure transducer", "integrated actuator"]
        if vav
        else [],
        "bus_families": ["FC", "SA"],
        "bus_scope": "Documented physical bus families only; topology, addressing, host compatibility and power are not evaluated.",
        "terminal_numbering_verified": False,
        "installed_verified": False,
        "electrical_compatibility_verified": False,
        "native_allocation_verified": False,
    }


def _models():
    rows = []
    expansion_counts = {
        "1711": {"BI": 4},
        "2711": {"UI": 2, "UO": 2, "RO": 2},
        "2721": {"UI": 8, "AO": 2},
        "2723": {"UI": 8, "AO": 2},
        "3711": {"UI": 4, "UO": 4, "RO": 4},
        "3721": {"BI": 16},
        "3723": {"BI": 16},
        "3731": {"BI": 8, "BO": 8},
        "3733": {"BI": 8, "BO": 8},
        "4711": {"UI": 6, "BI": 2, "AO": 2, "BO": 3, "CO": 4},
    }
    for brand, family, source in [("FX", "PCX", "fx-2024"), ("MS", "IOM", "metasys-13")]:
        for number, counts in expansion_counts.items():
            regional = number in {"2723", "3723", "3733"}
            prefix = "CH" if brand == "FX" and regional else brand
            for suffix in ["0", "2"] if number in {"2711", "3711"} else ["0"]:
                conflicts, notes = [], []
                if number in {"2711", "3711"}:
                    conflicts.append(
                        {
                            "code": "relay-label-conflict",
                            "scope": "abbreviated output naming",
                            "meaning": "Ordering/technical descriptions call relay outputs BO; detailed point-type matrix separates UO and RO. Counts retain these physical pools, not extra BOs.",
                        }
                    )
                    notes.append(
                        "Relay NO/NC/COM contacts belong to one relay; they are not additional physical outputs."
                    )
                if brand == "FX" and suffix == "2":
                    conflicts.append(
                        {
                            "code": "relay-voltage-conflict",
                            "scope": "electrical rating",
                            "meaning": "LIT-12011657 Table 5 states 24 VAC for -2 relays; ordering Table 9 states 240 VAC. No rating is chosen or approved.",
                        }
                    )
                if brand == "FX" and number in {"1711", "3721", "3731"}:
                    conflicts.append(
                        {
                            "code": "pulse-frequency-conflict",
                            "scope": "pulse frequency",
                            "meaning": "Generic bulletin lists 100 Hz; reviewed installation wiring lists 50 Hz with duty/timing requirements. This profile does not approve either pulse rate.",
                        }
                    )
                if brand == "FX" and number == "3731":
                    conflicts.append(
                        {
                            "code": "binary-output-source-conflict",
                            "scope": "output power source",
                            "meaning": "PCX3731 technical specifications state external source power only; the same installation guide's wiring/jumper sections describe internal/external selection. Exact variant/source settings require separate verification; no power mode is approved.",
                        }
                    )
                if regional:
                    notes.append(
                        "Region-specific product; availability is not established by this catalog."
                    )
                if number == "3733":
                    notes.append(
                        "BOs require an external low-voltage (<30 VAC) source; this profile does not size or approve that source."
                    )
                rows.append(
                    _profile(
                        f"{prefix}-{family}{number}-{suffix}",
                        counts,
                        source,
                        "PDF 10–11 Table 5; 15 Tables 9/10"
                        if brand == "FX"
                        else "PDF 11–12 Table 5; 18–19 Table 13",
                        conflicts=conflicts,
                        notes=notes,
                    )
                )
    for model in ["FX-PCG1611-1", "FX-PCG1621-1", "FX-PCG2611-0", "FX-PCG2621-0"]:
        counts = (
            {"UI": 2, "BI": 1, "BO": 3, "CO": 4}
            if "16" in model
            else {"UI": 6, "BI": 2, "AO": 2, "BO": 3, "CO": 4}
        )
        rows.append(_profile(model, counts, "fx-2024", "PDF 8 Table 2; 14 Table 7"))
    for prefix, family, source in [("FX", "PCV", "pcv-h"), ("MS", "VMA", "vma-k")]:
        for number in ["1615", "1630"]:
            counts = {"UI": 3, "BO": 2} if number == "1615" else {"UI": 3, "BO": 3, "CO": 2}
            rows.append(
                _profile(
                    f"{prefix}-{family}{number}-0",
                    counts,
                    source,
                    "Family -x technical table; selected legacy -0 applicability only",
                    vav=True,
                    notes=[
                        "Family technical table supplies counts. Only selected legacy -0 profiles are included; other suffixes require separate review.",
                        "Integrated pressure sensing and actuator are not spare external I/O channels.",
                    ],
                )
            )
    return sorted(rows, key=lambda row: row["model"])


CATALOG = {
    "profile": "jci-physical-counts/1",
    "sources": SOURCES,
    "modes": MODE_LABELS,
    "models": _models(),
    "scope": SCOPE,
    "limits": {"demand_rows": 32, "quantity_per_row": 64, "total_demand": 1024},
    "mode_scope": "Only signal families explicitly listed in these reviewed tables are matched. An unlisted mode is unreviewed here, not proof of physical impossibility.",
    "matching": "Exact catalog model after outer whitespace/case normalization only; no prefix/suffix/brand inference.",
}
CATALOG["catalog_sha256"] = digest(CATALOG)
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:+-]{1,80}$")]
Mode = Literal[
    "input-voltage",
    "input-current",
    "input-resistance",
    "input-contact",
    "input-pulse",
    "output-voltage",
    "output-current",
    "output-triac",
    "output-fet",
    "output-relay",
]


class Demand(StrictModel):
    id: Key
    label: str = Field(default="", max_length=120, pattern=r"^[^\x00-\x1f\x7f-\x9f]*$")
    mode: Mode
    quantity: int = Field(ge=1, le=64, strict=True)


class SurveyReference(StrictModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    content_sha256: Hash
    host: Literal["base", "sa"]
    sa_mac: int | None = Field(default=None, ge=1, le=254, strict=True)

    @model_validator(mode="after")
    def exact_host(self):
        if (self.host == "sa") != (self.sa_mac is not None):
            raise ValueError(
                "An SA reference needs its exact MAC; base references cannot include one."
            )
        return self


class CapacityRequest(StrictModel):
    catalog_sha256: Hash
    model: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f-\x9f]+$")
    demands: list[Demand] = Field(default_factory=list, max_length=32)
    survey_reference: SurveyReference | None = None

    @model_validator(mode="after")
    def bounded_demands(self):
        if len({row.id for row in self.demands}) != len(self.demands):
            raise ValueError("Demand row identities must be unique.")
        if sum(row.quantity for row in self.demands) > 1024:
            raise ValueError("Total demand exceeds 1024 declared channels.")
        return self


def catalog():
    return copy.deepcopy(CATALOG)


def _survey_binding(reference, model, hardware):
    if reference is None:
        return None
    if hardware is None:
        raise ValueError("Stored hardware survey is unavailable.")
    report = hardware.report(reference.id)
    if report.get("content_sha256") != reference.content_sha256:
        raise ValueError("Hardware survey hash changed; choose the current source explicitly.")
    if reference.host == "base":
        observed = report.get("identity", {}).get("model")
        basis = "survey Device model evidence"
    else:
        matches = [
            row
            for row in report.get("modules", [])
            if row.get("sa_mac") == reference.sa_mac and row.get("host") == "sa"
        ]
        if len(matches) != 1:
            raise ValueError("Survey does not contain one unambiguous module at that SA MAC.")
        observed = matches[0].get("configured_model")
        basis = "survey configured module evidence; physical module identity unverified"
    if not isinstance(observed, str) or observed.strip().upper() != model:
        raise ValueError("Exact selected model does not match the chosen survey host evidence.")
    return {
        "reference": reference.model_dump(),
        "model_evidence": observed,
        "basis": basis,
        "target": copy.deepcopy(report.get("target")),
        "imported": report.get("imported", False),
        "physical_identity_verified": False,
        "occupancy_applied": False,
        "source_conflicts": copy.deepcopy(
            report.get("archive_comparison", {}).get("conflicts", [])
        ),
        "source_unresolved": copy.deepcopy(
            report.get("archive_comparison", {}).get("unresolved", [])
        ),
        "meaning": "Binding preserves the original survey ID/hash. Counts do not establish spare or occupied terminals.",
    }


def _match(pools, demands):
    """Integral bipartite max-flow; alternate modes compete for the same pool."""
    graph = {}

    def edge(a, b, capacity):
        graph.setdefault(a, {})[b] = capacity
        graph.setdefault(b, {})[a] = 0

    for index, row in enumerate(demands):
        edge("source", f"d{index}", row.quantity)
        for pool in pools:
            if row.mode in pool["modes"]:
                edge(f"d{index}", "p" + pool["id"], row.quantity)
    for pool in pools:
        edge("p" + pool["id"], "sink", pool["count"])
    while True:
        parents = {"source": None}
        queue = deque(["source"])
        while queue and "sink" not in parents:
            current = queue.popleft()
            for node, remaining in graph.get(current, {}).items():
                if remaining > 0 and node not in parents:
                    parents[node] = current
                    queue.append(node)
        if "sink" not in parents:
            break
        amount, node = 1024, "sink"
        while parents[node] is not None:
            previous = parents[node]
            amount = min(amount, graph[previous][node])
            node = previous
        node = "sink"
        while parents[node] is not None:
            previous = parents[node]
            graph[previous][node] -= amount
            graph[node][previous] += amount
            node = previous
    allocations = []
    for index, row in enumerate(demands):
        portions = [
            {"pool": pool["id"], "quantity": graph.get("p" + pool["id"], {}).get(f"d{index}", 0)}
            for pool in pools
        ]
        portions = [part for part in portions if part["quantity"]]
        matched = sum(part["quantity"] for part in portions)
        allocations.append(
            row.model_dump()
            | {
                "matched": matched,
                "unmatched": row.quantity - matched,
                "pool_count_witness": portions,
                "unmatched_basis": None
                if matched == row.quantity
                else "no-reviewed-pool-for-mode"
                if not any(row.mode in pool["modes"] for pool in pools)
                else "shared-pool-count-exhausted",
                "terminal_assignment": None,
            }
        )
    return allocations


def evaluate(value, hardware=None):
    request = CapacityRequest.model_validate(value)
    if request.catalog_sha256 != CATALOG["catalog_sha256"]:
        raise ValueError("Capacity catalog changed; reload and review the current facts.")
    model = request.model.strip().upper()
    binding = _survey_binding(request.survey_reference, model, hardware)
    profile = next((row for row in CATALOG["models"] if row["model"] == model), None)
    pools = profile["pools"] if profile else []
    allocations = _match(pools, request.demands)
    matched = sum(row["matched"] for row in allocations)
    total = sum(row.quantity for row in request.demands)
    status = (
        "unknown-model"
        if profile is None
        else "no-demand-declared"
        if not total
        else "count-mode-fit"
        if matched == total
        else "count-mode-shortfall"
    )
    result = {
        "format": FORMAT,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "request": request.model_dump(),
        "normalized_model": model,
        "catalog_sha256": CATALOG["catalog_sha256"],
        "model_profile": copy.deepcopy(profile),
        "sources": {key: copy.deepcopy(SOURCES[key]) for key in profile["source_ids"]}
        if profile
        else {},
        "survey_binding": binding,
        "status": status,
        "declared_channels": total,
        "matched_channels": matched,
        "demands": allocations,
        "pools": [
            {
                "id": pool["id"],
                "count": pool["count"],
                "used_in_witness": sum(
                    part["quantity"]
                    for row in allocations
                    for part in row["pool_count_witness"]
                    if part["pool"] == pool["id"]
                ),
                "meaning": "Illustrative pool-count witness only; not terminal allocation or installed spare capacity.",
            }
            for pool in pools
        ],
        "source_conflicts_present": bool(profile and profile["conflicts"]),
        "installed_verified": False,
        "terminal_assignment_verified": False,
        "electrical_compatibility_verified": False,
        "power_verified": False,
        "native_allocation_verified": False,
        "field_queries": False,
        "controller_writes": False,
        "scope": SCOPE,
    }
    result["content_sha256"] = digest(result)
    return result


def capacity_router(hardware):
    router = APIRouter(prefix="/api/hardware-capacity")

    @router.get("/catalog")
    def get_catalog():
        return catalog()

    @router.post("/review")
    def review(body: CapacityRequest):
        result = evaluate(body, hardware)
        return Response(canonical(result), media_type="application/json")

    return router
