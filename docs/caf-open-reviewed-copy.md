# Continue authoring from a reviewed CAF copy

In Program → CAF file → Logic, a successful **Save constant CAF copy** or
**Save block CAF copy** now offers **Open CAF copy**. This opens the exact bytes
that passed the export proof, without finding the browser download through a
file picker. Opening remains optional. Saving still requests the normal browser
download; it does not confirm that a browser has persisted the download to disk.

The new file becomes the local application in the same workspace. The selected
controller and its exact route remain visible, and the controller/application
match remains unverified. No controller request, compilation, transfer or Apply
is introduced. Ordinary CAF Save retains its existing snapshot behavior.

## Review, save, open

The active creation task retains one primary action: Review, then Save, then
Open after a proven export. Repeat downloads and the reviewed proof remain
available. The optional handoff binds the original archive, output SHA-256,
immutable Blob, filename, diagram, creation kind and actual new block reference.
NativeCaf rechecks the Blob digest and live ownership before uploading it through
the existing local CAF validator. It checks both ownership and the returned
archive digest immediately before replacing document state.

A failed, cancelled, mismatched or retired handoff leaves the active source
unchanged. Source, prototype, kind, task, target-context and page lifecycle
changes retire the action and late completions, including leaving and returning
to the same source or selection. Duplicate clicks share one owned handoff.

The opened archive's actual graph inventory must confirm the diagram. Its actual
block, class and version must confirm the creation hint before the creator
selects the new block as its next prototype. Missing or incompatible hints fall
back to normal source discovery. The hint grants no native compatibility or
runtime authority.

## Pending edits and retained drafts

Creation copies start from the original opened archive. Other scalar, wiring,
hardware and instance proposals are not merged into that artifact. If other
unexported edits are pending, opening explicitly explains that they will be
cleared and asks the operator to continue or cancel. Cancel keeps the original
file and its edits. Failure also keeps them. Only a successful, explicitly
accepted replacement clears those proposal states.

Source-bound creation-coordinate drafts remain in the existing 32-entry cache,
including unfinished raw text, when earlier files are reopened. Reviews and
Open authority are not cached. This is in-memory workspace retention, not durable
draft storage across browser reloads. Other proposal types do not gain general
retention across accepted file replacement.

## Qualified scope

Authored browser fixtures cover the twelve initial creator shapes: Float,
Boolean and Enumeration constants; Float and Enumeration comparisons; Math;
Boolean logic; Timer; Float- and Enum-input Reliability Check; and Float
Multiplexers with Boolean or Enum selectors. Further cases cover mixed types,
nested diagrams, source-specific unfinished drafts, pending-edit cancellation
and acceptance, rejected uploads and wrong identities, stale completions, compact
controls, duplicate clicks and controller entry through an authored routed peer.
Pure handoff checks cover byte identity, location bounds and actual graph hints.
The separately qualified [Enum-valued Multiplexer](caf-recorded-enum-multiplexer-creation.md)
adds continuation from its typed output and optional state metadata. The
[Enum-selector Enum I/O profile](caf-recorded-enum-io-enum-selector-creation.md)
separately preserves its distinct selector and data state metadata.

These checks qualify local file continuation. Native CCT/PCT reopening, runtime
semantics, general File-3 generation, vendor resources/packages and physical or
Bluetooth acceptance remain separate. JCI-02, JCI-03, JCI-05, JCI-06 and JCI-09
remain partial.
