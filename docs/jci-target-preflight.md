# JCI CAF target readiness

The CAF workbench includes a **Target readiness** panel for FX/Metasys configuration planning. It inspects the original CAF, compares the intended target with explicitly supplied toolchain/package inventory, and exports a reproducible JSON readiness report. This feature does not run CCT/PCT, query a VM, compile a native application, or open a field transport.

## Browser workflow

1. Open **CAF files** and load the original CAF.
2. In **Target readiness**, enter the exact controller model, including suffix, and the firmware obtained from the intended controller's inventory. Choose an application object if the CAF has multiple target candidates. Sensor/SA expansion model properties are not treated as the application target.
3. Download the inventory template. Populate it from an authorized CCT/PCT installation and the applicable installation/package documentation. Load that JSON, or edit its text in the panel.
4. Optionally attach the original JCI DynamicHardwareDefinition XML. Add its expected SHA-256 to the inventory when checking provenance. The XML's interface name/revision is not assumed to identify a supported controller model.
5. Choose the planned connection and run preflight. Review each match, blocker, unknown prerequisite, and source property.
6. Export the target readiness report. Changing any input invalidates the current report for export until the check runs again. The report concerns the original imported CAF; export and reopen an edited CAF to check that copy.

## Evidence and comparisons

CAF evidence includes the archive and XML SHA-256 hashes, selected object reference/class, and original scalar properties 70 (model), 12 (Appl SW Version), and 44 (firmware), where those properties are mapped for the class. Missing, structured, or ambiguous values stay unknown. CAF firmware is stored metadata, not proof of current device firmware.

Identity values with unknown attributes or more than 256 characters stay unknown. Oversized scalar evidence is represented by its text hash and character count; the archive remains unchanged. Reports accept at most 256 application-target candidates with references of at most 256 characters.

Appl SW Version, separately declared CAF release mode, controller firmware, source-tool release and destination CCT/PCT product release are independent. For example, a CAF application version of `10.2` must not be treated as firmware `10.2` or compared numerically with the installed tool version. See the release-mode evidence in [the native investigation](jci-native-research-2026-10-19.md).

The inventory declares installation availability, tool/package licenses, Windows/SQL availability, and exact supported model/application/firmware identifiers. Support comparisons require an explicit evidence description. Matching is case-insensitive after trimming outer whitespace; model families, wildcards, aliases, and numeric version ranges are not expanded. Tool version does not automatically establish support for older or newer targets. Package version/hash declarations remain declarations; this feature does not scan package files or validate license activation. Optional packages do not satisfy required-package checks. An empty package list does not establish that no package is needed.

The report retains the exact submitted inventory text and its UTF-8 SHA-256, as well as the parsed/defaulted manifest. For uploaded UTF-8 JSON, the browser retains a BOM if present. After editing text, the hash identifies the submitted text rather than the original disk file. Reports may contain local inventory details; save/share them accordingly. No private programs, host paths, or installation inventories are embedded in this repository.

## Documented operation rules

Enable **Documented tool/release compatibility** to review a planned operation against the source-qualified rule catalog. Rules cover earlier CCT open/commission, CCT18 mode-sensitive edits/simulation/upgrades, package security/licensing, SQL portability, mixed-firmware enum caveats and historical PCT10.3 mode switching. They do not replace exact support lists or native acceptance. See [rules, source hashes and coverage limits](jci-release-rules.md).

## Release-specific transport checks

For BTCVT, the [Metasys System Configuration Guide 14.1 transfer limitation table](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Metasys-System-Configuration-Guide/14.1/Metasys-system/Performance-guidelines-and-limitations/Transfer-to-device-download-limitations) documents that CCT 14.0 and later does not support BTCVT, and Bluetooth application transfers are supported with firmware 6.2 and earlier, excluding 7.0 and later. These checks use the declared tool version and target firmware, never the CAF application version. Intermediate or unparseable versions stay unknown. A nonconflicting earlier version is not proof of a functioning driver, pairing, or native transfer. The report includes the source and its release applicability.

BACnet/IP discovery/property access and direct serial access likewise do not establish native application transfer. Native compilation/loader integration and vendor/device acceptance always remain independent unknown requirements in this preflight. Consequently `can_deploy` is always false; a manifest cannot assert that a missing compiler or loader is verified. The panel's result is `blocked` if a comparison fails or a declared prerequisite is missing, otherwise `needs-evidence` while those acceptance prerequisites remain unknown.

## API

- `GET /api/jci/preflight/release-rules`: bounded operation catalog, primary sources and unknown-valued review template.
- `GET /api/jci/preflight/template`: unknown-valued inventory template.
- `GET /api/caf/{sha256}/preflight`: inspect CAF candidates and report missing prerequisites.
- `POST /api/caf/{sha256}/preflight`: evaluate a request against the open CAF and optional open hardware definition.
- `POST /api/caf/{sha256}/preflight/export`: download the same result as JSON.

POST requests require the Studio session token and the strict `PreflightRequest` schema: `target_model`, `target_firmware`, `application_object_ref`, `transport`, `inventory_text`, and optional `hardware_sha256` and `release_review`. Inventory JSON is bounded to 256 KiB of text by the API and 256 KiB of uploaded bytes by the browser. Duplicate JSON keys, duplicate package name/version pairs, unknown schema fields, nonfinite numbers, and coerced Boolean strings are rejected. Hardware XML continues through the existing bounded/DTD-safe native hardware importer. These routes never mutate the CAF, execute installation commands, or open the BACnet interface.

## Validation boundary

Tests use authored CAF/XML fixtures and declarations, not private controller programs or live devices. They check hash/text preservation, ambiguous target selection, exact identifier mismatch, missing installation/license/evidence, strict JSON handling, qualified BTCVT rules, hardware provenance, session protection, unchanged CAF export, and the browser's report/download/stale-input workflow. No manufacturer-tool acceptance or physical Bluetooth/controller test is implied.
