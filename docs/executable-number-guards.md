# Executable integer precision boundaries

Studio preserves source numbers independently of whether an execution profile can represent them. Programs, arbitrary metadata, archived native evidence, canonical hashes and previously saved revisions retain their existing bytes and hash rules. JSON authoring export remains available for a program whose numeric block parameters cannot execute.

Known numeric block defaults and parameters, including expanded macros, must be finite integers or floats. Before an integer enters executable arithmetic or a target numeric conversion, Studio checks that converting it to binary64 is finite and converts back to exactly the original integer. `9007199254740993` is refused; `2**53`, `2**53 + 2`, and exactly representable large powers of two remain valid. Booleans remain a separate type. Very large integers produce a normal validation error when float conversion overflows.

This guard applies to graph admission, live numeric inputs and forces, and each computed node value before scan publication. A refused scan retains its prior state, outputs, clock, history and force map. Scenario simulation, conformance and local runtime deployment use the same engine admission. A nonrepresentable integer source cannot first round through an Add block and then pass an acceptance check against the rounded value.

ST/PLCopen literals, Niagara native numeric conversion, and native IEC and Sedona input builders also guard before integer coercion or external exchange. Sedona source generation runs before native toolchain lookup or output-directory creation, so an invalid source cannot start a native build. Existing Temco fixed-point limits already exclude these large integer literals.

This is not arbitrary-precision execution or a claim that floating-point arithmetic is exact. Operations on valid floats can still round normally. IEC/Sedona binary32 and Temco fixed-point differences remain explicit target-profile limitations and still require independent target verification. Ordinary fractions such as `0.1` are not refused merely because binary32 represents them differently. Opaque metadata and native application payloads are not interpreted as executable graph constants.

## Literal formatting

The integer guard preserves the legacy 15-significant-digit formatter for archive regeneration. That formatter can change an otherwise valid binary64 value before the target's declared binary32 conversion. The separate [versioned source-generator feature](source-literal-profiles.md) now uses roundtrip literal text for new ST/PLCopen/Sedona artifacts and retains the original formatter for old imports. Original canonical hash rules remain unchanged. Neither feature claims lossless native arithmetic.

The IEC host's 17-digit request format roundtrips binary64 inputs; its nine-digit native response format reflects binary32 execution. No source formatter using six significant digits was found in the audited backend.

## Validation scope

Tests exercise real HTTP step/scenario/runtime/export requests, archival save/reopen/hash preservation, finite and overflowing integers, exact large integers, nested macros, atomic rejected scans, and native input/build refusal before external exchange. Literal generation has separate source-profile tests. These checks do not establish physical controller behavior, native JCI compilation, arbitrary native-source conversion, or universal numeric equivalence across manufacturers.

## Legacy archival imports

Untouched older ST, PLCopen, GraphML, Niagara BOG and Sedona bundles can still be inspected even when their embedded graph contains a newly refused integer. Import comparison creates a separate bounded, import-only source projection reproducing the legacy generator's integer coercion. It restores the exact original embedded graph before comparing complete source/structure bytes, or compares the expected Sedona source against its original kit identity and checksum manifest. The returned Program retains its original integer and canonical digest.

This path performs no Engine execution, compiler invocation or external exchange and exposes no request flag to bypass executable validation. The projection only visits known numeric block parameters and the existing bounded macro library; arbitrary native metadata is untouched. Modified source, graph structure, application XML and checksum failures remain rejected. Importing an archive does not make it executable: new simulation, compile and target export still refuse its nonrepresentable integer. JSON archival export remains available.

The archival fixtures are synthetic public examples generated with the exact published legacy backend. Sedona binary fixture members are authored opaque placeholders that are never compiled, loaded or executed; they verify source/manifest preservation, not binary validity or target acceptance.

Analog BACnet Real/Double command previews also validate the original integer before native wire coercion. Exactly representable integers remain eligible; Real's binary32 difference is still shown through distinct requested/wire values. Tests use owned loopback devices and verify refusal creates no plan or write packet. No site device was used.
