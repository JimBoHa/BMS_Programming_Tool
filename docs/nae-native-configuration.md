# Direct NAE configuration capture

This implementation communicates directly with the selected NAE over BACnet/IP.
It uses no JCT/SCT login, server, runtime, executable, archive API or configuration
SQL. It does not reuse a field controller's CAF/MOI transfer or File identifiers.

Status: internal backend capture implementation, with independent UDP peer tests
and a successful live read-only NAE preflight. One authorized live STARTBACKUP
attempt was explicitly rejected with security/password-failure; independent
readback confirmed idle state and the original identity/database revision. The
request was not retried and no File contents were acquired or changed. Live file
capture now requires the engine's BACnet backup/restore credential, which is
separate from a Metasys/JCT user-account login. Configuration decoding, editing and restore
remain unfinished. There is no user-facing source editor or deployment route.

## Protocol and operating effects

The NAE [File-object specification][files] describes sequential configuration
file replacement and limits File visibility to backup/restore sessions. An idle,
empty Configuration_Files array therefore does not establish lack of support.
The [BACnet backup procedure][backup] requires an acknowledged start, readiness
monitoring, file acquisition and an end operation. The protocol permits a device
to suspend control processing while in backup mode. Backup is an operational
state change even when no file contents or point values are written.

The first adapter admits an explicitly selected Johnson Controls NAE that
advertises AtomicReadFile and ReinitializeDevice. Preparation reads its native
identity, firmware, database revision, services, operational status and backup
timing. It sends no backup command. Its one-use, expiring review binds those
values, the exact endpoint/router/Device and existing interface instance, the
capture time limit and the stated operational effects.

An explicitly accepted capture repeats the preconditions, retains durable local
intent, then dispatches one STARTBACKUP request. It waits for the native backup
state rather than assuming an acknowledgement means files are ready. It reads
the active Configuration_Files array with bounds and duplicate/identity checks.
Only those advertised File objects are read. Their names never become paths.
Stream offsets, requested response sizes, EOF, declared file sizes where known,
total bytes and native socket/source/service/transaction evidence are checked.
Original bytes are saved privately with hashes; they are not interpreted as CAFs.

An acknowledged start owns one ENDBACKUP request, including after a failed file
read or cancellation. Native idle state, original identity/database revision and
original operational status must be read back before capture is verified. Local
storage failure cannot suppress that owned closure attempt. Unacknowledged start
or end outcomes retain uncertainty; there are no lifecycle retries or guessed
ownership. A surviving journal blocks another capture of that target until
explicit read-only reconciliation establishes recovery. Reconciliation does not
retroactively declare incomplete files a verified capture.

No point value, source property, File content, backup timeout setting, restart or
restore operation is written. Passwords, when required, are supplied explicitly
for that operation and are excluded from reviews, receipts and error records.
No default or guessed password is attempted.

## Current boundary and next work

`NaeHttps` adds a separate direct-engine SOAP authentication/read transport. It
uses the NAE's own HTTPS origin and native account, with explicit leaf-certificate
binding, bounded XML, no redirects/proxy discovery or authentication retries.
The native local-account domain is supplied explicitly. Session tokens stay in
memory and their original XML prefixes/bindings survive subsequent read requests.
Only the named navigation/schema/configuration-read methods and logout are admitted; no
command, configuration edit, archive import or restore method is exposed.

The native read family also admits `GetViewList`, `GetView`, `ReadPropertyMultiple`
and `GetEngView`.
Their typed helpers validate reference, view identifiers, modes and hierarchy
depth, encode XML booleans canonically, and use an unfiltered descendant class
selection for hierarchy reads. The navigation class argument is a child filter;
passing the selected object's class there can hide its differently typed children.
These additional methods have software-peer qualification; their live field
qualification is pending. The engineering reader admits no corresponding writer.
The property reader selects at most 64 distinct native identifiers from one exact
reference, using the WSDL's typed request structure rather than substituting an
XML-element wrapper or a property-name dictionary.

The HTTPS software peer tests cover the native credential envelope, legacy POST
header, exact namespaces, opaque token preservation, refusal/invalid-XML handling,
credential-safe errors and changed certificates. A first existing account was
refused. A subsequent operator-entered native account authenticated successfully,
and real engine hierarchy, configuration-definition and property-list reads
succeeded with the preserved native token. No JCT/SCT server participated.
These results qualify native authentication and those reads; they do not by
themselves establish current-configuration capture, editing or transfer.

Live inspection established two distinctions the remaining implementation must
preserve. `GetConfigView` returns a creation/configuration definition with default
values, not the referenced object's current settings. It must never supply a
backup, expected-old value or write readback. The inspected mapper's source-instance
field appears in that definition but has `use="output"` in its ordinary property
list. Neither creation configurability nor that directional metadata establishes
online writability. No write was
attempted against that operating point. A supported engineering/transfer method
and an isolated test object remain prerequisites for source edits. The vendor's
[engine-attribute reference][attributes] also distinguishes the BACnet
Communications Password from a user-account login.

The site-neutral `native_signin_page` factory supports an isolated local
qualification harness; it is not a product navigation destination or a completed
selected-controller workflow. Engine details are supplied by the harness and
escaped as text. Passwords clear on submission and the submit action stays
disabled until its handlers initialize. A raw Python template preserves JavaScript
string escapes, correcting a page-refresh bug found during qualification. Chromium
and WebKit tests exercise the actual generated page against authored local API
responses: refusal, retry, accepted login, logout, duplicate-submit prevention,
no navigation, narrow layout and disabled submission without JavaScript. These
browser checks do not establish that a native engine accepted an account.

The capture implementation is deliberately separate from the older passive File
reader, which does not enter backup mode, and from the field-controller native
application transfer. The small common transaction transport extraction preserves
the existing field-controller File allowlist.

Retaining every advertised byte is a prerequisite, not proof of a fully decoded
or editable NAE configuration. The native files still need format/version
identification, exact round trips and independent identity/reference/resource
preservation evidence. Changing source instances requires a qualified native
codec; patching an arbitrary byte pattern is insufficient. A future restore must
bind a fresh pre-write original, expected current configuration, exact firmware,
all preserved fields and a separately reviewed operating effect. Unknown native
content must survive. Lost writes require readback rather than retransmission.

Independent authored UDP tests cover idle-only absence of File objects,
session-discovered identifiers including File zero, opaque/empty originals,
unknown file size, stale revisions, busy state, duplicate arrays, wrong offsets,
lost lifecycle replies, password refusal, cancellation and local journal failure.
Existing application transfer regressions exercise the extracted transport.
The live results qualify preflight, backup refusal/readback and direct native
authentication plus the named hierarchy/definition/property-list reads. Neither
software tests nor these field reads establish live file capture, native edit
or restore acceptance. Exact targets, credentials and captures stay outside Git.

[files]: https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/NAE/NCE-Protocol-Implementation-Conformance-Statement/9/BACnet-Standardized-Device-Profile-Annex-L/Standard-Object-Types-Supported/File
[backup]: https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-135-2008n.pdf
[attributes]: https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/SCT-System-Configuration-Tool-Help/16.0.1/Insert-Menu/Supervisory-Device/Engine-Device-Object/Engine-attributes
