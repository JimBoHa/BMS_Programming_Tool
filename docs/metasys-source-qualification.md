# Isolated Metasys source-method qualification

Status: internal experimental backend library. **Existing production source
editing and native supervisory configuration transfer remain unimplemented.**
Neither the creation contract nor a software test qualifies an existing source
property as writable. No general source-edit or deletion route is exposed to the
web interface. This work does not launch CCT, PCT or another vendor application.

## Why this is separate from source inspection

A mapped point has both a local identity and a remote source. Repairing a source
must retain the existing GUID, local object identifier, reference, names, parent,
extensions, incoming links and historian associations. Recreating a production
point is not an acceptable repair.

The [BACnet Hardware documentation][hardware] marks the source Instance Number
configurable without the writable flag. The [attribute notes][notes] distinguish
creation-time configuration from attributes that can change online. Consequently,
successful discovery, an API `canModify` permission, or permission to create an
object does not establish permission to change its existing source.

The [v6 API reference][api] documents schema-driven creation and ordinary object
PATCH requests. Its API profile and the authenticated online UI proxy have
observable differences: the latter can return HTTP 200 with a new-object
Location where the public creation contract documents 201. Newly created objects
can also be absent briefly from Focus reads; deleted objects can remain briefly
in navigation. A write is never repeated to resolve these cache windows.

## Implemented components

`MetasysConfigurationApi` provides bounded HTTPS authentication and metadata
reads with an explicitly trusted certificate fingerprint. A changed certificate,
foreign resource Location, invalid or ambiguous JSON, oversized reply, rejected
login, required password change or unaccepted terms stops the operation. It
performs no automatic redirects, proxy discovery or HTTP write retries. Tokens
and passwords are not retained in recovery records or exception messages.

`MetasysTemporaryMapping` prepares one isolated monitoring mapper using the
current creation schema. It separates the requested local identifier from its
remote source, checks the selected native engine and firmware, verifies engine
and parent through permitted network-device/navigation metadata, confirms the
General configuration category and checks identifier/reference conflicts.
Full System-object Focus access is not required for these identity checks.

Temporary device mappings disable time broadcasts and automatic alarming. AI/BV
mappings disable remote/intrinsic alarming. The payload contains no Present
Value, priority, output command, control link, historian or auto-restore setting.
Optional display fields come from the current server schema; additional required
fields stop creation. Discovering a schema does not qualify every mapper family
for actual hardware use: the live experiment below covered a device and AI.

Prepare returns an immutable, one-use, short-lived review bound to the account
generation, exact native interface/socket, engine identity, firmware, parent,
schema, reference and request. Apply repeats the preconditions and commits a
durable intent to the tool's private local SQLite recovery journal before its
single POST. This database is not the Metasys configuration database.

Creation verification independently checks the new GUID, parent, navigation
reference, name, ownership description, local identifier and source. Its result
explicitly reports `native_activation_verified: false`: API confirmation alone
does not establish activation on the physical NAE. Independently read the native
object identity, reference, source and live data before an experiment.

Read-only `reconcile` can find and verify the exact retained reference after a
lost reply or restart. No matching resource means outcome uncertain, not rejected.
An unresolved operation blocks another creation on the same engine. There is no
automatic retry, rollback, deletion or fallback transport.

`MetasysTemporarySourceProbe` admits only a verified AI created by this tool's
retained temporary-monitor intent. An arbitrary GUID, production point or imported
capture cannot become a probe target. It checks live API/native identities,
ownership, source, units, disabled alarming and absence of child extensions.
It supports two explicitly selected experiments: one native WriteProperty 32589,
or one authenticated v6 PATCH containing only `item.instanceNumber`. Each method
has a separate single-use review and durable intent. Rejection does not trigger
the other method; selecting another experiment requires a new explicit review.
No device mode transition, force flag, value command or array/priority write is
used. Native replies are bound to source, invoke ID and service, with matching
transport evidence; the shared wire observer now also handles SimpleACKs.

Acknowledgement remains unverified until fresh API and native source/identity
readback agree. If the experiment changes a source, a separate one-use restore
review admits only the retained original source and current expected replacement.
Lost replies retain uncertainty for read-only verification without retransmission.
All results keep `production_source_edit_qualified: false`; a successful isolated
source write would still require independent values, links and preservation
qualification before a production feature could be enabled.

Cleanup also uses a separate review and single DELETE bound to the retained
creation GUID. It requires the original source, matching native identity and
reference, and no children/extensions; it cannot cascade over a test parent with
children. Keep test objects isolated and independently check that nobody has
attached incoming references or historian records before cleanup. Verify both
native unknown-object and authenticated navigation absence. A cached navigation
entry retains uncertainty until another explicit read-only verification succeeds.
Never edit configuration SQL to remove an engine/server deletion marker.

The coordinators are internal Python services, not a general commissioning CLI
or user-facing workflow. Any qualified future editor belongs in the selected
controller's Points & I/O and Changes workflow. There is no new feature tile,
automatic field connection or deployment of an unsupported production writer.

## Verification and observed field boundary

Authored independent HTTP and literal UDP peers cover immutable reviews,
schema/class distinctions, wrong identities and firmware, stale sessions, occupied
or unverified local identifiers, certificate/origin checks, both creation status
contracts, one-send intent, refusals, lost replies, restart reconciliation,
restoration and owned cleanup. These software tests do not establish field
acceptance.

An authorized isolated live experiment on a supervisory engine successfully
created a temporary monitoring device and AI through BMS Tool code. Native reads
confirmed the AI's identifier, reference, source, units, value and healthy
reliability. Native WriteProperty returned error class 2/code 40,
`write-access-denied`. An independently reviewed authenticated PATCH returned
HTTP 400 with `writeAccessDenied` specifically for `instanceNumber`. Both were
verified to leave the original source unchanged. Neither method was retried.
The temporary AI and device were removed, then verified absent by native reads
and authenticated navigation. Private records contain exact targets and Pacific
timestamps; captures, credentials and vendor assets are excluded from the repo.

This result qualifies **creation, diagnosis and refusal handling**, not live
source remapping. The remaining writer requires a verified supervisory native
configuration capture/merge/apply protocol. [Synchronize][sync] describes the
desired upload-first merge without an engine reset, but its help page does not
specify the independent serialized transfer, authentication or recovery contract.
A stale archive, field-controller CAF/MOI transfer, direct SQL update, production
point recreation or repeated denied property write is not that implementation.

[hardware]: https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Metasys-Site-Management-Portal-Help/11.0/Insert-Menu/Object/Object-and-Feature-Tabs/Hardware-Tab/BACnet-Hardware-Tab
[notes]: https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Metasys-UI-Objects-Attributes-and-Commands-Reference-Guide/16.0/Concepts/Attributes
[api]: https://jci-metasys.github.io/api-landing/api/v6-15.html
[sync]: https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/SCT-System-Configuration-Tool-Help/17.1/Tools-Menu/Manage-Archive/Synchronize
