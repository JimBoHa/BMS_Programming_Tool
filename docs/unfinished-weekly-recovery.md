# Unfinished weekly text recovery

In **Schedules → Offline Calendar and Schedule library**, open the original capture,
select its Schedule and weekly day, and expand **Weekly workspace draft limits**.
**Export unfinished weekly text** saves the selected retained day even when its
time, number or quoted String fields are incomplete. Export its original capture
archive too before reloading or moving computers.

Import that capture archive on the destination, open the same Schedule and day,
and choose **Import unfinished weekly text**. An existing retained buffer must be
explicitly discarded before replacement, including a buffer previously exported
as a reviewed native draft. Failed imports keep existing rows. Recovery creates an
edited buffer; it does not mark the draft reviewed or restore a controller token.

The file uses `native-schedule-unfinished-weekly/1`. Its source is an exact original
capture ID, canonical Schedule identifier and day text `1` through `7`. It contains
ordered raw text rows and optional earlier import references. Internal row keys,
saved/dirty state, native proof and field authority are excluded. Invalid raw text,
empty days, inactive String fields and explicit native Null remain distinct. Row
keys are generated locally on import; the text and order remain unchanged.

The local multipart route is
`POST /api/bacnet/schedules/library/weekly/unfinished/import`. It requires the
Studio token, validates the immutable source against the existing numeric or
UTF-8 String weekly profile, and returns
`native-schedule-unfinished-weekly-import/1`. It makes no field requests, creates
no native review and does not mutate captures. Existing weekly profile rules,
seals, controller write paths and receipts are unchanged. In particular, recovery
does not broaden the older weekly profile's exception-context eligibility.

Strict parsing rejects duplicate keys, malformed UTF-8, unpaired Unicode
surrogates, excessive nesting, unknown fields and authority claims. A file is
limited to 512 KiB, with at most 32 rows, four time text fields of two UTF-16 units,
256 value-text units and 1,538 optional quoted-String units. Native types must
match the captured Schedule default or explicit Null. These are raw editor limits;
valid BACnet times and values still require a separate native review. Worst-case
escaped fields for all 32 rows fit the file limit.

The browser compares the response with the exact parsed original file, its SHA-256,
selected capture, Schedule, day and observed datatype before remembering any rows.
Retained filenames and earlier review IDs are unverified historical references.
The current raw filename and hash are displayed separately and survive editing
and re-export without growing a nested import history.

The existing 128-day/4 MiB workspace limits include the added provenance. Capacity
refusal keeps every previous buffer; there is no eviction. Import starts by
retiring the local review. Edits, source/day changes, target/interface changes,
task closure, visibility and page lifecycle changes retire pending replies. An
older reply cannot replace newer work, even after returning to the same day.

Qualification covers numeric and String recovery, local graph and CAF reload,
source/day mismatch, explicit replacement refusal, malformed and oversized files,
response substitution, late replies, raw copy isolation, workspace capacity and
narrow-screen provenance. Authored direct/routed native sources exercise the
existing capture profile. Controller deployment, physical acceptance and Bluetooth
remain separate operations.
