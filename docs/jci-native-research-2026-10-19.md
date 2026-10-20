# JCI native application and BTCVT investigation — 2026-10-19

The checked public sources do not provide a complete, independently buildable authoring and download toolchain for FX-PCV1615/1630 or VMA1630. The existing CAF adapter can preserve an observed archive and change selected existing scalar values. That is useful interoperability work, but it does not establish that newly generated logic, firmware downloads, or structural live changes will execute on these controllers.

This report records additional checks and the dependencies that remain. It supplements [RESEARCH.md](RESEARCH.md) and [VALIDATION.md](VALIDATION.md); it does not replace their validation boundaries. No field devices, TailScale peers, site credentials, or VM processes were accessed during this investigation.

## Tool version, CAF release mode, and firmware are separate

Do not interpret a CAF's `10.2` release mode as controller firmware `10.2`. The official [Release Modes help](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/16.0.1/User-Interface/User-Interface-Concepts/Release-Modes?contentId=tSlSFZTdW3mKdEs8WJ_yKw) distinguishes tool version from CAF release mode and gives Release Mode 10.2 / Firmware 6.2 as an example. The older [Controller Tool Help, page 38](https://docs.johnsoncontrols.com/bas/api/khub/documents/oljzrL52qtPGho8In2ASqA/content) maps both Release Modes 10.1 and 10.2 to simulation/packages/firmware 6.2. This matters for the existing private CAF samples and BTCVT compatibility; the archive alone is not a live firmware inventory.

The official [field-controller PICS](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Field-Equipment-Controllers-Protocol-Implementation-Conformance-Statement/Annex-A-Protocol-Implementation-Conformance-Statement-Normative) lists VMA1615/1630 families with firmware 6.2. A protocol-conformance statement describes services and object capabilities, not the complete proprietary application encoding or loader.

## Actual public projects checked

### OCT

Inspected local revision `c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2` of [thecontrolscompany/oct](https://github.com/thecontrolscompany/oct).

- Its [README](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/README.md) requires Windows, installed CCT 18, locally running SQL databases, and installed controller packages. It is not a way to obtain those dependencies.
- [`server/src/routes/caf.ts`](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/server/src/routes/caf.ts) reads CAF ZIP/XML and enriches objects using a firmware database. The inspected routes do not create native control applications or compile/download arbitrary new logic.
- [`server/src/mstpSerial.ts`](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/server/src/mstpSerial.ts) has an `active` mode label. In the checked implementation, the selected mode is stored in session state; serial data is received and parsed. There is no transmitting MS/TP master/token state machine in that file. Its label is not evidence of working direct-MS/TP or BTCVT support.
- [`tools/dll-inspection-output.txt`](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/tools/dll-inspection-output.txt) contains reflection metadata from another machine's JCI installation. Names such as `FdbStoredProcWrapper`, `FDBBertInterface`, `Metasys.DataAccess`, and `Metasys.FCAccess` identify possible integration surfaces. Method signatures are not implementations or a supported SDK. This investigation did not execute them, retrieve proprietary assemblies, or prove a bridge works.

The SQL/application boundary is significant: reproducing a few class dictionaries cannot replace the database procedures, block definitions, package compatibility rules, serializers, and device transfer behavior used by CCT.

### dbexport-viewer

Inspected the existing local [thecontrolscompany/dbexport-viewer](https://github.com/thecontrolscompany/dbexport-viewer) checkout at `269cb0db171bb3748f20f64b07ccf123c08ebfbe`. Its archive inspection and repair workflows remain useful reference material. No independent native controller application compiler or BTCVT host protocol implementation was established from this checkout. A simulated archive object tree is not execution of the vendor firmware.

### esp-bacblue: a new Bluetooth lead, but documentation only

Cloned [zeninboxes/esp-bacblue](https://github.com/zeninboxes/esp-bacblue) at `ccd8fa2c42e7b75c9c393a44c925d47dc263a855` into the external reference-source directory. The [overview](https://github.com/zeninboxes/esp-bacblue/blob/ccd8fa2c42e7b75c9c393a44c925d47dc263a855/overview/index.rst) advertises BACnet routing and BTCVT emulation. The [BTCVT tutorial](https://github.com/zeninboxes/esp-bacblue/blob/ccd8fa2c42e7b75c9c393a44c925d47dc263a855/tutorials/btcvt.rst) describes Bluetooth pairing, RFCOMM COM ports, and use with JCI software.

The checked tree contains Sphinx documentation, images, and documentation build files. It does not contain the device firmware, a host framing codec, a native application encoder, or a source license granting reuse of a driver implementation. No implementation was copied, executed, or represented as a working adapter. This is a hardware/documentation lead, not a completed open source transport.

### Other search results

GitHub searches included `BTCVT`, `MS-BTCVT`, `bluetoothmce`, `Metasys.FCAccess`, `FDBBertInterface`, `ControllerConfigurationTool`, and repository searches for Metasys compilers and PCT CAF controllers. Many matches were unrelated names or generic protocol/REST clients. No additional complete native authoring/download implementation was identified. Search coverage is bounded and public code indexes can omit repositories; this is not proof that no implementation exists anywhere.

The [bas-sandbox README](https://github.com/velovault-llc/bas-sandbox) describes a browser simulation environment rather than a live native JCI compiler. Its current Functional Source License also differs from an unrestricted open source license. It was not incorporated into the application.

## Installers and packages

Exact-name web searches for `ControllerConfigurationTool`, `FacilityExplorerProgrammableControllerTool`, and `FXFieldControllerPackageFiles6.2.2.6.zip` did not yield an authorized public installer binary in this investigation. Software listing/uninstaller pages are not downloads of the requested manufacturer product.

The official [CCT 18 custom installation instructions](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Configuration-Tool-CCT-Installation-Guide/18.0/Installing-and-licensing-the-CCT-software/CCT-custom-installation-and-licensing) require an installation file, supported SQL Server configuration, separately imported controller packages, and activation using Software Manager. The [CCT/FCP licensing page](https://docs.johnsoncontrols.com/bas/r/Johnson-Controls/en-US/Controller-Configuration-Tool-CCT-Catalog-Page/18.0/Controller-Configuration-Tool-CCT/CCT-and-Field-Controller-Package-Licensing?contentId=jiCJf4r3jKYgSZAZAooiZA) confirms separate package distribution and licensing. An installer by itself would not establish that the necessary legacy target packages are present.

The existing [FX-PCT 10.3 installation manual](https://docs.johnsoncontrols.com/bas/api/khub/documents/IbTB7WNN~rUJ16aPyrzn2w/content) names `FacilityExplorerProgrammableControllerTool_10.3.exe` on product media. The [2018 FX firmware distributor notice](https://www.jacksoncontrol.com/technical-tips/2018/10/11/flash-tech-tip-facility-explorer-field-controllers-with-version-62-firmware-mah99) points to a login at HVAC Navigator, rather than a public ZIP endpoint. No login or licensing barrier was bypassed.

## BTCVT compatibility and missing implementation

The [Metasys 14.1 transfer limitation table](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Metasys-System-Configuration-Guide/14.1/Metasys-system/Performance-guidelines-and-limitations/Transfer-to-device-download-limitations) establishes two independent restrictions:

1. CCT 14.0 and later does not work with BTCVT.
2. Bluetooth application transfers are supported for firmware 6.2 and earlier, not firmware 7.0 and later.

Therefore, newer CCT features do not automatically retain the user's original Bluetooth workflow. Conversely, legacy Release Mode 10.1/10.2 CAFs must not be rejected merely because their numbers exceed 6.2. For existing equipment, matching firmware and a tested legacy tool/transport combination matter.

The public commissioning guides show pairing and serial-port selection, but do not establish the complete application framing, initialization, addressing, timeouts, recovery, and control-plane behavior required by a new BTCVT host adapter. Opening an RFCOMM serial device proves only that an OS serial link opened. It does not prove BACnet transaction support or native application transfer. The hardware is also needed to validate a driver independently of a simulated peer written from the same assumptions.

BACnet/IP through an appropriate router is a separate path. Working object/property access over it does not, by itself, provide the missing native application encoder and transfer session implementation. Direct MS/TP additionally needs a correct master state machine and verified RS-485 turnaround/timing; a byte parser is insufficient.

## Title 24 library evidence

The previously collected [CCT 18.0.2.6 flash sheet, LIT-2026F07](https://docs.johnsoncontrols.com/bas/api/khub/documents/UqIAgBkE2450xh66jaS7vQ/content) was rechecked. It identifies certified JA18 tree changes for Release Mode 10.8 and names the VAV single-duct G36 and mixed-air single-duct AHU G36 trees. It specifies `ControllerConfigurationTool_18.0.2.6.exe` and retrieval through the JCI License Portal. It does not establish eligibility of every legacy 1630 model or every fan/heat configuration.

The current [CEC programming-library certification list](https://www.energy.ca.gov/sites/default/files/2026-09/Programming_Library_Certification_List_9_10_2026_ada.xlsx), linked from the [CEC certification page](https://www.energy.ca.gov/rules-and-regulations/building-energy-efficiency/manufacturer-certification-building-equipment-0), was downloaded and its worksheet XML inspected. Rows 19 and 20 list Johnson Controls Metasys and Facility Explorer respectively, Guideline 36 version 2021, library CCT 18.0.2. This identifies the certified library version; it does not supply six downloadable CAFs or prove that a hand-translated replacement inherits the certification.

Downloaded reference evidence is outside Git under `../Reference_Library/research/jci-native-2026-10-19/`:

| File | SHA-256 |
|---|---|
| `JCI-CCT-18.0.2.6-LIT-2026F07.pdf` | `00495df262eaeea93c7c013d002410612ab313db1b1de8d59d7cca598b1be532` |
| `CEC-Programming-Library-Certification-List-2026-09-10.xlsx` | `eeb1ff9d5a62a7f67fc33e6615bfef9c4c28e323366e01f88d3f5c624c815df6` |
| `CEC-G36-declaration-2025-07.docx` | `a34953e35c7388081d00d7c7d7b2f220fbff2615bc22eac134ab0de98189d471` |

The PDF duplicates a reference already in the earlier JCI collection; it must not be counted as a new distinct manual. `sources.json` records origin URLs, content types, sizes, retrieval date, and hashes. `CEC-certification-list-extracted.txt` records the worksheet cells. The original manufacturer/CEC files were not added to this repository.

## What would permit verified native completion

There are two credible development paths. Neither is currently complete.

### A. Bridge a matching installed manufacturer toolchain

Required evidence and dependencies:

- A working, authorized CCT/PCT installation and its supported Windows/SQL prerequisites; the existing VM inventory did not find one in the checked installed-program/vendor locations.
- Correct release-mode databases and installed FX/Metasys controller packages for the exact controller model suffixes and firmware. Modern example databases are not substitutes for legacy packages.
- A usable documented SDK/CLI or a verified local automation/interop surface. Public reflection text is a research lead; calls, session lifetimes, error handling, database transactions, and vendor compatibility still need to be measured.
- Actual create/edit/save/reopen tests in that tool, followed by vendor validation/simulation and an application-only bench transfer, readback, restart persistence, and restore test.
- For certified sequence delivery, the exact approved library and hardware mapping with project-specific configuration and acceptance evidence. Certification does not arise from naming a file `.caf`.

### B. Independently implement the native format and loader

Required specifications or independently verified observations:

- Complete per-version object/property/type schemas, supported primitives and execution semantics, initialization/retention behavior, wiring and sequence representations, and object identity/reference rules.
- Target-specific I/O definitions, supported sensor modes, available resources, and compatibility rules.
- The actual native serialization/transfer representation and its version checks, checksums or signatures where applicable, staging/activation behavior, transfer recovery, and readback rules. No particular instruction-set compiler or file extension is assumed from an XML container.
- BTCVT framing/initialization and physical captures if that transport remains required, or a separately validated router/native-loader path.
- An independent oracle: native CCT/PCT acceptance or equivalent authoritative fixtures plus target hardware acceptance. Testing an encoder against its own decoder alone does not verify device compatibility.

Existing manuals, seven observed private CAFs, dictionaries, and open protocol stacks support incremental research. They do not supply all of these dependencies. Full native completion cannot currently be substantiated solely from the locally simulated application. Local universal/Sedona work can continue independently, but it does not close the FX/VMA requirements or justify native controller changes or the completion-gated final push. The user separately authorized read-only site diagnostics during development; their latest connectivity evidence is recorded in [VALIDATION.md](VALIDATION.md).
