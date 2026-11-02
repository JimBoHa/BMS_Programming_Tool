# Restore unfinished exception text

Open the original capture and its Schedule in **Schedules → Offline Calendar and
Schedule library → Schedule exceptions**. Expand **Retained exception drafts**,
then choose **Import unfinished exception text**. Import restores the raw fields
saved by **Save unfinished exception text**, including invalid partial numbers,
times, dates, references and quoted JSON String fragments.

The original capture must already be in the local library. Keep its capture
archive with the unfinished-text file when moving computers. Import never chooses
a different live controller, switches the selected Schedule or reinterprets a
foreign capture by its model/name. A matching existing buffer requires explicit
**Discard exception edits** before replacement; other source buffers remain intact.

## Text and source qualification

The input format remains `native-schedule-unfinished-exceptions/1`. A separate
local importer, `native-schedule-unfinished-exception-import/1`, verifies the exact
immutable capture/Schedule and observed default datatype. All row/array shapes,
keys, period choices, native type choices and raw text lengths are bounded.
Row/time keys must be unique. Inactive numeric/String/date fields stay intact;
the importer does not parse partial text into native primitives or repair it.
String and typed Null retain their separate fields and meaning.

File input is bounded at 8 MiB to accommodate existing pretty-printed exports.
The existing workspace still holds at most 64 buffers and 4 MiB of serialized
UTF-8 data, including imported provenance. A file fitting its input bound can
still exceed the workspace's remaining capacity and is refused without eviction.
The existing 512 KiB reviewed-native document limit remains unchanged.

UTF-8, Unicode, duplicate keys and structural bounds are checked strictly.
Raw lengths match the browser's UTF-16 field limits, including astral characters.
The browser verifies the original file hash and exact parsed source/buffer against
the returned response before copying it into the workspace. It also rejects
unknown fields, changed authority declarations and substituted response content.
A late reply cannot replace work after edits, source changes, navigation,
visibility or A→B→A transitions. No review survives restoring text.

## Provenance and authority

**Unfinished text import provenance** records the imported filename and exact file
SHA-256 behind Details. These identify the saved file, not the current edited
buffer after later changes. Earlier filenames/review IDs in the file are retained
as unverified references and are not presented as verified native review proof.
Re-export includes the bounded provenance and raw fields without nesting history.

The import route is token-protected multipart
`POST /api/bacnet/schedules/library/exceptions/unfinished/import`. It creates no
native review, write token, capture mutation or field query. It retains no server
review cache or field plan and leaves original capture bytes unchanged.

Correct unfinished fields and choose **Review exception draft** when ready.
Native encoding, exact local export and separately qualified controller deployment
continue through their existing independent profiles. Importing a raw file never
implies a CAF edit, successful native compilation or controller acceptance.

Qualification uses authored source captures, actual local HTTP routes, Unicode/
size/schema refusals and exact raw fields. Browser cases cover graph/CAF entry,
reload, String/Null recovery, overwrite/source refusal, malformed files, substituted
responses, lifecycle changes and phone presentation. Normal file uploads exercise
browser multipart transport. Held ownership cases use a separately verified real
HTTP response from the known original bytes; they do not replay the browser's
multipart body. Older unexplained multipart/accessor/timeout observations remain
separate and are not explained by these passing cases.
