# Native Schedule exception drafts

Within **Schedules → Offline Calendar and Schedule library**, open an original
capture and expand **Schedule exceptions**. Select a captured Schedule, then
edit, add, remove or reorder its events. The same local workflow is available
after opening a graph or CAF, without opening a field interface. Its data comes
from the selected native capture, independently of the open local application.

The separate profile `native-schedule-exception-draft/1` encodes a complete
Exception_Schedule array for one existing standard Schedule. It supports inline
Date, DateRange and WeekNDay periods plus Calendar object references, explicit
event priorities and typed time/value transitions. Source Device/Schedule tag
identities, complete context and all original array elements are revalidated.
Unsupported or partial sources retain their original archive and show an issue.

## Native values and meaning

At most 32 events and 32 specific, strictly increasing times per event are
supported. Empty event arrays and empty event time lists are explicit values.
Order and duplicate events remain intact. EventPriority uses 1 through 16 and is
independent of the captured Schedule's Priority_For_Writing. The editor preserves
these values without evaluating overlap or choosing a winning event.
Zero-padded clock and priority fields are accepted as decimal integers while the
unfinished buffer retains their original text.

Periods reuse the reviewed Calendar choices. DateRange endpoints follow the
[specific/unspecified range qualification](native-calendar-date-ranges.md).
This separate exception domain also reads captured WeekNDay values 7–9 and
records a minimum-known protocol revision of 18 for original or proposed uses.
The existing numeric/String weekly profiles keep their previous qualification
and sealed rules. A successful local encoding does not verify a current device
revision. Calendar references retain their canonical object identifiers without
querying their existence, contents or current value.

The captured non-Null Schedule_Default supplies the value datatype. Every new
transition uses that exact type or explicit Null. Existing Boolean, signed32
Integer, unsigned32 Unsigned/Enumerated and finite Real32/Double64 policies apply.
Reviews retain requested text beside the decoded native text and complete tag
bytes, exposing floating rounding and signed zero. CharacterString values use
strict UTF-8 within 256 wire bytes. Quoted JSON editor text preserves empty
strings, literal `null` text, controls, NUL, whitespace and Unicode independently
of a typed Null release. Switching to Null preserves unfinished numeric or
String work for a later type selection.

Native encoding follows the pinned
[BACpypes3 SpecialEvent/period definitions](https://github.com/JoelBender/BACpypes3/blob/v0.0.110/bacpypes3/basetypes.py).
The specific date/time and event priority distinctions are reviewed against
[ASHRAE 135-2008 Addendum ac](https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-135-2008ac.pdf).
Modern week patterns retain the requirement documented in
[ASHRAE 135-2012 Addendum bg](https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-135-2012bg.pdf).

## Review, save and restore local work

**Review exception draft** verifies the exact source and constructs the native
whole-array value. Every original entry and the complete original array must
re-encode exactly. Decoding the proposed array must exhaust its tags and reproduce
the same bytes. The response retains original/new values, source/context hashes,
requested fields, normalized native text and a deterministic review ID.

**Export reviewed exceptions** regenerates that proof from the original capture
and expected ID and saves the exact authenticated JSON response bytes. **Import
reviewed exceptions** reproves the complete document and requires its original
capture to be present. The document bound is 512 KiB. Imports for another source,
unknown profiles, changed rules, altered native bytes or mismatched request
proofs are refused. Browser validation also checks native byte hashes and exact
request/source ownership. Keep the original capture archive with its draft when
moving computers.

Unfinished fields, selected events and imported filename/review provenance stay
with their capture/Schedule through task and surface navigation. The workspace
holds 64 edited source buffers within 4 MiB of serialized UTF-8 data. New or
expanded work exceeding a bound is refused without evicting earlier drafts.
Viewing an unchanged source uses no edited-buffer slot. **Discard exception
edits** restores only the selected captured seed. The retained-source list also
lets an operator save or explicitly discard an earlier buffer.

**Save unfinished exception text** exports raw editor fields and source references
for manual recovery, including invalid partial text. This separate document has
no import action or native review proof. Reviewed JSON import remains the restore
path for complete reviewed work. These buffers stay in memory; reloading or
restarting requires saving first. No original capture is deleted by draft discard.

Pending reviews, imports and exports retire on raw/source/selected-controller,
interface, task, visibility and A→B→A transitions. Restored text and imported
provenance do not restore a review. Loading remembered settings while no verified
field context exists keeps purely local imports usable. A same-Schedule import
cannot replace retained work until that buffer is explicitly discarded.

## APIs and qualification boundary

All routes require the Studio token and begin with
`/api/bacnet/schedules/library/exceptions`: `POST /source`, `/review`, `/export`
and multipart `/import`. Models reject mutation or token fields. Review/import
are stateless and leave the older weekly review cache and immutable capture
files unchanged. Captures remain sequential observations and self-sealed source
claims; they do not establish authenticated manufacturer provenance.

Qualification uses independently authored direct/routed UDP source captures,
literal array/primitive bytes, String/control limits, source/metadata refusals,
document bounds and actual offline HTTP routes. Browser checks cover both entry
paths, modern captured periods, exact imports/exports, raw retention, capacity,
source/controller lifecycle changes, response substitutions and late result
retirement. The controller-context test uses an explicitly authored HTTP identity
surface while the backend field interface remains closed. Normal uploads test
browser multipart transport; a held-import ownership case supplies a separately
verified real HTTP response without replaying the browser multipart request.

This profile performs local exception engineering. A [separate deployment
profile](native-schedule-exception-deployment.md) adds one whole-array write with
fresh same-Device Calendar identity checks and receipts. Calendar contents/current
value verification, effective-period/default/context/link changes, evaluation,
timezone/DST behavior, native CAF compilation and physical manufacturer/transport
acceptance remain separate. SCH-01–SCH-03 remain partial. Existing Calendar and
weekly writers and durable journals retain their original authority.
