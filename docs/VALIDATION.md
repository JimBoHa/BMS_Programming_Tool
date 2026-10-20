# Validation record — 2026-10-19

This development build validates the stated local behavior. It does not establish universal native-controller compatibility. [Native target support](NATIVE_TARGETS.md) records the remaining compiler, format and field-deployment gaps.

## Automated checks

- The final full backend run passed **948 tests with no skips in 165.40 seconds**, including all seven authorized CAFs, genuine external Niagara descriptors, independent native IEC execution, real UDP/routed Temco transfer/recovery and existing simulation/transport/storage coverage.
- **39 browser workflows passed in approximately 1.2 minutes** against the production TypeScript/Vite build. They cover existing authoring, macros, calendars, simulation, storage, CAF/BOG and field workflows plus genuine IEC compilation/execution, input-quality faults, timed recovery scenarios, native Temco transfer/restore and JCI hardware migration. Temco browser coverage also verifies that source edits cannot hide a completed transfer outcome and that restore previews use the backup run state.
- Ruff, TypeScript and production Vite build checks pass. Workspace pages load in separate bundles; the main bundle is approximately 413 kB before gzip. Screenshots of native formats, compiled traces, serial settings and field samples were visually inspected.
- Nine PLCopen example exports previously validated against an independently retrieved TC6 v2.01 XSD. Schema provenance: <https://raw.githubusercontent.com/mattsse/plcopen-xml-xcore/master/schema/tc6_xml_v201.xsd>. XSD conformance is not external PLC compiler acceptance.
- The environment uses Python 3.13.16, Node 22.23.3, FastAPI 0.146.0, Pydantic 2.14.1, BACpypes3 0.0.110 and Vite 7.3.7. Dependency pins are unchanged from the recorded advisory audit. Upstream Starlette TestClient and pybog Pydantic deprecation warnings remain; they are not failed checks.

Full test output and screenshot artifacts remain in ignored `local-reports/` and `web/test-results/`. Original controller programs, installed SDKs, manuals, VM images and credentials are not part of the code repository.

## Graph semantics and durable state

Tests verify strict types/units, explicit feedback memory, staged state/output commits, PI antiwindup/reverse action, hysteresis, timers, fault injection and finite arithmetic. A failed scan holds previous state/outputs. Internal forces replace a computed value after normal evaluation; source faults still stop the scan. Traces distinguish held and underlying values.

Typed reusable macros support nesting, independent state, bounded expansion, feedback without added scan latency, dependency closure, guarded library exchange, graphical apply/discard and browser draft recovery. Portable and native source-preserving formats retain their editable hierarchy. Shared-system simulation uses previous-cycle typed links and commits all program instances together.

Calendar tests cover IANA zones, both autumn folds, skipped spring minutes, date rollover, leap dates, closures, replacement windows and overnight precedence. Compiled calendar programs require explicit destination-host values and validity flags; they do not contain an IANA timezone database.

Simulation observations preserve simulation/receipt UTC timestamps, types, units and quality in SQLite. Alarm activation/return/acknowledgment/reactivation and explicit source ending remain distinct events. A partial batch reports completed scans, scan errors and recording failures separately. Audit completion failures cannot imply a committed acknowledgment or deletion rolled back.

Each observation database now retains a source-kind marker. Established field/simulation stores cannot be reopened under the other kind. Legacy unmarked stores containing evidence retain simulation identity. Tests cover migration, restart, corruption, concurrent access, bounds and retirement. Program revisions retain their legacy checksum format and audit history; new revisions use canonical JSON hashes and verify integrity on load.

## Native Sedona execution and online changes

The actual pinned Sedonac compiler builds kit binaries, SAX, SAB and SCode. All 27 blocks and the nine illustrative profiles execute in a separate native C SVM and compare with the Python graph engine. The SDK independently decodes the generated SAB. Source/build provenance and upstream license remain in exported bundles.

A second native VM preflights real Sox add/write/link/unlink/delete operations. Apply checks original configuration, records backups and verifies readback. Deliberately dropped-write tests verify compensating restoration. Saved native components, null configuration and wiring survive revisions and export/import/restart. Native operations are sequential, not atomic. Calendar and physical I/O bindings remain destination-host responsibilities.

The SDK revision is `406b11f3816fb00db6482640f9cf3397b874b515`. The reproducible 64-bit Unix port leaves upstream tracked source unchanged and binds the local simulator to loopback. The broader upstream harness contains `AppTest.verifyCallbacks` assertions accessing an object after removal frees it; that observed failure is not counted as platform certification. Physical Sedona platforms require their own matching ABI, kits and services.

## Native Temco compilation and interpretation

The MIT manufacturer source is pinned at `ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b`. Reproducible isolated build copies adapt Windows helpers and preserve the 32-bit integer ABI. Real manufacturer bytecode executes in the actual decode interpreter with in-memory point frames; no field transport is present.

All 27 blocks have native execution tests. Changing-input trajectories verify retained state, delayed feedback, nonzero initialization, PI antiwindup, timer saturation, staged fault holds and nested macros. All nine VAV profiles match 60 native scans; final bytecode sizes are 388 bytes for cooling-only, 689 for inline reheat and 923 for parallel fan-powered reheat. These remain illustrative sequences, not Title 24 or Guideline 36 certification.

Schedule tests verify explicit host active/valid bindings through DST, exceptions and minute boundaries. The native interpreter verifies gating/publication; the host evaluates IANA calendars. Native fixed-point quantization and overflow differences remain visible at every scan. The comparison uses 0.01 absolute or 0.001% relative numeric tolerance and exact Boolean outputs. Unsupported quality, source statements, bindings and resource sizes fail visibly. Checked authoring annotations cannot conceal a changed native executable body. A region-poisoned AddressSanitizer run exposed a local-table overwrite before the upstream compiler's later output-size rejection. Source preflight now bounds symbols, local storage, expression operands/postfix slots and statement encoding before native execution. A separate regression keeps REMARK assignments executable while stripping only actual REM comments.

Six real browser workflows cover native source/bytecode downloads, custom points, changed input values, bad-quality errors, retained-state traces, explicit UTC clocks, foreign-extension rejection and overflow mismatch. See [the complete native profile](temco-native.md).

## Native Niagara BOG and authorized CAFs

BOG tests exercise real ZIP/XML, typed component slots, four-input reductions, forward consumers, aliases, local ORD links, finite facets, status handling, source consistency and rejection of unsupported executable configuration. An independently authored public pybog generator creates an application that imports and computes `100 - 40 = 60`. There is no Niagara station/Workbench runtime acceptance test.

An additional 22 tests parse genuine external manufacturer module/API metadata.
They verify component declarations, inherited frozen property types, emitted
link endpoints, six complete serialized unit records and real palette aliases.
This exposed and corrected document-wide alias visibility, invalid bare unit
facets and compact scalar values that native complex status slots would ignore.
JARs and reference source remain outside Git; no Niagara implementation code
was incorporated or executed. Native runtime licensing/acceptance remains
unestablished. See [the exact evidence and member hashes](niagara-bog.md).

The separate inspector returns original BOG bytes exactly, including protected content, unknown typed records and extra archive members. HTTP tests verify upload/session guards, unsafe input rejection and bounded cache eviction. Browser workflows verify opaque ZIP and raw XML inspection/export without station connections.

Seven authorized CAF files include MS-VMA1630-0, FX-PCV1630-0 and FX-PCV1615-0 in release modes 10.1/10.2. Original files were not changed or uploaded. No-op export is byte exact; scalar edits preserve unrelated XML, job metadata and simulation properties.

Native CAF graph tests inspect block identities, connection records, order, positions and continuations. A guarded source rewire preserves unrelated native data. Prototype-checked connections add one native connection and continuation record without adding objects or changing execution order. All seven private archives yielded a guarded candidate that reparsed successfully. Browser downloads were independently reparsed to check changed tuples and object counts.

Matching CCT/PCT has not compiled or opened those edits. They have not been downloaded or executed on JCI hardware. Offline structure/readback is not vendor application validation.

## Independent IEC compiler and native Temco transfer

The optional MatIEC toolchain is pinned at
`3a41303bcb4e50403417bc39c63f88981d7d961e`. All 27 blocks and nine VAV
profiles pass through the actual exported ST, MatIEC-generated C and a native
Clang executable. Scan traces compare independent outputs, fault flags and
retained state. Tests cover input quality, late divide faults, recovery,
float32 overflow differences, scientific defaults, macros, calendars and timed
events. A test-owned worker is deliberately suspended to verify bounded timeout,
termination and temporary-file cleanup. Seventy-one focused compiler/API tests
passed; no controller I/O is available in that host profile. The compiler's
upstream Clang warnings stay visible. See [IEC execution details](iec-native.md).

Forty Temco transfer tests use actual BACpypes UDP, manufacturer C/C++ wire
fixtures, routed NPDU forwarding and an independent firmware-layout emulator.
The received image executes in the real manufacturer interpreter. Backup,
slot stop, all five chunk writes, full readback, conditional run-state changes,
restore, changing identity/generation/capacity, partial loss, external edits,
journal failures and cancellation are exercised. More than 256 exchanges check
transaction retirement and invoke-ID wrap. A watchdog catches cancelled-child
recovery loops; failed request admission restores the app handler. Nonboolean
resume flags cannot silently start a program. Physical Temco hardware, flash
persistence and scan cadence remain unverified. See [transfer scope](temco-transfer.md).

Browser workflows use the actual IEC compiler and a real UDP Temco
emulator. The latter verifies a stopped replacement and restoration of the
backup's prior running state. Holding a genuine completed HTTP response while
editing authoring bindings verifies that the field operation's result remains
visible. No mocked transport substitutes for those native transfers.

Twenty-one JCI hardware/API tests and a browser workflow exercise native
definition metadata, imperial/metric profiles, actual alias conflicts, presets,
binding/parameter/interface migration and byte-exact XML export. These are
offline metadata checks, not PCV/VMA object allocation or native compilation.
See [hardware-definition evidence](jci-hardware-definition.md).

## Network and field acquisition tests

BACnet/IP tests use actual loopback UDP for directed discovery, reads, unused priority commands, readback, occupied-slot refusal, restart ownership recovery and relinquish. Explicit disconnect refuses owned commands; a later audit-completion failure still reports that closing succeeded. Routed NPDU discovery/reads traverse an actual UDP router attached to a virtual downstream data link.

Direct MS/TP tests use actual pyserial/OS pseudoterminals and fixed wire peers through production HTTP endpoints. They cover CRCs, framing, token management, retries, turnaround, bounded queues, immediate/deferred replies, duplicate-MAC faults, reconnect and exact-interface command recovery. Six frame fixtures independently match an externally compiled unchanged BACnet-stack C encoder. This is not a physical bus or BTL certification. Automatic-direction no-echo RS485 hardware is required; BTCVT and extended/COBS frames remain unsupported.

Modbus tests use real TCP sockets and pseudoterminals, including fixed request/response frames, fragmented responses and bad-CRC rejection. Physical USB, RS485 and Bluetooth adapters remain untested.

Field trend tests use real BACpypes3 UDP numeric/binary reads with independently verified quality metadata. Samples retain actual acquisition/receipt times and explicit field identity in a separate store. Fault tests cover unknown/malformed quality, read errors, nonfinite values, backward/frozen clocks, interface replacement, timeouts, cancellation, serialization, bounds, audit/storage failures and restart without resumed traffic. No fabricated zero or re-timestamped old value substitutes for a failed read.

The browser starts read-only sampling against a local test controller, observes 12.5 with good quality, exports CSV, stops, reloads retained data and explicitly deletes only that ended test source. Audit/poll events remain after sample retirement. Active/open sources are refused; failed retirement intent preserves data, while failed completion evidence reports deletion committed. See [field acquisition details](field-trends.md).

## Site, compliance and VM status

E2/F2 were not contacted or changed. Tailscale checks remain deferred under the user's instruction to finish programming first. Desktop credentials have not been read. A real unused-input sensor test needs a verified native application adapter, exact target/terminal, original backup and verified restoration. BACnet point commands cannot add that input.

JCI/ALC/Honeywell native application compilers/loaders, BTCVT, full proprietary conversions, physical target packaging, external alarm delivery and six verified native 2025 Title 24 CAF applications remain incomplete. Native Temco and Sedona execution does not establish support on that firmware. The requested final GitHub push remains pending.

The Windows VM inventory checked 32-bit/64-bit installed-program registries and vendor application directories. No CCT/PCT installation appeared. No CCT binary analysis or compiler invocation occurred; the VM returned to the stopped state. The ignored inventory is `local-reports/windows-toolchain-inventory.json`.

The idle main local server was restarted with the final code after backing up `studio.sqlite3` and `observability.sqlite3` under ignored `.state/before-transfer-integration/`. Existing observation counts were zero. A production API smoke test independently compiled/executed three IEC and three Temco scans with output 42 and served the built GUI. The transfer service reported no connection, no uncertain operations and no field backups. No BACnet interface, field polling job, native SVM or owned point command was active after that check.

The reference desk now records 253 sources and 49 feature criteria: 24 implemented, 17 partial and eight pending. The multivendor PDF catalog contains 62 records, 61 distinct hashes and 6,777 indexed PDF pages, alongside the earlier JCI collection. Four new guides were downloaded, indexed and selectively reviewed; no claim of reading every manual word for word is made. Manufacturer SDK modules, manuals and original site files remain outside Git.
