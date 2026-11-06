# Local previous-terminal proposals for configured binary inputs

`FMT-NATIVE-BINARY-TERMINAL-RECOVERY-001` adds the local API
`/api/bacnet/controller/native-application/input/binary-terminal/recovery/prepare`.
Its strict request contains a retained receipt ID, current capture ID and snapshot
hash. It derives a previous-terminal proposal from an original profile-3 binary
terminal transfer. Preparation performs no controller query, creates no field
plan and does not apply a change.

The original operation must have a resolved historically verified result or an
immutable verified readback, possible dispatch, all three confirmations and
complete native preservation. Original native files and saved settings must
reconstruct the canonical binary edit, compilation and payload hashes exactly.
Other input and recovery profiles cannot supply the original move.

The current retained capture must match the original controller, route, identity
and static directory. Its native application must match the recorded after image
or the original effective image. The selected binary input's reference, terminal,
non-counter configuration and optional-property presence must remain unchanged.
State texts, states-text index, optional polarity and encoded configuration remain
preserved. Current saved counter values and unrelated saved settings are retained;
counter values remain captured observations, not live readings or electrical
configuration. Changes to the raw native application outside the supported move
are refused, including native counter changes.

The inverse compiler preserves the recorded ASCII/UCS-2 terminal-label encoding
and moves only the selected existing input to its previous universal terminal.
The sealed report contains original/current lineage, verified proof, a canonical
proposed edit, inverse compilation/output hash and explicit read-only flags. An
already-recorded previous binding produces no inverse or proposal. Original
receipts and source files remain unchanged.

This delivery provides backend preparation only. It grants no field token,
parent-enforced transfer authority or automatic rollback. A separate parent-bound
field review and contextual web workflow remain next, including fresh source and
identity checks, all confirmations, one-use transfer and native/published readback.
Allocation, electrical/polarity edits, dedicated binary terminals, SA/cross-host
movement, general restore, packages/resources and physical/CCT/BTCVT acceptance
remain separate. IO-02/JCI-10 remain partial.

Verification uses authored complete-image expectations across ASCII/UCS-2,
compressed/native images, record and terminal widths, and optional field presence.
It covers current saved counter ticks and unrelated values, refused configuration
and native-image drift, already-recorded bindings, malformed or mixed profiles,
strict authenticated local HTTP, and retained evidence after restart. Owned local
UDP peers supply both verified original transfers and uncertain transfers followed
by verified readback. Preparation after those operations must leave the original
records, files and peer traffic unchanged. Earlier input, recovery and transfer
families remain in regression coverage; no private inventory is embedded.
