# Strict UTF8 native Schedule weekly-day strings

Connect's existing native Schedule capture library can draft and explicitly
apply one day of an already observed standard BACnet CharacterString Schedule.
It uses separate profiles:

- `native-schedule-utf8-weekly-day-draft/1`
- `native-schedule-reviewed-utf8-weekly-day-write/1`

The seven original numeric/Boolean/Null draft domains keep their original rules,
request shapes and authority. Existing captures, draft exports and passive write
receipts retain their original bytes and seals. No old review is silently
upgraded to authorize strings. A String schedule requires its explicit new draft
marker even when the proposed day is empty or contains only Null transitions.

## Qualification before interpretation

The Schedule must have a non-Null CharacterString default, with every observed
present value, weekly value and exception value matching that domain or Null.
Complete existing identity, seven-day, exception and context evidence is still
required. The library checks every preserved application-tag7 payload before its own
interpretation: encoding byte0, strict UTF8, at most256 text bytes and exact
primitive re-encoding. This includes unselected days and exception events.
String-bearing `encoded_value` property-tag evidence must also re-encode
byte-identically before interpretation. That captured field is SDK tag
re-encoding, not original UDP packet headers. Its conservative canonicality
check rejects nonminimal imported property-tag evidence; it does not prove or
require original wire-header canonicality.

The reader can normalize harmless original UDP tag headers before producing
`encoded_value`. Valid UTF8 payloads can therefore remain eligible after such
normalization. A real loopback probe confirms this boundary: original empty
String tag `750100` appears in retained UDP evidence while the captured property
becomes canonical `3e71003f`, and the qualified String draft is accepted. No text
is lost. Raw UDP observations remain available separately where captured; no
new packet-capture fidelity or original-header equality is asserted.

The pinned SDK can fall malformed UTF8 back to Latin1 and unknown encodings back
to encoding0. Its AnyAtomic can also preserve those original opaque bytes through
a whole DailySchedule roundtrip. A successful whole-day roundtrip therefore does
not establish valid string interpretation. This profile validates original
primitive bytes directly; it never patches the SDK decoder globally.

Unknown/legacy encodings, malformed UTF8 and oversized strings remain in their
original capture archives but cannot authorize drafts/writes. No fallback,
trimming, Unicode normalization or inferred occupancy enumeration is performed.

## Text entry and evidence

An empty string is valid. Literal string `"null"` differs from the explicit BACnet
Null primitive. Spaces, quotes, backslashes, combining characters, emoji, NUL and
control characters retain their admitted values. Unpaired Unicode surrogates are
refused, rather than replaced or returned as a server error.

The editor uses a quoted JSON string literal as a local text buffer, so CRLF and
NUL can be represented without HTML newline normalization. It parses that buffer
to a string, verifies well-formed UTF16 before UTF8 byte counting and submits the
unquoted raw value to the API. JSON literal `null` is not a CharacterString. The
local quoted buffer has a separate bound because escaping256 control bytes can
require more than256 displayed characters.

Captured source, review and write-receipt downloads preserve original server
response bytes. Preview/Apply authority binds the selected String profile,
its rules, original capture, observed datatype, target, day and source identity.
Changing source, selection or draft invalidates that authority. Passive old
receipts are evidence, not reusable Apply tokens.

## Transfer limits and uncertainty

The existing single-day path performs fresh sequential identity/static-context
reads, one unsegmented WriteProperty attempt and bounded readback. It retains the
same source-pinned direct/routed IPv4 guards,32 transitions,16KiB property value,
4,096-tag capture and480-byte actual encoded write-APDU bound. A256-byte String
value does not authorize a larger day. Oversized drafts can be reviewed/exported
offline, but Apply is refused before dispatch. No segmentation, automatic retry,
compare-and-swap, inverse write or remote rollback is added.

ACK loss and negative replies retain possible-application uncertainty; matching
readback does not prove when or why a device accepted a write. Cancellation
cannot undo dispatch. Explicit read-only reconciliation sends no further write.

## Manufacturer scope

FX Workbench14.15, LIT-12012256, PDF220–222 describes string schedules, typed
facets and destinations. Reviewed SHA256:
`207c83d8260bb22223f6ab0b93dbd47c93f056e28b754cb4b165fc73d18d9fbd`.
CCT18PDF247 describes Binary/Analog/Multistate choices; SCT19PDF329 also describes
derived output types. Those pages do not establish a JCI CharacterString target
or Niagara station serialization contract.

This feature is qualified standard BACnet editing of an existing observed
String Schedule. It does not create objects, change defaults/targets/priorities
or exception schedules, evaluate schedules, generate Niagara ORD/facet links,
compile CAF files or establish physical JCI/FX support. Full FX HTML5 Schedule
Manager equivalence and manufacturer/physical acceptance remain unfinished;
manual feature `MF-f9b827580e` remains partial.
