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
evidence** retrieves all currently retained notifications. Samples are in memory
and disappear after restart; lifecycle audit metadata uses the ordinary local
audit store. This is not durable trend acquisition or an alarm subscription.

BBMD/foreign-device, direct serial and BTCVT configurations remain unsupported.
Routed segmented notifications are refused, rather than inferring a return path
from a mutable router cache. It does not provide SubscribeCOVProperty, COV increment
configuration, automatic polling fallback, or EventNotification monitoring.
Those are remaining work, not implied by this profile.

## API and validation

- `GET /api/bacnet/cov/status`: limits and monitor summaries/recent evidence.
- `GET /api/bacnet/cov/jobs/{id}`: the complete retained monitor evidence.
- `POST /api/bacnet/cov/start`: `address`, `device`, `object_id`, `lifetime`,
  `confirmed`, and optional paired `router`/`dnet` for an exact routed address.
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
