# Unfinished native identity text recovery

In **Overview → Identity settings**, choose controller name or native application
instance, then expand **Retained identity drafts**. **Save local identity draft**
saves raw proposal text and source references. **Import local identity draft**
restores that text after reloading. Existing retained work must be explicitly
discarded before replacement. Invalid imports preserve its fields and evidence.

Recovery preserves leading whitespace, unfinished instance text, both active and
inactive proposal fields, and earlier receipt/recovery identifiers as unverified
references. It imports no receipt, prepared recovery, native plan, allocation,
confirmation, transfer credential or controller-write authority. Review and
confirm any later controller change through the existing workflow.

## Context and original source

The file must match the current name/instance kind, connected/offline context,
interface configuration, address, Device and exact router/network. Every interface
configuration field stays bound. Only the application's explicitly declared
transient interface epoch is excluded from cross-session text matching; numeric
tokens in configuration are compared without binary64 rounding or underflow.
Unknown interface identity formats require literal equality. Imported epochs
never restore authority: pending replies still belong to the current full UI
selection and generation, including changes away and back to the same context.

If the file references a capture, the original capture and all three native
backup files must remain locally available. The local importer verifies the
snapshot hash, original target, file sizes and file hashes through the existing
private backup reader. Archived captures remain usable. A missing, changed or
damaged original is refused; reference metadata cannot substitute for its files.

The response contains the original sealed metadata body as exact UTF-8 text. The
browser hashes those exact bytes against the saved snapshot reference before
deriving a read-only capture pointer. It also verifies the exact incoming file
hash, document and current context. No native numbers or Unicode escapes need
to be re-encoded by JavaScript to prove the original source.

An offline file source can differ from the selected controller. Import does not
select its captured target, connect an interface or verify a responding device.
Existing fresh target, compiler, collision, allocation, confirmation, one-use
transfer and full readback checks still govern later field changes. Source-less
raw text has no fabricated capture. Empty/reference-only work does not acquire a
draft slot. Saving this reference file does not package original backup files or
add a native backup ZIP importer.

## File and workspace limits

The existing `native-identity-local-draft/1` reference format remains readable.
An optional `raw_imported` field records the most recent raw filename and SHA-256;
old receipt and recovery identifiers remain separate unverified references.
Ordinary edits and navigation retain that provenance. Explicitly adopting a new
native source or prepared recovery clears it. Re-export does not create nested
provenance histories.

Files are limited to 128 KiB. Raw names retain the editor's 128 UTF-16-unit bound;
instance text is limited to 65,536 units in this file profile. Interface identity
text is limited to 16,384 units and raw provenance filenames to 1,024 units. The
file ceiling can refuse heavily escaped text even within a field bound; it never
truncates work. Typing and native admission rules remain separate.

The existing 32-context workspace policy remains: no eviction, explicit discard,
no slot for empty views or passive receipts, and retained contexts remain editable
at capacity. Raw provenance is independently copied. Imports retire reviews and
confirmations immediately; edits, family/target/interface changes, navigation,
visibility and pagehide retire pending replies. Editing also releases the local
pending indicator without adopting a late response.

The Studio-token-protected local route is
`POST /api/bacnet/controller/native-application/local-drafts/import`, returning
`native-identity-local-draft-import/1`. Strict UTF-8, Unicode, duplicate-key,
schema, field, structure and byte checks apply. It performs local source reads
only, without compilation, receipt lookup, recovery preparation or file mutation.

Qualification uses authored native backups, local HTTP and isolated protocol peers.
Target-boundary browser coverage explicitly identifies its authored HTTP identities;
the actual field interface remains closed for raw recovery. Physical controller
and Bluetooth acceptance are separate.
