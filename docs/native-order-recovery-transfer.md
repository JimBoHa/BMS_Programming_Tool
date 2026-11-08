# Previous native execution-order controller transfer

`COMM-NATIVE-ORDER-RECOVERY-TRANSFER-001` extends the existing verified
[previous-order proposal](native-order-recovery-proposal.md) with a separate
confirmed controller transfer and recorded parent lineage. The profile is
`native-execution-order-recovery-transfer/1`. General native logic authoring,
arbitrary snapshot restoration and CCT/firmware equivalence remain unfinished.

## Operator workflow

1. Open a controller, then **Program → Native backup defaults**. Select a retained
   after capture, inspect its diagram and choose **Execution order**.
2. Choose the controller destination, load the original order-transfer receipt,
   compare the retained result and prepare its previous-order proposal. These
   actions are local. They require the actual verified original result and an
   exactly matching retained after application, effective order and static
   directory.
3. **Use previous order for controller review** selects that verified proposal
   without replacing the unfinished local order draft. The selected original
   receipt, immutable proof and member order remain visible. **Use local order
   draft for controller review** cancels the selection and its review.
4. **Review previous execution-order transfer** checks the selected controller,
   exact route, retained source, original proof and current fresh application.
   Inspect the before/after members, native widths, phase relationships, capacity
   and other-setting preservation evidence. Both order-change and application
   interruption confirmations are required.
5. **Apply previous execution order to controller** performs one new restore,
   with a new durable intent and receipt. Complete native/effective readback must
   verify the actual previous permutation. Saving the receipt retains the exact
   received JSON bytes.
6. An uncertain outcome remains pending. Load its retained receipt and explicitly
   **Read back execution order**. A lost acknowledgment never reuses the original
   token or automatically repeats a restore.

Local graph/CAF drafts, the unfinished order draft, original receipt and original
capture remain intact. The separate local replacement/export action is still
available without a field connection. New controller actions appear only when
the server advertises this specific recovery profile and the selected controller
and interface match the captured source.

## Evidence, compilation and transfer

The request adds only a paired original receipt identifier and origin hash to the
ordinary source-bound order proposal. Before preview network reads, the server
reconstructs the original actual order compilation and its verified result or
first immutable verified readback. It independently prepares the previous
proposal against the selected retained source. That exact proposal, comparison,
proof and origin must match the requested change.

The actual existing order compiler handles the supported Activity and Engineering
diagram records. Its guards bind the original membership/order, unsigned native
widths, property bytes and wire phase relationships. Fresh other saved settings
are retained by the existing effective compiler and common transfer path. A
changed selected diagram/order/static directory is refused. The original proof
and lineage are reconstructed again immediately before a durable intent, so a
modified parent capture or receipt cannot silently acquire authority after
review. Ordinary order plans cannot acquire recovery metadata by resealing a
stored plan.

The child receipt records exactly four recovery fields: profile, scope, strict
origin and origin hash. The origin binds the original receipt/intent, original
backup/snapshot, selected immutable proof and comparison. Browser admission
checks those fields, exact request, nested native compilation and retained
source in addition to the existing target/route/interface checks. Hashes establish
internal consistency; they do not authenticate a vendor or prove physical runtime
behavior.

Dispatch uses the existing one-use transaction, password capability check,
capacity preflight, identity verification, fresh merge, native backup/restore and
full readback. Dispatch failure remains not-sent; a sent but unconfirmed restore
stays uncertain. Restarted readback validates the child's own retained compilation
and typed lineage without requiring that the original parent's files still exist.
Recovery parents cannot be recursively used to prepare another inverse.

## Review lifetime and recorded history

Source, proposal, target, route, interface, operation, destination, task, surface
and page lifetime changes retire the selected review. Returning to the local
draft or selecting/loading another receipt retires it synchronously, before a
same-turn old Apply callback can dispatch. A pending receipt load also blocks a
late proposal-admission callback. An already dispatched transfer keeps its exact
late receipt and uncertainty state while workspace mutation remains locked.
Review, Apply, readback and snapshot actions have separate element identities;
a retired Apply element cannot become an unintended new Review action.

**Changes** and **History** project the recorded order-recovery lineage from the
child's own validated receipt. They show original receipt/proof, before/after
members, native widths and reviewed source. **Find original execution-order
receipt** filters existing local history; **Save recorded execution-order
lineage** exports the reconstructed recorded projection. This projection neither
reopens a parent file nor revalidates current controller state, and grants no
field authority. Invalid metadata produces an unavailable label instead of
breaking the history list or being mislabelled as a generic recovery family.

## Qualification and limits

All mutation tests use authored localhost peers, including BACnet/IP and an
authored IP-to-MS/TP route. Software tests cover raw/gzip sources, supported
diagram classes/widths, independent full native before-image reconstruction,
fresh other saved values, strict original proofs and API confirmations, stale or
tampered plans, uncertainty/restart/readback and immutable original records.
Browser checks cover CAF/graph and desktop/compact entry paths, exact receipt
exports, recorded history, stale callbacks, receipt replacement, unavailable
profiles and interrupted transfers.

The immutable **Native order qualification** cohort declares 417 backend cases
per source/installed build, 480 browser/contract cases and six connection-prefill
regressions per source/installed × Chromium/WebKit matrix: 2,778 executions.
The original 326 backend, 425 browser and six prefill identifiers remain present.
Collection and execution identifiers must match; retries, skips, flaky results,
missing cases and failures fail qualification. Installed checks compare exact
tracked Python, built UI/provenance, public metadata, reference data and bundled
legal files before importing the wheel package and serving its assets. Original
failure logs and traces are retained. See `scripts/qualify_native_order.py` for
the reproducible command and `native-order-recovery-proposal.md` for tool setup.

The browser interaction deadline remains 30 seconds. Happy-path and uncertain
transfer cases prepare their actual completed original transfer in a separate
test-owned fixture with its own 30-second setup/cleanup deadline. Both original
and new restores retain the application's ordinary six-second preparation delay
and normal acknowledgment/readback budgets. Each phase fails independently;
no failed sample is retried. The larger 417/480-case cohort has a 45-minute job
allocation, increased from the preceding 326/425 cohort's 35 minutes. This changes
total CI capacity, not any original case or assertion deadline. The original
combined-phase timeout and its complete passing assertion trace remain retained.

Connection-prefill evidence records the value at post-passive commit, immediately
before native focus, during focus/focusin and afterward. A prefill can already
have committed before focus; that displayed value is then the value to preserve.
The same test still requires an unchanged focused value/selection, exact text
replacement and exact interface request/connection. Final aggregate review must
retain at least one actually pending-at-focus sample of each producer (network
recommendation and saved status) in source and installed modes across their two
engines. Both timing outcomes are recorded; no sample is skipped or retried.

The existing Changes regression helper closes its own setup/cleanup HTTP
connections. A retained source Chromium trace passed all station-change and
stale-evidence assertions, then reset the cleanup request at the server's
five-second idle keepalive boundary. Closing the test client's connections avoids
that reuse boundary without retrying a request or changing application HTTP
settings, case identifiers, assertions or deadlines. The failed original remains
retained and the complete immutable cohort must pass again.

These checks establish this bounded software transfer path. Physical controller,
BTCVT, vendor CCT comparison, general logic/object allocation, hardware remapping,
changed-current-source recovery and unrestricted cross-brand compilation still
need their own implementation or evidence.
