# Saved-effective native CV local I/O

This draft adds source inspection and a narrowly qualified API for allocating an
independent dry-contact input or moving an existing binary output to a spare BO
terminal. It discovers the actual records and preserves their unrelated bytes.
It does not choose a replacement application from a controller model or add a
new feature tile. A future UI belongs in the selected controller's Points & I/O
and Changes workflows.

## Source and scope

`native-saved-effective-local-io/1` accepts complete File 3/11/12 captures with
ACS/DMCS 66/65, vendor 5 and documented local CV terminal capacities. Factory
images can expose a placeholder Device 1 while their saved parameter directory
contains the assigned Device identity, name and model. The offline compiler
requires all three saved identity fields, CRC-valid ObjectIdentifier storage,
format agreement and an independently captured responding identity. It retains
the original files and produces a separate saved-effective image.

The offline compiler supports the documented M4/F4 CVM03050 and CVE03050 model
variants listed in the module. Capacity is supplementary hardware evidence; it
never supplies a point inventory. Physical SA expansion or ambiguous host maps
are rejected. Explicit network-only SA value maps are retained and checked for
unique local owners. Their remote AI references are not local terminal bindings.

Live review/apply is restricted to firmware `10.0.0.2125` with an already active,
operational **Custom Application** bank. The selector identity, value and indexed
custom-state label are independently read before review and apply. A factory
source remains offline-only in this profile. Switching banks can expose an older
custom application with a different identity; this API never switches banks or
resizes File 3. Additional firmware, model and factory-to-custom workflows need
separate qualification. No claim of universal controller support is made.

## Review and transfer

The route prefix is `/api/bacnet/controller/native-application/runtime-io`.

| Route | Behavior |
| --- | --- |
| `POST /source` | Compile a capture-bound local copy and preservation evidence; no controller reads or writes and no apply token. |
| `POST /preview` | Verify the exact route, identity, interface, custom bank, allocator/object presence and old output binding. Issue a one-use, 120-second review. |
| `POST /apply` | Consume the review; recheck credentials, interface, bank, identity and bindings; take a recoverable fresh original; reject changed configuration; journal intent before the first mutation; transfer File 3 once; independently verify. |
| `POST /readback` | Read and verify the retained receipt without replaying a transfer. |

A binary allocation supplies `action: allocate-binary`, an unused public object
instance, a spare local UI slot, a visible name and an optional description.
It creates a normal-polarity Off/On binary input, with no control-logic wires.
A binary output move supplies `action: binary-output-terminal`, the existing
object instance, its expected old slot and a spare destination BO slot. It
changes only the terminal label and slot and retains output setup and logic.
Both edits preserve all unrelated effective application records.

Fresh saved parameters are remerged before transfer. The configuration review
binds every effective property except separately typed binary runtime counters
and the finite Real airflow-autocalculated offset. Changes to other settings,
record membership, program, identity or wiring invalidate the review.

Apply requires strict `local_io_testing_confirmed` and
`application_transfer_confirmed` booleans. It uses the existing native operation
lock, bounded source-pinned BACnet requests, private credentials and original
archive storage. Only File 3 is written; saved-directory, firmware and boot Files
are not written. A timeout, cancellation or rejected transfer after dispatch
retains an uncertain receipt and blocks another mutation. A successful ACK alone
is not completion. Verification checks the full native image, saved parameters,
operational identity and independently published I/O properties.

## Validation and remaining work

Authored UDP peers test both edits, assigned/factory source identities, stale
settings, invalidated reviews, unsupported banks/firmware, typed absence,
capacity, wrong published I/O and readback without replay. Fixtures contain no
site captures or credentials. An authorized isolated CVM field trial verified an
OUT4-to-OUT1 fan binding and a new dry-contact input with an OFF/ON/OFF current
proof. That field result qualifies the exercised path, not every listed model.

This is API functionality. Integrated UI editing, direct factory-to-custom
conversion, removal/reallocation, alarm creation, an NAE mapper and fan-proving
control interlocks are not implemented by this slice. Existing controller and
NAE GUIDs, trend extensions and control links are not edited here. Native restore
acceptance is separate from physical commissioning and supervisory mapping.
