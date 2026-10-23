# Versioned numeric literal generation

New ST, PLCopen and Sedona source uses `studio-literals/2`. Integer text retains the original decimal integer after executable binary64 admission. Finite float text uses its roundtrip representation, including signed zero. IEC mantissas retain a fractional part, including exponent notation. Existing REAL32 range/underflow checks and integer admission remain in force.

This fixes a source-generation loss before target conversion. For example, the next binary64 value above `1 + 2**-24` should convert to binary32 bits `3f800001`. The legacy 15-significant-digit text fell below that midpoint and selected `3f800000`. Independent native MatIEC and Sedona compiler/runtime tests verify the intended new binary32 result. This is a literal conversion check, not physical-controller validation or a promise that all native arithmetic is exact.

## Profile identity and archives

Each affected artifact binds an explicit profile ID and exact rules SHA-256:

- `studio-literals/1`: `0a090b7203496dd0bd5c20756464e55a491a1be06c3b9647d42776dcc12a8222`.
- `studio-literals/2`: `be014ca51c1d3e42538d607d698b8ddacd164b2e0ddfb821c433329b99050493`.

These rules are frozen. A later semantic change needs a new profile identity while preserving older regeneration rules.

The numeric-profile generation introduced `BMS_STUDIO_IR_V2`, containing the profile binding and original Program. Legacy `IR_V1` retains its original generator. Current IEC exports use `IR_V3` with the same frozen numeric profile and a separate [private symbol profile](iec-symbol-namespace.md); V1/V2 retain exact old regeneration. PLCopen binds `sourceProfile` and `sourceProfileRules`; current IEC exports add separate symbol attributes. Sedona bundles continue using schema2 and a `source_generator` binding; schema1 retains the original kit/source rules. Duplicate, missing, conflicting or unknown markers and rules digests are refused. Sedona manifest parsing is bounded to64KiB and rejects duplicate/nonfinite JSON fields.

Legacy files are compared against their original source bytes. The import-only legacy numeric projection preserves previously generated lossy graphs for archival inspection while returning their untouched Program and digest. New execution and native export still refuse nonrepresentable integer parameters. Edited source, application XML, graph structure and checksum failures remain rejected. Import never executes uploaded binaries.

Program schema, canonical hashes, saved revisions, JSON authoring, GraphML, Niagara BOG and native evidence retain their existing formats. GraphML/BOG do not consume the changed literal formatter and receive no new profile marker.

## Native identity and provenance

New Sedona kit names derive from the profile identity, rules digest and original canonical Program. The legacy kit name remains the original Program-hash derivation. This prevents the two generator profiles from sharing a generated kit identity for the same graph. Generated Graph source, bundle manifests, compiler results and owned simulator reports identify their profile. The generated component remains in its existing path, so snapshot preservation and online native operations retain their current boundaries.

IEC profile, compilation and scan reports identify the new literal generator. Conversion review and native simulator/compiler screens show the ID and rules digest. Source/profile provenance establishes what was generated; native target ABI, physical I/O, firmware, JCI compilation and controller acceptance remain separate requirements.

## Validation scope

Tests cover exact float/int text above15digits, signed zero, unchanged Program hashes, frozen legacy archives, new exact source roundtrips, unknown/duplicate/conflicting profile rejection, source/manifest tampering, profile-bound kit names and actual local native midpoint execution. Browser checks inspect/download the current profile evidence. No field controller, Bluetooth interface or site credential is used.
