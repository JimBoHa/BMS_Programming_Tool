# Effective native existing-wire source compilation

In **Program → Native backup defaults**, select a retained backup, inspect its
records and open an actual activity/control-sequence record. In its wire editor,
set **Native wire source basis** to **Saved effective snapshot**, then **Open
saved wire sources**. Choose the existing connection and an observed eligible
source, **Review effective wire compilation**, then **Save compiled native
wire**. Saving creates a separate local file and never contacts a controller.
The original archive-copy mode remains a separate operation.

This profile (`native-effective-wire-source-compiler/1`) uses the retained native
Files 3/11/12 and their manifest, rather than current controller values. It checks
all three file hashes, recorded vendor-5 identity qualification and the actual
archive's Device/name/model. Known saved selectors, complete storage coverage,
datatypes and checksums must pass the existing parameter merger. Unknown schemas
or an unverified acquisition refuse effective compilation, while leaving original
archive inspection and copying available.

The merge must retain the original controller identity, engineering references,
native object headers, typed object IDs and record membership. For every actual
activity/control sequence it must also preserve the encoded block membership,
connections, execution order and positions. Saved changes to those graph fields
are refused, even if a reader could recognize the resulting graph. Other saved
application parameters, including numeric and Boolean defaults, are merged.
Unmatched non-application slots stay in the original backup; the exported program
does not invent or separately deploy those slots.

The existing [wire source byte compiler](native-wire-source-copies.md) then works
on that effective snapshot. Its source/class/configuration, observed pin,
execution-order, cycle and original-width rules remain intact. No graph member,
wire or I/O object is allocated. After the single source-index patch, an
independent native parse must confirm the intended connection and preserve every
other expanded byte of the **merged** application. A no-op wire proposal returns
the merged snapshot; other saved values may therefore differ from the original
archive. This distinction appears in the review.

## Source and review contracts

The closed, token-admitted API is under
`/api/bacnet/controller/native-application/inspection/effective-wire-source`:

| Endpoint | Contract |
| --- | --- |
| `POST /source` | Original capture/manifest/archive/diagram guards; actual effective connections/candidates, saved-merge evidence and original connection |
| `POST /preview` | Additionally guard effective source and diagram hashes, wire property, original tuple and proposed existing source; return exact compilation/review evidence |
| `POST /export` | Recompute the entire review and require its seal; return bytes with artifact/review/snapshot digests |

Original and effective diagram hashes are separate. For example, a saved sequence
name can change the effective record hash without changing its membership or
wires. The original record hash still binds the selected archive, and the
effective record hash binds the actual edit. Retained acquisition qualification
does not verify the currently connected controller. Results explicitly retain
`current_identity_verified: false`, disabled field transfer and no controller
queries or write. Captured serial/routed provenance does not require opening that
transport for a local compile.

The editor preserves independent archive/effective proposals and connection
selections within their original source and graph. The selected basis and draft
survive task navigation. Source, record, mode, wire, proposal, target, interface,
visibility and field-operation changes retire reviews before paint. Delayed
A→B→A replies and exports cannot restore an earlier review or download. Original
JSON is exported without reserialization; compiled bytes must match all reviewed
digests. The bounded draft cache retains existing edits when full.

The native-backup operation matrix profile 6 adds a separate seventeenth operation
for this compiler. It inspects actual effective candidates and keeps archive-copy,
saved-effective compilation and field-transfer qualification distinct. It does not
promote an arbitrary readable graph, successful saved merge or open interface to
a supported edit or transfer.

## Verification and limits

Checks use literal native graph frames, plain/gzip and short/extended record
framing, numeric/Boolean saved slots, unreferenced storage, original/effective
record hashes and a native UDP backup followed by disconnected compilation.
They cover all retained file hashes, CRC/schema/identity/reference/object and
graph-structure refusals, changed source configuration, no-op merge behavior and
independence from standard Real signal fields. Earlier archive-mode reports and
artifact hashes remain unchanged. Browser checks cover both modes, navigation,
serial-recorded snapshots, original evidence, exact merged downloads and
altered/delayed responses. Installed-wheel checks verify the actual packaged API,
compiler, public metadata and built interface.

This completes one local compilation operation. Current live-setting checks,
controller review/restore/readback, full-program authoring, allocation, package/
release/resources, native runtime behavior, CCT/PCT reopening and physical/BTCVT
acceptance remain separate. JCI-02, JCI-03 and JCI-09 remain partial overall.
