# Saved unfinished recorded-copy drafts

In **Program → CAF file → Logic → Copy a recorded block/constant**, open
**Saved copy draft**. An explicit checkpoint retains the original recorded
prototype and its literal X/Y text across reopening and application restarts.
Incomplete or invalid coordinate text can be saved without compiling a copy.

1. Inspect the original prototype and enter coordinates. **Save unfinished copy
   draft** stores that text independently of a CAF export or successful review.
2. Reopen the same original CAF and prototype. **Restore saved copy draft**
   rechecks the existing source inspector. If a current draft differs, compare
   the literal current/saved coordinates and explicitly replace or retain it.
   Replacement rechecks the checkpoint revision before changing current text.
3. Continue editing and use the existing review/save/open-copy workflow. Restoring
   clears previous review, exported markers and saved-copy opening authority,
   including when coordinates are unchanged. No controller action is restored.

**Remove saved copy draft** removes only its checkpoint and retains current
coordinates. **Download copy checkpoint** returns the exact stored JSON bytes
and their independent digest. That record is a local reference, not a compiled
program, import service, native backup or controller restore plan.

## Original source and existing profiles

Checkpoints reuse the installed source inspectors for Float/Boolean/Enumeration
constants, Float/Enum comparisons, Math, Timer, Boolean Logic, Reliability Check
and the separately admitted Multiplexer variants. They add no new block schema,
port exposure, Enum interpretation, identity allocation or encoder behavior.

Each context binds the complete original CAF hash, diagram, family and prototype.
Save/restore also bind the inspector profile and original selection, diagram and
prototype digests. Source inspection does not run a compiler or encoder. Invalid
raw text remains a draft; the normal coordinate, identity, graph, archive and
copy checks still apply when reviewing an export. A changed CAF, including ZIP
metadata, has a separate context. Changes to an installed inspector can leave an
older checkpoint available as historical JSON while refusing restoration.

There are at most 32 contexts, with 1 MiB per stored record and 8 MiB total.
Coordinate strings are bounded to 8,192 characters; these storage bounds do not
make a string acceptable to the existing coordinate compiler. Capacity exhaustion
requires explicit removal and never evicts old work. Scalar and wiring checkpoint
stores and the existing in-memory copy drafts remain separate.

Storage serializes generation/revision checks and mutations. Concurrent saves,
stale revisions and delete/recreate ABA cannot overwrite a later generation.
Malformed or oversized stored content cannot supply restoration or download
authority; an intact stored generation can still be explicitly removed. Status,
exact-report download and removal require no original CAF cache or field
connection. Restoration requires the original CAF and current source inspection.

Pending replies are withheld after source, task, route/interface, prototype, type,
text or lifecycle retirement. Synchronous draft counters also reject coalesced
text/prototype/type ABA. A saved checkpoint does not silently replace differing
current work or revive a prior copy review. Existing original-source CAF Save,
scalar checkpoints, wiring work and copy handoffs retain their separate scope.

## Local API

Use `/api/caf/{source_sha256}/creation-draft`:

| Method | Input and result |
| --- | --- |
| GET | `kind`, `diagram_ref`, `prototype_ref`; stored metadata or explicit unavailable status |
| POST | Exact original-source `selection`, literal `x`/`y` and nullable expected generation/revision |
| POST `/restore` | Exact context and expected generation/revision; revalidated original-source draft |
| POST `/report` | Exact context and expected generation/revision; original JSON bytes with `X-Studio-Artifact-Sha256` |
| DELETE | Exact context and expected generation/revision; remove only that checkpoint |

Mutations and POST operations retain the existing local session/origin checks.
They inspect original local files and update local SQLite records, with no
controller queries, writes, compilation or automatic retries.

`UI-CAF-CREATION-DRAFTS-001` advances JCI-02 and UX-04. Native execution,
package/resource qualification, general compilation, physical acceptance and
broader recovery families remain separate; those roadmap groups remain partial.
