# Native Schedule exception deployment

Open a captured Schedule in **Schedules → Offline Calendar and Schedule library →
Schedule exceptions**. Edit and review the local exception draft, then open
**exception deployment and receipts**. The selected, verified controller must
match the capture's exact Device, address, router and network. Local review,
unfinished text and export remain useful without that match or a field connection.

Enter an operator declaration and rationale, choose **Review Exception controller
change**, inspect the fresh review, then **Apply Schedule exceptions**. The
operator text is a declaration, not authenticated site identity. This separate
profile is `native-schedule-reviewed-exception-write/1`; local exception encoding,
weekly/String writes and Calendar writes retain their independent authorities.

## Field admission and request

Only one existing standard Schedule's whole Exception_Schedule is replaced.
Before review and again before dispatch, the tool reads the exact Device and
Schedule native identities, actual maximum APDU and protocol revision, names,
description, effective period, default, write priority, destination references,
out-of-service flag, all seven weekly days and every original exception.
Array counts are checked again after their indexed reads. Sequential observations
cannot exclude every concurrent external change and are not compare-and-swap.

Present_Value, StatusFlags, Reliability and available device clock fields remain
typed observations. Their changing values do not become static configuration
locks or an evaluation of the new schedule. The default's observed native datatype
continues to constrain all proposed values, including explicit Null release.

Each distinct proposed Calendar reference requires a fresh matching
Object_Identifier read at the same selected Device and route. These targeted reads
do not scan a network, inspect Calendar contents or verify its current Boolean
value. An invalid older reference can be removed without requiring a new lookup
of that removed reference. Original or proposed WeekNDay values 7–9 require an
actual protocol revision of at least 18; the tool does not infer compatibility.

A changed proposal receives one review with a 30-second monotonic lifetime.
Cancellation also retires completed reviews owned by the cancelled operation.
Expiry, altered source, static context, capabilities, interface/socket identity
or review hash prevents dispatch. The lifetime and actual encoded request are
checked again immediately before dispatch and after durable intent publication.
An exact no-op issues no request or token.

Apply sends one unsegmented confirmed WriteProperty, service 15, property 38,
without an array index or request priority. The APDU must fit both the 480-byte
profile ceiling and the actual remote maximum. Values are never split or retried.
For Schedule instance 1, the service body starts with `0c0440000119263e`, followed
by the complete native exception array and closing tag `3f`.

This slice uses an already-open direct or explicitly routed plain BACnet IPv4
interface. BBMD, serial/BTCVT, segmentation, new objects, effective-period/default/
link editing, schedule execution, timezone/DST behavior, native CAF generation and
physical manufacturer acceptance retain separate qualification requirements.
Native value and period definitions follow the [local exception profile's
reviewed primary sources](native-schedule-exceptions.md#native-values-and-meaning).

## Receipts, uncertainty and recovery

The independent SQLite journal retains up to 64 sealed intent/result records
within 64 MiB, with an 8 MiB bound per record and reserved result capacity.
Full-sync intent publication precedes an admitted dispatch. Completed original
results are immutable; records are not evicted or replayed automatically.

A validated ACK, negative response and missing response remain distinct from
readback. Every admitted dispatch may have applied, including Error, Reject,
Abort or a lost ACK. Readback separately compares the complete proposed exception
array and all other static Schedule fields. An ACK with normalized or changed
values is not a matching readback. A matching readback after lost ACK does not
invent protocol acceptance. Interrupted or partial reads retain their observations
without claiming a complete match.

An intent with no sealed result stays unresolved after restart: dispatch,
protocol outcome and prior readback are unknown. Passive receipt inspection and
exact receipt downloads work offline. **Read back Exception receipt** explicitly
performs new read-only acquisition against the receipt's original selected target,
reports zero writes and leaves its original bytes unchanged. It never restores,
retries or clears newer local exception edits. Read the current Schedule into a
new capture before preparing another change against the modified configuration.

Source/controller/interface changes, navigation, visibility and A→B→A transitions
retire field authority. Late responses cannot revive it or replace newer raw work.
The existing teal workspace, focused local editor and progressive deployment
section retain one primary action for the current stage.

## API and qualification

The prefix is `/api/bacnet/schedule-exceptions/writes`:

- `GET /profile` lists the supported scope, limits and receipt catalog.
- Token-protected `POST /preview` takes the exact local draft, expected review ID,
  operation ID and operator declaration; it accepts no target override.
- Token-protected `POST /apply` consumes one token and review hash.
- Token-protected `POST /cancel` retires the owned active operation/review.
- `GET /receipts/{id}` returns retained evidence without a field query.
- Token-protected `POST /reconcile` takes a receipt/operation ID and only reads.

Qualification uses independently authored direct/routed UDP peers, literal native
array/service bytes, all seven observed value datatypes and Null, exact source and
capability conflicts, Calendar identity checks, size/revision refusals, cancellation,
expiry, storage failures, immutable intent/results and explicit restart readback.
Browser qualification covers controller and CAF entry, target/source lifecycle,
late replies, substituted responses, unfinished text, phone layout and receipt
recovery. These checks establish a simulated software profile, not physical
controller acceptance. SCH-01–SCH-03 remain partial.
