# Read-only field trend acquisition

The Field trends workspace explicitly polls selected BACnet properties through the interface already opened in Connections. It records finite numeric or Boolean observations, their quality and UTC timestamps in a separate durable store. It never opens or reconnects an interface, discovers devices, commands a point, or downloads a controller application.

Start and stop are explicit actions. Restarting the application preserves samples and event evidence but does not restore polling jobs or issue field traffic. Closing the application stops its polling tasks before closing the shared BACnet interface.

## Configure a job

First connect the intended BACnet/IP, routed BACnet/IP or direct MS/TP interface. Then add explicit unicast points in Field trends, choose the interval and start polling. Targets use the same address rules as Connections. No broadcast acquisition is supported.

The local HTTP entry point is `POST /api/field-trends/start`, with the standard `X-Studio-Token` header:

```json
{
  "name": "Local test temperatures",
  "interval_seconds": 10,
  "verify_quality": false,
  "points": [
    {
      "signal": "zone_temperature",
      "address": "127.0.0.1:47808",
      "object_id": "analog-input,1",
      "property_id": "present-value",
      "array_index": null,
      "unit": "degF",
      "value_type": "number"
    }
  ]
}
```

The example address refers to a local test device. Actual addresses come from the selected network and are never inferred from the example. Signal names must be unique within a job. Units are user-supplied labels; the poller does not convert units or verify those labels against a device's units property. Boolean points require an explicit Boolean type and accept a Boolean, binary integer 0/1, or the decoded BACnet `active`/`inactive` state.

Intervals range from 5 through 3600 seconds. Up to eight jobs and 128 total points can run, with at most 32 points in one job. All jobs share one sequential read lane, normally separated by at least 50 ms after each completed read. A cycle waits its configured interval after its point reads finish. Slow reads do not create overlapping polls or a catch-up queue.

Each job captures both the exact connector configuration and the application instance. A changed configuration, replaced/reconnected application or stopped interface faults the job. A result arriving across that change is discarded. Waiting jobs check connection health at most every 250 ms without issuing additional device reads. They do not move to a newly connected bus automatically.

## Values, quality and time

A failed read or invalid/nonfinite value creates a failure event and no sample. The poller does not substitute zero, repeat an old value under a new timestamp, or interpret a timeout as a sensor measurement. Previous samples remain available with their original timestamps.

Without quality verification, a successfully read value has quality `unknown`. A successful transport transaction alone does not establish sensor reliability. With verification enabled, each value read is followed by reads of `reliability`, `status-flags` and `out-of-service` on that object:

| Observed metadata | Recorded quality |
|---|---|
| Recognized no-fault reliability, four clear binary status flags, and false out-of-service | `good` |
| Fault status flag set | `fault` |
| Other reported reliability, out-of-service, or another set status flag | `unreliable` |
| Missing, unsupported, malformed or failed metadata read | `unknown`, with a quality-unavailable event |

This policy conservatively labels an in-alarm flag alone as unreliable. An alarm condition does not necessarily make a physical value inaccurate; this is the poller's conservative classification. No field alarm occurrence or notification is inferred from that flag. The metadata reads are sequential observations, not an atomic device snapshot or physical sensor validation. Some object types do not expose reliability; the [reference Analog Value implementation](https://github.com/bacnet-stack/bacnet-stack/blob/e295d20baba977132b47bc09f61f28e12f2dfac3/src/bacnet/basic/object/av.c) lists it as optional.

Sample `clock` is the host's timezone-aware UTC acquisition time immediately after the value read completes. It is not a controller-supplied timestamp. `recorded_at` is the independent UTC time of durable ingestion, which may follow quality reads. A frozen, backward or invalid acquisition clock faults the job; timestamps are not artificially incremented. A sample-persistence failure also stops polling and reports any available failure evidence.

## History, status and stopping

| Route | Purpose |
|---|---|
| `GET /api/field-trends/status` | Running/stopped job state, captured interface, counters, latest retained values and recent errors |
| `POST /api/field-trends/stop` | Stop one job with `{"id":"poll-..."}` |
| `POST /api/field-trends/retire` | Explicitly delete saved samples and source metadata for an ended source with `{"source":"field/poll-..."}` |
| `GET /api/field-trends/sources` | Retained source identifiers and evidence counts |
| `GET /api/field-trends/samples` | Cursor-paged samples; optional source, signal and inclusive UTC time filters |
| `GET /api/field-trends/events` | Cursor-paged lifecycle, read-failure, quality and job-failure evidence |

The GUI filters sources, pages samples and exports the displayed page to CSV. Definitions are held in memory, with up to 32 retained job summaries. Start events preserve their original configuration as evidence. Sample retention defaults to 100,000 rows; event retention is bounded to 5,000 rows and each job retains at most 50 recent error summaries. The observation store retains at most 256 source markers; exhausting that capacity stops a new recording without erasing existing evidence. Queries return at most 1,000 rows per request.

Stopping cancels an in-flight read, marks an existing source ended and preserves its samples. Stopping immediately after starting is supported even before the worker's first scheduling turn. Audit-storage failure cannot prevent stopping or application shutdown; available errors are reported separately. No native field alarms are created, acknowledged or cleared by ending a trend source.

Retirement is a separate, explicit deletion action. It rejects a source with an active job, an open source and an unknown source. It deletes only an ended source's saved observations and source metadata, freeing that source marker's capacity; polling lifecycle/failure events and operation-audit evidence remain. No automatic retirement occurs. Retirement also works after restart when the ended source's in-memory job no longer exists. Intent evidence is written before deletion; an intent-storage failure preserves the observations. A completion-evidence failure returns `retired: true` with an `audit_error` explaining that deletion committed, rather than implying it was rolled back.

Field observations live under `.state/field/observability.sqlite3`; simulation observations keep their separate store. Each database persists its source-kind marker and rejects reopening under a different kind. Legacy unmarked databases containing observation evidence migrate as simulation. A genuinely empty legacy store can be initialized for field use once. This prevents constructor settings from relabeling existing simulation evidence as field measurements.

## Implementation and verification

[field_trends.py](../backend/bms_tool/field_trends.py) exports `FieldTrendPoint`, `FieldTrendStart` and `FieldTrends(bacnet, directory, audit_store=None)`. The async service methods are `start(...)`, `stop(id)`, `retire_source(source)` and `close()`. `status()`, `events(...)`, and the separate `.store.trends(...)`/`.store.list_sources()` expose evidence. Constructor-only timing/clock injection supports deterministic failure testing and is not exposed in the start API.

The focused backend tests are:

```sh
.venv/bin/pytest -q tests/test_field_trends.py
```

The implementation includes 38 focused field-service tests. Tests include actual BACpypes3 UDP reads of numeric and binary points on loopback, verified quality, restart persistence, unknown/malformed quality, partial failures, nonfinite rejection, configuration changes, application replacement, clock faults, read timeout/cancellation, bounded jobs, read serialization, immediate stop, audit/storage failures and source-kind migration. Retirement tests cover active/open/unknown-source refusal, explicit deletion, restart and capacity recovery, and both intent/completion evidence failures. Loopback reads use the real BACnet application and sockets; injected peers exercise specific fault cases.

Physical equipment and E2/F2 were not contacted. This feature is host polling, not BACnet COV subscription or retrieval of a controller's Trend Log objects. It does not implement native alarm acquisition, external notification delivery, proprietary application programming or Title 24 sequence certification. Hardware and site-specific interoperability remain separate tests.

Explicitly recorded COV numeric receipts also share this field store through the
[separate COV recording service](bacnet-cov.md#opt-in-durable-receipts-and-field-trends).
They keep acquisition kind `bacnet-cov`, local receipt time, an unknown controller
clock and conservative quality; they do not create or join a polling job. Their
raw notification/lifecycle evidence is reopened in Connect. Source deletion also
removes the selected ended source's COV receipts and provenance.
