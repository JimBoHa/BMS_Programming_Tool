# Previous controller instance recovery

In **Overview → Identity settings**, choose **Device instance number** and
**Connected application transfer**. Open a complete retained backup and a resolved
instance-transfer receipt. Expand **Previous controller instance**, then choose
**Prepare previous controller instance**. **Load retained instance backups** and
preparation work offline, including after opening a CAF.

The result is a local previous-number proposal. It preserves the ordinary number
draft; **Return to ordinary instance draft** restores that text. Exact evidence
downloads preserve the original HTTP response bytes. Local sources, receipts,
ordinary drafts and completed proposals stay in a bounded context cache across
task navigation. Reviews, confirmations and active operations are not restored.
Reload requires explicit selection. Source/receipt/task/target/interface and
visibility lifecycle changes retire pending replies, including A→B→A changes.

Reserve the previous number across the BACnet internetwork, including offline
devices. Connect and verify the exact source station, choose **Review application
instance change**, confirm the reservation and application transfer, then choose
**Apply application instance change**. Review and Apply perform separate fresh
bounded collision checks. Their subnet or selected-router/network scope remains
explicit. Silence does not prove that a number is unused; the local proposal does
not allocate one.

## Original, verified-after and current evidence

The profile is `native-controller-instance-recovery-draft/1`:

- The original receipt must describe a separate confirmed instance-only native
  transfer, with exact unsigned22 old/new Device numbers, unchanged name, possible
  dispatch and a resolved historical verification. The first verified readback
  event can supply that fact after an uncertain result. Reconcile pending
  originals first; later observations never rewrite the original attempt.
- Its original Files 3/11/12 and manifest reconstruct both the recorded compiler
  result and exact payload. Vendor, name, model, root, route and recorded identity
  remain bound to that source.
- The actual verification capture named by the historical proof is also required
  for a new proposal. Its identity, application image and complete saved-setting
  preservation are revalidated independently. This retained **verified-after**
  directory matters: a controller may rebind or compact saved parameters during
  renumbering. The original pre-transfer directory is not substituted for it.
- The current source must retain the same route, name, model, other identity and
  original-after application image. Its static directory must match the verified
  outcome. Other current saved values remain current.
- A source already recording the old number can produce evidence without a new
  proposal if normalizing only its two typed identity fields recreates the
  recorded outcome. Existing root-selector object-number bytes may normalize for
  this comparison; all other directory bytes, metadata, selectors and positions
  must remain exact. This comparison does not write a parameter directory or
  claim that the current controller was restored.
- The proposed destination is separately checked under the existing settings
  preservation policy. An unmatched saved root value must not silently become an
  application setting only because the previous number makes its selector match.
  This check runs again against fresh pre-transfer files before intent/dispatch.

New review and pre-intent Apply reconstruct the original/current evidence and
paired origin seal. An original token, imported metadata or old receipt alone
cannot authorize another transfer. Existing target/interface, current application
and directory, credentials, ownership, capacity, cancellation, expiry and one-use
guards remain. Names and other fresh settings are preserved.

Apply retains its own original backup and typed lineage, transfers File 3 once,
and requires operational status, the reviewed identity, complete native readback
and settings preservation. Capture/readback can enter and end backup mode; Apply
can interrupt control separately. Lost acknowledgement remains uncertain until
explicit **Read back application and instance**, including after restart.
Readback uses the child's own backup without replaying the transfer or requiring
older ancestor files. A new proposal still requires its original evidence.

## APIs and recorded Changes

All paths below start with `/api/bacnet/controller/native-application`:

- `POST /instance/recovery/source`: capture ID and immutable snapshot SHA; a
  qualified local identity/source reader under
  `native-controller-instance-recovery-source/1`.
- `POST /instance/recovery/prepare`: adds the resolved original receipt ID and
  returns a sealed local report and optional previous-number proposal.
- `POST /instance/recovery/preview`: the exact proposal, paired parent/origin SHA,
  authoritative target and operation ID. A name edit is rejected. Ordinary
  `/preview` rejects recovery fields.
- Existing confirmed `/apply`, `/readback` and receipt routes retain durable
  uncertainty and no-replay behavior.

The Studio token is required. Source/prepare create no field query, review or
intent and reject mutation fields. The browser binds source, original proof,
verified-after capture, current files/root, numbers, unchanged name and route
before accepting a proposal, review or verified child receipt.

Changes projects recorded ObjectIdentifier lineage: original parent, current to
previous number, unchanged name and historical verification. It validates strict
origin/child bindings, source/directory hashes and both recorded four-byte patches
without loading sources, revalidating parents or allocating a number. Inconsistent
metadata stays unavailable while original receipt evidence remains readable.

Direct/routed IPv4 software peers qualify this operation. The authored router
forwards actual bounded Who-Is requests and wraps actual I-Am replies; an unused
candidate reaches the peer and declines, while an occupied one is observed.
These checks do not certify physical routing or every device on an internetwork.
General application restore, arbitrary authoring/allocation, package/release
compatibility and physical/BTCVT acceptance remain separate. JCI-10 stays partial.
Existing 900-second review, 1,800-second operation, four-second File and preparation
bounds remain unchanged.
