# Validation record — 2026-10-18

The implementation is a development build. The checks below validate the stated local behavior, not universal native-controller compatibility.

## Automated verification

- **166 backend tests passed with no skips:** control semantics, strict I/O types and quality, feedback cycles, PI anti-windup, timers, schedules, temperature conversion, rate limiting, alarm delay/reset, complete-scan commits, timed scenarios and internal forces, shared-signal simulation, dependency analysis, revision conflicts, interchange consistency, native-format rejection, CAF preservation and 32-bit numeric range guards, online sandbox application changes and rollback, session/origin checks, and network adapters. The final run took 114.78 seconds and included all seven authorized CAF samples. One upstream Starlette TestClient deprecation warning remains; it does not affect test results.
- **50 native Sedona integration cases:** all 27 block types, all nine example profiles, feedback/calendar behavior, automatic scanning, fault atomicity, real binary decoding, concurrent compiler processes, native component/link operations, persistent save/export/reopen and compensating recovery after a deliberately dropped write. These use the actual compiler, native SVM and SDK Sox client, rather than substituting the Python engine for native execution.
- **Eleven browser workflows passed:** actual drag/drop, pin wiring and dependency navigation; simulation and open-circuit refusal; internal holds/releases, fault retention, timed force events and CSV evidence; shared-signal cycles, fault atomicity, session reopening and portable workspace files; local revisions plus export/re-import; synthetic CAF inspection/scalar edit; online sandbox replacement/rollback; native application export/import; foreign SAX conversion with an explicit review report; native compile/scan, unused-input null readback, keyboard save, export and rollback; accurate display of native/hardware gaps. The final browser run took 20.1 seconds.
- **Nine PLCopen exports:** all examples validated against an independently retrieved PLCopen TC6 v2.01 XSD. Schema provenance: <https://raw.githubusercontent.com/mattsse/plcopen-xml-xcore/master/schema/tc6_xml_v201.xsd>. The original PLCopen schema documentation link was stale. The XSD is a local reference and is not redistributed here.
- TypeScript production build and Ruff checks passed. Current development environment: Python 3.13.16, Node 22.23.3, FastAPI 0.146.0, Pydantic 2.14.1, BACpypes3 0.0.110 and Vite 7.3.7.
- Dependency audits reported **no known third-party advisories** after updating the environment and Vite. Audit results are a dated package check, not a security certification. The local application itself is unpublished and is assessed through its tests/source review.

## Actual network behavior tested locally

The BACnet tests use real UDP sockets on loopback. They exercise directed Who-Is/I-Am, property reads, an unused priority-slot command, readback, occupied-slot refusal, process-restart command recovery and explicit relinquish.

Routing uses a real BACnet/IP UDP endpoint and a BACnet router attached to a virtual downstream data link. Reads and discovery reach the remote DNET/MAC address through the router. This verifies NPDU routing, **not physical MS/TP token timing, E2/F2 reachability, or an NAE's routing configuration**.

The Modbus tests use a real local TCP server and an actual OS pseudoterminal through pyserial. Fixed known RTU request/response bytes, deliberately fragmented replies and bad-CRC rejection are exercised. This verifies serial framing and the operating-system serial path without claiming physical RS-485, USB adapter or Bluetooth verification.

## Shared-signal and force semantics

Two to sixteen program instances can share typed signals at a common scan period. The tests verify the explicit one-cycle delay, order-independent feedback between programs, type/unit/initial-value validation, single-writer rules, session expiry/capacity and workspace export/import. A late failure in the second program cannot advance the first program's feedback state. Successful earlier cycles in a multi-cycle request remain committed if a later cycle fails.

Internal simulation forces replace a block output after its normal calculation. Tests verify persistent underlying rate-limit state, individual release while retaining another hold, complete-map release, Boolean/number validation, alarm/trace agreement, timed hold/release events and API session behavior. Input-quality or arithmetic faults still stop the scan and cannot commit a requested force-map change. CSV traces include the active override map and the underlying values for forced blocks. Program source exports do not contain these temporary holds.

The dependency explorer identifies direct and transitive sources/consumers, affected outputs and memory boundaries, including feedback without infinite traversal. Browser verification follows an affected output from the inspector. Native component extensions retain their separate native view rather than being falsely included in the core-graph trace.

## Native compiler and simulator

The Sedona SDK is pinned to `406b11f3816fb00db6482640f9cf3397b874b515`. A checksum-verified private Eclipse Temurin 17 JDK builds the Java compiler and bridge. `scripts/setup_sedona.py` reproduces the experimental 64-bit Unix compiler/SVM changes without changing upstream source. Compiler/manifest access is serialized across threads and processes.

Native exports contain real kit, SAB and SCode binaries plus source, hashes, license and provenance. The SDK independently decodes the SAB. The exported application enables automatic scans; interactive simulation advances the main graph explicitly. Physical I/O and calendar inputs require destination-runtime bindings. Native extensions persist null-valued configuration, component order and typed links through SQLite revisions and native export/import/restart. Portable execution/export rejects extensions it would otherwise omit.

Native online changes run first on a second SVM. Apply verifies the original configuration, executes the proposed operations and compares readback with the preview. A missed-write test verifies compensating restoration of the previous configuration. Explicit rollback also verifies readback. A downstream divide-by-zero test verifies that failed scans publish no partial outputs and do not advance feedback state. Native online operations remain sequential; compensation is not an atomic transaction or a physical failsafe.

Selected upstream Boolean, integer, long, float and double tests complete with positive assertion counts and no failures. The broader upstream harness contains `AppTest.verifyCallbacks` assertions that access an object after removal frees it; that observed failure is not counted as a passed platform certification. This port remains experimental and has not been certified or tested on a physical Sedona device.

## Authorized local CAF samples

Seven user-owned files were opened without uploading them. The sample set includes MS-VMA1630-0, FX-PCV1630-0 and FX-PCV1615-0 in CAF release modes 10.1 and 10.2. For every sample, unchanged export preserved the original archive bytes exactly. A copied archive was scalar-patched and reparsed; object counts and preserved data remained intact. Original files were not modified.

Real samples exposed `jobInfo` metadata and separate `simulationProperty` entries sharing an attribute number with a real property. The adapter preserves these separately. Regression tests use synthetic data so no building programs are distributed.

**Vendor validation has not occurred.** No patched CAF was opened in matching CCT/PCT, compiled, downloaded, or executed on field hardware. Round-trip preservation does not prove application correctness or certification.

## Field and compliance status

E2/F2 controllers were not contacted or changed. The user supplied Tailscale access and requested connectivity checks only after programming completion. Those checks remain queued while native target application support is incomplete. Desktop credentials have not been read. A physical unused-input test requires a verified native application adapter, exact target/terminal identification, original backup and verified restoration. A normal BACnet point write cannot add that input.

No native CAF/ALC/Spyder/Niagara application compiler, proprietary application download, BTCVT transport or direct MS/TP master has been validated. The working local Sedona compiler is a separate target. The nine VAV examples are illustrative; no 2025 Title 24 or complete Guideline 36 compliance claim is made. Six verified native FX/Metasys CAF applications have not been delivered.

The requested final GitHub push remains pending because those requested capabilities are incomplete.

## VM toolchain check

The existing Windows VM was started in UTM disposable mode. PowerShell inspected 32-bit and 64-bit installed-program registry entries and vendor application directories. Guest execution wrote the result to Windows Temp, and UTM file retrieval recovered a valid inventory. No Johnson Controls CCT/PCT installation appeared in the checked locations. The local result is retained in ignored `local-reports/windows-toolchain-inventory.json`. No CCT binary analysis or compiler invocation occurred. The VM returned to the stopped state afterward.
