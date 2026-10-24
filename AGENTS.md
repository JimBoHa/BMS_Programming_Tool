# BMS Studio repository rules

## Workflow and interface design

Read [the workflow style guide](docs/workflow-style-guide.md) before changing the
interface. Treat it as the default design contract for new and revised workflows.

- Organize the interface around an open controller or application. Do not add a
  top-level destination or a dashboard tile for each new feature.
- Start with Connect to a controller or Open a CAF file. Keep offline work useful
  without a field connection; provide a direct-address shortcut for known targets.
- Keep the selected controller, its exact route, the current file and the data
  source visible. Distinguish an open interface from a verified responding device.
- Group device work into Overview, Points & I/O, Program, Schedules, Trends &
  Alarms, and Changes. Put reusable assets in Library, cross-session records in
  History, configuration in Settings and reference material in Help.
- Read connected configuration and values from the selected controller. Discover
  objects, capabilities and I/O relationships rather than selecting inventories or
  module counts by model. Native readers belong to protocol/format families and
  must distinguish captured configuration, exposed live values and write support.
- Enter addresses once. Reuse the authoritative selection in downstream tools.
  Changing targets invalidates their pending write reviews, while retaining local
  file drafts and recovery evidence.
- Use focused task views, searchable tables and progressive disclosure. Show one
  visually primary action for the current task. Avoid a page of unrelated cards.
- Use explicit action labels: Open controller, Scan controllers, Edit instance
  number, Save CAF copy, Review change, Apply to controller, Read back and Release
  override. Saving local work must never imply a controller write.
- Keep field modifications in Edit → Review → Apply → Verify. Preserve existing
  identity checks, one-use plans, ownership, transaction limits and uncertainty
  recovery. A common Changes view is not an atomic batch operation.
- Expose supported operations in context. Explain unavailable capabilities without
  presenting a simulated or local result as physical controller acceptance.
- Preserve the teal visual language, readable engineering tables, keyboard access,
  visible focus and text labels for all status colors. See the guide for spacing
  and typography.

## Implementation and verification

- Carry authorized implementation through relevant checks and local verification.
- Check both entry paths, navigation without losing drafts, target propagation,
  target-change invalidation, offline behavior and failure/uncertainty states.
- Do not use live controller writes to verify interface-only changes. Use authored
  protocol peers and isolated state for mutation tests.
- Keep site data, credentials, controller archives and local state out of commits.
- If local review is requested before publication, prepare separate reviewable
  branches and commits, install the local result and hold remote pushes for review.
