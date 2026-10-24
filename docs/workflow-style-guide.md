# BMS Studio workflow and interface style guide

The open controller or application is the workspace. Connecting, discovering,
editing and verifying form one continuous workflow. Features belong where the
operator uses them, rather than each receiving an independent tile or workspace.

## Entry paths

The start screen emphasizes two choices:

1. **Connect to a controller:** connection → router → trunk → scan → select
   controller → verify and open the controller workspace. Direct addresses may
   bypass discovery. Ask for connection parameters once.
2. **Open a CAF file:** open → inspect or edit locally → optionally connect →
   verify the intended controller → continue in the same workspace. Connecting
   must not be required to edit or save a local file.

Recent work, saved connection information and New application are secondary
choices. Opening a page or restoring a draft must not silently connect to a field
network. The CCT/PCT workflow is a reference for task order, not a claim that all
of their native services are implemented here.

## Persistent workspace

The workspace retains the controller's name, router, network, MAC, Device instance,
last verification time, open filename and local changes. Interface open, controller
selected, controller responding and connection lost are separate states.

Use Edit, Simulate and Commission as explicit working modes. Clearly identify
values originating in a live controller, a local file or a simulator. File and
controller contexts may coexist; their application match must remain unverified
until actual compatibility evidence supports it.

An explorer provides router → trunk → controller navigation and local application
selection. The main area contains the selected task. Preserve drafts and source
identities when switching tasks. Changing a target invalidates the old target's
write review, and never silently transfers edits or releases an owned command.

## Function groups

| Workspace tab | Functions |
| --- | --- |
| Overview | Identity, model, firmware, connection state, device settings and instance changes |
| Points & I/O | Values, quality, hardware and input inspection, mapping, commands and overrides |
| Program | Application inspection, supported editing, logic, parameters, truth tables, simulation and validation |
| Schedules | Weekly schedules, calendars, exceptions and supported schedule changes |
| Trends & Alarms | Monitoring, recorded trends, device history, COV, events and acknowledgements |
| Changes | Pending changes, comparisons, review, results, readback and receipts |

Selecting a router or trunk exposes discovery, topology and advanced network
administration for that object. Library contains reusable templates, macros and
hardware definitions. History contains cross-session records. Settings contains
communications, preferences and toolchain configuration. Help contains reference
material. These groups replace most feature-level global destinations.

## Interaction rules

- Use a short guided setup, followed by direct workspace navigation. Show the
  current step, preserve completed choices and let known targets skip scanning.
- Query the selected router for trunk choices. Scan results are searchable,
  identify their response window and retain duplicate Device IDs by physical route.
- Use **Open controller** to verify a selected station and enter its workspace.
  Enter addresses once and reuse that authoritative target in related operations.
- Make target identity read-only outside connection and identity-edit workflows.
- Use tables for devices, points, schedules and changes, and drawers or focused
  dialogs for individual edits. Reserve cards for entry choices and concise summaries.
- Give each active task one visually primary action. Keep advanced settings and
  protocol evidence behind Details or an advanced section.
- An instance change belongs at Overview → Identity → Edit instance number →
  Review → Apply → Readback, without finding another page of tools.
- Show unsupported capabilities with a short explanation in the relevant view.
  Hide unrelated tools. Do not turn unavailable services into a wall of disabled cards.

## Action language and outcomes

Use precise verbs: Connect, Scan controllers, Open controller, Edit instance number,
Save project, Save CAF copy, Review change, Apply to controller, Read back, Release
override and Disconnect. Avoid ambiguous Use and Submit labels.

Saving a file never sends it to a controller. Application transfer appears only
where the actual adapter supports it. An exposed BACnet File capture must not be
described as a complete editable application or whole-controller backup.

Field operations follow **Edit → Review → Apply → Verify**. Reviews show the exact
target, property, previous value and proposed value. Results distinguish verified,
rejected and outcome uncertain. Common presentation does not turn unrelated
operations into a single atomic transaction. Retain existing protocol, allocation,
ownership and durable recovery checks.

## Visual rules

- Retain the teal accent with neutral backgrounds, clear borders and restrained
  emphasis. Use an 8, 16 and 24 pixel spacing scale.
- Use readable 14–16 pixel body text and differentiated headings. Engineering
  tables may be compact, with aligned numbers and explicit units.
- Use green for verified success, amber for incomplete or uncertain results and
  red for failure. Always accompany color with text or an icon. Offline is neutral.
- Keep detailed technical evidence, raw responses and hashes in Details. Put errors
  beside the affected action and include a concrete recovery step.
- Support keyboard navigation, visible focus, labelled controls and searchable
  lists. Preserve distinguishing addresses when names are truncated.
- On smaller screens, collapse navigation and inspectors into drawers. Do not
  force the operator to hunt through horizontal rows of feature tiles.

## Acceptance checks

A user can reach a controller through one continuous connection and discovery
flow; edit and save a CAF offline; change tasks without re-entering the target;
find instance settings from the controller overview; and distinguish local,
simulated, stale and live information at all times. Navigation must retain drafts,
prevent stale write plans from returning, and preserve uncertain-operation receipts.

The reference CCT commissioning sequence documents application and connection
selection, discovery, device selection and a commissioning summary:
[Commissioning Device Wizard, Controller Tool Help 15.0](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/15.0/Commissioning-a-System/Commissioning-a-System-Screens/Commissioning-Device-Wizard?contentId=QourvEPJYONFlcp_CGZU9Q).
