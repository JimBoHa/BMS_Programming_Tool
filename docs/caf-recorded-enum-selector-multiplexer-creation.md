# Recorded Float Multiplexer with an Enum selector

Program → CAF file → Logic supports a separately qualified Float Multiplexer
profile with an Enum selector. Use the existing **Multiplexer** task,
choose its actual source prototype, inspect the six recorded ports, enter
coordinates, review the copy and save it. The original archive stays unchanged.

The existing route selects a strict profile from the source's actual StandardName
property. A separate local copy starts from the opened archive; other pending file
edits are not included. Saving does not send a controller write or prove that the
file matches a connected application. Recorded values are not live values.

## Recorded profile

The `caf-recorded-float-enum-selector-multiplexer-copy/1` profile admits class/type
562, version 1.0, StandardName set 432 code 15. The reference catalog names it MUX
(Float IO, Enum Mode). Names and state metadata do not establish executable mode
bindings, source-release compatibility or logical Enum membership.

The parent has properties 75, 32527, 2381, 3122, 3184 and 3670. Setup remains
absent and inspection reports null. Property 2381 retains six unsigned-short
spellings `0`, `2`, `0`, `0`, `3`, `4`; property 3122 retains unsigned-short `1`.
The copy preserves this framing and content without interpreting positions,
lengths or numbers as native assignments or fallback behavior.

| Child order | Class / type | Port | Recorded configuration |
| --- | --- | --- | --- |
| 1 | 527 / 2 | 85 | Float output; default omitted |
| 2 | 526 / 2 | 7002 | Float input; StandardName set 433 code 0; default omitted |
| 3 | 526 / 2 | 7003 | Float input; StandardName set 433 code 0; default omitted |
| 4 | 526 / 2 | 7000 | Float input; default omitted |
| 5 | 526 / 2 | 7001 | Stored finite Float default, copied with its original spelling |
| 6 | 528 / 19 | 961 | Enum input; StandardName set 433 code 0; default omitted; Number Of States 6; States Text encoding set 802 code 900 |

All six ports are exposed. Parent exposure order stays 961, 7000, 7001, 85, 7002,
7003. The private examples include both `100` and `100.000000` Float defaults;
the profile also accepts other finite Float spellings in this existing slot.
Missing values remain missing. Unknown properties, defaults in other slots,
types, versions, namespaces, orders, metadata and bookkeeping are refused.

## Review and preservation

Seven identities must fit the unchanged local ceiling of 4,194,302. The lexical
clone path updates only copied identities, adds one graph member and layout entry,
and inserts one execution-order entry after the prototype. Original objects,
wires, continuations, unrelated XML bytes, defaults, metadata and ZIP attributes
remain exact. Independent readback verifies the result. Local identity allocation
does not establish vendor reserved identities, resources or firmware acceptance.

The existing authenticated `float-multiplexer-copy/source`, `/preview` and `/export`
route family dispatches between the separate Boolean- and Enum-selector engines.
The original Boolean-selector engine remains strict and unchanged. The facade
returns identical old selections, reports, seals and artifacts. Other unsupported
Multiplexer variants are refused; an Enum-profile failure does not trigger a
Boolean-profile fallback. There is no Apply action.

Client checks bind the source, prototype, six typed children, their metadata,
bookkeeping, coordinates, actual output and six artifact hashes to the review and
download. The contextual task shows the correct four/six-port and five/seven-object
counts, the Enum metadata and additional-input codes. Drafts for both source
prototypes coexist in the unchanged bounded cache. Changing prototype, task,
source, target context or page lifecycle retires reviews and late responses.
Existing graphics, controller routes, reference provenance and ordinary Save stay.

## Validation and remaining work

Independent complete-XML checks cover actual and other finite Float spellings,
all six ports, stored/omitted values, input names, Enum metadata, raw bookkeeping,
seven-identity limits, repeated creation, ZIP metadata and guarded Float
connections. Direct engines and the facade have separate admission and output
checks. Strict API/client and browser cases cover exact proofs and exports,
rejected resealed invalid structures, Unicode references, mixed prototypes and
drafts, stale responses, lifecycle retirement, compact controls and both entry
paths. Authored loopback peers verify that local review/export adds no field
traffic. Private examples are qualified in memory without changing originals or
saving derived private CAFs.

Native selector assignments, Enum membership, runtime/reliability/priority,
restart/scan behavior, vendor packages/resources, general File-3 compilation,
CCT/PCT reopening and physical/BTCVT acceptance require separate qualification.
Mode editing and simulation retain the [previous manual-derived
criteria](caf-recorded-float-multiplexer-creation.md), including preserved
assignments during Enum-set changes and explicit unmapped-state fallback review.
JCI-02, JCI-03, JCI-05, JCI-06 and JCI-09 remain partial.
