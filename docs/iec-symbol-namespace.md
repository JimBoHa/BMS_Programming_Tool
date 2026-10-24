# Private IEC identifiers and original graph identity

Current IEC Structured Text, PLCopen and native-host compilation allocate a separate private symbol namespace. Portable node IDs, project metadata, revision and digest stay unchanged. This fixes real collisions between graph IDs and generated variables, including an Input named `zone_temperature` and an Output named `zone_temperature_valid`. The old input-validity variable and that output previously produced duplicate IEC declarations. Renaming a single application output is not a general solution.

The fixed policy is `studio-iec-symbols/1`, with rules SHA-256 `f4ba350fc5d86fb33d7bbb8c7a9522a30713f4f3d8c98f6e9f4ca298e92d3666`. It is separate from the unchanged `studio-literals/1` and `/2` numeric profiles. The source formatter, arithmetic statements, scan transaction, compiler/SDK, zero initialization, limits, flags, deadlines and comparison tolerances are unchanged.

## Allocation and bindings

The allocator expands macros, validates the graph and sorts complete original expanded IDs using Python Unicode code-point ordering. It applies no case folding, sanitization or Unicode normalization to logical IDs. Each ID receives a fixed-width indexed private stem ending in digits. A private copy rewrites only executable node IDs and edge endpoints before using the original control-expression emitter. Sorted indexed stems preserve its existing execution and tie order. The lowered copy is never saved as a project or embedded in an interchange archive.

All node values, staged outputs, input-validity variables, hosted calendar values/validity and retained/calculation helpers have explicit typed roles. These include Delay/Deadband/Slew memory, PI integral/candidate/error/raw and TimerOn/Alarm elapsed/next. The complete declaration table, including fixed host globals, must be unique under case folding and must match the allocator's typed roles. Short private names avoid dependence on long or reserved-looking original IDs. Case-only and hyphen/underscore distinctions are preserved.

The native host consumes that same role table for inputs, quality, calendars, outputs and retained state. It never guesses a field from a sanitized original name. Output JSON keys remain original logical Output IDs. Retained-state JSON labels use `n_` plus the original expanded ID plus the state-role suffix. Existing underscore-only labels remain unchanged; case, hyphens and Unicode stay distinct. Generic allocator/low-level host Unicode checks do not widen the existing serialized HTTP/IR identifier validators.

`GET /api/iec/status` identifies the separate `symbol_generator`. Compilation, verification and scenario reports contain one `symbol_table` with the profile, content SHA-256, fixed globals, original/private IDs and typed role bindings. Full tables and symbol profiles are not repeated in every scan frame. The mapping hash establishes deterministic content consistency, not manufacturer authentication or physical I/O allocation. Source, Program and table identities remain separate evidence.

## Current and legacy source

New default ST uses `BMS_STUDIO_IR_V3`. Its bounded strict document contains exactly the original Program, existing numeric `source_generator` and separate `symbol_generator`. New PLCopen adds `iecSymbols` and `iecSymbolsRules` beside the existing numeric profile attributes. Both readers regenerate and compare the complete source against the original graph and the declared rules. Edited names/body/declarations, unknown or wrong rules, mixed/duplicate/extra markers and oversized documents are refused. There is no fallback to another decoder after a marker mismatch and no silent profile upgrade or reseal.

Legacy ST V1 and V2 and their corresponding PLCopen attribute sets retain their original byte regeneration. An old source file reopens its unchanged portable graph. A later new native compilation uses current private names; it does not rewrite or claim execution of that old source file. Importing a legacy numeric archive does not grant executable admission to a nonrepresentable integer. Existing source byte limits remain in force.

Sedona consumes the older shared statement emitter and reflected slot names. Its code, kit names, numeric profile, importer and host binding modules stay byte-identical in this IEC change. Its own arbitrary-name/slot allocation remains separate work. Global numeric source-document readers are not widened; JSON, GraphML, Niagara, Temco and saved project identities remain unchanged. The private IEC mapping is not an unrestricted foreign-language converter or native JCI allocator.

## Verification and limits

Independent clean source32 goldens preserve V1/V2 ST, PLCopen, Sedona and application bytes for numeric, retained-state/calendar and nested-macro programs. Existing published legacy numeric archives remain unchanged. Candidate archive checks forbid Engine execution and native compiler calls. The original statement emitter's AST and both numeric profile rules are frozen.

New local checks cover every derived role, complete declaration uniqueness, deterministic mapping and tie order, maximum-length/case/hyphen/Unicode distinctions, original Program preservation, strict V3/PLCopen imports and authenticated export/status APIs. Actual pinned MatIEC/Clang workers execute formerly colliding numeric/Boolean graphs, all retained state types, hosted calendars, nested macros and the original series-fan graph before its diagnostic rename. Original generated Program/ST/C/host/executable files, decoded worker observations and mapping evidence are retained privately. Bad-quality scans retain the complete prior outputs/state and successful-scan counter; worker cleanup is checked.

The related source/compiler suite retains original failures when older tests expected default V2 markers or public compiler variable spellings. Those test oracles are updated to the explicit new version and allocated role names; separate frozen V1/V2 checks continue to require exact old bytes. Source generation/host execution does not establish physical PLC, native CAF/JCI, Bluetooth, controller transfer or code compliance acceptance. Compiler warnings, REAL/binary64 differences and all existing runtime limits remain visible.

## Web workflow

The IEC verifier displays the symbol profile and its rules digest separately from the numeric literal profile. After compilation or verification, a read-only table maps each original expanded graph identifier and typed role to its private IEC name. At most 200 roles are displayed; the full table remains in the original compilation response or full verification trace download. Retained-state labels remain separate from private compiler names.

Download compilation evidence retains the original HTTP response Blob, including source, generated C, program identity and allocation evidence. The existing Structured Text/C downloads remain available. Verification trace downloads continue to retain their original response bytes. Changing the loaded program retires previous compilation and verification results. Conversion review shows symbol provenance only for IEC ST/PLCopen; the separately versioned Sedona contract remains unchanged.
