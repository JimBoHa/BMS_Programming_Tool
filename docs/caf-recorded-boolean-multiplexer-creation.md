# Recorded Boolean-output Multiplexer creation

Program → CAF file → Logic supports recorded Boolean-output Multiplexers with
Boolean or Enum selectors. The current **Multiplexer** task identifies actual
input, output and selector types. Inspect a compatible source prototype, enter
coordinates, review, save and optionally **Open CAF copy** to continue from its
new block. The file remains local and its controller association unverified.

Two strict profiles admit class/type 562, version 1.0: StandardName set 432 code
18 uses `caf-recorded-boolean-multiplexer-copy/1`; code 19 uses
`caf-recorded-boolean-enum-selector-multiplexer-copy/1`. Actual source configuration
selects a separate engine with no fallback after rejection. Earlier Float and
Enum-output engines and artifacts remain compatible. The original technical
route stays unchanged; these profiles receive a Boolean artifact filename.

## Recorded ports and selector configuration

The parent retains properties 75, 32527, 2381, 3122, 3184 and 3670. Setup remains
absent. Child order is output, selector, first data input, second data input.
Exposure order stays 961, 7000, 7001, 85.

| Child | Class / native type | Port | Stored default |
| --- | --- | --- | --- |
| Output | 531 / 5 | 85 | absent |
| Boolean selector | 530 / 5 | 961 | absent |
| Enum selector | 528 / 19 | 961 | absent |
| First data input | 530 / 5 | 7000 | absent |
| Second data input | 530 / 5 | 7001 | absent for code 18; required Boolean scalar for code 19 |

Each source has exactly one selector. Both selector profiles retain StandardName
set 433 code 0. Boolean ports have no Enum state metadata or encoding namespace.
Boolean default spellings `1`, `true`, `0` and `false` remain exact; copying never
normalizes them or adds an omitted value. Numeric aliases, case changes, Float
encodings, unexpected defaults and missing required values are refused.

| Selector profile | Raw property 2381 shorts | Raw property 3122 | Number Of States | States Text |
| --- | --- | --- | --- | --- |
| Boolean | 1, 2 | 0 | absent | absent |
| Enum | 1, 2 | 0 | 2 | set 802 code 350 |
| Enum | 1, 0, 0, 0, 0 | 2 | 5 | set 802 code 1347 |
| Enum | 0, 0, 0, 2, 0 | 1 | 5 | set 802 code 359 |

These are recorded structural combinations. Native assignments, fallback,
retention and Enum membership are not inferred from them. Unknown combinations,
versions, namespaces, child schemas or scalar framing are refused.

## Copies and workflow

Five new identities must fit the existing 4,194,302 ceiling. The shared lexical
clone path adds one graph member, one layout entry and one execution-order entry
after the source prototype, then independently reparses the result. It preserves
original objects, connections, continuations, unrelated XML and ZIP metadata.
Output and data ports retain native type 5; only an Enum selector uses type 19.

Independent client checks bind every typed child, stored default, selector
metadata, bookkeeping, omission, identity and exact review/export byte proof.
The contextual task retains separate drafts for all six Multiplexer profiles,
source/target/lifecycle retirement, compact controls, one primary action and the
[proven Open CAF copy handoff](caf-open-reviewed-copy.md). Ordinary Save, exact
controller routes and current graphics remain. No controller request or Apply
route is added.

Authored checks cover complete independent XML, Boolean storage forms, repeated
copying, allocation bounds, ZIP attributes, malformed sources, strict API/client
admission, mixed drafts, stale results, lifecycle changes and both entry paths.
Private compatibility checks run in memory and leave original files unchanged;
derived private CAFs are not saved.

This qualifies local structural copying. Native mode assignments, fallback,
Enum meaning, runtime/reliability/restart/scan behavior, vendor resources/packages,
CCT/PCT reopening, general File-3 generation and physical/BTCVT acceptance remain
separate. JCI-02/JCI-03/JCI-05/JCI-06/JCI-09 remain partial.
