# Inspector parameter drafts

The local graph inspector keeps unfinished numeric text, numeric arrays and
unapplied parameter JSON with the block and field where they were entered.
Selecting another block, using group selection or visiting another workspace
task does not apply or move that text. Returning to the original field restores
its text and parse error while its accepted source is unchanged.

Numeric edits still take effect when they parse successfully. JSON still requires
**Apply calendar exceptions** or **Apply parameter JSON**. An export, saved
revision, recovery document or simulation uses accepted Program data. Merely
opening a field or restoring its unfinished text never commits it or connects to
a controller.

## Ownership and retirement

The App owns an in-memory `ParameterDrafts` cache. Each entry identifies the graph,
declared target profile, node ID/kind, reusable definition, value type, engineering
unit, parameter and editor type. The accepted value is compared through the exact
source serializer or numeric token, including signed zero and numeric type.
Names and labels are presentation fields and do not own a parameter draft.

The inspector reads the current owner synchronously; selection changes cannot
temporarily show the last field's buffer while waiting for an effect. Accepted
Program changes reconcile cached entries even when the original inspector is
closed. Changing the field's accepted value, units, type or target, removing its
node, or opening another graph retires its old entry. Undoing that source change
does not revive a retired unfinished edit. Other fields' accepted changes and
renaming preserve a draft whose owner and source remain unchanged.

These buffers last for the current open graph session. They are not a new file
format or durable recovery store; reloading the page restores accepted graph
recovery through the existing mechanism. Native CAF scalar fields, reusable
Activity parameter forms, simulation-force fields and controller write reviews
retain their existing separate lifecycles. This change does not implement native
JCI compilation, controller editing or physical acceptance.

## Local verification

`web/tests/inspector-drafts.spec.ts` uses the actual application and HTTP import
and export endpoints with isolated state in Chromium and WebKit. It covers
different blocks with equal values, parse-error ownership, valid unapplied JSON,
task and group-selection navigation, accepted edits, undo/redo, numeric source
tokens, array/JSON separation, rename versus units/type/target changes, hidden
source retirement and another graph with the same node IDs. It verifies accepted
exported values and absence of BACnet mutation requests during local navigation.

The original numeric and JSON leakage was reproduced in both browsers before
the fix. No live controller, Bluetooth adapter or vendor runtime is used by these
checks. The broader UX-04 source/capability/recovery presentation item remains
partial; `UI-INSPECTOR-DRAFTS-001` describes only this local graph slice.
