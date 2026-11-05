# Native local terminal copies

`FMT-NATIVE-LOCAL-TERMINAL-COPY-001` moves one existing class-240 analog or
class-242 binary input between documented free universal terminals on the same
controller in a separate native file. This is a local authoring profile. It does
not change a connected controller or verify physical terminal behavior.

The existing native input allocation, electrical-mode, transfer and recovery
profiles remain unchanged. This profile does not acquire their field authority.
Contextual controls belong in the selected controller's Points & I/O workspace;
that interface is a separate delivery.

## Source and supported boundary

Both sources use immutable retained File 3/11/12 captures. The archive path edits
the original File 3 without merging saved values. The saved-effective path first
uses the existing identity-qualified vendor-5 parameter merger, then edits the
merged image. Captured saved values are historical and are not current live values.
Unknown saved schemas can prevent the effective path while leaving a readable
archive available for its independent local operation.

Controller/data-model pairs 60/60, 62/62 and 66/65 use the existing input format
boundary. Documented CV/VAV local capacity profiles and FX-PCG2611-0 supply the
terminal limit; actual input records supply occupancy. A published model capacity
alone does not prove an unused terminal or physical wiring suitability. Unknown
models, expansion roots, explicit host/device bindings, other input families and
unknown hardware records that could conceal occupancy are rejected.

Existing inputs must have consistent typed object identity, native header ID,
exact local parent reference, unique Slot and the corresponding `UI INn` label.
The VAV integral DPT is retained and fixed. SA/cross-host moves, dedicated binary
terminals, output terminals, new objects and electrical-mode changes are outside
this profile. Seven supplied CAF examples inform local binding terminology;
they are not a native File 3 corpus or physical acceptance evidence.

## Preservation and review

Only the existing Slot Unsigned payload and Device Type ASCII payload change.
Original tag and payload widths, record lengths and prefix widths are preserved.
All other expanded bytes remain exact, including object references, modes,
scaling, units, names, graph structure, continuation metadata, order and layout.
Compressed outputs retain the original minimal gzip header. An unchanged terminal
returns the exact original container. Every changed output is independently
reopened and checked against the proposed inventory and preserved bytes.

Source inspection returns exact record/property hashes and configured/free
terminal evidence. Preview requires the capture, snapshot, original source,
record, both terminal properties, previous slot and destination. Effective
preview also requires the merged source and selected merged record hashes.
Export recomputes the entire review and requires its exact SHA-256 seal.
Strict integer validation rejects Boolean, floating-point and string slots.

## HTTP contract

The original routes use `/api/bacnet/controller/native-application/inputs/terminal-copy`;
the effective routes use the same prefix with `effective-terminal-copy`.
Each has `POST /source`, `POST /preview` and `POST /export`. Session-token
validation applies to all six endpoints. Exports include artifact, review,
snapshot, source and compilation SHA-256 headers.

These routes do not open an interface, issue protocol queries, create a mutation
intent, create a field receipt, or enable Apply. They do not establish general
native compilation, controller package/resource qualification, CCT acceptance,
physical rewiring, or live deployment support. Review the separate transfer
profiles for the operations they independently qualify.

## Verification

Authored native fixtures check whole expanded images against independent literal
expected bytes for analog/binary inputs, compressed/plain containers, short/wide
record prefixes and one-to-four-byte Slot values. Additional cases cover supported
capacity/version boundaries, another root class, opaque diagram preservation,
occupied/fixed/unknown bindings, ambiguous identities, stale guards, independently
authored saved values, changed continuation refusal and HTTP exports with every
field/mutation entry point replaced by a failing sentinel. No live-site writes,
Bluetooth or CCT physical acceptance are part of this qualification.
