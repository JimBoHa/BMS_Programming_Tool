# Operation support for a captured controller application

Program → Controller application → **Operation support for this capture** shows
which installed operations recognize the selected controller's recorded File.
The table replaces the blanket assertion that every readable format lacks native
editing and download. It distinguishes typed identity/default operations, local
file copies and saved-setting compilation from general block and wire editing.

The existing application read/capture API includes `operation_capabilities`,
profile `controller-application-operation-capabilities/1`. This is local analysis
of retained bytes. Opening the table does not query another controller, launch a
vendor tool, enter backup mode, create a review or prepare a transfer.

## Evidence and states

| Operation | Basis and boundary |
| --- | --- |
| Read the published application File | An observed complete, integrity-checked capture supplies the bytes, source hash, File and captured Device/interface identity. It remains a dated snapshot. |
| Inspect blocks and wires | The installed reader must actually recognize a complete diagram. A readable diagram need not satisfy the stricter identity compiler. |
| Edit/compile Device instance | The existing `MoiIdentity` parser must recognize the actual fully framed source. Source-qualified is a compiler recognition result, not a proposed edit or compiled-output acceptance. |
| Edit/compile controller name | The same typed source must expose a root Device name. The proposed name's encoding and exact edit remain subject to the existing review. |
| Transfer a reviewed instance/name change | The captured vendor must establish the installed vendor-5 family, the source root must agree with the captured Device instance/name/model, and the interface must be plain direct or routed BACnet/IPv4. Even then the state is **preflight required**. |
| Save a native Real-default file copy | Actual supported fields in a fully framed source qualify the local copy profile. Source recognition does not establish matching Device identity or field-transfer support. |
| Compile an effective Real default | A separate identity-verified native backup with Files 3/11/12 is required. A published File capture never supplies or invents its saved parameter directory/values. Offline compilation is independent of the current interface transport. |
| Transfer one effective native default | Source/root/vendor/transport evidence can qualify a separate native preflight. The actual native backup, selected prior-value guard, preservation of other fresh settings, capacity, one-use review and full application/effective-setting readback remain required. |
| Edit/compile arbitrary native logic | The native reader and typed identity/default compilers do not generate arbitrary blocks, wires or allocations. This remains unavailable. |
| Package/destination release compatibility | **Not evaluated** by this capture analysis. Captured firmware and native ACS/DMCS codes remain separate namespaces; no version ordering or model table establishes compatibility. Existing offline CAF/toolchain preflight compares declared evidence separately. |
| Physical acceptance | **Not inferred** from a file read or source parser. Actual transfer, readback, restart and hardware qualification have their own evidence. |

Connected transfer still requires native protocol/identity preflight, credentials,
Static/Dynamic parameter layout, fresh source/parameter preservation, capacity,
allocation/name confirmation, a one-use review and exact readback. Direct MS/TP
or foreign-device File acquisition does not establish native transfer over that
interface. Backup and application readback use backup-state commands, unlike the
standard published-File read used by this viewer.

No controller model selects a substitute application, point inventory or reader.
Model text is compared only between the actual native root and captured identity.
Unknown models can satisfy the supported format; familiar names cannot override a
source, protocol or transport mismatch. No CCT/PCT installation is required to
recognize or use the existing narrow typed compiler.

## Ownership and remaining integration

The response binds operations to the retained capture ID and SHA-256, captured
Device identity and connector configuration. The browser rejects operations that
name another capture. Its current report is projected through the exact selected
controller/interface before rendering, while existing request generations retire
late replies. Changing targets or closing the interface hides the prior source.

`COMM-OPERATION-CAPS-001` implements this captured-source slice. The wider JCI-01
matrix remains partial: offline CAF/package
provenance and release rules, retained transfer-result correlation, additional
protocol/format families and independent physical qualification need further
integration. A newly parsed source never grants a field write. Program’s separate
[native default workflow](native-default-transfer.md) shares the controller context
but prepares its own operation-specific backup/review/transfer evidence. The
[record explorer](native-record-explorer.md), operation table and local file-copy
editor can inspect the same immutable source without discarding its local draft.

[Native backup analysis](native-backup-operation-capabilities.md) now covers
retained native-service-only File 3/11/12 sources separately. It evaluates the
actual saved merge and shares source qualification with the effective-default
compiler; a published-File capture is still not substituted for that snapshot.

## Local checks

Unit checks exercise compressed/plain unknown-model sources, source recognition
without a diagram, readable diagrams without compiler framing, identity mismatches,
vendor differences and unsupported transfer interfaces. Existing actual UDP File
acquisition checks verify capture provenance and reject other targets. Browser
checks read actual Files, distinguish the narrow compiler from general logic,
change between two controllers sharing one Device ID and reject mismatched
operation evidence. The peers refuse writes and backup-state commands. They are
local software checks, not physical controller or Bluetooth acceptance.
