# Recorded previous typed batch recovery

Open a native recovery receipt in controller **Changes** or **History → Recorded
changes**. The existing record list labels supported previous batch recovery and
its original parent. Details compare every originally selected Real, Boolean or
Enum field: original previous value, original result, retained value at recovery
review and the recovery proposal. Float32 signed zero remains visible as `-0`.

**Find original batch receipt** searches local native records for the original
receipt identifier. Both the parent and its recovery child can match. Missing
parents remain missing; this action does not recreate or reconcile a receipt.
The existing exact evidence JSON download preserves the original source response.

## Recorded evidence and independent validation

Profile `native-default-batch-recovery-recorded/1` recognizes only the four known
annotations of the separate recovery transfer profile. It validates the exact
origin schema and seal, original verified-proof reference, child identity and
retained review-source bindings. One to sixteen typed fields must match the
independently validated ordinary batch proposal in source order. Finite float32
bits, strict Boolean values, bounded Enum codes and current/previous/original-result
relationships remain explicit. Enum meanings remain unverified.

The browser independently checks the projection, its origin seal, the selected
typed values and original encoding hashes. Malformed, foreign, unsupported or
contradictory metadata shows **Batch recovery metadata unavailable**, without
typed values or a native-program handoff. Ordinary batch records keep their own
existing projection and display.

The ledger reads existing local child receipt metadata. It performs no parent
receipt lookup for validation, backup-file read, compilation, controller query,
preparation, review, restore or reconciliation. A source enumeration may separately
read the parent as an ordinary list entry; a missing parent does not invalidate
the child's recorded lineage. Original proof references describe the retained
parent verification and do not establish current controller state.

An uncertain child remains uncertain. A later inconclusive observation remains
visible even after an earlier verified readback; displaying its recorded lineage
does not replace the child outcome. Fresh controller recovery still uses the
independent [prepare](native-default-batch-recovery.md) and
[transfer](native-default-batch-recovery-transfer.md) workflows and their own
evidence, one-use review, confirmations and uncertainty rules.

The feature stays within the existing teal controller/file workflow. Tables retain
keyboard horizontal scrolling on smaller screens. Software qualification uses
authored receipts and isolated source/installed desktop/mobile Chromium/WebKit
workflows. Physical/BTCVT acceptance, general rollback, native authoring and
package/resource/runtime/CCT comparison remain separate. JCI-10 remains partial.
