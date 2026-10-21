# Read-only device event states

The **Connect → Device event states** panel explicitly acquires standard BACnet `GetEventInformation` summaries from an exact Device. This implements the retrieval portion of field-event handling. It does not subscribe to unsolicited notifications, send `AcknowledgeAlarm`, modify notification classes/recipients, or insert simulated/local alarms into field results.

## Operator workflow

Open a BACnet/IP interface, select a discovered Device or enter its exact address and Device object identifier, and click **Query device events**. For a routed MS/TP controller, also supply its explicit IPv4 router and matching `DNET:MAC` / DNET. A request can retrieve one through five device pages. When the device indicates more events, **Continue event query** uses the returned one-use cursor. Each continuation verifies the Device identity again.

Each row displays its object identifier, reported event state, notify type, transition acknowledgement bits, and local UTC receipt time. **Inspect event** retains the native EventSummary fields and all three BACnet `TimeStamp` choices. JSON export contains the complete displayed report; CSV includes raw summaries, timestamp choices, target/route, identity status, completeness, errors, cursor, and report-hash linkage. An empty/failed query also has an explicit report row in CSV.

Changing the selected source clears the displayed evidence and continuation. Cancellation explicitly retires this operation's transactions. Leaving Connect cancels an active query, and interface disconnect/reconfiguration cancels it before closing the socket. There is no automatic device polling on page open, continuation, export, or status inspection.

## Meaning of the evidence

`eventState` and `acknowledgedTransitions` are values returned by the device. A normal state can still have an unacknowledged transition. These bits do not prove an operator saw an alarm, that a notification was delivered, or that this application acknowledged anything. `GetEventInformation` does not return point reliability/status flags, so quality remains `not-supplied-by-EventSummary` rather than being labelled good.

Event source timestamps retain their native `dateTime`, `time`, or `sequenceNumber` choice, including wildcard Date/Time fields. A sequence number is not a wall clock. No source timezone is inferred and `source_clock_utc` remains null. `received_at`, identity-read times, page receipt times, and request start/finish times are local UTC observation times. Unknown/vendor event-state values remain native numeric values with their available enum rendering.

The live event list is not an atomic snapshot. Pages preserve device order without assuming numeric object ordering. Repeated object identifiers within/across pages, or an empty page claiming more events, stop collection as a protocol/changing-list error. Previously completed pages remain visible and are not duplicated. A complete result means the device ended this bounded list traversal; it does not certify every site alarm path or prove a continuously alarm-free system.

## Device and route guards

Requests inherit the strict destination rules from [Device details](device-details.md): literal unicast IPv4 or exact routed `DNET:MAC`, actual Device instance, explicit router/DNET pair, no broadcast/wildcard targets. An owned `ReadProperty` verifies the selected Device's `object-identifier` before event requests. `DeviceDetails._path` pins the selected router/remote source and restores its temporary handlers on all exits. The engineering connection configuration and owned command journal are unchanged.

`confirmed_exchange` owns each confirmed transaction from dispatch through response, timeout, and cancellation. ACK type/source/invoke/service must match. Native rejections, unsupported-service replies, timeouts, partial results, identity/protocol failures, limits, cancellation, and interface interruption have distinct outcomes. BACnet APDU confirmed-service choice **29** is GetEventInformation; its `protocol-services-supported` bit is **39**, a different numbering namespace.

The pinned BACpypes3 0.0.110 exposes GetEventInformation request/ACK classes but omits its generic BACnet-Error decoder registration for service choice 29. The adapter installs the standard two-field error decoder only if no decoder is already registered. Real UDP tests verify that `optionalFunctionalityNotSupported` becomes an explicit unsupported outcome rather than being dropped and appearing as a timeout.

## Bounds and cursor handling

The default per-request deadline is 15 seconds including connector-lock admission, with 1.5 seconds per exchange and at least 50 ms between request starts. A collection accepts at most 20 pages, 500 event summaries, 32 explicit acquisition attempts, 64 KiB per decoded/re-encoded ACK, and 1 MiB of report data. At most 16 reports are held in memory. Completed pages survive a later timeout; a fresh continuation token may be issued if the last valid page reported more events and limits allow it. Other protocol failures do not produce a cursor.

Continuation tokens are claimed before awaiting network I/O. Replay, changed Device/address/router/DNET, changed interface/configuration, a newer query for the same source, expired cursors (300 seconds), and evicted reports are rejected before an event request is sent. A cancellation request arriving before acquisition admission is retained in a bounded tombstone cache so that delayed admission cannot send a later query.

The report SHA-256 covers compact, sorted-key UTF-8 JSON excluding its own `evidence_sha256` field. Page ACK hashes identify BACpypes3 re-encodings of decoded acknowledgements, not raw packet captures. Local audit failures remain visible and the returned report hash is recomputed to include that evidence. Report state is temporary; export JSON to retain a local snapshot.

## API

- `GET /api/bacnet/events/profile`: local capability/limits/active-operation status; no field traffic.
- `POST /api/bacnet/events/read`: explicit `address`, `device`, `operation_id`, optional `router`/`dnet`, `pages_per_request` (1..5), and paired `report_id`/`cursor` for continuation.
- `POST /api/bacnet/events/cancel`: `operation_id`; cancels only this operation and never sends a field acknowledgement or write.

POST requests require the Studio session token. Admission/schema errors are HTTP 422. Admitted acquisitions return an evidence report even when the device replies unsupported, times out, or only some pages succeed. A caller-level task cancellation still propagates while retiring its owned exchange.

## JCI applicability and verification

This is a standard exposed-service client, not a JCI proprietary program/alarm database reader. Whether an FX-PCV/VMA/NAE model and firmware execute this service must be checked against that exact product's PICS and a real response. The collected [FX-PC PICS, 2019-03-22](https://s3.us-east-2.amazonaws.com/buildingcontrolsgroup.media/downloads_1/12011658.PDF) and [Field Equipment Controller PICS, 2017-12-01](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Field-Equipment-Controllers-Protocol-Implementation-Conformance-Statement) are release-specific references, not evidence that every JCI controller supports this query. Engine-proxied summaries, where exposed, remain summaries from the explicitly addressed engine.

Validation uses authored devices on real loopback UDP plus an independently framed IPv4-to-MS/TP router. It covers native choices/unresolved clocks, pagination/replay/source identity, unsupported services, malformed/incorrect acknowledgements, bounds, timeout retention, cancelled pre-invoke dispatch, explicit cancellation, and interface teardown. Browser tests use those real peers and check explicit traffic, inspection, JSON/CSV export, unsupported outcomes, and navigation cancellation. No site devices, credentials, or physical BTCVT were used.
