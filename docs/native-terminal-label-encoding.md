# Encoding-preserving native terminal copies

`FMT-NATIVE-TERMINAL-LABELS-001` adds explicit local terminal-copy profile
`tagged-moi-local-terminal-copy/3`. It preserves the recorded Device Type
CharacterString encoding, admitting ASCII (0) and UCS-2 (4) terminal labels.
Retained VMA archives use encoding 4; this delivery removes the older ASCII-only
admission barrier without changing the version-1/version-2 compiler contracts.

Only the existing Slot Unsigned payload and Device Type string payload change.
The charset byte, tag framing, payload widths, other expanded bytes, native
identity, graph, state labels, modes, saved values and record order stay intact.
Independent native readback checks the resulting inventory. An unchanged terminal
returns the original container; changed gzip files retain their original header.
The explicit output namespace from profile 2 remains separate from input slots.

The source still requires qualified format/model capacity and actual, unique,
direct-parent input records. No configured/free terminal list is embedded from
a site scan. Unknown encodings, SA/IOM/other input families, explicit device-host
bindings, dedicated binary terminals and ambiguous output bindings are rejected.
The integral DPT remains fixed. Encoding 3 and Latin-1 encoding 5 are not admitted
merely because another operation supports those string encodings.

## Retained sources and HTTP

The explicit archive envelope is `native-archive-local-terminal-copy/2` and the
explicit effective envelope is `native-effective-local-terminal-copy/2`.
New routes are under
`/api/bacnet/controller/native-application/inputs/encoded-labels`, with
`/terminal-copy/{source,preview,export}` and
`/effective-terminal-copy/{source,preview,export}`. The existing routes and
their envelope/compiler versions remain independently available.

The effective path retains the existing identity-qualified File 3/11/12 merge,
record/object preservation and graph-continuation check. Source, snapshot,
original/effective record, both terminal properties and the complete sealed
review bind exports. The same strict models, session protection and five artifact,
review, snapshot, source and compilation hash headers apply to the new routes.
New movable inventory rows and compiler proofs identify the recorded encoding.

This backend delivery does not switch the existing interface to the new routes.
Contextual controls and source-specific capability reporting require separate
delivery. No field compiler, review, writer, recovery helper or ledger gains the
new profile's authority. Local preparation does not send a file to a controller,
create a field intent or receipt, or establish wiring/electrical/CCT acceptance.

## Verification

Authored fixtures include the observed class-242 binary schema: Active Text,
Inactive Text, Description, States Text and optional Polarity/counters. They do
not invent analog scaling fields for a binary input. Literal independent whole
images cover analog/binary records, ASCII/UCS-2, plain/gzip containers, short/wide
record prefixes and one-to-four-byte Slot values. Separate output occupancy,
unsupported charsets, saved settings and strict immutable HTTP exports are checked.
Field and mutation entry points are replaced by failing sentinels for local APIs.

Read-only supplemental checks use retained captures outside the repository; no
site source, program names or controller bytes belong in this feature. These
checks qualify a local byte-preserving operation, not live operation or full
binary field transfer. Broader binary configuration/runtime semantics, SA/host
reassignment, resources/packages and physical/CCT/BTCVT acceptance remain open.
