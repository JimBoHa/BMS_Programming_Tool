# Saved-effective native CV local I/O

In **Points & I/O → Configure output points**, an engineer can add an independent
binary or proportional point or move an existing output to a compatible spare
terminal. The editor reads one selected controller application and displays its
actual source points and available destinations. Dry-contact input allocation
is also available through the existing runtime I/O API.

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
| `POST /output-sources` | List retained captures and output-transfer receipts for the selected device and route. |
| `POST /outputs` | Inspect a retained capture for compatible output points and spare terminals. |
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

## Configure an output point

1. Open the controller's **Points & I/O** tab and choose **Configure output points**.
   Inspect a saved capture or choose **Capture current application**. A fresh
   capture enters the controller's backup service and can interrupt processing.
2. Select an existing point with the required signal type. Select **Add independent
   point** to keep its original assignment and all of its logic. Enter the new
   point name and instance, then choose a free terminal. **Move existing point**
   keeps the selected point's identity and control logic and changes its terminal.
3. **Review local output edit** checks the retained application. **Review on
   controller** verifies the source assignment, controller identity and, for
   an addition, the allocator and the proposed object's absence. The operator
   verifies the connected load, signal type and restart window before Apply.
4. **Apply output change** retains the original application and independently
   reads the transferred image, settings and published point back. A new
   point must read zero or inactive, with a neutral default, healthy status
   and clear engineering priorities. Use **Review point command** to command
   an installed point and release the owned override afterward. Actuator travel,
   voltage and load operation require separate field evidence.
5. If a transfer outcome is uncertain, use **Recorded output transfers → Read
   back transfer**. To remove temporary points, release their commands and
   review the [retained application restore](native-application-restore.md).
   Inspect the current-versus-original comparison for intervening changes.

The new actions are `allocate-binary-output`, `allocate-proportional-output`
and `proportional-output-terminal`. An addition takes the existing
`template_instance`, its `expected_slot`, a new `object_instance`, `name`
and destination `slot`. Binary destinations are dedicated BO terminals 1–3.
Proportional destinations are configurable terminals 4–5. The source's
recorded two-state or percentage configuration supplies the electrical profile.
A new point starts without control-logic connections. Integral actuator pairs,
ambiguous slot ownership, occupied terminals and unqualified electrical profiles
are excluded. The new actions require `output_wiring_confirmed` at Apply.
[Johnson Controls CV termination diagrams](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/M4-CV-Series-VAV-Box-Controllers-Installation-Guide/K/15.0/Wiring/Termination-diagrams)

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
site captures or credentials. Authored peer tests do not establish physical
commissioning acceptance or qualify every listed model. Deployment-specific
wiring, field trials and commissioning records belong outside this repository.

The output editor is software-qualified using authored controller images and
a loopback BACnet peer. The tests cover binary and proportional commands,
priority release, uncertain readback and restoration of both original terminal
assignments. Supervisor mappings, field wiring and physical actuator feedback
have separate commissioning workflows.
