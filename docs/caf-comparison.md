# Offline native CAF change review

**CAF compare** opens two existing CAF archives and reviews their observed
native records. Both uploaded originals remain unchanged. This service does not
compile, retarget, simulate, apply or establish firmware compatibility for a
Johnson Controls application.

Object references and native record kind/ID are exact identities. Display names
never remap objects across controllers. An object with a different reference is
reported as removed/added even when its display name is unchanged.

The comparison distinguishes ordinary properties from saved simulation values.
Observed connection, execution-order, membership and drawing properties have
separate categories. Model/release-mode metadata differences are visible;
missing target metadata produces an unknown result rather than compatibility
approval. Object attributes, opaque records, root metadata, mixed text and
native ordering remain reviewable.

Namespace prefixes on element/attribute names, attribute ordering, empty-element
syntax and container indentation are normalized. Leaf text remains exact,
including whitespace and numeric spelling. A descriptive numeric-equivalence
flag does not hide a changed native value or prove identical firmware behavior.
Comments, processing instructions and namespace bindings referenced by prefixed
text/attribute tokens have their own hashed XML evidence. A binding change such
as an unchanged `type="t:Analog"` resolving to a different namespace is therefore
visible even when the expanded element tree is unchanged. Unprefixed `xsi:type`
values also retain their default-namespace binding. Unused namespace
declarations are normalized.

Rows contain clipped before/after previews and full normalized record hashes,
including significant trailing mixed text.
Scalar/leaf previews are at most 2048 characters; attribute and XML-annotation
previews have explicit bounds and truncation markers. Repeated identity previews
are clipped to 256 characters with full identity hashes/lengths when truncated;
internal matching still uses the complete original identities. Full values remain in the
original CAFs. Hashes are evidence of compared content, not a controller
signature. They do not cover ignored ZIP packaging differences; separate source
archive SHA-256 values identify the exact input bytes.

The local endpoint is `POST /api/caf/compare`, with cached upload hashes
`before_sha` and `after_sha`. It accepts a category, a metadata search of up to
200 characters, offset and page size 1..500. The browser displays 100 rows per
page. Search covers displayed object/record identity metadata and truncation hashes,
not all scalar payloads or clipped identity suffixes.
JSON export retrieves every filtered page, checks source hashes/counts and
refuses more than 5000 changed records until filters narrow the review.

CAF parsing rejects unsupported archives, unsafe entities/DTDs, duplicate native
identities, more than 500,000 XML elements or depth 64, and XML names or
namespace declarations over 4096 characters (including unused declarations). Scalar patches target
the parser's actual element positions, reparse/read back the precise edited
native value and retain unrelated source bytes. Comments/CDATA that resemble
serialized objects cannot redirect an edit. Native drawing coordinates must be
finite decimal float values before graph inspection or edits.

Browser editing retains drafts when changing workspace tabs. Archive replacement
and structural edits require explicit draft handling, delayed property responses
cannot attach values to a different object, and stale downloads are discarded
when their source archive changes. Scalar and wiring exports remain separate
candidate copies. These workflow checks do not replace matching licensed
CCT/PCT compilation, package validation or a hardware download test.

Tests use authored adversarial XML and all seven authorized private CAFs.
Original building files and their content are not distributed with the source.
