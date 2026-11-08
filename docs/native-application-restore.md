# Retained native application restoration

`COMM-NATIVE-APPLICATION-RESTORE-001` provides the separate
`native-retained-application-restore/1` profile. It restores one retained native
application and its supported historical saved application values to the same
recorded controller route and complete identity. It is a software-qualified
application transfer profile, not a general logic compiler or whole-controller
backup.

## Operator workflow

1. Open a controller or a local CAF/graph. In **Program → Native backup defaults**,
   select and inspect a retained native backup. Expand **Restore a retained
   application** and **Inspect retained restore image**. The comparison identifies
   the historical source and current selected controller separately.
2. Local reconstruction uses only the original File3/11/12 snapshot. **Save
   saved-application copy** checks the source, review and actual artifact hashes
   before saving its exact `.moz` or `.moi` bytes. **Save exact retained-image
   review** preserves the original received JSON. Both remain available offline
   and grant no controller authority.
3. Select the original controller and plain BACnet/IPv4 interface. Native backup
   and restore credentials remain explicit advanced settings. **Review retained
   application restore** verifies the exact original route, Device, object name,
   vendor, model, firmware and application-software identity. It captures the
   current application into a separate immutable backup and checks matching
   native ACS/DMCS versions.
4. Review native before/restored record counts, added/removed/changed records and
   configuration guards. Confirm both historical application replacement and
   possible control interruption. **Apply retained application to controller**
   keeps a fresh third pre-write backup and attempts the one newly reviewed
   transfer. A complete application and saved-value readback must verify it.
5. An interrupted or unconfirmed operation retains its original durable receipt.
   Select it under **Recorded application restores**, load it, and explicitly
   **Read back original retained-application restore**. Readback never replays the
   application. A proved original pre-write image is labelled recovered-original,
   separately from a verified retained-image restore.

These actions preserve local CAF/graph drafts and original evidence. Source,
target, route, interface, task, workspace, page lifetime and receipt changes retire
write reviews synchronously. Returning to the old source never resurrects a
review. A dispatched operation retains its exact late receipt and uncertainty
state; navigation remains locked while its field operation is active.

## Reconstruction and current-configuration guards

The existing native parameter compiler merges the original Files11/12 values
into their actual File3 application selectors. It preserves native object order,
identities, graph and opaque records. Existing CRC, datatype, selector ambiguity,
omitted-field qualification and file-size limits remain required. Source/model
inventories never generate objects or substitute an application.

The historical source, reviewed current capture and fresh pre-write backup have
distinct identifiers and original hashes. Both source roles are reconstructed
before review and again before durable intent. Any altered source or reviewed
capture is refused. The fresh pre-write source must match reviewed File3, File11
and every current saved configuration value. Flow autocalibration values remain
configuration for this guard. Only actual standard binary COS/elapsed counters,
or the independently qualified ACS/DMCS60 actuator seconds state, may advance
monotonically. Decreases, wraparound and unqualified similarly named properties
require a new review.

The target payload remains fixed to the historical image. It does **not** merge
new current settings or preserve current application-persistent counter values.
It restores the supported historical application values, including those
counters. Non-application runtime slots remain original evidence and are not
converted into application defaults or claimed as restored runtime state.

The common native writer retains fresh identity, interface and credential
guards, actual controller capacity checks, one-use plans, durable pre-dispatch
payload/intents and one attempted restore. Its ordinary five-second preparation,
four-second request budget and inter-block timing remain unchanged. Exact native
image and effective saved-value verification precede success. Known post-restore
runtime/calculated differences remain separately reported by the existing
preservation policy.

## Recorded evidence and interfaces

The session-protected `/application-restore/source`, `/export`, `/preview` and
`/apply` endpoints share the existing native-application service. Source/export
perform no field queries. Preview and Apply have closed strict request schemas;
both Apply confirmations are required booleans. The browser admits exact source,
compilation, route, interface, review, receipt and preservation bindings; hashes
prove consistency and do not authenticate a vendor or establish runtime behavior.

Changes and History show the three original backup roles and native record
comparison from the child's own typed receipt. Recorded metadata is explicitly
unverified against current files/devices and grants no field authority. Missing
historical files do not erase the recorded reference. Malformed or future metadata
shows unavailable without breaking the history list. It cannot be mistaken for
another edit/recovery family or authorize a replay.

## Reproducible software qualification and remaining scope

`scripts/qualify_native_order.py` declares 512 backend cases per source/installed
build, 538 browser/contract cases and six connection regressions per
source/installed × Chromium/WebKit matrix: 3,200 executions. The preceding
417 backend, 480 browser/contract and six connection case identifiers remain.
The added 95 backend and 58 browser/contract cases cover independent literal
native images, raw/gzip sources, direct/authored routed UDP, large multi-block
images, all three backup roles, current settings/counters, source drift, complete
HTTP/receipt paths, ACK loss, restart and recorded provenance. Browser cases
exercise graph/CAF, desktop/compact, keyboard confirmations, offline exports,
actual changed settings, malformed reviews, same-turn cancellation, late
responses and immutable receipt downloads.

Collection/execution identifiers must match; failures, skips, retries and flaky
results fail qualification. Individual browser deadlines stay 30 seconds and the
aggregate job allocation stays 45 minutes. Real restore preparation is not
shortened in browser peers. Installed runs compare tracked Python, actual built
assets/provenance, public metadata, reference data and legal files before importing
and serving the packaged code. Original failed logs remain retained separately.

No site, Bluetooth, VM, CCT or physical actions are part of this qualification.
New native identity allocation, arbitrary logic generation, cross-controller or
release migration, firmware/resources/packages, whole-controller backup and
physical/runtime/CCT acceptance remain separate. Both broader JCI-09 and JCI-10
roadmap items remain partial.
