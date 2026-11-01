# Compare retained native backups

In **Program → Native backup defaults**, select the left retained source, open
**Compare retained backups**, select the right backup and choose **Compare original
backups**. A field connection is not required. Both snapshots retain their own
original Device, route, capture time and acquisition limitations. Recorded
configuration equality preserves JSON types; missing or invalid interface
metadata remains unknown. Selecting a backup or opening this disclosure performs
no controller query or backup command.

The report keeps three distinct observations:

- Exact original byte equality and SHA-256 for Files 3, 11 and 12. Changed saved
  files do not silently replace archive properties or trigger a saved-setting merge.
- Recognized engineering records matched by their unique engineering reference.
  Record byte changes are reported even when recognized property encodings match.
  Properties are compared only within the same native class. Added/removed records,
  class replacements and added/removed/changed property encodings remain distinct.
- Metadata records compared as a multiset of exact record hashes. They are never
  paired by offset, order, name or controller model. Equal metadata multisets do
  not imply identical file bytes or execution behavior.

Original and compressed containers can have different bytes while their expanded
recognized records match. Native datatypes and encodings remain evidence: signed
zero, Integer versus Unsigned and opaque structured properties are not normalized
into a claimed equal value. Scalar text in the table is a display preview; long
strings are explicitly truncated at 256 characters. Original property hashes,
record hashes and retained source files remain unchanged.

## Coverage and limits

Structured comparison requires recognized declared record framing on both sides
without ambiguous references or parser errors. An unsupported or opaque File 3
still has an original-file byte comparison and an explicit reader limitation; it
does not produce an invented empty structured program. Source acquisition identity
errors remain visible and do not authorize compilation or a controller change.

Each scan is bounded to 4,096 engineering references, 65,536 properties and 4,096
change rows. A budget stop is explicit, including when a search returns no visible
rows. Pages contain at most 64 rows; the interface requests 32. Search covers the
observed report evidence within that bounded scan. Empty search/page results do
not establish that the whole application is identical. Unrecognized semantics,
layout/execution effects and target release/package compatibility remain outside
this operation. There is no semantic equivalence, migration or restore plan.

**Download comparison JSON** saves the original response bytes for the current
page, with its query, source manifests, all three file hashes, coverage, limits
and evidence seal. It does not make another request. Display parsing never
reserializes that evidence. The seal is SHA-256 of the report without
`evidence_sha256`, using Python JSON with sorted keys and compact separators.
This is a local integrity record, not manufacturer authentication or a live
controller status.

## Ownership and API

The token-admitted local endpoint is
`POST /api/bacnet/controller/native-application/inspection/compare`. Its profile is
`native-backup-comparison/1`. It accepts left/right capture IDs and original
snapshot manifest hashes, plus bounded query/page fields. Extra targets, file
paths, compiler options and write instructions are refused. Both manifests and
all three original files are checked before comparison. Corruption, stale hashes
and redirected capture folders are refused through the shared source loader.

The interface binds a result to both source IDs/manifests/routes, query, selected
controller/interface, visibility and request generation. Changing either source,
search text, task or interface retires pending results before paint. Returning
A→B→A or closing/reopening the disclosure cannot revive the prior response.
Native field-operation locks remain authoritative; comparison cannot dispatch a
write, consume a plan or retarget an uncertain transfer.

Native-backup capability profile 8 adds a separate comparison-source row. It
qualifies one integrity-checked source for local comparison; the second snapshot
and structured coverage are evaluated by the comparison operation. Other archive,
compiler, package and transfer qualifications remain separate.

Local checks use independently authored plain/gzip records, opaque values,
different native numeric types, signed zero, changed metadata, replacements,
budgets, tampered files/manifests and strict HTTP admission. Chromium/WebKit checks
exercise actual local API responses and original downloads, source/search/task/
disclosure races, pagination, rejection and phone keyboard/layout behavior. No
site or Bluetooth result, native logic compiler, general restore, field program
change or physical controller acceptance is established here. JCI-02 and JCI-09
remain partial overall.
