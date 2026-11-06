# Saved unfinished CAF scalar drafts

The existing **Changes → Local CAF changes** view can retain an explicitly saved
checkpoint of scalar proposals for the original opened CAF. This is local recovery
of a saved draft, not automatic recovery of every keystroke. Reopen the same
original CAF bytes after a restart, inspect the saved checkpoint, then explicitly
restore it. Renaming the file does not change its identity; different CAF bytes
have a different checkpoint.

Saved proposals preserve the exact object reference, property identifier, original
scalar text and unfinished replacement text. Incomplete numbers such as `-` or
`1e`, invalid Enum text and whitespace remain recoverable. Saving a draft does not
validate the replacement as an exportable value. The existing **Save CAF copy**
operation still performs its original type, source, old-value and artifact checks.

Save and restore check the actual editable property in the reopened original CAF.
Restore derives Enum eligibility from that source again. Stored or uploaded claims
cannot authorize an unsupported property. Restoring retires earlier scalar export
results and treats the restored proposals as local work awaiting export. It does
not restore a controller connection, confirmations, compilation result or field
write review.

A restore that differs from current nonempty scalar proposals requires an explicit
choice to replace them. Leaving the replacement unconfirmed preserves current
work. Graph, hardware, instance and other edit families keep their own drafts and
are not included in this scalar checkpoint. Exporting a CAF copy does not silently
remove the checkpoint. Discarding local proposals and removing the saved checkpoint
are separate actions.

On narrow screens, the current-proposal table scrolls horizontally. Focus the
labelled table region and use Left/Right to scroll or Home/End to reach either
edge. These keys do not intercept typing in nested controls.

One checkpoint is stored per original CAF hash. Updates and removal require the
expected checkpoint generation and revision. Concurrent edits receive a conflict
instead of silently overwriting saved work. Deleting and recreating a checkpoint
creates a new generation, so an older browser cannot reuse a stale revision.
Capacity checks and replacement occur in one storage transaction; errors retain
the preceding checkpoint and existing checkpoints are not evicted.

Limits are 32 CAF checkpoints, 1,000 unique property proposals per checkpoint,
8,192 characters per original or replacement value, 1 MiB per stored checkpoint
and 8 MiB of combined checkpoint content. A damaged record is unavailable for
restore. An intact recorded generation and revision permit explicit removal of
that checkpoint without trusting its proposal payload.

The API is `/api/caf/{caf_sha256}/scalar-draft`. GET returns the saved checkpoint
and capacity without reopening the file. POST saves exact proposal strings using
`expected: null` for creation or `expected: {id, revision}` for an update.
`POST /restore` requires the current generation/revision and reopened original
CAF; its response supplies freshly derived property evidence. DELETE uses the
same generation/revision guard. Mutations require the existing Studio token.

This JCI/UX slice covers unfinished scalar drafts only. General native authoring,
hardware/graph draft recovery, semantic package matching, native compilation and
physical controller acceptance remain separate work.
