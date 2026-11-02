# Weekly draft workspace continuity

Within **Schedules → Offline Calendar and Schedule library**, unfinished weekly
rows now stay with their exact original capture, Schedule and native day.
Switch tasks, open another capture or day, or visit Library and return to
Workspace without exporting first. Opening a local graph or CAF offers the same
offline workflow. Reopening a retained selection reads the local library only;
it does not open an interface or query a field device.

The workspace preserves raw text, including incomplete numeric/time fields and
invalid quoted String text. It does not parse, normalize or repair a buffer while
restoring it. Imported work retains its original review ID and filename as
provenance, independently of subsequent edits. A same-day import cannot replace
unfinished retained work: export it or explicitly discard that day first. Imports
for another day keep the other source's work.

Local and field reviews are transient. Edits, source/day changes, navigation,
visibility and interface/selected-target transitions retire pending reviews and
exports. Returning to the original source or target cannot revive an older
operation. Restored imported provenance supplies no write authority. Review the
retained rows again; controller deployment still requires its separate fresh
review, one-use Apply and readback workflow.

Loading remembered connection settings while no verified field connection exists
does not cancel a local import. Opening a verified connection or changing the
selected target still retires authority. Offline settings supply no field token.

## Storage and discard

The workspace retains at most 128 edited weekly days and 4 MiB of serialized UTF-8
buffer data. Viewing an unchanged day does not consume a draft slot. A new or
expanded buffer that exceeds a limit is refused without changing existing work.
Raw rows are independently copied so restored editor values cannot mutate another
retained source. Existing row and editor-text limits remain unchanged.

**Discard weekly draft** removes only the selected capture/Schedule/day buffer
and restores its captured seed. Other retained days and imported provenance stay
available. Exported work remains in the workspace until explicitly discarded.
Reviewed native export marks that buffer saved without altering its original
source; unfinished text export preserves its current edited state.

Buffers live in this application's in-memory controller workspace. Export work
before reloading, restarting or moving computers. **Weekly workspace draft limits**
now offers [unfinished text export and import](unfinished-weekly-recovery.md),
including invalid fields that cannot yet produce a reviewed native draft. Export
the original capture archive too. Durable source
captures, receipt journals and existing backend review limits are unchanged.

## Scope and checks

Browser checks cover local graph and CAF entry, partial numeric/time/String text,
source/Schedule/day navigation, task and surface transitions, import provenance,
same-day replacement refusal, exact exports and late review/import/export
retirement. Separate boundary cases verify count/byte refusal, copy isolation and
explicit discard. Authored direct/routed captures provide actual native source
evidence; offline navigation adds no field requests.

Tables scroll within their own containers on narrow screens. The surrounding
source labels and actions remain visible; imported hashes stay behind Details.
Existing styles remain intact, with a scoped library stylesheet containing these
tables and wrapping original evidence.

No production backend, protocol rules, native writer, receipt or source archive
changes. This completes the scoped weekly workspace continuity
idea under SCH-01/UX-01; exception/context/link editing, schedule evaluation,
native CAF integration, durable unfinished-draft storage and physical acceptance
remain separate work. The public criterion register is unchanged.
