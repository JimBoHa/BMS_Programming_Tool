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
extra_sources = ROOT / "research/jci-native-2026-10-19/sources.json"
if extra_sources.exists():
    known = {r.get("sha256") for r in refs if r.get("sha256")}
    for item in json.loads(extra_sources.read_text()):
        if item["sha256"] in known:
            continue
        refs.append(
            {
                "vendor": "California Energy Commission"
                if item["filename"].startswith("CEC-")
                else "Johnson Controls",
                "title": item["filename"],
                "url": item["url"],
                "sha256": item["sha256"],
                "status": "downloaded and reviewed",
                "notes": "Native-target research 2026-10-19; certification list and declaration do not establish legacy-controller eligibility or supply native applications.",
            }
        )
        known.add(item["sha256"])
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
for title, url, note in [
    (
        "bbartling/pybog",
        "https://github.com/bbartling/pybog",
        "MIT; pinned 0248d941bf230aad2f19f9805be67c0e64bd51ef. Public native BOG encoding reference; independent builder fixture verified locally. No Niagara runtime acceptance claim.",
    ),
    (
        "Temco native compiler/interpreter verification",
        "https://github.com/temcocontrols/T3000_Building_Automation_System/tree/ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b",
        "MIT. Reproducible host of the manufacturer compiler/interpreter. Separate native BACnet program-slot transfer uses independently checked manufacturer wire layouts; physical hardware remains unverified.",
    ),
    (
        "MatIEC independent Structured Text compilation/execution",
        "https://github.com/beremiz/matiec/tree/3a41303bcb4e50403417bc39c63f88981d7d961e",
        "External GPL-3.0-or-later compiler with individually LGPL runtime headers; no compiler/runtime source bundled. All 27 blocks and nine example graphs compile to C and execute independently on this host. No physical PLC deployment claim.",
    ),
    (
        "Temco ESP32 program-transfer firmware reference",
        "https://github.com/temcocontrols/T3-programmable-controller-on-ESP32/tree/845973a37b91ac5ddac9c465787f2ab3a5037708",
        "Native private BACnet program service and actual 128-VAR limit reviewed. Original Python adapter; upstream source stays external. UDP, routed NPDU, readback, backup/restore and recovery tested locally.",
    ),
    (
        "BACnet-stack MS/TP encoding reference",
        "https://github.com/bacnet-stack/bacnet-stack/tree/e295d20baba977132b47bc09f61f28e12f2dfac3",
        "File-specific GPL-2.0-or-later with GCC exception and MIT. External C frame oracle only; no upstream code or binary bundled. See mstp-provenance.md.",
    ),
    (
        "Johnson Controls Metasys BasicServices 6.0.5 SDK",
        "https://www.nuget.org/packages/JohnsonControls.Metasys.BasicServices/6.0.5",
        "Manufacturer service SDK and XML API documentation downloaded locally; package SHA256 017cea3bb95da40fe565f77993f2451742fdb98cb53f72a694177b5cda7ec199. Server API access does not provide CCT native compilation, FCAccess or field-controller packages.",
    ),
    (
        "Niagara 4.10.9.14 manufacturer module/API reference",
        "https://downloads.onesight.solutions/iSMA/Niagara%20Software/IC%20Workbench/Software/",
        "Selected original signed modules and vendor documentation obtained from the public iC Workbench archive by HTTP ranges. Local-only descriptor, palette, slot, unit and format checks; no vendor code execution, runtime license or station acceptance established. No binaries/source redistributed.",
    ),
    (
        "ALC Integration Builder native symbol reference",
        "https://github.com/automatic-controls/integration-builder-eikon-script",
        "BSD-3-Clause public script/release archive reviewed locally. Native .logicsymbol ZIPs expose blocks, properties and coordinate wires; licensed EIKON/WebCTRL supplies symbol insertion/compilation. This is not an independent ALC equipment compiler.",
    ),
    (
        "ASHRAE 135-2001 Addendum b: Trend Log timestamps and ReadRange sequences",
        "https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-2001-135b.pdf",
        "Primary protocol reference for device-local log timestamps, ReadRange sequence ordering and wrap to 1. Implemented standard single-value Trend Log profile is tested with actual UDP/routed local services; physical devices and proprietary history formats remain unverified.",
    ),
]:
    if not any(r["url"] == url for r in refs):
        refs.append(
            {
                "vendor": "Open source / source research",
                "title": title,
                "url": url,
                "notes": note,
                "status": (
                    "Source/API/format metadata reviewed; no vendor runtime execution"
                    if title
                    in {
                        "Johnson Controls Metasys BasicServices 6.0.5 SDK",
                        "Niagara 4.10.9.14 manufacturer module/API reference",
                        "ALC Integration Builder native symbol reference",
                    }
                    else "source and local behavior reviewed"
                ),
            }
        )
(PROJECT / "docs/references.json").write_text(json.dumps(refs, indent=2))

requirements = []


def add(id, feature, criterion, source, pages, status, implementation):
    if any(row["id"] == id for row in requirements):
        raise ValueError(f"Duplicate feature criterion identifier: {id}")
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
    "Separate point services, sandbox/Sox changes and Temco program-slot backup/replacement/readback workflows. Temco physical validation and JCI/ALC/Honeywell native loaders remain pending",
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
    "Byte-exact no-op; scalar patches, guarded source rewires and prototype-checked added connections in observed native graph tables; jobInfo/simulationProperty retained",
)
add(
    "FMT-002",
    "Full JCI logic",
    "Create, rewire, compile and validate native applications for each supported model/release.",
    "OCT README and local CAF evidence",
    "Requirements; native container",
    "partial",
    "Observed native blocks/wires/order/positions can be inspected, compatible existing sources rewired and prototype-checked connections added offline. New block identities, complete semantics, packages, compiler and download adapter remain pending",
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
    "FMT-011",
    "Native CAF change review",
    "Compare exact native object/record identities, application and simulation values, wiring/order and opaque metadata while preserving both original files and review hashes.",
    "Authorized local CAF samples and parsed XML evidence",
    "Offline native-record inspection",
    "implemented",
    "CAF compare: bounded paged/filterable before/after values and full-record hashes; namespace-bound QName tokens, comments/PIs, mixed text and unknown records remain visible. No native compilation or compatibility approval",
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
    "implemented",
    "Simulation API clock/input quality, native UTC calendar control and shared-signal group cycle clock",
)
add(
    "SIM-004",
    "Multiple applications",
    "Simulate interacting programs through typed shared signals.",
    alc,
    "54-55",
    "implemented",
    "2–16 graph instances, typed/unit-checked previous-cycle links, atomic group cycles, common clock, quality faults and portable workspace files",
)
add(
    "UI-003",
    "Resource/error view",
    "Show target resource accounting and errors beyond drawing correctness.",
    alc,
    "50-51",
    "partial",
    "Node/terminal constraints, real Temco compiler byte counts and conservative target program budget; complete per-controller RAM/flash/cycle estimates pending",
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
    "implemented",
    "Versioned typed single-output libraries, nested instances with independent state, graphical definition editing/apply/discard, draft recovery, bounded expansion and dependency-closed portable exchange",
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
    "implemented",
    "Internal graph simulation holds/releases, independent override maps, computed-value/force traces and timed force events; source faults do not get bypassed",
)
add(
    "DBG-001",
    "Live debug",
    "Watch selected signals and show force state without silently clearing others.",
    spyder,
    "367-376",
    "partial",
    "Core graph values/force badges and native Sox value/link readback; proprietary field-application internal watch pending",
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
    "partial",
    "Numbered source conversion, manufacturer compiler/interpreter execution and explicit native program-slot transfer, backup, readback and compensating restore over real UDP/routed BACnet. Physical hardware, scan cadence, calendar host and whole-device configuration remain unverified",
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
    "implemented",
    "Zoom, drag/link/minimap, Shift selection, group movement/alignment, internal-wire copy/duplicate, delete and undo; browser verified",
)
add(
    "FMT-007",
    "Migration reports",
    "Describe incompatible types/services instead of dropping them silently.",
    "Niagara AX to N4 Migration Guide",
    "Migration and compatibility sections",
    "partial",
    "Foreign standard-kit Sedona and supported native Niagara BOG/Control Basic imports report execution/null/precision/priority/infrastructure differences; unknown logic is rejected; full proprietary mappings pending",
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
    "implemented",
    "Bounded durable simulation and explicit read-only BACnet field sampling, UTC acquisition/receipt timestamps, verified or unknown quality, unit labels, cursor queries and CSV. Field jobs require a connected interface, stop on change/fault and never resume automatically. Separate explicit Trend Log history retrieval preserves original device timestamps and immutable captures",
)
add(
    "DATA-002",
    "Existing BACnet device history",
    "Retrieve standard single-value Trend Log records with bounded forward ReadRange pagination, explicit device timezone, unresolved-clock evidence, quality and partial-result reporting; save immutable captures without polling or device writes.",
    "ASHRAE 135-2001 Addendum b; BACpypes3 0.0.110 primary datatypes/APDU definitions",
    "Trend Log and ReadRange sections",
    "implemented",
    "Real UDP/routed local services, all 11 LogRecord alternatives, DST/sequence wrap/gaps, timeouts/cancellation, sealed captures, browser JSON/CSV provenance and restart tested. Physical devices, Trend Log Multiple and proprietary histories remain outside profile",
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
    "implemented",
    "IANA zones, both DST folds/skipped minutes, dated closure/window exceptions with explicit overnight precedence; compiled exports require explicit host calendar binding",
)
add(
    "REL-001",
    "Dependency view",
    "Trace incoming/outgoing references and effects of edits.",
    "Niagara Relations Guide",
    "Relations concepts",
    "implemented",
    "Direct and transitive dependencies, affected outputs, memory boundaries and click-through block navigation in the inspector",
)
add(
    "ALM-001",
    "Alarm lifecycle",
    "Provide thresholds, delays, acknowledgements, transitions and routing.",
    "ALC Eikon 3.02 Microblock Reference",
    "Alarm microblocks",
    "implemented",
    "Graph thresholds/on-delay, durable activation/return/acknowledgment/reactivation and operator notes. Explicit source/event webhook routes use a durable ordered outbox, bounded retries, stable idempotency keys, uncertain receipts, gap evidence and restart-off activity. Receipts do not acknowledge alarms. Native intrinsic alarms, SMTP/email and human receipt remain outside this profile",
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
    "Read-only checks authorized: site Mac reachable, target network route unavailable",
    "pending",
    "Site Mac reached through Tailscale; no approved target subnet route visible and both NAE HTTP/HTTPS probes timed out. Credentials not read/authentication not attempted. Native application adapter and physical sensor test still required",
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

add(
    "FMT-009",
    "Niagara BOG interchange",
    "Read native component relationships, preserve unknown archive data and convert only verified primitive semantics with a visible review report.",
    "Tridium kitControl guide; Niagara troubleshooting presentations; public pybog source",
    "Native component slots, XML/BOG encoding and protection",
    "partial",
    "20 graph kinds map to real BOG ZIP/XML (including composite Clamp and native Scale/Convert); independent pybog fixture converts. Genuine manufacturer descriptors verify types, inherited slots, link types, units and aliases. Unknown logic and malformed status/configuration fail explicitly. Workbench/station runtime acceptance, stateful components and full station services remain unverified",
)
add(
    "COMM-004",
    "Direct serial BACnet MS/TP",
    "Implement framing, CRCs, token management and bounded point services through a selected serial adapter.",
    "BACnet-stack pinned MS/TP implementation and frame encoder",
    "Legacy master FSM, Annex G CRC examples and independent C frame fixtures",
    "partial",
    "Real Python token master and BACpypes3 data link; HTTP discovery/ReadProperty verified over OS pseudoterminals. Automatic-direction no-echo RS485 hardware required; physical timing, BTCVT, extended frames and proprietary downloads unverified",
)
add(
    "SIM-007",
    "Independent IEC execution",
    "Compile generated Structured Text with an independent compiler and compare native output, fault and retained-state behavior against the reference simulator.",
    "MatIEC pinned compiler and vendor simulation workflows",
    "Generated IEC source, runtime driver and independent scan tests",
    "implemented",
    "Real MatIEC to C to Clang execution for all 27 blocks and nine examples; explicit REAL32 differences, quality faults, calendars, macros, timed events and bounded process cleanup. Host verification only",
)
add(
    "FMT-010",
    "Native hardware-definition migration review",
    "Inspect native point types, unit profiles, aliases and presets, then identify binding and parameter changes between device-definition revisions without inventing application objects.",
    "JCI OCT native NS8000 DynamicHardwareDefinition and CCT hardware workflows",
    "Native Interface XML, Measurement, Enum, Bus and Preset records",
    "implemented",
    "Offline typed metadata selection, collision rejection, exact original export and source-hashed migration reports. Sensor metadata does not provide PCV/VMA object allocation, compiler or device writes",
)

add(
    "SIM-008",
    "Native CAF saved simulation inputs",
    "Export and edit archive-bound native saved simulation values while preserving ordinary program properties and refusing unknown enum/type/version semantics.",
    "JCI Controller Tool Help: Simulation mode; authorized local native CAFs",
    "Saved startup simulation settings; simulationProperty records",
    "implemented",
    "Complete source-hashed profiles, observed float32/boolean guards, exact native readback, byte-preserving unknown data, bounded profile size, explicit draft handling and real browser downloads. No JCI execution or hardware acceptance claim",
)
add(
    "COMM-005",
    "BACnet/IP foreign device through BBMD",
    "Explicitly register, renew, discover and use point services across a BBMD while preserving lease health, exact recovery configuration and deterministic teardown.",
    "BACpypes3 pinned IPv4/BVLC source; ASHRAE 135-2004 Addendum m",
    "BVLC registration/result/distribution; TTL and grace period",
    "implemented",
    "Independent raw UDP BBMD/device peers verify registration, forwarded discovery, reads, real 31-second expiry, cancellation/bind cleanup and owned-command recovery. Physical/site BBMD validation remains unverified; this does not provide controller programming",
)

with (PROJECT / "docs/FEATURE_REQUIREMENTS.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(requirements[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(requirements)
(PROJECT / "docs/requirements.json").write_text(json.dumps(requirements, indent=2))
print("Reference records:", len(refs), "feature criteria:", len(requirements))
