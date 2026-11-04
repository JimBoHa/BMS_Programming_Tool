# Recorded Float Multiplexer creation

Program → CAF file → Logic can copy an actual version 1.0 Float Multiplexer and
its four recorded port objects into a separate local CAF archive. Select
**Float Multiplexer**, choose a compatible source prototype, inspect it, enter
coordinates, review the copy and save it. Open the saved copy to inspect or connect
its Float output through the existing guarded graph workflow.

This task starts from the opened archive. Other pending edits are not included.
The original file stays unchanged. A local save does not write to a controller,
prove that the file matches one or supply live values.

## Supported recorded configuration

The separate `caf-recorded-float-multiplexer-copy/1` profile admits class/type 562,
version 1.0, with StandardName set 432 code 14. The versioned reference catalog
labels this MUX (Float IO, Boolean Mode). Other Multiplexer variants, including
other output types and additional-input forms, require separately qualified
profiles. A separate [Enum-selector profile](caf-recorded-enum-selector-multiplexer-creation.md)
now covers StandardName 15 through the same contextual task and route family.
Unknown source shapes return an unsupported profile error rather than silently
changing their configuration.

The parent has properties 75, 32527, 2381, 3122, 3184 and 3670. It has no Setup
property; inspection reports null and never inserts one. Recorded property 2381
is a list containing unsigned-short spellings `0` and `2`; property 3122 is the
unsigned-short spelling `1`. These fields retain their source framing and values.
Their native mode/fallback bindings remain unverified: the tool does not infer
selector assignments from these numbers.

| Child order | Class / type | Port | Direction |
| --- | --- | --- | --- |
| 1 | 527 / 2 | 85 | Float output |
| 2 | 530 / 5 | 961 | Boolean input |
| 3 | 526 / 2 | 7000 | Float input |
| 4 | 526 / 2 | 7001 | Float input |

All four ports are exposed. Parent exposure order stays 961, 7000, 7001, 85. Every
port in the supported profile omits a stored default and additional metadata.
Omission stays omission; no false, zero, live value or simulation value is added.
Unknown properties, types, versions, orders, namespaces, bookkeeping and stored
values are refused.

## Copy and review

Five identities must fit the unchanged local ceiling of 4,194,302. This check does
not establish vendor reserved identities or resource limits. The shared lexical
clone path updates only the copied subtree's identities, adds one graph member
and layout entry, and inserts one execution-order entry after the prototype. It
preserves original objects, wires, continuations, unrelated XML bytes, exact
selector bookkeeping and ZIP metadata. Independent readback checks the result.

Authenticated `/api/caf/{archive}/float-multiplexer-copy/source`, `/preview` and
`/export` routes bind the source, prototype, coordinates, four child hashes and
the actual Float output to the reviewed and downloaded bytes. There is no Apply
route. The client independently checks the typed profile, recorded bookkeeping,
local-only flags and artifact proofs before saving.

The task retains existing graphics, reference provenance, controller routes and
ordinary Save. Drafts share the unchanged 32-slot cache without silent eviction.
Source, kind, prototype, target context and page lifecycle changes retire pending
reviews and late responses while retaining local coordinates. The current task
keeps one primary action.

## Mode editing criteria

The vendor help describes variable input counts, input-to-selector assignments,
an explicit fallback for unmapped selector states, and distinct Boolean and Enum
selector variants. It also describes discarding assignments when the selector's
Enum set changes. Future mode editing should retain the original assignments as
drafts, migrate verified members and review unresolved mappings before saving.
The current copy preserves the recorded configuration and does not enable mode
editing or infer its native bindings. See [Controller Tool Help 10.2,
LIT-12011147](https://docs.johnsoncontrols.com/bas/api/khub/documents/oljzrL52qtPGho8In2ASqA/content),
PDF pages 154, 221–222 and 1463–1465.

## Validation and remaining scope

Independent authored fixtures check complete XML output, all four typed ports,
exact default omission, raw bookkeeping, five-identity boundaries, repeated
creation, ZIP metadata and an existing guarded Float connection. API/client
checks reject unsupported or resealed invalid structures and accept supported
Unicode references. Browser checks cover exact downloads, mixed drafts, late
responses, page lifecycle, source-proof rejection, compact controls and both
entry paths. Authored loopback peers distinguish local copying from field traffic.
Private examples are qualified in memory without publishing or changing originals.

This qualifies structural copying. Native selector/operator semantics, mode
editing, reliability, priority, restart/retention, scan behavior, vendor packages
and resources, general program compilation, native File-3 creation, CCT/PCT
reopening and physical/BTCVT transfer require separate qualification.
JCI-02, JCI-03, JCI-05, JCI-06 and JCI-09 remain partial.
