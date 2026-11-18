# SA-bus address diagnostics

Open a verified controller → **Points & I/O → SA-bus diagnostics**. Choose an
inclusive MAC range, select **Review SA-bus probe**, check the responding
controller and range, confirm the temporary diagnostic action, then **Run SA-bus
probe**. The default 199–206 page covers the NS8000 address switches. Other SA
devices can use different addresses. A page admits 1–16 addresses within 1–254;
the operator explicitly selects each additional page. There is no repeat scan.

This uses BMS Studio's own BACnet connection. It requires no vendor executable,
VM, JCT/SCT session, CAF download or change to a configured network-sensor MAC.
It addresses the selected **parent controller**, including its exact IPv4 next
hop, DNET, station and Device identity. It never sends an outer-router scan to
the controller's internal SA network as though that network were site-unique.

## Diagnostic protocol and limits

`jci-sa-port-communication-probe/1` qualifies the native JCI MSTP Manager SA port
at `307,2`: vendor 5, network 65000, local MAC zero, enabled, in service and port
status Active. Each review retains the actual controller name, Device ID, model,
firmware, database revision, interface and typed property evidence. A missing,
unreadable, differently encoded, inactive or different port is unsupported. A
model name alone never grants this capability.

The native diagnostic is **not a read-only BACnet transaction**. For each selected
SA MAC it sends exactly one unprioritized WriteProperty to **Comtest Dest,
property 1036**, encoded as Unsigned. That property is a transient writable
diagnostic selector, not an archived/configurable application setting. It then
reads the selector and **Test Status, property 30033**, a uint16 result:

| Native status              | Display and meaning                                            |
| -------------------------- | -------------------------------------------------------------- |
| 65535                      | Test pending; continue bounded polling                         |
| 0                          | Controller reports diagnostic success                          |
| Other                      | Controller reports diagnostic error; preserve the numeric code |
| Property/transport failure | Stop the page, retain uncertainty and untested addresses       |

The adapter waits at least two seconds before accepting a completed result and
polls at half-second spacing. A test pending after its seven-second window stops
the page; it does not advance to another address. Request/response time is part of
the bounded operation, not an asserted sensor latency. The whole job is limited
to three minutes plus bounded selector restoration.

Success is a **parent-controller diagnostic result**. It does not identify a
sensor, read its temperature, prove correct wiring or guarantee that a configured
integration is healthy. The evidence separately records whether a pending state
was observed. An immediate completion can occur without observing that state.
Unknown native error codes retain their numbers; the app does not invent error
labels or equate an error/timeout with physical absence. This is not an exhaustive
SA inventory, a general nested BACnet router or an arbitrary private-command API.

Application archives, operating points, outputs, configured SA integrations,
statistics latches, firmware and backup/restore state are not written. Native
application/identity changes in this app are blocked while diagnostics or their
unresolved recovery intent remain active.

## Ownership, cancellation and recovery

Review makes only attributable reads. Run requires the local session token, an
explicit diagnostic confirmation and the exact two-minute, one-use review digest.
It rechecks the interface, controller identity/revision and complete reviewed SA
port state before dispatch. A nonzero diagnostic destination or pending test
refuses a new review. Close other engineering tools using that controller's SA
diagnostics; the selector is shared and has no atomic compare-and-set operation.

The worker owns the existing connection lock and exact route throughout the job.
Before every next address it rechecks the controller identity and the last owned
selector. Before any diagnostic dispatch, a durable local intent records the
original zero destination and attempted address. Lost acknowledgements are not
retried. Remaining addresses stay **Not tested** after interruption or failure.

Cancel waits for the current address test and restores the original zero
destination; cancelling before the first dispatch needs no restoration. Leaving
the task sends a best-effort cancellation request and retires late UI responses.
The server owns the operation independently of its progress display. If the
browser loses contact, reopen the retained report instead of starting another
probe. Shutdown requests cancellation before closing BACnet.

Restoration checks the original identity/revision and current selector, writes
zero only if the selector still matches the owned diagnostic, then reads zero
back. If another tool changed it, or a response/interface/identity cannot be
verified, the app retains **restoration required** and blocks new probes.
It never overwrites a different diagnostic owner's selector. A fresh process
retains the intent; it does not resume a scan or repeat a diagnostic request.

Open the saved report on its original selected controller/interface and choose
**Restore original diagnostic destination** for explicit guarded recovery. If
another tool owns it, let that tool relinquish it first. Recovery verifies or
restores only the original selector, without replaying the address page.

Reports, routes, original identities, timestamps, raw transport evidence, result
codes and recovery records stay in the private runtime SQLite store. **Download
probe evidence** exports the selected report locally; its field data must not be
committed or attached to a public PR. The latest 100 report summaries are listed;
unresolved intents remain blocking even outside that display page.

## Verification and references

`tests/test_sa_bus_probe.py` supplies an independent literal UDP peer that admits
only parent-addressed reads and the one diagnostic property. It tests actual
wire framing, sequential addresses, pending/success/error outcomes, durable
pre-dispatch intent, stale identity/interface/reviews, rejection, lost ACKs without
retries, cancellation, external ownership, explicit recovery after restart,
wrong-next-hop rejection, bounds, local API authentication and offline refusal.
`web/tests/sa-bus-probe.spec.ts` runs the real API and peer through the selected
controller workflow, including review invalidation, cancellation, JSON export,
late-response retirement, reopening a lost start response without another
diagnostic dispatch, keyboard confirmation and responsive screenshots.
These authored-peer cases qualify software behavior, not physical sensor
operation. Site-specific field evidence remains outside the repository.

The protocol adapter is independently implemented against the native MSTP
Manager communication-test contract. No vendor assembly or decompiled source is
included or needed at runtime. JCI's public documentation describes the broader
SA status workflow and the address-switch range; neither page documents the
private diagnostic wire contract:

- [SA Bus Status Screen, Controller Provisioning with Tools 10.1](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Provisioning-with-Tools/10.1/Using-the-Advanced-Transfer-Option-in-CCT/SA-Bus-Firmware/SA-Bus-Status-Screen)
- [NS8000 network sensor addressing](https://docs.johnsoncontrols.com/bas/r/Johnson-Controls/en-US/NS8000-Series-Network-Sensors-Installation-Guide/J/Network-sensor-addressing)
