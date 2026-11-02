# BACnet/IP route-change qualification

The real BACnet/IP connection status contains its bind, Device instance and
router/network settings. It omits a `transport` selector. Serial MS/TP status
uses `transport: "mstp"` through its separate connection path.

Three authored browser fixtures now mirror that IP shape. A prior navigation
fixture inserted `transport: "ip"`, then reused that fictional status during a
route change. The strict IP endpoint rejected its extra field before opening an
interface. The preserved trace identified a test setup mismatch; it did not
establish a product connection defect. The backend admission schema and production
connection code remain unchanged.

The added end-to-end browser check uses an actual loopback BACnet/IP interface
and two independently running authored IP-to-MS/TP routers/controllers. Through
the GUI it opens each routed controller with the same Device instance, confirms
the selected router/network and retains the original local bind across route
changes. Its BACnet responses are not mocked. Peer observations show read traffic
without Write/Reinitialize requests. An explicit invalid IP `transport` field is
also rejected while the existing interface configuration stays intact.

Separate fixture regressions cover the current-controller point-tools link,
identity target changes away and back, and the full 32-context retention boundary.
Those UI-only cases continue to identify their authored HTTP contexts and keep
their actual backend interface closed.

This qualifies the existing IP route-selection workflow in local simulation.
Physical site networks, Bluetooth, serial adapters, controller program compilation
and application transfer retain their separate acceptance requirements.
