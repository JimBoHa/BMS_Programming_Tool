# Recorded Boolean logic creation

Program → CAF file → Logic can copy an actual version 1.0 Boolean logic block
and its three or four recorded port objects into a separate local CAF archive.
The original archive stays unchanged. Select **Boolean Logic**, inspect a block
prototype, enter coordinates, review the copy and save it. Open the saved copy to
inspect or connect its new block through the existing guarded graph workflow.

This task uses the opened file. Other pending file edits are not included. A local
save does not write to a controller or establish that the file matches one.

## Recorded configuration

The separate `caf-recorded-boolean-logic-copy/1` profile admits class/type 559,
version 1.0. Parent properties are 75, 32527, 518, 3184 and 3670. The observed
Setup set 286 and StandardName set 432 pairs are 1/24, 2/25 and 3/26. The
versioned reference catalog labels the standard names AND, OR and XOR. These
reference names do not establish executable semantics or source-release
compatibility. Setup set 286 remains outside the separate reference-label reader's
three-set catalog; raw setup codes are retained and shown.

The small profile has one class-531/type-5 output at port 85 followed by two
class-530/type-5 inputs at ports 7000 and 7001. Exposed order is 7000, 7001, 85.
The larger profile is observed only with Setup 1 / StandardName 24. It adds input
7002, carrying StandardName set 433 code 0, and exposes 7000, 7001, 85, 7002.
Its recorded child order is either 7002, 85, 7000, 7001 or 85, 7002, 7000, 7001.
The required output is identified by its port and type, rather than its child
position.

Every observed Boolean logic port omits a stored default. The copy preserves
that omission; it does not insert false, zero, a simulator value or a live value.
Unknown child shapes, properties, namespaces, orders, identities and setup/arity
combinations are refused. No runtime meaning is inferred from a missing value.

## Copy and review

The existing lexical clone path copies only the recorded subtree and updates its
identities. Four or five identities must fit the unchanged local ceiling of
4,194,302. This is an archive allocation check, not vendor resource validation.
One graph member, one execution-order entry and one layout entry are added.
Original objects, wires, continuations, other metadata, stored spellings, unrelated
XML bytes and ZIP metadata remain exact. Independent readback checks the result.

Separate authenticated `/api/caf/{archive}/boolean-logic-copy/source`, `/preview`
and `/export` routes bind the source, prototype, coordinates, selection, all child
hashes and actual output to the review and exported bytes. There is no Apply route.
The client checks the same typed structure before offering a download. Source,
kind, prototype, controller context and page lifecycle changes retire pending
reviews and late responses. Existing local drafts share the unchanged 32-slot
cache, with no silent eviction.

The contextual task retains Program navigation, exact target routes, reference
provenance, ordinary Save behavior, graphics and the single primary action. Boolean
Logic is distinct from Boolean Constant. Reference annotations never rewrite the
original graph or grant controller compatibility.

## Validation and remaining scope

Independent authored examples cover all three setup/name pairs, all three child
orders, omitted defaults, input metadata, complete XML output, exact allocation
boundaries, repeated copies, existing-wire connection copies and ZIP metadata.
API, client-contract and browser checks cover exact reviews/exports, rejected
resealed invalid proofs, Unicode references, mixed drafts, stale responses,
compact controls and both offline and routed controller entry. Authored loopback
peer evidence verifies that local review/export adds no field requests.

Private local examples are read and qualified in memory. Their source archives,
paths and derived artifacts are excluded from commits. Source and installed-package
checks also preserve previous supported profile results, package assets and
reference attribution.

This qualifies local structural copying. Native Boolean operator execution, scan
order, restart/retention, reliability, priority, live values, general program
compilation, vendor identity/resource limits, native File-3 generation, CCT/PCT
reopening, firmware execution and physical/BTCVT transfer require separate
qualification. JCI-02, JCI-03, JCI-05, JCI-06 and JCI-09 remain partial overall.
