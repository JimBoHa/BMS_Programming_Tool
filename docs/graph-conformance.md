# Portable graph conformance suites

**Conformance tests** runs operator-authored acceptance checks against the current
portable Studio graph. Author input value/quality changes, exact expected block
values and optional final transactional scan faults. Save named suites locally,
reopen them after restart, or import/export their JSON. Download a sealed run
report containing the original server response bytes.

This closes the portable acceptance-check gap associated with **MF-8f42fc2004**.
It does not execute native CAF logic, emulate JCI firmware, test physical I/O or
certify a complete sequence, Title 24 or Guideline 36. A graph imported from a
supported interchange format is tested only as its verified portable graph;
unknown/native Sedona components are refused. Existing native CAF saved scalar
editing and stimulus previews remain separate workflows.

## Criteria and source scope

The reviewed Johnson Controls/Yorkland *ASHRAE Guideline 36 Presentation*, June
2021, PDF page3, describes detailed HVAC sequences and labels functional tests
that confirm implementation **“(Future)”**. The downloaded source is
`guideline36-training-2021.pdf`, SHA256
`075565f9664a80f9720ae68c1020c84cb08ad12aaaa7aef5d329ad4ac2d9ed3d`.
It supplies no authoritative executable acceptance trajectories. Therefore all
expected values in this feature are explicitly authored criteria, never derived
from the engine under test. Authoritative Guideline36 trajectories
(IA-0c2a127e64), native CCT execution and manufacturer acceptance remain open.

## Workflow and identity

1. Open an executable portable graph, then **Conformance tests**. The displayed
   source includes program identity, saved revision and full model SHA256.
2. Name the suite and each case. Set duration, scan interval and aware UTC start
   clock. Add input changes at exact scan starts, beginning at elapsed zero.
3. Add explicit expected signal values at exact successful scan ends. Choose
   existing root inputs, outputs, internal blocks or supported macro outputs.
   Types and exact engineering-unit tokens must match; no implicit conversion.
   A new suite contains no generated expected values and cannot run/save/export
   until every case contains a check or explicit expected fault.
4. Run and inspect each comparison, actual value, tolerance, quality fault,
   missing check and coverage statement. Change an expected value to exercise
   a failing test; passing checks alone never imply full sequence coverage.
5. Save a local suite revision, reopen it, export/import portable suite JSON or
   download the original sealed report. Reports are downloads, not persisted
   execution sessions. Local suite storage has optimistic revision protection;
   stale saves/deletes fail rather than overwrite another revision.

Suites bind to the exact program hash, identity and revision, the ordered
signal/type/unit contract and an explicit execution-profile SHA256 (a versioned semantics contract, not
a runtime-build or manufacturer attestation). A label,
layout, metadata, block, library or revision change invalidates the old binding.
The UI retains a stale draft for inspection, disables execution/export and offers
an explicit new suite. Expectations are never silently transferred. Returning
to the exact source permits reopening its saved suites. Source/draft changes,
unmount, navigation and late/malformed/wrong-source responses cannot authorize
an old report download. The shared workspace navigation boundary separately
controls component lifetime.

## Deterministic semantics

Each case starts a fresh Engine, with default input values, good input quality
and empty retained state. Cases do not share memory. Input changes apply at an
exact scan start and hold until replaced. Numeric and Boolean samples remain
distinct; bad qualities trigger the engine's transactional `ScanError` behavior.
An omitted input continues its default or held sample. The report lists defaults
and supplied conditions explicitly.

Scans use the declared interval, with a shorter final scan when required.
Decimal schedule matching avoids ambiguous `0.1+0.1+0.1` event matching. Checks
observe a successful scan's values at its declared end. The explicit engine
clock is the normalized start clock plus elapsed scan end; wall-clock execution
speed has no effect. Numeric expectations use finite binary64 values and

`abs(actual-expected) <= max(abs_tol, rel_tol*max(abs(actual),abs(expected)))`.

Boolean checks are exact and require zero tolerances. No scripts, expressions,
regular expressions, automatic expected-value generation or inferred units are
accepted. A final expected fault must match its exact attempted scan end and an
optional literal message substring, and leave the engine snapshot unchanged.
Unexpected faults stop that case and list later checks as not run. A missing
expected fault fails the case. Numerical error overflow is explicit rather than
encoded as non-finite JSON. Integer criteria/stimuli that cannot be represented
exactly as binary64 are rejected; such actual values fail the comparison with
explicit representation evidence rather than passing through float rounding.

Coverage lists asserted/unasserted root signals and outputs, inputs using only
defaults and the supplied value/quality conditions. Checks at other times,
unlisted conditions/combinations, downstream physical behavior and native
controller behavior remain untested.

## Bounds, storage and evidence

Strict local session-protected APIs expose `/api/conformance/catalog`,
`validate`, `run`, `import`, `export`, `save`, `saved/{id}` and guarded deletion.
All are local POST operations; none opens a field interface or writes a
controller. A suite allows20 cases,5000 total scans,2000 total checks and one
million expanded block evaluations. Durations are at most24h, intervals at most
60s and suite JSON at most2MiB. A report is at most4MiB. There are100 saved
suites and32MiB aggregate suite storage; reaching capacity refuses the save and
never silently evicts existing criteria.

Stored canonical suite bytes have SHA256 integrity checks and are revalidated
against the current exact source on every load. Reports include the program,
suite and execution-profile hashes, target declarations, timestamp, comparisons,
faults, coverage and explicit native-execution/controller-write/certification
flags. `content_sha256` covers the entire report except itself using UTF-8 JSON,
sorted keys, compact separators, finite values and no ASCII escaping. The
browser pairs parsed display data with the same original HTTP Blob, preserving
integral floats, signed zero and exponent spellings; it never reconstructs or
reseals evidence with `JSON.stringify`.

Tests use independent hand-calculated Delay, TimerOn and clock-driven Schedule
expectations, quality transactions, source/type/unit/budget conflicts, nested
macro observation, SQLite restart/optimistic integrity and real local browser
workflow/download checks. These are portable engine tests, not independent
vendor firmware validation.
