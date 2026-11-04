# CAF prototype reference names

`FMT-CAF-REFERENCE-LABELS-001` adds versioned reference names beside actual CAF
prototype references in the existing Program Logic creator. A Math prototype
can show `Multiply`, `Divide` or `MAX`; a comparison can show `Greater Than` or
`Equal (Enum)`. The reference stays first in the option text, and the name carries
an explicit `(reference)` suffix. Captured names, codes and program bytes remain
unchanged.

Expand **Reference names and provenance** for the reference standard name,
setup label and source version. This metadata does not participate in creation
reviews, type checks, saved values, compilation or field plans. Receiving a label
does not retire a valid review or consume a draft slot. Unknown or unavailable
labels leave raw references and all existing CAF tools usable.

## Source and version

The packaged dictionary contains complete reference sets 287 (six Comparison
Setup members), 288 (23 Math Setup members) and 432 (11,152 Standard Component
Names). These are generic format reference data, not controller inventories,
site scan results or sample controller applications.

The source is OCT's
[generated Enum export](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/ui/src/data/fdbEnums.ts),
revision `c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2`. Its
[export script](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/server/src/scripts/exportFdbEnums.ts)
identifies database `FDB_Control_10_8___Firmware_12_0`. The original export SHA256
is `ce867309de563177133975dcf02661696b11a7839a81a554f24c2cfedef8986e`.
The selected JSON SHA256 is
`d155e2fac61c7e0c0455f4e25d749831993b4f72b6ad8d433008f3840f3a4515`.
The packaged data retains provenance, source attribution and the Apache-2.0
license. No SQL database binary, CCT SDK or controller application is bundled.

This reference version does not establish compatibility with the opened
archive's package/release or executable behavior. The response explicitly keeps
`archive_compatibility_verified` and `runtime_meaning_verified` false. Existing
typed admission, semantic limitations and physical acceptance requirements remain.

## Actual source annotation

The read-only `GET /api/caf/{id}/reference-labels?ref=...` operation reads the
selected archive's actual diagram and parent properties. It resolves property
3670 only when it records Enum set 432, and property 518 only for recorded sets
287/288. Absent properties stay absent; unknown codes retain their original
scalar evidence without a label. Unsupported encodings are not coerced.

Each annotation binds source hash, diagram, ordered block identity, raw scalar,
reference lookup, catalog provenance and a consistency seal. The backend verifies
the packaged catalog digest. Client admission binds the source/row identities,
raw code/namespace relationships, reference status, provenance and seal. These
checks grant no native meaning or field authority. The endpoint opens no network
interface and changes no archive or graph payload.

The creator loads one local annotation per active diagram/context. Retired
source, diagram, task or controller contexts cannot replace fresh metadata.
Reference names remain separate from existing review ownership and the unchanged
32-context draft cache. Both controller and offline entry paths retain the same
layout, routes and source distinction. No destination or feature tile is added.

## Enum domains remain separate

This feature annotates parent component/setup fields. It does not interpret
input/output defaults or infer Enum membership. For example, the export names
set 647 `Off/On`, while actual archived Enum defaults carry higher codes alongside
separate States Text metadata. Looking up that encoding field alone would give
an incomplete domain. Existing raw defaults, namespaces and state metadata stay
exact; no substitution, range inference or executable lowering is introduced.

## Qualification

All 123 actual diagrams were annotated without changing their original graph
payloads. All 538 earlier constant/comparison/Math selections, reports, seals and
artifacts match PR231 after annotation. Seven private originals stay unchanged;
no derived private CAF is saved. Source extraction verifies all three complete
generic sets against the pinned public export.

Authored backend/API cases verify actual fields, absent/unknown encodings,
metadata purity, resource corruption refusal and no field access. Browser cases
cover reference/provenance display, unavailable metadata, delayed arrival without
review loss, stale-context failure retirement, mixed drafts, compact controls and
routed-controller entry. The local qualification report records source/installed
case counts, data/module/UI parity, build provenance, privacy and preservation.

This completes reference-label display only. JCI-01/JCI-02 remain partial overall;
native semantics, signed packages, arbitrary compilation and physical acceptance
retain their separate roadmap work.
