# Read-only airflow and damper observation

The optional POSIX command-line observer records a selected controller, explicitly chosen reference boxes and actual air-handler startup evidence. It uses `ControllerWorkspace.properties` in the BMS Tool. It exposes no write, override, tuning, application transfer, schedule or NAE trend/alarm operations. It adds no web navigation destination.

Run from an installed environment, or set `PYTHONPATH=backend` in a source checkout:

```sh
python -m bms_tool.airflow_observer --config /private/path/observation.json --state /private/path/job --sample-only
python -m bms_tool.airflow_observer --config /private/path/observation.json --state /private/path/job
```

Keep the configuration and all output outside the repository. They contain controller identities, paths and network addresses. The observer requires no account password. Use a dedicated BACnet local port and Device instance, and avoid sharing the web application's connection. Check site network policy before choosing them. `--sample-only` performs one live read of each configured group and writes a separate `preflight` report. It does not wait for startup and must not be described as a completed observation.

## Private configuration

The JSON configuration requires:

- `timezone`: IANA timezone name for report times.
- `collection_from`, `startup_deadline`, `hard_stop`: explicit ISO 8601 timestamps with UTC offsets. The total collection window cannot exceed two days. No scheduled field connection is opened before collection or after the allowed window. An already-running property read can finish after the boundary, bounded by the 25-second group deadline.
- `minimum_monitor_seconds`: required elapsed time after confirmed startup, between 600 and 86,400 seconds.
- `minimum_qualified_seconds`: required actual target observation, defaulting to `minimum_monitor_seconds`. A five-hour run uses 18,000. Allow extra elapsed time for startup confirmation and occasional missing reads.
- `checkpoint_seconds`: between 60 and 3,600, typically 600.
- `startup_confirmations`: 1–10 consecutive qualified startup reads, typically 2.
- `startup_fans`: explicit aliases for actual binary fan proof. Any healthy value of 1 qualifies; enable commands do not establish startup.
- `startup_pressure`: explicit numeric duct-static alias, with values in inches water gauge. `startup_min_static` must be positive and less than 10. Select a meaningful threshold for the site.
- `target_name`, `reference_names`: alias prefixes. Each box should have `.damper`, `.flow` and `.flow_sp` aliases for command/estimated position in percent and flow in CFM.
- `interface`: the existing `Bacnet.connect` options, including `local_address`, `instance`, and the required router/network options for the chosen interface.
- `groups`: explicit read groups, described below. There must be at most 256 unique point aliases.
- `output_directory`: private report directory, outside the repository.
- `limits`: an array of evidence limitations, including source cache age, feedback type, sensor status and whether airflow calibration and branch pressure equivalence are verified.
- Optional `scheduled_start_note`: the checked schedule and its evidence, for context only. Actual fan proof and pressure gate observation.

Each group has a distinct `name`, `source` description, `interval_seconds` (10–3,600), `target`, `expected_device_name`, and `points`. The target uses the existing controller reader's `address`, `device`, `router` and `dnet` fields as applicable. Each point has `alias`, `object` (BACnet Object Identifier), and `expected_name` (exact published object name, which may include the NAE path). Both compact numeric and canonical object identifiers are accepted. Verify actual identities before creating the configuration.

Read all startup aliases in one group every 60 seconds or faster. Target damper, measured flow and requested flow should be in one group every 30 seconds. References can use 60-second groups; occupancy, operating mode, zone/discharge temperature, fan state and limits can use 600-second groups. Every read verifies Device identity/name and point identity/name. Groups read in batches of at most 16 points with an overall 25-second deadline; unavailable values remain explicit. The groups run sequentially to limit load; timeouts may delay subsequent samples.

## Persistent execution and recovery

The CLI stays in the foreground and takes a POSIX advisory lock for its job directory. Use a managed process such as a per-user macOS LaunchAgent if it must continue after a terminal or chat closes. The operating machine must remain powered, awake and connected. An idle-sleep assertion does not protect against shutdown or loss of power.

Pin the reviewed module and its dependencies for the job; do not point an unattended job at a checkout another session may change. A process manager may restart a failed process with the same configuration. The retained configuration hash rejects changes to an existing job. Interrupted final JSON appends are preserved separately before resuming. Completed or bounded-incomplete jobs exit without opening another field connection. Startup must be detected before the configured deadline; a missed window is reported as incomplete.

## Coverage and engineering interpretation

The observation clock starts after consecutive healthy fan-proof and pressure reads. Actual coverage additionally requires healthy target damper, airflow and airflow-request samples while recent fan/pressure evidence confirms operation. Coverage counts consecutive samples conservatively, at most 30 seconds per pair, and never fills long gaps, known-invalid samples or AHU-off intervals. The job finishes only after both configured elapsed and qualified durations, or ends incomplete at the hard stop.

The report keeps read failures, reliability, out-of-service and override flags. Faulted or out-of-service values do not qualify. A reported override flag on a software value does not identify who set it or establish that it was manually overridden. Damper override flags exclude automatic-control screening. Published command/estimated position is not independent blade feedback. NAE mapper reads may have an unexposed underlying field-cache age.

Ten-minute checkpoints screen the preceding hour, excluding the first 20 minutes after startup. A possible-hunting flag requires at least 40 damper samples, a requested-flow range no greater than the larger of 10 CFM or 10% of median request, at least four damper reversals of five percentage points, a damper range of at least 15 points, and at least three airflow-error crossings outside the larger of 10 CFM or 10% of request. These are transparent screening heuristics, not vendor acceptance criteria or an instruction to tune PID gains. Changing demand can prevent a flag. A missing flag does not prove stable tuning; 30-second sampling cannot resolve faster oscillations.

Compare similar requested airflow, occupancy and fan/heating state. The report shows median damper commands in common 20-CFM request bands (at least ten samples per box). Matching request bands do not establish equal duct pressure. Calibration error, unavailable room sensors, supply pressure changes and mechanical issues must be considered before tuning.

## Output

`report.html` contains quality-qualified damper, flow, request and static-pressure plots, comparison metrics, request-band comparisons and checkpoint results. `samples.csv` and the private `samples.jsonl` retain values and quality evidence. `checkins.jsonl`, `analysis.json` and the private `state.json` distinguish scheduled, waiting, monitoring, complete, retry-needed and incomplete runs. No physical response, tuning acceptance or completed monitoring is claimed by authored tests or preflight reads.
