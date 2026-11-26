# Inline hot-water reheat airflow interlock

The interlock uses the integral differential-pressure sensor and the measured supply airflow in the selected controller. A reliable reading at or above the commissioned threshold permits the existing temperature sequence to regulate heat. Low flow or a sensor fault removes heating permission and sends zero to the automatic proportional valve command. The gate runs in the controller's root sequence on every scan. An operator override has its own BACnet priority.

## Review an application

Use `bms-tool inline-heat-gate --help` to see the three backup file arguments and signal selectors. Select the root diagram, the local pressure input, the flow calculation in CFM, the heating-enable input, its passthrough and the physical percentage valve. Enter the commissioned airflow proof in CFM and a first object instance at or above the reported allocator. The local review returns the source and candidate digests. To save a copy, repeat that review with `--output` and `--review-sha256`. The original files remain available for recovery.

The compiler requires a compatible native ACS 66 / DMCS 65 control sequence. It checks the existing wiring, typed block prototypes, physical valve assignment, scan order and new object identifiers. It inserts local reliability checks, supplies a reliable zero reading on a sensor fault and limits the final valve command independently of the state selector. The existing heating sequence continues to supply the proportional demand when airflow is proven.

## Commission the controller

The native application API provides `POST /api/bacnet/controller/native-application/inline-heat/review` and `POST /api/bacnet/controller/native-application/inline-heat/apply`. The review uses a retained backup from the same station and a fresh physical identity check. Initial commissioning supports an operational M4-CVM03050-0 running firmware 10.0.0.2125 with an active custom application, an integral damper and one proportional heating valve. The station must report low airflow, healthy signals and clear engineering priority slots.

Apply consumes the review once. It captures fresh settings, checks the live allocator and every proposed object, retains a recoverable original and verifies capacity before transferring the application. The controller can briefly suspend control. Readback checks the complete native image, saved settings, operational identity, actual airflow proof and automatic valve output. If readback is incomplete, use the existing receipt readback operation before any further transfer.

Confirm both valve travel and the return to proportional control during site acceptance. Discharge-temperature high limits, valve direction, sensor calibration, acceptance thresholds and stable operation near design minimum airflow require separate commissioning evidence.

The block definitions and the distinction between unconditional and state-specific logic follow the manufacturer's controller help. [Boolean logic](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/15.0/Logic/Boolean) · [Selection logic](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0/Logic/Selection) · [Hybrid activities](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/16.0/Configuring-a-System/Setting-Preferences-Steps/Logic-View-Steps/Configuring-a-Hybrid-Activity)
