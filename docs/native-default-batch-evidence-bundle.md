# Save retained comparison evidence

In **Program → Native backup defaults**, load a verified batch receipt and compare
the selected retained source with its recorded result. **Save comparison evidence
bundle** exports that comparison and its supporting local evidence as one ZIP.
The export works offline and preserves the ordinary unfinished edit buffer.

Profile `native-default-batch-evidence-bundle/1` requires the exact comparison hash
currently displayed. The server reconstructs the original verified typed result
and recomputes the comparison before export. Changed or unavailable original/current
evidence refuses export. An explicitly reported source difference remains a
difference in the package; exporting never changes its verification status.

## Included evidence

- `manifest.json`: the source roles, snapshot bindings, selected proof reference,
  comparison state, member byte counts/checksums and a manifest seal.
- `comparison.json`: the freshly checked comparison, using the same JSON response
  serialization as the comparison endpoint.
- `intent.json`: the original sealed intent for the selected batch operation.
- `proof.json`: its selected immutable verified result or verified readback event.
- `captures/<capture-id>.zip`: existing native backup archives containing their
  manifests and original Files3/11/12. If both roles name one capture, it appears
  once. The exporter checks each returned archive against the retained original
  manifest/files before adding it.

Supported recovery children use their own intent, proof and pre-transfer backup.
Their earlier parents are not reopened after dispatch. The selected proof is
included instead of materializing the complete event journal. No credential,
unconsumed review, import, automatic restore or new field authority is created.
This is retained application/settings evidence, not a complete controller backup,
deployment package or CCT/runtime/physical acceptance certificate.

## Integrity, bounds and ownership

The outer ZIP uses stored members with fixed ASCII paths. Capture archives retain
their existing format. Each capture archive is at most 8 MiB, the comparison at
most 512 KiB, each intent/proof at most 128 KiB and the complete bundle at most
20 MiB. Existing capture admission, import limits and native field contracts remain
unchanged.

The browser verifies the response profile, exact report/source/proof bindings,
declared size, whole-bundle hash, ZIP boundaries/directories/CRC, fixed member
names, manifest seal and member checksums. Canonical intent/proof verification
keeps their original numeric atoms, including signed zero and float renderings.
Nested original capture bytes are checked by the server before export. The bundle
does not add an import or receipt-restoration path.

Source, receipt, task, visibility and report replacement retire pending exports
and cached callbacks. A late or altered response cannot trigger a download.
All export work reads local retained evidence; it performs no controller query,
backup-state command, compilation for deployment, journal write, restore or
reconciliation. Earlier comparison and field workflows remain independent.

`POST /api/bacnet/controller/native-application/default-batch/result/evidence`
requires the local session token and exactly `receipt_id`, `capture_id`,
`snapshot_sha256` and `comparison_sha256`. The ZIP response carries its bounded
description in `X-Native-Batch-Evidence`. That transport description does not grant
native or field authority.

Qualification uses authored captures/proofs, isolated source/installed backend
tests and desktop/mobile Chromium/WebKit workflows. Physical/BTCVT acceptance,
broader verification packages, general application authoring and complete backups
remain separate under JCI-10.
