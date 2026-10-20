# Research findings — 2026-10-19

There are useful open source control editors, runtimes, interoperability tools, and protocol stacks. The search did not establish a complete open source compiler/downloader that replaces CCT/PCT for the existing FX-PCV1615/1630 and VMA1630 controllers. Repository feature claims are leads, not evidence that a target controller accepts a generated application.

## Projects worth building around

| Project | Declared license / evidence | What it contributes | Target boundary |
|---|---|---|---|
| [OpenPLC Editor](https://github.com/Autonomy-Logic/openplc-editor) | GPL-3.0; repository license downloaded | IEC programming IDE, graphical authoring, simulation/debugging and runtime deployment workflows | Its supported PLC runtimes; no evidence of a JCI CAF compiler |
| [OpenPLC Runtime](https://github.com/Autonomy-Logic/openplc-runtime) | MIT in current repository LICENSE | Open execution environment and extensible I/O drivers | Requires its runtime on compatible hardware |
| [Beremiz](https://github.com/beremiz/beremiz) | GPL-3.0 | IEC 61131-3 editing and compiler/runtime ecosystem | IEC target/toolchain compatibility must be verified |
| [Sedona framework community fork](https://github.com/linsong/sedona) | Academic Free License 3.0; README and LICENSE.md | Component kits, SAX/SAB applications, compiler, virtual machine and Sox live component services | Requires a Sedona-enabled device and matching kits; generic BACnet support does not imply Sedona |
| [Temco T3000](https://github.com/temcocontrols/T3000_Building_Automation_System) | MIT | Manufacturer-published BAS front end, Control Basic editing, device configuration and BACnet/Modbus integration | Native compiler/interpreter verifies all 27 blocks; separate native slot transfer has real UDP/routed emulator tests, with physical execution unverified |
| [Eclipse 4diac IDE](https://github.com/eclipse-4diac/4diac-ide) and [FORTE](https://github.com/eclipse-4diac/4diac-forte) | EPL-2.0 | IEC 61499 function-block engineering and runtime | IEC 61499 differs from IEC 61131 scan semantics and proprietary DDC applications |
| [OpenBuildingControl](https://github.com/lbl-srg/obc) and [Modelica Buildings](https://github.com/lbl-srg/modelica-buildings) | Repository-specific notices must be checked before copying implementations | Control Description Language, executable reference sequences and verification methods | Reference models still need target lowering and validated runtime behavior |
| [BACpypes3](https://github.com/JoelBender/BACpypes3) and [BACnet Stack](https://github.com/bacnet-stack/bacnet-stack) | Inspect package/source notices; repository metadata alone was inconclusive | BACnet application/network services and data-link foundations | Protocol access is not an application compiler |
| [Node-RED](https://github.com/node-red/node-red) | Apache-2.0 | Flow editor and integration patterns | Flows execute in Node-RED, not automatically in proprietary field firmware |
| [OpenBMS](https://github.com/openbms-io/bms-apps) | AGPL-3.0-or-later declared in LICENSE | Visual BMS authoring and edge architecture | README marks real BACnet integration as planned; verify implementation rather than treating every roadmap item as complete |

## JCI, ALC and Niagara-specific findings

[OCT](https://github.com/thecontrolscompany/oct) is a public Apache-2.0 JCI tool with CAF/archive viewing, attribute editing, commissioning and BACnet services. Its README requires a Windows CCT 18 installation, SQL databases and controller packages. It does not establish an independent native application compiler. Its class/attribute dictionaries are used here with attribution; no JCI databases or binaries were copied.

[dbexport-viewer](https://github.com/thecontrolscompany/dbexport-viewer), Apache-2.0, is an offline CAF/SCT archive inspection and audit tool. Its README explicitly distinguishes viewing/archive repair from full runtime simulation and native logic creation. Those gaps become requirements in our adapter work.

[ALC Integration Builder](https://github.com/automatic-controls/integration-builder-eikon-script), BSD-3-Clause, generates control programs through an EIKON Groovy extension. It requires licensed WebCTRL 9/EIKON. This offers a possible supported bridge, not an independent open compiler. The related [property import/export add-on](https://github.com/automatic-controls/cp-property-import-export-addon) is another workflow reference.

[EIKON for Educators](https://eikonforeducators.automatedlogic.com/eikonlogicbuilderforeducators.html) provides a public vendor download and training materials. A free download does not establish open source licensing. The installer and available manuals were downloaded for local reference; the installer was not executed.

Tridium's [FOX session example](https://github.com/tridium/forum2025-fox-session-demo) requires Niagara 4.15+, signing configuration and a Niagara installation. Its custom “Tridium Open Source License” imposes redistribution conditions; it is not treated as a generic permissively licensed replacement for Workbench, and its code was not incorporated.

[REA](https://github.com/morluto/rea), MIT, is an analysis framework for applications and binaries. Its source was inspected, not executed. It grants no CCT license or vendor SDK. A read-only Windows guest inventory checked installed-program registries and vendor application directories; no CCT/PCT installation appeared in those locations. The VM was shut down after the inventory. No CCT binaries were extracted or analyzed.

## Native Sedona verification

The pinned Sedona revision `406b11f3816fb00db6482640f9cf3397b874b515` was built locally with a private JDK 17. Its compiler produces actual kits, SAX, executable SAB and SCode. The native C SVM runs on the Apple silicon host with reproducible 64-bit changes recorded in `scripts/setup_sedona.py`. Those changes cover reference-field allocation, pointer-null comparisons, null stack-cell writes, UDP structure offsets, loopback binding and the macOS endian include. The original upstream source remains unchanged.

All 27 graph block types and the nine illustrative VAV profiles execute through that native compiler/VM. Values are read through the SDK's actual Sox client and compared with the separate graph engine. A second native VM preflights structural changes. Saved native configuration and links survive revision storage, export/import and restart. Foreign standard-kit SAX/SAB conversion supports a declared subset and reports changed scan/null/fault semantics; arbitrary native kits do not silently convert.

This is an experimental local Unix platform, not physical Sedona certification. The broad upstream test harness includes an `AppTest.verifyCallbacks` assertion that reads an object after removal frees it; that failure is recorded, not counted as a passed certification. Selected native core-value tests and our structural readback/rollback tests pass. A real Sedona controller still needs its matching platform image, ABI, services and kits. This compiler/VM does not make JCI, ALC, Spyder or Niagara firmware accept Sedona applications.

Some search results call themselves BACnet simulators or universal controllers while using commercial/source-available terms or distributing only binary appliances. Those are not automatically reusable open source implementations. They were not incorporated.

## Additional native formats and serial verification

The manufacturer-published [Temco compiler/interpreter source](https://github.com/temcocontrols/T3000_Building_Automation_System/tree/ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b) is MIT licensed. The reproducible host emits genuine Control Basic bytecode and executes it with the manufacturer's decode interpreter. All 27 graph blocks, state retention, fault output holds and all nine illustrative VAV profiles have native execution evidence. Calendars use explicit host active/valid flags. Native integer precision and overflow differences remain visible. The separate [program-transfer service](temco-transfer.md) follows independently checked client/firmware wire layouts and has real UDP/routed emulator evidence for backup, replacement, readback and recovery. Physical execution, flash persistence and source scan cadence remain unverified. See [the native host profile](temco-native.md).

The MIT [pybog project](https://github.com/bbartling/pybog/tree/0248d941bf230aad2f19f9805be67c0e64bd51ef) supplies a public, independently authored Niagara BOG encoding reference. A supported native primitive profile now imports/exports real ZIP/XML BOG files, with an independent pybog-generated fixture. A separate inspector preserves unknown/protected components and archive resources byte for byte. Conversion rejects logic or configuration it cannot model. There is no installed Niagara station/Workbench acceptance test. See [native BOG scope](niagara-bog.md).

Tridium's [2026 troubleshooting presentation](https://www.tridium.com/content/dam/tridium/en/documents/niagara-summit-2026/application/tri-niagara-summit-2026-session-nth4.pdf), [2023 presentation](https://www.tridium.com/content/dam/tridium/en/documents/niagara-forum-2023/NF23-Technical-Troubleshooting-Niagara.pdf) and the manufacturer kitControl guide were added to the private reference collection. Their 190 pages were extracted and indexed; encoding/component/protection sections were reviewed. Four additional Niagara/Honeywell guides contribute 698 indexed pages, including the 430-page Niagara introduction, Spyder Model 5 engineering guide and TB3026B N4 wizard. Original notices remain, and no manual PDF is redistributed in this repository. The multivendor catalog has 62 PDF records, 61 distinct hashes and 6,777 distinct PDF pages.

The pinned [MatIEC compiler](https://github.com/beremiz/matiec/tree/3a41303bcb4e50403417bc39c63f88981d7d961e) independently compiles the exported ST to C. A real native process executes all 27 blocks and nine example graphs, with explicit comparison of retained state, scan faults, quality, calendars and timed events. Scientific numeric defaults exposed an invalid IEC literal format; the exporter now includes a fractional mantissa and canonical exponent. This is host verification, not physical PLC deployment. See [IEC provenance and limits](iec-native.md).

Native JCI `DynamicHardwareDefinition` XML from the public OCT source now drives an offline typed point catalog and revision-migration review. Sensor definitions reveal actual aliases, units and presets; they do not supply the PCV/VMA application compiler. Public manufacturer BasicServices SDK and OSS disclosure packages were also obtained. They supply service APIs and third-party notices, rather than the missing CCT `Function.xml`, data-access assemblies and controller packages. See [the hardware investigation](jci-hardware-definition.md).

A separately written legacy MS/TP master now handles token/frame services through pyserial and a BACpypes3 data-link adapter. Production HTTP discovery and ReadProperty use actual pseudoterminals with fixed wire peers. Selected frame octets match an externally compiled pinned BACnet-stack encoder. Physical bus timing, USB adapters, BTCVT, extended frames and vendor application downloads remain unverified. See [the protocol implementation](mstp-transport.md) and [file-specific provenance](mstp-provenance.md).

Authorized local CAFs exposed native block lists, four-short connection records, order, positions and continuation tables. Guarded source rewires and prototype-checked added connections preserve objects and unrelated XML. These operations were exercised on separate copies of all seven samples. There is still no independent JCI compiler, target package installation or field application loader, so offline relationship authoring is not evidence that a controller accepts the application.

## Local evidence and manual collection

The existing `../Manual_Library` holds the earlier JCI collection. The new `../Reference_Library` contains ALC, Honeywell, Tridium, Temco and standard references, provenance, retrieval failures, SHA-256 hashes, page text, outlines and a searchable SQLite index. Source repositories and offline Sedona/OBC documentation are under `../Reference_Sources`.

The collection is bounded by public searches, linked download indexes and referenced repositories. It is not every manual on the internet. Some old links return 404; some sites return 406; authenticated portals were not bypassed. All extractable PDF pages were indexed. Review focused on contents, programming, resource accounting, simulation, online operations, migration, and explicit limitations; this is not a claim that every word of every manual was read.

The [May 2026 NS8000 firmware flash sheet, LIT-2026F17](https://docs.johnsoncontrols.com/bas/api/khub/documents/qJGLaOTYwigeohhdTpb68g/content) was also downloaded, indexed and reviewed across all four pages. Its hardware-definition update procedure requires checking point connections and occupancy logic after migration. That becomes a desired automatic migration/remapping feature with an explicit verification report. It does not establish that legacy VMA/FX-PCV hardware supports every newer package feature.

## Turning restrictions into design criteria

Avoidable workflow restrictions become features: preserve unknown data during conversions, show losses before exporting, keep historical versions, distinguish simulation from commissioning, permit reproducible fault tests, expose dependencies, and prepare reversible online changes.

Hardware capacity, physical sensor types, target execution models, transport protocols and access permissions remain facts an adapter must model. For example, a boolean/analog incompatibility calls for an explicit conversion rule, not implicit reinterpretation of bits. A memory limit calls for resource accounting or a supported external runtime, not silently exceeding firmware capacity. Copyright/confidentiality notices are not product features to invert.

The universal architecture therefore needs a source-neutral graph plus explicit per-vendor semantic mappings, compiler/format adapters, transport adapters and target acceptance tests. Unsupported conversions fail visibly. The current capability matrix records which parts exist and which still require work.
