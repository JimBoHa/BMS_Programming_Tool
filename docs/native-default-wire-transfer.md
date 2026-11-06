# Combined native Real-default and connection transfer

Inside **Program → Native backup defaults → Combined native default and
connection**, the controller transfer task applies one existing Real Default
Value and one existing connection source through one guarded File 3 restore.
It reuses the selected controller, exact route, retained Files 3/11/12, actual
Real field, proposed decimal text and inspected connection. There is no separate
top-level destination or model-selected application inventory.

This is `native-effective-default-wire-transfer/1`, independent of the existing
single-default and wire-source transfer profiles. The local
[combined compiler](native-combined-default-wire.md) still grants no field
authority. A combined transfer requires its own current review and confirmations.
Device instance/name, blocks, connections, record membership, pins, execution
order and hardware assignments remain unchanged.

## Workflow

1. Open and verify the intended vendor-5 native controller using direct BACnet/IPv4
   or an explicit IPv4 router, network and MS/TP station route. Configure native
   backup/restore credentials privately. Stop owned commands, polling and COV
   monitors before native engineering work.
2. **Read current native backup** retains identity-qualified Files 3, 11 and 12.
   Capture enters/ends backup mode; it does not restore an application. Local
   compilation and original backup export remain separate operations.
3. Select an actual class 526/527 Real field, enter finite decimal text, open the
   combined compiler and inspect an actual retained connection. Select a qualified
   existing replacement source. Drafts remain bound to their original source.
4. **Review controller combined transfer** binds the source manifest, application
   and static parameter-directory hashes, actual identity and route, selected
   default's original encoding/effective bits, and the connection's configuration
   guard. Review shows the stored binary32 value, any decimal rounding, original
   and proposed bits, and both connection sources. At least one edit must change.
5. Confirm both proposed changes and application interruption. **Apply native
   default and connection to controller** consumes that review once. Apply captures
   a fresh backup and checks the original interface, credentials, expiry, identity,
   application, directory, selected effective default and graph configuration.
   A failed preflight does not enter restore.
6. Merge every other fresh saved value, then compile both edits together from that
   one merge. The final payload can differ from preview because unrelated saved
   values may have changed. The receipt retains the fresh backup and exact final
   compilation, payload hashes and configuration guard. Capacity, readable durable
   intent and final payload storage must pass before dispatch.
7. The existing restore path sends one start-restore, retains its five-second
   preparation interval, writes bounded File 3 blocks and sends end-restore once.
   It does not write Files 11/12 or retry a failed restore automatically. An
   acknowledgement alone does not establish verified success.
8. Readback verifies unchanged Device identity and operational status, the entire
   expanded native image against an independent fresh recompilation, the selected
   effective Real bits, the actual selected connection and the other saved values.
   Existing runtime-counter/calculated-value exceptions remain narrowly scoped.
   They cannot excuse a wrong selected default or connection.

Editing either proposal, changing source/route/task, closing the combined task or
coalescing a proposal A→B→A retires its review before repaint. Server plans are
cancelled when possible. Drafts and original receipts remain distinct from review
authority. The ordinary Real transfer is hidden while the combined task is open;
it retains its draft but cannot reuse a review from the other task. Finish or
discard an active previous-Real recovery proposal before reviewing a new combined
transfer. Existing workspace ownership locks and cancellation semantics apply.

## Outcomes, retained evidence and history

**Verified** requires the complete application and effective-value proof above.
An older saved default that overrides the new archive value, a wrong wire, corrupt
saved-value CRC, missing readback or unrelated changed application byte leaves the
outcome uncertain. **Not sent** means restore was not dispatched. A lost restore
acknowledgement can mean an application was applied even when its outcome is
uncertain; no automatic replay or rollback follows.

Retained combined receipts keep their exact controller and both original edits.
After restart, reconnect the original local interface and exact controller route,
load the receipt, then use **Read back native combined transfer**. Readback can
enter/end backup mode, but sends no restore or file write. It appends evidence and
resolves a pending operation only after the existing complete verification or
original-application recovery checks pass. Unresolved native operations continue
to block another native transfer. Keep original backups and uncertain evidence.

The task downloads exact review/receipt response bytes. Changes and History show
the recorded Real before/after bits, connection source/destination and payload
identity through a bounded local projection. Malformed/inconsistent metadata is
unavailable. History does not reload original application bytes, query the field,
prepare a transfer or grant a previous-value recovery proposal. Opening a record
does not establish its current controller state.

## API and qualification boundary

Session-token protected endpoints are:

- `POST /api/bacnet/controller/native-application/default-wire/transfer/preview`
- `POST /api/bacnet/controller/native-application/default-wire/transfer/apply`

Apply requires strict Boolean `default_change_confirmed`,
`wire_change_confirmed` and `application_transfer_confirmed`, plus the one-use
token and exact review digest. Combined plans cannot pass through older operation
endpoints. Existing native operation status, cancellation, retained receipt and
readback endpoints are shared; the new kind and profile remain explicit.

Qualification uses authored native records, independent literal byte patches,
real loopback UDP peers and direct/routed browser workflows. It covers unrelated
fresh saved values, selected/configuration drift, capacity/identity/credential/
expiry faults, malformed reviews/receipts, lost start/block/end acknowledgements,
restart/readback without replay, cancellation, synchronous proposal retirement
and recorded history without field access. Older transfer families remain under
regression checks. Source and installed-wheel Chromium/WebKit checks distinguish
software acceptance from actual controller acceptance.

General native graph generation, new block identities/connections, packages,
resources, hardware reassignment, native execution proof, CCT comparison, physical
controllers, BBMD transfer, direct serial and BTCVT are outside this profile.
JCI-03 and JCI-09 remain partial overall.
