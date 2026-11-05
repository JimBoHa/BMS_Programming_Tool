# Native backup capacity before controller operations

Native application capture and verification retain immutable original snapshots.
The active catalog remains limited to 128 snapshots. An authored regression
demonstrated that an application restore could complete and then remain uncertain
because its required verification snapshot could not be retained locally.

`COMM-NATIVE-CAPTURE-CAPACITY-PREFLIGHT-001` checks current local retention space
before starting these operations:

- Capture and explicit receipt readback require one available snapshot slot before
  entering their network path.
- Apply requires two slots before collision discovery or fresh backup: one for
  the fresh original and one for complete verification.
- Each capture session rechecks space before controller identity reads or backup
  state commands. Apply also rechecks the remaining verification slot after its
  fresh backup and compilation, before retaining an intent or starting restore.

An early Apply refusal remains `not_sent` with no transfer intent. Its one-use
review stays consumed. A later refusal during preflight may retain a fresh backup;
that does not mean a restore was sent. The existing backup-effect declarations
and durable dispatch journal remain authoritative.

These checks observe current capacity; they do not reserve slots. Local ZIP
imports and archived-backup restoration can compete for the same space. A write
after the last check can still prevent verification retention after dispatch.
That outcome stays uncertain with its original intent and receipt. No restore is
automatically repeated and no older backup is deleted or silently archived.

Use the existing [native backup catalog](native-backup-lifecycle.md) to archive an
appropriate retained snapshot, then perform explicit readback of the original
receipt. Archiving retains the original files and references. It frees an active
catalog slot, not disk space. A full-catalog refusal before readback makes no new
controller observation and leaves the retained receipt unchanged.

Authored checks cover literal 126/127/128 boundaries, strict counts, direct/routed
UDP, identity collision admission, capture-path races, actual ZIP imports before
and after dispatch, exact retained originals and explicit recovery with one
restore. The existing save/import/archive limits, wire requests, deadlines,
retries, compiler profiles and transfer/uncertainty rules remain unchanged.

This is desktop evidence-retention preflight. Controller RAM/flash capacity,
general compilation, vendor resources/packages and physical/BTCVT acceptance
remain separate. The previously retained combined WebKit navigation, network
timeout and Sedona observations are not explained or repaired by this change.
