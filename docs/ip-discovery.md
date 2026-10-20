# Explicit BACnet/IP device discovery

IP discovery sends read-only Who-Is requests on an already opened BACnet/IPv4
interface. Opening the application, viewing status, or changing scan inputs
does not connect an interface or start discovery. It does not send routed or
global-network Who-Is, modify controller properties, or retrieve native programs.

`IpDiscovery(bacnet, store).scan(**parameters)` implements
`POST /api/bacnet/scan-ip`; `IpDiscovery.status()` implements
`GET /api/bacnet/ip-scan-profile`. The strict request model is `IpScanRequest`.

## Connect tab workflow

1. Open the intended BACnet/IP interface in **Connect**. Choose the local
   interface address that reaches the desired network; an unopened interface
   does not scan automatically.
2. In **Scan**, select local network, single IP, or IP range. Set the UDP port,
   optional Device-instance bounds, response window and result limit, then
   select **Scan BACnet/IP devices**. A larger range has an explicit continuation
   button; changing its inputs clears that continuation.
3. Run **Routed BACnet discovery** with an explicit router and DNET to add its
   actual Who-Is responses to the same list. **View named Scan results** returns
   to the combined list. Reading the router's cache alone does not add live
   discovery observations.
4. Device details load sequentially for the displayed 20-row page. **Stop**
   ends the queue after the current bounded device request. Resume or retry
   the shown page as needed. Moving pages reads details for the new page unless
   the queue is stopped; select **Resume shown-page details** to continue.
5. Filter by IP/routed source, search received metadata, sort, inspect a row's
   evidence, or export all retained results as CSV/JSON. Page membership stays
   stable as metadata arrives; **Refresh search and sort** applies newly read
   names and values. Exports include
   non-displayed pages and partial/error states. Export is enabled after the
   current read completes, including when the queue is stopped.
6. A row's **Use** action fills the commissioning target and, for routed
   devices, the router/DNET draft. It does not open another interface or send
   a controller write. Ordinary routed point operations still require opening
   the matching commissioning route.

The list retains at most 2,048 distinct identities, 32 discovery scopes and
512 response pages. Capacity refusal is visible; export and clear results
before collecting more. A repeated scan replaces its scope's current window;
previous observations remain labelled earlier rather than silently becoming
fresh. Range continuation retains the original bounds and page provenance.
Results last for the current Connect workspace; export them before leaving
the page. A saved export is evidence, not a guaranteed current inventory.

## Modes and bounds

Local discovery uses the actual subnet of the opened IPv4 interface:

```json
{ "mode": "local", "udp_port": 47808, "timeout_seconds": 3.0 }
```

The service resolves the matching interface's network prefix with `ifaddr`.
It does not guess a `/24`. An explicit connection prefix is a fallback when no
matching interface prefix is available; a prefix that conflicts with an observed
interface is rejected for local broadcast. Point-to-point `/31` and `/32`
interfaces, including typical Tailscale addresses, require single-IP or range
mode. A normal connection sends Original-Broadcast-NPDU to that subnet's
broadcast IP and the selected UDP port. The NPDU has no routed/global destination.
Direct I-Am evidence must come from the same subnet and selected UDP port.

On an already registered foreign-device connection, local mode means the
configured BBMD's BACnet/IP network. It sends Distribute-Broadcast-To-Network
through that existing registration and reports `broadcast_scope: "bbmd-network"`;
normal local broadcast reports `"local-subnet"`. The requested UDP port must
match the registered BBMD port. Forwarded-NPDU evidence is accepted only from
that exact configured BBMD IP/UDP endpoint. Each device retains its embedded
original endpoint and the forwarding BBMD. Plain connections ignore forwarded
packets from unconfigured BBMDs. No registration or subnet setting is changed
by discovery, and unhealthy foreign registration stops the operation.

Single-IP discovery addresses exactly one literal IPv4 endpoint:

```json
{
  "mode": "single",
  "ip": "192.0.2.32",
  "udp_port": 47808,
  "timeout_seconds": 3.0
}
```

Range discovery pages through explicit inclusive host bounds:

```json
{
  "mode": "range",
  "start_ip": "192.0.2.1",
  "end_ip": "192.0.5.254",
  "udp_port": 47808,
  "timeout_seconds": 3.0,
  "max_devices": 256
}
```

An original range may contain at most 65,536 addresses. A request processes at
most 256 addresses, with at least 0.05 seconds between transmissions: at most
20 requests per second. The response window runs after the final transmission.
If `next_ip` is returned, continuation requires another explicit request with
the same original bounds and `cursor_ip` set to that address. There is no
automatic continuation. The cursor must remain inside the original range.

Single and range modes always send Original-Unicast-NPDU directly to each
chosen endpoint, including on a foreign-device connection. They do not use
automatic router lookup or BBMD distribution. Responses must identify an
endpoint actually addressed on the current page. Known local subnet network
and broadcast addresses, and the engineering client's own exact socket, are
skipped in range mode and retained in `skipped_targets`; the cursor advances
past them. Single mode rejects these targets. Remote subnet masks are not
guessed. Hostnames, prefixes in target fields, multicast, unspecified addresses,
limited broadcasts, and out-of-range ports are rejected.

All modes accept optional `low` and `high` Device-instance bounds, defaulting
to 0 through 4,194,302. The response window is 1–10 seconds; results are capped
at 256 endpoint/Device pairs. Collection has a 4,096-packet observation budget
and considers at most 2,048 NPDU bytes per packet. The entire send/window phase
has a 30-second deadline. Admission to the shared connector lock takes at most
five additional seconds. Restart does not resume discovery.

## Interpreting evidence

Reports retain the original request, connector configuration, actual subnet
and prefix provenance, broadcast scope, requested range count, page count,
processed targets, submitted UDP destinations, skips, explicit continuation
cursor, receipt times and warnings. `targets_sent` means submitted to the
existing UDP transport; it is not an acknowledgement from the destination.

Each device row retains IP, UDP port, Device identifier, vendor identifier,
maximum APDU size, segmentation, first/last local receipt UTC timestamps and
announcement count. The four I-Am application fields must have valid types and
values. Routed source addresses are excluded from this IP-device inventory.
The engineering endpoint is excluded by its actual IP and UDP port, with
`ignored_self_packets`; its Device instance alone is never an exclusion rule.

Repeated announcements for the same endpoint and Device increment a count.
Different Device instances at one endpoint, or the same instance at different
endpoints, remain distinct rows. Conflicting capabilities generate a warning;
the first observed values are retained. `source_paths` records direct and
configured-BBMD forwarding paths when both are seen.

`complete` means the requested page/window finished without reaching a result,
packet or operation bound and no later target remains. It does not establish
an exhaustive inventory, previous page completion, or controller liveness
after the observation window. `response_window_complete` distinguishes a
finished response window from a bounded interruption. Missing responses remain
unknown. Who-Is has no transaction identifier; received announcements are
scoped evidence rather than an authenticated challenge response.

The service checks application identity, connector configuration, UDP health
and foreign registration while it runs. A change or fault stops it. Its
temporary link-layer observation handler delegates normal traffic and restores
the previous handler on success, failure and cancellation. It does not change
the opened interface, selected commissioning route, global route-awareness
setting, owned commands or controller data. Audit persistence failure is
reported separately from received discovery evidence.

## Local verification and provenance

`tests/test_ip_discovery.py` uses an independent raw UDP peer and literal
BVLC/NPDU/APDU encodings, with production BACpypes transport and service code.
Tests cover exact unicast bytes/destinations, explicit paging, pacing, source
port checks, duplicates and conflicts, malformed I-Am, unknown responses,
bounded partial reports, cancellation, busy/configuration changes, interface
faults, local subnet selection, and foreign registration/forwarding/source pins.

macOS does not deliver unbound `127.0.0.2` addresses or loopback subnet
broadcasts to the test listener. Range destination assertions therefore observe
encoded datagrams at the real UDP transport's `sendto` boundary; responsive
`127.0.0.1` uses actual UDP and other addresses remain unknown. The local
broadcast test records and attempts the actual broadcast destination, then
explicitly mirrors the identical encoded packet over real loopback UDP to the
independent peer. This mirror exists only in the test harness. Production has
no delivery substitution. These tests do not prove physical LAN broadcast
delivery or discover any building devices.

Primary references are the pinned
[BACpypes3 BVLC codecs](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/ipv4/bvll.py),
[normal and foreign link behavior](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/ipv4/service.py),
[Who-Is/I-Am service implementation](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/service/device.py),
and [ifaddr 0.2.0](https://pypi.org/project/ifaddr/0.2.0/). No upstream source is
modified or copied by this module.
