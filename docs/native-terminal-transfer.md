# Native analog terminal transfer

`FMT-NATIVE-INPUT-TERMINAL-TRANSFER-001` adds explicit operation profile
`native-local-universal-input-transfer/2` for moving one existing local analog
input to a configured free universal terminal on the same documented controller.
The existing allocation, electrical-mode and remove-app-allocated actions keep
their complete version-1 request/response shapes and operation profile.

This is a software-qualified native transfer extension. Controller/CCT physical
acceptance, actual rewiring, SA/cross-host/dedicated-BI moves, new allocation,
binary field transfer and general native compilation remain separate.

## Edit and compilation

The existing input endpoints accept `edit.action: "terminal"`, the existing
analog `object_instance`, destination `slot` and exact captured
`configuration_sha256`. Name, configuration and allocation receipt must remain
absent/null. The previous slot comes from the exact source; unchanged destinations
are rejected. This adds no serialized nullable fields to older actions.

The standard saved-value merger and parameter-addition qualification run first.
The terminal copier then changes only the existing Slot and Device Type payloads.
All other merged bytes, native identities, electrical mode, scaling, graph,
record lengths and prefix widths remain exact. Original/saved-effective local
archive-copy endpoints and their version-1 contracts remain unchanged.

An explicit inner `tagged-moi-local-terminal-copy/2` recognizes unchanged local
class-239 BO and class-241 AO records with consistent public/native identity,
exact local parent, Unsigned Slot and output-only `BO OUTn`, `AO OUTn` or
`CO OUTn` labels. Output slots belong to a separate namespace and do not consume
input slots. Every output byte is preserved. Input-looking, ambiguous, integral
output or explicit device/SA bindings stay blocked. The default inner version 1
continues its previous admission boundary. Class/attribute metadata and provided
CAF output labels inform this closed profile; authored native fixtures qualify
its encoding and preservation, not physical hardware behavior.

## Review, Apply and Verify

`POST /api/bacnet/controller/native-application/input/preview` requires the exact
controller route, interface and retained capture. It checks controller identity
and the currently published input configuration. Its response uses outer native
transfer profile 1 and explicit input operation profile 2. The compilation report
also identifies profile 2 and retains the inner two-payload proof.

Apply uses the existing `/input/apply` endpoint with a one-use token, exact review
SHA-256 and strict Boolean wiring, input-change and application-transfer
confirmations. Profile 2 requires the unchanged full review seal, exact typed
options and compiler profile. Old actions cannot inherit version 2, and a terminal
action cannot use version 1 in Apply or receipt verification.

The common transfer pipeline rechecks current identity, full application/static
source, selected published configuration, capacity, interface, expiry and
credentials before native restore. It retains a durable intent before dispatch.
Only File 3 is transferred. Verification checks operational status, complete native
image, fresh saved-setting preservation and the published input, including Device
Type 31 and Slot 519. Output bytes and all unrelated input settings stay exact.

An uncertain outcome retains its intent and blocks another transfer. Reusing a
consumed plan fails. Explicit `/readback` reconciles the original exact target
without reapplying its program. Native verification can issue start/end-backup
state commands; its existing backup-effects declaration and `read_only: false`
remain in place. It is not passive File copying or an automatic inverse operation.

## Local and interface scope

The existing `/input/copy/preview` and `/input/copy/export` endpoints can create
local profile-2 copies with the exact review seal. They issue no field query or
intent and cannot authorize Apply. Current terminal-copy UI remains a separate
local workflow; new profile-2 field controls and structured history presentation
are subsequent deliveries. Existing graphics, styles, input UI and all other
native operation profiles remain unchanged.

## Verification

Independent whole-image byte expectations cover saved values, compressed/plain
images, short/wide framing and padded Slot widths. Owned direct and routed UDP
peers cover native transfer/readback, unchanged output records, stale sources,
published configuration mismatch, capacity, exact review/version guards and all
operator confirmations. Wrong published bindings, a lost restore acknowledgement
and changed unrelated saved values cannot become verified results. Explicit
reconciliation and consumed-plan tests prove no automatic second download.
No live-site, VM or Bluetooth operations are used for these checks.
