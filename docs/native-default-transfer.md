# Native effective Real-default controller transfer

**Program → Native backup defaults → Controller transfer** adds a reviewed transfer
for one existing class 526/527 Real Default Value property 3113. The field comes
from the controller's actual framed native application. It is a logical application
default, not an input/output force or a physical terminal reassignment. The Device
instance and name remain unchanged.

This operation extends the existing vendor-5 MCE/tagged-MOI generation-1 application
path. It supports direct BACnet/IPv4 and an explicit IPv4 router/DNET/MAC route.
Direct MS/TP, BTCVT, BBMD transfer, general logic creation, native package/resource
validation and physical controller acceptance remain separate. The local snapshot
compiler and file-copy editor retain their independent scopes.

## Operator workflow

1. Open and verify the controller through its exact route. Stop owned commands,
   field polling and COV monitors before native engineering work.
2. In Program, open **Native backup defaults**. Configure native backup/restore
   credentials under Details if they are not configured on this machine. These are
   stored privately on the server; they are not returned in status or receipts.
3. **Read current native backup** captures original Files 3, 11 and 12. Capture
   enters and ends backup mode; this is not an application restore. The compiler
   opens the retained source and derives its supported actual fields. **Save
   original native backup** exports the source ZIP without another field request.
4. Select an actual Real default. The table distinguishes the archive value from
   its effective value after merging saved application settings. Enter decimal
   text. Local review/export remains available independently of field transfer.
5. **Review controller default transfer** binds the exact station, current native
   identity, source manifest, application/directory hashes, selected record/property
   encoding, prior effective bits and proposed text. Review shows the stored
   float32 value/bits. An unchanged effective value cannot start a transfer.
6. Confirm the selected change and application interruption. **Apply native default
   to controller** consumes the review once and makes a fresh native backup. The
   application and saved selector directory must match the review. The selected
   effective value must still match; a changed value is refused before restore.
7. Other fresh saved application values are merged before the selected four-byte
   edit. Consequently, the final payload can differ from the preview payload; the
   receipt retains the fresh backup, final compilation and exact transmitted hashes.
   The actual File 3 capacity is checked. Original files, final payload and durable
   intent exist before the first restore request.
8. One start-restore, the existing storage-preparation interval, bounded File 3
   writes and end-restore activate the application. No File 11/12, firmware or
   standard property-write fallback is sent. The station is then read back.

Review expires after the existing fifteen-minute window. The total native operation
budget, per-request deadlines, transfer pacing and five-second restore preparation
are unchanged. Editing the proposal, source or selected station retires the old
review before paint and cancels its server plan. Local text remains source-bound.
Active operations lock workspace navigation; **Stop native operation** requests
cancellation and cannot undo a restore that was already dispatched.

## Verification and uncertainty

**Verified** requires unchanged native/standard Device identity, operational status,
the complete expanded native image matching the final payload, and preserved
effective saved application settings. Verification recompiles the retained fresh
backup using the exact reviewed edit. Every other merged native byte must match.
Only the existing documented runtime-counter and calculated-flow-output exceptions
can differ in subsequent saved values; the selected default has no such exception.

Matching File 3 bytes alone is insufficient. If the controller retains an older
saved default that overrides the new archive value, or another saved setting is
wrong or corrupt, the outcome remains uncertain. A smaller post-restore parameter
directory is acceptable only when effective values still verify. No missing value
is invented or copied from a controller-model template.

**Not sent** means no restore dispatch was recorded; its displayed reason explains
the failed preflight. **Outcome uncertain** means a restore may have occurred but
complete verification is absent. Protocol acknowledgement alone is not success.
No automatic retry or rollback occurs. Pending receipts block further native
engineering writes under the existing journal/instance guards.

Retained default-transfer receipts identify their own station and proposed field.
Load a receipt after reload/restart, reconnect its original local interface and
select its exact controller route, then use **Read back native default transfer**.
Readback can enter/end backup mode but never starts another restore or file write.
It appends evidence and resolves a pending receipt only after full verification.
Keep an unresolved receipt and its original files for independent investigation.

The UI exports exact original JSON review/receipt response bytes. A stale download
cannot follow another source, proposal or station. Receipt exports retain their
explicit original operation context rather than implying they belong to a newly
selected controller. Native identity screens list identity receipts; this view
lists default receipts. No site data or controller archives belong in Git.

## API and qualification

Token-admitted endpoints are
`POST /api/bacnet/controller/native-application/signal-default/transfer/preview`
and `/apply`. They use the same native operation lock, one-use plans, capture store,
credentials, durable journal, cancellation and `/readback` path as existing identity
operations. Operation kind is checked: an identity review cannot be applied through
the default endpoint or vice versa. Oversized intents fail before journal insertion
or restore, so dispatched evidence remains within the journal's readable limit.

Qualification uses authored native records and saved slots, independent literal
float32 bytes, production HTTP and actual UDP services. An independent literal
BVLC/NPDU proxy verifies explicit router/network/station envelopes while forwarding
native APDUs unchanged. Tests cover fresh-setting preservation, selected-value
drift, retained wrong defaults, corrupt settings, capacity/credential/expiry guards,
lost acknowledgement, restart recovery and no replay. Browser tests exercise direct
and routed capture/review/apply/readback. These are software and protocol-peer
checks; no physical MS/TP, BTCVT, controller firmware or plant-control performance
acceptance is inferred.
