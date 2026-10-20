# Temco Control Basic adapter

The adapter exports genuine numbered `.bas` source, imports a declared native
subset into editable graphs, compiles with Temco’s own compiler, and executes
actual native bytecode in a local host of the controller interpreter. All 27
graph block types have native execution tests. Physical controller configuration,
download and online application replacement remain outside this adapter.
Simulated IN/OUT/VAR points are memory arrays; the host has no field transport.

The separate [native program-transfer adapter](temco-transfer.md) implements
BACnet slot inspection, backup, stop/replacement/readback, conditional resume
and compensating restore. Its narrower physical firmware profile has a
128-VAR limit and refuses unprovisioned calendars. Local UDP/routed emulator
tests do not establish physical execution, flash persistence or scan cadence.

## Manufacturer source and reproducible build

The reference comes from the manufacturer-published MIT repository
[T3000 Building Automation System](https://github.com/temcocontrols/T3000_Building_Automation_System/tree/ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b),
pinned at `ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b`. Relevant sources are
`T3000/CM5/BacNetProgram_transplant.cpp`, `T3000/CM5/PARSER.H`,
`T3000/decode.c`, `T3000/vm_shim.h` and `T3000/VirtualProgramEngine.cpp`.
The original license is retained in
[Temco-T3000-LICENSE.txt](../third_party/Temco-T3000-LICENSE.txt).

Run `.venv/bin/python scripts/setup_temco.py` with Clang available. A missing
external checkout is downloaded into
`../Reference_Sources/temcocontrols--T3000`. The script refuses an unexpected
revision or changed tracked source. All adaptations are applied to build copies
under `build/bms-host`; upstream tracked files remain untouched.

The host replaces Windows string helpers, preserves the Windows 32-bit integer
ABI for interpreter values, corrects mismatched array deletion in the copied
compiler, and restricts the point resolver to bare local IN/OUT/VAR references.
Remote point, external alarm and unsupported field hooks abort. Jumps/GOSUB that
need platform pointer handling are excluded from accepted source. Compiler and
VM execution run in bounded subprocesses. The manifest records the upstream
revision, source hashes, adapter hash and binary hashes. Runtime verifies binary
hashes before execution. Set `BMS_TEMCO_HOME` to an explicitly installed host.

## Source profile and retained state

All 27 graph types lower to executable native statements: Input, Output,
Constant, Add, Subtract, Multiply, Divide, Min, Max, Abs, Clamp, Scale, Convert,
Greater, Less, Equal, And, Or, Not, Switch, Delay, PI, Deadband, TimerOn, Slew,
Alarm and Schedule. Nested macros are expanded first. Additional native Sedona
components are rejected rather than omitted.

Delay, PI, hysteresis, timers, rate limiters and alarm thresholds use persistent
private native locals. Nonzero initial state is initialized on the first valid
scan. New state and outputs are staged until all calculations succeed; a later
zero divisor holds both, including the first scan. Delay feedback is committed
after all graph values have been evaluated. PI preserves conditional antiwindup
and reverse action. Timer accumulators saturate at their configured threshold,
which preserves Boolean behavior while preventing multi-day integer rollover.

Each invocation advances time-dependent state by `program.scan_seconds`. A
physical destination host must provide that scan cadence. Each local verification
starts a fresh native instance, then keeps its bytecode/local-state buffer for
all requested scans. Bounded changing-input frames are available for acceptance
tests. Every output at every native scan is compared with the separate graph
engine; final equality does not hide an earlier difference.

Graph inputs bind to `IN1..64` or `VAR1..256`; graph outputs bind to `OUT1..64`
or `VAR1..256`. All interface bindings are explicit and unique. Defaults map
inputs and outputs sequentially. Existing vendor terminal labels are not silently
reused as Temco physical bindings.

## Calendars and quality

Each Schedule reserves two unused VAR points for **active** and **valid** flags.
The host evaluates IANA timezone, DST, overnight and dated-exception behavior,
then supplies those flags before every native scan. An invalid or unbound flag
ends the scan before any state/output commits. The compiler response exposes
these required bindings. The native interpreter verifies flag gating and
publication; it does not independently calculate IANA calendars. The local UTC
clock is explicit and advances between native scans. Calendar plumbing tests
cover both fall-back folds, spring-forward, exception days and minute boundaries.

Native source has no physical sensor quality channel in this profile. Local
verification rejects bad-quality inputs. Commission physical sensor range,
quality/fault handling and calendar-host bindings before any future deployment.
The graph Alarm block computes its threshold/timer Boolean; external alarm
notification and controller alarm configuration are not supplied by this adapter.

## Numeric and resource limits

Arithmetic uses signed 32-bit fixed point with 0.001 resolution. Native literals
must be multiples of 0.001 within ±2,000,000. Overflow and quantization differences
remain visible in native/reference comparisons; they do not become a success
badge. Numeric comparison tolerance is 0.01 absolute or 0.001% relative; Boolean
comparison is exact. Scale uses an exact fixed-point gain when representable,
avoiding amplification of a quantized 0..1 intermediate. Nonrepresentable-gain
cases remain explicitly tested as differences.

Native comparison instructions use a different raw Boolean scale from ordinary
numeric constants. Generated conditional assignments normalize Boolean results.
Division guards retain published outputs and persistent state on a zero divisor.

Source is ASCII, at most 24 KB and 180 increasing numbered lines. Before
invoking native code, preflight limits the source to 400 unique native symbols,
1,800 bytes of local-name/value storage, 16 operands per expression, eight
postfix opcode bytes per operand and a conservative 400 encoded bytes per
statement. These limits leave room below upstream’s 500-symbol table,
4,000-byte local region, 20-operand array, ten-byte postfix slots (including
termination), and 450-byte statement buffer. The actual manufacturer compiler enforces a
native program size below 2,000 bytes. Larger applications are rejected with its
real diagnostic; this adapter does not claim to bypass controller memory limits.

## Import and authoring annotations

Foreign import supports straight-line assignments, arithmetic and logic, ABS,
two-operand MIN/MAX, and single-line IF/THEN/ELSE selections assigning the same
variable on both branches. The division-guard pattern is accepted only before
its matching division. Source-order assignments become graph dependencies;
physical point writes become outputs. Source case is normalized for compilation.
Arbitrary foreign loops, jumps, remote I/O, wait/time functions and unsupported
implicit coercions are rejected.

Generated stateful/calendar sources also contain optional standard REM authoring
annotations for lossless graph reimport. The numbered executable body remains
real BASIC and is regenerated and compared in full before annotations are
accepted. Changed code with stale annotations is rejected. Metadata decompression
is bounded to 512 KB. Comments are stripped before native compilation to conserve
controller program memory; there are no supported jumps whose targets depend on
those comments. The GUI previews executable statements and downloads the full
annotated source. This is executable source with checked authoring metadata,
not a JSON file renamed as BASIC.

Foreign source lacks engineering units and physical hardware/quality setup, so
its imports carry a review-required conversion report. A validated generated
artifact recovers its original graph, state semantics, units and macro library.

## Local evidence

`tests/test_temco.py` has **162 passing tests**. These include actual compiler and
interpreter execution for all 27 types, six changing-input state trajectories,
PI antiwindup and reversal, delayed feedback, rollback on later/first-scan
arithmetic faults, timer saturation, nested stateful macros, host-calendar flags,
annotation integrity/decompression bounds, numeric differences, compiler
resource preflight and provenance. A diagnostic ASan build with the adjacent
timer region explicitly poisoned confirmed that a previously accepted 12,113-byte
foreign source could overwrite `local_table + 4000` during `createlocaltable`,
before the later 2 KB output check. Ordinary allocation-boundary ASan misses
this because both regions share one allocation. The new local-storage preflight
rejects that source before starting the compiler. The local diagnostic is in
`local-reports/temco-native/compiler-region-asan.txt`.

Comment stripping also requires the complete `REM` keyword: a local variable
such as `REMARK` remains executable. A raw-source native bytecode/interpreter
test verifies that `REMARK = 42` publishes 42, rather than silently dropping its
assignment.

All nine illustrative VAV profiles compile and match the portable reference for
60 native scans: cooling-only uses **388 bytes**, inline reheat **689 bytes**,
and parallel fan reheat **923 bytes**. The FX/Metasys labels describe the source
graph’s intended application; those graphs were compiled for the Temco reference
here. This does not make their bytecode executable on JCI controllers and does
not certify any sequence against Title 24 or Guideline 36.

Six browser workflows pass against the real compiler/interpreter: source and
bytecode download, custom VAR bindings, changed numeric values, bad-quality and
invalid-point errors, retained-state traces, an explicit UTC calendar boundary,
foreign-extension rejection and visible overflow mismatch. No compiler response
is mocked. This host has not been tested on physical Temco hardware and is not
a certified replacement for the complete T3000 front end or controller firmware.
