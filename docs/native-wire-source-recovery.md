# Previous existing native wire-source recovery

Profile `native-wire-source-recovery-draft/1` derives a local previous-source
proposal for one existing class-536/575 property-3118 connection from an original
verified wire transfer receipt. It uses a new reviewed transfer and full readback.
JCI-10 remains partial; this is not a general application restore.

## Operator workflow

1. Open **Program → Native backup defaults** and choose a retained source. When
   connected, explicitly **Read current native backup** first. Capture enters and
   ends backup mode; preparing a proposal does not contact the controller.
2. Inspect the diagram recorded in the original wire-transfer receipt. Choose
   **Native wire source basis → Saved effective snapshot**, **Open saved wire
   sources** and that receipt's connection number. Open its retained receipt.
3. Reconcile a pending original attempt with explicit readback before preparing
   another change. **Prepare previous wire source** reconstructs retained local
   evidence. A different diagram/connection keeps preparation unavailable. This
   local workflow is available without an open controller.
4. Focus moves to the prepared result. The replacement selector is locked while
   the proposal is active. **Discard wire recovery proposal** restores the
   separate ordinary wire draft, including after task navigation. Source-bound
   proposals use a bounded transient browser cache; they are not durable projects.
   **Export exact previous wire proposal** saves the original response bytes.
5. An exact previous merged application image produces an already-recorded
   report with no transfer proposal. It does not establish current live state.
   Otherwise **Review controller wire transfer**, inspect the exact target,
   source/destination, tuple and parent receipt, confirm the wire change and
   controller interruption, then **Apply native wire to controller**.

## Evidence and boundaries

- The original separate wire receipt must be resolved, record possible dispatch
  and retain a verified result or immutable historical verified readback. A later
  observation cannot turn an explicit no-dispatch result into recovery authority.
- Reconstruct the original fresh saved-setting merge and wire compilation from
  its retained backup. Its selected tuple, references, byte offset/width,
  configuration guard and expanded payload hash must match the recorded outcome.
  Numeric/Boolean aliases for indices or tuple elements do not qualify.
- The current retained source must match the exact Device identity and route,
  original static directory and recorded original-after expanded application.
  The exact previous merged image is recognized separately as already recorded.
  Container recompression can differ. Unrelated native image or directory changes
  require separate engineering; this profile does not merge arbitrary programs.
- Re-run the existing effective wire compiler. The prior source must still exist
  with the same compatible class/configuration and an observed outgoing pin in
  the current diagram. Preserve the other three tuple fields, destination, ports,
  membership, execution order, layout, original source-index width and every
  other expanded byte. Check execution order and introduced cycles independently.
- **The v1 profile requires a current observed pin.** When the earlier edit
  removed the source's only outgoing connection, the separate
  [verified original-pin profile](native-historical-wire-pin-recovery.md)
  qualifies that actual original connection and unchanged current non-default
  source configuration. It retains the other compiler guards. Ordinary v1
  behavior remains unchanged; no pin is invented from a name/model.
- Other current saved values remain current. Review and pre-intent Apply
  reconstruct the parent/current-source lineage. Apply takes a fresh backup,
  rechecks application/directory and the selected graph/source/target signatures,
  merges other fresh settings and verifies controller-reported File-3 capacity.
  Credentials, ownership, interface, expiry, cancellation and one-use guards stay.
- One application restore can interrupt control. Verification requires the full
  native image, unchanged identity, operational state, effective selected wire and
  other saved settings. Lost acknowledgment stays uncertain. Explicit readback
  reconciles it after restart without a second restore or automatic rollback.

The 900-second review, 1,800-second operation budget, four-second individual File
bound and existing preparation interval remain. Direct/routed IPv4 software peers
qualify this operation; no new transport, block/port/wire/I/O allocation, general
compiler, whole-device restore or physical/BTCVT acceptance is inferred.

## API and Changes

`POST /api/bacnet/controller/native-application/wire-source/recovery/prepare`
requires the session token, `receipt_id`, `capture_id` and `snapshot_sha256`.
It creates no query, review token or transfer intent. Submit the returned proposal
and `origin_sha256` as `recovery_origin_sha256` to a new wire transfer preview.
The paired `recovery_parent_receipt` is mandatory for this purpose. The server
reconstructs the proposal; a caller-supplied parent is never write authority.

The child intent retains `recovery_origin` and its seal. Changes projects only the
known recorded wire profile, strict tuple/reference/index bindings and historical
proof. It keeps original dispatch separate from later readback and provides the
existing bounded parent-receipt search. Listing does not load original backup
files, revalidate the parent, authorize recovery or establish live state. Invalid
metadata stays unavailable while original receipt evidence remains readable.

Qualification includes literal graph/saved-byte cases, strict local HTTP,
independent direct/routed UDP peers, lost-commit/restart and Chromium/WebKit
offline/connected workflows. Name/instance recovery, general restore and
equipment acceptance remain future work.
The separate original-pin profile has its own proof and local-copy contract.
