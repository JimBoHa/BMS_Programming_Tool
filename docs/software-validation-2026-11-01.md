# Software qualification — 2026-11-01

These are source-specific local software results. They do not certify the whole
universal tool, controller families, electrical wiring, code compliance or
physical/Bluetooth acceptance. Original failed logs, traces, test state and
downloaded evidence remain in the private local reports; site data and vendor
archives are not published here.

## Combined backend run and explicit toolchain follow-up

The combined stack through #151 (`fa7e70d`) ran all 5,799 collected backend cases
with the authorized private CAF corpus. The original result was **5,409 passed,
66 failed and 324 skipped** in 706.07 seconds.

- Sixty-four failures reached the actual Sedona compiler but selected the macOS
  `java` shim. Their errors report that no Java runtime could be found. The SDK
  was present; the isolated worktree had not selected the installed local JDK.
- Of the skips, 323 required the already installed pinned MatIEC compiler, whose
  home was not selected from that isolated worktree. One routed-source-filter
  composition skip is intentional and remains unchanged.
- Two other failures are independent BACnet timeout investigations, described
  below. They were not assigned to the Java or MatIEC problem.

Explicit existing `BMS_JAVA`, `BMS_IEC_HOME` and SDK paths passed runtime and
manifest/checksum preflight. The exact 64 Java-failed and 323 IEC-skipped cases
then ran: **387 passed, zero failed and zero skipped** in 254.28 seconds. The
source, assertions, protocol limits and retry policies were unchanged. The
follow-up includes actual native compiler/runtime comparisons rather than
substituting portable simulation results.

Together, these two runs establish **5,796 distinct passing cases**, with the
two original BACnet failures and one intentional skip still recorded. This is
not a single-run full-suite pass. A later pass must not be described as a repair
for an unexplained original failure.

## Unresolved BACnet observations

1. `test_malformed_stream_ack_is_rejected_without_saving_partial_bytes[no-progress]`
   received the file-read timeout error after zero bytes instead of the expected
   `AtomicReadFile` validation error. The original run does not establish whether
   the deliberately malformed response reached the intended validation path.
2. `test_new_collision_during_apply_cannot_dispatch` timed out during its initial
   authored native capture, before the collision mutation or Apply. Its fixture
   uses a 0.1-second individual response bound. The stack identifies the owned
   response wait; the generic native-operation error does not establish that the
   production overall operation deadline expired.

Their original failures and test state are retained. No Apply/restore was reached
in the second case. Neither a host-load explanation, an SDK/network defect nor
a repaired cause has been established. No timeout was widened, assertion removed,
automatic retry introduced or historical Schedule failure relabelled as fixed.
These remain separate from the earlier Source41 Schedule, String Schedule and
source-filter investigations under QA-01.

## Later integration checks

#152 changes documentation and public scope descriptions only. Its offline API
matches the public register; original broad partial/pending statuses, backlog
gaps and the historical validation body remain preserved.

#153 changes the graph inspector and its App-owned unfinished parameter cache;
the acquisition backend remains identical to #151. Its original #119 tests and
implementation are retained. All **118 Chromium/WebKit checks** pass: 24 draft
ownership, 26 responsive/drawer, 56 controller/workspace and 12 native wire
transfer/recovery cases. Final-source **25 Program-source and six installed-wheel
checks** pass. Its clean wheel matches all 143 Python modules, 85 UI assets and
public metadata. This is a scoped integration result, not a fresh full backend
run at #153.

The original older CAF local-scenario browser suite stopped before simulation at
its removed global navigation button. Its failed trace is retained separately.
The current harness enters through **Open CAF → Simulate** and retains the
original source bytes, saved-revision, quality, startup-copy and late-export
assertions. Its result belongs to that separate harness qualification.

All work used authored local/loopback or kernel-PTY peers and local files. Native
backup-state commands in mutation tests concern those authored peers; they are
not passive reads or new field acceptance. The original older checkout and its
31 changed files remain preserved.

## Schedule browser harness qualification

The older Schedule inventory browser suite also stopped at its removed global
Connect button. That same failure was reproduced on the preceding runtime.
[The updated Schedule workflow](schedule-workflow-validation.md) follows verified
controller selection and keeps original native numeric/seal, routing,
cancellation and delayed-result checks. All 32 desktop/compact Chromium/WebKit
cases pass with retries disabled. Product sources and styles remain unchanged.
Original failed traces and the separately observed Program-navigation datagram
remain retained; this does not explain the two earlier full-run BACnet failures
or establish physical acceptance.

## Reproducing optional compiler coverage

Configure the existing supported environment variables for the actual installed
assets before collecting tests:

- `BMS_JAVA`: executable Java path, not a shell alias or macOS launcher shim.
- `BMS_SEDONA_HOME`: matching Sedona SDK and native host runtime.
- `BMS_IEC_HOME`: pinned MatIEC home with its build manifest and compiler.
- `BMS_TEST_NIAGARA_SDK_DIR`: optional authorized SDK metadata; tests verify pins.
- `BMS_TEST_CAF_DIR`: optional authorized private CAF corpus.

From the selected source checkout, use its virtual environment and explicit
source path:

```sh
PYTHONPATH="$PWD/backend" .venv/bin/python -m pytest -q -ra
```

Missing optional assets can produce skips; a present SDK does not prove its
external executable can start. Keep each source commit, environment preflight,
original failure and subsequent qualified result together. Do not publish
private credentials, site captures or undistributed SDK/CAF files.
