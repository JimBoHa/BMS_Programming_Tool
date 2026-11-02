# Schedule selection qualification

The selection integration begins at `94921842`. All existing backend files,
506 prior test/support files, 40 styles and three public metadata documents remain
byte-identical. The original checkout's 31 dirty files, status and diff retain
their saved hashes. No site or Bluetooth operation is part of this review.

Source qualification includes 336 existing native schedule/library/String/
Calendar-draft backend tests and 18 new Chromium/WebKit checks without retries.
The browser checks use authored UDP identity, Schedule acquisition, native
weekly-day writes and explicit readback. They cover different station addresses,
different routers for the same routed station, different Device identifiers,
matching direct/routed selections, exact original receipt export, readback only
under the original selection, delayed preview after A → B → A, the separately
qualified String domain, and offline application/CAF entry paths. Matching cases
make one write; readback adds no write. Desktop/compact screenshots and overflow
checks retain the existing layout.

The original implementation reproducibly left Preview enabled after its profile
finished loading while a foreign capture was open under another verified
controller. The negative trace is retained privately. Initial fixture checks
were corrected to supply the required acquisition operation ID and await profile
readiness before judging the button; those earlier results are retained and are
not evidence of a product fix.

One first positive browser check observed an empty body through the test driver's
Apply-response accessor while the application displayed the completed receipt
and the journal retained a sealed result. Its trace and state remain retained;
the observation's cause is not established. Export qualification now compares
against the original immutable journal response, the artifact the operator saves.
The product/request policy was not changed to address that observation, and a
later pass does not explain it.

TypeScript/Vite build and diff checks pass. These focused results preserve the
existing source/target, lease, dispatch and uncertainty contracts. They do not
resolve earlier separately recorded BACnet timeouts, establish physical control
performance, or complete Calendar/exception authoring and weekly draft continuity.
See [the feature scope](native-schedule-controller-selection.md).
