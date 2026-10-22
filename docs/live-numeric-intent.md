# Live numeric input intent

Numeric input edits retain their validated original JSON token until the local API receives them. `1e30` and `1.0` remain Python floats, `-0.0` keeps its float sign, and an exact integer such as `1152921504606846976` remains an integer. Integer token `-0` follows JSON/Python integer semantics and becomes integer zero. Booleans and quality strings retain their types.

The existing execution profile still requires finite binary64 values and refuses integer tokens that cannot be represented exactly. Decimal and exponent tokens use ordinary finite binary64 semantics; this is not arbitrary decimal precision. Native REAL/binary32 and Temco fixed-point limits remain separate and may produce a visible mismatch or refusal.

The token-preserving boundary covers portable simulation inputs/forces, timed stimulus JSON, IEC verifier inputs/scenarios, Temco verifier inputs, generated Sedona scan inputs, shared-group external inputs and link initial values. The local runtime uses the same admitted portable input map. The existing BACnet command parser and its separate exact request/receipt contract remain unchanged.

Force defaults use accepted last-scan values from the original response bytes, separately from display/chart history. Scenario final forces and reopened group external inputs/link initial values likewise reuse verified original tokens. Source and simulation epochs still retire stale replies. Group projection handles only declared signal-value paths; Program revisions, IDs, counts and unknown structural DTO fields retain their existing strict projection.

The shared strict JSON reader has unchanged Program limits (8 MiB, 200,000 values, depth 64). Execution receipt tail extraction has a separate 128 MiB/8,000,000-value/depth-64 bound and retains only the final history row's values and forces. Earlier rows are scanned and discarded. An extraction refusal after a proved receipt retains its owned calculation handle; Reset can retire it. No scans are automatically retried, and already committed scans are not rolled back. Unknown HTTP outcomes retain the existing bounded-expiry warning.

Tests independently parse actual browser request bytes in Python to check numeric type, exact integer value and signed zero. They cover genuine MatIEC, Temco and generated Sedona local execution, the unchanged IEC REAL overflow mismatch, group reopen, force defaults, runtime preview, oversized/deep receipt handling and late-reply cleanup. These are local software tests; physical controllers, native JCI execution and field transfer remain unverified.
