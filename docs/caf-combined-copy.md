# Scalar and wiring changes in one CAF copy

In **Program → CAF file → Objects & parameters**, edit the supported stored
scalar fields. In **Logic → Connection table and guarded CAF export**, select
an existing replacement source or a new connection between existing blocks.
Open **Scalar + wiring CAF copy** to review all current scalar proposals with
one selected wiring operation. If both wiring proposals exist, choose which
one to include. The other proposal remains available separately.

1. **Review scalar + wiring copy** checks both families against the same original
   CAF and shows original text, raw proposed text and exported text.
2. **Save combined CAF copy** downloads the complete verified result. It marks
   only the included scalar and wiring proposals exported. It leaves the original
   file and current proposal text visible.
3. **Open CAF copy** explicitly opens those verified bytes. Other unexported work
   requires the existing confirmation; canceling retains the original workspace.

The ordinary **Save CAF copy** action remains scalar-only. Existing rewire-only
and addition-only exports retain their behavior. Removal, block creation, hardware,
instance and simulation changes are not included in this combined operation.
Explicit saved scalar checkpoints remain independent.

## Supported composition

The local adapter accepts one existing-source rewire or one connection addition
from a same-archive observed prototype, together with 1–1000 guarded scalar rows.
The entire raw request is limited to 1 MiB. Existing scalar and graph eligibility,
native type/configuration, observed-pin, destination occupancy, execution-order
and cycle restrictions still apply to the original source. A scalar edit cannot
rescue an originally incompatible graph operation.

The adapter runs both operation orders and independently checks the final XML
against the union of allowed parser-bound scalar and wiring byte changes. It
also checks final graph semantics, object identities and archive metadata.
It publishes no intermediate or partial CAF when any check fails. Unsupported
or ambiguous XML serialization is refused rather than rewritten.

Requested text and actual changes are distinct. For example, Float `12.5000`
can export as `12.5`, and an eligible Enum code `0002` as `2`. Raw proposals are
not normalized in the editor. Counts derive from actual leaf-byte changes rather
than the length of legacy encoder reports. A fully unchanged result returns the
exact original archive bytes and explicitly reports no changes.

Source, review and artifact proofs bind the original archive, ordered raw scalar
rows, exact selected wiring request and output. Edits, source replacement,
navigation, target/interface changes and page lifecycle events retire old reviews
and pending callbacks. Both included families receive saved markers together only
after artifact verification. Explicit copy opening rehashes the bytes and checks
the identity returned by the normal CAF loader before activating the new source.

## Local service

The separate `/api/caf/{id}/combined-copy/source`, `/preview` and `/export` POST
operations use strict discriminated wiring requests. Source evidence rederives
editable fields and Enum metadata from the original CAF. Preview binds the source
selection seal; export recomputes the entire review and requires its seal. Export
returns source, request, selection, review, combined-result and output hash headers.
The two operation orders retain their literal intermediate hash chains.

This is local source editing. It does not establish native execution, unwired
fallback behavior, controller resource/package compatibility, CCT/PCT acceptance
or controller transfer authority. No controller queries or writes are performed
by these operations.
