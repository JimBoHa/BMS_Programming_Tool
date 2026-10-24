# Parallel fan thermal request and heating purge

The parallel-fan purge template creates one ordinary, editable Activity2 graph. It combines heating and cooling requests with separate on/off thresholds and a heating-below-off purge interval. Five live numeric ports produce two Boolean outputs: `fan_request` and `request_configuration_valid`.

The result is a logical request for a downstream fan control sequence. It is not fan speed, run proof, a hard shutdown input or a complete VAV program. It does not add occupancy, low-flow demand, fan/airflow proof, motor minimum times, electric-heat protection or physical commands. Existing equipment and series-fan templates keep their separate scopes.

## Source and authored behavior

The source is [Johnson Controls Controller Tool Help 18.0, LIT-12011147](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0), dated 2025-10-06, original PDF SHA-256 `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`. Actual PDF pages 1167–1168 and Tables 950–951 describe Fan Determination (VAV Parallel Temp Based). The text requests the fan when either heating or cooling exceeds the on threshold. Both commands must fall below the off threshold before release, with heating below that threshold for the purge duration. Documented defaults are 5% on, 0.1% off and 120 seconds of heating purge.

The source describes editable logic and last-reliable input values, but does not establish every equality, timer clamp, startup or reliability detail. This template therefore records its own strict comparisons, finite domain, elapsed counter, invalid-good handling and whole-transaction quality policy. Its Boolean request is an authored proxy for the desired Off/On state; it is not a native JCI Enum code. No native algorithm, CAF/controller package, transfer or physical acceptance is established.

The related flow-based module on PDF pages 1165–1166 additionally uses occupancy and low supply flow. That is a separate unfinished function. Its short-cycle differential warning does not make this thermal request a motor protection sequence.

## Live ports and defaults

All five input ports are required when the activity is instantiated. Defaults serve standalone definition simulation; they do not replace missing wires.

| Port | Type/unit | Default | Authored domain |
|---|---|---|---|
| `heating_percent_command` | number, % | 0 | 0–100 |
| `cooling_percent_command` | number, % | 0 | 0–100 |
| `fan_on_threshold` | number, % | 5 | Strictly above the off threshold and below 100 |
| `fan_off_threshold` | number, % | 0.1 | Strictly above 0 and below the on threshold |
| `heating_purge_duration` | number, seconds (`s`) | 120 | 0–86400 |

Both outputs have Boolean type and no unit. `fan_request` is the selected committed request. `request_configuration_valid` describes the configuration on the last successful transaction. It is not present input quality, fan reliability, occupancy, physical permission or proof that the fan is running.

Choices contain the five typed defaults plus strict whole `scan_seconds`, from 1 to 60 seconds. The default declared scan is 1 second. Construction rejects invalid defaults. Runtime wiring can still produce invalid good-quality values. Typed float defaults can deliberately admit integer JSON numbers as floats while preserving negative zero. Opaque Program metadata and parameter atoms retain the existing source rules.

## Request and purge state

The graph contains 51 ordinary nodes and 73 edges, including two Delay memories. Request memory starts false; heat-low elapsed memory starts at zero. There is one shared graph and one copy of each memory per instance, regardless of how many outputs are consumed.

For a valid configuration, start a request if heating is strictly greater than the on threshold or cooling is strictly greater than it. Retain a previous request through the hysteresis band. Release only when both current commands are strictly below the off threshold and the updated heat-low counter is at least the current purge duration. Equality to the on threshold does not start a request. Equality to the off threshold is not below it and therefore prevents release; heating at that equality also resets its counter. These ties are explicit authored rules, not verified native boundary behavior.

The counter tests the raw current heating command against the off threshold. It does not test whether a heating-demand latch is false. A heating rise into the band between off and on resets the counter even though it does not start a new request. This prevents an earlier low period from satisfying purge across an intervening heating rise.

With declared scan 1 second and purge 3 seconds, one example is:

| Scan | Heating % | Cooling % | Committed heat-low seconds | Request |
|---|---|---|---|---|
| 1 | 6 | 0 | 0 | On |
| 2 | 0 | 0 | 1 | On |
| 3 | 0 | 0 | 2 | On |
| 4 | 1 | 0 | 0 | On |
| 5 | 0 | 0 | 1 | On |
| 6 | 0 | 0 | 2 | On |
| 7 | 0 | 0 | 3 | Off |

Cooling can start a request immediately and can keep it on while cooling is in-band or at the off threshold. Cooling does not reset the heating-low counter. Low heating can accumulate time while the fan request is already off. Consequently a cooling-only request may release immediately after cooling falls below off if heating has already been low long enough. Purge is not a minimum fan running time.

Duration stays live. The elapsed counter caps at a fixed 86400 seconds, not at the current duration. Raising duration preserves already counted low time; lowering duration can permit release on that successful scan. Zero duration permits release on the current both-low scan. A fractional duration completes at the first declared scan whose elapsed counter reaches or exceeds it.

## Invalid values, quality and forcing

Arithmetic uses safe clamped copies of all five inputs. Validity also requires the originals to equal those copies and requires `0 < off < on < 100`. A successful good-quality invalid configuration holds the previous request, resets purge elapsed to zero and publishes a false configuration diagnostic. Exact off = 0, on = 100, equal/reversed thresholds and out-of-domain commands or duration are invalid. A repaired configuration begins low-time accounting again. Holding an earlier On request is not physical shutdown.

Bad quality, wrong type, nonfinite input, invalid clock or arithmetic failure follows the existing whole-scan rollback policy. It retains time, both memories and all committed outputs, potentially including an On request, a true diagnostic and earlier elapsed time. A failed interval is not counted. This behavior differs from the manual's per-input last-reliable/default connection mechanics. It does not prove uninterrupted physical low-heating conditions through a quality gap.

Before any successful scan, portable snapshots can have empty outputs and the current native host initializes outputs and state to zero/false. The template does not seed a new safe physical output set. Another permission or shutdown request in a larger program does not override whole-transaction rollback after a required-input fault.

Only internal selected request and next elapsed values feed memory. Both published outputs are terminal. A portable force on a published activity output therefore does not rewrite the two memories in this generated graph. That is a graph-specific property, not universal activity isolation or native internal-port forcing. Internal forces and manual edits can leave the recorded qualification.

## Declared clock and numeric limits

The reviewed parent must declare the same whole scan `h` as the choices. The graph adds constant `h` per accepted valid low-heating scan. It cannot read actual `dt`, and definition metadata does not create an independent clock. An explicit `dt` override, a generic import into a different cadence or a later clock/graph edit can leave this fixed-scan qualification. No global engine clock gate is added. An actual-dt-aware live-duration timer remains a separate unfinished capability.

Before addition, remembered elapsed is clamped to 0–86400. Therefore the evaluated sum is at most 86460. The graph has no division, and all evaluated branches use bounded values. Starting from zero with whole `h`, unforced counter values are integers below `2^24` and exactly representable in binary32. Fractional duration and threshold values can still round differently across widths. Existing arithmetic, literal, private-symbol, SDK/compiler profiles and comparison tolerances remain unchanged.

NativeIEC separately rejects numeric inputs outside ±`3e38` and nonzero values that round to REAL zero. Ordered portable thresholds can coalesce in native REAL and become invalid there. Host admission refusals and native/portable state differences remain visible; no epsilon or widened bound hides them. Host IEC execution does not establish native JCI or physical fan behavior.

## Review, import and remaining scope

The prefix is `/api/activities/templates/parallel-fan-purge`. `GET /catalog` exposes the profile hash, exact choices/request/import schemas and defaults. Authenticated `POST /preview` reviews an explicit Activity2 parent; its original source response contains exactly the generated `program` and `bundle.library.definitions[0].program` descriptors. `POST /export` returns original review or bundle bytes with `X-File-SHA256`. There is no unit conversion: command ports remain percent, duration remains seconds and outputs remain Boolean.

`POST /import` revalidates fresh choices, current supplied canonical parent/profile and declared clock, then uses the existing canonical-conflict Activity2 import. An unchanged preview after import is idempotent because parent binding remains outside the reusable definition. An edited definition with the same ID is not replaced silently. Legacy libraries require deliberate Activity2 migration. Incomplete editor parents can receive a reviewed definition without pretending they are executable.

These operations do not instantiate, wire, save a revision, scan, connect, acquire a power lease or write a controller. Users separately inspect/edit the ordinary definition, instantiate and wire all inputs, simulate, save/reopen and use existing interchange exports. Source hashes establish portable content consistency and stateless provenance; they are not server compare-and-swap, authentication, field permission or physical identity.

`PARALLEL-FAN-PURGE-001` covers this authored thermal-request/purge composition. Broad `MF-b292402bbd` remains partial. Flow-based and occupancy-qualified parallel fan control, executable Enum/reliability/Timer semantics, actual-dt accounting, retained physical restart, fan/airflow proof, motor/electric-heat protection, full VAV sequencing, native JCI packages/CAF/compiler/transfer and G36/Title 24/physical acceptance remain unfinished.


## Web workflow

The **Parallel fan purge template** card appears in an explicitly initialized or migrated version-2 activity library. It exposes five standalone numeric defaults and a declared whole scan from 1 to 60 seconds. Every placed instance still needs all five live inputs. The declaration must match the current parent scan; fractional purge durations are allowed without a divisibility rule. The card explains the separate raw-heating-low timer, in-band heat reset, dynamic duration, invalid-good hold/reset and complete fault rollback before import.

Preview displays the ordinary 51-block/73-wire graph and typed five-input/two-Boolean-output interface. The supported profile, exact parent identity/revision/clock, typed choices, both original Program descriptors, shared memories and literal safe topology are checked. Fresh float controls preserve negative zero and scientific tokens without projecting opaque Program parameters or metadata. Reviewed import is a deliberate reversible library edit with no second confirmation; it adds only the definition. Creating/wiring an instance, editing its ordinary graph, simulation, saving a revision and interchange export remain separate existing activity operations.

The original preview response Blob can be downloaded directly. Review and activity-archive downloads preserve original server bytes and must pass the returned byte-SHA header plus current reviewed source checks. Server digests bind these produced bytes; they are not manufacturer authentication or native compatibility. The client binds import to its exact owned editor epoch, parent identity/clock/structure and reviewed new definition. The backend rechecks the supplied canonical parent before merging. Equivalent Python exponent re-emission in existing opaque parent values does not trigger a blanket lexical comparison or JavaScript numeric projection.

Draft/scan edits, criteria reload, parent changes, explicit discard and unmount retire preview/download/import authority. A held response, including a source ABA transition, cannot replace a newer editor or save an outdated download. The UI identifies this output as a logical request rather than fan run proof, motor protection or physical switching. It also explains committed-scan timing, unchanged Native IEC admission, possible finite-width threshold/duration comparison differences, and the absence of native JCI/G36/Title 24 or physical acceptance.
