# CAF Enum default code copies

In an open CAF, choose **Program → CAF file → Objects & parameters**. A connected
workspace labels the tool **Local CAF file**. Inspect an actual Input Enum or
Output Enum object. Recognized Default Value (3113) fields accept decimal code
proposals through the same property editor as other scalar values. The inspector
shows the retained Enum set reference, when recorded.

Review proposals in **Changes → CAF changes**, then **Save CAF copy**. Enum,
ordinary numeric and string edits share that single copy and the existing
source-specific draft, dirty-state and discard behavior. Invalid unfinished Enum
text stays visible after navigation or an unsuccessful export. The original CAF
and recorded property values remain unchanged.

The scoped metadata/report profile is `caf-enum-default-code-copy/1`. Eligibility
requires the actual class 528/529, ordinary property 3113, a scalar `enum` with
either no attributes or exactly a `set` attribute, a canonical original unsigned
32-bit code, and an observed UTF-8/ASCII leaf serialization that can be spliced.
The owning class is required explicitly; recognizing an `enum` tag alone cannot
make another field editable. Previous ordinary numeric editability is preserved.

Decimal proposals from 0 through 4294967295 use this local software representation
profile. It is not a manufacturer-verified Enum range or allowed-state table.
Leading zeroes and surrounding whitespace normalize to decimal text; Boolean,
floating-point, negative, exponent, hexadecimal and overlong values are refused.
Numerically unchanged proposals return the entire original archive unchanged.
Unknown attributes, other Enum classes/properties, simulation properties, opaque
leaf markup and unqualified encodings retain their original read-only behavior.

Only the actual parsed leaf content changes. Raw set attributes, namespace
prefixes, comments, unknown records and every other XML byte remain intact except
other explicitly proposed scalar edits. Container entry/comment metadata is
retained, and the output is reparsed to verify each change. Enum set membership,
state meanings, executable mappings, simulation behavior, CCT/PCT reopening,
native compilation and controller acceptance remain unverified. No saved-state
merge or field operation is added.

The existing token-admitted `POST /api/caf/{source_hash}/export` adds source,
request and output SHA-256 headers. The browser checks all three and the actual
artifact bytes before requesting a download. The browser's request digest covers
the exact submitted scalar string fields using compact, sorted UTF-8 JSON. It
does not reinterpret arbitrary program metadata or numeric tokens.

The established save-snapshot contract remains: delivery contains the proposal
captured when Save was clicked; edits made during preparation remain dirty.
Opening another file after accepting discard retires an earlier export, even
when the original file hash returns. Source changes and unmounting cannot attach
an old artifact or success result to the new file. Saving remains local and
independent of controller-transfer authority.

Local qualification covers literal prefixed XML, both classes, optional set
references, UInt32 boundaries, source conflicts, no-ops, mixed edits, Unicode,
container metadata, character references, opaque/UTF-16 refusals and actual HTTP
with field methods forbidden. Optional authorized local programs are inspected
and copied without changing their originals; those files are not distributed.
Browser checks cover both local and authored routed entry, phone layout/focus,
invalid drafts, altered property evidence and artifact headers/bytes, snapshot
delivery and file A→B→A ownership. Existing CAF workflow and draft regressions
remain separate checks. No physical site or Bluetooth acceptance is inferred.
