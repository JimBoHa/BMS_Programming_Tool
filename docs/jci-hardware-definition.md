# Native JCI hardware-definition authoring metadata

`backend/bms_tool/jci_hardware.py` imports the observed Johnson Controls `Interface` XML namespace, schema version `1.0`. It resolves native point definitions, imperial/metric measurements, parameter ranges, BACnet object identities, local/external enumeration references, reusable point attributes, bus address limits, and application presets. It creates offline engineering selections and migration reports. It does not allocate CAF objects, compile a controller application, or write to hardware.

## Concrete source evidence

The inspected public OCT repository is pinned at `c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2`:

| Artifact | Finding |
|---|---|
| [NS8000 device-info XML](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/hardware/ns8000_device-info.xml) | Real package-style device-interface metadata: 25 point definitions, two local enum sets, offset attribute property `956`, and sensor-bus address range `199..206`. |
| [NS8000 meta.xml](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/hardware/ns8000_meta.xml) | Describes build `4.0.0.105`, dated 2025-10-23. Declared package hash fields are not a verified publisher signature or the hash of this standalone device-info XML. |
| [jcpkg member listing](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/hardware/jcpkg_contents.txt) | Lists NS8000, NSA7000, actuator and other device-interface bundles. It does not contain a PCV1630/VMA1630 field-controller definition or application compiler. |
| [CWCVT firmware artifacts](https://github.com/thecontrolscompany/oct/tree/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/hardware/1.1.0.371) | Router firmware release `1.1.0.371`. Static strings identify an ESP32 BACnet MS/TP-to-IP router, BLE transport, web UI and router OTA upload. These are not CCT binaries or a native VAV application compiler. No firmware or probe script was executed. |
| [Package reader](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/server/src/routes/packages.ts) | Reads hardware and primitive XML from an existing Windows package directory. The checked code does not provide those packages or compile applications. |

The device-info XML SHA-256 is `529555eed35b54754b43e44801bb0596eda5f0e08f71fd9afcd5684263772eaa`. This records the exact inspected public copy, not manufacturer authentication. Neither the manufacturer XSD nor a validated signed package accompanies this standalone fixture. Original XML and firmware remain in the external reference checkout; the implementation and committed tests do not redistribute the manufacturer fixture.

## Point identity and alias protection

Point IDs identify selectable interface functions. They must not be collapsed into a map keyed only by BACnet object type/instance. The observed NS8000 `setpoint` and `warmercooler` functions both use type `2`, instance `0`; choosing both would create an ambiguous binding. The importer preserves both definitions, lists the alias group, and rejects a selection containing both.

Measurement profiles merge the typed value's base parameters with the explicitly selected imperial or metric measurement. A point attribute merges its declared definition with its point-specific override. For example, the native offset attribute retains property `956` while using the point's narrower limits. Local enum entries remain available; external dictionary references remain visibly unresolved instead of receiving invented state labels.

Native `Input`/`Output` tags and write-strategy strings are reported as written. An output using `outOfService` does not become a generic BACnet priority command. No method in this module sends commands, changes out-of-service state, or claims that an external sensor definition supplies the missing PCV/VMA terminal allocation rules.

## Python interface

```python
from bms_tool.jci_hardware import JciHardwareDefinition, plan_hardware_migration

definition = JciHardwareDefinition(xml_bytes)
inventory = definition.summary(system="imperial")
point = definition.point("temperature", system="metric")
selection = definition.selection(["temperature", "setpoint"], system="imperial")
original = definition.export()  # Exact original bytes.

report = plan_hardware_migration(old_definition, new_definition, ["temperature"])
```

Selections validate unique point IDs, supported measurement systems, finite ranges/defaults, enum references, attribute references, and collisions in the selected native object identities. They always return `can_apply: false` and the offline scope. Unsupported point configuration is reported explicitly in `point_errors` and cannot enter a selection. Unknown root metadata remains visible and byte-exact in the original export.

Migration compares stable point IDs within the same interface/vendor identity. It reports object remapping separately from changes that require program review, including types, units/ranges, enum definitions, point attributes and write strategies. It also reports interface revision, vendor metadata, bus address constraints and naming-prefix changes, so unchanged selected points cannot conceal changed interface metadata. Removed points are blocking; no fuzzy name-based replacement is guessed. New collisions and direction/type changes block the plan. Reports preserve both source hashes and revision numbers and never apply a change.

## Studio workflow

Open **JCI hardware**, upload the current native device-info XML, and choose imperial or metric profiles. Search the typed point catalog, choose explicit points or an existing native preset, and review a validated engineering selection. Native aliases and unsupported point descriptors produce visible errors. Upload a replacement XML to compare selected stable point IDs, binding changes, parameter changes and interface metadata. Export either original XML byte-for-byte or a separate JSON review report. The JSON report is an engineering artifact and does not become a native CAF or controller download.

## Tests and next native authoring dependency

Authored examples exercise measurement selection, inheritance, enum behavior, alias collisions, malformed/unknown XML, protected metadata, and migration decisions. An optional local test reads the pinned public NS8000 fixture and checks all 25 point profiles in both systems, the actual alias collision, the actual preset, and byte-exact export without changing its source file. These are metadata tests, not controller acceptance tests.

Local validation on 2026-10-19 passed 21 backend/API cases and one browser workflow: alias rejection, native preset selection, metric parameter inspection, replacement binding review, and byte-exact original XML download. The production web build passed. API tests also checked session-token requirements, unsafe XML rejection, bounded-cache eviction, and that the field network stayed closed throughout.

The next native authoring dependency is the correct **field-controller** package/schema for the target PCV1630/VMA1630 release mode, together with an independently verified object-creation/compiler/transfer interface. The sensor package cannot substitute for it. OCT's [reflection output](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/tools/dll-inspection-output.txt) exposes `CCTDataAccessBridge.Request`, `FDBCreateObject` and related signatures but no implementation or complete request contract. Its [continuity notes](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/CONTINUITY.md) identify the installed CCT `bin/Function.xml` as the operation contract; that file is not included in the public tree.

A matching authorized installation would need `Function.xml`, `Metasys.DataAccess.dll`, `Metasys.FCAccess.dll`, their dependencies, and matching FDB/controller packages before a bridge could be implemented and checked against the real tool. An independent implementation instead needs equivalent native schemas and transfer observations. Reflection names alone are insufficient to invent function IDs, request encodings or transfer state machines.

## Additional installer checks on 2026-10-19

New checks followed the actual [Canada Controls download link](https://support.canadacontrols.com/en_US/downloads), [Stromquist CCT link](https://www.stromquist.com/software/CCT), and [Stromquist controller-update link](https://www.stromquist.com/software/controller-updates). Each redirected to its login page. No authentication boundary was bypassed and no public installer was obtained from those routes.

A bounded filename-only search covered this user's Downloads, Desktop, Documents and mounted `/Volumes/NewQ 4TB`, excluding Library/secret locations and the Desktop credential filename. It found no CCT/PCT/BranchTools installer, `Function.xml`, or `Metasys.DataAccess`/`FCAccess` assembly. The sole matching installer filename was the existing project-generated Windows installation ISO. Four filesystem traversal notices limit that search; it does not prove absence from inaccessible paths. No credentials, Tailscale peers, site addresses, hardware probes or original CAF files were accessed by these checks.

The manufacturer-owned [Metasys Basic Services SDK 6.0.5](https://www.nuget.org/packages/JohnsonControls.Metasys.BasicServices/6.0.5) was downloaded from NuGet's public package endpoint: 34,036,322 bytes, SHA-256 `017cea3bb95da40fe565f77993f2451742fdb98cb53f72a694177b5cda7ec199`. Its source pin is [`9085094d4c7df4e5612930a2e8a155596a25bdd5`](https://github.com/metasys-server/basic-services-dotnet/tree/9085094d4c7df4e5612930a2e8a155596a25bdd5). Package members include the server REST SDK, localization resources and API documentation. They do not include CCT/FCAccess/DataAccess assemblies, `Function.xml`, native controller packages or a CAF compiler. Original package, XML documentation, README, license and a member/hash manifest remain outside Git under `Reference_Library/research/jci-public-sdk/`; no package code was executed.

The manufacturer's [third-party software page](https://www.johnsoncontrols.com/legal/digital/third-party-software-information) provided three additional downloaded notices: CCT 13.0, CCT 17.0.0.65 and Metasys Equipment Controllers 9.0. Its public Metasys 9 GPL-source download returned 9,262,080 bytes, SHA-256 `c1d1e72656215c7fc334df398c64aee5a1ead7b973417131514db573eb2a45c3`, without a ZIP central directory or end record. Only complete local-header records and a partial Linux-source member could be identified; no reconstructed archive or compiler was used. The checked records concern OS utilities and boot/kernel source. Neither an OSS component notice nor this incomplete OS-source response establishes access to a CCT application compiler.
