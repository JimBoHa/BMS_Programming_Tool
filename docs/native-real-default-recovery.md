# Previous effective native Real default

Profile `native-real-default-recovery-draft/1` prepares the previous effective
value of one existing class-526/527 property-3113 Real default from a retained,
historically verified native default-transfer receipt. It does not replay an
earlier operation or restore an entire backup. JCI-10 remains partial overall.

## Operator workflow

1. Open **Program → Native backup defaults**. Select and open a retained backup.
   When connected, explicitly **Read current native backup** first. Capture enters
   and ends native backup mode; selecting a retained backup performs no field query.
2. Open the original Real-default transfer receipt. Resolve an uncertain original
   attempt with **Read back native default transfer** before preparing another edit.
3. Choose **Prepare previous Real default**. Preparation reads only retained local
   evidence. It selects the original field and proposes its previous *effective*
   saved value, which can differ from the old archive default. The ordinary field
   draft remains separately retained. Focus moves to the local result. The prepared
   value is read-only; discard
   the proposal to return to ordinary editing.
4. Inspect or export the exact local proposal. If the retained source already has
   the previous value, no transfer proposal is created. This observation does not
   establish current live controller state.
5. Explicitly **Review controller default transfer**, inspect the exact route,
   field, prior/proposed float32 bits and parent receipt, and confirm both the edit
   and controller interruption. **Apply native default to controller** consumes a
   new one-use review. Full native application and effective-setting readback are
   required for a verified result.

Local preparation remains useful offline. Field transfer requires the existing
qualified direct or explicitly routed plain IPv4 native adapter, an open matching
interface, matching selected controller, private transfer credentials and zero
owned commands. Task/source/target/interface changes retire pending reviews and
late preparation responses. Source-bound local proposals survive task navigation;
they are transient browser state, not a new persistent project format.

## Evidence and preservation contract

- The original receipt must be a separate existing Real-default transfer with
  unchanged Device instance and name, a possible dispatch and no unresolved pending
  outcome. A verified immutable result or a retained historical verified readback
  is required. A later observation never rewrites the original dispatch/result.
  An explicit no-dispatch refusal cannot gain recovery authority from readback.
- Original backup manifest/files, original effective compilation, selected field,
  exact before/after bits and expanded native payload must agree. Finite float32
  values, including signed zero, are preserved by bits.
- The current retained source must have the same exact remote route, Device and
  identity. Its expanded File 3 must equal the recorded original-after native
  payload, and its static parameter directory must equal the original directory.
  Gzip recompression can differ while the expanded native bytes remain identical.
  Changed application configuration, unknown saved layouts or a selected effective
  value other than the original outcome/previous value refuse preparation.
- Other current saved values remain current. A new review binds the original
  receipt, immutable proof, source hashes and proposal. Apply reconstructs that
  lineage again before durable intent, captures a fresh source, checks the
  selected value/application/directory, merges other fresh saved settings and
  checks actual File-3 capacity. Existing credentials, ownership, interface,
  cancellation, expiry and uncertainty guards remain in force.
- The new intent retains `recovery_origin` and `recovery_origin_sha256`, including
  parent receipt/intent/proof and old/current source identifiers. The parent is
  unchanged. Only the existing confirmed File-3 application path dispatches;
  no old token/payload, automatic inverse write or retry is used.
- A lost acknowledgement remains uncertain and blocks another write. Explicit
  readback can resolve the new receipt after restart without another restore.

The existing 900-second review lifetime, 1,800-second operation budget,
four-second individual File request bounds and native storage-preparation interval
are unchanged. Backup/readback can send start/end-backup state commands.

## API and scope

`POST /api/bacnet/controller/native-application/signal-default/recovery/prepare`
requires the local session token and exactly `receipt_id`, `capture_id` and
`snapshot_sha256`. It creates no review, transfer intent or controller request.
Its report and original JSON bytes can be exported from the web workflow.

The existing Real-default `/transfer/preview` accepts the optional paired fields
`recovery_parent_receipt` and `recovery_origin_sha256`. It independently reconstructs
the prepared origin; caller-supplied lineage cannot authorize an arbitrary value.
Ordinary Real requests retain their previous body/evidence shape. Boolean, wire,
name and instance recovery are separate future profiles. General restore,
application allocation, firmware migration, native hardware reassignment and
physical controller/BTCVT acceptance remain unimplemented by this slice.

Qualification uses authored original/saved bytes, strict local HTTP, actual direct
and routed UDP native peers, and Chromium/WebKit workflows. Software verification
does not establish actual equipment performance or acceptance of every release.
