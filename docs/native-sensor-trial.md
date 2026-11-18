# Legacy NetSensor compatibility trials

Use **Points & I/O → Configure native inputs → Test sensor definition
compatibility**. This operation uses BMS Studio's native BACnet client and
application compiler. It does not launch CCT/PCT or use JCT/SCT.

An NS8000 integration and a legacy NetSensor are different native device
definitions. JCI's [implementation notes](https://docs.johnsoncontrols.com/bas/r/Johnson-Controls/en-US/NS8000-Series-Network-Sensors-Application-Note/Implementation-notes)
require NetSensor for NS7000 and original NS8000 1.x firmware. A failed address
communication test alone does not establish that a sensor is absent or defective.
The actual installed model, firmware, wiring and address remain independent
evidence.

## Scope

Profile `native-netsensor-compatibility-trial/1` admits the tagged MOI ACS/DMCS
66/65 family with a captured explicit NS8000 DeviceInfo definition on SA port
307,2. It temporarily disables one offline NS8000 integration and adds a
bounded page of legacy Net Sensor Device 627 / Net Sensor AI 628 temperature
readers at addresses 199–206. Each reader is unconnected to the control graph.
No setpoint/occupancy output, firmware, boot, supervisor point, historian,
trend, alarm extension or operating-point command is created or changed.

Existing BACnet point identifiers, names, native references and every program
record remain intact. The only existing configuration edit is the selected
integration's Enabled property 673. Native saved settings are merged before
compilation. Original parameter Files 11/12 remain retained; only application
File 3 is transferred. Backup and readback enter/end backup mode. Apply and
Restore enter restore mode and can interrupt controller operation.

This is a compatibility trial, not a permanent sensor-family migration. A
positive trial does not automatically redirect existing control inputs or NAE
points. Native identifier high-water accounting may advance when the temporary
objects are created; removed identifiers are not forced back into the allocator.

## Workflow

1. Verify/open the selected controller. Configure native transfer credentials
   through the existing local credential workflow.
2. **Capture sensor configuration**, or open a retained capture for local
   inspection. Read the controller's actual next available identifier.
3. Select the captured NS8000, addresses and temperature units. **Review local
   trial copy → Save trial application copy** is useful offline and creates
   no controller request or field review.
4. **Review controller sensor trial** checks the original route/interface,
   complete identity/firmware, offline original sensor, enable/address and
   independently attributable absence of the proposed trial identities.
5. Review the target and temporary changes, then confirm the trial and native
   application transfer. **Apply reviewed sensor change** consumes one review.
6. Application acceptance requires operational identity, the complete outgoing
   native image, saved-setting preservation and independent membership/enable
   readback. It does not establish a sensor response.
7. **Read trial sensor values** obtains actual address, enable/offline state,
   point identity/reference/name, units, temperature, reliability, status flags
   and out-of-service state. Only an online, enabled, reliable, unforced input
   is labelled live. Allow initial discovery/polling to settle; a physical
   sensor identity and room-temperature comparison remain separate.
8. **Review restoring original definition → Apply reviewed sensor change**
   removes only the exact trial objects and restores the original enable
   representation. New references to those objects, foreign identities or
   changes to original configuration block restoration instead of overwriting
   other engineering work. Complete image/settings and membership readback
   verify restoration.

## Ownership and recovery

Reviews are source-bound, one-use and expire after 15 minutes. Source, edit,
target, interface and credential changes retire authority. Apply captures a fresh
original, rejects changed application/static-directory/configuration evidence,
checks File 3 capacity and retains both the original and exact outgoing payload
before the first dispatch. The shared native operation owner serializes work
and the existing durable journal retains intent and each individual dispatch.
Files are sent once. There is no background retry or automatic rollback.

A rejection before dispatch remains `not_sent`. Once any restore request is
dispatched, an incomplete result remains `unknown` and blocks another native
change. Reopen the retained receipt after a lost HTTP response or process
restart. **Read back sensor transfer** sends no application download; it
independently recognizes either the reviewed image or the exact original
operational image/settings. Neither a reply nor an unchanged Device instance
alone releases uncertainty. An unrecognized image or a controller that has not
recovered operation remains unresolved for explicit recovery.

Restoration is another reviewed transfer, not an automatic inverse write. Keep
the original backup and all transfer receipts until it is verified. Original
failed results are immutable; later readbacks append evidence.

## Validation

Authored native records and isolated UDP peers exercise one/eight addresses,
gzip/plain files, retained opaque records, saved values, exact restoration,
address/identifier collisions, unknown format, stale review/identity/allocator/
credentials, actual source pinning, unreliable/forced values, lost ACKs,
restart readback without replay, cancelled reviews and authenticated local
copy export. Real-API browser tests cover both controller and CAF entry,
draft/navigation retention, review invalidation, local copy hashes, trial
observations, restoration, keyboard controls and a lost Apply response.
Physical qualification is recorded separately from these software tests.

Relevant manufacturer guidance:

- [NS8000 implementation notes](https://docs.johnsoncontrols.com/bas/r/Johnson-Controls/en-US/NS8000-Series-Network-Sensors-Application-Note/Implementation-notes)
- [Network sensor addressing](https://docs.johnsoncontrols.com/bas/r/Johnson-Controls/en-US/NS8000-Series-Network-Sensors-Installation-Guide/J/Network-sensor-addressing)
- [SA-bus status and firmware provisioning](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Provisioning-with-Tools/10.1/Using-the-Advanced-Transfer-Option-in-CCT/SA-Bus-Firmware/SA-Bus-Status-Screen)

These references describe compatibility and diagnostics. Native record/transfer
qualification remains independent of vendor-tool screenshots or reflection APIs.
