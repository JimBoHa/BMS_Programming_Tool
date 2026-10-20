# Read-only BACnet field validation

This checklist distinguishes a working IP path, a router response, an actual downstream controller response and a native application service. It uses explicit targets and bounded requests. It is a validation plan; it does not state that site equipment passed these checks.

Completed local and authorized site results are recorded separately in the
[validation record](VALIDATION.md#site-compliance-and-vm-status).

## Interface and UDP path

1. Record the intended local bind address/UDP port, client instance, explicit router IPv4 endpoint and any configured BBMD registration. Preserve the connection status before and after each test. A reachable web server or VPN peer does not establish BACnet UDP reachability.
2. Read the selected router's own standard device identity. Record object identifier, object name, vendor identifier, model, firmware, protocol revision, maximum APDU and segmentation support. Retain errors for unsupported optional properties. Do not replace missing metadata with assumptions about the brand.
3. Check source/destination UDP endpoints from an observed exchange when the path uses VPN routing or NAT. A changing source port, a nonforwarded return route, or an advertised private BACnet/IP address can explain discovery/read differences. A BBMD must explicitly accept foreign registration when that service is used; registration status and lease renewal are separate evidence.
4. After a timed-out or cancelled operation, confirm its exact BACnet request and native client transaction are retired. Closing an interface must not leave timers sending onto its closed UDP socket. Reconnection is an explicit action; failed trend/history jobs must not reconnect themselves.

## Router and downstream identity

1. Send Who-Is-Router-To-Network to the selected router only. Retain the finite response window, received network numbers, warnings and truncation. An empty response does not establish that the router has no downstream network.
2. Optionally read the known router device's standard device-address-binding property. Mark every returned address as cached with unverified liveness. BACnet's unknown instance sentinel 4194303 is not a real device instance. A six-octet BACnet/IP MAC is not an MS/TP one-octet MAC.
3. Select one explicit DNET and a narrow device-instance range. Send routed Who-Is for that network only. Preserve each responder's routed address, device identifier, vendor, maximum APDU and the selected router. A completed response window is a response set, not a complete inventory.
4. For a received or otherwise explicitly known DNET/MAC, perform addressed identity reads and compare the actual controller's device identifier/model with the intended target. NAE proxy I/O objects alone do not prove direct controller access or application-transfer support.
5. Confirm router forwarding configuration when a router responds locally but downstream requests do not. Retain a timeout or rejection as the result; do not silently fall back to a different router, broad broadcast, or another MAC.

## Objects and property values

1. Read object-list index zero, then a bounded page of individual indices. Retain requested index range, device-reported total, returned objects, source target, timestamps, errors, truncation and an explicit continuation cursor. A later failed index must not erase received objects or become a complete inventory.
2. On selected objects, read object identifier/name/type, description, units, present value, reliability, status flags and out-of-service when supported. Optional-property rejection is distinct from connection failure.
3. Exercise actual Boolean, numeric, enumeration, array and structured values. Confirm JSON preserves their actual data. Nonfinite values, opaque tags, unknown proprietary types and oversized responses must produce typed evidence or explicit errors rather than fabricated null/zero values or object-memory strings.
4. Check maximum APDU and segmentation limitations using bounded reads. Indexed object-list reads and small history pages avoid requiring an unsupported large response. An abort, reject or insufficient APDU is not proof of an empty property.
5. Download an object/discovery report and compare its exact request, target identities, response timestamps, completeness flags and source hash with the displayed result. Keep private addresses, names and captures outside source control.

## Field trends and stored history

1. Start one explicit read-only field-trend job on known points. Check numeric/Boolean typing, declared engineering unit, acquisition UTC time and receipt time. Quality becomes good only when the configured reliability/status/out-of-service reads support that conclusion; missing quality remains unknown.
2. Compare live values with separate addressed reads. Cause a local test timeout or use a known unavailable test point to verify an error event without a manufactured sample. Preserve successful readings from other points. Stop the job explicitly and verify that requests stop.
3. Verify a job stops when its exact connector application/configuration changes or fails. Process restart must retain stored evidence without resuming field traffic.
4. When the device exposes standard Trend Log objects, request a small page with an operator-supplied IANA timezone. Verify sequence anchors, date/time fields, datum type, status flags, read/receipt times and any DST ambiguity. Generic device-clock reads do not establish a timezone.
5. Test empty, bounded/truncated and partial-failure reports using local peers; on field equipment, preserve whichever outcome actually occurs. Do not fabricate log data when history is unsupported. Save/reopen a capture and verify report hash, provenance columns, errors/warnings and continuation cursor in JSON/CSV.

## Native controller applications

Standard BACnet discovery, ReadProperty, ReadRange and priority commands do not upload, decompile, compile or replace a JCI CAF application. Establishing those point services does not satisfy native programming support. JCI FX/VMA application transfer still requires a verified manufacturer format/compiler/controller package and native service implementation. Unknown private-transfer commands are not a read-only inventory technique.

The separate Temco application-transfer adapter is manufacturer/model/firmware/slot specific. Its native protocol, backup, bytecode and recovery tests do not establish JCI compatibility. Physical MS/TP timing and hardware remain separate from routed UDP or pseudoterminal tests. Bluetooth/BTCVT is outside this checklist.
