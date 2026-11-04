# Native matching connection archive copies

In **Program → Native backup defaults**, select a retained backup, inspect its
records, and open a recorded activity (536) or control sequence (575). Choose
**Native diagram operation → Add matching connection**, then expand the local
connection editor and **Open native connection candidates**. Select a recorded
connection prototype, an observed matching source, and an unused matching input.
**Review native connection copy** checks the proposal. **Save native connection
copy** exports a separate MOI file; the adjacent review action saves the original
review response bytes. Neither action contacts a controller.

This is `FMT-NATIVE-CONNECTION-COPY-001`, with compiler profile
`tagged-moi-connection-copy/1` and review profile
`native-archive-connection-copy/1`. It appends one connection between existing
members, rather than allocating a new block or inventing a port. Existing source
substitution, effective compilation, transfer and recovery retain their separate
contracts under **Change existing source**. Their component remains mounted when
switching local operations, preserving recovery ownership and evidence.

## Recorded prototype and exact preservation

Both endpoints must match the native class and ordered encoded configuration of
the recorded prototype endpoints. The existing source profile excludes identity,
reference, name and description, and compares recognized Real/Boolean defaults by
datatype; other properties retain exact encoded hashes. The source pin must
already have an outgoing connection in this actual diagram. The matching target
pin must be unused. Source execution must precede the destination, and the added
edge must not introduce a cycle. Pre-existing duplicate input ownership refuses
this operation. Candidate lists come from captured native records, independent
of controller model names.

The compiler requires the original File 3, diagram record, connection property,
optional continuation property, prototype index/tuple and connection count.
It appends the recorded four-Unsigned struct shape to property 3118. Port bytes
and sufficient index payload widths are retained. A new member index may widen
only its new tag. Original tuples remain exact. If property 3384 is present,
its Boolean/CharacterString rows must align exactly with the connection list;
the selected row is copied unchanged for the appended connection. Unknown or
misaligned continuation structures refuse the edit while original read-only
inspection remains available.

Only the selected record length prefix changes. Original extended framing stays
extended; a short record grows to extended framing only when needed. Other
record prefixes and payloads remain exact. Ordinary gzip retains its original
header with recomputed compression, CRC and size; this is expanded-byte
preservation, not compressed-stream identity. An independent native parse checks
the original graph plus exactly one edge, unchanged membership, object IDs,
execution order, layout, root identity and unrelated bytes. Inspection offsets
must shift by exactly the known record-growth delta. Existing source, expanded
size, tag and graph budgets remain in force; unsupported or oversized outputs
are refused.

## Local API and workspace ownership

The token-admitted API prefix is
`/api/bacnet/controller/native-application/inspection/connection-copy`:

| Endpoint | Result |
| --- | --- |
| `POST /source` | Recorded prototype, matching observed sources and unused matching destinations |
| `POST /preview` | Exact request, compilation/readback evidence, artifact and review digests |
| `POST /export` | Recomputed reviewed bytes with artifact, review, snapshot, source and compilation digest headers |

There is no Apply endpoint. Strict requests accept no field address, controller
command, extra authority flag or type coercion. Every operation verifies the
original immutable backup manifest and Files 3/11/12. Unknown saved schemas and
historical identity errors do not grant current controller authority or prevent
a qualified local archive copy. Saved settings are not merged or rewritten.

Drafts remain bound to capture, manifest, original File 3, exact target, diagram
record and prototype. They share the existing 256-slot wire draft cache, with
distinct keys and refusal at capacity; no existing work is evicted. Returning
the prototype selector to its first entry, discarding a proposal, or returning
the operation to source substitution frees only that selection's slots.
Navigation preserves local proposals while source/record/target/interface,
operation visibility, field-busy, proposal and page lifecycle changes retire
reviews and delayed results, including A→B→A transitions. A retired review must
be prepared again. Export verifies all five proof headers and actual file bytes.

Software qualification covers independently authored native frames and literal
tuples, gzip/raw input, both diagram classes, original unsigned widths, new index
width and short-record growth, continuation framing, class/configuration, pin,
input ownership, order, cycle, source/hash/count/type and capacity refusals;
immutable local APIs with field access forbidden; and Chromium/WebKit offline
and authored routed entry, exact downloads, draft navigation and rejected stale
or substituted results. Source and installed distributions are checked
separately. Tests use authored loopback peers, not site controllers.

This profile does not establish saved-effective connection additions, controller
transfer, general logic compilation, arbitrary new blocks or I/O allocation,
resource/package/release compatibility, native execution, CCT/PCT reopening or
physical/BTCVT acceptance. JCI-02, JCI-03 and JCI-09 remain partial overall.
