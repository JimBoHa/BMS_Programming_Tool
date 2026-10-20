# BACnet/IP foreign-device connection through a BBMD

The BACnet connector can explicitly register as a foreign device with one
existing IPv4 BBMD. This adds cross-subnet broadcast discovery while preserving
the existing unicast point services and optional BACnet network/router paths.
It does not host a BBMD or change its distribution table, and it does not
compile or download controller programs.

The registration and renewal task starts only after an explicit Connect
request. Loading a saved configuration after restarting the tool does not open
a socket, register or discover devices.

## Connection and API

```json
POST /api/bacnet/connect
{
  "local_address": "192.0.2.20:47809",
  "instance": 4190001,
  "bbmd_address": "198.51.100.10:47808",
  "foreign_ttl": 60
}
```

These are documentation addresses, not a suggested site configuration. The
local IP must belong to this computer. The BBMD must already exist and permit
foreign registrations. The TTL is an actual integer from 1 through 65535
seconds; default 60. Local and BBMD endpoints must be separate IPv4 endpoints;
the BBMD port cannot be zero. Router/dnet remain optional as in the existing
BACnet connector. Invalid settings are checked before closing a working
interface. Omitting the BBMD preserves the existing normal connection/config
shape and does not issue registrations.

Python callers use:

```python
await bacnet.connect(local_address, instance=4190001,
                     router=None, dnet=None,
                     bbmd_address=bbmd_address, foreign_ttl=60)
devices = await bacnet.discover_foreign(low=1000, high=2000)
```

`POST /api/bacnet/discover-foreign` accepts `{low, high}`. This explicit action
sends one local-broadcast Who-Is through the configured BBMD using BVLC
Distribute-Broadcast-to-Network. Device replies arriving in Forwarded-NPDU
messages retain the original device address, which is used for later point
reads/commands. Existing `/api/bacnet/discover` remains addressed unicast.
Broadcast discovery requires an active foreign registration; it never falls
back to local/global broadcasts when that registration is unavailable.

Discovery collects for at most two seconds; its six-second operation deadline
includes waiting for the shared connector lock. The result collector is bounded
to 1000 unique device instances. Reaching that limit rejects the result with an
explicit instruction to narrow the instance range. The underlying BACpypes
collector identifies devices by instance, so this feature is not a diagnostic
for conflicting duplicate device instances at different addresses.

## Registration lifecycle and status

Initial registration must receive a valid six-byte BVLC Result from the exact
BBMD IP/port within three seconds. Results from another endpoint, unsolicited
results and malformed result lengths cannot acknowledge registration. A
rejection or missing initial acknowledgement closes the new socket/task and
returns an explicit connection error.

This connection opens one local unicast UDP socket rather than a separate local
broadcast listener. Closing also cancels pending endpoint-bind retry tasks;
failed initialization does not leave a retry worker that can later open a
socket after the connection request already failed.

Successful registrations renew periodically while the connection remains open.
The managed task renews at 80% of the configured TTL. Lost renewal responses do
not immediately invent a disconnection: the prior lease remains valid through
its TTL plus the standard 30-second BBMD grace period, capped to 65535 seconds.
The conservative expiry clock starts at the acknowledged request's send time,
so ACK latency does not extend the assumed remote lease. A rejection or lease
expiry marks the connection unhealthy and stops the worker; explicit reconnect
is required. A dead local UDP transport also reports unhealthy.

`GET /api/bacnet/status` includes `foreign_device` (null for normal/MS/TP
connections), with:

- Registration/connection state, BBMD address, TTL and status code.
- Last request send and acknowledgement UTC timestamps.
- Remaining assumed lease, lease duration and grace period.
- Attempt, acknowledgement and ignored-result counters.
- Worker/socket state and explicit registration/deregistration errors.

Top-level `connected` and `require()` incorporate registration health, so
existing services do not silently operate through a failed foreign connection.
Reconnect with the same configuration is permitted after failure. When the tool
owns priority commands, changing the BBMD, TTL, interface or router path is
refused; the exact saved configuration can be reopened to recover and
relinquish those commands. No priority is relinquished automatically.

Disconnect/close cancels the renewal task, clears local registration state and
sends best-effort standard TTL=0 through the existing UDP socket before closing
it. This does not claim that the BBMD acknowledged deletion. Renewal must stop
even if recording pending command ownership during shutdown raises a local
audit error; ownership remains available for later explicit recovery.

## Scope and evidence

This is BACnet/IPv4 Annex J foreign registration. It does not provide BACnet/SC,
IPv6 BVLL, a VPN, NAT traversal, encryption or BBMD configuration. Registration
does not make otherwise unreachable unicast device/router addresses reachable;
normal IP routing/firewall rules still apply. BVLC results have no transaction
identifier or authentication, so an exact source IP/port check is a protocol
check rather than proof of peer identity. Physical BBMD/controller acceptance
and site networking remain unverified.

The managed adapter uses the existing pinned BACpypes3 0.0.110 data link and
codec. It owns renewal/lease cleanup rather than using the upstream foreign
link's timer lifecycle unchanged. Relevant primary sources are the
[BACpypes3 foreign data link](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/ipv4/service.py),
[BVLC definitions](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/ipv4/bvll.py)
and [ASHRAE 135-2004 Addendum m](https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-2004-135m.pdf),
which clarifies foreign-device TTL/grace timer semantics. Upstream source is
not modified by this feature.

`tests/test_foreign_bacnet.py` uses independently authored raw UDP peers with
actual BVLC registration/result/distribute/forwarded frames and fixed NPDU/APDU
fixtures. It exercises registration, malformed/rogue responses, forwarded
discovery, actual ReadProperty, real short-TTL renewal, the full **31-second
TTL+grace expiry** without a mocked clock, teardown, timeout/cancellation,
same-config recovery and resource/result bounds. A real loopback commandable
BACnet object additionally verifies owned-priority write, process-session
restart and relinquishment over the foreign connection. HTTP tests exercise
the actual registration/discovery/read/disconnect flow and request/security
validation. All traffic uses loopback sockets; no Bluetooth, site addresses,
credentials or physical devices are used.
