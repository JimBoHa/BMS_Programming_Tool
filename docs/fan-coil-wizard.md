# Portable fan-coil wizard foundation

**Equipment wizard → Fan coil** creates an editable portable graph with two separate modulating coil commands and an explicitly selected fan policy. This foundation implements authored Studio logic. It does not reproduce the JCI standard application or provision a native controller.

Choose **separate modulating heating/cooling coils**, a **single-speed** or **variable-speed** fan, **continuous while occupied** or **cycle on positive demand**, and **no condensate signal**, **disable cooling**, or **shut down the unit**. Every choice is explicit. Common two-pipe changeover, staged/on-off/incremental valves and three-speed fans are deferred. Model, firmware and release labels remain operator declarations; no terminals or actuator allocations are inferred.

## Logical sequence

The generated Boolean Inputs are `occupied` (default true), `unit_enable` (default true) and `energy_holdoff` (default false). A declared condensate policy adds `condensate_alarm` (default false). Each default can be explicitly changed. The zone and optional external heating/cooling setpoints are temperature Inputs; fixed setpoints use Constants.

Both valve commands require occupied and enabled, hold-off inactive, and heating setpoint below cooling setpoint. Unoccupied is explicitly **off**: no setback, frost protection or unoccupied heating/cooling sequence is generated. Equal/crossed external setpoints also gate both commands off. Diagnostic Outputs expose setpoint order and separate general/heating/cooling permissions.

Independent fixed-gain P/PI loops calculate heating below the heating setpoint and cooling above the cooling setpoint. Their gains are shared declarations; valve outputs are bounded from0 to100%. An inactive/inhibited loop receives its own setpoint as measured value, yielding zero error and holding its retained integral. Its selected demand and valve command are zero. Reactivation resumes the retained integral; there is no native adaptive tuning or bumpless-transfer claim.

With **disable cooling**, a condensate alarm inhibits only cooling. Heating remains available and a continuous-occupied fan can continue. With **shut down unit**, both coils and the fan are gated off. These are logical command policies; no physical protection or shutdown is established.

Continuous-occupied fan enable follows the general permission, including neutral conditions. Cycle-on-demand enable is true only while at least one selected coil demand is positive. It uses numeric demand without hysteresis, minimum-run, anti-short-cycle or restart timing. Variable speed maps the maximum selected coil demand from0–100% to the declared minimum/maximum speed, only while fan enable is true; a stopped logical fan has speed0%. Neutral continuous operation therefore uses the declared minimum. Those percentages neither prove airflow nor establish a permissible physical minimum speed. A single-speed selection produces only Boolean fan enable.

Bad-quality inputs, nonfinite values and unsupported arithmetic use the Engine's transactional scan fault: prior committed state and outputs remain. This differs from the authored good-quality off/inhibit policy. A previously positive valve command can remain in the retained simulation snapshot after a bad-quality fault; this is not a fail-safe field interlock.

## Units, source and workflow

Fahrenheit/Celsius changes convert the absolute zone/setpoint values and reciprocal temperature gains together. Percent limits, fan choices, Boolean defaults and scan seconds retain their meaning. VAV airflow, damper and parallel-fan hysteresis choices remain inactive evidence and create no fan-coil points. Inactive single-speed percentage limits or unused condensate defaults are listed explicitly.

The new generator profile is `studio-fan-coil-selection/1`. Preview and generated metadata retain its exact profile/source/choice hashes and the generated Program digest. The preceding single-duct and dual-duct profiles, saved graphs and generation digests are unchanged. No old artifacts are migrated or regenerated. Intentional normalization of newly authored editable choice/parameter numbers follows the existing wizard schema; original native receipts are unaffected.

Use Preview to inspect the actual logical points and limits, then Create, normal graph editing/simulation, revision save/reopen and JSON/ST/PLCopen/GraphML interchange. Choice or current-editor changes retire preview authority; replacing a nonempty editor requires confirmation. Creation does not save implicitly or open a field interface. Manual edits retain the original generation evidence without claiming it describes those later edits.

## Primary source and verification

JCI **Controller Tool Help18.0**, LIT-12011147, PDF479–483 describes the core fan-coil interfaces, fan/coil selections, variable-speed proportional-coil restriction, condensate inhibit versus optional shutdown, enable/energy hold-off and occupied fan cycling. Reviewed PDF SHA256: `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`. [Official Help](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0).

Those pages qualify the equipment choices. The fixed-gain logic, explicit unoccupied-off behavior and zero-error integral hold are authored policies. Native enable fallback behavior, fan-status protection, adaptive tuning, balancing/position feedback, water flushing, minimum-run/restart timing, unoccupied setbacks/frost protection, ventilation/discharge limits, physical sensor/actuator allocation, CAF creation/compilation/transfer and package/firmware acceptance remain unimplemented. Complete Guideline36/Title24 behavior and physical manufacturer acceptance are not established. FC-001 is the scoped foundation; broad MF-2e7fda5bcf remains partial.

Independent Engine tests calculate cooling/heating/neutral/saturation commands, all fan/condensate policies, retained integrals and resume, good-quality off gates, bad-quality rollback, strict choices and coupled unit conversion. Actual fixed-host MatIEC/Clang tests compile and execute each fan/policy/condensate choice in both temperature units, including modes, inhibition, crossed setpoints, fault retention and owned-process closure. This is host IEC execution, not JCI firmware execution. HTTP and browser tests cover actual authoring, guarded preview, simulation, save/reopen and downloaded source evidence with field networking closed.
