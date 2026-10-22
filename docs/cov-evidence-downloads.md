# Original COV evidence downloads

Live COV job exports and saved receipt-page JSON preserve the original HTTP
response bytes. Parsing and rebuilding a response with JavaScript changes
`2.0` to `2`, `-0.0` to `0`, and some exponent/large-number spellings. These
exports retain the actual native numeric evidence without client normalization
or replacement seals. COV exports do not gain a new whole-document signature
or manufacturer-authenticity claim.

The existing saved-events GET returns an array of receipts. It cannot by itself
provide recording metadata, the requested cursor/limit, or a matching retention
boundary. Combining separately parsed metadata/events in the browser both
loses numeric spellings and can combine different recording states. The additive
read-only endpoint is:

`GET /api/bacnet/cov/recordings/{id}/page?after=0&limit=100`

It returns a `bms.cov-saved-page` version 1 envelope containing the selected
recording, requested `after`/`limit`, returned count/first/last sequence, retained
receipt boundary/count, known evictions, local snapshot time and native receipt
bodies. A single SQLite read transaction covers metadata, boundaries and events.
The original events/list endpoints and stored schemas remain unchanged.

Bounds retain the existing profile: cursor 0 through 2^63−1, page limit 1 through
1,000 and monitor text through 80 characters. The UI requests 100 receipts and
advances/returns explicitly. It refuses sequence identifiers beyond JavaScript's
exact safe-integer range rather than silently changing a cursor. The server's
bounded JSON endpoint remains available for exact integer consumers.

Receipt sequence numbers are global across recordings. A numeric gap alone
does not prove omitted controller notifications. Retention boundaries describe
that local snapshot, not a complete historical capture. Recording counters,
closure receipts and retention can change while a recording runs or shuts down;
earlier native receipt bodies are not recomputed by export. Controller time,
current liveness, sensor quality and physical JCI support retain their existing
limits.

The browser stores the parsed page and its authoritative Blob together. It
checks exact recording/source/store/process/config identity, requested cursor
and limit, returned ordering/count/boundaries and receipt source before showing
or downloading a page. A failed load clears the prior document. New selections,
pages, refreshes and unmounts invalidate earlier responses. Opening saved
observations starts no field operation, and later downloads save the retained
page without another query.

Job exports retain the original detail response. Exact job ID, original source
configuration, interface identity and receipt Device/object/process/mode/route
must match the selected job. A changed controller selection, removed/changed job,
hidden panel or navigation suppresses a delayed download. Other subscription,
recording, ACK, renewal and cancellation behavior is unchanged.

Validation uses real loopback COV notifications with integral Real values,
signed zero and small/large magnitudes. Independent Python reads the actual
browser files and compares exact response bytes and SHA-256 digests. Saved
pages are compared with stored native receipts, and API tests reopen them after
restart without a connection. A concurrent SQLite commit between metadata and
receipt queries verifies snapshot consistency. Browser tests cover 100-row
paging, wrong identity/source/cursor/boundaries, malformed/error responses,
controller-selection changes and delayed navigation. No physical interfaces,
site devices, point writes or manufacturer tools are involved.
