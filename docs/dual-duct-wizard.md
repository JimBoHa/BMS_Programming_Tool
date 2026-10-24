# Portable dual-duct VAV wizard

Equipment wizard → **Dual duct: declared hot and cold decks** creates a separate editable portable graph. It adds distinct logical hot/cold demand and percentage damper commands. Target/model/firmware/release labels remain operator declarations; integrated, proportional and incremental actuator hardware is not allocated.

## Explicit pickup and control choices

Position mapping requires the explicit **No airflow pickups** layout. Zone cooling demand maps to declared cold-deck minimum/maximum position; heating demand maps to separate hot-deck position bounds. No measured airflow input or inferred flow is generated.

Airflow feedback requires one of three explicit two-pickup layouts:

| Measured inputs | Third flow derived by the graph |
| --- | --- |
| Hot and cold decks | Total = hot + cold |
| Hot deck and total | Cold = total − hot |
| Cold deck and total | Hot = total − cold |

Inputs must already represent calibrated airflow in the declared common unit. No pressure-to-flow conversion, pickup calibration or sensor identity is inferred. Raw measured/derived flows, each deck's airflow setpoint and their total target are inspectable Outputs. Derived negative values stay visible; they are not clamped into plausible measurements. The nonnegative-arithmetic flag does not establish native sensor quality, calibration, coherent sampling, physical mixing or controller health.

The total-only layout is refused. CCT18 PDF596 limits that selection to its Guideline36 applications, and this generator does not implement the missing mixing/control sequence.

## Authored portable sequence

Temperature P/PI gains are explicitly shared by the separate hot/cold zone loops. Cooling uses zone minus cooling setpoint; heating uses heating setpoint minus zone. A deck's temperature loop is active only on its own side of the declared deadband. Inactive demand is zero, and its loop receives its own setpoint as the measured value so error is zero and the integral is retained. Reactivation resumes that retained integral; no bumpless transfer or vendor adaptive tuning is inferred.

In feedback mode, each selected demand maps from0–100% to its deck's declared minimum/maximum airflow target. Two independent P/PI flow loops use the shared declared flow gains to produce percentage damper commands. Increasing each command is assumed to increase the corresponding deck airflow. Cross-deck pressure/mixing effects are not modeled.

Both deck minima are independent declarations. Neutral conditions can therefore request simultaneous minimum hot/cold flow or position. These are neither ventilation requirements nor energy/code compliance settings. No occupancy, outdoor-air reset, demand-controlled ventilation, exhaust tracking, supplemental heat or discharge-temperature limit is generated.

The explicit Studio guard requires heating setpoint < cooling setpoint and, in feedback mode, nonnegative measured/derived deck flows. Equal/crossed external setpoints or negative flow arithmetic gives both logical damper commands zero. Every P/PI loop then receives its own setpoint as measured input, holding its integral through zero error. Raw flows and separate setpoint-order/flow-arithmetic/control-permission Outputs remain visible. This is an authored simulation policy, not a manufacturer sequence, physical safety interlock or certified failure mode. Bad input quality/nonfinite arithmetic still uses the Engine's transactional scan fault: no partial state/output commit.

Setpoints may be fixed constants or logical Inputs. Runtime ordering is checked, but physical temperature ranges, occupancy/reset policies and a full operating deadband policy are not implemented. Inactive configuration values remain in choice evidence and are listed separately; unused pickup defaults do not become hidden inputs.

## Units, evidence and compatibility

Fahrenheit/Celsius changes convert both absolute setpoints/defaults and reciprocal temperature gains together. Cfm/L/s changes convert cold/hot target bounds, both measured-deck defaults, the total pickup default and reciprocal flow gains. Seconds and percentage limits retain their meanings. The existing derived factor `1cfm = 0.4719474432L/s` applies; this is not a general unit-conversion engine.

The distinct generator profile is `studio-vav-dual-duct/1`, with source/profile/choice/program hashes in preview and generated metadata. Nested `dual_duct` choices require explicit layout and finite typed values. Switching equipment to a single-duct option removes that nested declaration; switching dual-duct control strategies requires a new explicit compatible layout. Choice/source/profile changes retire preview authority. A legacy single-duct profile cannot authorize a dual-duct preview.

The existing `studio-vav-selection/1` profile and all single-duct generation behavior are unchanged. Literal hashes frozen from the preceding published source cover all six existing equipment/control combinations. Existing saved graphs, source bytes and metadata are not migrated or regenerated. Generated choice/parameter numbers retain the existing intentional normalization for newly authored editable graphs, without changing canonical rules or native evidence.

Preview/create, normal simulation, revision save/reopen and JSON/ST/PLCopen/GraphML interchange remain available. Creating requires a guarded exact preview and confirmation before replacing a nonempty editor. Manual edits after creation do not rewrite the original generation evidence. No field interface is opened by the wizard.

## Primary source and verification scope

JCI **Controller Tool Help18.0**, LIT-12011147, PDF594–596 describes dual-duct equipment, hot/cold/total pickup locations and native actuator/commissioning options. Reviewed PDF SHA256: `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`. [Official Help](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0).

That source qualifies equipment/layout choices. It does not establish equivalence between this fixed-gain graph and JCI adaptive tuning or native controller execution. Auto-calibration, balancing overrides, exhaust tracking, supplemental heat, smoke control, total-only control, physical actuator direction/terminals, native CAF creation/compilation/download, package/firmware acceptance and complete G36/Title24 behavior remain outside this profile. Scoped VAV-DD-001 is implemented; broad MF-173d9ae6c9 remains partial.

Independent Engine tests calculate cooling/heating/neutral/saturation outputs for all three pickup layouts, position minima, P/PI trajectories, retained integrals, strict bad-flow/setpoint guards, sensor-quality rollback and both unit conversions. Interchange preserves complete source/profile choices. HTTP tests exercise tokens, actual simulation, save/export/restart reopen and a closed field network. Chromium/WebKit author every layout, independently verify downloaded graphs/digests with Python, simulate/reopen, convert units, reject invalid default totals and refuse stale/legacy-profile authority. These checks do not validate a physical controller or certify a sequence.
