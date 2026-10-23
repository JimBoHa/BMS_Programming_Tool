# Cancelable pulse macro template

This template generates an editable, fixed-duration Boolean pulse from six existing
portable blocks. A true request starts the pulse. A committed false request cancels
it. A request held true after expiry does not start another pulse. Each macro
instance has its own elapsed time and memory.

This is an authored Studio sequence informed by the timer descriptions in Johnson
Controls Controller Tool Help 18.0. It does not encode a native JCI Timer, CAF,
controller package or download protocol. Host simulation and optional MatIEC/native
C execution do not establish physical controller compatibility or protection.

## Timing and graph

Choose a duration **D from 1 through 86,400 whole seconds** and a scan interval
**h from 1 through 60 whole seconds**. D must be at least h and an exact multiple
of h. Defaults are D = 5 seconds and h = 1 second. These are authored bounds and
resolution; they do not copy the manufacturer's conflicting limits or its native
minute rounding.

The definition has exactly six nodes and six edges:

1. Boolean `request` Input, initially false.
2. `TimerOn`, driven by request, with a fixed duration D.
3. Boolean `Delay`, driven by the timer's done value, initially false.
4. `Not`, driven by the previous committed done value.
5. `And`, combining the current request and that inverted previous done value.
6. Boolean `result` Output, driven by the AND result.

A successful scan first computes the timer's next elapsed value from the current
request. The pulse uses the **previous committed** done value. The delay receives
the current done value only when the whole scan commits. For a request that remains
true, the first published true is at h, the pulse stays true at h through D, and the
first published false is at D + h. The interval between those first published
values is D. This ordering does not claim a physical output changed at time zero.

For D = 6 seconds and h = 2 seconds:

| Successful scan end | Request | Timer done this scan | Pulse |
| --- | --- | --- | --- |
| 2 s | true | false | true |
| 4 s | true | false | true |
| 6 s | true | true | true |
| 8 s | true | true | false |
| 10 s | true | true | false |

The delayed done value is intentional. When D equals h, the first scan publishes
true and the next held-true scan publishes false. Omitting the delay would suppress
that one-scan pulse entirely.

A committed false request publishes false immediately in that scan, resets elapsed
time to zero and commits done as false. A later true request starts a new pulse.
The false scan must actually commit; it cannot be replaced by an unreliable
observation or an unobserved transition between scans. This template has no
separate reset or enable input and does not infer a native Reset Action enum.

A fresh engine or session starts with zero elapsed time, false previous done and
the input default false. An explicitly true first input starts a fresh pulse.
Restarted state is not retained. Restoring a graph document does not restore a
running timer or prove a physical controller's restart behavior.

## Parent clock and source admission

Macro definitions inherit their caller's scan interval and target. The saved
scan interval inside a definition is descriptive; it does not override the parent.
The template's preview, original export and narrow import require the supplied
parent Program's declared `scan_seconds` to equal the chosen h. A typed parent
value of `1.0` is compatible with the choice `1`; the parent source is not rewritten
for that comparison.

The parent must be a valid Program document, but it may be an unfinished editor
graph with unwired ordinary blocks. Importing a reusable definition does not
require that unfinished graph to be executable. The generated definition and the
existing macro library still pass the established macro validation rules.

The preview records the parent identifier, revision, declared scan and canonical
Program digest in an outer `parent_reference`. Those fields are excluded from the
reusable definition itself. Repeating the same D/h review after a successful
import therefore binds the new parent source while preserving the identical
definition, Program and bundle digests. The deterministic definition identifier
contains D and h. An identical same-ID definition imports idempotently; an edited
same-ID definition is refused by the existing canonical-source conflict check.

The narrow import endpoint requires the reviewed profile hash and parent digest.
It checks the current supplied Program, profile and clock before regenerating the
reviewed definition and calling the unchanged generic macro importer. This is a
stateless source/provenance and stale-payload check. It is not a saved review,
server-side compare-and-swap, authentication signature, physical identity check
or field permission. Ordinary local session authentication is still required.

Manual generic bundle imports, later parent-clock edits and per-step `dt`
overrides can leave this fixed-scan qualification. No global engine gate prevents
those operations. Historical template metadata does not certify a later edited
Program or enforce its scheduling. The GUI must retire pending reviews when its
current source, choices or clock changes and check ownership again before adopting
an import response.

## Quality, state and numerical limits

All blocks retain the existing transactional scan policy. A bad required-input
quality or invalid value refuses the whole scan. State, elapsed simulation time
and previously committed outputs remain unchanged. In particular, a false request
with stale quality **does not cancel a previously true pulse**. Its retained
output can remain true. This is a software rollback contract, not physical
shutdown, fail-safe wiring or an equipment safety function.

All macro input ports are required when an instance is wired. Boolean values are
strict; numeric zero and one do not substitute for false and true. Different
instances have separate timer and delay state. There is no hidden physical input,
output terminal, controller address or automatic connection.

The graph uses the existing host binary64 and native IEC REAL policies. Admitted
whole seconds are exactly representable through the chosen duration. This does
not promise arbitrary-duration, arbitrary-`dt` or indefinitely held timer state
will have identical trajectories in every runtime. Actual native verification
uses representative short cases within the existing worker and scan limits; it
does not execute a 24-hour test or qualify the manufacturer's full 45-day range.
No compiler flags, SDK, runtime deadlines, scan limits or tolerances are changed.

Original Program atoms, including signed zero and integer/float distinctions in
opaque parent metadata, remain part of canonical source identity. Existing JSON
serializers may spell equivalent scientific exponents differently across HTTP
and stored text; raw bodies and canonical digests are separate evidence. A digest
binds its declared source representation and does not authenticate vendor origin.

## API and original artifacts

The routes are under `/api/macros/templates/cancelable-pulse`:

- `GET /catalog` returns the profile/hash, defaults, strict schemas and export kinds.
- `POST /preview` accepts `{program, choices}` and returns the source-bound review.
- `POST /export` accepts the same fields plus `format: "review" | "bundle"` and
  returns original JSON bytes with `X-File-SHA256` and a download filename.
- `POST /import` accepts `{program, choices, profile_sha256,
  reviewed_parent_sha256}` and returns the merged current Program.

The choices are `duration_seconds` and `scan_seconds`. Booleans, strings, fractional
values, unknown fields and nonaligned clocks are refused. Public direct-call
helpers revalidate mutable model objects through a fresh dictionary so an object
changed after construction cannot bypass those constraints. POST requests need a
valid local session token. Invalid source, profile or alignment returns 422;
unauthenticated mutation requests return 403.

Preview responses can use `X-Studio-Program-Source: true`. Their two Program paths
are the standalone definition Program and the identical Program inside the macro
bundle. Import responses use the ordinary root Program source envelope. Original
source bytes, profile/choices/definition/Program/bundle digests and exact downloaded
bytes remain separate checks. Imports do not instantiate or wire a macro, save a
project, run a simulation, open a controller connection or acquire a power lease.
Those actions remain deliberate existing workflows.

Native evidence retains the original constructor Program, actual compiler ST/C,
host and executable, original compiler-returned compilation and SymbolTable before
the first scan, actual decoded step observations, and owned worker reap receipts.
A separately labeled pre-generated ST copy is compared to the actual compiler
input after construction; it is not relabeled as an independent packet or raw
stdout capture. The source graph and compiler-returned table bind elapsed and
memory observations without guessing generated names.

## Primary source and remaining work

The source is Controller Tool Help 18.0, LIT-12011147, dated 2025-10-06, physical
PDF pages 1698–1700, Table 1375. The local original PDF SHA-256 is
`68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`.
The [publisher's manual](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0)
describes rising-edge pulse behavior and cancellation on a falling input. It also
describes dynamic duration changes, Reset Action and reset on restart or logic
re-enable; those native behaviors are outside this template.

The manual's prose gives a five-second minimum while its effective-duration clamp
uses one second. It switches resolution below/above 6,535 seconds without
specifying that exact boundary. The authored limits above intentionally avoid
pretending those source conflicts define this runtime. Native reliability,
Time Remaining, dynamic Duration/Setup/Reset Action, other timer modes, native
CAF/package compilation/transfer and physical controller acceptance remain open.
`TIMER-CANCELABLE-001` covers the bounded authored template; the broad manual
capability `MF-c1feb93911` remains partial.


## Web workflow

Open **Macros → Cancelable pulse template**. Enter the fixed duration and scan in whole seconds. The parent Program scan is shown beside the declarations. Preview refuses a different parent clock, fractional values, a duration below one scan, or a duration that is not an exact multiple of the declared scan. It never edits the parent clock automatically.

Preview shows the six ordinary blocks, their parameters, all six connections, the required Boolean Request input and Boolean Pulse output, the generated Program digest, and the reviewed parent digest. The timing text distinguishes the first published true at h, the last true at D, and the first expired false at D+h. A committed false cancels immediately. Bad-quality false does not commit cancellation; rollback may retain an earlier positive pulse.

**Download original pulse review** and **Download original pulse bundle** save the server's original response Blob after checking its byte SHA-256 header and its relationship to the accepted preview. They do not reconstruct JSON from the displayed fields. The source envelope preserves both generated Program paths; only the two declared whole-number choices and typed interface fields are projected for comparisons. Source/Program digests are local software provenance, not manufacturer authentication or native JCI acceptance.

**Import reviewed pulse definition** requires an explicit confirmation and uses the scoped import endpoint with the exact current editor source, the supported profile digest, and the reviewed parent digest. The server checks the supplied parent again before the existing conflict-preserving macro merge. The browser rejects a changed editor, parent clock, profile, definition, or pending-response ownership. This is a stateless stale-payload guard, not a persisted review or server compare-and-swap. Import creates no instance, saves no revision, opens no field connection, and acquires no operation power lease. Add an instance separately and wire its required Request port through the ordinary graphical editor. Simulation, revision save, and portable interchange use the existing application paths.

Changing either declaration, replacing the source Program, reloading criteria, discarding a pending response, or leaving the view retires the relevant preview/import/export authority. A failed or unsupported criteria reload leaves old downloads unavailable. A held response cannot later adopt a definition or save a file after that authority is retired. Dismissing confirmation leaves the current editor unchanged.

The definition retains its generation evidence when subsequently edited. Generic macro import, later parent-clock edits, and per-step time overrides remain possible through the existing tools and can leave the reviewed timing qualification. The UI adds no global runtime gate, native Reset Action, retained restart promise, or physical protection.
