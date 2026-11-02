# Captured native Calendar date drafts

Open **Schedules → Offline Calendar and Schedule library**, open an original
capture, then expand **Calendar dates**. This works from a local application or
CAF without opening a field interface. With a controller selected, its header
and the capture's original target remain separate: opening a capture does not
establish that the file belongs to the selected controller.

The editor reads actual captured standard BACnet Calendar objects. It offers
three entry types: Date pattern, Date range and Weekday pattern. Add or remove
entries, edit their fields, then choose **Review Calendar dates** and **Export
reviewed Calendar draft**. These actions produce a local encoding review. They
do not query or change a controller, create a Calendar object, compile a CAF,
or grant permission to transfer the value.

## Patterns and preservation

Date controls show years 1900–2154 or `*` for any year. Month controls include
odd, even and any month; day controls include last, odd, even and any day.
Weekdays use Monday through Sunday or any weekday. Date ranges retain two
independent native Date patterns. Weekday patterns retain the native month,
week and weekday bytes. Source order and duplicate entries remain unchanged;
empty lists are valid. New rows begin incomplete, without inventing a current
controller date or an all-day default.

The CalendarEntry alternatives and Calendar Date_List type follow the pinned
[BACpypes3 0.0.110 datatype definitions](https://github.com/JoelBender/BACpypes3/blob/v0.0.110/bacpypes3/basetypes.py)
and [object definitions](https://github.com/JoelBender/BACpypes3/blob/v0.0.110/bacpypes3/object.py).
Week values 1–5 select successive seven-day portions from the month's start;
6 selects its last seven days. Values 7–9 select the seven-day periods before
the last seven, fourteen or twenty-one days. Those newer values were added by
[ASHRAE 135-2012 Addendum bg](https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-135-2012bg.pdf)
in protocol revision 18. Reviews record that requirement when applicable and
explicitly leave target revision and acceptance unverified. Related native
test patterns appear in [ASHRAE 135.1-2019 Addendum s](https://bacnet.org/wp-content/uploads/sites/4/2024/05/135_1_2019_s_20230331.pdf).

The profile checks native byte ranges, concrete Gregorian dates, concrete
weekday agreement and fully concrete range order. It encodes wildcard and
special patterns without evaluating them. Captured Present_Value remains an
original observation, not a simulation of proposed dates. No target clock,
timezone, DST policy, exception precedence or manufacturer behavior is inferred.

## Source and review contract

`native-calendar-date-list-draft/1` is independent of the existing numeric and
String weekly-day draft authorities. The original capture must contain a verified
Device identity and exactly one verified selected Calendar, matching native
Object_Identifier evidence, a native Boolean Present_Value and a complete
Date_List. The original Date_List must decode, exhaust tags and re-encode exactly.
Unknown, partial, ambiguous, noncanonical or unsupported sources remain retained
evidence and cannot seed an editable value.

A review binds the exact original capture/source and evidence hashes, Device and
route, Calendar, property, complete original property bytes and unchanged-property
context. It contains the old and proposed ordered entries, native value bytes,
SHA-256 values, roundtrip proof and count/change summary. Nothing rewrites the
original capture or other properties. Local self-seals detect changed evidence;
they do not authenticate manufacturer provenance or current controller state.

Export regenerates the entire deterministic review from the original source and
requires its exact expected ID. It has no expiring review cache and cannot evict
weekly-day reviews. The browser saves the original HTTP response Blob and checks
that it equals the reviewed document. Import validates the profile, rules and
seal, regenerates the proof from the retained original, and compares the whole
document. A modified or missing source requires reopening valid evidence.

To move work, export the original capture archive as well as the Calendar draft.
Import the capture on the destination computer before importing its reviewed
draft. A draft JSON file alone is not a controller backup or self-contained
application. Imported rows require another explicit review before export and
carry no field transfer authority.

## Workspace behavior and limits

Unfinished text stays with the exact capture and Calendar while switching tasks,
workspace surfaces, captures, and connected/offline views. Discard affects only
that selected Calendar. The workspace holds at most 512 edited Calendar buffers;
reaching capacity refuses another new buffer without replacing existing work.
Export and discard a retained draft to make room. Buffers remain in memory, so
export work before restarting or reloading.

Edits, capture/object/interface changes, task departure, visibility changes and
source A→B→A retire pending results and reviews. Delayed review/import/export
responses cannot restore retired authority, overwrite another draft or start a
download. Source refresh retires transient operations and preserves local text.
The existing weekly editor retains its own behavior and export-before-navigation
boundary; this slice does not claim weekly draft retention is complete.

The new profile permits at most 32 entries and 128 KiB per reviewed document.
Existing source-library capture, byte and namespace limits are unchanged. Strict
request models reject extra fields and coerced native values. All four endpoints
require the local session token:

- `POST /api/bacnet/schedules/library/calendar/source`: original capture `id`.
- `POST .../calendar/review`: `capture_id`, exact `object_id`, typed `entries`.
- `POST .../calendar/export`: exact `draft` and `expected_review_id`.
- `POST .../calendar/import`: reviewed JSON file; the original capture must exist.

## Qualification

Independent literal tags cover all three alternatives, empty/duplicate/ordered
lists, strict invalid patterns, altered identities and seals, partial and
noncanonical evidence, stateless restart/import/export, immutable originals and
unchanged weekly review caches. Direct and routed authored UDP peers provide
actual captures; local drafting continues after the interface closes.

Chromium/WebKit checks exercise local graph and CAF entry, selected-controller
source labels, compact controls, raw text retention, native literal exports,
invalid dates, re-import, substituted responses and delayed operations. These
are software checks using authored peers. Native Date_List transfer now has a
separate [guarded backend](native-calendar-write.md) and
[controller deployment interface](native-calendar-controller-deployment.md).
Exception editing, schedule context/linking, vendor CAF integration and physical
controller acceptance remain separate work under SCH-01–SCH-03.
