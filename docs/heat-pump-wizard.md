# Portable single-compressor heat-pump wizard

The equipment authoring page creates an editable portable Program for one
reversible compressor and one single-speed fan. It uses existing core blocks,
with inspectable demand, actual logical command and timer-readiness outputs.
The new profile is `studio-single-compressor-heat-pump/1`.

CCT18, LIT-12011147, PDF484–489 describes heat-pump selections and reversing
polarity. PDF1383–1386 distinguishes compressor minimum-on/off, off-before-valve
and valve-to-compressor transition timing. The reviewed PDF SHA256 is
`68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`.
These references qualify the selection criteria. The generated fixed-hysteresis
sequence is authored Studio behavior, not a recovered JCI adaptive PID/MSC module.

## Choices and scope

The operator explicitly selects reversing polarity, initial heating/cooling
valve mode, continuous-occupied/demand-cycling fan and condensate policy. Defaults
for those selectors are blank. A separate logical `airflow_proven` input defaults
false. A permitted fan can run before airflow permission arrives; its command
never supplies its own proof.

Temperature setpoints may be fixed or typed inputs. Demand turns on at the
selected on-difference and off at the selected off-difference; on must exceed off,
and both must be nonnegative. Heating setpoint must remain below cooling
setpoint. Absolute temperatures are bounded to -100..200°C or -148..392°F;
maximum differences are100°C/180°F. Unit conversion changes absolute temperatures
and differences together, preserving all Boolean choices and timings.

Only whole-second declared scan intervals1..60 are generated. Four distinct
positive timers1..3600 seconds must be multiples of that interval. Defaults are
minimum-on120, minimum-off120, off-before-valve6 and valve-settle6 seconds.
This bounded profile does not promise its sequencing under arbitrary overridden
fractional timesteps or after arbitrary graph edits.

## Sequencing and priorities

A fresh engine starts with compressor off, the explicitly selected initial valve
mode and zero timers. The first successful scan represents one declared elapsed
scan interval from boot. It is not an observed wall-clock startup timestamp or a
power-loss/restart guarantee.

The previous committed compressor state drives timing. A requested reversal
first stops the compressor. The valve command remains unchanged until the
compressor has been off for the selected off-before-valve dwell. A valve change
resets valve settling. Compressor start requires a matching requested/valve mode,
full minimum-off and full valve-settle readiness. The valve never changes while
the previous committed compressor command is on.

After off-before-valve dwell is satisfied, rapidly alternating requests can
change the valve command on every declared scan while the compressor is off.
This profile does not rate-limit those off-state valve changes. Each change
resets settling and prevents compressor restart until the mode remains stable.
No physical valve chatter, pressure equalization or mechanical protection is
certified by this simulation.

Ordinary demand loss holds a running compressor until minimum-on expires;
demand-cycling fan remains on during that hold. Occupancy/unit-disable,
energy-holdoff, explicit false airflow permission, crossed setpoints, condensate
inhibit/shutdown and requested mode reversal override minimum-on immediately.
This uniform authored priority differs from CCT18's native distinction between
Heating-Off instant shutdown and Cooling-Off minimum-on behavior.

Condensate choices are none, cooling-only inhibit or unit shutdown. Cooling-only
inhibit allows heating and a permitted continuous fan. Unit shutdown stops the
fan and compressor. While idle or disabled, the reversing valve holds its last
committed mode, including a possibly energized output. It is not forced off.

Bad input quality follows the existing all-or-nothing scan contract: the scan
faults and retains prior outputs, timers and valve/compressor states. A prior
running command can remain on in this simulation. Bad quality is not an immediate
physical safety shutdown claim.

## Source evidence and browser workflow

Catalog, preview and unit conversion bind the exact profile and normalized
choices by SHA256. The preview returns the editable Program, canonical Program
hash, diagnostics, output mapping and explicit false native-compile/controller
write flags. The review JSON export contains the authoritative original server
bytes. The browser rejects stale or mismatched profile/source/choice results,
converts units together, creates a separate project and supports existing local
simulation, revision save/reopen and JSON/ST/PLCopen interchange.

Target family, model, firmware and release fields remain operator declarations.
No terminal is assigned and no field interface opens during authoring. Local
MatIEC/Clang testing is independent portable source execution; it is not JCI CAF
compilation or firmware acceptance.

Two-compressor staging, supplemental heat, economizer, water-side isolation,
native adaptive PID/MSC/PMAC/EWMA, output-priority tracking, physical fan/airflow,
pressure/smoke/freeze protections, setbacks and durable restart remain outside
this first profile. Native CAF compilation/allocation/transfer, live native edits
and complete manufacturer, Guideline36 or Title24 acceptance remain unfinished.
Broad manual feature `MF-724ea67583` therefore remains partial.
