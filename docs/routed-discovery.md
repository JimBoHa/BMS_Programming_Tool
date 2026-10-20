# Explicit BACnet/IP routed-network discovery

The routed discovery service queries one selected IPv4 router and, in a separate
action, one selected BACnet destination network. It uses the already connected
BACnet interface. Opening this workspace does not connect an interface, discover
devices, poll a trunk, subscribe to changes or write controller properties.

## Workflow and API

1. Explicitly connect a BACnet/IPv4 interface. An existing foreign-device
   connection can also carry these addressed packets while its registration is
   healthy.
2. Query a selected router with `POST /api/bacnet/router-networks`:

   ```json
   {"router":"192.0.2.32","timeout_seconds":2.0,"max_networks":64}
   ```

   The service sends one unicast Who-Is-Router-To-Network request. It accepts
   I-Am-Router-To-Network replies only from that exact router IP/UDP port and
   retains the advertised network numbers. It never searches every router or
   sends a local or global broadcast to find one.
3. If the router is silent and its Device instance is known, explicitly read its
   standard address cache with `POST /api/bacnet/router-bindings`:

   ```json
   {"router":"192.0.2.32","device":505,"max_bindings":2048}
   ```

   This first sends a directed Who-Is restricted to that exact Device instance
   and router IP/UDP port. A matching I-Am must advertise valid APDU length,
   segmentation and vendor values. Its observed capabilities are saved in the
   client cache before one ReadProperty of Device `device-address-binding`.
   The report retains this preflight as `router_identity`. This handles engines
   that need prior directed discovery before returning a large binding cache;
   it never assumes that an unknown peer supports segmentation. Returned
   networks and addresses are **cached hints**. They do not establish liveness,
   routing support or a physical MS/TP trunk. An eight-bit MAC is presented as a
   possible MS/TP address; wider MACs remain visible with no MS/TP MAC label.
   Device instance `4194303` means unknown in this cache profile: the result keeps
   the address with `device_instance: null` and `device: null`. It is never
   offered as a valid Device identifier. Local-network cache entries are counted
   separately and do not become remote trunks.
4. Choose one known network and explicitly request
   `POST /api/bacnet/scan-trunk`:

   ```json
   {
     "router":"192.0.2.32",
     "dnet":2105,
     "low":0,
     "high":4194302,
     "timeout_seconds":3.0,
     "max_devices":128
   }
   ```

   The IP datagram remains unicast to the selected router. Inside it, the NPDU
   destination is a broadcast on only that destination network, with Hop Count
   255, matching the native BACpypes allowance. There is no global-network
   broadcast or automatic router-search fallback.
   I-Am evidence must arrive through that exact IPv4 router and carry the
   selected source network. Each row retains its actual source MAC, Device
   identifier, vendor, APDU size, segmentation and receipt timestamps. Duplicate
   announcements update a count; conflicting device identifiers or MAC
   addresses remain separate and generate a warning.
5. Explicitly select the router/network connection before ordinary addressed
   controller services. Use the discovered `DNET:MAC` address to connect/read
   that controller. Discovery does not silently replace the commissioning
   connection or its command-recovery configuration.
6. When a cache identity is unknown, or a controller does not answer Who-Is,
   identify one explicitly selected MAC with
   `POST /api/bacnet/probe-controller`:

   ```json
   {"router":"192.0.2.32","dnet":2105,"mac":7}
   ```

   The existing connection must already select that exact router and network.
   The first request reads `object-identifier` from Device wildcard `4194303`.
   A responding device supplies its actual Device identifier in both the ACK
   and property value; these must agree. The service then reads its actual
   Device object's name, vendor identifier, model, firmware revision and
   application software version. It does not require I-Am, guess a Device ID,
   or identify a controller's manufacturer from its MAC. Optional metadata
   failures remain in `errors`; absent values are omitted from `properties`.
   The result retains `router`, `dnet`, `mac`, `address`, `device`,
   `device_instance`, `live_verified`, times and the connector configuration.
   Preserve the full routed address when selecting a device: the same Device
   identifier can be encountered on different trunks.
7. Explicitly probe a bounded MAC page with
   `POST /api/bacnet/probe-trunk` when a broadcast scan remains silent:

   ```json
   {
     "router":"192.0.2.32",
     "dnet":2105,
     "mac_low":1,
     "mac_high":8,
     "per_mac_timeout_seconds":0.75,
     "spacing_seconds":0.1,
     "timeout_seconds":30.0
   }
   ```

   This sends one wildcard `object-identifier` read at a time, to at most 32
   explicitly selected MACs. It does not read all metadata for every MAC.
   `devices` holds verified identity replies. `attempts` distinguishes
   `identified`, `timeout` and protocol `error`; `no_response` keeps silence
   separate from an explicit negative response. A timeout leaves that address
   unknown. It never proves that no device exists there. The service returns
   `next_mac` if its deadline prevents attempting the entire page; continuing
   requires another explicit request. Single-controller metadata probing is a
   separate action after selecting a returned row.

The addresses above are documentation examples. No example request is issued
automatically. Direct MS/TP interfaces and hostnames, prefixes, multicast,
unspecified addresses and limited broadcasts are refused as router targets.

`RouterNetworksRequest`, `RouterBindingsRequest`, `RoutedScanRequest`,
`RouterProbeRequest`, `ProbeTrunkRequest` and
`RoutedDiscovery` are defined in
`backend/bms_tool/routed_discovery.py`. Python callers use
`await service.networks(**parameters)`, `await service.bindings(**parameters)`
`await service.scan(**parameters)`, `await service.probe(**parameters)` and
`await service.probe_range(**parameters)`.

## Evidence, bounds and lifecycle

Discovery reports include the selected router, request/receipt/completion UTC
times, connector configuration, warnings, result limits and truncation.
**`complete` for a scan means its response window finished.** It never proves
that every controller answered or that an empty network has no controllers.
Who-Is has no transaction identifier; matching announcements received during
the window are evidence, not authenticated responses to a unique challenge.

The collector retains at most 128 advertised networks or 256 discovered
device/address pairs. Requested response windows are 1–5 seconds for router
networks and 1–10 seconds for a selected trunk. Lock admission takes at most
five seconds. Selected-router observations are bounded to 4096 packets, with
at most 4096 APDU bytes considered per observation. Reaching a packet budget
stops the window and marks it incomplete/truncated. A result cap retains a
bounded partial inventory and discloses truncation. Defaults are smaller than
the upper limits.

Address-binding identity preflight takes at most 2.25 seconds, with a two-second
I-Am response window. A missing, mismatched or invalid identity stops the action
before the property request. The subsequent property read has a six-second
response deadline, at most 64 KiB of
encoded property evidence and at most 4096 returned entries. A truncated cache
report says so explicitly. The ACK must match the exact router, Device object
and property. Cancelled or timed-out reads retire the specific BACpypes client
transaction and request bookkeeping; they do not leave retries running.

The shared connector lock serializes these operations with other cooperating
services. Application identity, connection configuration and link health are
checked during collection. A change or fault stops the operation. The temporary
observer delegates ordinary packet processing and is removed on completion,
failure and cancellation. It does not change the process-wide route-awareness
setting or choose a different cached router for the outgoing scan. Normal
BACpypes handling can still learn routes from received advertisements.
Audit persistence failure is reported separately from discovery that already
completed. Restart never resumes a scan.

Single-MAC probes have a six-second initial identity deadline, up to three
seconds per optional metadata property and a 20-second overall response budget.
A MAC page has at most 32 addresses, a 0.5–2-second response window per MAC,
at least 0.1 seconds between completed requests and the next transmission, and
a 1–30-second overall budget. A new MAC is not attempted unless enough budget
remains for its whole requested response window. Lock admission adds at most
five seconds. These bounds limit one request; the operator explicitly chooses
whether to request another page.

During either probe, outgoing requests and SegmentACKs for the selected target
are sent through the selected IPv4 adapter/router with Hop Count 255, matching
the native BACpypes allowance. An engine may need more than one logical
forwarding stage even when its IP endpoint is the only selected next hop.
A Hop Count of 1 can expire inside that path. No learned router-cache entry can
silently redirect them or cause a router-search
broadcast. Incoming replies for the selected routed MACs must come through that
exact router IP/UDP port and carry their expected source network/MAC. Temporary
send/receive hooks restore previous handlers on completion, failure and
cancellation, without changing the global BACpypes route-awareness setting.
This source pinning is not cryptographic authentication.

## Johnson Controls routing and native program limits

JCI documents that a network engine normally exposes mapped/proxy objects.
Actual access to its MS/TP devices requires the engine's routing feature.
Routing Mode can be Disabled, Enabled, or Enabled Without Broadcast. A silent
network discovery or broadcast scan therefore does not prove that unicast
controller reads cannot work. This service never changes that setting. See the
manufacturer's [release 11 BACnet routing considerations](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/BACnet-Controller-Integration-Technical-Bulletin/11.0/BACnet-routing-considerations)
and [engine Routing Mode attribute](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/SCT-System-Configuration-Tool-Help/19.0/Insert-Menu/Supervisory-Device/Engine-Device-Object/Engine-attributes?contentId=xFvLgLxVTdCqbqkZEUVY8A).

JCI's [portable-router configuration guide](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Portable-BACnet/IP-to-MS/TP-Router-Installation-Guide/G/Operation/Configuring-the-router)
requires the same BACnet/IP UDP port assignment for devices on the same BACnet
network, normally 47808. When testing an engine path, explicitly bind the client
to the site's configured UDP port if that local port is available. A successful
direct read of the engine on an ephemeral client port does not establish that
its routed traffic will work with that port. This is a configuration check,
not evidence that a particular engine rejects ephemeral ports. The service
never changes an engine's port, routing mode or network numbers.

Discovering an engine's proxy objects, receiving an I-Am, or reading a field
point does not upload a native CAF application. A native program upload still
requires the matching JCI application service/compiler/packages or a verified
independent adapter. Standard BACnet objects and address-cache dumps are not
substitutes for a controller program file. Bluetooth/BTCVT is outside this
service and its tests.

## Local verification and provenance

`tests/test_routed_discovery.py` runs the production connector against an
independently authored raw UDP router. Literal BVLC/NPDU/APDU fixtures verify
the exact unicast router request, one-network broadcast, Hop Count, source
filtering and a subsequent real routed ReadProperty. Tests also cover address
cache alternatives, unknown Device identities, duplicate conflicts, malformed
announcements and ACKs, caps, empty windows, cancellation, failed sockets,
bounded lock admission and interface changes. The actual ASGI endpoints are
also tested through raw UDP, including session/origin guards and an explicit
routed controller read. These local tests do not
establish physical router, trunk or controller acceptance. Site verification
is recorded separately by the operator.

An independent raw peer also sends an actual 161-entry cache across multiple
segmented ComplexACKs and checks each client SegmentACK. This is tested both
without a peer capability-cache entry and through the service's directed
identity preflight. The no-cache test proves that local segmented receive does
not depend on guessing a remote capability. Cancellation during an unfinished
segmented ACK retires the local transaction, and cancelling the preflight
removes its I-Am collector without starting a property read.

Probe tests encode the actual wildcard request and actual-identifier ACK
independently, verify metadata and explicit partial failures, and test source
pinning even with a poisoned route cache. Page tests verify actual UDP timing,
silent addresses, negative responses, duplicate Device identifiers, explicit
deadline/resume and cancellation without later packets. An independent peer
that consumes two forwarding hops tests the selected-network broadcast, single
probe and MAC page. The wildcard procedure
is defined independently of the local Python server by
[ASHRAE 135.1-2019 Addendum s, test 12.1.3.X3](https://bacnet.org/wp-content/uploads/sites/4/2024/05/135_1_2019_s_20230331.pdf),
which requests Device 4194303 and expects the actual Device in the response.
[ASHRAE 135-2016 Addendum br](https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-135-2016br.pdf)
explains why Device wildcard access identifies devices that do not generate
I-Am. The independently installed
[BACnet-stack ReadProperty handler](https://github.com/bacnet-stack/bacnet-stack/blob/e295d20baba977132b47bc09f61f28e12f2dfac3/src/bacnet/basic/service/h_rp.c#L95)
also rewrites the wildcard to the actual Device before encoding its ACK. These
references do not imply that every physical controller supports the procedure.

The implementation uses the pinned BACpypes3 0.0.110 adapter/codec interface.
Primary upstream references are
[`NetworkAdapter` and network messages](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/netservice.py),
[`NPDU` and routed addresses](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/npdu.py),
and [Who-Is/I-Am service encodings](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/apdu.py).
No upstream source was modified or copied into this module.

## Connections identity workspace

The Identify one controller panel uses an already open, exactly matching router
and destination network. Discover controller by address queries one explicit MAC,
then displays its actual Device identifier, object name, vendor, model, firmware,
application software and timestamps. Individual metadata failures remain visible
and are exported with the complete report. Use identified controller transfers
the router, network, MAC/address and Device identifier together into point/file
services. Duplicate Device identifiers on different trunks remain distinct.

The separate address-page action requests only Device identifiers at up to 32
consecutive addresses. Controls allow a 0.5–2-second per-address response
window, a 0.1–1-second request gap and a 1–30-second page deadline, with defaults
of 0.75, 0.1 and 30 seconds respectively. Timing draft changes invalidate old
page reports; the selected values are retained in the returned/exported request
evidence. Every attempted address has an
outcome; silence is displayed as unknown. A returned address has an explicit
metadata-read action. Prepare next MAC page changes drafts only and never
dispatches another page automatically. The complete raw report fields are
retained in JSON exports. Changing the route/interface invalidates pending
results, and operation guards prevent duplicate dispatch and stale selection.

Four browser tests use the independently encoded UDP router to verify complete
and partial identity metadata, exported source/route/timestamp evidence, exact
selection into file services, route-change invalidation, MAC-page bounds,
actual wildcard requests, unknown silent addresses and explicit next-page
behavior. The peer asserts that every emitted request is a directed confirmed
ReadProperty, with no discovery broadcasts or controller writes. These are
local implementation checks, separate from site acceptance.
