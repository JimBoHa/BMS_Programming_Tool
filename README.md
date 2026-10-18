# BMS Studio

A local graphical control editor, deterministic simulator, format workbench, and BACnet/Modbus commissioning application. This repository is a **development build**, not a complete universal replacement for CCT, PCT, EIKON, Spyder, or Niagara Workbench.

The current implementation creates and executes **our own control graphs**. It inspects real Johnson Controls CAFs and makes narrow, loss-preserving offline scalar edits. It does **not** compile new CAFs or download applications into VMA1630, FX-PCV1630/1615, ALC, Honeywell, or Niagara controllers. BACnet point writes and application programming are different operations.

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

- Drag blocks from the palette, connect pins, edit units/properties, duplicate/delete blocks, undo/redo, and save numbered revisions. Double-click a wire to remove it.
- Simulate numeric/boolean I/O, PI control with conditional anti-windup, math, logic, hysteresis, scan delays, on-delay timers, rate limits, alarms, and weekly schedules. Inject open-circuit/stale/missing input quality. Run timed scenarios and export traces.
- Export BMS JSON, IEC 61131-3 Structured Text, PLCopen TC6 v2.01 XML with an ST body, and GraphML. Re-import Studio-generated interchange files with a consistency check. Edited or unsupported foreign source is rejected instead of silently losing logic.
- Inspect observed JCI ZIP/XML CAFs, including FX and Metasys release modes 10.1 and 10.2. Keep unknown objects, native metadata and simulation properties. Export unchanged files byte-for-byte or patch selected existing scalar values into a separate copy.
- Connect via BACnet/IP, including an explicit IP router and remote DNET/MAC address. Read objects/properties and preview a command at an unused priority slot. Read back and relinquish owned commands. Command ownership is journaled before transmission so timeouts/restarts retain a recovery path.
- Read Modbus TCP registers and serial Modbus RTU registers/coils with framing and CRC validation. USB and Bluetooth serial ports are enumerated through the operating system.
- Apply online changes to the **local BMS Studio sandbox runtime** with preflight execution, generation checks, compatible state retention, backups, audit entries and rollback. This does not alter proprietary firmware. Sandbox scan state and its rollback snapshots live in memory for the current process; saved project revisions and audit records persist.

See [the capability matrix](docs/capabilities.json) and [feature criteria](docs/FEATURE_REQUIREMENTS.csv) for exact scope. These are also visible in the Reference workspace.

## Important distinctions

- The nine example graphs cover cooling-only, inline reheat without a fan, and parallel fan-powered reheat for the BMS runtime and FX/Metasys target profiles. They are illustrative sequences, **not 2025 Title 24 certification, complete Guideline 36 implementations, or native CAF files**.
- An offline CAF patch is not vendor compiler validation. Open the edited copy in matching licensed CCT/PCT, verify its resource/package compatibility, and compare its behavior before a field download.
- Selecting a controller model records intent. It does not make our generic graph executable on that controller. Hardware capacity, execution semantics, firmware and native download protocols still apply.
- Generic Bluetooth/USB serial access is not BTCVT support or an MS/TP master. BACnet/SC, BBMD/foreign-device registration, direct MS/TP token handling and BTCVT native transports are not implemented.
- Standard BACnet point services do not create a physical sensor input or modify a CAF application. E2/F2 testing has not occurred; the network route is pending.
- Simulation holds prior outputs after a failed scan and stops continuous sandbox execution. No physical output driver or independent failsafe is implemented. Do not use this development runtime for unattended equipment control.

## Interchange semantics

The graph runtime uses finite Python floating-point numbers, strict booleans, named ports, explicit engineering units and deterministic topological execution. Feedback requires a one-scan memory block. Scan state and outputs commit only after the entire scan succeeds. Fault input quality fails the scan instead of substituting a plausible value.

Generated ST supplies `StudioScanSeconds`, `StudioDayOfWeek` (Monday = 0), `StudioMinuteOfDay` and per-input validity flags as explicit inputs. It stages outputs and state before committing. It uses IEC `REAL`; precision, overflow, scheduling, retention and I/O mapping must be checked with the destination compiler/runtime. PLCopen XML is schema-validated locally against the public TC6 v2.01 schema, but that alone does not prove a particular PLC compiler accepts or executes the generated program.

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

Native vendor encoders/compilers, full native imports/conversions, BTCVT/direct MS/TP, field application download/online modification, E2/F2 hardware verification, certified sequences, complete scheduler/alarm/trend services, target packaging and broader acceptance tests remain incomplete. The user's instruction was to push after every requested feature works; this development build has not been pushed as a finished universal tool.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). JCI interoperability dictionaries retain OCT attribution. Vendor names and trademarks identify compatibility targets; this project has no vendor affiliation.
