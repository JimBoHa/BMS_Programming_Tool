# Responsive workspace panels

The existing controller/application workspace now adapts its primary navigation
and inspectors below 900 px. The desktop teal rail, task tabs, block palette,
wiresheet and properties columns retain their existing placement.

## Compact controls

- Menu opens labelled navigation with the current workspace source and selected
  controller route/interface state when available.
- Task and Tool selectors replace wrapped/horizontal tab rows. Their choices,
  disabled states and navigation callbacks are the same as the desktop buttons.
- Controllers opens the existing explorer without scanning or reopening an
  interface. The original selected controller, Device, router and network remain
  visible in the drawer context.
- Block library opens the existing searchable palette. Tapping a block adds it
  through the existing authoring action and opens its properties. Drag placement
  remains available on the desktop.
- Properties opens the existing block or group inspector. Explicit node clicks
  can reopen it, including the already-selected block. Selection/drag position
  updates do not interrupt a gesture by opening a modal.
- Object properties opens the existing local CAF scalar inspector. Object names
  are keyboard buttons as well as row click targets. Re-selecting the same object
  reopens the drawer and retains its local scalar changes.

Drawers identify their data as a local graph, local CAF or selected controller.
Opening one never verifies a device, sends a field read/write, creates a review
or releases ownership. Actual connection/discovery/verification buttons keep
their existing meanings and checks.

## Focus and draft ownership

`ResponsivePanel` uses a native modal dialog in compact layouts and a nonmodal
inline container on the desktop. The panel's children stay mounted in the same
place while the presentation changes. Accepted graph/CAF drafts remain in their
existing owners. Unfinished numeric input text and its validation error survive
drawer close/reopen and compact/desktop resize; selecting another source still
uses that editor's existing invalidation rules.

Escape, Close and the backdrop dismiss a compact drawer. Focus returns to its
trigger, or stays with the corresponding visible input when widening to desktop.
Tab and Shift+Tab cycle visible enabled controls explicitly, including button-only
stops in WebKit. Native modal inertness prevents background pointer actions;
keyboard events inside the drawer do not reach hidden graph save/delete/undo
handlers. Copying/editing text inside a field retains browser behavior.

Changing task, file, controller or interface retires the associated open drawer.
Existing request generations, pending-review invalidation, local draft recovery
and protocol ownership remain with their original components. Closing a drawer
does not cancel an owned command or silently stop/retry a field operation.
Local property/catalog failures remain visible inside the active drawer. Mobile
fields and labels use 14 px text, metadata uses 12 px, and drawer/trigger controls
have explicit labels and visible focus. Engineering tables keep their own scroll
containers.

## Scope and verification

This profile covers navigation, primary task/tool chrome, the controller explorer,
portable graph palette/inspectors and CAF scalar properties. Existing full-page
manufacturer engineering views and native logic forms retain their own task
layouts; this is not a rewrite of their controls or an extension of compilation,
transfer or physical capabilities.

`web/tests/responsive-workspace.spec.ts` covers touch/keyboard opening, focus
containment/restoration, backdrop/Escape, hidden-shortcut isolation, accepted and
unfinished edits, repeated selection, the same input node across resize, source
replacement with a delayed reply, visible errors, exact routed context, desktop
drag/wiring/undo and compact node movement without a modal interruption. Tests
run in Chromium and WebKit against built production assets and authored local
peers. Existing workflow/controller suites check both entry paths, target changes,
read failure/late replies, unverified CAF matching and instance-review retirement.
No physical controller or Bluetooth actions are part of these interface checks.
