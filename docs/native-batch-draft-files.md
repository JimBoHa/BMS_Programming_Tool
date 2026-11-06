# Save and restore unfinished native batch text

Open **Program → Native backup defaults**, open the original retained source and
expand **Compile several native defaults together**. Within that task, expand
**Save or import unfinished batch text**. **Save unfinished batch draft** writes
a small JSON file. **Import unfinished batch draft** restores its selected raw
text into an empty batch for the same original source.

The file preserves one to sixteen selected Real, Boolean or Enum defaults.
Real and Enum values remain exact text, including an empty value, signed zero,
unfinished exponents, whitespace, Unicode or invalid proposals. A Boolean retains
its explicit true/false choice. Saving or restoring raw text performs no numeric
conversion or native compilation. A separate explicit local review validates a
finished proposal before any compiled copy can be saved.

## Source and file checks

The `native-default-batch-unfinished-draft/1` JSON profile binds the original
capture, evidence hash, capture time, Device/full route, recorded identity,
Files 3/11/12 hashes and lengths, and effective/native merge hashes. Every selected
field retains its actual kind, reference, class, property, encoding hash and
effective bits or value; Enum capacity remains separately bound. A model name
supplies no fields and a draft file supplies no application bytes.

The file is limited to 64 KiB, sixteen distinct fields and 128 UTF-16 code units
per raw value. UTF-8 decoding and the shared JSON parser reject malformed Unicode,
duplicate keys and excessive nesting. Unknown fields, authority, mismatched
sources/encodings, invalid Boolean choices and over-limit selections are refused.
All selections install together only after complete validation and the actual
file digest; a late invalid field cannot install an earlier partial selection.

On another computer, first [import the original native backup](native-backup-import.md)
and open its batch source. Then import the unfinished draft. This file does not
replace that original backup, change its metadata or establish a current field
connection. Existing single-Real draft files retain their separate profile.

## Existing work and lifecycle

Import refuses to replace any existing selection, including an empty raw value.
Use **Discard this batch draft** explicitly before replacing it. The existing
sixteen-field and thirty-two-source limits remain unchanged; imports never evict
an older source. Discarding an old batch frees a source slot.

Native review/export state and ordinary single-field drafts remain separate.
Source/task/visibility/disclosure changes and edits retire pending imports through
both file-read and actual-digest awaits. Monotonic counters distinguish changes
away and back before repaint. A retired response cannot replace newer text or
trigger an old Save action. Import provenance records the original file digest;
it grants no review, plan, journal, controller query/write or verified identity.

Qualification covers both entry paths, clean browser contexts, original-backup
portability, malformed files, no-eviction limits, interrupted work and exact
compiled output after a new explicit review. This remains local text portability.
General JCI authoring, batch field deployment/recovery, package/resource/runtime
validation and CCT/physical/Bluetooth acceptance remain separate.
