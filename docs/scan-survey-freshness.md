# Scan freshness and explicit interface resume

Closing and reopening an engineering interface could automatically restart
metadata reads for pending devices in retained scan results. The scan workspace
now keeps those observations paused after a local bind address or interface
identity/epoch change. An operator must choose **Resume shown-page details**,
**Read shown-page details again**, or perform a new explicit scan.

The interface owner retires pending discovery and metadata results before a late
response can paint in another interface context. Completed observations retain
their original source, timestamps and metadata evidence; they are not relabelled
as a fresh read. A status message identifies the retained observations and the
available actions. Search, sort and page changes on the same authorized interface
keep the existing bounded shown-page naming behavior. Explicit Stop still lets
only its current bounded RPC finish, as before.

The separate **Hardware survey** remains a captured snapshot. Updating an input
on a controller does not alter a previously displayed survey. A second explicit
survey reads its new value and replaces that snapshot with newly acquired
evidence. The selected controller and exact endpoint remain in the workspace;
the hardware tool does not reintroduce editable target fields.

## Actual protocol qualification

`web/tests/scan-survey-freshness.spec.ts` uses the current controller workspace
and production HTTP services without API interception. Its loopback-only peer
reuses the existing controller-workspace fixture and assigns a random Device
instance, name, model and two exactly representable input values for each run.
The browser scans a nondefault UDP port, opens the discovered controller, checks
the authoritative target, and reads two hardware surveys around a test-owned
input change. The old snapshot stays visible until the second explicit survey.
Request counts grow and the peer records every incoming service before dispatch;
only discovery and property reads are allowed.

A second workflow holds an actual Device name response, closes the interface,
releases that response and reopens the same bind configuration. No name is
adopted or reread automatically. Explicit resume reads the name through the
current interface without sending another Who-Is. Both workflows join their
owned peer process and retain request evidence; assertion and cleanup failures
are reported together. The peer's JSON pipe controls only authored fixture data,
never application responses or controller configuration.

The initial tests exposed the automatic-resume behavior; the interface-owner
guard fixes it. Other initial failures identified outdated toolbar/target-field
selectors, which were adapted to the existing design contract. This qualification
does not encode scan observations in the application, fabricate controller
inventories, establish physical device/adapter acceptance, or perform site or
Bluetooth configuration tests. Broader QA-02 work remains separately tracked.

Final local qualification passed all four new browser cases and 38 existing
scan/workspace cases across Chromium and WebKit, including both CAF entry paths,
real routed discovery, paging, late-result retirement and instance-review
regressions. Seven existing backend fixture cases, six package checks, the UI
build, format checks and public metadata/API/CSV consistency also pass. Legacy
scan tests now follow the current guided entry and explicit Open controller
semantics, retain route provenance checks and use the current controller-name
lookup status rather than a removed link. Original failed evidence is retained.
