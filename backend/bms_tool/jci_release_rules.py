"""Reviewed, operation-qualified JCI rules; never installer or native acceptance proof."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Annotated, Literal

from pydantic import Field, StrictBool

from .models import StrictModel

Text = Annotated[str, Field(max_length=80)]
Operation = Literal[
    "open",
    "commission",
    "edit-defaults",
    "edit-logic",
    "simulate",
    "upgrade-caf",
    "define-hardware",
    "transfer-to-device",
    "mstp-coexistence",
]


class ReleaseReview(StrictModel):
    operation: Operation = "open"
    source_tool_product: Literal["CCT", "PCT", "unknown"] = "unknown"
    source_tool_release: Text = ""
    source_channel: Literal["production", "alpha", "beta", "unknown"] = "unknown"
    caf_release_mode: Text = ""
    active_release_mode: Text = ""
    caf_device_family: Text = ""
    active_device_family: Text = ""
    package_generation: Literal["pre-16-only", "updated-16-plus", "unknown"] = "unknown"
    package_generation_evidence: Annotated[str, Field(max_length=2000)] = ""
    mixed_firmware_on_mstp: StrictBool | None = None
    source_sql_version: Text = ""
    destination_sql_version: Text = ""


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


SOURCES = {
    "guide11": {
        "title": "Metasys System Configuration Guide",
        "document": "LIT-12011832",
        "release": "11.0",
        "date": "2022-02-07",
        "pdf": "jci-lit-12011832-11-0-c2734c.pdf",
        "sha256": "cd4ec7ba7d8012a1dbfa8ced59ae6d14cf025a08f99614473be41af889543a73",
        "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Metasys-System-Configuration-Guide/11.0",
    },
    "guide16": {
        "title": "Metasys System Configuration Guide",
        "document": "LIT-12011832",
        "release": "16.0",
        "date": "2026-06-17",
        "pdf": "jci-lit-12011832-16-0-47f8e3.pdf",
        "sha256": "0c12f1988f5be8c46cc9d779d782139fe2b41994d98afc54d7dfc91e234d20d4",
        "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Metasys-System-Configuration-Guide/16.0",
    },
    "help18": {
        "title": "Controller Tool Help",
        "document": "LIT-12011147",
        "release": "18.0",
        "copyright_year": "2025",
        "pdf": "jci-lit-12011147-18-0-14d1fc.pdf",
        "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
        "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    },
    "pct103": {
        "title": "FX-PCT Installation Instructions",
        "document": "LIT-12011673",
        "release": "10.3",
        "date": "2019-03",
        "pdf": "jci-lit-12011673-10-3-1cf21e.pdf",
        "sha256": "46aeeb12517462f3eae28e177dff57bd38ea319cd98dcb7a067eb2aed9006248",
        "url": "https://docs.johnsoncontrols.com/bas/v/u/Facility-Explorer/en-US/FX-PCT-Installation-Instructions/10.3",
    },
}


def evidence(key, *pages):
    return SOURCES[key] | {"pdf_pages": list(pages)}


RULES = [
    {
        "id": "application.origin-unknown",
        "operations": [
            "open",
            "commission",
            "edit-defaults",
            "edit-logic",
            "simulate",
            "upgrade-caf",
            "define-hardware",
            "transfer-to-device",
        ],
        "kind": "review-coverage-policy",
        "criterion": "Unknown or unreviewed application-tool origins remain unresolved. This conservative review accepts declared CCT source releases1.0..18.0 and PCT source releases1.0..10.3; this bound does not authenticate release existence or installed availability. CAF Appl SW Version and installer consolidation do not identify source-tool release/product.",
        "sources": [evidence("help18", 37, 51), evidence("pct103", 2)],
    },
    {
        "id": "cct.earlier-open-commission",
        "operations": ["open", "commission"],
        "criterion": "CCT 10.1 or greater can open and commission earlier CCT applications. This reviewed implementation bounds destination releases to 10.1..18.0; it does not equate source-tool release with CAF mode.",
        "sources": [evidence("guide11", 54), evidence("guide16", 53)],
    },
    {
        "id": "cct18.mode-operation",
        "operations": ["edit-defaults", "edit-logic", "simulate"],
        "criterion": "CCT 18: exact matching release mode for logic editing/simulation, or upgrade where documented; older CAF opened without upgrade permits default-value edits only. Attributes may display unexpectedly.",
        "sources": [evidence("help18", 51, 79, 89, 90)],
    },
    {
        "id": "cct18.upgrade-mode-family",
        "operations": ["upgrade-caf"],
        "criterion": "CCT 18 CAF upgrade requires a newer active release mode and the same device family. Device-model/package support and post-upgrade validation remain separate.",
        "sources": [evidence("help18", 51, 123, 130)],
    },
    {
        "id": "cct.prerelease-upgrade",
        "operations": ["upgrade-caf"],
        "criterion": "Alpha and beta site applications do not automatically upgrade; major/minor production revision upgrades are described, not independently executed here.",
        "sources": [evidence("guide11", 54), evidence("help18", 121)],
    },
    {
        "id": "cct16.package-security",
        "operations": ["define-hardware", "transfer-to-device", "upgrade-caf"],
        "criterion": "Packages compatible only with earlier CCT releases are incompatible with CCT 16 and later after security updates; updated packages are required. Reviewed destination ceiling18.0.",
        "sources": [evidence("help18", 38)],
    },
    {
        "id": "cct18.package-license",
        "operations": ["define-hardware", "transfer-to-device"],
        "criterion": "CCT 18 unlicensed field devices become artificial devices, cannot be set in Define Hardware and cannot receive CAF transfers.",
        "sources": [evidence("help18", 37, 38, 79)],
    },
    {
        "id": "cct.mstp-mixed-firmware",
        "operations": ["mstp-coexistence"],
        "criterion": "Different controller firmware revisions may coexist on an engine MS/TP integration; engineering enumeration display can still be incomplete.",
        "sources": [evidence("guide11", 54), evidence("guide16", 53), evidence("help18", 121)],
    },
    {
        "id": "cct.sql-file-independence",
        "operations": ["open"],
        "criterion": "CCT CAF file portability is independent of SQL Server version. This does not establish supported SQL installation/runtime prerequisites.",
        "sources": [evidence("guide11", 54), evidence("guide16", 53), evidence("help18", 122)],
    },
    {
        "id": "pct103.release-modes",
        "operations": ["open", "commission", "edit-defaults", "edit-logic", "simulate"],
        "criterion": "FX-PCT 10.3 can switch among 10.x release modes for earlier FX-PCT CAFs. Pre10.0 requires the documented clean-installation workflow; cross-product CAF compatibility is not established by software consolidation.",
        "sources": [evidence("pct103", 2, 4)],
    },
    {
        "id": "pct-cct.not-equivalent",
        "operations": [
            "open",
            "commission",
            "edit-defaults",
            "edit-logic",
            "simulate",
            "upgrade-caf",
            "define-hardware",
            "transfer-to-device",
        ],
        "criterion": "The PCT 10.3 installation guide describes software consolidation at CCT 13 and installer upgrade paths; that is not a universal PCT/CCT application, model, package or firmware compatibility table.",
        "sources": [evidence("pct103", 2)],
    },
]
RULESET = {
    "profile": "jci-reviewed-release-conditions/1",
    "rules": RULES,
    "namespaces": [
        "tool release",
        "source tool release",
        "CAF release mode",
        "Appl SW Version",
        "controller firmware",
        "package generation",
    ],
    "reviewed_destination_ceiling": "CCT 18.0; PCT 10.3 only",
}
RULESET_SHA = digest(RULESET)


def version(value):
    # Release identifiers only: a build/prerelease suffix is not silently discarded.
    if not re.fullmatch(r"[0-9]{1,3}\.[0-9]{1,3}", value):
        return None
    return tuple(int(part) for part in value.split("."))


def catalog():
    return {
        "format": "bms.jci-release-rule-catalog",
        "version": 1,
        "ruleset_sha256": RULESET_SHA,
        "ruleset": RULESET,
        "template": ReleaseReview().model_dump(),
        "operations": list(ReleaseReview.model_fields["operation"].annotation.__args__),
    }


def review(value: ReleaseReview, tool, packages, *, caf_sha256, application_version):
    declared = value.model_dump()
    findings = []
    op, target, origin = value.operation, version(tool.version), version(value.source_tool_release)
    caf_mode, active_mode = version(value.caf_release_mode), version(value.active_release_mode)
    cct = tool.product == "CCT" and target is not None and (10, 1) <= target <= (18, 0)
    cct18 = tool.product == "CCT" and target == (18, 0)

    def add(identity, status, detail):
        rule = next(row for row in RULES if row["id"] == identity)
        findings.append(
            {"rule_id": identity, "status": status, "detail": detail, "sources": rule["sources"]}
        )

    if op in ("open", "commission") and tool.product == "CCT":
        if not cct or value.source_tool_product != "CCT" or origin is None or origin >= target:
            add(
                "cct.earlier-open-commission",
                "unknown",
                "Requires declared CCT destination release10.1..18.0 and an explicitly earlier CCT source release. Equal/newer, unknown source, build strings and cross-product cases remain uncovered; Appl SW Version is not substituted.",
            )
        else:
            add(
                "cct.earlier-open-commission",
                "condition-met",
                "The declared earlier-CCT open/commission condition is documented. This does not establish full attribute display, editing, simulation, device/package support or native operation acceptance.",
            )
    if op in ("edit-defaults", "edit-logic", "simulate") and tool.product == "CCT":
        if not cct18 or caf_mode is None or active_mode is None:
            add(
                "cct18.mode-operation",
                "unknown",
                "This rule requires CCT 18.0 and separately supplied numeric CAF/active release-mode identifiers. No mode is inferred from tool release, Appl SW Version or firmware.",
            )
        elif caf_mode == active_mode:
            add(
                "cct18.mode-operation",
                "condition-met",
                "Declared CAF and active modes match for this operation. Installed mode, model and package availability remain unverified.",
            )
        elif op == "edit-defaults" and caf_mode < active_mode:
            add(
                "cct18.mode-operation",
                "condition-met",
                "Only default-value edits are documented when opening an older CAF without upgrading; this does not permit logic edits or simulation and attributes may display unexpectedly.",
            )
        else:
            add(
                "cct18.mode-operation",
                "conflict",
                "The current declared mode does not match. Switch to the exact matching mode, or separately review a supported same-family upgrade before this operation; no switch or upgrade is performed.",
            )
    if op == "upgrade-caf" and tool.product == "CCT":
        if (
            not cct18
            or caf_mode is None
            or active_mode is None
            or not value.caf_device_family.strip()
            or not value.active_device_family.strip()
        ):
            add(
                "cct18.upgrade-mode-family",
                "unknown",
                "Requires CCT 18.0, explicit CAF/active modes and independently declared device-family identifiers. Model prefixes and firmware do not establish the family.",
            )
        elif active_mode <= caf_mode or value.caf_device_family != value.active_device_family:
            add(
                "cct18.upgrade-mode-family",
                "conflict",
                "CAF upgrade requires a strictly newer active mode in the same declared device family. No downgrade or cross-family conversion is inferred.",
            )
        else:
            add(
                "cct18.upgrade-mode-family",
                "condition-met",
                "Newer-mode/same-declared-family prerequisite matches. Exact model firmware availability, packages and post-upgrade function/capacity validation remain required.",
            )
        if not cct:
            status, detail = (
                "unknown",
                "Destination CCT release is outside the reviewed 10.1..18.0 scope.",
            )
        elif value.source_channel in ("alpha", "beta"):
            status, detail = (
                "conflict",
                "The declared alpha/beta application does not automatically upgrade; production version ordering cannot override this exception.",
            )
        elif value.source_channel == "production":
            status, detail = (
                "condition-met",
                "The declared source is production; this clears only the alpha/beta automatic-upgrade exception.",
            )
        else:
            status, detail = (
                "unknown",
                "Source production/alpha/beta status is unknown; automatic upgrading is not established.",
            )
        add("cct.prerelease-upgrade", status, detail)
    if op in ("define-hardware", "transfer-to-device", "upgrade-caf") and tool.product == "CCT":
        if target is None or not (16, 0) <= target <= (18, 0):
            add(
                "cct16.package-security",
                "unknown",
                "The reviewed security rule covers CCT 16.0..18.0; other releases remain outside this rule's scope.",
            )
        elif value.package_generation == "unknown" or not value.package_generation_evidence.strip():
            add(
                "cct16.package-security",
                "unknown",
                "Declare whether the package is pre-16-only or updated for 16+ and cite its provenance. Package filename/version alone does not prove its security generation.",
            )
        else:
            add(
                "cct16.package-security",
                "conflict" if value.package_generation == "pre-16-only" else "condition-met",
                "Pre16-only packages are incompatible with the declared CCT 16+ tool."
                if value.package_generation == "pre-16-only"
                else "Declared updated 16+ package generation clears only this security boundary; exact model/mode/firmware support remains unverified.",
            )
    if op in ("define-hardware", "transfer-to-device") and tool.product == "CCT":
        required = [p for p in packages if p.required]
        status = (
            "unknown"
            if not cct18 or not required or any(p.license_status == "unknown" for p in required)
            else "conflict"
            if any(p.license_status == "missing" for p in required)
            else "condition-met"
        )
        # A known missing license dominates other unknown licenses.
        if cct18 and any(p.license_status == "missing" for p in required):
            status = "conflict"
        add(
            "cct18.package-license",
            status,
            "Unlicensed field devices cannot be assigned in Define Hardware or receive CAF transfers. Required-package license declarations were reviewed, not activated or independently probed; licensed declarations clear only this restriction.",
        )
    if op == "mstp-coexistence":
        status = "condition-met" if cct and value.mixed_firmware_on_mstp is True else "unknown"
        add(
            "cct.mstp-mixed-firmware",
            status,
            "Documented coexistence applies to mixed controller firmware on an engine MS/TP integration, not every engineering display or native transfer. Mixed-version enumerations may display incorrectly. No network was inspected.",
        )
    if op == "open" and tool.product == "CCT":
        add(
            "cct.sql-file-independence",
            "condition-met"
            if cct
            and value.source_tool_product == "CCT"
            and value.source_sql_version
            and value.destination_sql_version
            else "unknown",
            "Different SQL Server versions do not by themselves prevent CCT CAF opening. Exact supported SQL/Windows installation and runtime availability remain independent prerequisites; no SQL-to-CAF version equality is imposed.",
        )
    if tool.product == "PCT":
        supported_op = (
            op in next(r for r in RULES if r["id"] == "pct103.release-modes")["operations"]
        )
        if supported_op:
            match = (
                target == (10, 3)
                and value.source_tool_product == "PCT"
                and origin is not None
                and (10, 0) <= origin <= (10, 3)
                and caf_mode is not None
                and active_mode is not None
                and (10, 0) <= caf_mode <= (10, 3)
                and (10, 0) <= active_mode <= (10, 3)
            )
            add(
                "pct103.release-modes",
                "condition-met"
                if match and caf_mode == active_mode
                else "conflict"
                if match
                else "unknown",
                "PCT 10.3 documents switching among 10.x modes for earlier PCT CAFs. Matching declared 10.x modes clear only this mode-switching condition; mismatches require switching. Pre10.0 and cross-product combinations need separate evidence; no native execution is performed.",
            )
    if (
        value.source_tool_product != "unknown"
        and tool.product != "unknown"
        and value.source_tool_product != tool.product
        and op != "mstp-coexistence"
    ):
        add(
            "pct-cct.not-equivalent",
            "unknown",
            "Source and destination products differ. Software consolidation/installer upgrade instructions do not prove application compatibility; generic earlier-CCT/PCT rules are not crossed.",
        )
    source_in_scope = origin is not None and (
        value.source_tool_product == "CCT"
        and (1, 0) <= origin <= (18, 0)
        or value.source_tool_product == "PCT"
        and (1, 0) <= origin <= (10, 3)
    )
    if not source_in_scope and op != "mstp-coexistence":
        add(
            "application.origin-unknown",
            "unknown",
            "Source application tool product/release is unknown or outside this review's coverage. Mode equality cannot resolve that gap; no origin is inferred from Appl SW Version.",
        )
    if not findings:
        findings.append(
            {
                "rule_id": "uncovered-operation",
                "status": "unknown",
                "detail": "No reviewed rule establishes this product/release/operation combination.",
                "sources": [],
            }
        )
    report = {
        "format": "bms.jci-release-review",
        "version": 1,
        "ruleset_sha256": RULESET_SHA,
        "source": {
            "caf_sha256": caf_sha256,
            "declarations": declared,
            "destination_tool": tool.model_dump(),
            "required_package_declarations": [p.model_dump() for p in packages if p.required],
            "observed_appl_sw_version": application_version,
        },
        "findings": findings,
        "counts": dict(Counter(row["status"] for row in findings)),
        "status": "documented-conflict"
        if any(row["status"] == "conflict" for row in findings)
        else "needs-evidence"
        if any(row["status"] == "unknown" for row in findings)
        else "documented-conditions-only",
        "can_execute_native": False,
        "can_deploy": False,
        "manufacturer_tool_executed": False,
        "scope": "Offline operation-qualified review of submitted declarations against exact cited manuals. A cleared documented prerequisite is not installed tooling, model/package/firmware acceptance, native compilation or transfer approval.",
        "unverified": [
            "actual installed tool/release modes/licenses",
            "exact controller model/package/firmware compatibility",
            "OS/architecture/SQL runtime support",
            "native compiler/loader execution",
            "vendor reopen and bench acceptance",
            "full attribute/enumeration display",
            "post-upgrade logic/connections/capacity correctness",
        ],
    }
    report["content_sha256"] = digest(report)
    return report
