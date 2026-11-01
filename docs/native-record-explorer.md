# Captured native record explorer

Program → Controller application → **Browse captured native records** lists
recognized engineering and metadata records from the selected File capture,
including records outside readable diagrams. Search finds record references,
names, native classes, stored object references and property IDs/names/decoded
values. **Inspect record** opens its stored properties and encoding evidence.

This is captured source data. A stored object reference is not proof that the
controller publishes that object or that its value is currently live. Native
class names and source references do not establish a physical module inventory,
spare input, hardware binding or program association. Current live reads remain
separate.

## Source and encoding evidence

The existing reader advertises `record_inspection` independently of diagram
reading, logic editing and native compilation. Fully framed sources include
metadata records without an engineering reference. Legacy reference scans are
labelled separately; neither view claims an inventory of every device structure.
Record parse errors remain visible and original opaque captures stay retained.

Every row has an ID derived from its actual expanded-source offset, its native
class, stored reference when present, property count, byte range and record
SHA-256. Metadata records use offsets for identity rather than invented names or
Device addresses. Property details retain original source order, native scalar
datatype/value or a structured/undecoded status, encoded byte range/length and
SHA-256. Unknown properties are not dropped or replaced with guessed values.

Offsets and record/property hashes refer to the expanded application bytes. The
original compressed or plain File has its own capture SHA-256. Those namespaces
remain distinct. Signed zero is displayed explicitly; datatype and original
encoding evidence accompany decoded numeric values.

## Bounded local API

`POST /api/bacnet/controller/application/records` accepts the existing exact
controller target and `capture_id`, plus literal case-insensitive `query`,
`offset` and `limit`. `POST .../record` adds a canonical `record:<offset>` ID and
pages or searches that record's properties. Default pages contain 64 rows;
requests admit 1–128 rows and queries up to 256 characters. Both endpoints require
the existing local session token.

Responses use `controller-native-records/1` and bind to the capture ID, original
File SHA-256, target and capture time. Existing capture integrity, route, Device
and exact connector checks run before inspection. Results are explicitly
read-only, make no field action and do not reverify a responding controller.
They read retained bytes; they send no BACnet request or backup-state command.

The browser checks source/request/record identity and retires pending results on
selection or source changes. Closing the explorer retires pending display
requests. Search results identify their applied query; typing a new query does
not silently relabel earlier results. Changing targets cannot transfer a record
selection or resurrect a late property response. Table scroll regions accept
keyboard focus and scoped left/right arrow scrolling, with a visible focus ring.
Controls stay within the
existing Program workspace, using searchable tables and progressive disclosure.

## Verification and remaining work

Checks cover compressed/plain source offsets and hashes, metadata outside
diagrams, unknown structured properties, source-order paging, literal search,
legacy versus declared framing, API bounds/tokens, route/interface mismatches and
actual UDP acquisition followed by zero additional wire requests for records.
Browser checks inspect actual captured metadata and a typed Real, retain byte
evidence, reject a wrong capture and hold a genuine property reply while changing
between controllers sharing a Device ID. Narrow tables retain local scrolling.

`FMT-NATIVE-RECORDS-001` records this inspection slice. JCI-02 remains partial:
loss-preserving native editing, broader structure/format coverage, full editable
IR, general native logic compilation and controller deployment require separate
typed contracts and acceptance. These local authored checks do not establish
physical-controller or Bluetooth acceptance.

Signed Integer application tags with one-to-four-byte payloads are decoded by the
[bounded signed32 reader](native-signed-integer-reading.md). Wider/structured
encodings remain opaque with their original evidence; no write is implied.
