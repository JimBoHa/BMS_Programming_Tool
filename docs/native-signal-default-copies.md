# Native signal default file copies

Program → select a captured native block → **Edit default in a file copy**
supports a deliberately narrow local operation. The application exposes this
editor only for actual eligible records in the captured File. It does not select
properties or inventories by controller model.

Profile `tagged-moi-signal-default-copy/1` requires a complete, length-framed
tagged-MOI source with an unambiguous Device root, validated records and unique
engineering references. Existing class 526 (Input Float Block) and 527 (Output
Float Block) property 3113 (Default Value) must contain a finite, ordinary BACnet
Real with exactly four value bytes. Other classes, data types, properties,
reference-scan-only sources and unsupported encodings are unavailable.

These class/property names come from the retained JCI class and per-class
attribute dictionaries used by the native reader. The storage directory described
in [native parameter storage](native-parameter-storage.md) does not establish
that its selectors are writable. This editor does not use that directory as an
edit permission list or modify saved runtime parameters.

## Review and preservation

1. Enter decimal text. Incomplete text is retained separately from accepted native
   bytes, by exact route/interface, source content, record and property encoding.
   Block/task navigation restores that text; another station never inherits it.
   Browser session storage holds at most 64 such drafts. Storage failures are
   visible. No review is restored from storage.
2. **Review file copy** binds the source/capture, actual selected target and
   connector configuration, record reference, original encoded-property hash and
   proposed text. Review shows the previous value, stored Real, binary payloads
   and any decimal precision change. Text/source changes retire pending results.
3. **Save edited File copy** recomputes and checks the complete review digest.
   The browser verifies source/review headers and the downloaded byte digest
   before saving. Changing inputs or controllers retires a late export.

The numeric policy is explicit decimal text → finite Python binary64 → IEEE
binary32. A maximum of 128 characters is admitted. Nonfinite values, invalid
syntax, excessive exponents, float32 overflow and nonzero values rounded to zero
are rejected. Signed zero is preserved in the binary payload and shown as bits
in review. This is not a claim that CCT uses the same decimal conversion policy.

Only the four existing expanded Real payload bytes may change. Source headers,
record lengths, tags, references, Device identity, unknown fields and metadata
remain exact. The implementation reparses its output and checks every expanded
byte outside that payload. Ordinary single-member gzip is recompressed with its
original ten-byte header and a new valid trailer; compressed bytes can therefore
change more widely. A no-op returns the original bytes exactly, including gzip.
The original capture is never overwritten. Each copy changes one selected field.

## Explicit boundaries

Preview and export use already captured bytes and issue no BACnet requests. The
exact capture route and current connector configuration must still match; this
does not introduce a separate offline native-file upload entry path. Reviews
declare `field_actions: false` and `controller_write: false`. There is no apply
endpoint for this profile, and the edited file is not relabelled as the running
application or fed into the separate instance/name transfer workflow.

This is a checked local binary transformation, not general native logic
generation, saved-parameter merging, hardware allocation, vendor-package or
firmware compatibility validation. CCT reopening, matching release semantics,
deployment and physical controller acceptance remain separate unverified work.
The existing CAF editor and portable graph workflows retain their own scopes.

## Local evidence

`tests/test_moi_signal_defaults.py` uses independently authored full records,
short/extended framing, raw/gzip sources, both eligible classes and opaque
metadata. An independent BACnet Real encoder supplies expected changed bytes.
It covers byte-exact no-op, signed zero, rounding, malformed/ambiguous sources,
unsupported types, numeric bounds, source/property/review/configuration guards
and session-token admission. Actual UDP File acquisition precedes production
HTTP preview/export; no additional field request is allowed during either local
operation and the immutable original is checked afterward.

`web/tests/controller-workspace.spec.ts` checks actual production HTTP and UDP
peers, incomplete drafts across blocks/tasks, precise downloaded bytes, unchanged
original captures, delayed reviews, altered download digests and controller
changes between identical Device IDs. These are local tests, not field evidence.
Enter in the value field submits a standard review form; saving a copy remains
a separate explicit action. Storage failures and readable form text are checked.

The final local qualification passed 120 relevant backend cases, eight new
browser cases across Chromium/WebKit, eight existing controller-workspace cases,
four CAF entry/save regressions and six package checks. The final complete-APDU
observer check records no additional requests during local review/export. Five
previously saved native File captures were also inspected locally and transformed
in memory with preservation checks; none was sent to a controller or saved as an
edited program. This extends source-format evidence, not CCT or field acceptance.
