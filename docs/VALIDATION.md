# Validation record — 2026-10-18

The implementation is a development build. The checks below validate the stated local behavior, not universal native-controller compatibility.

## Automated verification

- **84 backend tests:** control semantics, strict I/O types and quality, feedback cycles, PI anti-windup, timers, schedules, temperature conversion, rate limiting, alarm delay/reset, complete-scan commits, timed scenarios, revision conflicts, native-format rejection, CAF preservation and 32-bit numeric range guards, online sandbox application changes and rollback, session/origin checks, and network adapters.
- **Six browser workflows:** actual drag/drop and pin wiring; simulation and open-circuit refusal; local revisions plus export/re-import; synthetic CAF inspection/scalar edit; online sandbox replacement/rollback; accurate display of native/hardware gaps.
- **Nine PLCopen exports:** all examples validated against an independently retrieved PLCopen TC6 v2.01 XSD. Schema provenance: <https://raw.githubusercontent.com/mattsse/plcopen-xml-xcore/master/schema/tc6_xml_v201.xsd>. The original PLCopen schema documentation link was stale. The XSD is a local reference and is not redistributed here.
- TypeScript production build and Ruff checks passed. Current development environment: Python 3.13.16, Node 22.23.3, FastAPI 0.146.0, Pydantic 2.14.1, BACpypes3 0.0.110 and Vite 7.3.7.
- Dependency audits reported **no known third-party advisories** after updating the environment and Vite. Audit results are a dated package check, not a security certification. The local application itself is unpublished and is assessed through its tests/source review.

## Actual network behavior tested locally

The BACnet tests use real UDP sockets on loopback. They exercise directed Who-Is/I-Am, property reads, an unused priority-slot command, readback, occupied-slot refusal, process-restart command recovery and explicit relinquish.

Routing uses a real BACnet/IP UDP endpoint and a BACnet router attached to a virtual downstream data link. Reads and discovery reach the remote DNET/MAC address through the router. This verifies NPDU routing, **not physical MS/TP token timing, E2/F2 reachability, or an NAE's routing configuration**.

The Modbus test uses a real local TCP server and deliberately fragmented replies. Serial framing/CRC calculations are covered without a connected RS-485 device. No Bluetooth adapter was available for verification.

## Authorized local CAF samples

Seven user-owned files were opened without uploading them. The sample set includes MS-VMA1630-0, FX-PCV1630-0 and FX-PCV1615-0 in CAF release modes 10.1 and 10.2. For every sample, unchanged export preserved the original archive bytes exactly. A copied archive was scalar-patched and reparsed; object counts and preserved data remained intact. Original files were not modified.

Real samples exposed `jobInfo` metadata and separate `simulationProperty` entries sharing an attribute number with a real property. The adapter preserves these separately. Regression tests use synthetic data so no building programs are distributed.

**Vendor validation has not occurred.** No patched CAF was opened in matching CCT/PCT, compiled, downloaded, or executed on field hardware. Round-trip preservation does not prove application correctness or certification.

## Field and compliance status

E2/F2 controllers were not contacted or changed. The user will establish a route and provide target information later. A physical unused-input test requires a verified native application adapter, target identification, original backup and restoration plan. A normal BACnet point write cannot add that input.

No native CAF/ALC/Spyder/Niagara/Sedona application compiler, proprietary application download, BTCVT transport or direct MS/TP master has been validated. The nine VAV examples are illustrative; no 2025 Title 24 or complete Guideline 36 compliance claim is made.

The requested final GitHub push remains pending because those requested capabilities are incomplete.

## VM toolchain check

The existing Windows VM was started in UTM disposable mode for a read-only toolchain inventory attempt. Guest execution/file retrieval did not produce the inventory, so CCT/PCT installation and licensing status remain unverified. No CCT binary analysis or compiler invocation occurred. The VM returned to the stopped state afterward.
