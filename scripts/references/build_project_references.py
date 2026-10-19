#!/usr/bin/env python3
"""Publish factual source metadata and original feature criteria, never raw manuals."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2].parent / "Reference_Library"
WORK = ROOT.parent
PROJECT = Path(__file__).resolve().parents[2]
refs = []
for r in (
    json.loads((WORK / "Manual_Library/catalog.json").read_text())
    if (WORK / "Manual_Library/catalog.json").exists()
    else []
):
    if r.get("scope_status") == "excluded" or r.get("duplicate_of"):
        continue
    refs.append(
        {
            "vendor": "Johnson Controls",
            "title": r["title"] + " · " + str(r.get("edition", "")),
            "url": r.get("source_url", ""),
            "document": r.get("document_number"),
            "pages": r.get("pages"),
            "sha256": r.get("sha256"),
            "status": r["status"],
            "local_collection": "jci",
            "local_id": r["id"],
            "notes": r.get("category", ""),
        }
    )
seen = set()
for r in json.loads((ROOT / "catalog.json").read_text()):
    if r.get("kind") == "index":
        continue
    key = r.get("sha256") or r["url"]
    if key in seen:
        continue
    seen.add(key)
    refs.append(
        {
            "vendor": r["vendor"],
            "title": r.get("title") or Path(r.get("path", r["url"])).name,
            "url": r["url"],
            "pages": r.get("pages"),
            "sha256": r.get("sha256"),
            "status": r["status"],
            "local_collection": "multivendor" if r.get("id") else None,
            "local_id": r.get("id"),
            "notes": r.get(
                "notes", "Local reference; original copyright/confidentiality notices retained."
            ),
        }
    )
inventory = (
    json.loads((ROOT / "research/github/inventory.json").read_text())
    if (ROOT / "research/github/inventory.json").exists()
    else []
)
overrides = {
    "linsong/sedona": "AFL-3.0 per README and LICENSE.md",
    "openbms-io/bms-apps": "AGPL-3.0-or-later per LICENSE",
    "thecontrolscompany/oct": "Apache-2.0 per LICENSE",
    "tridium/forum2025-fox-session-demo": "Custom Tridium license; not treated as a general permissive code source",
}
for r in inventory:
    repo = r.get("full_name", r.get("repository"))
    license = overrides.get(
        repo,
        (r.get("license") or {}).get(
            "spdx_id", "Unverified from metadata; inspect source/package notices"
        ),
    )
    refs.append(
        {
            "vendor": "Open source / source research",
            "title": repo,
            "url": r.get("html_url", "https://github.com/" + repo),
            "notes": license + " · " + (r.get("description") or ""),
            "status": "metadata and README/license inspected",
        }
    )
(PROJECT / "docs/references.json").write_text(json.dumps(refs, indent=2))

requirements = []


def add(id, feature, criterion, source, pages, status, implementation):
    requirements.append(
        {
            "id": id,
            "feature": feature,
            "acceptance_criterion": criterion,
            "evidence": source,
            "pdf_pages_or_section": pages,
            "status": status,
            "implementation_or_gap": implementation,
        }
    )


jci = "JCI Controller Tool Help 18.0 LIT-12011147"
add(
    "UI-001",
    "Graph authoring",
    "Create blocks, connect named pins, edit parameters and navigate large diagrams.",
    jci,
    "148-175",
    "implemented",
    "React Flow canvas and inspector",
)
add(
    "IR-001",
    "Typed wiring",
    "Reject missing/multiple writers and show unit/type mismatches before execution.",
    jci,
    "159-161",
    "implemented",
    "engine.validate; tests/test_engine.py",
)
add(
    "SIM-001",
    "Offline execution",
    "Simulate complete scans and inject numeric/boolean I/O without field writes.",
    jci,
    "265-274",
    "implemented",
    "Engine; Simulation workspace",
)
add(
    "OPS-001",
    "Separate operations",
    "Label application download, parameter writes, backup and restore as distinct actions.",
    jci,
    "286-290",
    "partial",
    "Point services and local runtime implemented; native download absent",
)
add(
    "OPS-002",
    "Commissioning",
    "Support calibration, actuator tests and balancing with preserved parameters.",
    jci,
    "329-344",
    "pending",
    "Target-specific commissioning adapter",
)
add(
    "VAV-001",
    "VAV families",
    "Support cooling-only, inline reheat and parallel fan-powered applications.",
    jci,
    "585-591",
    "partial",
    "Illustrative graphs; native/certified sequences pending",
)
add(
    "FMT-001",
    "Preserve originals",
    "Retain unknown objects and metadata; export edited copies with explicit validation scope.",
    "Authorized local CAF samples",
    "ZIP/XML inspection",
    "partial",
    "Byte-exact no-op; scalar patch; jobInfo/simulationProperty retained",
)
add(
    "FMT-002",
    "Full JCI logic",
    "Create, rewire, compile and validate native applications for each supported model/release.",
    "OCT README and local CAF evidence",
    "Requirements; native container",
    "pending",
    "Native semantics, packages, compiler and download adapter",
)
add(
    "FMT-003",
    "FX/Metasys interoperability",
    "Read both product families without confusing model or release compatibility.",
    "JCI FX Workbench guide LIT-12012256",
    "49-50; 243-244",
    "partial",
    "Both sample families inspected; cross-target compilation pending",
)
add(
    "COMM-001",
    "Bluetooth transport",
    "Provide an adapter with explicit firmware and transfer compatibility.",
    "JCI System Configuration Guide LIT-12011832 v16",
    "84",
    "pending",
    "BTCVT protocol/hardware; do not fake compatibility by opening serial",
)
add(
    "LIC-001",
    "Portable workspace",
    "Keep project data independent of host-specific vendor licenses.",
    "JCI Software Manager Help LIT-12012389 v5",
    "7;17-18",
    "implemented",
    "Open graph data and local revision store; vendor tools retain their own license rules",
)

alc = "ALC Eikon 3.02 User Guide"
add(
    "UI-002",
    "Block properties",
    "Edit labels, parameters and units with immediate diagnostics.",
    alc,
    "29-51",
    "implemented",
    "Inspector; validation",
)
add(
    "SIM-002",
    "Time controls",
    "Run, stop, reset and single-step with configurable scan duration.",
    alc,
    "52-55",
    "implemented",
    "Simulation controls; program scan_seconds",
)
add(
    "SIM-003",
    "Clock and communications",
    "Inject calendar, time and communications validity explicitly.",
    alc,
    "52-54",
    "partial",
    "Engine clock/input quality; native simulation includes an explicit UTC calendar control",
)
add(
    "SIM-004",
    "Multiple applications",
    "Simulate interacting programs through typed shared signals.",
    alc,
    "54-55",
    "pending",
    "Multi-program simulation coordinator",
)
add(
    "UI-003",
    "Resource/error view",
    "Show target resource accounting and errors beyond drawing correctness.",
    alc,
    "50-51",
    "partial",
    "Node/terminal constraints; native memory/cycle estimates pending",
)
add(
    "FMT-004",
    "ALC native bridge",
    "Generate or import executable ALC control programs through a verified interface.",
    "ALC Integration Builder README",
    "Installation; Usage",
    "pending",
    "Licensed EIKON scripting bridge or independent documented encoder",
)

spyder = "Honeywell Spyder Tool for WEBs-N4 31-00089-02"
add(
    "UI-004",
    "Reusable macros",
    "Create nested, reusable control components with typed interfaces.",
    spyder,
    "56-60",
    "pending",
    "Subgraph library and versioned macro interface",
)
add(
    "SIM-005",
    "Timed scenarios",
    "Support repeatable input timelines and trace exports.",
    spyder,
    "390-392",
    "implemented",
    "run_scenario; CSV traces",
)
add(
    "SIM-006",
    "Force/release simulation values",
    "Override selected signals independently; restore their source cleanly.",
    spyder,
    "374-376;392",
    "partial",
    "Input forcing and quality faults; internal block forcing pending",
)
add(
    "DBG-001",
    "Live debug",
    "Watch selected signals and show force state without silently clearing others.",
    spyder,
    "367-376",
    "partial",
    "Explicit point reads/commands; application internal signal watch pending",
)
add(
    "FMT-005",
    "Honeywell native format",
    "Compile and download supported Spyder/CIPer applications using correct modules.",
    spyder,
    "41-65",
    "pending",
    "Verified Honeywell compiler/module and application adapter",
)
add(
    "RES-001",
    "Per-target limits",
    "Describe memory, block, terminal and channel limits per model.",
    "Honeywell Spyder Model 5 guide 31-00282-03",
    "8-9",
    "partial",
    "Generic node/I/O capacities; native model profiles pending",
)
add(
    "COMM-002",
    "Point services",
    "Discover addressed devices, browse properties and read values without application download.",
    "Honeywell Spyder Utility Tool 62-0381",
    "1-8",
    "implemented",
    "BACpypes3 BACnet/IP and routed destinations",
)

temco = "Temco T3000 Software Manual Rev4"
add(
    "RUN-001",
    "Atomic replacement",
    "Keep the last valid application when replacement validation fails.",
    temco,
    "138-139",
    "implemented",
    "Runtime.plan/apply; generation and execution checks",
)
add(
    "UI-005",
    "Revision history",
    "Save applications and restore prior versions with conflict detection.",
    temco,
    "139",
    "implemented",
    "SQLite revision store; optimistic save",
)
add(
    "RUN-002",
    "Explicit scan semantics",
    "Define evaluation order and commit outputs after the scan succeeds.",
    temco,
    "141",
    "implemented",
    "Topological order; delayed feedback; staged state/output commit",
)
add(
    "FMT-006",
    "Control Basic",
    "Support valid Temco BASIC source conversion and device compiler transfer.",
    temco,
    "137-169",
    "pending",
    "Control Basic semantic adapter and acceptance fixtures",
)
add(
    "COMM-003",
    "Serial framing",
    "Offer real Modbus TCP/RTU reads with response and CRC checks.",
    "Temco T3000 repository README",
    "Communication; source modules",
    "partial",
    "TCP loopback and real OS pseudoterminal RTU with fragmented replies/CRC rejection verified; physical serial hardware untested",
)

add(
    "UI-006",
    "Graph navigation",
    "Provide zoom, minimap, drag/drop, multi-selection and intuitive linking.",
    "Tridium Niagara 4.12 Features Overview",
    "5",
    "partial",
    "Zoom/drag/link/minimap; multi-node editing pending",
)
add(
    "FMT-007",
    "Migration reports",
    "Describe incompatible types/services instead of dropping them silently.",
    "Niagara AX to N4 Migration Guide",
    "Migration and compatibility sections",
    "partial",
    "Foreign standard-kit Sedona imports show execution/null/precision/infrastructure differences; unknown logic is rejected; proprietary vendor semantic reports pending",
)
add(
    "PKG-001",
    "Signed target packages",
    "Track compiler/module versions and target package provenance.",
    "Niagara Module Signing guide",
    "Signing a third party module",
    "pending",
    "Native compiler/package plugin contract",
)
add(
    "DATA-001",
    "Trend services",
    "Record timestamps, quality and units with bounded retention and export.",
    "Niagara Histories Guide",
    "History service concepts",
    "partial",
    "Simulation history/CSV; durable field trend service pending",
)
add(
    "PKG-002",
    "Hardware schema migration",
    "Preserve sensor/controller point connections during hardware-definition changes; show and verify every required remap.",
    "JCI Flash Sheet LIT-2026F17, May 22 2026",
    "3-4; Installation and Verifying connections after an upgrade",
    "pending",
    "Versioned native hardware-package mappings, migration review and target acceptance tests; do not substitute package definitions silently",
)
add(
    "SCHED-001",
    "Schedules and exceptions",
    "Support weekly and exception calendars, time zones and daylight saving.",
    "Niagara Scheduling Guide",
    "Schedule concepts",
    "partial",
    "Weekly schedule block; holidays/time zones/DST pending",
)
add(
    "REL-001",
    "Dependency view",
    "Trace incoming/outgoing references and effects of edits.",
    "Niagara Relations Guide",
    "Relations concepts",
    "pending",
    "Dependency explorer beyond visible graph wires",
)
add(
    "ALM-001",
    "Alarm lifecycle",
    "Provide thresholds, delays, acknowledgements, transitions and routing.",
    "ALC Eikon 3.02 Microblock Reference",
    "Alarm microblocks",
    "partial",
    "Threshold/on-delay simulation alarms; lifecycle/routing pending",
)

sedona = "Sedona framework doc/apps/apps.md and doc/network/sox.md"
add(
    "FMT-008",
    "Sedona SAX/SAB",
    "Create valid kit-linked applications and compile for the matching SVM.",
    sedona,
    "Applications; compiler",
    "implemented",
    "Pinned Sedonac compiles generated kits, SAX, real SAB and SCode for the local native SVM; physical platform images require their own ABI/kits",
)
add(
    "RUN-003",
    "Online component operations",
    "Add/edit/link components with version checks, rollback and verified target behavior.",
    sedona,
    "Sox add/write/link operations",
    "partial",
    "Native Sox add/write/link/delete on an owned SVM; native preflight, conflict checks, compensating rollback, persistent revisions and complete native export; field vendor adapters pending",
)
add(
    "OBC-001",
    "Executable reference sequences",
    "Use reference trajectories and functional tests to verify generated control behavior.",
    "OpenBuildingControl specification/example.rst",
    "Control-sequence verification",
    "partial",
    "Deterministic scenarios; G36 reference comparison pending",
)
add(
    "OBC-002",
    "Semantic lowering",
    "Map source execution/units/state into a target-specific intermediate representation.",
    "OpenBuildingControl specification/codeGeneration.rst",
    "Code generation",
    "partial",
    "Sedona standard-kit subset imports preserve backward-link scan delays; native code generation implements 27 blocks with independent VM comparisons; proprietary adapters pending",
)
add(
    "IO-001",
    "Physical input configuration",
    "Add a real unused sensor terminal and verify reliability/open-circuit on the target.",
    "User-authorized E2/F2 test",
    "Tailscale access supplied; connectivity checks follow programming completion",
    "pending",
    "Native application adapter and physical target test required",
)
add(
    "CODE-001",
    "2025 Title 24",
    "Deliver verified code-edition sequences and acceptance evidence for exact hardware.",
    "JCI application note LIT-2026F07",
    "18.0.2.6 release note",
    "pending",
    "Legacy 1630 eligibility and full system compliance unverified",
)
add(
    "AUD-001",
    "Change evidence",
    "Record intent, readback, ownership, original program hash and rollback outcome.",
    "Design inference from transfer/commissioning manuals",
    "Original engineering requirement",
    "implemented",
    "Hash-linked local audit; BACnet durable ownership journal",
)
add(
    "OSS-001",
    "Honest support status",
    "Separate implementation, external dependency and target validation in every adapter.",
    "Research synthesis",
    "Original engineering requirement",
    "implemented",
    "Capability matrix; unsupported formats fail explicitly",
)

with (PROJECT / "docs/FEATURE_REQUIREMENTS.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(requirements[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(requirements)
(PROJECT / "docs/requirements.json").write_text(json.dumps(requirements, indent=2))
print("Reference records:", len(refs), "feature criteria:", len(requirements))
