# Selected-controller trends and single-log history

From an open controller, choose **Trends & Alarms → Field recording** or
**Controller history**. These views reuse the selected address, Device identity,
router and network. The interface remains the one verified for that controller;
opening a monitoring view never connects or starts sampling automatically.

## Choose actual objects

The shared object chooser reads a bounded page of up to 16 objects from the
controller's real object list. Field recording offers exposed value objects;
single-log history offers standard Trend Log objects. Names are read separately
from the selected controller. Search covers the shown inventory page; continue
to another page when necessary. An empty page does not prove the controller has
no other eligible objects. Failed names retain the verified object identifiers.
No point list is selected by controller model, and no object is auto-selected.

The source checks include the exact controller route and Device identifier.
Unverified or wrong-target inventories cannot supply choices. Changing target,
interface readiness or task retires pending replies; another station's late
reply must not populate the new view. Local field-recording drafts are retained
only under their own controller/interface context in this browser document.

## Start acquisition explicitly

**Start field sampling** creates a job pinned to its original controller and
connector. Selecting another controller or leaving the view does not transfer
or automatically stop an admitted background job. Its original source remains
labelled in the jobs and saved-data views, with an explicit **Stop sampling**
action. An interface replacement or change faults the job instead of reconnecting.

**Read device history** acquires the selected Trend Log using the requested
range and timezone. Bound replies are checked against the requested controller,
log object and captured connector context. Partial or failed identity evidence
is not presented as verified selected-controller records. Saved captures retain
their sealed report and original source. JSON downloads retain the exact bytes
of their current read or load HTTP response; reloading need not reproduce the
initial response bytes. A capture is never relabelled as belonging to the
currently selected controller. Saved
captures and field samples remain available with the interface closed.

## Additive API contract

The existing polling and single-log history endpoints accept an optional pair:

```json
{
  "controller_target": {
    "address": "3001:7",
    "device": "device,42",
    "router": "127.0.0.1:47809",
    "dnet": 3001
  },
  "expected_connector_config": {
    "local_address": "127.0.0.1:47810",
    "instance": 4190001,
    "router": "127.0.0.1:47809",
    "dnet": 3001
  }
}
```

Addresses above describe authored loopback examples. Send the actual complete
connector configuration captured for the selected controller, including any
additional keys returned by the connection service. A target/config mismatch
fails before acquisition. Every requested point address must agree with that
controller. Bound polling stages successful observations until its final Device
and object identity checks; route, identity or interface changes discard that
cycle's pending samples. Durable samples retain their original source context.

The pair is supported for direct and explicitly routed BACnet/IPv4 acquisition,
and for the explicit direct-MS/TP profile described below. Other unsupported
profiles are refused explicitly. Clients
omitting the pair retain the original standalone API and report shapes. The
pair must not be supplied to the separate multiple-channel/event-log profiles;
those retain their existing target contract.

A configuration comparison cannot prove that an identical configuration now
reaches the same physical network. The server pins the application object after
admission, verifies actual responding identities and retires transactions when
that interface changes. No global uniqueness or electrical identity is inferred
from an IP address, Device number or configuration alone.

This feature performs read-only acquisition. It does not write points, allocate
physical I/O, change native applications or establish physical sensor health.

## Selected-controller direct MS/TP

`UI-MONITOR-SERIAL-001` extends the same selected-controller flow to the already
open legacy serial master. Open a known remote decimal MAC and Device, then use
Trends & Alarms → Field recording or Controller history. Addresses remain read
only. The original port, baud rate and local MAC remain visible with the target;
existing jobs continue to name their original interface after navigation.

For these two acquisition profiles only, the nested `controller_target` accepts
`transport: "direct-mstp"`, a canonical remote decimal MAC 0..254, an actual
Device and null router/DNET. The paired `expected_connector_config` must match
the complete current serial configuration, including port, local MAC, client
Device instance, baud rate, maximum master and frames per token. Both the
original and actual serial identities are strictly validated: `false` cannot
stand for MAC 0, or a floating value for an integer baud rate. The local station,
broadcast, inherited IP route, stale port and omitted marker are refused.

The new token-protected
`POST /api/bacnet/controller/monitoring/choices` endpoint reads at most 16 actual
indexed object-list entries per explicit page. It checks the selected Device,
each eligible object's identity before and after its name, object-list count
and the final Device/interface identity. Names that cannot be decoded remain
unavailable. Rows are published only after the final source checks. The 15-second
operation, 1.5-second individual request and existing source/transaction guards
remain bounded. A partial page requires explicit continuation; no discovery or
background collector is started by this endpoint. Standard schemas filter
present-value or Trend Log choices; model names do not supply inventory.

Selected serial polling uses the existing staged cycle and before/after Device
and object identity checks. History uses the existing single Trend Log
position/sequence/time ReadRange and exact response/capture/JSON export path.
The application object is pinned, so reopening identical serial settings cannot
resume an old polling job. Failed final identity checks discard pending samples.
Changing source or page cursor hides previously displayed sample/event pages
before their replacements arrive; an admitted source remains selectable while
its first saved-sample catalog entry is pending.

This explicit opt-in does not widen Device details, generic controller
inventory/properties, COV, multiple/event logs, native application transfer or
controller mutation APIs to serial targets. Legacy standalone API shapes and
IPv4 target serialization remain unchanged. Serial selection also clears
irrelevant IP routing context; its known-address form hides router/DNET inputs.

Qualification uses production HTTP and BACnet services through actual POSIX
kernel TTYs, with only port enumeration replaced. Independently built MS/TP
frames/CRCs and authored peers admit only ReadProperty and ReadRange services.
Two different TTY buses with the same MAC and Device prove interface ownership.
These are software tests: RS-485 direction, adapter timing, physical bus/device
acceptance and BTCVT Bluetooth remain unverified. Large replies still require
the controller's supported unsegmented APDU/page size; this adds no retry,
segmentation or timing-budget expansion.

The final local qualification passed 245 backend cases (27 new serial cases,
26 existing selected-context cases and 192 related acquisition/serial
regressions), six real serial browser cases and 26 context/picker cases across
Chromium and WebKit, four CAF entry/save regressions and six package checks.
The deterministic held-page case checks that previously displayed samples and
CSV export disappear immediately after selecting a different source. The final
serial fixture audit contains only service 12 (ReadProperty) and 26 (ReadRange).
One picker regression initially overlapped a UI build and loaded removed asset
names; the isolated recheck passed after the completed build. No site or
Bluetooth configuration test was performed.

## Integration with native engineering

The selected-controller monitoring profile is integrated with the current native
archive/effective editors, Real/Boolean/default/wire transfers, focused Schedule
diagnostics and retained-scan interface ownership. Those workflows retain their
own source, draft and recovery boundaries. Selecting a saved monitoring job or
capture does not change the selected engineering controller or authorize a
program transfer. The controller-centered navigation and existing visual style
remain the common entry point; standalone API callers keep their legacy shapes.

At a selected serial controller, Program marks the shared native default/wire
backup, transfer and readback controls unavailable under their IPv4-only field
profile. Local native compilation, retained backups/receipts and local credential
settings remain available. The API independently refuses serial native capture
before bus traffic; serial monitoring does not add native application transfer.
