# Metasys mapped-point sources: investigation and read-only inspection

Status: source inspection implemented; independent live NAE remapping **not
implemented or qualified**. This work must not be presented as a completed
remapping feature. No production mapping was changed to develop it.

## The distinction that matters

A supervisory mapped point has a local BACnet Object Identifier and a remote
source Instance Number. For example, local `analog-input,501` could read remote
instance `41`. Changing the local identifier does not repair that source.
The remote source object type, remote Device, route and actual equipment must
also be established; a matching instance or name alone does not identify a sensor.

The intended eventual repair changes only the remote source while preserving the
point's Metasys identity, reference, extensions, trends and all incoming links.
SQL historian import, changing a field Device instance and editing a field
controller's native application are separate operations.

## What the manufacturer's documentation establishes

- The [SMP BACnet Hardware tab][hardware] identifies Instance Number as **C**
  (configurable), without **W** (writable). This is the mapped BACnet point
  hardware source, not the engine or field Device identity.
- The [NAE55 analog-input PICS][ai-pics] lists `INSTANCE_NUMBER`, property
  **32589**, as Unsigned with no writable marker. The [binary-value PICS][bv-pics]
  does not describe this property, so observed mapped BV metadata must not be
  generalized into a documented BV write contract. A successful property read
  is not permission or evidence for a successful WriteProperty.
- The official [Metasys Server API v6 / release 15 reference][api] describes
  object attributes, schemas and ordinary PATCH operations. It does not publish
  an NAE database transfer/synchronization contract. A returned `readOnly` schema
  can also reflect the requesting account; do not treat a read-only account's
  schema alone as proof of the underlying attribute's write semantics.
- [SCT Synchronize][sync] merges an archive and the online database and applies
  changes without an engine reset. It starts by uploading current data, retains
  an original, checks structural conflicts, and applies the merge. Archive edits
  win conflicting attribute changes. This is more than a property write, and
  the help describes the workflow rather than its serialized request, package,
  authentication, acknowledgement and recovery protocol.
- The [documented MCT `.imp` workflow][imp] adds information; it cannot update
  existing objects. Delete/reinsert is not a substitute for preserving identity.

Read-only inspection of an authorized installation corroborated separate local
and source identities. Its API schema also returned `instanceNumber.readOnly`.
Public client assets exposed online attribute-edit and archive routes, but did
not establish an independent live NAE remapping transaction. No write-denial
probe, configuration download, sync, reboot or SQL write was used. Private
captures, credentials and vendor assets are not in this repository.

## Implemented inspection

Open a connected controller, select **Points & I/O → Configuration → Metasys
source mapping → Read Metasys source mapping**. It uses the selected target and
interface; no connection is opened automatically. It is useful for reviewing
current sources, including before a repair performed by a separately qualified
tool. It does not select or approve replacement sources.

`POST /api/bacnet/controller/metasys-source-mapping/inspect` accepts the existing
`address`, `device`, optional `router`/`dnet`, and one `object_id`. It requires
the normal local session header. This first profile admits analog-input and
binary-value objects only, with a live vendor-5 Device check before reading
proprietary attributes. A model string does not select a fabricated inventory.

All traffic is bounded ReadProperty under the existing pinned path lease. The
inspector checks Device identity, local point identity, name, item reference
(32527), source instance (32589), remote name (2564), and native remote-address
evidence (538). It repeats point identity/name/reference/source and Device
identity/vendor. A changed, missing, mistyped or unverified core value leaves
`mapping_observed: false` and retains the failure evidence. An opaque remote
address stays opaque; it is not converted into an assumed remote Device or route.

The UI separates local identity from source instance, retains observation time
and raw evidence, and discards late results after selection/interface changes,
disconnect or unmount. It shows partial-read failures without a verified mapping.
There is no proposal, write-plan, apply, restore or configuration-transfer route.
`write_support.available` is always false. The inspection neither verifies nor
claims to preserve Metasys GUIDs, historian links or extensions; it changes none.

## What is needed for independent live editing

A spare/test NAE of the relevant firmware and one authorized, controlled native
SCT mapping change are the next reference experiment. Retain before/after native
archives and transaction evidence privately. Establish:

1. Engine configuration capture/authentication, format and exact source field.
2. Whether small changes can be applied independently, their transaction
   boundaries, required state transitions and failure behavior.
3. Identity and unrelated-data preservation across upload, merge and application,
   including concurrent online changes and all extensions/incoming references.
4. Definite rejection versus lost acknowledgement; readback and recovery without
   replaying an uncertain write or assuming rollback succeeded.

Only after that reference exists should a distinct NAE adapter expose
Edit → Review → Apply → Verify. It must retain a fresh recoverable original,
bind the review to target/interface/firmware/source hashes, restrict the exact
changed fields, and independently read back identities, references and sources.
Historian linkage and meaningful current values/units also require verification.
Do not repurpose MCE/MOI File-3 field-controller transfers, ordinary property
writes, direct SQL updates or delete/recreate as a fallback.

## Verification scope

Authored direct and routed UDP peers independently emit native tags and reject
every non-ReadProperty request. Tests cover separate local/source identities,
typed values, wrong vendor/point, changes during inspection, failures/timeouts,
API session and request boundaries, and absence of an apply operation. Browser
coverage checks the selected point, late-result retirement and wrong-target
rejection. These tests qualify inspection software, not physical NAE remapping.

An authorized private read-only smoke check also observed one AI and one BV on
an operating NAE with the expected pre-existing source instances. No configuration
commands were sent, and no mapping edit or preservation-after-edit is claimed.

[hardware]: https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Metasys-Site-Management-Portal-Help/11.0/Insert-Menu/Object/Object-and-Feature-Tabs/Hardware-Tab/BACnet-Hardware-Tab
[ai-pics]: https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/NAE55-Protocol-Implementation-Conformance-Statement/12.0/BACnet-Standardized-Device-Profile-Annex-L/Standard-Object-Types-Supported/Analog-Input
[bv-pics]: https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/NAE55-Protocol-Implementation-Conformance-Statement/12.0/BACnet-Standardized-Device-Profile-Annex-L/Standard-Object-Types-Supported/Binary-Value
[api]: https://jci-metasys.github.io/api-landing/api/v6-15.html
[sync]: https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/SCT-System-Configuration-Tool-Help/17.1/Tools-Menu/Manage-Archive/Synchronize
[imp]: https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Network-Engine-and-Server-Commissioning-for-C-CURE-victor-Integration-Application-Note/15.0/Detailed-procedures/Transferring-device-and-point-information/Generating-an-MCT-.imp-file
