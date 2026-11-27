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
62/62 applications on MS-VMA1630-0 and FX-PCV1630-0 firmware 6.2.0.1054 with
an integral damper and either a proportional heat output or an external floating
valve. For a floating valve, review and apply both read the numbered opening and
closing terminals, their order in the device type, the full stroke time and the
command priorities. These values must match the selected controller's capture.
The floating valve and integral damper keep their existing control connections.

A confirmed `inline-monitor/apply` uses the one-use review token and digest,
`monitor_confirmed` and `application_transfer_confirmed`. Transfer temporarily
interrupts control. The seven internal blocks add one connection between the
timer and its downstream witness. A fresh capture and a durable intent precede
the transfer. Readback checks the native graph, identity and saved settings.
Use the receipt for readback after a lost reply. The original capture remains
available for a separately reviewed restoration.

Firmware 6.2 archives may store the root's Block Position List and Continuation
List in a separate trailing record. The encoder preserves each existing drawing
row, inserts the new native objects before the trailing record and extends its
tables by one row per added block or wire. It checks both counts again after
serialization. An inconsistent original drawing stops the new graph edit at
review. Receipts from the previous encoder still reproduce their original bytes.

The new diagnostic receipt also reports whether its downstream clock advanced,
stayed stationary, or could not be confirmed. Six reads check elapsed time,
countdown direction and rollover, signal reliability and controller identity.
The program and saved-setting verification remains available if the clock stalls,
so the operator can still select and restore the original application.

Read the witness across a complete timer cycle without polling the timer.
Compare each internal sensor observation with its corresponding physical
property. Record time, input quality and discrepancies. An installed graph, an
advancing clock, valid sensor bindings and observed heating operation are
separate results. This diagnostic preserves the existing control program and
output wiring. It publishes no supervisory points.

## Reviewing the inline reheat sequence offline

The full reheat program is an engineering draft for matching 6.2 applications.
During commissioning, one version's elapsed clock advanced while its sample
count stayed at zero. A subsequent version received a complete transfer
acknowledgement and the controller restarted with no application. Operators
recovered the original from its verified pre-transfer backup. New observation
downloads and valve activations for this sequence are disabled on the server.
Existing diagnostic receipts can still be reconstructed, read back and used
for recovery.

If a legacy observation receipt is pending after the controller acknowledges
the transfer and reports no application, submit its `receipt_id` and a fresh
`operation_id` to the native application API's `/readback` endpoint. On the
matching model, firmware and route, BMS Tool compares each byte of the
acknowledged image with the controller archive and checks the controller
identity and last restore time again. A full match returns
`image_present_application_not_running`, the number of bytes compared and
the verified original capture and export digests. The existing
`/application-restore/source` and `/application-restore/export` endpoints
can use that capture to verify and save the original locally. Readback leaves the
receipt pending. A missing acknowledgement, a changed identity or an
incomplete match leaves the startup diagnosis unconfirmed.

Open the local draft with `inline-sequence/observe/review`. Supply the target's
retained capture and a verified primitive-library capture from the same model
and firmware, including their snapshot digests. The response contains the
proposed graph, its two point definitions, file size, expanded size, native
record count and root member count. It works with the field interface
disconnected. It returns `can_apply: false` and issues no transfer token.

| Proposed tuning point | Default | Intended control action |
| --- | --- | --- |
| VLV-LOCKOUT-CFM | 30 CFM | Heat requires a complete 30-second window of measured airflow at or above the threshold. |
| MAX-DA-T | 125°F | The valve opening limit drops from 100% to zero over the last 10°F below the ceiling. Heat can resume after a 2°F recovery. |

The draft takes one corroborated airflow sample per elapsed second. Thirty
registers hold the rolling history. Two timers with different periods check
that the clock advances in order, including across a missed minute. Invalid
airflow data or timing restarts airflow proof. An invalid discharge reading
also inhibits heat. The valve can reopen by up to five percentage points per
second. Independent simulation exercises these connections and the discharge
limit.

The 62/62 draft uses a zero-differential Float Equal comparison for each
clock second. It groups additions and Boolean reductions when a matching
native block in the source or library demonstrates that input layout.
Both use the normal release 6.2 primitive types. [Johnson Controls comparison blocks](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/15.0/Logic/Compare)

For a 62/62 inline application with an external floating heating valve, the
offline review reads its two binary output assignments and configured actuator
stroke time. The assignments must agree with the captured terminal label, and
the command must use percent units. The review reports the terminals in their
stored order. The observation draft preserves the valve and damper records,
their travel settings and the existing control connections.

Qualification of the complete reheat application requires a matching off-equipment controller or
firmware simulator. Verify startup, the complete sample window with changing
inputs, input loss, timing gaps, adjustable limits, valve action and recovery
of the original application. Object count and compressed archive size alone
cannot establish that an application will execute. Johnson Controls describes
separate BACnet and controller object limits and recommends simulation above
85% of system capacity. [System Capacity Indicator](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/16.0.1/User-Interface/User-Interface-Concepts/Status-Bar/System-Capacity-Indicator)
