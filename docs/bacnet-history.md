# BACnet Trend Log history

Device history retrieves records already stored by a standard BACnet Trend Log
object. It sends actual `ReadRange` requests for the addressed object's
`log-buffer`. It uses the shared BACnet connector and its configured routing;
it never opens a connection, discovers devices, subscribes, polls in the
background, clears a log or writes a device property.

Device history is separate from simulated observations and from live field
point polling. Its reports and optional saved captures use
`source_kind: "device-history"`. No old records are inserted into the simulator
or live polling databases.

## Explicit retrieval

Python: `BacnetHistory(bacnet, store_or_directory=None)` exposes:

- `await read(**BacnetHistoryRequest.model_dump())`: one bounded retrieval.
- `status()`: connector health, protocol profile, limits and saved summaries.
- `save(id)`: explicitly save one of the eight recent server-created reports.
- `captures()`: saved capture summaries.
- `capture(id)`: verified saved report, including its original records.

The local HTTP routes are:

| Route | Purpose |
| --- | --- |
| `GET /api/bacnet/history/status` | Read-only profile and connector health |
| `POST /api/bacnet/history/read` | Request the addressed log history |
| `POST /api/bacnet/history/save` | `{id}`; explicitly save a returned report |
| `GET /api/bacnet/history/captures` | List saved summaries |
| `GET /api/bacnet/history/captures/{id}` | Read a verified saved report |

The read body accepts:

```json
{
  "address": "192.0.2.10",
  "object_id": "trend-log,1",
  "device_timezone": "America/Los_Angeles",
  "mode": "sequence",
  "reference": 100,
  "count": 100,
  "page_size": 25,
  "fold": null
}
```

The address can also be a configured routed station such as `2201:4`, or a
decimal remote MAC when using the direct MS/TP connector. Existing connector
unicast/own-MAC rules apply. The request permits only standard single-value
`trend-log` objects; Trend Log Multiple and proprietary log formats are outside
this profile.

Modes `position` and `sequence` use an integer `reference`; positions begin at 1.
The default is position 1. Time mode instead requires an aware
`reference_time`, omits `reference`, and converts the requested instant into the
selected device clock timezone for the BACnet request. BACnet dates are limited
to 1900..2154 and times to whole hundredths of a second. Counts are positive and
forward only; reverse ranges are not implemented.

## Timestamps and quality

BACnet Trend Log records contain device-local dates/times without a UTC offset.
The operator must supply the timezone used by that device's clock; it is never
guessed from the laptop or network. Each report records the zone name,
available tzdata package version and available zone-file SHA-256.

Every row retains its raw `local_timestamp` date/time fields.
`source_clock` is the corresponding UTC acquisition time only when those fields
can be resolved. `recorded_at` is the UTC receipt time of that page on this
computer. A historic device timestamp is never replaced with the receipt time.

Unresolved wildcard fields, conflicting weekdays and nonexistent DST local
times retain `source_clock: null` with `timestamp_error`. A missing weekday
alone does not prevent converting an otherwise complete calendar date.
Repeated DST hours remain unresolved unless the operator explicitly supplies
`fold: 0` or `fold: 1`. That selection applies to **all ambiguous records in the
request**. It cannot automatically distinguish two occurrences of the same
local time in a buffer spanning the DST transition; separate reads/operator
knowledge may be needed. The original raw fields and timezone choice remain
in the report.

All eleven standard `LogRecord` datum alternatives are handled. Finite numeric
and Boolean values retain their actual value; enumerated values remain numeric
codes without guessed engineering units. Historic record flags determine
`good`/`unreliable`; missing flags yield `unknown`. An in-alarm flag alone does
not make the acquired value unreliable. Reliability is not separately recorded
by this BACnet datatype, and the report states that quality scope.

The integer result profile is signed 32-bit or unsigned/enumerated 32-bit. A
nonconforming longer integer payload is retained as explicit fault/non-sample
evidence, with exact decimal text for bounded values and a hash of its canonical
decoded integer bytes. It never becomes a lossy JavaScript JSON number.

Status, failure, null, bitstring, clock-change and opaque records remain visible
as their original alternatives with `sample: false`. Failure/nonfinite values
do not become zero. A numeric/Boolean record with an unresolved timestamp also
has `sample: false`. Opaque values retain their byte count, full encoded SHA-256
and at most 1024 encoded bytes, with an explicit truncation flag.

## Pagination, errors and limits

Reads run sequentially under the connector's shared lock. They capture its
exact application/configuration, recheck it before each page and stop on
connection faults or changes. Each page validates reply source, object,
property, count, flags and record encoding. Device errors, malformed ACKs and
timeouts never manufacture records. Errors before the first valid page fail
the request. Later failures return received records with explicit errors and
`truncated: true`. Caller cancellation retires the wire transaction and releases
the lock; no background continuation is scheduled.

The adapter retains result flags and sequence anchors instead of using the
library's convenience helper, which returns only decoded values. `moreItems`
reports that the requested range did not fit in an APDU; it is **not** a general
end-of-buffer flag. The adapter also checks `lastItem` and continues valid
forward requests until the requested count, end, error or bound. Sequence
numbers wrap from 4294967295 to 1. Sequence jumps/repeated pages stop the read
with an explicit gap error, and a requested start preceding retained history is
disclosed.
The returned sequence span must fit the actual requested forward window.
A request entirely before retained history can return an empty range; it does
not implicitly fetch unrelated later records. Empty reply sequence metadata
does not create an artificial sample.

A by-position response may legally omit its first sequence number. Such a page
keeps `sequence: null`; automatic continuation stops rather than guessing a
live buffer's identity. Its explicit position cursor remains available for a
separate read. Sequence mode is preferable for automatic pagination. By-time
and by-sequence nonempty responses must supply their sequence metadata.

`complete` means the forward retrieval reached the end/no matching records.
`truncated` means the requested count, page limit or an error stopped it before
that conclusion. The requested start/range remains part of the report;
completion does not claim records purged before that range were recovered.
`next_cursor` describes a possible separate explicit request and is never
automatically followed after returning.

Bounds: 1000 requested records, 100 records per page, 100 pages, 2 MiB encoded page
or decoded report, 3 seconds per request and 30 seconds per complete operation by
default. The operation deadline includes waiting for the shared connector
lock. Timeouts are configurable within the documented status limits. Smaller
pages may be needed for devices that do not segment large responses.

## Explicit immutable captures

Reading alone keeps a bounded recent in-memory report cache. Saving accepts a
server-created report ID, never caller-supplied replacement evidence. Captures
are written under the application's `bacnet-history` directory with restricted
file permissions, fsynced data/directory and atomic creation without replacing
an existing capture. A canonical JSON SHA-256 seal is checked on every saved
read; summaries expose that hash. This detects accidental edits, rather than
providing a cryptographic signature from the controller.

Storage is bounded to 32 captures and 32 MiB. Capacity exhaustion refuses a new
save; it never silently deletes prior evidence. Restart lists saved captures
but neither reconnects nor rereads any device. JSON/CSV downloads are local
exports of the retrieved record evidence.

Capture reads reject symlinks, FIFOs and other nonregular files before reading,
and reject oversized, deeply nested or malformed saved metadata. A cross-process
save lock has a two-second acquisition deadline and does not hold the report
cache lock while waiting. A stale temporary file from a prior interrupted save
does not prevent retry or get overwritten.

## Provenance and verification

The service uses installed BACpypes3 **0.0.110**, whose local primary-source
checkout is revision `21f918c0396c72c95e7e635abde18514e58feb8d`. Relevant primary
implementations are the
[ReadRange request/ACK definitions](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/apdu.py),
[LogRecord/range datatypes](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/basetypes.py)
and [object service](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/service/object.py).
The primary [ASHRAE 135-2001 Addendum b](https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-2001-135b.pdf)
documents the switch to local Trend Log timestamps and the sequence ordering,
including wrap to 1. These references establish this implemented profile; this
application does not claim BACnet certification or universal device support.

`tests/test_bacnet_history.py` uses an independently authored device service
with a real `TrendLogObject` buffer and actual BACpypes UDP encoding. It covers
pagination/flags, sequence wrap/gaps, time requests, DST/wildcards, all datum
alternatives, quality, device/malformed errors, partial results, deadlines,
cancellation, explicit saves/restart/integrity and routed UDP-to-virtual-link
delivery. `tests/test_bacnet_history_api.py` exercises the real HTTP lifecycle,
security and separate durable capture storage. These tests use only loopback
and virtual links; they do not establish acceptance by a particular physical
controller, router or MS/TP trunk.
