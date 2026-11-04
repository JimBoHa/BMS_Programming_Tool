# Recorded Enum Multiplexer with a Boolean selector

Program → CAF file → Logic now supports a separately qualified Enum-valued
Multiplexer profile. The existing task is labelled **Multiplexer** and identifies
the inspected Float or Enum I/O and selector type. Choose an actual source
prototype, inspect its recorded ports, enter coordinates, review and save a copy.
**Open CAF copy** continues from the verified artifact and its actual new block.

The original Float/Boolean-selector and Float/Enum-selector engines remain
unchanged. Source configuration selects the separate engine; a failure does not
fall back to another profile. For compatibility the existing technical
`float-multiplexer-copy` route remains. Enum-valued artifacts use an
`enum-multiplexer-copy.caf` filename; original Float filenames remain unchanged.
No controller request, Apply operation or native runtime authority is added.

## Recorded configuration

The `caf-recorded-enum-multiplexer-copy/1` profile admits class/type 562, version
1.0, StandardName set 432 code 16. The parent retains properties 75, 32527, 2381,
3122, 3184 and 3670; setup remains absent. The four ports stay in this child order:

| Child | Class / native type | Port | Recorded data |
| --- | --- | --- | --- |
| Output | 529 / 19 | 85 | Enum state metadata; default omitted |
| Selector | 530 / 5 | 961 | Boolean input; default omitted; optional StandardName set 433 code 0 |
| Input | 528 / 19 | 7000 | Enum state metadata and stored or omitted default |
| Input | 528 / 19 | 7001 | Enum state metadata and stored or omitted default |

All ports are exposed in the recorded order 961, 7000, 7001, 85. Three source
forms have separate structural admission:

| Property 2381 | Property 3122 | Number Of States | States Text |
| --- | --- | --- | --- |
| unsigned shorts `0`, `2` | unsigned short `1` | `4` | set 802 code 366 |
| unsigned shorts `1`, `2` | unsigned short `0` | `2` | set 802 code 418 |
| unsigned shorts `1`, `2` | unsigned short `0` | `2` | property 931 omitted |

Output and both Enum inputs retain the same recorded metadata shape. Defaults
retain canonical unsigned numeric spelling and their original set 647 or recorded
States Text namespace. Missing defaults and missing States Text remain missing.
Unsigned storage capacity does not establish Enum membership or a code/count
relationship. Raw bookkeeping is preserved without interpreting it as executable
assignment, fallback or retention behavior. Unknown structures are refused.

## Preservation and workflow

Five identities must fit the unchanged local allocation ceiling of 4,194,302.
The existing lexical clone path adds one graph member and layout entry and one
execution-order entry after the prototype. It independently reparses the copy,
checks the new Enum output and all children, and preserves original objects,
connections, continuations, unrelated XML and ZIP metadata.

Client checks separately bind the typed output namespace, four children, optional
metadata, raw bookkeeping, defaults, identities, source, coordinates, review and
artifact hashes. Float and Enum prototypes retain distinct unfinished drafts.
Source, prototype, kind, task, target and lifecycle changes retire old reviews
and late results. Saving and opening remain local. Other pending edits follow
the explicit confirmation described in [CAF copy continuation](caf-open-reviewed-copy.md).
The selected controller and its exact route remain separate from the local file;
their application match remains unverified.

Authored tests cover complete independent XML, all six observed combinations of
namespaces/default omissions, ZIP attributes, repeated creation, five-ID bounds,
unsigned storage capacity, malformed shapes, strict API/client proof admission,
mixed prototypes/drafts, late results, compact controls and both entry paths.
Private source compatibility is checked in memory; original programs and derived
private CAFs are not distributed.

Native Enum/mode meanings, assignment editing, runtime/reliability/priority,
restart/scan behavior, resources/packages, general File-3 compilation, CCT/PCT
reopening and physical/BTCVT acceptance require separate qualification.
JCI-02/JCI-03/JCI-05/JCI-06/JCI-09 remain partial.
