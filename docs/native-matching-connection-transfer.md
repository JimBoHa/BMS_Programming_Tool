# Native matching-connection transfer backend

The separate `native-effective-matching-connection-transfer/1` operation adds one
connection between existing native members. It uses an actual recorded prototype,
an observed output pin and an unused input with matching recorded configuration.
Execution order, cycle, continuation, framing, tag and size checks remain those
of the [local matching-connection compiler](native-effective-connection-compiler.md).
It allocates no blocks, points, I/O terminals or controller identities.

The existing local connection-copy/export workflow remains available. The
separately delivered [controller-workspace workflow](native-matching-connection-workflow.md)
uses this service from the current Program connection task, with explicit
Review/Apply/Verify and retained uncertainty evidence.

## Review, apply and verify

1. Capture the selected controller's original Files 3, 11 and 12 through the
   existing native backup service. Retain the exact interface, route, station,
   Device identity and original evidence hash.
2. Select a diagram, recorded connection prototype, observed output member and
   unused matching destination through the existing saved-effective connection
   source API. Retain the archive/effective hashes, record/property/continuation
   hashes, prototype tuple and original connection count.
3. POST those source fields, the authoritative target and a fresh operation ID to
   `/api/bacnet/controller/native-application/matching-connection/transfer/preview`.
   Review checks the retained source, compiler output and responding identity.
   It retains a one-use review and a configuration guard covering the diagram,
   prototype endpoints and selected source/destination. A separate compilation
   digest binds the guard and parameter qualification to the compiled report.
4. POST the returned token/review hash and a fresh operation ID to the matching
   `/apply` endpoint. Both `connection_change_confirmed` and
   `application_transfer_confirmed` must be actual Boolean `true` values.
5. Apply checks current interface, credentials, review expiry, exact identity,
   fresh backup and controller-reported capacity. Original application and saved
   directory hashes must still match. Other fresh saved values may advance; the
   selected configurations and graph must match the reviewed guard. The final
   payload can therefore differ from preview while preserving those newer values.
6. The original backup, final payload, intent and dispatch events are retained
   before the single existing restore sequence. Only application File 3 is sent.
   Full native/effective readback and saved-setting preservation are required
   before the result becomes verified.

The native interface must already be open. These endpoints use the existing
session-token, ownership, pending-target, cancellation, review, request and overall
operation limits. This operation cannot consume a default, existing-wire,
point-name or identity review. A mutated retained connection review is refused.
No address allocation or collision scan is performed.

## Outcomes and evidence

Verification compares the entire expanded application to the compiled connection
and fresh settings, checks the appended effective edge and connection count,
retains original graph members/order/layout and continuation, and verifies all
saved settings. Existing qualified runtime counters and calculated outputs remain
separate reported observations. Unexpected saved differences reject verification.

A protocol acknowledgment alone cannot establish success. Lost replies, changed
application/settings or incomplete readback retain uncertainty and the original
receipt. Explicit restart/readback uses the existing reconciliation endpoint and
does not replay a restore. Complete original-image/settings recovery is reported
as `recovered_original`, separately from verifying the proposed connection.
There is no automatic inverse deletion or new connection-removal writer.

Capture, fresh backup and application readback can enter and end controller
backup mode. A `not_sent` restore outcome does not mean no backup-state commands
occurred. Apply can interrupt control. Existing transaction limits and dispatch
receipts remain authoritative; a local digest is not a controller signature.

Changes/History now project known connection references, prototype/new tuples,
counts, compilation hash and recorded confirmation from the retained intent.
This projection neither reopens original backups nor queries controllers. It
does not substitute for present graph state, original-source validation or a
fresh transfer review. Malformed/future metadata remains available as original
evidence while its interpreted connection fields are withheld.

## Capability compatibility and acceptance

The default `native-backup-operation-capabilities/12` and explicit versions 11/12
retain their existing contracts. Explicit version 13 adds the single
`matching-connection-transfer` row to version 12's 24 operations. Removing that
row and selecting version 12 reproduces the complete older response. Capability
analysis compiles nothing, sends no controller request and prepares no write.
`preflight-required` means a captured source can attempt its separate connected
review; it does not imply current field acceptance.

Authored software checks cover direct/routed UDP, literal full-byte append
oracles, fresh values, configuration drift, strict HTTP admission, durable
originals/intents, failed replies, readback/restart and recorded evidence.
Existing bounds, retries and historical failures are unchanged. This is a scoped
native protocol/format operation, not arbitrary native programming, resource or
package qualification, native runtime semantics, CCT acceptance or physical/BTCVT
acceptance. JCI-03/JCI-09 and broader recovery remain partial.
