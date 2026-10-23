# Occupied Unit Ventilator Cycle III foundation

**Equipment wizard → Unit ventilator Cycle III wizard** creates a separate editable ordinary graph for an occupied single-speed supply fan, separate proportional hot-water and chilled-water coils, and one mixed-air/outdoor-air damper command. Increasing the damper command is assumed to admit colder outdoor air and reduce mixed-air temperature (MAT). This is a declared engineering prerequisite, not a measured or validated mixing model. No complementary return-air output, physical terminal or automatic external setpoint link is generated.

The authored profile is `studio-occupied-uv-cycle3/1`. It is distinct from the existing fan-coil, SAT-based AHU, heat-pump and series/parallel/inline VAV applications. It does not reproduce a native JCI v51 module, allocate hardware, compile or transfer CAF files, establish physical protection, or certify ASHRAE, Guideline 36 or Title 24 behavior.

## Primary criteria and authored choices

The reference is [Controller Tool Help, edition 18.0, LIT-12011147](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0), original PDF SHA-256 `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`.

PDF 490–494 describes unit-ventilator mechanical options and cycle-dependent sensors. Cycle III requires MAT control and a damper minimum; Cycles I, II and W require different discharge-air controls. PDF 1112–1114 separates direct zone coil control from MAT ventilation control. Figure 143 uses native Heating/Cooling/Damper Control Status High/Low/IsResponding and fast-setpoint flags. This graph uses explicitly authored hysteresis and previous selected heating command instead of inventing those native status enums.

PDF 1273–1276 describes the shared damper controller: MAT is its UV main process variable, zone temperature is the UV low-limit variable, and limit control selects the lower damper command. The shared module also contains heat-pump defaults; its default Process ID must not replace these explicit UV input roles. The native command hierarchy includes fire overrides, Hold, tracking and tuning-reset behavior that this foundation excludes.

Fan Status on PDF 490 and position feedback on PDF 493 are monitoring-only selections unless additional control is selected or authored. The following stable-proof, deadline and latched-loss policy is authored behavior. It is not inherited physical safety or a native default. The Fahrenheit references are chosen values; source pairs such as 55 °F/13 °C are rounded alternatives, not interchangeable exact conversion values.

## Inputs, admission and fan lifecycle

There are 13 required logical inputs with declared simulation defaults:

- Boolean: `occupied`, `unit_enable`, `energy_holdoff`, `airflow_proven`, `fan_reset`, `condensate_alarm`, `heating_available`, `cooling_available`.
- Absolute temperature: `zone_temperature`, `mixed_air_temperature`, `heating_setpoint`, `cooling_setpoint`, `mixed_air_setpoint`.

The external heating target intentionally also supplies the zone low-limit damper target. Ordinary graph edits or explicitly simulated values can supply targets from another Program, including the zone setpoint wizard; no native object or automatic graph connection is inferred.

Raw request is occupied AND unit enable AND NOT energy holdoff. `setpoints_valid` checks all three setpoint ranges and strict heating-below-cooling order. `temperature_range_valid` separately checks zone and MAT ranges. All absolute values require -50..100 °C equivalents. These broad authored bounds are not physical operating limits. An invalid good-quality value stops ordinary commands/readiness and restarts startup without itself adding a fault or counting as operator off.

The fan starts on the first successful permitted request scan. There is no series-VAV damper-close estimate. Stable proof counts only while fan is requested and continuously proven. An independent deadline spans chatter. Defaults are an authored 5-second proof interval and 60-second startup deadline. The first successful request scan represents one elapsed scan interval; with one-second scans and continuous proof, readiness begins on request scan 5. Stable proof completing at the exact deadline wins, so a true deadline diagnostic alone does not establish a trip.

Missing startup proof at the deadline latches a fault. Good-quality proof loss after a ready scan immediately latches and stops fan, valves and damper in that same scan. Only raw request off plus a fresh rising `fan_reset` edge clears the latch. Holding reset through value inhibition or later raw off does not create another edge. `reset_accepted` means a clear edge was admitted, even when no previous fault existed. Permission loss resets timers/readiness, while PI integrals remain retained.

`condensate_policy` requires an explicit choice before preview or unit conversion:

- **disable-cooling**: an alarm selects cooling valve zero and holds its inactive integral; fan, MAT and heating may continue.
- **shutdown-unit**: an alarm also inhibits fan/MAT/heating/readiness and resets startup timers. Raw request remains unchanged, so this does not authorize a fault reset.

There is no separate condensate latch. Heating and cooling availability gate only their respective selected coil commands, not raw request or fan readiness.

## Zone control and MAT limiting

The zone modes are mutually exclusive. A heating error or cooling error at or above the positive entry difference enters its mode. An opposite entry switches directly. Otherwise an active mode releases only strictly beyond the opposite release difference and when its **previous selected coil command** is zero. Equality at a zero release difference does not release the mode. Readiness loss clears mode memories. Availability can make the selected command zero even while raw PI memory remains positive; that inactive raw value is not the release authority.

The heating PI directly controls the hot-water valve. The reverse cooling PI directly controls the chilled-water valve. Each selected command is 0..100%. Inactive loops see measured equal to setpoint, retain their integral through zero error, and select command zero. MAT or zone limiting never boosts heating.

The MAT reverse PI produces more demand when MAT is above its target, under the cold-outdoor assumption. Its raw 0..100 output maps to the declared minimum position through 100%:

`mapped MAT = minimum + (100 − minimum) × raw / 100`

A minimum of 100 is defined and produces a constant mapped command of 100. The displayed `mixed_air_damper_demand` is selected zero while not ready. Mechanical cooling unavailability does not itself disable MAT ventilation control.

Zone limiting is selected while ready, in heating mode, below the heating target, and either the previous selected heating valve was 100% or heating is unavailable. This authored unable-to-heat condition substitutes for only that declared function; it does not create native `ControlStatus` or `IsResponding` semantics.

A forward zone-cold PI produces correction 0..100. Its latent allowed position is `100 − correction`. In limit mode the selected damper is:

`max(minimum, min(mapped MAT, allowed position))`

Otherwise it is mapped MAT. This can restrict OA toward its minimum but cannot close it below that declared minimum. The limiter affects the damper only. When inactive it holds integral memory. `zone_limit_correction` and `zone_limit_allowed` can therefore show retained latent values while the limiter is not selected. `zone_limit_restricting` is true only when the final minimum-clamped actual selected damper is below mapped MAT. At minimum 100 it cannot reduce the command. Neither minimum position nor logical proof establishes measured ventilation or physical freeze protection.

## Quality, units and source fidelity

Every required input is evaluated by the unchanged transactional runtime, including when another input asks for shutdown. Bad quality or nonfinite arithmetic rolls back the whole scan: outputs, modes, timers, reset edge, delays and integrals all retain their previous committed values. Positive commands can remain after a failed scan. Before the first successful scan there is no preseeded safe output set; core snapshots can be empty and the existing native host initializes outputs to zero/false. This differs from the source's individual-input reliability fallbacks and is not a physical shutdown guarantee.

Unit conversion couples five absolute temperatures, two differences and eight inverse-temperature gains between degF/degC. Identity, flags, percentages and aligned whole-second timing remain unchanged. Strict conversion validation can refuse adjacent legal differences that collapse together after binary64 conversion; the original draft remains authoritative. There is no invented minimum, tolerance widening, state migration or promise of unit-invariant nonlinear trajectories. Existing host binary64 and native REAL/float32 policies remain unchanged.

This wizard's local authored-number representation canonicalizes integer-valued floats to integers, except that it preserves negative zero in choices, generated parameters and conversion responses. This is separate from global source codecs or native evidence interpretation. The authoritative original server Program source and export bytes retain their actual spelling, including generated negative-zero release constants and scientific values. Content hashes establish portable integrity, not manufacturer authentication.

The graph has 198 ordinary nodes for disable-cooling or 197 for shutdown-unit, with 13 inputs and 29 outputs in either case. The shutdown branch omits an unnecessary constant. `heating_requested`/`cooling_requested` describe held modes; `heating_active`/`cooling_active` mean permitted loops and can be true with zero command. Authored `unit_state` is 0 off, 1 fan-start, 2 run, 3 fault. `thermal_state` is 0 neutral, 1 heat, 2 cool, 3 zone-limited heat. These are not native enumeration values.

## API, evidence and remaining scope

`GET /api/unit-ventilator-cycle3-wizard/catalog` supplies the source-qualified profile, limits, strict Choices schema and incomplete defaults requiring the condensate policy. Token-protected `POST /preview` and `/export` accept `{choices}`. Preview supports existing original Program-source transport; export returns original review JSON and `X-File-SHA256`. `POST /units` takes `{choices,temperature_unit}` and separately binds original and converted choices. None opens a field interface, creates a power lease or modifies a controller.

Core and actual local API tests cover the independent fan machine, exact thresholds, direct coils, MAT limiting, minimum 100, unavailable heat/cooling, both condensate policies, selected-command versus integral retention, every required bad-quality input, source/export/save/reopen and coupled units. Actual pinned MatIEC/clang tests execute generated graphs across F/C, P/PI, two scan intervals and both policies, with independent lifecycle and REAL control checks. Supplemental analytic traces verify integral retention, selected-command release and minimum 100. Original Program/ST/C/host/executable artifacts and decoded worker observations are retained privately; decoded observations are not raw stdout capture or physical controller evidence.

`UV-C3-001` records this bounded authored foundation; broad `MF-069429184f` remains partial. Cycles I/II/W, variable/three-speed/external fans, DX/electric/staged/changeover/face-bypass coils, unoccupied recovery and coil protection, warm-outdoor action, OAT/RAT suitability, physical airflow/actuator protections, native adaptive tuning/status/tracking/fire modes, native CAF allocation/compiler/transfer and full compliance/physical acceptance remain separate work.

## Web workflow

Open **Equipment wizard → Unit ventilator Cycle III wizard** and explicitly choose the condensate policy. The unit picker and preview remain disabled until that choice is made. Configure the declared target, logical temperature/default permissions, minimum OA position, all four P/PI gain pairs and aligned proof/deadline timing. Unit conversion keeps the bounded form choices coupled; the returned Program's opaque source numbers remain separate and untouched.

Preview lists all 13 actual generated inputs and 29 outputs with types, units and defaults, the ordinary graph diagnostics, exact source/profile criteria and remaining engineering scope. Requested modes, permitted loops, latent limit values and actual selected restriction have distinct explanations. Program and choice digests identify server evidence; they are not independent manufacturer authentication or native deployment acceptance.

**Export original unit ventilator Cycle III review JSON** saves the original HTTP Blob only after its byte SHA-256 and exact current preview/source context agree. Changing the draft or loaded editor, discarding a pending response, backing out or closing the wizard retires that authority. No field operation is started. Creating the separate editable project requires current source authority and an explicit replacement confirmation when the editor already has work. Existing simulation, undo, revision saves and JSON/ST/PLCopen/GraphML exchange then operate on the ordinary graph. Saved revisions retain the canonical Program identity and numeric values, including negative zero; raw HTTP and stored JSON can use different equivalent exponent spellings and are retained separately in validation evidence.

The form retains an explicitly entered negative zero and uses source-preserving requests for preview, unit conversion and original review export. Conversion validation distinguishes zero signs as well as values. Editing zero to negative zero clears previous preview authority; a temporarily blank numeric field remains editable, refuses preview without dispatching an invalid request, and can be corrected before reviewing again.
