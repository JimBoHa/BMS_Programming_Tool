"""Offline BACnet number engineering; all topology relationships are declarations."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import Field, model_validator

from .models import StrictModel

FORMAT = "bms.bacnet-network-number-plan"
MAX_BYTES = 2 * 1024 * 1024
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:+-]{1,80}$")]
Name = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^\S(?:[^\x00-\x1f]*\S)?$")]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
SCOPE = (
    "Review of submitted operator declarations only. Physical-network and internetwork keys are "
    "explicit assertions, not inferred topology. Advertised routes, IP subnets and endpoint addresses "
    "cannot establish network identity, bus type or complete inventory. No global available-number "
    "claim, automatic renumbering, field scanning or device writes."
)
SOURCES = [
    {
        "id": "bacnet-range",
        "document": "ANSI/ASHRAE 135-1995 errata, 1999-09-07",
        "section": "6.2.2.1; PDF page 3",
        "artifact": "primary publisher PDF bytes",
        "sha256": "5e0c5a707ba360fe10d1d72396088aec34688118974b4d3739788fec52ad2c8e",
        "url": "https://bacnet.org/wp-content/uploads/sites/4/2022/08/135-1995-Errata-9-7-1999.pdf",
        "scope": "Numbered physical networks use 1..65534; 0 is local addressing context and 65535 is a global destination, not an assigned physical-network number.",
    },
    {
        "id": "bacnet-internetwork",
        "document": "NISTIR 6392, November 1999",
        "section": "6.1, 6.4, 6.6.2; PDF pages 26, 35, 39",
        "artifact": "primary author PDF bytes, hosted on bacnet.org",
        "sha256": "2e15fa8a34e1f36a93deb848a775664c83e1c0254b862af09768ad464319f80f",
        "url": "https://bacnet.org/wp-content/uploads/sites/4/2022/06/NISTIR-6392.pdf",
        "scope": "Each network has a unique number within its internetwork. One BACnet/IP network may span IP subnets; physical segments joined by bridges/repeaters need not be separate numbered networks.",
    },
    {
        "id": "jci-r15-remote-field",
        "document": "JCI LIT-12011034",
        "release": "15.0",
        "date": "2026-09-29",
        "section": "PDF pages 10, 12–13",
        "artifact": "primary publisher PDF bytes",
        "sha256": "18c323a65edec4fe29120bab29d38303bf57e9b21fe1b1a108eb597c077aee37",
        "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/MS/TP-Communications-Bus-Technical-Bulletin/15.0",
        "scope": "Explicit Release 15 Remote Field Bus IP/MS/TP engineering profile only. Engine and router-side numbers must match for the same network. Distinct remote buses need site-unique numbers, including local trunks/IP networks. Avoid 2000 and 65000 for new remote-field assignments; existing embedded networks may use them. No inference for other releases.",
    },
]


def canonical(value):
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Network plan requires bounded finite JSON values.") from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


PROFILE = {
    "id": "bacnet-network-number-review/1",
    "sources": SOURCES,
    "rules": {
        "numbered_physical_network": {"min": 1, "max": 65534},
        "jci_r15_new_remote_field_avoid": [2000, 65000],
        "identity": "Exact case-sensitive operator keys; domain + physical-network key",
        "maximum_assignments": 512,
    },
}
PROFILE["sha256"] = digest(PROFILE)


class Assignment(StrictModel):
    id: Key
    label: Name
    domain_key: Key
    physical_network_key: Key | None = None
    endpoint_key: Key | None = None
    port_key: Key | None = None
    network_number: int | None = Field(default=None, ge=0, le=65535, strict=True)
    medium: Literal["unknown", "bacnet-ip", "mstp", "other"] = "unknown"
    role: Literal[
        "network",
        "router-port",
        "engine-ip-port",
        "engine-remote-field-integration",
        "route-advertisement",
    ] = "network"
    policy: Literal["generic", "jci-r15-remote-field"] = "generic"
    assignment_state: Literal["new", "existing", "unknown"] = "unknown"
    notes: str = Field(default="", max_length=2000)


class NetworkPlan(StrictModel):
    format: Literal["bms.bacnet-network-number-plan"] = FORMAT
    version: Literal[1] = 1
    profile_sha256: Hash
    name: Name
    declarations_complete: bool = Field(default=False, strict=True)
    notes: str = Field(default="", max_length=4000)
    assignments: list[Assignment] = Field(default_factory=list, max_length=512)

    @model_validator(mode="before")
    @classmethod
    def explicit_version(cls, value):
        if isinstance(value, dict) and (
            value.get("format") != FORMAT or type(value.get("version")) is not int
        ):
            raise ValueError("Network plan requires explicit format and integer version 1.")
        return value

    @model_validator(mode="after")
    def exact_identities(self):
        if len({row.id for row in self.assignments}) != len(self.assignments):
            raise ValueError("Network attachment record IDs must be unique.")
        if self.profile_sha256 != PROFILE["sha256"]:
            raise ValueError(
                "Network review source profile changed; review current sources and rebind explicitly."
            )
        return self


def template():
    return NetworkPlan(
        format=FORMAT, version=1, profile_sha256=PROFILE["sha256"], name="New network-number plan"
    ).model_dump()


def validate_plan(value):
    if len(canonical(value)) > MAX_BYTES:
        raise ValueError("Network plan exceeds 2 MiB.")
    return NetworkPlan.model_validate(value)


def review(value):
    plan = validate_plan(value)
    findings = []

    def add(code, severity, message, rows=(), **context):
        detail = {
            "code": code,
            "severity": severity,
            "message": message,
            "assignment_ids": sorted(row.id for row in rows),
            **context,
        }
        detail["id"] = digest(detail)
        findings.append(detail)

    if not plan.assignments:
        add("no-assignments", "unknown", "No network attachments were declared.")
    if not plan.declarations_complete:
        add(
            "inventory-not-declared-complete",
            "unknown",
            "Submitted inventory is not declared complete; omitted networks cannot be compared.",
        )
    numbers, networks, endpoints = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in plan.assignments:
        rows = [row]
        context = {"domain_key": row.domain_key}
        if row.network_number is None:
            add(
                "unknown-network-number",
                "unknown",
                "This attachment's network number is unknown.",
                rows,
                **context,
            )
        elif row.network_number in (0, 65535):
            add(
                "not-a-physical-network-number",
                "error",
                "0 denotes local addressing context and 65535 is a global destination. Neither identifies an assigned numbered physical network.",
                rows,
                **context,
            )
        if row.physical_network_key is None:
            add(
                "unknown-physical-network",
                "unknown",
                "No physical-network key was declared; sameness or separation cannot be inferred from the number, endpoint or IP subnet.",
                rows,
                **context,
            )
        else:
            networks[row.domain_key, row.physical_network_key].append(row)
            if row.network_number is not None and 1 <= row.network_number <= 65534:
                numbers[row.domain_key, row.network_number].append(row)
        if (row.endpoint_key is None) != (row.port_key is None):
            add(
                "incomplete-endpoint-port",
                "unknown",
                "Declare both endpoint and port keys to compare this attachment's endpoint assignment.",
                rows,
                **context,
            )
        if row.endpoint_key is not None and row.port_key is not None:
            endpoints[row.domain_key, row.endpoint_key, row.port_key].append(row)
        if row.role == "route-advertisement":
            add(
                "route-observation-only",
                "unknown",
                "A route advertisement alone does not prove a distinct physical network, medium, consistent configured endpoints or full inventory; topology keys remain operator assertions.",
                rows,
                **context,
            )
        if row.policy == "jci-r15-remote-field":
            if row.medium not in ("bacnet-ip", "mstp"):
                add(
                    "jci-profile-medium-unconfirmed",
                    "unknown",
                    "The reviewed R15 Remote Field Bus rule covers explicitly declared BACnet/IP or MS/TP assignments only; this medium does not establish that scope.",
                    rows,
                    **context,
                )
            elif row.network_number in (2000, 65000):
                if row.assignment_state == "new":
                    add(
                        "jci-r15-new-reserved-number",
                        "error",
                        "The reviewed JCI R15 Remote Field Bus profile avoids 2000 and 65000 for new IP/MS/TP assignments. Existing embedded networks may use them; this is not a universal BACnet prohibition.",
                        rows,
                        **context,
                    )
                elif row.assignment_state == "unknown":
                    add(
                        "jci-r15-assignment-state-unknown",
                        "unknown",
                        "2000/65000 need explicit existing/new context under the R15 profile. Existing embedded network use is not declared universally illegal.",
                        rows,
                        **context,
                    )
                else:
                    add(
                        "jci-r15-existing-number-review",
                        "info",
                        "Existing use of 2000/65000 is recorded without declaring it universally illegal. Confirm whether this is the documented embedded-network context before adding remote-field assignments.",
                        rows,
                        **context,
                    )
    for (domain, number), rows in sorted(numbers.items()):
        keys = sorted({row.physical_network_key for row in rows})
        if len(keys) > 1:
            add(
                "number-on-distinct-networks",
                "error",
                "One network number is assigned to distinct declared physical networks in this internetwork.",
                rows,
                domain_key=domain,
                network_number=number,
                physical_network_keys=keys,
            )
    for (domain, key), rows in sorted(networks.items()):
        assigned = sorted(
            {
                row.network_number
                for row in rows
                if row.network_number is not None and 1 <= row.network_number <= 65534
            }
        )
        if len(assigned) > 1:
            add(
                "network-number-mismatch",
                "error",
                "The same declared physical network has inconsistent attachment numbers. Engine integration and corresponding router-side assignments must agree.",
                rows,
                domain_key=domain,
                physical_network_key=key,
                network_numbers=assigned,
            )
        media = sorted({row.medium for row in rows if row.medium != "unknown"})
        if len(media) > 1:
            add(
                "physical-medium-mismatch",
                "error",
                "The same declared physical network has contradictory media. Confirm the topology keys and medium declarations.",
                rows,
                domain_key=domain,
                physical_network_key=key,
                media=media,
            )
    for (domain, endpoint, port), rows in sorted(endpoints.items()):
        keys = sorted(
            {row.physical_network_key for row in rows if row.physical_network_key is not None}
        )
        assigned = sorted(
            {
                row.network_number
                for row in rows
                if row.network_number is not None and 1 <= row.network_number <= 65534
            }
        )
        if len(keys) > 1 or len(assigned) > 1:
            add(
                "endpoint-port-conflict",
                "error",
                "The same declared endpoint/port has conflicting physical-network or number assignments. This does not infer physical identity for other records.",
                rows,
                domain_key=domain,
                endpoint_key=endpoint,
                port_key=port,
                physical_network_keys=keys,
                network_numbers=assigned,
            )
    findings.sort(
        key=lambda row: (
            {"error": 0, "unknown": 1, "info": 2}[row["severity"]],
            row["code"],
            row["id"],
        )
    )
    counts = {
        severity: sum(row["severity"] == severity for row in findings)
        for severity in ("error", "unknown", "info")
    }
    result = {
        "format": "bms.bacnet-network-number-review",
        "version": 1,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "plan_sha256": digest(plan.model_dump()),
        "source_profile": copy.deepcopy(PROFILE),
        "plan": plan.model_dump(),
        "status": "conflicts"
        if counts["error"]
        else "incomplete"
        if counts["unknown"]
        else "no-conflicts-in-declarations",
        "counts": counts,
        "findings": findings,
        "declared_domains": sorted({row.domain_key for row in plan.assignments}),
        "declared_physical_networks": len(networks),
        "scope": SCOPE,
        "field_scans": False,
        "controller_writes": False,
        "physical_topology_verified": False,
        "inventory_verified": False,
        "provenance": "Operator-declared plan and reviewed source hashes; no manufacturer authenticity claim.",
    }
    result["content_sha256"] = digest(result)
    return result


class PlanBody(StrictModel):
    plan: dict


def network_plan_router():
    router = APIRouter(prefix="/api/network-number-plan")

    @router.get("/catalog")
    def catalog():
        return {"profile": copy.deepcopy(PROFILE), "template": template(), "scope": SCOPE}

    @router.post("/validate")
    def validate(body: PlanBody):
        plan = validate_plan(body.plan).model_dump()
        return {"plan": plan, "plan_sha256": digest(plan)}

    @router.post("/review")
    def calculate(body: PlanBody):
        return review(body.plan)

    return router
