# Portable VAV runtime setpoint guard

`VAV-SETPOINT-GUARD-001` adds an explicit option to the existing equipment wizard
for cooling-only, inline-reheat without a fan, and parallel-fan-reheat applications.
Open **Program → Graph editor → Equipment wizard**, select a single-duct family,
then expand **Setpoint ranges and deadband** in Parameters. Existing programs and
the default wizard remain unchanged until the operator enables this option.

## Declared behavior

The operator declares inclusive minimum/maximum absolute setpoints and, for
reheat, a minimum heating/cooling gap. Initial Fahrenheit choices are 50–90°F and
5 delta-degF. Both nominal setpoints must satisfy that declaration before preview
or unit conversion. Enabling the option does not silently change the original
68°F/72°F nominal pair: change it explicitly, for example to 68°F/73°F.

Ordinary editable graph blocks check raw runtime setpoints against bounded
copies. Reheat also checks their order and gap, with a documented 1e-9 delta-degF
equivalent binary64 gap tolerance. Cooling-only checks only its cooling range.
Temperature demand is permitted above the cooling setpoint or below the heating
setpoint respectively; the thermal modes cannot overlap. Inside the band or with
an invalid finite configuration, their commands are zero and temperature PI
integrals hold. The minimum damper-position or airflow **request** remains active;
the airflow PI continues to regulate that request. This does not measure or
guarantee ventilation or physical actuator position.

Parallel fan control receives the gated heating demand, retaining the existing
authored nonnegative on/off hysteresis. Invalid configuration supplies zero demand
and resets that fan request. No fan-proof, discharge-temperature, freeze, electric
heat or motor interlock is added.

Three diagnostics are logical portable outputs: configuration accepted, cooling
mode permitted, and, for reheat families, heating mode permitted. They describe
the last completed scan. Existing whole-scan bad-quality/fault handling retains
the preceding committed outputs, state **and diagnostics**. They are not native
reliability values or a physical failure response.

Absolute bounds and setpoints convert between Fahrenheit/Celsius; the gap is a
temperature difference. Existing inverse temperature gains and airflow conversion
continue to apply. Preview binds the exact choices, guard rules, source reference
and program profile. Creating a project, revisions, JSON import/export and local
simulation use the existing editor workflows. Saved graphs remain directly
editable; editing them can change the generated policy, so metadata records
authoring provenance rather than certifying arbitrary later changes.

## Reference and limits

The [CEC 2025 standards](https://www.energy.ca.gov/sites/default/files/2025-07/CEC-400-2025-010-F_0.pdf),
CEC-400-2025-010-F, PDF pages 235–236, §120.2(b)1–3, document thermostatic adjustment
capability, a dual-comfort deadband capability and exceptions. They motivate the
declared 5°F default; they do not make every project require this particular
configuration. PDF SHA256:
`83c43852d3b72e89386fabdb7562b3dd077df90a7bec0b4c332fdae833f8afaa`.

Occupancy/standby/setback, measured ventilation, heating safety, full Guideline 36
and project-specific Title 24 conformance remain separate engineering work.
Dual-duct and fan-coil applications do not inherit this single-duct option.
Native JCI allocation, CAF generation, controller compilation/transfer and
physical commissioning are not established by this portable graph feature.

## Qualification

Independent trajectories cover P/PI thermal changes, range and gap boundaries,
extreme finite portable inputs, invalid-configuration integral retention,
transactional bad-quality rollback, unit conversion and JSON round trips. A
54-case fixture generated from reviewed main preserves absent-guard choices,
program and JSON export hashes, including excluded families.

Actual MatIEC/host-C trajectories cover all three families, both units and both
damper strategies. This runtime uses IEEE float32 and the existing bounded
numeric comparison profile; the portable interpreter uses binary64. Successful
tested trajectories do not imply equality for every value near a representational
boundary or acceptance by JCI firmware. Browser checks exercise both entry paths,
compact navigation, source/profile refusals, revisions, export, simulation and
late-response retirement. All field and Bluetooth acceptance remains separate.
