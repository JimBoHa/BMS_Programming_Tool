# Guarded CAF execution-order copies

Open a CAF, then choose **Program → CAF file → Logic → Connection table and
guarded CAF export → Change block execution order**. Select an existing block
and use **Move block earlier** or **Move block later**. The table compares proposed
and original positions, starting at one. **Review execution order** checks the
original source again. **Save execution-order CAF copy** saves a separate archive;
**Save exact execution-order review** saves the original admitted JSON bytes.
Open the exported CAF explicitly before combining further changes.

This implements `FMT-CAF-EXECUTION-ORDER-001`, profile
`caf-execution-order-copy/1`. It edits the recorded execution list of class 536
Control Activity or class 575 Control Sequence, version 1.0, with 1–512 members and
at most 6,000 connections. Model names never select a substitute application.
The original CAF and other pending scalar, creation or wiring proposals remain
independent. This feature adds no controller operation or field plan.

## Recorded dependencies and exact preservation

The proposed list must be a strict permutation of every original block index.
Each recorded connection retains its original source/destination execution
relationship: before, same block, or after. A move that reverses an existing
forward or backward edge refuses, including in a diagram containing feedback.
Self-connections remain self-connections. The editor disables forbidden adjacent
moves; the server independently checks the complete proposed order. No assumption
that every original diagram is acyclic is required.

Only changed numeric atoms in property 3117 are replaced. Unchanged numeric
spelling, surrounding whitespace, container/attribute spelling and all XML outside
those atoms remain exact. Object identities, membership, wires, continuation,
positions, child configuration and opaque fields stay unchanged. A recorded
user-modified property must already be true when present. Unknown property
metadata, mixed text or unsupported lexical encodings refuse editing. Inspection
and the original archive remain available. A no-op returns the exact original ZIP.

An independent archive/parser readback verifies the intended order, derived block
ranks, unchanged graph and objects, unrelated properties, ZIP entry attributes,
dates and comments. Changed ZIP compression/container bytes are not claimed
identical. These are structural checks. They do not verify side effects between
otherwise independent blocks, resource limits, complete native semantics,
CCT/PCT reopening or firmware execution.

## API and review ownership

Strict token-protected local routes under `/api/caf/{sha256}/execution-order`:

| Route | Result |
| --- | --- |
| `POST /source` | Exact original diagram/order hashes, members, recorded wire relationships and sealed selection |
| `POST /preview` | Recomputed source, strict permutation/dependency check, independent readback and sealed review |
| `POST /export` | Recomputed reviewed CAF bytes and artifact/source/review/order/request proof headers |

The browser independently checks original member/order/connection relationships,
selection and nested review seals, the clicked proposal and original object count.
All five proof headers and the actual artifact digest must agree before download.
Source, diagram, controller/interface context, proposal, navigation, disclosure,
visibility and page-lifetime changes retire reviews and late replies. Retired
callbacks cannot fetch or download. Concurrent clicks share the owned local task.

Up to 32 source/diagram drafts retain their discrete proposals in memory without
evicting earlier work. Passive inspection uses no slot. Explicit discard or moving
back to the original order frees only that draft. Task/file navigation keeps drafts
while retiring reviews. Reload persistence and restored field authority are not
provided. Export marks only its matching proposal saved and leaves the opened
original unchanged.

Software qualification uses authored XML/ZIP oracles, all four-member permutations,
both diagram classes, backward/self connections, strict stale/schema refusal,
exact no-op and preservation, actual offline HTTP/browser exports and independent
download inspection. Desktop/phone, keyboard, draft navigation, late replies,
altered artifacts and authored routed-controller context are tested separately.
Private originals are never committed or rewritten. No site, VM or Bluetooth
operation is used. JCI-02/JCI-03, general compilation and physical acceptance
remain partial and separate.
