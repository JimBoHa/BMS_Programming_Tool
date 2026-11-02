# Previous controller name recovery

In **Overview → Identity settings → Controller name**, select a resolved native
name-transfer receipt and a complete retained backup. Expand **Previous controller
name**, then choose **Prepare previous controller name**. **Load retained name
backups** selects an existing source without opening a network interface.
Preparation and exact evidence downloads work offline.

The proposal temporarily overlays the ordinary name draft. **Return to ordinary
name draft** restores that text. Source, receipt, task, target, interface and
visibility changes retire pending local replies, including A→B→A changes. A
bounded in-memory context cache retains local sources, receipts, ordinary drafts
and completed proposals across task navigation. It never restores a transfer
review, confirmations or an operation. Reload requires explicit source selection.
The [32-context retention policy](native-identity-draft-capacity.md) refuses new
work instead of evicting older drafts and provides explicit save/discard actions.

An offline proposal does not change a controller. Connect and verify the exact
source station, choose **Review name change**, confirm both the name change and
application transfer, then choose **Apply controller name**. A retained source
from another station cannot enable field review. Existing freshness, identity,
credentials, ownership, capacity, expiry and one-use checks remain. Native
capture/readback can enter and end backup mode; Apply separately restores the
application and can interrupt control. No property-write fallback or instance
reservation is introduced.

## Qualified evidence

The local profile is `native-controller-name-recovery-draft/1`:

- The original receipt describes a confirmed name-only application transfer,
  preserves the Device instance and has possible dispatch with a resolved,
  historically verified result or first retained verified readback event.
  Reconcile uncertain originals first. Later observations do not rewrite the
  original attempt or erase that verification event.
- Original Files 3/11/12, manifest, recorded identity/route and complete compiler
  output reconstruct the exact recorded original payload. Both names retain the
  existing character encoding, nonempty/control/whitespace and 128 UTF-8 byte
  restrictions. Exact strings identify names; label similarity supplies no proof.
- The current source has the same Device instance, root reference/class, route,
  vendor, model and other identity, with the recorded new name. Its static
  parameter directory remains exact. Normalizing only its root name to the
  recorded outcome reproduces the original-after expanded native image.
  Unrelated raw application changes refuse.
- A source already recording the previous name produces an evidence-only result
  only if that exact name-normalized image matches. It supplies no new proposal
  and does not verify the current controller. Other raw application changes are
  not silently treated as completed recovery.
- Other current saved values remain current. New name-only compilation merges
  fresh settings. Review and pre-intent Apply reconstruct the original/current
  proof and compare the paired origin seal. An old receipt/token or supplied
  metadata cannot authorize another write.

The normal name compiler preserves the instance, records, references and every
non-name merged byte while reframing a changed-length root name. New Apply retains
its own backup and typed lineage, dispatches once, and requires reviewed identity,
operational status, complete native readback and name-only parameter preservation.
Lost acknowledgement stays uncertain until explicit **Read back application and
name**, including after restart. No old transfer is replayed or automatically
reversed.

## APIs and recorded Changes

All paths below start with `/api/bacnet/controller/native-application`:

- `POST /name/recovery/source` takes capture ID and immutable snapshot SHA. It
  validates original files, saved schema and retained identity and exposes the
  actual root under `native-controller-name-recovery-source/1`. Generic record
  reader contracts remain unchanged.
- `POST /name/recovery/prepare` adds the original receipt ID and returns a sealed
  local report and optional proposal.
- `POST /name/recovery/preview` requires that proposal, paired parent/origin SHA,
  existing exact field target and operation ID. Ordinary `/preview` rejects
  recovery fields.
- Existing confirmed `/apply`, `/readback` and receipt routes retain their
  one-use, durable uncertainty and no-replay behavior.

All routes require the Studio token. Source/prepare create no field request,
review or intent and reject mutation fields. Downloads preserve original HTTP
report bytes. The browser binds source, receipt, historical proof, root, names,
route and instance before accepting a proposal, review or verified child receipt.

Changes projects strict recorded CharacterString lineage and its historical
verification separately from the child outcome. It checks the origin seal and
child metadata without loading source files, revalidating the parent or granting
a transfer. Inconsistent metadata stays unavailable; original evidence remains
readable.

This software-qualified name operation leaves JCI-10 partial. Instance recovery,
general restore, new logic/I/O allocation, package/release compatibility and
physical/BTCVT acceptance remain separate. Existing 900-second review,
1,800-second operation, four-second File and preparation bounds remain.
