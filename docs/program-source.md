# Exact portable Program source

Opening a saved portable graph used to parse every JSON number as a JavaScript Number. Without editing, `1.0` became `1`, `-0.0` became `0`, and `9007199254740993` became `9007199254740992`. Python's existing canonical Program hash distinguishes those source values, so an unchanged project could lose its saved conformance-suite binding.

The editor now uses an explicit, bounded Program source codec. Ordinary integral browser projections serialize their actual represented integer using BigInt rather than the JavaScript shortest decimal; for example, an exact live value of 2**60 remains 1152921504606846976 on the wire. Opaque numeric leaves in `nodes[].params` and `metadata` retain their JSON numeric tokens, including nested macro libraries. The normal Python Program model, canonical hash algorithm, revision content, legacy hash formats, and default API responses stay unchanged. Existing stored revisions are not migrated or rewritten. Already rounded files or older recovery drafts cannot be reconstructed from their projected numbers.

## Source and browser projection

| Data | Editor representation |
| --- | --- |
| Numeric leaves in opaque parameters/metadata | Immutable `SourceNumber` tokens; exact integers, integral floats, signed zero and nested arrays/objects retained |
| Program schema/revision and typed integer target limits | Explicit safe JavaScript integer projection; unsupported structural integers are refused |
| Typed scan duration and node coordinates | Finite JavaScript floating-point projection matching the Python model's typed float fields; negative zero retained |
| Booleans, strings, null and identifiers | Original types; no numeric-string or Boolean coercion |
| DTO fields outside independent Program roots | Explicit finite numeric projection; unsafe integers refused |
| Native device evidence and sealed reports | Existing native response/byte-download paths; this codec does not reinterpret them |

A private enumerable Symbol marks an authoritative Program root and survives immutable object spreads. A source-aware clone preserves tokens across undo/redo, duplicate, copy/paste, node changes and array reorder. Ordinary `JSON.stringify` and numeric coercion of a source atom throw. An owned noncloneable guard also makes accidental `structuredClone` fail instead of flattening the class into an ordinary object. Unmarked graph-shaped request values are refused rather than assumed to be exact.

Deliberate numeric parameter edits create a new token even when the resulting JavaScript Number would compare equal: `1.0 → 1` and `-0.0 → 0` remain distinct edits. Numeric arrays and whole JSON parameter editors use the same strict parser. Incomplete or invalid replacements are displayed as unapplied; duplicate JSON keys are refused.

This preserves the Python model's numeric type, signed zero and integer value. It does not promise original file whitespace, key order or arbitrary floating-point literal spelling. Imports still use their existing Python model normalization; newly typed floating literals use the existing finite binary64 interpretation when parsed by Python. Archival retention is separate from executable numeric acceptance. The execution profile may refuse a retained integer before simulation, conversion or native compilation; retaining a graph is not proof it can execute on a target.

## Opt-in API transport

Program-producing endpoints accept `X-Studio-Program-Source: true`. Their versioned `bms.program-source-response/1` response contains exact `source_json`, its SHA256, independent Program paths/IDs/revision text, and the existing backend canonical hashes. The client checks byte consistency, complete descriptor coverage, identity and path before adoption. Embedded metadata is opaque and is not independently projected as another Program root.

Program requests replace each independently edited Program with a `bms.program-source/1` envelope containing exact JSON text, SHA256, Program ID and revision text. A Program model prevalidator checks those fields and parses the source before existing validation. Nested macro import and grouped simulation Program fields use that same model contract. Normal clients may continue sending ordinary Program JSON.

These hashes bind bytes and declared identity. They do not authenticate a sender or grant authorization. Session checks, native device restrictions and existing operation guards remain applicable. Original native and conformance report downloads retain authoritative HTTP bytes; the editor does not reseal or migrate them.

The supported source profile is at most 8 MiB UTF-8, 200000 values, 64 nesting levels and 4096 characters per numeric token. Duplicate keys, nonfinite floats, invalid Unicode and unsupported values are refused. Large bounded integer tokens can remain archival source without conversion to JavaScript Number. The full encoded request, including envelope escaping, must also fit the unchanged global 9 MiB request cap. Escaping overhead can reduce usable source below its separate 8 MiB limit; such a request is explicitly refused rather than normalized or truncated. Recovery uses the same source serializer through the existing lifecycle/write-failure guard.

## Audited workflows

| Workflow | Exact-source path |
| --- | --- |
| Project open/revision/save/import/export | Opt-in source responses, Program request envelope, existing server encoders and revision store |
| Templates and block defaults | Exact source response; typed graph projection and opaque parameter tokens |
| Equipment wizard | Existing normalized generator choices/hash contract, exact generated Program adoption and stale-source comparison |
| Macro create/inspect/update/instantiate/delete/import/export | Exact independent Program roots and opaque embedded library graphs; source-aware bundle parsing/serialization |
| Undo/redo, duplicate and cross-project clipboard | Token-preserving clone and stable node/subtree values; no numeric equality/index sidecar |
| Ordinary and nested macro recovery drafts | Shared source serializer/parser; existing ready/read-failure/storage-failure lifecycle policy |
| Validation, dependencies, conversion preview, runtime plan, simulation/scenario, conformance, IEC/Temco/native start/save | Exact Program request encoding; existing result/evidence handling |
| Group simulation start/demo/reopen/step/reset/import/trace | Exact independent Programs in workspace definitions; no automatic source normalization |

Local executable input/force/scenario text is parsed before Number conversion, so an unrepresentable JSON integer cannot silently become a rounded numeric input. Native controller command-intent editing is a separate feature and does not inherit this Program transport automatically.

## Verification

`tests/test_program_source.py` exercises source/model/hash bindings, strict bounds, default-response compatibility, project and conformance paths, nested macro envelopes, grouped definitions, and unchanged legacy revision bytes/hash. `web/tests/program-source-codec.mjs` exercises token/coercion/clone guards, source intent, reorder/copy, strict parsing, envelope identity/coverage and archival versus execution projection. Run it with Node 22: `node --experimental-strip-types --test web/tests/program-source-codec.mjs`.

Actual browser tests independently inspect downloaded files with Python. They cover unchanged saved conformance bindings, unrelated label/save/reload edits, intentional type/sign replacements, undo/duplicate, nested macro recovery and library/clipboard transfer, array/whole-JSON replacements, malformed edits and corrupt source responses. Existing wizard, recovery, macro, conversion, conformance, simulation and project workflows remain regression checks. This feature requires no field-network traffic and establishes no physical controller acceptance.
