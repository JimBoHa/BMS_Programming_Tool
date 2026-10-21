# BACnet change-of-value monitoring

**Connect → Change-of-value monitoring** receives object-level notifications from
one explicitly selected BACnet/IP endpoint. Open a direct IPv4 interface, enter
the endpoint, expected Device identifier and monitored object, choose confirmed
or unconfirmed notifications, and start the monitor. The application reads back
the exact Device and object identities before requesting a subscription.

This implements the direct-IP profile of feature audit **IA-c6c0348b91**. It uses
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
lease. Broadcast/BBMD-forwarded notifications are outside this direct profile
and are rejected. Mismatches are ignored and counted; mismatched confirmed
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

This first profile rejects routed MS/TP, BBMD/foreign-device, direct serial and
BTCVT configurations. It does not provide SubscribeCOVProperty, COV increment
configuration, automatic polling fallback, or EventNotification monitoring.
Those are remaining work, not implied by this profile.

## API and validation

- `GET /api/bacnet/cov/status`: limits and monitor summaries/recent evidence.
- `GET /api/bacnet/cov/jobs/{id}`: the complete retained monitor evidence.
- `POST /api/bacnet/cov/start`: `address`, `device`, `object_id`, `lifetime`,
  `confirmed`.
- `POST /api/bacnet/cov/renew` and `/stop`: `id`.

Mutating routes require the normal loopback origin/session protections. Tests
cover real confirmed/unconfirmed UDP notifications, changes, identity/source
filters, cancellation, rejection/timeouts, pending native dispatch cancellation,
explicit renewal across expiry, shutdown/start races, interface replacement,
retention/capacity and HTTP/browser operation. The implementation follows the
pinned BACpypes3 0.0.110 APDU, datatype, application and COV service definitions.
It intentionally avoids that library's automatic subscription renewal and
unbounded subscription queues.
