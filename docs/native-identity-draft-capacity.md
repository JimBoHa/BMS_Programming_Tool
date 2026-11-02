# Retained native identity drafts

Within **Overview → Identity settings**, controller-name and native application
instance drafts now refuse another allocation when their 32 retained contexts
are in use. Opening another controller no longer deletes the oldest unfinished
proposal. Existing contexts remain editable at capacity.

The context retains its exact interface, connected/offline state, station,
Device, router/network and edit kind. It holds the selected capture, raw name or
number text and prepared local recovery evidence. Empty views and passive receipt
viewing use no draft slot. An admitted capture or source-loading operation
reserves a slot before starting; cancellation or failure releases an empty
reservation without deleting completed work.

## Save and discard

Expand **Retained identity drafts** to inspect retained sources without changing
the selected controller. **Save local identity draft** downloads JSON containing
the exact raw proposal text, its UI context, the distinct captured target and
capture/receipt/recovery references. Leading whitespace and incomplete numeric
text are preserved. This reference document has no field authority, executable
plan, credentials or confirmations. It does not contain original application
files or complete recovery evidence, and there is no import action for it.

Save original backups, original receipts and exact prepared recovery evidence
through their existing actions when those artifacts are needed. They remain in
the local backend independently of this in-memory list. Exported proposal text
can be read and re-entered after reopening its original source; it is not an
application backup or a transferable write authorization.

**Discard local identity draft** clears only the current context's capture,
proposal and prepared recovery buffer. **Discard selected retained draft** frees
only the chosen context, including an earlier controller when the list is full.
Both actions retire relevant local authority; neither deletes a server backup or
durable transfer receipt. Viewing or saving a retained source does not select it
as the current controller or communicate with a device.

Drafts remain in memory for the current page session. Reloading, restarting or
moving computers requires saving proposal text and the separate original
artifacts first. This slice does not add durable draft storage or JSON restore.

## Field ownership and verification

Navigation, source/target/interface changes and visibility still retire reviews
and confirmations. Retained work never restores them. Verified Apply or original
recovery readback retires only its matching capture/proposal; a newer capture or
ordinary draft remains intact. Matching cleanup is recorded before a verified
identity updates the selected context, preventing a completed proposal from
reappearing under its previous key.

Qualification covers offline CAF entry for both kinds, passive receipts,
navigation, exact JSON text, explicit discard, original file/journal integrity,
the full 32-context UI boundary, refusal of a 33rd context and editing an earlier
context. The boundary UI uses explicitly authored read-only HTTP identity
responses while the backend field interface remains closed. Transfer/recovery
regressions separately use owned direct/routed UDP peers. These checks add no
physical-controller or Bluetooth acceptance claim.

No production backend, protocol, native compiler/writer, receipt format or style
change is required. This completes the scoped capacity/retention idea under
UX-01; general native authoring and durable cross-session draft storage remain
separate.
