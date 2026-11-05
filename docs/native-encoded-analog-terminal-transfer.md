# Encoding-preserving analog terminal transfer backend

`FMT-NATIVE-ENCODED-ANALOG-TERMINAL-001` adds explicit native input action
`encoded-terminal` and operation profile 4. Original input actions and transfer
profiles 1–3 retain their behavior. The new source API is
`/api/bacnet/controller/native-application/input/encoded-terminal/source`.
It binds the captured Device/vendor/name/model to the actual native image.

The compiler moves one existing local universal analog input to a recorded free
universal terminal on the same controller. It uses local terminal-copy compiler
profile 3 to preserve observed ASCII/UCS-2 labels and the existing separate output
namespace. Only the Slot and label payloads change; other merged bytes, identities,
configuration, graph and record framing stay intact. It performs no allocation,
mode/scaling edit, SA/IOM/cross-host move or general native compilation.

A separate typed analog configuration profile requires recorded Enum and finite
Real32 fields. Both linear output endpoints may be absent together, as observed
in retained VMA inputs; they remain absent and appear as null in recorded values.
Every present field keeps its exact native type/value. Missing mandatory fields,
one-sided endpoints, unsupported types and nonfinite values cannot qualify a move.
Saved settings that would undo the destination binding prevent compilation.

The existing field writer retains current interface/target/identity, published
preflight, source/static-directory, fresh saved-merge, complete image and separately
published property checks. Exact operation/action/compiler pairing, canonical
review/options binding and the sealed inner copy prevent downgrade/substitution.
All three confirmations and a one-use unexpired review remain required. Unknown
outcomes retain durable evidence and reconcile by reading without replay. Apply
transfers File 3 and may restart control; physical suitability/wiring and CCT
acceptance remain separate.

Verification uses independent literal whole-image expectations, typed/absent
configuration, malformed evidence, local API/export checks and authored direct/
routed UDP peers. It covers full published/saved readback, confirmations, review
substitution, lost acknowledgements and no replay. Private retained VMA sources
also compile with UCS-2 labels and absent output endpoints while all other expanded
bytes and saved configuration remain unchanged. No site data enters the code.

This delivery is backend support. Next, expose the explicit profile in contextual
Points & I/O, then add source-specific capability, recorded evidence and recovery
support. Existing GUI defaults remain available. Broader host/Device Reference,
allocation/electrical changes, resources/packages and physical/BTCVT acceptance
remain separate; IO-02/JCI-09 remain partial.
