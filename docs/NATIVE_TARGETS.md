# Native target support

The editor's model selector records intended hardware. A target is executable only when its encoder, runtime semantics, packages and deployment service are supported and verified. Protocol point access alone does not establish application programming support.

| Target | Authoring and exchange | Independent execution evidence | Application deployment |
|---|---|---|---|
| BMS Studio graph | 30 blocks, macros, calendars, versioned JSON/ST/PLCopen/GraphML | Python scan engine, scenarios and shared-system simulation | Local sandbox changes, state retention and rollback; no physical output driver |
| Sedona | Real kit source/binary, SAX, SAB and SCode; supported foreign standard-kit conversion | Actual pinned compiler and experimental native Unix SVM, all 30 blocks | Real Sox structural changes on owned loopback VMs; physical platform ABI/kits unverified |
| Temco Control Basic | Numbered BASIC and real native bytecode, explicit point mappings; checked authoring annotations | Actual manufacturer compiler/decode interpreter, all 30 blocks and nine examples over 60 scans | Native BACnet slot stop/backup/replace/readback/resume and compensating restore tested through real UDP and routed emulators; physical execution/flash/cadence unverified |
| Niagara BOG | Real ZIP/XML, 23 graph kinds including Clamp, Scale and Convert, bounded foreign conversion, byte-exact opaque archive inspection | Independent pybog fixture plus genuine manufacturer module/API checks of types, inherited slots, links, palettes and units | Niagara station/Workbench import and native execution unverified; no deployment service |
| JCI FX-PCV / Metasys VMA | Observed native CAF containers, scalar patches, saved simulation inputs, source rewires and prototype-checked new connections between existing blocks | Archive/XML preservation and relationship readback on seven authorized samples | New block identities, native compiler/packages, firmware acceptance and application loader missing |
| ALC EIKON / WebCTRL | Public manuals and vendor-dependent Integration Builder workflow reviewed | No independent equipment compiler/runtime verified | Requires a supported licensed toolchain or an independently verified adapter |
| Honeywell Spyder / CIPer | Public programming manuals and native dependencies reviewed; generic BOG inspection can preserve unknown types | No proprietary component semantics/compiler verified | Native application compiler/modules and loader missing |
| External IEC PLC | ST and schema-valid PLCopen TC6 XML with an ST body | Real MatIEC → C → native host executable, all 30 blocks/nine examples with state and fault comparisons | Host memory I/O only; physical deployment requires a matching destination toolchain and adapter |

Native Temco and Sedona execution does not make their bytecode executable on JCI, ALC or Honeywell firmware. Niagara event/status/priority behavior differs from Studio scan semantics. All native conversions expose their supported profile and reject unknown executable logic or configuration.

The **IEC native** workspace exposes independent compiler artifacts, input quality and timed scenario traces. **JCI hardware** inspects native device-definition point metadata and plans offline migrations; its observed sensor definitions are not PCV/VMA compiler packages. Temco's host simulation supports 256 VARs, while the narrower transfer profile enforces the firmware's 128-VAR limit and refuses unprovisioned calendar services. See [IEC execution](iec-native.md), [hardware definitions](jci-hardware-definition.md) and [Temco transfer](temco-transfer.md).

BACnet/IP, explicit routed destinations and direct legacy MS/TP provide addressed point discovery/reads and owned priority commands. Router-network queries and address-binding cache reads are separate explicit actions; cached hints are not live identities. A selected-DNET Who-Is window, exact-MAC Device-wildcard probe and bounded MAC page retain silence, partial metadata and resume evidence. An empty/completed response window is not a complete inventory. Router/DNET selection must match the opened interface before point services. See [routed discovery](routed-discovery.md).

Object inventories are bounded indexed pages with exact displayed-report export, partial errors and explicit next offsets. Native property JSON preserves Booleans, schema-backed records, octets and typed nonfinite/large-integer/opaque evidence within resource budgets; unknown proprietary types fail explicitly. Commands validate the known BinaryPV/Real/Double/Unsigned datatype and state count, preserve requested values, journal exact wire values and require exact priority-slot ownership. Cancellation, timeout and shutdown stop the owned confirmed dispatch and native transaction without automatically relinquishing an uncertain command. See [values](bacnet-values.md) and [command ownership](bacnet-commands.md).

Standard BACnet File inspection uses Configuration_Files or a bounded advertised Object_List fallback. Explicit reads create opaque stream/record captures with source identity, metadata guards, times, hashes and record boundaries; offline exports preserve exact stream bytes or a record evidence ZIP. This service neither enters backup state nor converts storage to an editable CAF. It does not establish a coherent complete-device backup or native JCI application upload. See [File scope](bacnet-files.md).

Optional BBMD foreign-device registration adds explicit distributed discovery with managed renewal and failed-lease handling. Modbus TCP/RTU provides reads. Field sampling shares those BACnet interfaces explicitly. These services do not add controller application objects or create a sensor terminal. BTCVT's Bluetooth host protocol remains unimplemented; Bluetooth configuration is excluded from the requested test pass.

The durable alarm outbox sends explicitly enabled HTTP webhook routes from retained simulation alarm events. Receipts, retries, uncertain outcomes and operator dispositions survive restart; routes restart paused. Delivery is separate from alarm acknowledgment. This is not native-controller alarm acquisition or email delivery. See [the delivery profile](notification-outbox.md).

Six native 2025 Title 24 CAF applications have not been delivered. The nine VAV example graphs are illustrative, even where their generated Temco/Sedona programs match the reference simulator. Controller eligibility, complete sequences, field commissioning and compliance evidence still require separate verification.

The [native CAF comparison workspace](caf-comparison.md) reviews exact observed
record identities, graph fields, simulation values and opaque XML evidence
without modifying either source file. It does not close the JCI compiler,
package, loader or hardware-validation gaps in the table above.

The approved Tailscale subnet route reaches both E2/F2 NAEs. Authorized read-only BACnet checks verified both engines as MS-NAE5510-2, firmware 11.0.7.40, identified genuine downstream VMA controllers on four trunks and read values. No controller changes occurred. Site results and current test counts are recorded separately; these identity/point reads do not validate native CAF upload, compilation, application replacement or the unused-input sensor test. The final GitHub push remains pending full completion.
