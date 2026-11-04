# Recorded Reliability Check creation

Program → CAF file → Logic can copy an actual version 1.0 Reliability Check and
its two recorded port objects into a separate local CAF archive. Select
**Reliability Check**, inspect a prototype, enter coordinates, review the copy and
save it. Open the saved copy to inspect or connect the new block through the
existing guarded graph workflow. The original archive stays unchanged.

This task starts from the opened file. Other pending file edits are not included.
Saving locally does not write to a controller or establish that the file matches
one. Recorded defaults are distinct from live values and simulated values.

## Supported recorded configuration

The separate `caf-recorded-reliability-copy/1` profile admits class/type 539,
version 1.0. Parent properties are 75, 32527, 3184 and 3670. There is no parent
Setup property: inspection reports null and never inserts a setup code. The
observed StandardName set 432 codes are 21 and 22. The versioned reference catalog
names them Reliability Check (Float) and Reliability Check (Enum); those names do
not establish source-release compatibility or executable reliability behavior.

Both variants have a class-531/type-5 output at port 85 first in child order,
followed by input port 513. Parent exposure order is 513, 85. Both ports are
exposed; input and output directions remain explicit.

| StandardName | Input | Output default | Input default and metadata |
| --- | --- | --- | --- |
| 21 | Class 526 / type 2 | Exact recorded Boolean spelling `true` or `1` | Default omitted; no added units or metadata |
| 22 | Class 528 / type 19 | Omitted | Default omitted; Number Of States 2, States Text code 349 in encoding set 802 |

The Float-input profile is qualified for the two observed output spellings.
Unknown defaults, extra properties, namespaces, child types, orders or variant
combinations are refused. A missing default is preserved as missing; no false,
zero, logical Enum member or runtime state is inferred. The output's stored value
does not prove how a controller executes the check.

## Copy and review

Three identities must fit the unchanged local ceiling of 4,194,302. The existing
lexical clone path updates only the copied subtree's identities, appends one graph
member and layout entry, and inserts one execution-order entry after the
prototype. It preserves original objects, wires, continuations, unrelated XML
bytes, recorded spellings and ZIP metadata. Independent readback checks the new
subtree, graph and original records. Local allocation does not prove vendor
reserved identities, resource limits or runtime acceptance.

Authenticated `/api/caf/{archive}/reliability-copy/source`, `/preview` and `/export`
routes bind the source archive, prototype, coordinates, all child hashes and the
actual output to the review and downloaded bytes. There is no Apply route. The
client independently validates the typed source and review before saving.

The contextual task retains reference provenance, exact controller routes,
ordinary Save behavior and existing graphics. Drafts for both Reliability Check
variants and other block kinds share the unchanged 32-slot cache without silent
eviction. Source, prototype, kind, target context and page lifecycle changes
retire reviews and late responses while retaining local coordinates. One primary
action remains visible for the current task.

## Validation and remaining scope

Independent authored fixtures cover both variants, both Boolean spellings, omitted
defaults, exact Enum metadata, complete XML output, three-identity allocation
boundaries, repeated creation, ZIP metadata and the existing connection-copy
workflow. Typed API and client checks reject unsupported shapes and resealed
invalid proofs, while accepting supported Unicode references. Browser checks
cover exact review/export downloads, prototype and task changes, draft retention,
late responses, lifecycle retirement, source-proof failures, compact controls and
both entry paths. Authored loopback peers distinguish local copying from field
requests. Private examples are qualified in memory without saving derived CAFs or
publishing original controller files.

This qualifies local structural copying. Native reliability propagation, Enum
meaning, Boolean execution, restart/retention, scan behavior, priorities, live
values, general program compilation, vendor package/resources, native File-3
creation, CCT/PCT reopening, firmware execution and physical/BTCVT transfer require
separate qualification. JCI-02, JCI-03, JCI-05, JCI-06 and JCI-09 remain partial.
