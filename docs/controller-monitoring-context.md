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

The pair is supported for direct and explicitly routed BACnet/IPv4 acquisition.
Selected-controller direct MS/TP and other unsupported profiles are refused
explicitly; this does not remove legacy standalone serial acquisition. Clients
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

## Integration with native engineering

The selected-controller monitoring profile is integrated with the current native
archive/effective editors, Real/Boolean/default/wire transfers, focused Schedule
diagnostics and retained-scan interface ownership. Those workflows retain their
own source, draft and recovery boundaries. Selecting a saved monitoring job or
capture does not change the selected engineering controller or authorize a
program transfer. The controller-centered navigation and existing visual style
remain the common entry point; standalone API callers keep their legacy shapes.
