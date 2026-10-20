# Validation record — 2026-10-20

This development build validates the stated local behavior. It does not establish universal native-controller compatibility. [Native target support](NATIVE_TARGETS.md) records the remaining compiler, format and field-deployment gaps.

## Automated checks

- The full backend run passed **1,499 tests with no skips in 338.61 seconds**, including all seven authorized CAFs, saved CAF simulation profiles, genuine external Niagara descriptors, independent native IEC execution, real UDP/routed Temco transfer/recovery, native CAF comparison/hardening, BACnet history/capture, real-time BBMD lease expiry, durable webhook delivery and existing simulation/transport/storage coverage. Scan coverage adds independently encoded BVLC discovery, IP range continuation, Device/Program metadata and actual UDP/HTTP integration. After the full run started, a narrow prefix-mismatch fix retained the actual OS subnet for single/range exclusions; **all 63 focused Scan backend checks passed again in 32.69 seconds**, including the added regression. This does not claim a second full run after that fix.
- **All 87 browser workflows were verified** against the production TypeScript/Vite build. The initial full run passed 83 and exposed four test-fixture failures in 4.8 minutes: three serial UI fixtures rejected the newly added read-only Scan-profile GET, and a one-shot Playwright interceptor stalled the Temco test after successful transfer/readback. The three corrected serial cases passed in 5.4 seconds; the corrected Temco case passed eight repeats in 18.5 seconds. No production code or timeout was changed for these fixture repairs; this records the full run plus focused reruns, not a second full-suite run. They cover authoring, macros, calendars, simulation, storage, CAF/BOG and field workflows, genuine IEC compilation/execution, quality faults, timed recovery, native Temco transfer/restore, JCI hardware migration, native CAF comparison/saved simulation values, 20-kind Niagara conversion, device Trend Log history, BBMD registration/discovery/renewal and actual HTTP webhook receipts/retries. Additional real UDP browser workflows cover routed cache/discovery, wildcard controller selection, paced MAC pages, partial object-list continuation/export and opaque File reads/exports. Held genuine responses verify draft preservation and stale save/load/import/validation/preview handling. A 501-record comparison export traverses multiple API pages. History cases use actual UDP ReadRange for complete, limited, partial, empty and DST-fold reads, CSV provenance, sealed captures and restart. Notification tests explicitly end, acknowledge and retire only their own isolated test sources after verifying delivery leaves alarms unacknowledged; this prevents test-order contamination.
- Ruff, TypeScript and production Vite build checks pass. Workspace pages load in separate bundles; the main bundle is approximately 419 kB before gzip. Screenshots of native formats, compiled traces, serial settings, field samples, CAF comparison/simulation, BBMD state, alarm delivery and device history were visually inspected.
- Earlier adjustable MAC-page timing checks passed all four actual-UDP controller-probe browser workflows in 13.8 seconds. The current full browser run also covers these controls: chosen timing values on the wire/API report, bounds, stale-result invalidation and explicit continuation.
- Nine PLCopen example exports previously validated against an independently retrieved TC6 v2.01 XSD. Schema provenance: <https://raw.githubusercontent.com/mattsse/plcopen-xml-xcore/master/schema/tc6_xml_v201.xsd>. XSD conformance is not external PLC compiler acceptance.
- The environment uses Python 3.13.16, Node 22.23.3, FastAPI 0.146.0, Pydantic 2.14.1, BACpypes3 0.0.110, ifaddr 0.2.0 and Vite 7.3.7. Existing dependency pins are unchanged; ifaddr was added for actual OS subnet resolution, and the lock file is consistent. Upstream Starlette TestClient and pybog Pydantic deprecation warnings remain; they are not failed checks.

Full test output and screenshot artifacts remain in ignored `local-reports/` and `web/test-results/`. Original controller programs, installed SDKs, manuals, VM images and credentials are not part of the code repository.

## Connect Scan and named discovery

The Connect tab now supports local BACnet/IP discovery, a single literal IPv4
endpoint and inclusive IP ranges with explicit 256-address continuation. Local
scope comes from the actual OS subnet, with registered BBMD-network discovery
handled separately. A Tailscale /32 correctly directs the operator to single-IP
or range mode. Exact endpoint/source checks, bounded pacing and response windows,
own-socket exclusion, malformed announcements, duplicates, capability conflicts,
foreign-device lease loss and handler cleanup have independent raw-UDP tests.
The loopback broadcast delivery constraint and test-only mirror are documented
in [the IP profile](ip-discovery.md); they do not establish remote physical LAN
broadcast acceptance.

A separate controlled LAN check used this Mac's actual Ethernet/Wi-Fi IPv4
subnet and an independent raw UDP listener on a free high port. Exactly one
production Original-Broadcast-NPDU reached that listener at the actual subnet
broadcast address, verified by `recvmsg` destination evidence. Its I-Am was
accepted through the production collector; the one-second window completed and
both sockets closed. No mirror, port 47808 traffic or building-controller access
was involved. The private report is `local-reports/device-scan-local-lan.json`.
This verifies actual local OS broadcast delivery, not a remote hardware device's
response.

IP observations and actual routed Who-Is responses feed one named inventory.
Device details verify exact identity before optional reads. Standard Program
names come only from actual Program objects. A complete validated inventory with
none returns `not_exposed`; partial, failed and capped inventories do not. Actual
UDP tests cover 84-object whole arrays, larger indexed arrays, changing counts,
wrong ACKs/identities, source-pinned routes before commissioning-route selection,
existing command ownership, unrelated in-flight reads, cancellation and deadlines.

Six new browser workflows use real UDP Device/Program objects and independently
encoded discovery/router peers. They verify single/range/local response handling,
duplicate identities across addresses/routes, genuine Program names, metadata
errors, formula-safe CSV and JSON provenance, empty-report exports and clear,
explicit 258-address range continuation, Stop after the current bounded RPC,
stale results, and stable 20-device pages while names affect sorting. CSV includes
separate device and full-report rows, so empty continuation pages retain evidence.
Selection fills the exact target/route draft without reopening the interface.

The existing strict serial-browser fixtures now allow only the new local
read-only Scan-profile GET while continuing to reject scan and write requests.
The Temco test retained the first real apply response to exercise an authoring
edit during an in-flight operation. Its one-shot auto-unrouting could stall the
following browser fetch even though an independent status request returned HTTP
200 in 8.7 milliseconds. A stable interceptor now holds only the first response,
and cleanup always terminates its owned emulator. Eight repeated real native
replacement/restore workflows passed without raising the 30-second test timeout.

Authorized read-only field checks through Tailscale found Device 505 at E2 and
Device 506 at F2 in both single-IP and four-host range scans. Device details read
the actual names `E2-NAE` and `F2-NAE`. Their large object lists exceed this
metadata profile's 512-object cap, so Program-name inspection remains explicitly
limited rather than asserting no programs exist. Four selected routed Who-Is
windows and details reads returned `TB4-101`, `TB4-304`, `TB5-101` and `TB5-302`
on the four previously verified trunks. Each selected VMA returned a complete
84-object list without standard Program objects. Device instances 5007 and 5005
remain distinct across their separate networks.

Eight actual production-browser stages repeated single/range and four routed
checks, displayed real names/model/firmware and Program status, exported all six
identities and six discovery scopes as JSON/CSV, and verified draft-only target
selection. CSV parsing separately checked exact names, routes, duplicate
instances and Program status. No controller writes or credential reads occurred.
Private evidence is `local-reports/site-device-scan-feature.json`,
`site-device-scan-ui.json` and the corresponding exports/screenshots. An initial
browser-test endpoint whitelist omitted local graph validation/catalog POSTs;
the harness was corrected against the retained request evidence without
repeating site traffic.

Four SQLite databases were backed up before updating the local service. The
restart and final checks retained all 14 prior File captures and 14 field trend
samples. Original closed connection settings were restored; the service ended
with no open BACnet interface, owned commands or running field jobs. The private
restart record is `local-reports/device-scan-restart.json`.

## Graph semantics and durable state

Tests verify strict types/units, explicit feedback memory, staged state/output commits, PI antiwindup/reverse action, hysteresis, timers, fault injection and finite arithmetic. A failed scan holds previous state/outputs. Internal forces replace a computed value after normal evaluation; source faults still stop the scan. Traces distinguish held and underlying values.

Typed reusable macros support nesting, independent state, bounded expansion, feedback without added scan latency, dependency closure, guarded library exchange, graphical apply/discard and browser draft recovery. Portable and native source-preserving formats retain their editable hierarchy. Shared-system simulation uses previous-cycle typed links and commits all program instances together.

Calendar tests cover IANA zones, both autumn folds, skipped spring minutes, date rollover, leap dates, closures, replacement windows and overnight precedence. Compiled calendar programs require explicit destination-host values and validity flags; they do not contain an IANA timezone database.

Simulation observations preserve simulation/receipt UTC timestamps, types, units and quality in SQLite. Alarm activation/return/acknowledgment/reactivation and explicit source ending remain distinct events. A partial batch reports completed scans, scan errors and recording failures separately. Audit completion failures cannot imply a committed acknowledgment or deletion rolled back.

Each observation database retains a source-kind marker and a stable logical store UUID. Established field/simulation stores cannot be reopened under the other kind. Legacy unmarked stores containing evidence retain simulation identity. Concurrent migration assigns one UUID; copying or moving the same database retains it. The outbox binds to that logical stream rather than a machine path or inode. Tests cover migration, restart, copying, corruption, concurrent access, bounds and retirement. Program revisions retain their legacy checksum format and audit history; new revisions use canonical JSON hashes and verify integrity on load.

Browser tests hold genuine HTTP responses while authors edit, start a new graph, save, load, import or prepare a runtime change. Late responses cannot replace newer drafts, validation results or runtime plans. A save records its completed snapshot while retaining edits made during the request, including macro and undo/redo state.

## Durable alarm delivery

The explicit HTTP webhook outbox is verified against actual loopback HTTP servers. Tests cover future-only and deliberate historical cursors, source/event filters, unchanged event timestamps and quality, stable payload hashes and idempotency keys, restart with routes paused, 2xx receipts, bounded 429/5xx backoff, terminal 4xx responses, ambiguous outcomes, operator retries/discards and explicit completed-history pruning. Delivery never acknowledges the original alarm. Retention gaps and capacity limits remain visible rather than silently dropping evidence.

A separate OS owner lock prevents two services from dispatching the same workspace. A crash or receipt-storage failure after a request records uncertainty; the service does not silently resend it. A real SQLite lock held through an HTTP 204 receipt verifies recovery without a second request. Routes can reference an environment variable for the destination URL and bearer token; their values are not persisted, returned or logged. Fixed destination URLs are ordinary local configuration and are documented as plaintext. Missing/replaced observation sources stop dispatch while existing receipt history remains readable. An incompatible persisted outbox leaves other programming features available and preserves the original database. No third-party notifications or site messages were sent during testing. See [delivery scope](notification-outbox.md).

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

The supported native exchange profile now has 20 graph kinds. Clamp uses native Min/Max components; clamped same-unit Scale uses Reset, while other scales use explicit arithmetic and facets. Convert uses NumericUnitConverter. Genuine external descriptors verify the emitted slots and units. Source-free Reset/converter imports are tested. The previous 17-kind native XML output remains byte identical. This evidence establishes format structure and conversion behavior, not station execution.

An additional 22 tests parse genuine external manufacturer module/API metadata.
They verify component declarations, inherited frozen property types, emitted
link endpoints, six complete serialized unit records and real palette aliases.
This exposed and corrected document-wide alias visibility, invalid bare unit
facets and compact scalar values that native complex status slots would ignore.
JARs and reference source remain outside Git; no Niagara implementation code
was incorporated or executed. Native runtime licensing/acceptance remains
unestablished. See [the exact evidence and member hashes](niagara-bog.md).

The separate inspector returns original BOG bytes exactly, including protected content, unknown typed records and extra archive members. HTTP tests verify upload/session guards, unsafe input rejection and bounded cache eviction. Browser workflows verify opaque ZIP and raw XML inspection/export without station connections.

Seven authorized CAF files include MS-VMA1630-0, FX-PCV1630-0 and FX-PCV1615-0 in release modes 10.1/10.2. Original files were not changed or uploaded outside this computer. No-op export is byte exact; scalar edits preserve unrelated XML, job metadata and simulation properties.

The native saved-input profile identifies 72 simulation-property records in four of the files: 39 floating-point, 11 Boolean and 22 enumerated records. All seven archives are covered. Only observed floating-point/Boolean leaves are editable, with exact archive hash, full record metadata and old-value guards. Enumerations remain read-only because their source definitions are from a different firmware generation. Native exports replace only the selected simulation leaf and independently reparse the result; ordinary application properties remain exact. Browser flows cover profile exchange, invalid value refusal, draft retention and suppression of a late download after leaving the workspace. These saved inputs do not execute the proprietary JCI simulator. See [CAF simulation profile](caf-simulation-profiles.md).

Adversarial CAF tests cover corrupted compression, duplicate identities/wrappers,
DTD/entity encodings, depth/element/name/namespace resource bounds, regex
lookalikes inside comments/CDATA, unsupported edit encodings and cached ZIP
metadata isolation. Scalar edits use actual parser byte positions and reparse
the precise native target for readback. Native diagram coordinates reject
nonfinite/malformed values while preserving valid decimal spellings.

Offline CAF comparison tests distinguish archive bytes, normalized XML records,
application/simulation values, graph fields, order, target metadata and unknown
content. Comments/PIs and prefixed QName bindings, including unprefixed
`xsi:type` default-namespace resolution, cannot disappear as formatting changes.
Mixed text and significant tails remain in evidence. Bounded value/attribute/
identity previews retain complete comparison hashes; matching uses full native
identities. Both source files remain unchanged. See [comparison scope](caf-comparison.md).

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

Forty-three Temco transfer tests use actual BACpypes UDP, manufacturer C/C++ wire
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

Foreign-device tests use an independent raw UDP BBMD and point peer. They verify registration, source/length-checked acknowledgments, forwarded distributed discovery, ReadProperty, real short-TTL renewal, rejection, best-effort deregistration and the full 31-second lease/grace expiry without mocked time. Failed registration or lease loss disables point operations while allowing interface closure. Owned-command recovery retains the exact BBMD/TTL configuration. Actual OS bind failure releases workers and sockets. Browser tests exercise registration, renewal, discovery, reads, reload and failed-lease controls; a pending command plan cannot be retargeted by a concurrent interface or point edit. Physical BBMD/router acceptance remains unverified. See [foreign-device profile](bacnet-foreign-device.md).

Direct MS/TP tests use actual pyserial/OS pseudoterminals and fixed wire peers through production HTTP endpoints. They cover CRCs, framing, token management, retries, turnaround, bounded queues, immediate/deferred replies, duplicate-MAC faults, reconnect and exact-interface command recovery. Six frame fixtures independently match an externally compiled unchanged BACnet-stack C encoder. This is not a physical bus or BTL certification. Automatic-direction no-echo RS485 hardware is required; BTCVT and extended/COBS frames remain unsupported.

Modbus tests use real TCP sockets and pseudoterminals, including fixed request/response frames, fragmented responses and bad-CRC rejection. Physical USB, RS485 and Bluetooth adapters remain untested.

Field trend tests use real BACpypes3 UDP numeric/binary reads with independently verified quality metadata. Samples retain actual acquisition/receipt times and explicit field identity in a separate store. Fault tests cover unknown/malformed quality, read errors, nonfinite values, backward/frozen clocks, interface replacement, timeouts, cancellation, serialization, bounds, audit/storage failures and restart without resumed traffic. No fabricated zero or re-timestamped old value substitutes for a failed read.

The browser starts read-only sampling against a local test controller, observes 12.5 with good quality, exports CSV, stops, reloads retained data and explicitly deletes only that ended test source. Audit/poll events remain after sample retirement. Active/open sources are refused; failed retirement intent preserves data, while failed completion evidence reports deletion committed. See [field acquisition details](field-trends.md).

Existing device history has a separate read-only `ReadRange` profile. Fifty-two
service/API checks use actual UDP and a routed virtual link for all eleven
LogRecord alternatives, timezone/DST resolution, sequence wrap/gaps/windows,
partial failures, malformed replies, cancellation and transaction cleanup.
Out-of-profile integers retain exact evidence without lossy JavaScript numbers.
Capture tests verify restart, integrity, atomic nonreplacement, capacity,
interrupted saves and bounded file-lock contention. FIFO/symlink and deeply
nested files are rejected without blocking or opening a field connection.
JSON/CSV retain report completion/errors, timezone/fold and original timestamps;
an empty CSV uses an explicit metadata-only row. Captures do not backfill the
simulation or polling databases. See [history scope](bacnet-history.md).

## Site, compliance and VM status

After the user approved the subnet and restarted Tailscale on the site Mac, the 192.168.75.0/24 route appeared in the peer's approved primary routes and the OS selected utun4 for both NAEs. TCP 80/443 connections succeeded. Both HTTPS peers presented self-signed certificates with the expected E2-NAE/F2-NAE names; certificate-chain trust was not established. Public web roots and documented UI paths returned HTTP 403. The legacy TimeService metadata request redirected to its 400 page. No credentials were transmitted to a guessed login endpoint.

Actual production BACnet unicast discovery and ReadProperty succeeded through that route: E2-NAE at 192.168.75.32 is device 505; F2-NAE at 192.168.75.35 is device 506. Both report model MS-NAE5510-2, firmware 11.0.7.40 and vendor 5. These are NAE firmware values, not the downstream VAV firmware. Desktop credentials remain unread and web authentication remains untested. The BACnet checks did not require those credentials. Private engine-access evidence is retained in ignored `local-reports/site-route-retest-after-restart.json`, `site-http-identity.json` and `site-bacnet-readonly.json`. No local exit node was selected.

Subsequent addressed reads established actual downstream VMA access on all four
selected MS/TP networks. Device wildcard `4194303` returned the actual controller
identifier; the identifier in the ACK and property value agreed. All four
controllers report vendor 5, model `MS-VMA1630-0`, firmware `6.2.0.1054` and
application software version `10.1`.

| Engine | Routed address | Device instance | Controller name | Observed trunk I-Am rows |
| ------ | -------------- | --------------- | --------------- | ------------------------ |
| E2     | 2105:7         | 5007            | TB4-101         | 81                       |
| E2     | 2205:7         | 5007            | TB4-304         | 62                       |
| F2     | 2106:5         | 5005            | TB5-101         | 70                       |
| F2     | 2206:5         | 5005            | TB5-302         | 68                       |

The four three-second selected-network Who-Is windows observed 281 Device/MAC
rows. This is a set of responses on each network, not a globally unique physical
controller count or exhaustive inventory. Both router-network advertisement
queries remained silent; the exact Device address-binding reads returned 161
cached entries for E2 and 145 for F2. Cache entries remain unverified hints.
Separate paced wildcard pages attempted MACs 0 through 127 on each trunk.
The 0.75-second default missed one already identified F2 VMA; explicit
two-second probes subsequently identified MAC5 on both F2 networks. The GUI now
exposes bounded response-window, spacing and overall-deadline controls and
invalidates old results after editing them. A timeout still means unknown.

Device identifiers repeat across networks. Discovery and selection retain the
router, network and MAC rather than treating an instance as a globally unique
site identifier. Each controller returned 84 objects. Independent indexed reads
collected 20/20/20/20/4 entries per controller with no page errors; all 336
ordered objects matched their prior snapshots. Earlier larger production HTTP
requests retained partial/time-out reports, and a later real browser explicitly
read and exported two 20-object pages. Direct reads retrieved
discharge-air temperature, velocity pressure, zone temperature and heating
output, together with units, reliability, status flags and out-of-service.
The actual inventories contain no standard Trend Log object; stored VMA history
retrieval therefore has no physical target in this sample. The separate local
UDP history tests remain the evidence for that service.

Field testing exposed a real routing defect: Hop Count 1 did not reach the VMA
through the NAE. The same interface and addressed wildcard request succeeded
with Hop Count 16 and with the native stack's 255. Routed scans and probes now
use 255 while retaining exact selected IP router, DNET/MAC and response-source
checks. A fresh-socket Hop-255 probe succeeded without a preliminary direct
router read. No new automatic router preflight was added. The existing measured
I-Am preflight for a large address-binding read remains separate.

All four VMAs advertise six BACnet File objects despite an empty
`configuration-files` property. The file reader now discovers only File objects
actually present in the bounded Device object list and retains its inventory
hash. Production HTTP AtomicReadFile captured Archive File3 (`.moi`), Static
File11 (`.pss`) and Dynamic File12 (`.pss`) from each VMA: **12 source files,
152,229 bytes total**. Independent export checks matched every size, SHA-256 and
receipt. Private copies and a manifest live outside Git in the sibling
`Controller_Uploads/2026-10-19/` directory. A real browser additionally inspected
the six Files, captured/exported Static PSS and verified its hash. This is raw
controller-file evidence, not an editable CAF or a verified coherent application
backup. Firmware files were not downloaded.

Bounded offline analysis of the first 36,880-byte MOI expanded its single gzip
member to 188,288 bytes of native binary data, with an MOI header and model
prefix, rather than CAF XML. JCI documents a separate XML/MOI/PSS conversion
component and persistent storage for commissioning changes in its
[CCT manual](https://docs.johnsoncontrols.com/bas/api/khub/documents/oljzrL52qtPGho8In2ASqA/content).
The copied PSS files therefore remain alongside the MOI; gzip decompression
alone does not establish an editable CAF conversion.

Four explicit production field-trend jobs each persisted two actual zone
temperature samples with verified good quality and Fahrenheit unit labels,
then stopped. A real browser selected one source and exported its two rows with
acquisition/receipt times, source, quality and units. The private full API and
browser evidence is `site-routed-field-final.json` and
`site-ui-verification.json`; the latter records a corrected test-harness CSV
selector and initially over-restrictive local validation-request guard. Neither
required an application change. Independent discovery/page reports are
`site-e2-routing-pages-final.json` and `site-f2-routing-pages-final.json`.

A real unused-input sensor test still needs a verified native application
adapter, exact target/terminal, original backup and verified restoration.
BACnet point commands cannot add that input. No field WriteProperty,
ReinitializeDevice, backup-state change or native application modification was
issued. Desktop credentials were not needed for these BACnet reads and remain
unread; web authentication remains untested.

JCI/ALC/Honeywell native application compilers/loaders, BTCVT, full proprietary conversions, physical target packaging and six verified native 2025 Title 24 CAF applications remain incomplete. Explicit webhook delivery is implemented within its documented profile; native-controller alarm acquisition, SMTP/email and human receipt are outside it. Native Temco and Sedona execution does not establish support on that firmware. Bluetooth configuration is excluded from this test pass. No physical USB serial adapter was present. The requested final GitHub push remains pending full completion.

The Windows VM inventory checked 32-bit/64-bit installed-program registries and vendor application directories. No CCT/PCT installation appeared. No CCT binary analysis or compiler invocation occurred; the VM returned to the stopped state. The ignored inventory is `local-reports/windows-toolchain-inventory.json`.

The preceding native-transfer integration backed up `studio.sqlite3` and `observability.sqlite3` under ignored `.state/before-transfer-integration/`. Its production API smoke independently compiled/executed three IEC and three Temco scans with output 42. The transfer service reported no connection, no uncertain operations and no field backups.

The earlier history/comparison update also backed up the project, simulation and field
databases under ignored `.state/before-history-comparison/`. The actual local
production API served the built GUI, compared an authored scalar-edited CAF,
returned the original CAF byte exactly and exposed the new history profile.
A history request with no connected interface failed explicitly without opening
a field socket. The main server retained no active BACnet connection, field
polling job, native SVM, system simulation or owned point command. Captures from
automated loopback browser tests live only in isolated temporary test state.

Before the preceding non-Bluetooth integration, the same three databases were copied through
SQLite's backup API into ignored `.state/before-nonbluetooth-integration/` and
passed integrity checks. The verified idle server was restarted with the new
backend and built GUI at <http://127.0.0.1:8765>. Its production smoke exported
one guarded floating-point simulation leaf from an authorized native CAF,
reparsed the result, retained the same object count and returned the cached
original byte exactly. It exposed all 20 Niagara kinds and an available empty
notification service. No route, field connection, polling job, native VM,
shared-system session or owned command was active. Original CAF bytes were
rehashed unchanged. No destination was configured in the main outbox.

For the current routed-field integration, all four project, simulation, field
and notification databases were copied with SQLite's backup API into ignored
`.state/before-routed-integration-final/`; every backup passed integrity checks.
The final production server at <http://127.0.0.1:8765> was restarted from an idle
state. It retained all 14 File captures (12 source files and two repeat
verification captures) and 14 field samples (six earlier NAE-proxy readings plus
eight direct VMA readings). No BACnet connection, polling job or owned command
resumed. The browser then reopened/exported the saved PSS and field CSV with the
interface closed, verifying the file hash and both selected source rows again.
All 14 saved file exports also passed independent offline size/SHA-256 checks.
The private evidence is `local-reports/site-restart-persistence.json`. All
separate field-test interfaces also closed; no site traffic remains active.
The consolidated private result is
`local-reports/site-bacnet-verification-final.json`; the user export directory
also includes the eight direct samples with route/point identity in CSV.

The reference desk records 259 sources and 61 feature criteria: 37 implemented, 16 partial and eight pending. The Scan feature adds scoped IP discovery and named device inventory criteria, with the primary ifaddr interface reference. The multivendor PDF catalog contains 64 records, 63 distinct hashes and 6,813 indexed PDF pages, alongside the earlier JCI collection. Downloaded primary references include the 14-page ASHRAE Trend Log addendum and the 22-page ASHRAE BBMD/foreign-device addendum. Manuals were indexed and selectively reviewed; no claim of reading every manual word for word is made. Manufacturer SDK modules, manuals and original site files remain outside Git.
