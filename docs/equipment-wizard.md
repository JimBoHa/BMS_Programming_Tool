# Equipment and sequence wizard

The editor's **Equipment wizard** creates a separate, uniquely identified portable VAV project from declared equipment, sensor, strategy and engineering choices. It previews logical inputs/outputs, generated topology, validation findings and exact choice/profile/program hashes before replacing the editor contents. Existing **New** and illustrative templates remain available.

Choose cooling only, inline modulating hot-water reheat without a fan, or parallel-fan hot-water reheat. Select a declared portable/FX/Metasys target and optional model, firmware and CAF release-mode labels. These labels do not establish native compatibility, installed packages, physical terminals or controller capacity.

## Strategies and parameters

- **Damper-position demand mapping:** zone P/PI cooling demand maps to declared minimum/maximum damper position percentages. Those percentages are not measured airflow or design ventilation. No airflow sensor or flow loop is generated. The older static template's misleading `Minimum airflow` label is now `Damper position mapping`; existing saved projects and its numeric behavior are unchanged.
- **Measured-airflow feedback:** a numeric airflow Input, declared minimum/maximum airflow setpoint map and a separate P/PI airflow loop generate the damper-position command. The input must already represent calibrated airflow, and increasing the command is assumed to increase airflow. The generated logical airflow-setpoint Output makes that intermediate signal inspectable.
- Setpoints can be constants or separate logical temperature Inputs. Reheat has a separate zone heating loop. Parallel fan enable uses declared heating-demand on/off hysteresis; it does not prove fan operation. Electric stages, fan proof, discharge limits, occupancy/ventilation coordination and physical interlocks are not generated.

Finite bounds, equipment-dependent constraints and P-only zero-integral constraints are checked by the server. Parameter choices that do not participate in the selected strategy remain in the choice evidence and are explicitly listed as inactive. Input setpoints have no automatic runtime range/deadband enforcement. Defaults are illustrative starting values, not a validated plant design.

## Engineering units

Unit changes convert values and gains together. Fahrenheit/Celsius conversion applies the absolute offset to zone/setpoint values and only the difference slope to inverse-temperature gains. Both proportional gain (`%/delta-unit`) and integral gain (`%/delta-unit/second`) change reciprocally to preserve the declared physical response. Airflow values and both inverse-flow gains receive the corresponding reciprocal conversions. Scan seconds, fan thresholds and percentages retain their meanings.

Using the exact international foot definition, `1 cfm = (0.3048 m)^3 × 1000 L/m³ ÷ 60 s = 0.4719474432 L/s`. The foot definition is from the [NIST unit conversion reference](https://www.nist.gov/pml/us-surveyfoot/revised-unit-conversion-factors); the volumetric-flow factor is derived here. This scoped conversion does not implement general dimensional algebra.

## Workflow, persistence and evidence

1. Select equipment and declared target, then sensors, strategy, units and parameters.
2. Preview the generated graph, actual logical signals, core validation findings and unimplemented sequence areas. The preview includes full declared choices, primary workflow reference, profile/choice hashes and initial program digest.
3. Create the editable project. Replacing a nonempty or saved editor requires confirmation so current edits can first be saved/exported. A fresh project ID prevents overwriting the source revision, and Undo retains the prior editor state.
4. Use normal graph editing, simulation, revision save/reopen and exports. Choice metadata records the original generation decisions; later manual graph edits do not automatically regenerate or update those original choices. A saved revision changes the program digest because the revision is part of the program identity.

Changing choices or the current editor source invalidates the preview. Closing the dialog retires pending replies. Late or mismatched choice/profile/program-identity responses cannot create a project. The API does not save projects implicitly or open field interfaces.

Generated editable parameters and choice JSON intentionally normalize integral floating values and signed zero to integers before hashing. This newly authored schema survives browser JSON number round trips. No existing graph schema/hash or native evidence is normalized or resealed. Hashes identify submitted choices and the documented generator profile; they are not manufacturer authenticity, native compiler or certification evidence.

## Primary workflow reference and limits

Controller Tool Help 18.0, LIT-12011147, PDF pages 149–151 and 153–154 describes equipment/components/strategy selection, required sensors, name/device/release/unit choices, separate simulation/hardware definition and regeneration overwriting customized logic. Reviewed PDF SHA-256: `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`. [Official Help](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0).

That reference qualifies the authoring workflow. The generated graphs are Studio-authored illustrative sequences, not copied manufacturer standard CAF logic. Native CAF creation/allocation/compilation, package/model/firmware acceptance, real wiring and controller deployment remain separate gaps. The wizard does not establish complete Guideline 36 or Title 24 behavior or certification.

## Verification

Authored tests calculate P/PI outputs and retained-state trajectories independently, including airflow feedback, heating/fan hysteresis, unit equivalence and sensor-quality rollback. Optional pinned MatIEC/native-C tests execute generated ST against hand-calculated values; metric airflow uses an explicit 0.001-flow-unit tolerance for float32 cancellation. This host execution is not native JCI execution. Production API tests verify strict bounds/token checks and exact revisioned save/export/restart reopen without opening field interfaces. Actual browser workflows exercise authoring, stale/closed/mismatched replies, coupled unit conversion, simulation, save/reload and a downloaded project independently parsed and executed by Python.
