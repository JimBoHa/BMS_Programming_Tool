# Observe a verified batch

`scripts/observe_controller_batch.py PRIVATE_DIRECTORY` reads individually verified
controllers, their keepers, each controller's own discovered physical I/O, and a
supervisory engine. It sends only ReadPropertyMultiple requests. It does not change
programs, instances, point values, backup/restore state, or engine configuration.

Create `batch-settings.json` in a protected local directory outside Git. Supply:

- `local_address` (a separate local BACnet socket) and `local_device`.
- `router_target`: the engine's DeviceDetailsRequest route, including `device`.
- `targets`: one entry per approved physical station, each containing `controller`,
  `new_instance`, the new `target` route, `keeper` route, `keeper_name`, and the full
  discovered `io_objects` list. No model or expansion-module count is assumed.
  Its length must match the verified I/O count; verified zero-I/O devices are valid.
- `verification_file` and `preservation_file` in each target entry: relative paths
  to that controller's verified-change and preservation-proof JSON. Unverified,
  mismatched or unexplained settings changes prevent observation from starting.

Defaults are 3,600 seconds, five-minute checkpoints, one-minute polling and seven
controllers per poll. The configured rotation must cover all targets within a
checkpoint interval. Only explicitly listed targets are read; omit held devices.
Optional timing keys are `duration_seconds`, `checkin_seconds`, `poll_seconds` and
`controllers_per_poll`; results always record the actual requested duration.

The clock starts after a healthy full baseline. Native ObjectIdentifier values
are checked as `[8, instance]`, independently of the requested object's echo.
Faults, alarms, overrides, out-of-service values, stale/missing samples or an engine
error prevent a clean pass. A transient failure stays recorded after recovery.

Output is private JSON/JSONL. An exclusive marker prevents accidental restart or
overwriting a prior watch. An interrupted or failed run exits nonzero. Retain its
evidence and investigate before deliberately preparing another observation.
Additional vendor supervisory/alarm checks remain separate, private, read-only
reviews; a healthy BACnet sample is not a complete engine alarm-history review.
