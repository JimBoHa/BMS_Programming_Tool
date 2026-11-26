# Observing legacy VAV input and timer behavior

When a template uses elapsed time or an input's service status, qualify the
behavior on the controller before connecting that template to a heating output.
A timer can report its current remaining time in response to a read. Read a
separate downstream block to establish that changes propagate through the
controller application under its own power. Johnson Controls describes the
timer update interval and the event-driven behavior of Last Value in its
[Timer](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/15.0/Logic/Timing/Timer)
and [Last Value](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/15.0/Logic/Timing/Last-Value-Float)
references.

In the native application API, capture the selected station and pass the capture
ID and its `snapshot_evidence_sha256` to `inline-monitor/review`, together with the
same route, Device, operation ID and first free instance. The review checks
the manufacturer, exact model and firmware, source graph, saved settings,
recoverable original application, live I/O quality, command priorities and
the availability of each proposed object. The current profile covers native
62/62 applications on MS-VMA1630-0 and FX-PCV1630-0 firmware 6.2.0.1054 with a
physical proportional heat output and integral damper.

A confirmed `inline-monitor/apply` uses the one-use review token and digest,
`monitor_confirmed` and `application_transfer_confirmed`. Transfer temporarily
interrupts control. The seven internal blocks add one connection between the
timer and its downstream witness. A fresh capture and a durable intent precede
the transfer. Readback checks the native graph, identity and saved settings.
Use the receipt for readback after a lost reply. The original capture remains
available for a separately reviewed restoration.

Read the witness across a complete timer cycle without polling the timer.
Compare each internal sensor observation with its corresponding physical
property. Record time, input quality and discrepancies. An installed graph, an
advancing clock, valid sensor bindings and observed heating operation are
separate results. This diagnostic preserves the existing control program and
output wiring. It publishes no supervisory points.

## Qualifying the inline reheat sequence

The `inline-sequence/observe/review` route accepts a verified station capture
and a verified primitive-source capture from the same model and firmware. Both
references include their snapshot digests. The compiler copies type-checked
math, timer and selection primitives, retaining the target's sensor terminals,
output action, flow calibration and original heating demand. Its observation
program adds two BACnet analog values. The existing heat and damper connections
remain in control at this stage.

| Tuning point | Default | Behavior |
| --- | --- | --- |
| VLV-LOCKOUT-CFM | 30 CFM | Enables heat at or above this 30-second average when the inputs and sampling clock are healthy. |
| MAX-DA-T | 125°F | Limits the commanded opening over the last 10°F below the ceiling. Reaching the ceiling closes the valve. Reopening requires 2°F of recovery. |

The sequence checks the measured pickup, calculated airflow and service flags,
uses the lower corroborated airflow, and collects 30 elapsed one-second samples.
Each second on the native timer addresses a separate airflow register. Further
logic executions in the same second address the same register. Timers on the
registers verify that each sample is recent, and complementary clock phases
detect a stalled timer. Loss of input quality inhibits heat. The final valve
can advance by one opening increment during each elapsed second.
It checks the higher of the two discharge readings. Reopening is limited to five
percentage points per second. A sensor, timing or tuning fault inhibits heating.
The field release profile requires a proportional valve and integral damper.
Each observation installation also checks object allocation and file capacity.
On a slow trunk, the allocation check can take several minutes. The review
includes time to repeat the measured walk and capture a fresh backup, subject
to a 45-minute limit. A missing reply gets one further read of that same object.
The controller must explicitly identify every proposed object as unused.
Johnson Controls publishes this controller family's object budgets in its
[System Capacity Indicator reference](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/16.0.1/User-Interface/User-Interface-Concepts/Status-Bar/System-Capacity-Indicator).

Review and apply the observation program before proposing activation. Use its
verified receipt ID and the exact current capture in
`inline-sequence/activate/review`. The review measures the downstream sampling
clock, window count, airflow mean, supply-air threshold, discharge limit and
proposed valve command on the running station. Activation requires a completed
window and an output consistent with the observed airflow and temperature.
`inline-sequence/activate/apply` repeats the checks, retains the fresh original
and changes the existing heating-enable and valve-source connections together.
Verify the returned receipt and compare automatic output, measured airflow,
discharge temperature and any independent position feedback during commissioning.
