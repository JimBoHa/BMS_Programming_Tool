# BACnet change-of-value monitoring

**Connect → Change-of-value monitoring** receives object-level notifications from
one explicitly selected direct BACnet/IP endpoint or downstream DNET:MAC through
an explicit IPv4 NAE/router. Open an IPv4 interface, select the source path,
enter its address/route, expected Device identifier and monitored object, choose
confirmed or unconfirmed notifications, and start the monitor. The application reads back
the exact Device and object identities before requesting a subscription.

This implements direct and explicitly routed IP profiles of feature audit
**IA-c6c0348b91**. The routed profile supports a one-byte unicast MS/TP MAC,
DNET 1–65,534, and unsegmented notifications. A loopback UDP router and virtual
downstream data link test the actual NPDU route; MS/TP token timing, site NAEs
and physical devices are unverified. It uses
standard BACnet services and is useful for JCI FX/Metasys devices that accept
those services. The tests use real isolated UDP peers, not physical JCI devices.
Native application compilation, transfer, controller programming and sensor
quality verification remain separate capabilities.

## Lease and lifecycle

Each subscription has a requested finite lifetime of 5–3,600 seconds. **Renew
COV lease** explicitly requests the same lifetime again. There is no automatic
renewal, reconnection, device discovery, restart restoration, or point-value
write. Expired monitors require a new verified start.
Leaving the Connect tab does not stop an active finite lease.

**Stop COV monitor** sends a cancellation while the original interface is still
available. Acknowledged cancellation and an uncertain outcome are displayed
separately. If cancellation or renewal times out, a remote subscription may
remain until its finite lease expires. The application stops local capture and
does not retry after returning. Expiry is based on the local monotonic clock;
it does not independently read back remote subscription state.

Closing/replacing/changing the interface retires capture and restores only this
manager's notification handlers. It does not reconnect or send cancellation
through a changed path. Application shutdown explicitly cancels subscriptions
that still have their original interface. An operation already in progress is
joined before shutdown completes. Each exchange has a three-second deadline;
only its exact native transaction and dispatch are retired on timeout or
cancellation.

## Received evidence and limits

Notifications must match the selected source endpoint, initiating Device,
monitored object, subscriber process identifier, confirmation mode and active
lease. Routed notifications additionally require the actual IPv4 next hop and
NPDU source DNET/MAC to match their selected route. These are captured before
the native stack strips routing metadata. Broadcast/BBMD-forwarded notifications
are rejected. Mismatches are ignored and counted; mismatched confirmed
notifications receive an unknown-subscription error. Other application-owned subscriptions
keep their original handlers. There is no unbounded notification queue.

Evidence retains receipt time, Device/object/process/source identity,
confirmation mode, reported remaining lifetime, property identifiers, optional
array indexes, optional priority, decoded values and encoded-value evidence.
Status flags and reliability are retained when sent; receipt alone does not
prove a good sensor or current physical value. Unknown vendor properties stay
opaque, with bounded tagged-byte previews and hashes. Decode errors retain the
encoded evidence rather than inventing a value. Nonfinite values remain typed
JSON evidence. Device event timestamps are not inferred from receipt time.

The manager permits eight active monitors, 32 retained monitor records, 100
notifications per record, 32 properties per notification and 16 KiB of serialized
evidence per notification. Old notifications are evicted with a visible dropped
count. Retired monitor evictions are also counted. Oversized/unsupported
notifications are rejected and counted. Local
status returns the latest three notifications per record; **Export COV
evidence** retrieves all currently retained session notifications. Without
explicit recording, these samples remain in memory and disappear after restart;
lifecycle audit metadata uses the ordinary local audit store. Opt-in durable
receipt/trend recording is described below. COV monitoring is not an alarm
subscription.

BBMD/foreign-device, direct serial and BTCVT configurations remain unsupported.
Routed segmented notifications are refused, rather than inferring a return path
from a mutable router cache. It does not provide SubscribeCOVProperty, COV increment
configuration, automatic polling fallback, or EventNotification monitoring.
Those are remaining work, not implied by this profile.

## API and validation

- `GET /api/bacnet/cov/status`: limits and monitor summaries/recent evidence.
- `GET /api/bacnet/cov/jobs/{id}`: the complete retained monitor evidence.
- `POST /api/bacnet/cov/start`: `address`, `device`, `object_id`, `lifetime`,
  `confirmed`, optional paired `router`/`dnet` for an exact routed address, and
  optional strict boolean `record_observations` (defaults false).
- `GET /api/bacnet/cov/recordings`: locally saved recording sources and counters.
- `GET /api/bacnet/cov/recordings/{id}/events?after=0&limit=100`: locally saved
  evidence with a nonnegative sequence cursor and limit 1–1,000.
- `POST /api/bacnet/cov/renew` and `/stop`: `id`.

Mutating routes require the normal loopback origin/session protections. Tests
cover real confirmed/unconfirmed UDP notifications, changes, identity/source
filters, cancellation, rejection/timeouts, pending native dispatch cancellation,
explicit renewal across expiry, shutdown/start races, interface replacement,
retention/capacity and HTTP/browser operation. The implementation follows the
pinned BACpypes3 0.0.110 APDU, datatype, application and COV service definitions.
It intentionally avoids that library's automatic subscription renewal and
unbounded subscription queues.

## Explicit routing and response ownership

Subscribe, verification reads, renewal and cancellation reuse the existing
serialized Device-details path. The engineering interface configuration stays
unchanged; its default route does not replace the monitor's selected route.
Only a separately validated COV notification may pass another route's temporary
read filter. Other service replies keep the original exact-source filtering.

Owned notification responses use a task-local ContextVar for the selected route.
The native adapter checks that context at the final outbound boundary, so a
changed route cache or another temporary operation cannot redirect the ACK.
Other tasks and other service traffic keep their original routing. ACK invoke
IDs come from the actual received confirmed request. Hooks preserve prior
transport/user data and handlers, and retire on the final monitor's stop,
expiry, interface change or shutdown.

The Connect form defaults to the selected router/network. Changing its source
clears stale identities; changing the parent selection while a start is pending
does not relabel that monitor. The completed action identifies its original
source, and each monitor/export retains its own immutable route configuration.

## Opt-in durable receipts and field trends

**Record COV receipts and eligible trends locally** is off initially and resets
when the source selection changes. Select it before starting a monitor. A normal
monitor still keeps only its bounded session evidence; opting in creates a
separate durable `cov/<monitor-id>` source in the **existing field observation
SQLite store**. Source provenance identifies the acquisition as `bacnet-cov`,
the verified Device and object, connector configuration, explicit route, process
identifier and notification mode. Accepted notification rows retain their actual
next-hop/NPDU source evidence and native property values, array indexes, priority,
encoded values and decoding/type information. Invalid packets are counted as
rejected evidence, never promoted into samples.

Notification callbacks and confirmed ACK handling perform no SQLite writes.
They submit evidence to a bounded 64-item queue; a single background writer
commits receipts and eligible samples atomically off the event loop. Queue loss,
rejected packets, explicit renewals, stops, local expiry, interface changes and
remote cancellation outcomes are recorded separately. A database failure stops
recording, exposes a storage error and counts omitted notifications; it does not
turn off the finite monitor or suppress confirmed ACKs. Failed notification
writes are never silently retried. If even the final gap/closure cannot be saved,
the next process marks the source interrupted with an **unknown uncommitted
tail**. Durable counters alone cannot measure that tail.

COV provides no controller timestamp in this profile. `received_at` is this
computer's UTC receipt/event time; `recorded_at` is the separate local commit
time. `source_clock` remains null and `clock_basis` is `receipt`. Backward or
repeated receipt-clock readings remain unchanged, accompanied by a clock anomaly
event. No controller time is guessed and no monotonic timestamp is fabricated.

Only one unambiguous decoded, finite numeric/boolean present-value can become a
trend sample. Unknown, opaque, nonfinite, array-valued or conflicting values stay
raw evidence. Native datatype checks exclude numeric-looking enumerations other
than BinaryPV. Trend quality stays **unknown** for absent or normal received
statusFlags; an actual fault flag gives `fault`, and other asserted status flags
give `unreliable`. A notification never establishes good sensor quality. Units
are left empty rather than inferred. These samples share **Field trends** with
polled values while retaining their own provenance, receipt-clock labels and CSV
columns; no polling job is created.

Use **Load saved COV observations** in Connect to reopen local history after a
restart. It performs local reads only. Select a recording, inspect its raw source
and receipt evidence, page forward/backward, or **Download saved COV page** as
JSON (at most 100 events per displayed page). The saved list includes durable
loss/rejection counts, retained evidence eviction counts and evicted trend links
for still-retained receipts. Field trends also exports each displayed sample page
as CSV, including COV provenance. Refresh these views explicitly for current
committed recording counters. New subscriptions and recording are never resumed
automatically. An OS-owned lock permits only one COV writer per field workspace;
other processes may read history, but opt-in recording rejects until ownership is
released. Lock support uses POSIX flock or Windows byte locking; actual Windows
execution remains unverified.

Default raw evidence retention is **5,000 events across COV sources**; old rows
are removed and their source's eviction counter increases. Numeric samples obey
the field store's existing 100,000-sample retention. Receipt and sample retention
are independent; the `samples_evicted` count covers references in retained raw
evidence only. Source capacity is shared with polled sources (256 by default).
Deleting an ended source through **Delete ended field history** also deletes its
COV raw receipts/provenance. Open sources cannot be deleted through that action.
Recording adds no point writes, auto-renewal, reconnect, BBMD, serial/BTCVT, native
JCI application transfer or physical MS/TP validation.

Additional tests use actual direct and routed loopback UDP notifications plus
SQLite and guarded HTTP: opt-in/off, native/opaque values and source provenance,
confirmed ACK continuity during storage failure, queue overflow, rejected packet
accounting, finite expiry/interface closure, writer ownership, cancellation before
Subscribe, retention and restart unknown-tail recovery. Browser tests exercise
explicit opt-in, source-change reset, saved history reopen, JSON download and
Field trends/CSV provenance against an actual loopback UDP publisher. These
virtual downstream devices do not establish physical JCI interoperability.

## Original evidence JSON downloads

Job exports and saved receipt pages retain the original HTTP response bytes. Native integral floats and signed zero survive browser download. Saved pages bind source metadata, requested and returned page boundaries, counters and retention in one local SQLite read snapshot; metadata/counters may change later. See [COV evidence downloads](cov-evidence-downloads.md) for guards, bounds and validation.
