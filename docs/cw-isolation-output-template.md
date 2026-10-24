# Authored CW isolation/pump output activity

This template creates one reusable version2 activity with a logical on/off output
and a percent command. Both outputs share the same ordinary control graph and
one retained Delay. It ramps toward an enabled command, selects zero immediately
on a **committed** disable, and restarts a later enable from zero.

It is an authored Studio sequence informed by Controller Tool Help18.0. It does
not reproduce a native JCI CW Iso Valve block, vendor Off/On Enum codes,
reliability rules, CAF/packages, controller compilation/download or physical
pump/valve protection. The source manual's G36 application-tree placement does
not establish G36, Title24 or plant acceptance.

## Inputs, outputs and fixed choices

The definition has two required inputs:

| Port | Type/unit | Default | Meaning |
|---|---|---|---|
| `device_enable` | Boolean | false | Logical request to enable the device output. |
| `command` | number, `%` | 0 | Requested percent, clamped to0..100 for good finite samples. |

It publishes exactly two named ports:

| Port | Type/unit | Meaning |
|---|---|---|
| `device_on_off` | Boolean | Authored logical enable proxy; not flow/run proof or native Enum encoding. |
| `effective_command` | number, `%` | Current selected percent after the fixed-scan ramp/disable rule. |

Choose `minimum_command` m from0 through100%, `stroke_seconds` T from1 through
86400 whole seconds, and `scan_seconds` h from1 through60 whole seconds. Require
T>=h and T%h=0. Defaults are m=0,T=60,h=1. These bounds and resolution are
authored choices; the cited manual supplies defaults but does not define these
limits. T=h permits a one-scan full stroke.

Minimum is a typed float. A JSON integer may deliberately become a float during
DTO validation, while `-0.0` remains signed in reviewed choices, definition
constants and original exports. Duration/scan choices reject Boolean values and
floating representations. Parent Program schema validation remains unchanged;
typed parent scan1.0 and choice1 compare equal without changing the supplied
editor object. Opaque parent parameter/metadata numeric atoms retain their
existing source representation.

## Authored ramp and restart rule

Let q be the previous committed effective command, initially zero. Compute:

```text
target    = max(minimum, clamp(command, 0, 100))
step      = 100 * h / T
candidate = q + clamp(target - q, -step, +step)
effective = device_enable ? candidate : 0
on_off    = device_enable
q_next    = effective
```

Step is a fixed percentage-point increment per declared scan. Both increasing and
decreasing targets use the same rate while enabled. Minimum is an **enabled
target floor**, not an instantaneous output floor: a ramp transient may remain
below the configured minimum. This avoids inventing a step to a minimum speed
whose physical acceptability is unknown. With m=0 and command0, on/off can be true
while percent is zero; it does not prove a pump is operating.

A committed false enable selects false/zero in that scan without a gradual
downramp and commits q=0. A later true enable starts a fresh ramp from zero.
Fresh engines/sessions also start from zero; source reload does not restore a
physical actuator's position or running state. These initial, disabled and
restart policies are explicitly authored because the source pages do not define
them.

For m=20,T=4,h=1, step is25 percentage points:

| Scan end | Enable | Command | Previous q | Target | Effective | On/off |
|---|---|---|---|---|---|---|
|1s|false|100|0|100|0|false|
|2s|true|100|0|100|25|true|
|3s|true|100|25|100|50|true|
|4s|true|100|50|100|75|true|
|5s|true|10|75|20|50|true|
|6s|true|10|50|20|25|true|
|7s|true|10|25|20|20|true|
|8s|false|100|20|100|0|false|
|9s|true|80|0|80|25|true|

Full stroke is a nominal0→100 rate of100/T percent per second. Existing
binary64/REAL/fixed-point rounding can change a last tiny increment or the first
exact-equality scan. The template promises no universal cross-width trajectory,
exact physical stroke-completion time or expanded numeric tolerance.

## Ordinary graph and complete-scan quality

The definition contains13 nodes and14 edges: two Inputs; minimum/zero Constants;
command Clamp; target Max; previous-command Delay; target-minus-previous Subtract;
fixed-step Clamp; candidate Add; enabled/zero Switch; and two Outputs. Switch
feeds Delay directly. Delay publishes its previous committed value and stores the
current selected command only when the complete scan succeeds.

No new engine block, dynamic-dt introspection, opaque vendor runtime, duplicated
state per output or extra feedback memory is added. The existing activity2
lowerer creates one shared instance graph with independently typed named aliases.
Different instances retain independent state.

The existing whole-scan policy governs both outputs and q. Bad quality, invalid
types or arithmetic faults retain the entire previous committed time, state and
outputs, possibly true on/off and a positive percent. A bad command sample with a
false enable is **not a committed disable** and is not a physical shutdown.
A first failed scan does not establish published zero/false outputs. Good finite
out-of-range commands are clamped; fixed invalid configuration rejects before
generation rather than introducing a new fault latch.

Here the public Output aliases are terminal: the internal selected command,
rather than an Output alias, feeds Delay. Portable forcing of the published
percent therefore does not overwrite internal q; releasing it reveals the
continued ramp. This is a property of this graph, not a universal activity
isolation rule. Native internal-port forcing and field overrides are not added.

## Parent source and reviewed import

The parent must already declare an exact-integer version2 activity library.
Version1 projects require the existing deliberate migration; this template never
silently changes their format. Parent source must be a valid Program document,
but ordinary unwired draft blocks remain allowed. Existing library and generated
definition admission use unchanged activity2 validation/import rules.

Preview, original review/bundle export and narrow import require the current
parent declared scan to equal h. An outer `parent_reference` contains its
identifier, revision, clock and canonical source digest. Parent-specific data is
excluded from the reusable definition. Profile and choices determine a stable
definition ID, so reviewing the same choices after import produces the same
definition/Program/archive hashes while binding the new parent source.

Reviewed import checks the supplied profile hash and current validated parent
digest/clock, regenerates the activity and delegates to unchanged activity2
import. Identical same-ID source imports idempotently; an edited same-ID
definition refuses without overwrite. The guard is stateless provenance and
stale-payload admission, not stored server review, compare-and-swap, a signature,
physical identity or deployment permission.

Generic archive imports, later definition/parent clock edits and per-step dt
overrides may leave the recorded fixed-scan qualification. There is no new global
runtime gate. Historical template metadata does not certify a later edited graph
or enforce its scheduling. Source/profile/choice changes must retire pending
reviews and original download authority before adoption.

## API and original artifacts

The narrow prefix is `/api/activities/templates/cw-iso-output`:

- `GET /catalog`: source/profile, default choices, DTO schemas and scope flags.
- Authenticated `POST /preview`: current parent and choices.
- Authenticated `POST /export`: the same plus `format:review|bundle`.
- Authenticated `POST /import`: current parent/choices, profile hash and reviewed
  parent digest; returns the updated editable parent through existing source
  transport.

The preview format is `bms.cw-iso-output-template-preview` version1 and carries
the separate `studio-cw-iso-output-template/1` profile. It includes choices,
parent reference, definition/Program/archive hashes, required input and named
output manifests, diagnostics and explicit false native-compile/controller-write
flags. The original generated Program appears at `program` and in the version2
archive at `bundle.library.definitions[0].program`; both exact Program source
descriptors are retained by the existing opt-in source transport.

Original review and archive downloads are canonical JSON with `X-File-SHA256`.
They are separate from display formatting. Imported hierarchy remains editable
through activity2 inspect/update, named handles, portable simulation/forces,
deliberate revision saves and current JSON/STV3/PLCopen/GraphML exchange.
Authoring does not create an instance, wire a parent, save a project, acquire a
power request or open field networking automatically.

Current source/draft/clock/mount ownership must be checked before adopting an
import or saving an original response Blob. Hashes are server-reported canonical
provenance, not independently regenerated Python seals or authenticated targets
in the browser. Parent metadata and generated Program numeric atoms must not be
blanket-projected into ordinary JavaScript numbers during these checks.

## Source criteria and remaining limits

Controller Tool Help18.0, LIT-12011147, dated2025-10-06, original PDF SHA256
`68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`,
PDF905–906/Tables571–572 identifies separate OnOff/Effective Command roles,
enabled ramping, an unramped disabled transition, Minimum Command default0% and
Stroke Time default60s. See
[Controller Tool Help](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0).

Those pages do not define a numerical ramp, enabled-direction policy, transient
minimum behavior, disabled analog value, midstroke/restart state, configuration
limits/rounding or native Enum/reliability mapping. The authored choices above
remain visible. Neighboring dedicated-pump/stager proofs, sequencing, stroke
timers and ramp-down rules are separate and are not copied into this graph.

Local hand-calculated and host IEC trajectories test this authored sequence,
typed source, shared state, disable/restart and rollback. They do not verify
actual valve/pump position, minimum speed/flow, mechanical stroke, plant/stager
coordination, native JCI algorithms/CAF/package/transfer, physical protection or
G36/Title24 acceptance. Existing SDK/compiler flags, numeric/symbol/source
profiles and target admission limits remain unchanged.


## Web workflow

Open **Macros** in a version 2 activity editor and use the **CW isolation output
template** card. A legacy version 1 library first requires the separate explicit
activity migration; opening this card never upgrades or rewrites a legacy library.

Enter the minimum target command, full-stroke seconds and declared scan seconds.
The minimum field retains its draft spelling, including `-0.0` and scientific
notation. A fresh integer-form minimum is deliberately sent as a typed float
(`-0` becomes `-0.0`); existing Program parameters and opaque metadata are not
projected through JavaScript Numbers. Stroke and scan must be aligned whole
seconds and scan must equal the parent declaration. Changing the declaration,
parent source or criteria retires the earlier review.

**Preview CW isolation output** displays the 13-node/14-wire graph, both required
inputs, both named typed outputs, source qualifications and parent/definition
digests. It adds no instance, saves no revision and opens no field connection.
The initial preview response, canonical review export and canonical activity
bundle are separate original byte downloads. Export checks the actual byte hash
and delivery header; the bundle must also match the reviewed archive digest and
source tree. Digests bind server-produced source evidence, not manufacturer
authentication or physical compatibility.

**Import reviewed CW isolation definition** asks for deliberate confirmation and
uses the source/profile/clock-checked import endpoint. The client also fences the
current source epoch, mounted view, activity criteria authority and reviewed new
definition before adoption. The backend revalidates the exact supplied canonical
parent and preserves existing source through the activity merge. Client guards
do not claim arbitrary exponent-spelling identity or emulate Python canonical
number formatting. A refused source conflict leaves the current editor intact;
no existing definition is silently replaced.

After import, select the definition and use the existing **Add activity instance
to program** action. Wire both required inputs and the separate Boolean and
percent output handles. Normal activity inspection, definition editing, portable
simulation, revision saves and interchange remain separate deliberate actions.
A portable force on this template's terminal output changes that published
alias, while the internal selected command continues to drive Delay memory.
Editing the definition, changing its parent clock or overriding dt can leave the
recorded fixed-scan qualification; the template introduces no global runtime
gate or native controller force mechanism.

The card explains that minimum is a target floor rather than an immediate output
floor, and logical on/off is not position, flow or pump-running proof. A scan
fault can retain a positive previous command even with a requested disable.
Use the existing simulation quality controls to examine that transaction
behavior; it does not establish a physical shutdown path. Pending responses can
be discarded, and changed source, unmounted views or retired activity criteria
cannot authorize a late import or download.
