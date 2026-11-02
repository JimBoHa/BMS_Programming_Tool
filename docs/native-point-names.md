# Native point names in the controller workflow

Open a verified controller, choose **Points & I/O**, select a point's
**Configuration**, and expand **Edit point name**. Read its application backup,
enter a name, review, confirm and apply. This stays inside the selected point's
configuration; it adds no workspace destination or feature tile.

The native format profile discovers existing analog, binary and multistate value
objects through their typed BACnet identifiers and engineering references. It
edits only the existing typed native Name property (2390). It does not select an
inventory by controller model, allocate an object, change an object identifier,
rewire logic, move a terminal, change electrical mode or rename a supervisor label.
The controller's public BACnet Object_Name must agree before review and after
transfer. An archive-only change cannot count as verified success.

The compiler merges the captured saved parameters first, retains the source
character encoding, reframes variable-length records, and compares every other
expanded record byte, including opaque records. It rejects duplicate identifiers,
conflicting point names, stale references/hashes, unsupported strings and incomplete
snapshots. The Device identity and all non-name application bytes remain intact.

Apply uses the existing native transfer journal and one-use, expiring review. It
checks the exact route/interface, current Device and point name, fresh File 3 and
static directory, credentials and reported capacity before dispatch. Other fresh
saved values remain current. Original files and payload are durable before the
restore. Readiness polling uses reads only; a full native image and saved-setting
comparison follows. An uncertain receipt blocks another change and supports
explicit readback without replaying the application.

Unreviewed text, selected capture and receipts survive task navigation within the
workspace. Reviews and confirmations do not. Target/interface/point changes retire
the previous component's review and late responses. Retained receipts remain
available for their exact original station and point, including after restart.
Saving a receipt does not communicate with the controller.

The workspace holds up to 32 point-specific drafts without evicting earlier
work. Empty point views do not consume a slot. At capacity, a new capture is
refused until the operator opens an earlier point and explicitly chooses
**Discard local point name work**. This clears only that workspace buffer; it
does not delete original backups or the durable transfer journal. Draft buffers
last for the current page session, while retained receipts survive restart.

Reviews bind the exact preview operation, profile, source capture and digest,
point record/hash and proposed name. Apply responses must match the dispatched
operation, reviewed digest and selected edit. Readback must retain the original
receipt identity. A substituted response cannot clear the proposal or display
verified success; the original journal remains available for explicit readback.
Reading an older receipt does not clear a newer source-specific proposal.
Visibility changes retire reviews, and late receipt exports cannot trigger a
download after leaving the owning task. Receipt downloads retain their original
response bytes.

Authored tests cover compressed/plain archives, four supported string encodings,
Unicode, short/extended framing, opaque bytes, saved settings, stale selection,
duplicate names/identifiers, endpoint/confirmation guards, one-use transfer and
published-name verification. Browser qualification uses an owned UDP native peer
for transfer and explicit readback, with an authored point inventory surface; it
checks task navigation, draft retention, review retirement and desktop/phone layout.
These software qualifications do not establish electrical I/O or wiring acceptance.
