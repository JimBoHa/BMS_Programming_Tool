# Native effective Real-default compiler

In **Program → Native backup defaults**, open a retained native application
backup and select an actual supported signal. This works without opening a field
connection. Native backups are captured through the existing native application
workflow; their capture can enter and end controller backup mode. Opening,
reviewing and exporting from this compiler use only the retained files.

The source is one immutable, identity-verified vendor 5 snapshot. File 3 holds the
application archive, File 11 the saved-parameter selector directory and File 12 the
saved dynamic values. The compiler validates the original files and merges their
matched saved application parameters before applying one supported edit. The
table distinguishes the archive default from its effective value after this
merge. These are historical snapshot values, not current live input/output values.
Unmatched non-application slots remain in the original backup; they are not
invented in the compiled application.

The narrow edit profile supports existing class 526/527 Real Default Value
property 3113 fields in complete framed tagged MOI. Native object identities and
references must remain unambiguous through the saved-setting merge. A merge
that changes Device identity or reassigns a supported signal reference is refused.
No controller-model inventory supplies a replacement application or a field list.

Enter decimal text and select **Review native compilation**. The review binds the
snapshot seal, original File 3/11/12 hashes, actual record/property encoding and
proposal text. It shows the stored float32 value, exact bits and decimal rounding.
Nonfinite, overflowing and nonzero-underflow values fail. Other merged application
bytes remain identical; no block, link, ordering or physical I/O allocation is added.

**Save compiled native copy** exports the native image with exact source/review/
artifact digest checks. **Export exact compilation review** retains the original
review response bytes, preserving native number spelling. Original snapshot files
are never replaced. An unchanged selected value can still produce a different
archive because other saved parameters have been merged; the review identifies
these two facts separately.

The local compiler endpoints have no Apply route or controller write. Their output is not a
current-setting guarantee, general native graph compiler, vendor package/resource
validation, CCT reopening result or physical controller acceptance. The separate
[controller transfer workflow](native-default-transfer.md), shown below local
compilation in the same Program view, acquires fresh saved values, guards the
selected prior value, retains original files and uses a one-use reviewed intent.
It verifies both application bytes and effective settings after transfer. Saving
a local compiled copy never invokes that operation. Existing identity-transfer
support remains independently available.

The current CAF/local graph remains independent. Navigating away retains local
native drafts, while transient reviews and pending downloads retire. Source,
field, proposal and controller/interface changes invalidate the old review before
paint, including a return to the same selection. Native draft storage is bounded
at 64 fields; capacity pressure does not silently remove old drafts. Explicitly
discard a selected field draft to free space. Browser storage failure remains visible.

## Local API

The compiler endpoints are under
`/api/bacnet/controller/native-application/signal-default`:

- `GET /sources` lists retained sources without controller requests.
- `POST /source` opens one capture and derives actual archive/effective fields.
- `POST /preview` compiles a source-bound proposal and returns a sealed review.
- `POST /export` recomputes the same review before returning exact native bytes.

POST operations use the existing session token admission. Every source is loaded
through the retained snapshot's original checksums; missing, substituted or
redirected source files fail. The snapshot namespace remains trusted local state.

Qualification uses literal authored records/storage slots, independent expected
Real bytes, unknown-record preservation, source/identity/CRC failures and the
production HTTP API. A real authored native UDP backup is captured, its interface
closed, and the compiler then produces output with zero additional wire requests.
Browser verification covers source-specific drafts, stale/altered replies,
exact downloads and independent CAF navigation. No site or Bluetooth writes are
used to qualify this compiler.
