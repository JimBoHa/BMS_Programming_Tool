# Independent IEC Structured Text execution

The IEC native verifier sends Studio's generated Structured Text through the
real [MatIEC compiler](https://github.com/beremiz/matiec), compiles its generated
C with the host's Clang, and runs the resulting native executable. Each scan is
compared with a separate instance of Studio's Python graph engine. It does not
use the Python result as the native result and does not claim controller
compatibility from a successful host test.

The implemented path is:

```
Studio graph → unchanged exported ST → MatIEC iec2c → generated C
                                                     ↓
Studio graph → Python reference ← compare ← native Clang executable
```

MatIEC receives the same ST downloaded by the portable exporter, with one small
configuration/resource/task declaration appended to instantiate `PROGRAM MAIN`.
The host driver calls MatIEC's generated `MAIN_init__` and `MAIN_body__`
functions. Host bindings provide elapsed scan seconds, day/minute and inputs;
the compiled program produces its own outputs, retained state and fault flag.

## Install the optional compiler

On macOS with Apple Command Line Tools, run from the repository root:

```sh
.venv/bin/python scripts/setup_iec.py
.venv/bin/pytest -q tests/test_iec.py tests/test_iec_api.py
```

The script requires Git, Clang/Clang++, Flex, Make and `/usr/bin/m4`. It downloads
public source when absent and builds outside this repository:

- Primary source: `../Reference_Sources/matiec`, pinned commit
  `3a41303bcb4e50403417bc39c63f88981d7d961e` from
  [beremiz/matiec](https://github.com/beremiz/matiec/tree/3a41303bcb4e50403417bc39c63f88981d7d961e).
- Private build: `../.toolchain/matiec-3a41303bcb4e`, containing a private source
  copy, generated parser, objects, compiler and manifest. The pinned checkout
  remains clean, with no source or runtime patches.
- Private parser generator: GNU Bison 3.8.2 from the
  [GNU source archive](https://ftp.gnu.org/gnu/bison/bison-3.8.2.tar.xz), SHA-256
  `9bba0214ccf7f1079c5d59210045227bcf619519840ebfa80cd3849cff5a5bf2`.
  macOS's system Bison 2.3 is too old. This private build changes no system tools
  or shell settings.

`--source` and `--destination` customize the build paths. At runtime,
`BMS_IEC_HOME` can select an installed build. Rebuild on the destination host
after moving to another architecture or changing compilers; do not assume an
Apple silicon executable runs on a different platform. The setup script
records compiler revision, host compiler, platform and SHA-256 values. Runtime
checks both the compiler executable and the entire IEC runtime library tree
against that manifest before use. These checks detect accidental changes to
the local installation; they are not a signature from an independent party.

## APIs and evidence

Python callers use `bms_tool.iec.profile`, `compile_program`, `verify_program`,
`verify_scenario`, or the persistent `NativeIEC` context manager. Compilation
returns the actual ST and generated C, project digest, provenance and compiler
diagnostics. It marks `native_runtime_verified` false. Verification executes
scans and returns individual rows with native outputs/state, native fault,
successful scan count, independent reference values/fault and
`matches_reference`. A run can complete while containing mismatches; inspect
both fields.

The local API exposes:

| Endpoint | Request / purpose |
| --- | --- |
| `GET /api/iec/status` | Availability, provenance, types and bounds |
| `POST /api/iec/compile` | `{program}`; compile Studio-generated ST to C and a local executable |
| `POST /api/iec/verify` | `{program, inputs?, scans?, dt?, clock?}`; repeated native scans |
| `POST /api/iec/scenario` | `{program, events, duration, dt?, clock?}`; timed input changes |

An event has exactly `{time, inputs}`. Events apply at the first scan boundary
at or after their time. Arbitrary ST/C uploads, output forces and native
extensions are not accepted by these endpoints. Mutating requests require the
local session token and pass the application's loopback host/origin checks.

The independent execution tests compile and run all **27 graph block kinds**,
all **nine VAV example graphs**, feedback, independent nested macro instances,
Boolean memory, PI anti-windup, timer/alarm resets, sensor quality faults,
late-scan divide faults, float overflow, hosted calendars and timed scenarios.
HTTP tests run the real compiler/executable and verify validation/security;
field connector methods are patched to fail if accidentally invoked.
Optional compiler tests skip explicitly when the separate toolchain is absent;
an unavailable compiler never silently substitutes the Python engine.

## Types, faults and host limits

- Numeric data use IEC `REAL` / native IEEE float32; Boolean data use `BOOL`.
  Python's reference uses float64. Numeric output comparison uses relative
  tolerance `2e-5` and absolute tolerance `2e-4`; Boolean/fault comparisons are
  exact. Float32 rounding and threshold differences can produce real
  mismatches. Very large finite Python results can overflow the native
  implementation; these remain visible as a fault/mismatch.
  The portable exporter can represent literals up to float32's maximum, but
  this runtime's existing generated scan guard faults numeric node results
  beyond ±`3e38`; successful export alone does not bypass that runtime bound.
- Numeric inputs must be actual finite numbers within ±`3e38`; numeric strings,
  Boolean numbers, NaN, infinity and nonzero values that underflow float32 are
  rejected. Boolean inputs must be actual Booleans. Unknown input names fail.
- Input wrappers accept only `{value, quality}`. Nongood quality sets the
  compiled ST validity input false, causing a native scan fault. The placeholder
  value is never published as a good result. Native output/state commits occur
  only after the complete scan succeeds. Tests inspect retained native state
  across faults and recovery.
- Timezone-aware clocks are required. Simple weekly schedules execute in the
  native program. IANA timezone and dated-exception evaluation is supplied by
  the host for each scan; the native validity flag guards missing bindings.
  The IANA/date evaluator is therefore not independently implemented in C.
- Each graph is limited to 2,000 expanded nodes. Each session performs at most
  1,000 scans, with one outstanding scan at a time. Timestep is finite in
  `(0,60]` seconds and must remain nonzero in float32. A scenario has at most
  10,000 events, 1,000 scans and 86,400 seconds.
- Compiler queue wait is bounded to 45 seconds. Each of the two compiler
  invocations has a 45-second timeout; this is not a single 45-second deadline
  for the complete operation. Scan request/response exchange is bounded to
  three seconds and 1 MiB. Invalid protocol/EOF/timeout closes the worker.
  Closing terminates the process, waits briefly, kills if needed and removes
  its temporary build directory.
- Generated host programs have no device/network bindings or controller
  download operations. They run as the local user, rather than in an operating
  system sandbox. Only validated graph-generated code is accepted.

The unchanged pinned MatIEC runtime headers emit Clang warnings on the tested
Apple silicon host, including `varargs`, `pointer-sign` and
`parentheses-equality`. In particular, some upstream standard functions use
named float/short variadic parameters that Clang flags for default argument
promotion. Warnings are retained in compilation results instead of suppressed.
The tested operations execute correctly on this host; these upstream warnings
remain a portability and review gap. This is an experimental host verification
profile, not a certified IEC runtime or physical controller deployment test.

## Source and licensing provenance

MatIEC's compiler is GPL-3.0-or-later. Its runtime headers carry individual
LGPL notices: for example `iec_std_lib.h` is LGPL-2.0-or-later and
`iec_types_all.h` is LGPL-3.0-or-later. The downloaded source/build directories
retain the upstream copyright notices and license files. GNU Bison has its own
upstream licensing notices retained in its private source/install directories.

This repository's adapter invokes the external compiler as a separate process.
It does not copy compiler/runtime source into the Apache-licensed application.
Generated C references the separately installed LGPL runtime headers. A native
executable includes compiled runtime-header code, so redistributing one requires
checking the applicable LGPL notice/source/relinking obligations. The verifier
currently keeps executables in temporary local directories and does not provide
a native executable export or bundle MatIEC into the application's distribution.
