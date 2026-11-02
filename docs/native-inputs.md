# Native local input allocation and electrical modes

Open a verified controller → **Points & I/O** → **Configure native inputs**.
Capture its native application, select a spare local terminal or an existing
configured input, edit the electrical range and engineering scaling, then choose
**Review controller input change**. Confirm the actual wiring and application
transfer before Apply. The result includes complete application preservation and
independent published-property readback. This adds no workspace destination.

## Source and offline work

**Capture native inputs** uses the existing original File 3/11/12 backup workflow,
including Start/End Backup state services. It is not a purely read-only capture.
**Retained native source** opens an immutable original backup without a network
query. Its controller identity, route and format remain visible.

**Review local input copy** and **Save native copy** work without a field
connection. They produce a separate native MOI application, not a CAF or a whole
controller backup. The original capture remains unchanged. A local copy review
has no controller token or transfer authority. Export regenerates the same
source-pinned compilation and requires its exact reviewed digest.

Unfinished input drafts survive task navigation for their exact controller route
and interface. Up to 32 controller drafts can be retained without eviction; the
operator must save/discard earlier work at capacity. Discard affects the local
draft, not original captures or durable transfer receipts. Field reviews and
confirmations retire on edits, target/interface changes, navigation and visibility
changes. A late reply cannot restore their authority.

## Qualified profile

`native-local-universal-input-transfer/1` reads actual configured native records
and public identifiers, rather than selecting a program inventory by model.
Native ACS/DMCS pairs 60/60, 62/62 and 66/65 are supported. Physical terminal
capacity comes separately from exact documented hardware model evidence.
The newly admitted omitted analog-input defaults (813 and 3164) use the same
three-pair boundary; an undeclared or mixed data-model pair remains blocked.

The profile supports one of these operations per review:

- Allocate one unconnected local class-240 universal analog input at a documented
  spare UI terminal, using a fresh controller-reported next available identifier.
- Change one existing local analog input's electrical mode, linear input/output
  scaling, engineering unit and present-value limits. Its identity, binding,
  name, connections and all other configuration remain unchanged.
- Remove an unreferenced input originally allocated by this app, using the
  verified original allocation receipt for that exact controller and terminal.
  Other inputs cannot be removed. Unknown additional properties or references,
  including native identifiers inside opaque values, prevent removal.

Integral DPTs, SA/expansion allocation, binary input conversion, output modes,
terminal reassignment, new graph connections and supervisor changes are outside
this profile. Unknown models, formats, host relationships, ambiguous assignments,
duplicate identities and unsupported datatypes stop compilation explicitly.

Native Setup 1 means user-range volts, 0 user-range ohms and 2 user-range current.
Voltage uses native unit 5, resistance 4 and current 2. Native engineering units
are separate (for example 62 °C, 64 °F, 98 percent). The compiler checks finite
Real32 storage, increasing electrical endpoints, distinct engineering endpoints
(including inverse scaling), present-value limits and the
documented electrical range. Reviews show the stored, rounded values.

CV-series local UI1–UI3 support 0–10 V and resistance; direct 4–20 mA is unavailable.
Current mode is qualified here only for FX-PCG2611-0, with explicit physical
current-loop jumper confirmation. Its resistance limit uses the conservative
2 kΩ terminal-table limit. Supporting another current-capable device requires
its own hardware evidence; the format adapter itself is shared.

## Transfer and preservation

Apply reuses the native application's expiring one-use review, source-pinned
interface, durable intent and original backup. Before restore it checks:

- Exact responding Device identity, current application and static directory.
- Typed attributable input existence/absence and the proposed identifier against
  Device property 787. Timeout or unknown-property never proves absence.
- Current input name, terminal, mode and scaling for existing-input changes.
- Fresh saved settings, qualified application datatypes and File 3 capacity.

The compiler merges fresh saved settings first, preserves every other raw record,
unknown property, wire and framing style, and changes only the selected input.
Apply writes File 3 only. It does not write firmware, boot, Static or Dynamic files.
Allocation adds one minimally configured Monitor Only analog input with Process
ID Other; it does not connect it to the running control graph.

Verification compares the complete native application and saved settings, checks
operational status, and separately reads published Object_Identifier, Object_Name,
Device_Type, Slot_Number, Setup and all nine electrical/scaling fields present in
the expected input. Removal requires an attributable unknown-object response.
New input initialization is explicit: only previously absent class-240 Time
Constant (finite non-negative Real seconds), calculation-default byte (Unsigned
0–255), and presence Boolean are admitted on the newly created object. Their
exact encoded values are reported and bound to the original allocation receipt;
removal requires those non-electrical values to remain unchanged. Existing-object
changes and other new saved fields remain subject to the strict preservation gate.

Monitor Only filtering determines its live Update Interval from Time Constant / 30
seconds. Readback validates that derived interval against the independently read
Time Constant and records it separately from the stored interval default. A wrong
calculated interval still prevents verification. See [Analog Input Attributes](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/16.0/Analog-Input-Object/Analog-Input-Attributes).

Runtime counters, event timestamps and calculated airflow offsets can change
when control restarts; original values remain in the backup and observed runtime
differences appear separately from configuration preservation.

Uncertainty blocks a further transfer at that station. Open the retained input
receipt and choose **Read back input transfer**; it can use backup state services
but never replays a download. A malformed or foreign response cannot establish
success. Retained transfers remain discoverable after restart.

## Verification and physical limits

Authored tests cover allocation, terminal occupancy, integral-sensor exclusion,
mode changes, typed scaling, opaque property preservation, saved-presence handling,
reference-protected removal, local export and strict HTTP admission. Real UDP peer
tests exercise transfer, one-use plans, stale identifier checks, missing/negative
responses and published-property mismatch followed by explicit readback. Browser
tests follow the actual UI through allocation, voltage/resistance round trips and
removal, local copy saving, task navigation and substituted-review rejection.
CAF entry also reaches retained native input copies through Points & I/O without
opening a field interface; the native source stays separate from the open CAF.
The original feature author supplied the native datatype declarations and reports
a field allocation/mode/removal round trip. Independent review on this Mac uses
authored sources and checks the declared version boundary, transfer safeguards,
published-property comparisons and graphical workflow. It does not independently
establish that reported physical result or acceptance by every controller using
one of those native formats.

Software configuration/readback and an open-terminal value do not establish
calibrated analog accuracy. Applying a known voltage/resistance and checking field
wiring remain physical commissioning steps.

Hardware references: [CV-series model information](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/M4-CV-Series-VAV-Box-Controllers-Catalog-Page/13.0/VAV-Box-Controllers-CV-Series/CV-series-model-information),
[CV-series terminal ratings](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/M4-CV-Series-VAV-Box-Controllers-Installation-Guide/F/13.0/Wiring/Terminal-wiring-guidelines-functions-ratings-and-requirements/Input-and-Output-wiring-guidelines/I/O-terminal-blocks-ratings-and-requirements),
[Facility Explorer CV capacities](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/F4-CV-Series-VAV-Box-Controllers-Catalog-Page/VAV-Box-Controllers-CV-Series/CV-series-model-information),
and [FX-PCG26 current-loop jumpers](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PCG26-General-Purpose-Programmable-Controller-Installation-Guide/G/Setup-and-adjustments/Setting-the-Input-and-Output-jumpers/Universal-Input-current-loop-jumpers).
