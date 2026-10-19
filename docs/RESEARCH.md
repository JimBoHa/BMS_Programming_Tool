# Research findings — 2026-10-18

There are useful open source control editors, runtimes, interoperability tools, and protocol stacks. The search did not establish a complete open source compiler/downloader that replaces CCT/PCT for the existing FX-PCV1615/1630 and VMA1630 controllers. Repository feature claims are leads, not evidence that a target controller accepts a generated application.

## Projects worth building around

| Project | Declared license / evidence | What it contributes | Target boundary |
|---|---|---|---|
| [OpenPLC Editor](https://github.com/Autonomy-Logic/openplc-editor) | GPL-3.0; repository license downloaded | IEC programming IDE, graphical authoring, simulation/debugging and runtime deployment workflows | Its supported PLC runtimes; no evidence of a JCI CAF compiler |
| [OpenPLC Runtime](https://github.com/Autonomy-Logic/openplc-runtime) | MIT in current repository LICENSE | Open execution environment and extensible I/O drivers | Requires its runtime on compatible hardware |
| [Beremiz](https://github.com/beremiz/beremiz) | GPL-3.0 | IEC 61131-3 editing and compiler/runtime ecosystem | IEC target/toolchain compatibility must be verified |
| [Sedona framework community fork](https://github.com/linsong/sedona) | Academic Free License 3.0; README and LICENSE.md | Component kits, SAX/SAB applications, compiler, virtual machine and Sox live component services | Requires a Sedona-enabled device and matching kits; generic BACnet support does not imply Sedona |
| [Temco T3000](https://github.com/temcocontrols/T3000_Building_Automation_System) | MIT | Manufacturer-published BAS front end, Control Basic editing, device configuration and BACnet/Modbus integration | Temco native programming semantics/protocols need a dedicated adapter |
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

[REA](https://github.com/morluto/rea), MIT, is an analysis framework for applications and binaries. Its source was inspected, not executed. It grants no CCT license or vendor SDK. Guest automation did not produce a usable CCT/PCT installation inventory in the VM, so its installed-toolchain state remains unverified. No CCT binaries were extracted or analyzed.

Some search results call themselves BACnet simulators or universal controllers while using commercial/source-available terms or distributing only binary appliances. Those are not automatically reusable open source implementations. They were not incorporated.

## Local evidence and manual collection

The existing `../Manual_Library` holds the earlier JCI collection. The new `../Reference_Library` contains ALC, Honeywell, Tridium, Temco and standard references, provenance, retrieval failures, SHA-256 hashes, page text, outlines and a searchable SQLite index. Source repositories and offline Sedona/OBC documentation are under `../Reference_Sources`.

The collection is bounded by public searches, linked download indexes and referenced repositories. It is not every manual on the internet. Some old links return 404; some sites return 406; authenticated portals were not bypassed. All extractable PDF pages were indexed. Review focused on contents, programming, resource accounting, simulation, online operations, migration, and explicit limitations; this is not a claim that every word of every manual was read.

## Turning restrictions into design criteria

Avoidable workflow restrictions become features: preserve unknown data during conversions, show losses before exporting, keep historical versions, distinguish simulation from commissioning, permit reproducible fault tests, expose dependencies, and prepare reversible online changes.

Hardware capacity, physical sensor types, target execution models, transport protocols and access permissions remain facts an adapter must model. For example, a boolean/analog incompatibility calls for an explicit conversion rule, not implicit reinterpretation of bits. A memory limit calls for resource accounting or a supported external runtime, not silently exceeding firmware capacity. Copyright/confidentiality notices are not product features to invert.

The universal architecture therefore needs a source-neutral graph plus explicit per-vendor semantic mappings, compiler/format adapters, transport adapters and target acceptance tests. Unsupported conversions fail visibly. The current capability matrix records which parts exist and which still require work.
