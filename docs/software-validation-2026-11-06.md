# Backend software qualification — November 6, 2026

The installed wheel passed **10,747 backend cases**, with three specified skips,
in 1,487.99 seconds. The tested source was
[`e086f4fa`](https://github.com/JimBoHa/BMS_Programming_Tool/commit/e086f4fa924a0c3435878b90c76b34ee328ecc6e),
whose tree matches merged main `89b52d45`. Original logs, JUnit reports, toolchain
metadata, package proofs and failed-run evidence remain in private local reports.

The run selected the existing pinned IEC, Sedona and Temco host toolchains,
actual Java executable, authorized private CAF compatibility inputs, independent
pybog source and pinned Niagara SDK metadata. Native host execution and static
vendor metadata inspection retain their separate scopes. Tests used isolated
state, authored loopback protocol peers and kernel pseudoterminals. They performed
no building-controller, VM or Bluetooth operations.

## Source run and environment correction

The original full source run collected 10,750 cases: **10,715 passed, 32 setup
errors and three skips**, in 1,491.83 seconds. All 32 errors came from the shared
UI-build fixture: Node.js was installed but absent from the runner's `PATH`.
The retained error was `The UI compiler acceptance tests require Node.js on PATH.`

Selecting the existing pinned Node.js executable passed those exact **32 cases**
in 2.65 seconds. Source, assertions, deadlines and retry policies were unchanged.
The two source runs establish 10,747 distinct passing cases; they are not a
single passing full-source run. The subsequent installed run selected Node.js
before collection and passed all 10,747 applicable cases in one run.

The installed run used an independent pytest configuration without the
repository's source `pythonpath`. Import checks at collection and session finish
verified every loaded `bms_tool` module came from the extracted wheel: 251 modules
at collection and 253 at session finish. The wheel separately matched all 254
tracked Python modules, 59 UI assets, public metadata, reference data and bundled
legal files. A separate TypeScript contract run passed all **1,737 cases** with
retries disabled.

## Skips and preserved investigations

The three skips were the intentional routed-source-filter composition case and
two Windows-only storage cases: native named-pipe handles and NTFS junctions.
This qualification ran on macOS. The desktop installer checks for macOS ARM64,
macOS x64 and Windows x64 are separate distribution acceptance evidence.

Earlier Schedule, String Schedule, source-filter, BACnet File/native-capture,
native-startup and browser-response observations remain recorded with their
original sources and failures. Their later passing counterparts do not explain
their earlier causes. This run changes no production protocol timing, automatic
retry policy or native admission rule, and does not mark those investigations
repaired.

## Reproducible native-application case names

Of the 10,750 collected source/installed identifiers, 10,747 matched literally.
Three included gzip bytes generated during collection; the four timestamp bytes
in their gzip headers differed between runs. Their remaining header and compressed
payload identifiers matched exactly. They belong to the unrecognized/oversized
native-file and misleading `.moz` extension rejection cases.

`QA-NATIVE-FIXTURE-IDENTITY-001` fixes those fixture timestamps at zero and gives
the six related parameter cases explicit descriptive names. This keeps reports
stable without embedding large binary strings in identifiers. Input payloads,
apart from the declared gzip timestamp, and all test bodies/assertions remain
unchanged. Production readers and compression remain unchanged. Fixed fixture
timestamps do not promise identical gzip output across every compressor version.

## Application acceptance scope

The subsequent offline pulse workflow in #294 separately passed 87 source and
87 installed backend checks and 192 Chromium/WebKit executions across both
installation modes. That feature preserves the backend runtime and adds no
controller writes. Its desktop and compact checks include actual original
multipart uploads, raw draft ownership, local/native separation and accessible
arithmetic tables.

The roadmap still tracks broader native authoring, package/resource validation,
runtime semantics, cross-brand conversion and physical acceptance. Local software
qualification does not establish manufacturer acceptance, Title 24 compliance,
physical I/O behavior or BTCVT compatibility. Original private CAFs and the older
local checkout remain preserved.
