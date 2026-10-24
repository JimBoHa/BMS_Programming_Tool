# Editable zone effective-setpoint composition

Open **Zone setpoint wizard** in the equipment wizard. The separate `studio-zone-effective-setpoints/1` profile creates a fresh editable ordinary-core Program with fixed declared occupied/unoccupied heating and cooling pairs. Optional population setback and an optional absolute window-open pair compose the effective targets. This graph outputs targets and logical diagnostics. It does not start equipment, assign a physical sensor, publish native occupancy MV values or control airflow.

Explicitly select each optional branch. Off branches refuse residual controls and omit the corresponding Input. Every graph has `scheduled_occupied`; population adds `populated`, and window adds `window_open`. These are logical Boolean Inputs with declared defaults, not automatically discovered or wired points. Scheduled occupied defaults false, populated defaults true when selected, and window defaults closed.

## Target selection and clocks

Scheduled occupied selects its fixed heating/cooling pair; otherwise the unoccupied pair is used. The population branch activates a deadband-expanding difference after continuously occupied-but-unpopulated time. It subtracts the difference from heating and adds it to cooling. Once active, it remains until continuously populated for the full release interval, or clears immediately when scheduled unoccupied.

The reference intervals are 300 seconds entry and 60 seconds release. Exposed customization is an explicit authored choice, not a recovered native parameter contract. Scans are whole 1–60 seconds. Both positive intervals, up to 3600 seconds, must be exact multiples of the declared scan. Memory/timers initialize false/zero; the first successful scan represents one elapsed interval. Entry or release completes on the scan reaching the full interval. Chatter resets the corresponding continuous dwell.

Window open selects its declared absolute heating/cooling pair above base and population output selection, including during unoccupied operation. **Population timers continue behind the window override.** Closing the window reveals their current state. Scheduled unoccupied still clears the latent population state while a window is open. This behind-window timing rule is authored because the cited manual does not specify it.

Outputs are:

- `effective_heating_setpoint` and `effective_cooling_setpoint`, in the selected absolute temperature unit.
- `occupied_base_selected`, meaning the occupied target family is visible rather than hidden by a window profile. This remains true when a population offset is applied; it does not identify an unadjusted nominal pair.
- `population_setback_ready`, the **latent timed state**, which can remain true behind an open window.
- `population_offset_applied`, meaning that population difference is actually selected in the outputs.
- `window_override_active` and `applied_population_offset`; the applied difference is zero during window override.
- `setpoint_profile`, authored codes 0 unoccupied, 1 occupied, 2 occupied plus population offset, 3 window. These are not native enumeration values.

There is no separate legacy Standby pair in this profile. Native fixed Standby presets and the G36 timed population offset are different layers; applying both unknowingly would double-count behavior.

## Values, units and quality

All reachable heating/cooling pairs must be ordered and inside the authored −50 to 100 °C equivalent software range. Validation includes base, population-adjusted and window pairs. It refuses invalid choices rather than silently clipping them. These bounds are not project safety limits or proof a historical window preset is suitable for equipment or occupants.

The reference choices start at occupied 70/74 °F, unoccupied 61/82 °F, population difference 1 °F and optional window 40/120 °F. Branch selection and values remain explicit. F/C conversion moves all absolute pairs and the population difference together, while Boolean/timing values remain unchanged. Differences scale without an absolute-temperature offset. Rounded manufacturer C/F defaults are retained as source facts; conversion does not replace selected values with those rounded defaults.

Existing binary64/core and REAL/float32 native-host numeric rules remain. Conversion and nonlinear execution are not promised to be invariant at finite precision. For example, the smallest positive binary64 difference 5e-324 °F remains positive at 5e-324 °C but converts back to 1e-323 °F. Native representability/precision and physical significance of such tiny choices remain separate limitations.

**Bad quality on any selected required Input faults and rolls back the complete scan**, retaining previous targets, latent state and timers. This includes a bad population/schedule Input during window override. A logical higher-priority window selection does not bypass required-input quality evaluation. It is not a physical shutdown or a native last-reliable-value implementation. Failed scans do not advance state or time.

Before the first successful scan there are no committed target values. An initial fault retains the existing Python host's empty outputs or the native host's zero-initialized outputs; it does not preseed a safe target pair. The first successful scan selects the declared profile. Constructor range/order checks describe reachable successful target pairs, not physical protection or a special startup fault fallback.

## Editing, reuse and exclusions

Generated Constant/Switch/TemperatureOffset/Delay/TimerOn/Boolean nodes remain visible and editable. Profile, choices and actual Program have separate hashes. Typed manifests are derived from real Input/Output nodes. Use ordinary simulation, source interchange and project revision save/reopen after creation. Later manual graph changes do not automatically revalidate original wizard provenance.

The separate API is `GET /api/zone-setpoint-wizard/catalog` and token-protected `POST /preview`, `/units`, `/export`. Preview supports the existing `X-Studio-Program-Source` header. Units bind original and converted choice hashes. Export returns the original server review body with `X-File-SHA256`. No endpoint opens a field interface, queries a controller, saves a project implicitly or invokes a JCI compiler/loader.

An explicit System simulation link can connect these outputs to compatible external setpoint Inputs. Its existing previous-cycle delay still applies. Supplying unoccupied targets does **not** change an equipment generator's separate occupied-off or enable policy. No existing wizard, core block, compiler or source transport is changed for this feature.

Demand-limit selection/stacking and local-adjustment freezes, network/hardware setpoint arbitration/fallback, native override/bypass/temporary occupancy, warmup/cooldown/setup/setback/freeze group arbitration, equipment unoccupied operation, minimum-flow/ventilation, sensor mapping and physical protection remain future work. Current macros expose one Output; the two target outputs therefore remain a normal flat Program rather than an opaque macro.

## Source and verification

Primary reference: [Controller Tool Help 18.0](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0), LIT-12011147, original PDF SHA256 `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`. PDF 753–756 describes ZN-T target determination, fixed occupied/standby/unoccupied values and local/network adjustments. PDF 854–855 describes the separate timed population/window offset module and its VAV/single-zone AHU mapping. PDF 1129–1130 describes the larger occupancy hierarchy, which is not reconstructed here. The manual's uneditable-module restriction is addressed by this openly editable authored graph, without claiming recovered native internals.

The 2021 Yorkland/Johnson Controls training presentation, PDF 5, SHA256 `075565f9664a80f9720ae68c1020c84cb08ad12aaaa7aef5d329ad4ac2d9ed3d`, supplied the original review criterion. Its one-degree and 40/120 examples alone do not establish units or complete logic. CCT's Window Open table wording mentions output airflow in a setpoint module; this feature does not infer airflow outputs from that wording.

Independent tests cover all four branch combinations, F/C and aligned scan variants against a separate elapsed-duration oracle; reference 300/60 boundaries; chatter, hidden timer transitions and unoccupied reset; all reachable target ranges/order; strict branch choices; subnormal conversion qualification; required-quality rollback; actual API/source/export/revision/restart and source interchange. Ordinary MatIEC/native-worker evidence covers generated compositions and the full reference timing without changing compiler/SDK/deadlines/tolerances. Software verification does not establish native JCI, physical sensor/equipment, full G36 or Title 24 acceptance. `ZONE-SP-001` records this bounded feature; broad `MF-b04d70f58e` remains partial.
