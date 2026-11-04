# Combined software regression and capability-version qualification

The frozen source
[`51bae77e`](https://github.com/JimBoHa/BMS_Programming_Tool/commit/51bae77e3a227769037b4d30fcf18b1d47c01028)
has the same tree as merged main `316007ef`. Its full backend run collected
8,761 cases: **8,747 passed, 11 failed and three skipped** in 1,267.08 seconds.
The original log, JUnit, source/toolchain metadata and available failed-test state
remain in private local reports. No automatic retries or timeout changes were
used. The installed Java, Sedona, MatIEC and Temco assets were selected explicitly.

One skip is the intentional routed-source composition case. Two require actual
Windows named-pipe or NTFS-junction support. Their platform exclusions remain;
this run was on macOS. Authored local protocol peers, kernel pseudoterminals,
private read-only CAF compatibility inputs and native host runtimes were used.
No building controller, VM or Bluetooth operation was performed.

## Nine deterministic capability-test failures

Two older test functions, covering one Boolean case and eight Enum source/
identity/transport cases, still called the default capability API while expecting
version 11 and 22 operations. The earlier
[`78442e2`](https://github.com/JimBoHa/BMS_Programming_Tool/commit/78442e23cf4f1b083f1117daba97242be431498e)
delivery intentionally changed that default to version 12 with 24 operations and
retained explicit version 11. The request model and existing capability tests
already document that versioned contract. All nine failures reproduce on the
unchanged merged baseline.

The repaired tests keep their original identities and exercise three calls each:
the current default, explicit version 12 and explicit version 11. They require
exact 24/22-operation counts and unique IDs, equality of default and explicit
current responses, and the complete exact legacy projection. Both versions must
retain the original Boolean/Enum, fixed-storage, unknown-storage, identity,
transport, immutability and no-field-authority assertions. Sources without a
matching graph must refuse the two newer connection capabilities. No production
code, package asset, API profile, assertion threshold, deadline or retry changes.

## Two separate timeout observations remain unresolved

- `test_native_nested_boolean_calendar_uses_expanded_host_binding` failed during
  native simulator startup with DASP `No response from hello`. The retained VM
  log reports a started Sox service, an application running and opened sessions
  with duplicate-ID closures. Those facts do not establish why the client lacked
  its expected response or prove a compiler, macro, SDK or host-load cause.
- `test_allocate_mode_round_trip_and_remove_with_durable_origin[True]` failed at
  the mode-change Apply assertion after the earlier allocation had verified.
  That failed attempt returned `not_sent` with no new intent and a native
  operation timeout. This is not a claim that the entire test sent no restore:
  the earlier allocation succeeded against the authored peer. Available capture,
  journal and application state from both parameter cases are retained.

Neither timeout is marked repaired by the capability-test correction or a later
pass. They remain separate observations alongside historical Schedule, String
Schedule, source-filter, File/native-capture, commit-ACK and browser-accessor
investigations. No unavailable original trace is reconstructed as observed fact.

The separately completed CAF qualification at this same source passed 1,332
backend cases and 1,394 Chromium/WebKit executions in each source/installed
environment, plus six distribution checks. All 754 prior CAF artifacts remain
exact within 776 supported structural copies. Those scoped successes do not
turn the full backend result into a passing run or complete general native
compilation, resources/packages, CCT/PCT, physical or Bluetooth acceptance.
