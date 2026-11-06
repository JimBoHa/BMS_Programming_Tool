# Saved unfinished CAF wiring selections

In **Program → Logic → Connection table and guarded CAF export**, open
**Saved wiring draft**. This saves an explicit checkpoint for the original CAF
and diagram, including the selected original wire occurrence, replacement source
and unfinished new-connection source/destination choices. Empty selectors remain
empty. Saving does not require the proposed operation to pass native compatibility
or export checks.

1. **Save unfinished wiring draft** stores current choices. It creates no CAF
   download and marks no proposal exported.
2. Reopen the same original CAF, open the same diagram and choose **Restore saved
   wiring draft**. Original bytes, tuple/count, block membership and source
   evidence are checked again. If current choices differ, explicitly replace them
   or keep the current draft.
3. Continue editing, then use the existing graph-only or combined CAF export.
   The normal compatibility, execution-order, occupancy and cycle checks still
   apply. A checkpoint never restores a successful export or review.

**Remove saved wiring draft** removes only the checkpoint. Current selections and
other edit families stay available. **Download wiring checkpoint** saves a JSON
reference record; it is not a compiled program, controller backup or import service.

An incomplete new-connection selection counts as unfinished work and participates
in the existing source-replacement/discard protection. Scalar checkpoints, removal
and block-creation drafts remain separate. Conflicting graph work must be resolved
through the existing workflow before restoring wiring choices.

## Persistence and source checks

There is one checkpoint per original CAF/diagram, with at most 32 contexts, 1 MiB
per record and 8 MiB total. New work never evicts old records. Generation identifiers
and optimistic revisions prevent stale saves, removals and delete/recreate ABA.
Corrupt or oversized content is not loaded as a usable checkpoint; a valid stored
generation can be explicitly removed without changing current work.

Status and removal require no original CAF cache or controller connection. Restoring
requires the original CAF to be opened and independently rechecks the actual graph.
Stored source evidence includes the diagram bytes, native block identities and
selected continuation. Historical status is not fresh source validation. Changes
to archive bytes, including unrelated or ZIP metadata changes, create a different
source hash and do not inherit a checkpoint.

Late replies are withheld after source, intent, task, route/interface or page
lifecycle changes. Restoring retires earlier copy reviews and clears exported
markers for the restored proposals. Existing unrelated draft stores remain intact.

## Local API

Use `/api/caf/{source_sha256}/wiring-draft`:

| Method | Request | Result |
| --- | --- | --- |
| GET | `diagram_ref` query | Sealed checkpoint metadata or explicit unavailable status |
| POST | Exact `selection` and nullable expected generation/revision | Save a source-checked checkpoint |
| POST `/restore` | Diagram and expected generation/revision | Revalidate the opened original and return exact selections |
| DELETE | Diagram and expected generation/revision | Remove only that saved generation |

The existing local session/origin protections apply. These operations inspect local
source and update local SQLite state. They perform no graph encoding, compilation,
controller queries or writes and grant no field authority.
