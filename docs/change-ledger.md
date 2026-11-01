# Changes ledger

Changes opens a searchable local record table in the existing controller/application
workspace. It does not require an open field interface. Local CAF changes and the
current graph appear above recorded operations; their actions return to the
existing editors without discarding drafts or sending controller changes.

## Recorded sources

The first profile combines eight existing evidence sources:

| Family | Retained evidence and meaning |
| --- | --- |
| Audit | Selected project/CAF exports and local plans, sandbox/runtime changes, Sedona/native project and online operations, Temco operations, point commands/releases and event acknowledgement events |
| Native application | Existing JCI instance/name, Real-default, Boolean-default and wire-source transfer intents, results, pending state and latest readback; original application files are not loaded by the list |
| Device instance | Standard BACnet instance attempts and later readbacks; successful later verification does not rewrite the original uncertain attempt |
| Schedule | Existing numeric/String Schedule weekly-day write receipts and intent-only uncertainty |
| BBMD | Original administration receipts and observed desired/different/unknown state; observation never proves authorship |
| Event acknowledgement | Session-scoped receipts; durable audit events remain independently available after the session receipt is retired |
| Temco | Retained operation snapshots; incomplete/destructive outcomes keep their original uncertainty |
| Owned command | Retained ownership records, including active verified overrides and pending verification; both still require explicit release |

This is a projection of existing records, not a new transaction coordinator.
The list never calls an adapter's connect, scan, readback, apply, resolve, retry,
rollback or release operation. It does not create or consume review tokens.
Existing adapter tools continue to own review, dispatch and recovery. Unapplied
transient reviews and providers without a retained record are not centralized
in this profile; open their existing task tools.

## Search, target and time bounds

Filter by family, recorded outcome, text or the selected station's original route.
Device instances are historical: a receipt with the old Device ID remains findable
after an instance change. Routed matching includes router endpoint, destination
network and station; duplicate Device IDs on another route do not match. IPv4
addresses normalize their default UDP port. A bare serial MAC also requires an
exact retained interface fingerprint. A legacy record without that evidence stays
available under All original targets and is never attributed to a serial trunk
solely because its MAC matches.

Each window reads at most 16 records per family, with strict validated per-source
cursors and explicit exhausted-source state. Text/outcome/target filters cover
that window; an empty filtered window can still have older matches. Older/previous
window controls retain the original source positions. This is not a global
chronological merge or an unlimited full-text database search: each family uses
its own insertion/key order, and returned rows sort by their recorded timestamp.
Missing timestamps remain unknown. Refresh starts a new local snapshot.

Journal head queries use read-only SQLite connections with a short progress
budget. A five-second processing budget is checked between source/record reads;
individual existing source readers retain their own limits. An interrupted window
retains unread positions. Corruption, optional source unavailability and read
budget errors remain visible alongside other valid records. An unavailable source
can be retried with Refresh; it is not silently presented as an empty healthy
journal. Separate journals are not an atomic snapshot.

Changing source/filter/window, controller, route or interface retires the current
selection and its pending responses. Late replies cannot restore evidence after
another record is selected, its panel is closed or its source view is retired.
The original target remains printed with every receipt and evidence view.

## Evidence and recovery

Details shows review/dispatch/readback evidence when recorded and distinguishes
unknown values. Needs attention includes uncertainty and owned commands requiring
release. Audit outcomes are historical events; later source evidence can supersede
them. An observed/verified record describes that operation's retained evidence,
not present controller health or general application acceptance.

Existing native, instance, schedule, BBMD and event receipt endpoints provide their
own documents and integrity checks. Downloads preserve the exact response Blob,
including numeric spelling such as signed zero and large integer tokens. Raw
technical evidence remains behind Details. Native source endpoints may include
the full retained event history; listing does not load that history.

Native rows retain their explicit operation kind and existing engineering record
reference. Original dispatch possibility comes from the attempt's durable result
or earlier intent; a later readback can resolve state without changing that fact.
Missing legacy kind retains the original instance-change meaning. An unknown or
invalid kind is labelled unsupported and receives no guessed tool link, while its
original evidence remains readable.

Real/Boolean defaults and wire-source rows open **Program → Native backup
defaults**, including offline retained work. Instance/name rows open the existing
identity tools. These links select the matching workspace navigation and preserve
the current controller; they do not select the receipt's station or dispatch a
field operation.

Audit/Temco/ownership detail endpoints instead return explicitly labelled local
views, with credential/token-named fields redacted. These views are not original
controller archives. Audit reads check the individual entry digest and its stored
previous-hash link, not the entire chain or an external digital signature. Temco
and ownership snapshots retain their existing storage contracts rather than
gaining a new seal through aggregation.

Open identity/schedule/event/BBMD/Temco/owned-command tools only navigates to the
existing task. It retains the current workspace target and does not retarget to
the receipt or trigger reconciliation. Select/reconnect the original station and
choose the original receipt there before following that adapter's recovery flow.
These links do not make separate changes an atomic batch.

## API and verification

`POST /api/changes/query` uses the existing local session-token admission. Its
strict body contains `source`, `text`, `outcome`, optional `selected_target`, and
the returned `before`/`exhausted` cursor fields. A selected serial target includes
the authoritative `interface_key`. `GET /api/changes/records/{source}/{id}` provides
redacted views for audit/Temco/ownership; source receipts retain their existing
endpoints. Reading the ledger does not append an audit event or change pending
state.

`tests/test_change_ledger.py` exercises actual local journals, seals, later
verification, corruption, cursor exhaustion, interrupted windows, exact routes,
serial interface identity, confidentiality and original response bytes. Browser
checks cover both entry paths, retained CAF edits, filters, paging, late-response
retirement, exact downloads, offline failures, navigation and narrow/desktop tables.
Authored direct/routed peers validate source propagation without physical device
writes. These checks do not establish new native compilation/transfer, electrical
allocation, physical acceptance or Bluetooth support.
