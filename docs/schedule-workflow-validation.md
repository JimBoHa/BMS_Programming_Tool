# Schedule browser workflow qualification

The older Schedule inventory browser suite expected a global Connect button and
editable per-tool addresses. Its original failure was reproduced on the runtime
before schedule continuation was added. The suite now follows **Connect to a
controller → known address → verified controller → Schedules**. No application
interface, compiler, protocol, transaction limit or source guard changes.

The authored UDP peer supplies the identity fields required to open a controller.
Tests assert the visible selected source and actual Schedule request target,
including router and DNET. An ordered acknowledgement separates these initial
identity reads from subsequent Schedule request counts. A held Schedule peer is
armed only after controller verification. Selecting a controller performs no
implicit Schedule read.

The original eight scenarios retain:

- Exact downloaded evidence, SHA-256 seal, native negative zero/numeric bytes,
  Calendar wildcards, nested choices and opaque values.
- Routed endpoint, DNET and NPDU source evidence.
- No late export after a changed draft, another verified controller, another
  retained report or navigation.
- Cancelled status, retired active operation, exactly one request per attempted
  held read and no retry after leaving the task.
- No old response attached to a newly selected controller, even with the same
  Device instance at another UDP endpoint.

The cancellation/navigation case leaves for **Library**, an offline destination.
Program now displays actual controller data and can start its own inspection.
The original failed navigation trace retains its observed third datagram and
Program API requests; no exact wire-to-API attribution or repaired retry defect
is inferred from a subsequent pass. The test keeps its exact two-request check.

All **32 checks pass**: eight scenarios in Chromium and WebKit at both 1440 px
and 600 px widths, with retries disabled. Owned peers exit before cleanup ends.
The original failed runs, request records, state and traces remain retained
separately. The original 350/150/100 ms checks and native evidence assertions are
unchanged; there is no longer timeout, ignored assertion or automated replay.

This qualifies the browser harness against the controller workspace. Product
sources, styles, dependencies and public capability data are unchanged. It is not
a new physical controller, Bluetooth or full-suite acceptance result. The earlier
two unexplained BACnet failures and other acquisition investigations retain their
original status in [software validation](software-validation-2026-11-01.md).
