# Finite truth-table authoring and completeness review

The **Truth tables** workspace creates portable Boolean/Enum tables, reviews
all declared input combinations and evaluates a selected combination. It is
an offline authoring/review feature. It neither reads CAF tables nor compiles,
lowers or uploads executable controller logic.

The reviewed source is JCI *Controller Tool Help*, LIT-12011147, Release 18.0,
revision 2025-10-06. The local publisher PDF has SHA-256
`68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`.
PDF pages 1690–1691 describe Boolean/Enum hierarchy outputs and unresolved
reliability for missing combinations. Pages 167–168 describe wildcard cells,
ordered priority, redundant rows and the documented native hold-last behavior.
The [publisher's configuration instructions](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0/Configuring-a-System/Setting-Preferences-Steps/Logic-View-Steps/Configuring-the-Command-Hierarchy-Block)
provide the corresponding release-specific explanation. PDFs are not bundled.

## Deliberate portable interpretation

The default policy rejects every overlapping match, even when outputs agree.
An operator may explicitly choose **first matching row**. That choice uses the
source row order; every matching/shadowed row identity remains visible and fully
shadowed rows receive diagnostics. Row order and policy are hashed source data.
This explicit option is consistent with the reviewed CCT priority description;
choosing it does not establish native CAF/runtime compatibility.

A wildcard accepts any **declared** state of its input. Unknown values, missing
inputs, Boolean/integer coercion and invalid states never become wildcard hits.
An unlisted combination remains unresolved. A declared constant fallback may
resolve only unlisted combinations and requires an output-domain state plus a
visible rationale. It does not create a source row or hide unlisted counts.
The evaluator never invents a previous output or emulates native reliability.

Input/output domains have stable identifiers and editable labels. Boolean
domains contain exactly false and true. Enum domains explicitly assign unique
signed 32-bit integer values to named states. These are operator declarations,
not inferred JCI enumeration-set codes. Rows declare one exact state or wildcard
per input and one valid output state. Duplicate identifiers, duplicate domain
values, missing/extra conditions and undeclared state references are errors.

## Browser workflow

Start a new table or edit the small example. Add/remove Boolean or Enum inputs,
author Enum values/labels, select an output domain, and add/copy/delete/reorder
rules. Set the overlap policy and optional fallback explicitly. Review then
shows every hole, overlap, fallback and row-usage count. Coverage pages contain
at most 64 cases and can be filtered without hiding overlap evidence.

Select actual declared input values and request evaluation. A locally resolved
case can be evaluated while other cases remain incomplete; the result retains
the whole-table status. Selecting another input clears the previous result.
Changing the source invalidates reviews, evaluation, pages and pending exports.
Late imports/reviews/pages/evaluations cannot replace newer edits or selections;
leaving the workspace suppresses pending downloads.

**Export table** and **Export full review** fetch authoritative server bytes.
The source export is a sealed, importable `bms.truth-table-document` JSON file;
the review export contains the entire bounded case matrix and source/profile.
Import checks exact profile/content/source seals and reports the actual uploaded
file SHA-256. The displayed table hash identifies canonical table content, not
arbitrary original JSON whitespace. Hashes identify content and detect changes;
they are not manufacturer signatures. No automatic profile migration occurs.

Drafts live in the current view. Export a structurally valid table before leaving;
incomplete or ambiguous coverage can still be saved as a source document.
Import a saved document and review again after restarting. The global graph
save controls are disabled in this separate workspace.

## Bounds and evidence

The profile permits 12 inputs, 32 states per domain, 128 rows and 4,096 product
combinations. It never samples a larger product or drops overlapping identities.
Source/upload/JSON bodies are limited to 1 MiB; JSON rejects duplicate keys,
nonfinite values, invalid UTF-8 and excessive nesting. Reports are limited to
4 MiB, with eight immutable session reports and a 32 MiB cache limit. Expired
review IDs require an explicit new review. No disk capture or background task
is started by the feature.

Full review cases use a compact, documented encoding:

```text
[input_state_indices, all_matching_row_indices, chosen_row_index_or_null,
 output_state_index_or_null, disposition]
```

Indices refer to the exact sealed input/domain/row arrays, preserving every
identity without repeating long labels thousands of times. Browser pages expand
these references into labels, IDs and actual values. Full exports retain all
cases. Canonical table SHA-256, fixed source-profile SHA-256 and review content
SHA-256 serve different purposes. Export headers also include the SHA-256 of
actual response bytes, including the serialized content seal and final newline.

`GET /api/truth-tables/profile` is local metadata. Explicit token-protected POST
routes provide `/review`, `/cases`, `/evaluate`, `/import` and
`/export/{table|review}`. Cache operations require exact review, source and
profile identity, and a new review requires the displayed rule-profile hash.
A stale browser cannot silently review against changed rules. Export never
accepts caller-provided replacement evidence.
The service imports no BACnet/serial client and performs no field traffic.

## Validation and remaining work

Independent expected Boolean/Enum matrices test holes, conflicting and identical
outputs, priority reordering, fallback, unknown/nonfinite values, Boolean versus
integer types, malformed sources and maximum-size complete overlap evidence.
HTTP tests verify raw parsing, local tokens, authoritative downloaded byte seals,
exact-profile imports, session/source staleness and closed field interfaces.
Browser tests use real service responses/downloads, including delayed source,
selection, pagination, import and unmount races.

Executable portable graph lowering is deferred. The current graph/runtime does
not yet provide a verified complete Enum-domain/unknown-value/reliability guard
contract for these tables. Native CCT/PCT encoding, proprietary compilation,
controller transfer and firmware acceptance remain separate unresolved paths.
No physical or manufacturer-independent equivalence is claimed.
