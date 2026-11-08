# Supplemental checks for Metasys source changes

This is a local preparation and comparison tool for a future source-remapping
adapter. **It does not edit a controller, implement NAE synchronization, qualify a
source-write method, or complete a live remapping.** The independent NAE writer
and its controlled hardware test remain unfinished. The
[source inspection investigation in PR #327](https://github.com/JimBoHa/BMS_Programming_Tool/pull/327)
describes that gap.
No CCT/PCT application is launched or required by this command.

## Local command

```sh
bms-tool metasys-source-review --manifest proposed.json --before original.json --output review.json
bms-tool metasys-source-review --manifest proposed.json --before original.json --after subsequent.json --output comparison.json
```

The first command checks expected old sources and exact captured identities.
The second independently compares the subsequent capture to the proposed source
changes. A comparison that does not match exits with status 1 and retains its
report. Invalid, ambiguous or stale input exits with status 2. Existing output
files are never overwritten. Reports contain private point references and GUIDs;
keep them with private captures outside the repository. New reports use mode
0600 on POSIX systems; Windows uses the containing directory's access controls.

This CLI adds no destination or feature tile. Any later connected source editor
belongs in Points & I/O and its guarded changes belong in Changes, following the
existing Edit → Review → Apply → Verify workflow. An imported comparison report
is never a controller write review or an Apply token.

## Manifest and capture contract

A manifest is an explicit list of 1–128 point records. Each record requires:

| Field | Meaning |
| --- | --- |
| `item_id` | Exact captured item ID |
| `guid` | Existing point GUID |
| `metasys_object` | Existing local `type.instance`, unchanged by the repair |
| `path`, `name` | Existing item reference and point name |
| `source_type` | Explicit mapped analog-input (0) or binary-value (5) |
| `old_source_instance` | Expected original remote source |
| `proposed_source_instance` | Intended replacement remote source |

Additional manifest annotations are not interpreted as verification evidence.
The tool rejects duplicate item IDs, GUIDs, local objects or references, including
ambiguities elsewhere in the captured branch. It rejects missing/duplicated or
nested source rows, local/source-type conflicts, Boolean numeric values, and
old sources that differ from the original capture. Names and references must
match exactly. It never globally replaces an instance number in a document.

A supplemental JSON capture has a timezone-qualified `captured_utc` and all of
these record arrays, including explicit empty arrays where appropriate:

- `items`: original item records, including `itemID`, `GUID`, `ObjectId`,
  `PartialReference` and `UserName` for each selected point.
- `properties`: captured property rows, including `ItemID`, `AttribID`, `Value`,
  `ValueOrder` and `ParentValueOrder`. Exactly one scalar source row (32589) is
  required for every proposed point.
- `incoming_item_references`, `incoming_text_references`, `historians`,
  `historian_slices` and `reporting`: supplemental identity/link records.

The module does not connect to SQL or execute SQL statements. A separately
authorized SELECT-only capture can provide these records. Missing sections do
not become empty successful comparisons. Each input file is bounded to 32 MiB;
duplicate JSON keys and non-finite numeric values are rejected.

## What the comparison establishes

The report binds the normalized manifest and both supplied captures to SHA-256
digests. These hashes identify local inputs; they do not authenticate the source,
establish freshness or confer permission. A subsequent capture must not predate
the original. Live identity, firmware, route and expected-old-source checks are
still necessary immediately before any future field transfer.

The comparison permits only the explicitly selected source `Value` changes.
Changed source-row `EventTimeStamp` and `ValueState` bookkeeping is separately
reported. Every other captured record remains protected, including local object
identifiers, GUIDs, item references, names, parentage, other property values,
extensions present in the capture, incoming links and historian/reporting rows.
Comparison ignores row order and preserves multiplicity. Unselected energy
points and their historian records receive no special exemption.

Both flags must match for a successful local comparison:

- `all_expected_sources_observed_in_after_capture`: all intended sources appear
  in the supplied subsequent capture.
- `captured_records_match`: no other protected captured-record differences were
  found. Partial completion or a rejected/unapplied batch stays a failed
  comparison, even if some individual sources match.

Other timestamp or cache/reporting watermark changes remain visible differences
for review. A difference is not automatically diagnosed as a configuration change
or deletion. This conservative comparison never silently accepts concurrent work.

## Boundaries that remain

These captures are not complete native engine backups, authenticated current
readbacks, or historian sample exports. Matching imported records does not prove
that uncaptured links/configuration or historical samples are preserved. Separate
live source/name/unit/value and engine-identity checks remain necessary.

`apply_available`, `native_backup_verified` and `network_access` are always false.
The command performs zero configuration writes and never commands a polarity BV.
An independent native NAE configuration adapter, recoverable original, one-use
review, stale/concurrency protection, rejection/uncertainty reconciliation and
controlled mapper-class/firmware qualification are required before live editing
can be enabled. This module does not substitute ordinary WriteProperty, a
field-controller CAF transfer, delete/recreate or direct configuration SQL writes.
