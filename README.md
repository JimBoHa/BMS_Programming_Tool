# BMS Studio

A local graphical control editor, deterministic simulator, format workbench, and BACnet/Modbus commissioning application. This repository is a **development build**, not a complete universal replacement for CCT, PCT, EIKON, Spyder, or Niagara Workbench.

The implementation creates and executes **our own control graphs**, compiles them into real Sedona kits/SAX/SAB/SCode and Temco Control Basic bytecode, and compares native interpreter outputs with the graph engine. It imports defined subsets of foreign Sedona, Niagara BOG and Control Basic applications with conversion reports. It inspects real Johnson Controls CAFs and supports loss-preserving scalar edits and guarded native wiring changes. A separate Temco adapter performs real native BACnet program-slot transfer and readback against isolated UDP/routed emulators; physical execution is unverified. It does **not** compile new CAFs or download applications into VMA1630, FX-PCV1630/1615, ALC, Honeywell or Niagara controllers. BACnet point writes and application programming are different operations.

## Run locally

Requirements: Python 3.11+ (3.13 recommended) and Node.js 22.12+ to build the UI. The already configured workspace has a virtual environment and built UI assets. On that Mac, double-click `Launch BMS Studio.command`, then open <http://127.0.0.1:8765>.

From a fresh source checkout:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[test]'
cd web
npm ci
npm run build
cd ..
.venv/bin/python -m bms_tool serve
```

The app binds to loopback. It has no cloud account or cloud storage. Project revisions, audit records and BACnet command recovery live in `.state/`, excluded from Git. Field network sockets open only when the user connects an interface. Restarting does not erase the record of owned BACnet commands; reconnect the saved interface and relinquish them explicitly.

For UI development, run `npm run dev` in `web/` alongside the Python server. The Vite server proxies `/api` to port 8765.

## Working features

- Drag blocks from the palette, connect pins, edit units/properties, and save numbered revisions. Shift-click multiple blocks to move, align, copy, duplicate or delete them together; internal wires follow the copied selection. Undo restores a group operation. Double-click a wire to remove it.
- Extract a one-output internal selection into a typed reusable macro. Nest definitions, instantiate independent control state, inspect dependencies and edit a definition graphically with apply/discard. Draft recovery retains the parent project after a browser reload. Export/import portable macro libraries with their dependencies; conflicts and deletion of used definitions are rejected. Root I/O stays outside definitions. Compilation expands bounded, deterministic ordinary blocks while source exports retain the editable hierarchy.
- Simulate numeric/boolean I/O, PI control with conditional anti-windup, math, logic, hysteresis, scan delays, on-delay timers, rate limits, alarms, and weekly schedules. Inject open-circuit/stale/missing input quality. Run timed scenarios and export traces.
- Calendar schedules support IANA time zones, daylight saving and dated exceptions. Disabled dates close the entire local day; enabled exception windows replace its weekly periods. Own-date exceptions suppress incoming overnight periods. Repeated autumn minutes run in both folds; skipped spring minutes never occur. The Program simulator accepts an optional UTC clock for the next scan. Compiled calendar exports require explicit destination-host calendar values and validity flags; they do not embed an IANA database.
- Enable **Persist history** to retain successful simulation scans in SQLite with simulation/receipt timestamps, types, quality and units. **Trends & alarms** filters sources, pages samples, exports the shown CSV and retains activation, return, acknowledgment and reactivation events. Acknowledgment records an operator note without clearing the condition. Every reactivation creates a new occurrence. End an abandoned simulation source to close its active occurrences with a distinct source-ended event, then acknowledge them before retirement. Unresolved alarms prevent source retirement. Recording errors are reported separately from scans that already executed; a batch fault reports how many scans completed and preserves their evidence. This service does not acquire field trends or deliver external alarm notifications.
- Hold and release any core graph block's output during simulation. The block continues computing its underlying state, and source faults still stop the scan. The canvas marks applied holds, the inspector distinguishes requested changes from the last completed scan, and traces/CSV retain both held and computed values. Timed scenarios can replace the force map at a cycle boundary. These temporary overrides are not written into program exports or sent to field controllers.
- Trace a block's direct/transitive dependencies, affected outputs and previous-scan memory boundaries from the inspector. Follow related blocks without searching the entire diagram.
- Simulate 2–16 graph instances together in **System sim**. Typed/unit-checked links read the preceding cycle; every program commits its state and outputs together. A failed cycle leaves all programs unchanged. Use a common clock, persistent external input values, bounded fault/history records, and portable `.bms-workspace.json` save/reopen. A multi-cycle request keeps earlier successful cycles if a later cycle fails. Sessions stay in memory for up to one idle hour and can be reopened within the same server process; source definitions persist through exported files.
- Compile exported ST in **IEC native** with independent MatIEC, compile the generated C using Clang, and execute a persistent native process. Compare all scans, retained output/fault behavior, quality validity, calendars, macros and timed input events with the separate graph engine. Download actual ST/C and full native traces; REAL32 precision/overflow differences remain visible. See [IEC execution](docs/iec-native.md).
- Export BMS JSON, IEC 61131-3 Structured Text, PLCopen TC6 v2.01 XML with an ST body, and GraphML. Re-import Studio-generated interchange files with a consistency check. Edited or unsupported foreign source is rejected instead of silently losing logic.
- Compile native Sedona application bundles containing the generated kit source, kit binary, SAX, executable SAB, simulator SCode image, provenance and upstream license. All 27 graph blocks execute in a separate native SVM. The GUI compares actual Sox-read outputs with the separate Python reference engine and exposes an explicit UTC scan clock.
- Convert supported foreign Sedona SAX/SAB containing standard math, Boolean, constant and writable-point components into editable graphs. Preserve source ordering through explicit previous-scan delays. A visible report identifies null/fault behavior, precision and infrastructure changes. Unknown logic/services and missing kit checksums stop conversion.
- Export native Niagara BOG ZIP/XML for 17 primitive graph types. Import supported foreign kitControl math/logic and numeric/Boolean writable components with explicit event, status, priority and infrastructure differences. Unsupported executable configuration, links, archive resources and protected content stop conversion. Independent pybog fixtures and genuine manufacturer module/API metadata check native types, inherited slots, links, units and palette aliases. Niagara station execution remains unverified. See [the native BOG profile](docs/niagara-bog.md).
- Export numbered Temco Control Basic, compile real bytecode with the pinned manufacturer's compiler and execute the actual native decode interpreter in **Temco native**. Explicit local IN/OUT/VAR point mappings, fixed-point resolution, output comparisons and precision/overflow differences are visible. Supported foreign source converts semantically; arbitrary loops, remote point operations and native services remain outside the profile. See [Temco native verification](docs/temco-native.md).
- Inspect native JCI device-definition XML in **JCI hardware**, including typed imperial/metric points, BACnet identities, aliases and native presets. Review validated engineering selections and changes in bindings, parameters and interface metadata between revisions. Exact original XML and separate JSON plans are downloadable. This offline sensor metadata profile does not create CAF objects. See [hardware definitions](docs/jci-hardware-definition.md).
- Replace a pinned Temco program slot through real native BACnet private transfers in **Temco native**. Inspect the exact model/firmware/device/slot, create a durable original-image backup, review a five-minute plan, stop the slot, write all five native chunks, read back and conditionally resume. Failures attempt bounded compensating restoration while retaining the connection lock; uncertain restart state stays visible without automatic field writes. Restore plans use saved backup run state. The firmware profile refuses unprovisioned calendars and VARs above 128; physical I/O/scan cadence/flash persistence remain unverified. See [Temco transfer](docs/temco-transfer.md).
- Inspect observed JCI ZIP/XML CAFs, including FX and Metasys release modes 10.1 and 10.2. Keep unknown objects, native metadata and simulation properties. Export unchanged files byte-for-byte or patch selected existing scalar values into a separate copy. Inspect native blocks, positions, execution order and connections. Rewire an existing source only when its opaque native type/configuration, proven output property and execution ordering match the observed schema. Prototype-checked connections can also be added between existing compatible blocks, with unused destination and execution-order guards. These are offline edits, not vendor compilation. See [native CAF graph handling](docs/caf-native-graph.md).
- Connect via BACnet/IP, including an explicit IP router and remote DNET/MAC address. Read objects/properties and preview a command at an unused priority slot. Read back and relinquish owned commands. Command ownership is journaled before transmission so timeouts/restarts retain a recovery path.
- Open a selected serial interface as a fixed-address legacy BACnet MS/TP master. CRCs, framing, token management, retries, immediate/deferred replies and a bounded serial worker connect BACpypes3 point services to the bus. Tests exercise production HTTP discovery and ReadProperty through actual pseudoterminals. Physical RS485 timing and adapters remain unverified. Requires automatic-direction hardware without echo; this is not the BTCVT Bluetooth protocol. See [direct MS/TP setup and limits](docs/mstp-transport.md).
- Record addressed BACnet field values in **Field trends** using explicit read-only jobs on the connected interface. Verify reliability/status/out-of-service or retain unknown quality; acquisition failures generate events without fabricated values. Samples persist with UTC acquisition/receipt times and CSV export in a separate field database. Jobs stop when the interface changes and never resume after restart. See [field trend acquisition](docs/field-trends.md).
- Read Modbus TCP registers and serial Modbus RTU registers/coils with framing and CRC validation. Tests use actual TCP sockets and an OS pseudoterminal, including fragmented serial responses and bad-CRC rejection. USB and Bluetooth serial ports are enumerated through the operating system; physical adapters remain untested.
- Apply online changes to the **local BMS Studio sandbox runtime** with preflight execution, generation checks, compatible state retention, backups, audit entries and rollback. This does not alter proprietary firmware. Sandbox scan state and its rollback snapshots live in memory for the current process; saved project revisions and audit records persist.
- Add/write/link/unlink/delete real native components over Sox in an owned loopback SVM. Preview runs the proposed operations on a second native VM. Apply checks the original configuration, records a backup, and supports compensating rollback. Save the running native application as a project revision or export it with all added components, null-valued configuration and wiring. Reopening the project restores the native application. A graphical native palette/wiring view and unused-input/null-value example are included. Native operations are sequential, not atomic; the control graph outside the `/online` test folder retains its running state.

## Optional native Temco toolchain

The configured Mac already has the pinned manufacturer compiler/interpreter host. A fresh checkout needs `git` and a C++ compiler:

```sh
.venv/bin/python scripts/setup_temco.py
```

The script obtains the MIT upstream revision `ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b` and builds isolated copies outside this repository. It records source/build hashes and checks executable integrity before use. The compiler/interpreter host simulates local points. A separate Python adapter implements the observed native program-slot service and has real UDP/routed emulator tests; it does not establish physical controller execution. All 27 blocks are available within the documented fixed-point/resource profile. Calendar programs require explicit host active/valid values. Native hardware compatibility remains a separate target test.

See [native target support](docs/NATIVE_TARGETS.md), [the capability matrix](docs/capabilities.json) and [feature criteria](docs/FEATURE_REQUIREMENTS.csv) for exact scope. These are also visible in the Reference workspace.

## Optional independent IEC compiler

The configured Mac already has MatIEC and a private GNU Bison build. A fresh checkout with Git, Clang/Clang++, Flex, Make and m4 can run:

```sh
.venv/bin/python scripts/setup_iec.py
```

The script builds pinned source outside this repository, preserving the original checkout. The application verifies compiler/runtime-library hashes and accepts validated Studio graphs only. Native executable export and physical I/O are outside this host verification profile. See [compiler provenance and limits](docs/iec-native.md).

## Optional native Sedona toolchain

The configured Mac already has a private, checksum-verified Eclipse Temurin 17 JDK and the native toolchain. A fresh checkout needs a JDK 17 installation and a pinned external Sedona checkout. Stop active native simulations before rebuilding the SDK:

```sh
.venv/bin/python scripts/setup_sedona.py --java-home '/path/to/jdk/Contents/Home'
```

The script builds the compiler, standard kits and an experimental 64-bit Unix SVM from revision `406b11f3816fb00db6482640f9cf3397b874b515`. All port changes are reproduced in the script; original upstream source stays intact. The native simulator binds sockets to loopback and starts only from **Native sim → Compile and start**. It uses randomly generated local credentials, passed through stdin rather than command arguments. Exported bundles have no network user or Sox service.

Interactive native simulation advances the main graph only when explicitly stepped. Exported applications enable automatic scans at the configured program interval. Calendar inputs and physical I/O bindings must be supplied by the destination runtime. Additional native components run on the native application cycle; their value/link readback is distinct from the main graph's reference comparison. Projects containing those components use Native sim and native/JSON export; portable simulation and ST/PLCopen/GraphML export refuse to omit them.

Set `BMS_SEDONA_HOME` and `BMS_JAVA` to use another installed location. Compiler/manifest access is serialized across threads and processes. Physical Sedona devices require a matching platform image, native services, ABI and installed kits. The included SCode image targets the local Unix simulator. The port is not a Sedona-certified platform.

The upstream broad test harness contains `AppTest.verifyCallbacks` assertions that read an object after `App.remove` frees it. The local verification records that failure rather than treating it as a passed platform certification. Our native structural-operation tests verify readback, links and rollback without dereferencing freed objects.

## Important distinctions

- The nine example graphs cover cooling-only, inline reheat without a fan, and parallel fan-powered reheat for the BMS runtime and FX/Metasys target profiles. They are illustrative sequences, **not 2025 Title 24 certification, complete Guideline 36 implementations, or native CAF files**.
- An offline CAF patch is not vendor compiler validation. Open the edited copy in matching licensed CCT/PCT, verify its resource/package compatibility, and compare its behavior before a field download.
- Selecting a controller model records intent. It does not make our generic graph executable on that controller. Hardware capacity, execution semantics, firmware and native download protocols still apply.
- Generic Bluetooth/USB serial access is not BTCVT support. The direct MS/TP master is tested through pseudoterminals; physical bus timing and adapters remain unverified. BACnet/SC, BBMD/foreign-device registration, extended MS/TP frames and BTCVT native transports are not implemented.
- Standard BACnet point services do not create a physical sensor input or modify a CAF application. The user supplied Tailscale access for E2/F2 and requested connectivity checks after programming completion. Those checks and field testing have not occurred.
- Simulation holds prior outputs after a failed scan and stops continuous sandbox execution. No physical output driver or independent failsafe is implemented. Do not use this development runtime for unattended equipment control.

## Interchange semantics

The graph runtime uses finite Python floating-point numbers, strict booleans, named ports, explicit engineering units and deterministic topological execution. Feedback requires a one-scan memory block. Scan state and outputs commit only after the entire scan succeeds. Fault input quality fails the scan instead of substituting a plausible value.

Project hashes use canonical JSON so object-key insertion order does not change identity during export/re-import. Stored revisions record their checksum format. Existing revisions retain their original content, hashes and audit records; loads verify either the original model-JSON hash or the new canonical-JSON hash and reject corruption.

Generated ST supplies `StudioScanSeconds`, `StudioDayOfWeek` (Monday = 0), `StudioMinuteOfDay` and per-input validity flags as explicit inputs. It stages outputs and state before committing. It uses IEC `REAL`; precision, overflow, scheduling, retention and I/O mapping must be checked with the destination compiler/runtime. PLCopen XML is schema-validated locally against the public TC6 v2.01 schema, but that alone does not prove a particular PLC compiler accepts or executes the generated program. The optional IEC verifier independently compiles the exported ST through MatIEC into native C and compares actual execution with the graph engine. This host profile does not establish physical PLC compatibility. Sedona lowering uses the same bounded statement representation and is independently compiled/executed in the native SVM. Sedona's special null/NaN equality semantics have their own explicit guard and regression test.

## Research

[Research findings](docs/RESEARCH.md) distinguishes complete open authoring/runtime projects from protocol libraries, vendor-dependent extensions and source-available projects. [Reference sources](docs/references.json) records public links. The full downloaded manuals, extracted text, original CAFs, installers and VM remain outside this repository; their copyrights and confidentiality notices remain intact.

The reviewed vendor restrictions are tracked as desired improvements with evidence. Product lock-in and avoidable workflow limits become requirements. Physical I/O limits, data types, incompatible execution models and permissions become explicit adapter constraints; silently discarding them would produce incorrect controller programs.

## Verify

```sh
.venv/bin/pytest -q
cd web
npm run build
npx playwright install chromium
npm run test:e2e
```

Local private sample verification is optional and never uploads the building files:

```sh
BMS_TEST_CAF_DIR='/path/to/authorized/CAF files' .venv/bin/pytest -q
```

Network integration tests bind only loopback. They use real UDP/TCP and a virtual BACnet data link for routed NPDU tests. They do not scan the building network or prove physical MS/TP timing. See [validation results](docs/VALIDATION.md).

## Remaining work before the requested final push

Proprietary JCI/ALC/Honeywell encoders/compilers, full native imports/conversions, BTCVT, JCI/ALC/Honeywell field application download/online modification, physical MS/TP and E2/F2 hardware verification, certified sequences, native device history import, external alarm delivery and physical target packaging remain incomplete. The Windows VM's installed-program registry and vendor application directories were inspected: CCT/PCT was not present in that inventory. The VM was shut down after the check. Matching licensed JCI tooling/controller packages or authoritative independent format/compiler/protocol specifications are still needed for verified FX/VMA application support. The [additional native-toolchain investigation](docs/jci-native-research-2026-10-19.md) identifies the missing dependencies and distinguishes CAF release mode from firmware. The user's instruction was to push after every requested feature works; this development build has not been pushed as a finished universal tool.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). JCI interoperability dictionaries retain OCT attribution. Vendor names and trademarks identify compatibility targets; this project has no vendor affiliation.
