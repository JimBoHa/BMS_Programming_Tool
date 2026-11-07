# Inspect a portable comparison evidence bundle

In the existing **Changes** or **History → Change ledger** view, open **Inspect
saved comparison evidence** and choose **Open comparison evidence bundle**.
Select a ZIP previously saved by **Save comparison evidence bundle**. The bundle
can come from another computer; its original captures and receipts do not need
to exist in this computer's catalog. Offline CAF and graph work remain available.

The inspector shows the original recorded controller/route, compared capture
route and time, selected historical proof kind/time and typed values. **Matches**
and **Different** describe the included historical comparison. A valid bundle
with an application, saved-value or route difference remains an internally
consistent record of that difference. Damaged or inconsistent evidence refuses
inspection. Signed zero remains visible as `-0`.

**Save inspection report** downloads the exact verified response bytes. **Save
original evidence bundle** preserves the complete incoming ZIP unchanged.
**Comparison details and original evidence** exposes each original member,
including the nested capture archives, for individual byte-preserving download.
Original capture IDs, evidence and file bytes remain unchanged.

## What inspection establishes

Profile `native-default-batch-bundle-inspection/1` checks the existing
`native-default-batch-evidence-bundle/1` format. It validates fixed ASCII paths,
stored ZIP local/central directories, boundaries, CRCs, member sizes/checksums,
duplicate-free bounded JSON, manifest seals and exact capture/source roles.
Each nested original capture is checked by the existing pure native ZIP reader,
including its manifest seal and original Files3/11/12 hashes and bounds.

The selected immutable proof must bind the original intent and native result.
Successful-result proofs and later verified-readback events remain distinct.
Recorded recovery children retain their own original files and lineage; earlier
parents are not required. The original typed edit and fresh saved-value compiler
are rerun through the existing comparison implementation using private in-memory
read adapters. The recomputed comparison must match the bundled report exactly,
including selected values, source differences and hashes. Proof preservation
fields must agree with the reconstructed original typed edits.

The browser independently checks the whole incoming file hash, inspection seal,
original comparison/manifest/member bytes and existing bundle contract before
display or export. File MIME descriptors supplied by the operating system do
not change the original bytes. File replacement, source/target changes, task
navigation, disclosure changes and page lifetime retire pending responses and
cached export callbacks. Canceling retires an observation without replaying it;
the same or another original file can be inspected again explicitly.

## Bounds and authority

The outer bundle is at most 20 MiB, each original capture at most 8 MiB, the
comparison at most 512 KiB and each intent/proof at most 128 KiB. The manifest is
at most 64 KiB. The existing native capture reader retains its 2 MiB per-file
limits. Only this multipart upload receives a 20 MiB plus 64 KiB framing request
limit; other application request limits are unchanged.

Inspection does not import captures, create catalog entries, restore receipts,
credentials or review plans, prepare recovery, connect to a network, query a
controller or perform a field write. The in-memory adapter has only read methods
and has no application-store, journal, credentials or native-service connection.
Reconstruction verifies internal consistency rather than supplying a deployment
artifact or enabling an apply action.

Hashes are not signatures or vendor provenance. Included source claims and
historical proofs are not independently authenticated, current-device
verification, complete controller backups/journals, general native compilation,
CCT/runtime comparison or physical/BTCVT acceptance. Catalog ingestion and whole
state migration remain separate work.

`POST /api/bacnet/controller/native-application/default-batch/result/inspect-evidence`
requires the existing local session token and one multipart `file`. Its sealed
JSON report is bound to the complete original ZIP hash and byte count. Processing
uses only the uploaded bytes and returns no retained receipt or authority token.

Qualification uses actual exporter bundles from authored localhost peers,
malformed/resealed evidence, isolated source/installed backends and
Chromium/WebKit desktop/compact/keyboard workflows. Production inspection itself
has no network or storage side effects.
