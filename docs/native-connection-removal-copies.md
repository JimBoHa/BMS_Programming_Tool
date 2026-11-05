# Native connection removal copies

`FMT-NATIVE-CONNECTION-REMOVAL-COPY-001` removes one exact recorded native
connection from a retained application. This is a local compiler and export
service. Its contextual Program interface is the following separately reviewed
`UI-NATIVE-CONNECTION-REMOVAL-001` slice.

## Supported operation

Select an observed connection in an eligible class 536 or 575 diagram. The
compiler removes that connection's four-value row from property 3118 and, when
present, its aligned Boolean/String continuation row from property 3384. It
retains empty arrays when removing the last connection. Existing block identities,
membership, execution order, layout, destination configuration and every other
expanded application byte remain unchanged. Short and wide record prefixes keep
their original width. Compressed applications retain their original gzip header;
their compressed stream and checksum are regenerated and independently parsed.

The destination becomes unwired. Preserving its recorded configuration does not
prove the controller's default, fallback or retained-value behavior. A graph
readback proves the compiled native structure, not its execution semantics.

Two separate sources are supported:

- **Original archive:** remove the connection from retained File 3 without
  incorporating saved File 11/12 settings.
- **Saved-effective application:** first run the existing identity-qualified
  File 3/11/12 merge, then remove the connection. Graph membership, connections,
  order, layout and continuation metadata must survive that merge. Retained saved
  settings are captured configuration, not current live measurements.

Both sources remain immutable. Source, record, connection-property and optional
continuation hashes, connection index/count and all four original native values
must match. Effective compilation additionally checks the merged application and
record hashes. Malformed or unsupported native structures are refused without
widening the existing readers' limits.

## Local API

The existing authenticated/session-protected inspection router exposes two
families under `/api/bacnet/controller/native-application/inspection`:

| Family | Operations |
| --- | --- |
| `connection-removal-copy` | `source`, `preview`, `export` |
| `effective-connection-removal-copy` | `source`, `preview`, `export` |

`source` inspects the exact retained snapshot and selected connection. `preview`
recompiles the proposed local copy and returns sealed source/compiler evidence.
`export` recomputes that result and requires the exact review hash before
returning the native file. Artifact, review, snapshot, original-source and
compilation hashes accompany the binary response. Strict request models reject
unknown fields, Boolean integers and stale or substituted selections.

Archive, effective and low-level compiler profiles are separately versioned.
Existing connection-copy, transfer and capability profile contracts are unchanged.
Every new response explicitly withholds controller-write, Apply and field-transfer
authority. No interface is opened, target queried, native intent created or
controller operation dispatched by these endpoints.

## Verification and remaining work

Authored native records exercise literal whole-application output comparisons,
both framing widths, compressed/uncompressed containers, both diagram classes,
metadata order and absence, selected first/middle/last rows and final-row removal.
Saved-effective cases independently assert retained Real and Boolean settings.
HTTP tests use actual retained snapshots and session admission, check export
bytes and seals, and fail if a controller path or durable native intent is used.

The contextual Program editor follows in `UI-NATIVE-CONNECTION-REMOVAL-001`.
Native controller transfer, inverse/recovery authorization, arbitrary new blocks
or I/O, resource/package/runtime validation, CCT compatibility and physical/BTCVT
acceptance remain separate work. JCI-03 and JCI-09 remain partial overall.
