# Unfinished Calendar text recovery

Open **Schedules → Offline Calendar and Schedule library → Calendar dates**.
Select the original capture and Calendar, then expand **Unfinished Calendar drafts**.
Export saves the retained raw fields even when they cannot produce a native
review. Save the original capture archive too before reloading or moving computers.

Import requires that same original capture and Calendar. Existing retained work
must be explicitly discarded before replacement. Failed imports keep its fields.
The raw copy preserves order, duplicates, empty lists, incomplete years, wildcards
and inactive date/range/WeekNDay fields. Unknown selected pattern values remain
visible as unrecognized choices; the editor does not repair them silently.

`native-calendar-unfinished-text/1` contains an exact two-string source and raw
buffer, excluding internal row keys and native/field authority. Keys are generated
locally when the buffer is restored. Earlier imported review IDs are unverified
historical references. The current raw filename and SHA-256 are separate provenance,
survive ordinary editing and re-export, and do not form an expanding nested history.
An actual new reviewed-native import replaces that raw provenance with its own proof.

The Studio-token-protected local route is
`POST /api/bacnet/schedules/library/calendar/unfinished/import`. It uses the existing
immutable Calendar source context, validates strict UTF-8/Unicode/duplicate-key and
schema/field bounds, and returns `native-calendar-unfinished-text-import/1`.
It creates no native review, cache entry, capture mutation, controller query or token.
The browser verifies the exact parsed original buffer, source and file hash before
remembering anything. Native Calendar profiles/rule hashes and controller-writer
admission remain unchanged; raw import cannot make an invalid pattern transferable.

Files are limited to 128 KiB and 32 rows. Each row retains its kind and all four
raw field arrays: four date fields, four start fields, four end fields and three
WeekNDay fields. Each text field has its existing four UTF-16-unit bound. A worst-case
escaped document with all 32 rows and bounded provenance fits the file ceiling.
The existing 512-context workspace count policy remains; new work at capacity is
refused without eviction. Stored buffers are independently copied.

Import retires the current local review immediately. Edits, source/object or
selected-target/interface changes, task closure, visibility and pagehide retire
pending replies. Returning to the same context cannot revive an older import.
Remembered offline interface settings carry no authority and do not cancel local
file work merely while preferences load. Draft fields stay attached to their
original capture/Calendar across these changes.

Qualification covers raw graph/CAF reload, all pattern kinds and inactive fields,
source/object mismatch, explicit discard, bad/oversized files, held and substituted
replies, copy isolation, capacity and phone provenance. Existing Calendar and shared
exception controls retain separate native and field qualification. No site or
Bluetooth action is part of this recovery workflow.
