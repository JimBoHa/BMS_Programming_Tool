# Controller workspace draft continuity

State mapping and the standard BACnet instance editor retain unexported text while
the operator changes controller tasks. This extends the existing controller
workspace; it adds no global destination or controller writes during navigation.

## Retained work

- **Points & I/O → State mapping** retains the operator declaration and imported
  plan provenance in the containing workspace. An imported plan still requires a
  new review. Editing its declaration removes the imported provenance. These are
  operator declarations, not acquired controller data or native program bindings.
- **Overview → Identity settings** retains proposed standard instance text by
  the exact interface identity, controller address, Device object, router endpoint
  and network. Duplicate Device IDs at different stations keep separate drafts.
  A draft does not migrate to another interface or station.

The retention is in memory for the workspace lifetime, not durable storage across
browser reloads. Export operator mapping plans when a persistent copy is needed.
Durable instance receipts remain the recovery source for uncertain operations.

## Review and completion

Reviews, allocation confirmations and pending operations remain panel-owned.
Leaving the task retires them. Restoring text never restores Apply authority or
silently opens a connection.

A verified instance Apply clears its completed proposal. A later explicit
readback that verifies an uncertain change also clears the matching original
proposal. Readback does not remove a different, newer proposal or another
controller's text. Reconciling a retained receipt while viewing another controller
updates that receipt without changing the selected controller's identity.

## Software qualification

Browser tests use authored loopback BACnet peers, including a held real
WriteProperty request followed by uncertain cancellation and explicit readback.
They cover separate routed stations with duplicate Device IDs, newer unapplied
text, receipt reconciliation while another controller is selected, imported plan
provenance, retired reviews, CAF and Connect entry paths, and compact navigation.
These checks do not establish physical controller acceptance or Bluetooth support.
