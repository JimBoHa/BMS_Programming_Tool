# Native existing-wire source archive copies

In **Program → Native backup defaults**, select a retained backup, inspect its
records, and inspect an actual activity or control-sequence record (class 536 or
575). Keep **Native diagram operation → Change existing source**, expand
**Copy an existing native wire source**, open its recorded sources,
choose an existing connection and replacement source, then **Review native wire
copy**. **Save native wire copy** exports a separate file; **Save exact native
wire review** retains the original response JSON. Neither action contacts a
controller or applies the change.

**Add matching connection** now opens a separately qualified
[local connection addition](native-matching-connection-copies.md). Switching
operations retains source drafts and recovery ownership while retiring reviews.

The web entry uses an original retained native backup. Its manifest and all three
Files 3/11/12 are checked before source inspection, review and export. Unknown
saved-setting schemas and historical acquisition identity errors do not suppress
this local archive operation. They remain visible evidence and do not qualify a
current controller. The copy does **not** merge saved settings. Its values are
stored archive values, rather than effective saved or live values. The paired
saved files and original archive remain unchanged. A separate published BACnet
File capture is not silently promoted to a complete native backup.

## Recognized edit contract

The byte compiler profile is `tagged-moi-wire-source-copy/1`; the local backup
review profile is `native-archive-wire-source-copy/1`. It changes only the source
member index of one existing four-Unsigned connection tuple in property 3118.
The source port, destination member and destination port remain identical.

An alternate source must:

- Already belong to the same fully framed diagram, with a typed native object ID
  agreeing with its record header.
- Have the same native class and ordered opaque property configuration as the
  recorded source. Identity, engineering reference, name and description are
  excluded from the signature. Only the value of an already recognized Real or
  Boolean Default Value 3113 is excluded; its datatype must still match. Other
  default structures and unknown properties compare by their encoded hashes.
- Already expose that exact source port in an observed outgoing connection in
  this diagram. No port is invented from its name or model.
- Execute before the existing destination and introduce no graph cycle when
  replacing the selected edge.
- Fit the original source-index Unsigned payload width. No record or tag growth,
  block identity allocation, connection allocation or execution reordering occurs.

The original archive, diagram record, wire property and exact old tuple must
match the request. After the fixed-width patch, the output is independently
parsed and its graph checked. Every expanded byte outside that source-index
payload must match, preserving IDs, references, native headers, memberships,
execution order, positions, unknown records and metadata. Ordinary gzip retains
its header with recomputed compression/checksum/length. A no-op returns the exact
original compressed bytes.

The token-admitted local API is under
`/api/bacnet/controller/native-application/inspection/wire-source`:

| Endpoint | Result |
| --- | --- |
| `POST /source` | Actual connections, eligible recorded candidates and source provenance |
| `POST /preview` | Deterministic compilation/preservation evidence, exact proposal and review seal |
| `POST /export` | Recomputed reviewed artifact with artifact, review and snapshot digest headers |

The closed request schema admits no network address, controller command or new
object allocation. Every response identifies local archive scope, unmerged saved
settings and disabled field transfer. The backup capability matrix profile 5
adds this as its sixteenth operation. A readable diagram without an eligible
alternate remains unsupported for an actual source change.

## Workspace ownership and verification

Connection and source drafts remain keyed to their original capture, manifest,
archive, diagram record and wire. Navigation preserves drafts. Source, record,
wire, proposal, target, interface, visibility and field-operation changes retire
pending reviews before paint. A delayed A→B→A reply cannot restore an older
review. Export checks the reviewed snapshot, review and output digests before
downloading. Errors leave the operator's original source and draft available.
The draft cache refuses new entries at 256 slots without evicting another edit;
discarding an older proposal or returning its selector to the first wire frees a
slot for an explicit retry.

Verification uses independently authored native frames, short/extended tags,
gzip, positions and unknown metadata; class/configuration, unobserved pin,
execution order, cycle, width, member identity and stale-source refusal cases;
strict local HTTP; and an authored UDP backup followed by disconnected local
copying. Actual retained native payloads are also transformed in memory without
saving program outputs, changing their containers or sending field requests.
Chromium/WebKit cover exact review/output downloads, drafts, source transitions,
delayed responses and substituted output bytes. Package checks include the new
compiler, API and built interface.

This is a scoped graph archive edit. It does not establish general native logic
generation, units or algorithm equivalence, saved-effective graph compilation,
resource/package/release compatibility, controller transfer, native execution,
CCT/PCT reopening, hardware reassignment or physical/BTCVT acceptance. JCI-02,
JCI-03 and JCI-09 remain partial overall. Each broader operation needs its own
contract and independent evidence.

**Saved effective snapshot** now selects a separate
[effective wire compiler](native-effective-wire-compiler.md). It merges and checks
the retained saved settings before the same scoped byte edit. The original
archive mode described above keeps its existing contract and does not merge
settings or prepare a field transfer.
