# Native Calendar Date_List transfer backend

`native-calendar-reviewed-date-list-write/1` replaces the complete Date_List of
one existing standard BACnet Calendar. It consumes the separate
[local Calendar draft](native-calendar-drafts.md) and its exact expected review
ID. The source capture supplies the Device, address and route; callers cannot
substitute another target. This backend does not add a Calendar Apply button.
Its controller-centered deployment interface is the next separate feature.

The service requires an already-open plain IPv4 interface, either direct or
through an explicit router/DNET:MAC. Opening a source, requesting capabilities
or reopening a receipt never connects to a network. BBMD, serial/BTCVT,
segmentation, new objects, native CAF compilation and physical manufacturer
acceptance remain outside this profile. Existing numeric and String weekly
writers, their journals, rules and limits remain unchanged.

## Review and dispatch

1. Recreate the entire local draft from the immutable original source and verify
   its expected ID. Require exact captured Calendar identifier, name, description,
   Boolean Present_Value and complete canonical Date_List. Missing or unsupported
   context remains local evidence without field eligibility.
2. Read the actual Device and Calendar identifiers, name, description, Date_List,
   Present_Value, remote APDU limit and protocol revision through the pinned
   interface. Match complete original static tags. Present_Value is a changing
   observation, not an equality lock or simulation of the proposed dates.
3. If either original or proposed entries use WeekNDay values 7–9, require an
   actual known protocol revision of at least 18. Otherwise an unavailable
   revision remains explicit unknown evidence. Do not infer a manufacturer's
   behavior from successful local encoding.
4. Prepare the exact service-15 request with no array index and no request
   priority. A no-op provides no token. A changed value requires an explicit
   one-use Apply within the 30-second monotonic review lifetime.
5. Before dispatch, recreate the source proof, recheck every static value and
   remote capability, and retain the original socket/adapter/configuration.
   Verify the actual encoded APDU against the reviewed service body. Recheck
   review age and operation deadline both before and after durable intent.
6. Commit the original intent with SQLite `synchronous=FULL`, then permit one
   dispatch. No automatic retry, split, rollback or inverse write occurs.
7. Validate the protocol response independently of a fresh complete readback.
   Record selected Date_List matching and other static context matching
   separately. Retain partial evidence when readback cannot finish.

The Date_List type and native alternative tags follow pinned
[BACpypes3 0.0.110 CalendarEntry definitions](https://github.com/JoelBender/BACpypes3/blob/v0.0.110/bacpypes3/basetypes.py).
The protocol-revision requirement is documented in
[ASHRAE 135-2012 Addendum bg](https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-135-2012bg.pdf).
Read and write responses use the existing independently qualified property
evidence and scoped service-15 wire boundaries.

These sequential checks reduce stale-write risk and provide no compare-and-swap
or atomicity. Other work can change a controller between the last read and the
write. A matching property readback is not physical equipment acceptance,
calendar evaluation, a complete application transfer or a whole-controller
backup. Referencing Schedules and other devices are not crawled or rewritten.

## Receipts, uncertainty and reconciliation

Every admitted dispatch retains `may_have_applied: true`, including validated
Error, Reject and server Abort responses. A negative reply does not prove
unchanged state. Lost or unverified replies remain protocol-unknown even when
independent readback matches. An ACK with changed or unavailable readback does
not become a verified value replacement.

`protocol_accepted` is `true` for a validated ACK, `false` for a validated
negative response or a proven not-sent operation, and `null` after possible
dispatch without a validated response. The separate protocol status and
readback fields retain those distinctions after cancellation and restart.

The independent Calendar journal preserves exact original intent and immutable
result BLOBs, source/target/request bindings, their seals and the original intent
byte hash. Result publication and passive loading reject a substituted source,
target, request, review or missing original intent. Journal capacity never
evicts a receipt. Unresolved intents reserve space for a result before dispatch.

An intent without a sealed result projects dispatch, protocol acceptance and
readback as unknown after restart. Its pre-send fields remain only a historical
intent snapshot. A later explicit reconciliation uses the retained original
capture and saved local draft, sends reads only, and returns a new sealed
observation bound to the exact original receipt bytes. It never rewrites that
receipt or grants another write. Missing or invalid source evidence leaves the
receipt available for passive inspection while blocking active reconciliation.

Closing or changing interfaces clears prepared tokens and cancels the owned
operation before the connection changes. Cancellation before dispatch produces
a not-sent/cancelled result. Cancellation after possible dispatch retains
uncertainty. User-owned reconciliation cancellation returns its partial read
evidence; caller cancellation still propagates. No cancellation undoes a write.

## API and bounds

All mutation-shaped endpoints require the existing local session token and strict
request models. Operator name and rationale are visible, user-declared audit
text; they are not authenticated site credentials.

- `GET /api/bacnet/calendars/writes/profile`: limits, rules, active operation and
  bounded local receipt index; no controller request.
- `POST .../preview`: local `draft`, `expected_review_id`, `operation_id`,
  `operator_name`, `rationale`. Performs fresh reads; never dispatches a write.
- `POST .../apply`: exact one-use `token`, `review_sha256`, new `operation_id`.
- `POST .../cancel`: exact owned `operation_id`.
- `GET .../receipts/{id}`: exact original receipt JSON bytes.
- `POST .../reconcile`: original `receipt_id` and new `operation_id`; reads only.

Each request allows at most a **480-byte unsegmented APDU**, further restricted
by the actual remote limit. The existing local draft limit is 32 entries. At most
16 prepared reviews are retained; a newer review of the same Calendar retires
its predecessor, while unrelated reviews are not evicted at capacity. Production
request/operation bounds are one/15 seconds, 64 reads and 1.5 MiB of retained
property evidence per fresh observation. The independent journal allows 64
records, 64 MiB total and 8 MiB per BLOB, including reserved result capacity.
These limits do not enlarge any earlier writer or source-library quota.

## Software qualification

Independent direct/routed UDP peers check the literal Calendar object/property
bytes, complete replacement choices, absent index/priority and one dispatch.
Tests separate rejected, lost, malformed and wrong replies from independent
value/context readback; cover revision requirements, dynamic values, remote APDU
limits, no-op/empty lists, stale source/interface/review, pre-dispatch expiry,
storage failures, durable intent recovery and cancellation. Actual HTTP tests
perform the complete preview/Apply/receipt/reconcile path. Journal tests preserve
corrupt originals, reject re-sealed context substitution and serialize competing
capacity claims. Existing Calendar and numeric/String weekly contracts remain
separately qualified. All mutation targets are authored local peers; no site or
Bluetooth operation is used to qualify this backend.
