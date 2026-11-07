# Native execution-order controller transfer

In **Program → Native backup defaults**, capture the selected controller or open
its retained backup. Inspect an actual native activity/sequence record, choose
**Change execution order**, inspect its effective order and move an existing
block. Select **Native execution-order destination → Selected controller**.
**Review execution-order transfer** reads the responding controller's identity
and creates a new one-use review. Confirm the proposed order and possible control
interruption before **Apply execution order to controller**.

This implements `COMM-NATIVE-ORDER-TRANSFER-001`, profile
`native-effective-execution-order-transfer/1`, using the separately qualified
[saved-effective local compiler](native-execution-order.md). The existing common
native transaction performs the restore. This does not grant general native
authoring or compatibility with every FX/Metasys controller or firmware.

## Admission and preservation

- Require the exact selected route/Device, current plain BACnet/IPv4 interface,
  vendor 5 identity and matching original File 3/11/12 backup. Another station
  with the same Device number cannot adopt the source or review.
- Accept a nontrivial complete permutation of 1–512 existing native class
  536/575 diagram members. Preserve each original numeric payload width and each
  recorded wire's before/same/after relationship. Do not create blocks, links,
  object identifiers, hardware assignments or I/O.
- Guard the original application and saved directory, selected diagram and all
  members' non-default configuration. Saved merges cannot change identity,
  membership, order, wiring, layout or continuation metadata. Unknown parameter
  encodings and unqualified omitted application fields are refused.
- Before dispatch, capture fresh files and recompile from their actual saved
  values. Retain the reviewed configuration guard while allowing fresh saved Real
  and Boolean values. The final payload can differ from the historical preview.
- Preserve every other expanded merged application byte. Check the controller's
  advertised application capacity, current credentials, interface identity,
  operation lifetime, pending engineering work and local evidence capacity.

The edit uses explicit execution-order request/guard/operation profiles and two
strict Boolean confirmations. It cannot consume another native edit's review.
Changing source, target, interface, proposal, destination, task or page lifetime
retires field authority. Local proposals remain with their original source;
restoring a draft or loading a receipt prepares no review or restore.

## Restore, readback and interrupted operations

The common writer retains a fresh original snapshot, reviewed payload and durable
intent before the first restore command. It sends one File 3 restore attempt,
waits for readiness and captures complete native and saved-setting readback.
Verification compares the entire expanded application with the expected fresh
compilation, then checks the effective saved order, original widths and wire
phases, identity and saved settings. Existing qualified runtime counter and
device-calculated differences retain their separate rules.

A protocol acknowledgment alone does not verify the change. Dropped start,
block or commit acknowledgments retain uncertainty without retrying the restore.
Use **Read back execution order** against the original station/interface. The
retained receipt survives restart; explicit readback never replays Apply.
Complete original-image recovery is reported as `recovered_original`, with the
proposed order explicitly unverified. No automatic inverse order is sent.

Active mutation locks the workspace and its disclosure. Late receipts remain
attached to the original operation after page/task retirement. Exact reviews and
receipts can be downloaded separately from a local native copy. Changes/History
recognize the execution-order family and recorded diagram reference, preserve the
original response bytes and offer navigation to native program tools. That link
performs no transfer or readback and restores no field review.

## API and qualification boundaries

Token-protected strict endpoints:

| Route | Behavior |
| --- | --- |
| `POST /api/bacnet/controller/native-application/execution-order/transfer/preview` | Validate the retained source and proposal; read current identity; retain one review. |
| `POST /api/bacnet/controller/native-application/execution-order/transfer/apply` | Consume the exact review with both confirmations; use the common durable restore/readback path. |
| Existing native status, credentials, cancel, receipts and readback routes | Share current ownership, capacity, evidence and recovery contracts. |

Qualification uses authored localhost direct and routed BACnet peers, literal
native byte oracles, strict API/contract checks and browser lifecycle tests. It
does not use a live site, physical controller, Bluetooth adapter or VM. General
compiler/package/resource/runtime validation, CCT comparison, new identities and
physical acceptance remain unfinished under JCI-03/JCI-09 and their related work.
