# Direct serial MS/TP hardware surveys and archive jobs

**Connect → Hardware and input survey** now uses an explicitly selected, already-open direct serial MS/TP interface in addition to its existing BACnet/IP and IP-routed paths. It reads actual exposed inputs and existing advertised archive files. It does not compile, download, reassign hardware, modify controller logic or implement BTCVT.

## Operator workflow

Open the intended serial interface through the existing **BACnet MS/TP** connection controls. Choose a currently enumerated automatic-direction RS-485 adapter, the correct baud rate, and an unused client master MAC/device instance. Opening the master already participates in normal token/control traffic; the hardware panel does not open a port or start discovery automatically. See [direct MS/TP setup and physical limits](mstp-transport.md).

The hardware panel selects **Direct serial MS/TP** when that transport is open and displays its port, baud rate, client MAC, device instance and master policy. Select the controller's exact Device object and canonical decimal local MAC from 0 through 254, excluding the client MAC. The router and DNET fields are disabled for this transport. Broadcast, IP, routed, hexadecimal, wildcard and ambiguous leading-zero addresses are rejected. Missing `transport` always retains the existing IPv4 profile; it never infers serial from a numeric address.

Start a bounded survey, inspect typed input readings and quality/error evidence, or cancel. Survey jobs retain the exact selected target and serial connector configuration even before their first read. The session holds the connector lock and verifies application identity, link health, physical adapter address, port, baud, station, instance and master policy before and after requests. Configuration changes stop the operation; a queued job cannot migrate to another interface.

Saved reports retain source configuration in JSON and CSV. Source labels, saved-report options and job progress identify the bus as well as the MAC/Device pair. Reopening a saved report is offline and does not resume reads. After a restart, the interface remains closed until explicitly opened again.

To copy an existing controller archive, use a report with a complete advertised object inventory and select **Read controller archive**. The current serial configuration must exactly match the saved report. A different port, baud rate, station, device instance, max-master or max-info-frames policy requires explicitly reopening the original configuration or running a fresh survey. The UI disables archive reads when it sees a mismatch, and the server independently checks again at admission and under the session lock.

The archive job verifies Device identity, model/name/firmware, inventory count and selected File membership. It reads only one existing advertised stream-access `.moi` archive, with the established size, offset, page, EOF and deadline bounds. It rechecks identity, membership and file metadata afterward. A changed source or interface saves no partial archive. A successful receipt records the exact target, serial configuration, file metadata, byte count, source hash and read-only scope. The exact bytes can be reopened/exported after restart. They remain an opaque existing file copy, not an atomic native backup or a verified editable program.

## API and compatibility

The existing `/api/bacnet/hardware` routes are reused. A direct survey request explicitly adds the transport:

```json
{
  "transport": "direct-mstp",
  "address": "1",
  "device": "device,123",
  "max_objects": 512,
  "max_inputs": 256,
  "timeout_seconds": 45,
  "property_timeout": 1.5
}
```

These values illustrate the schema and are not site settings. The exact serial interface must already be healthy. The endpoint does not infer a connection, scan a trunk or open a router. The hardware-only `HardwareTargetRequest` provides this capability. Shared `DeviceDetailsRequest` retains its IPv4 profile; this change does not widen unrelated event/COV request profiles.

Reports use the existing `bacnet-hardware-survey/1` profile with an optional target `transport` field and captured `connector_config`. New serial evidence requires a validated complete configuration. Pre-existing direct/routed IPv4 reports, finished jobs and archive receipts without a transport field continue to reopen and export exactly. Loading those files does not normalize their stored JSON, rewrite their integrity wrappers or alter source/content hashes. A new import is separately labelled/revalidated supplied evidence, as before.

Read limits, one active hardware job, request pacing, partial/cancelled evidence, private bounded local storage, atomic persistence, job interruption/restart behavior and token/origin protections remain in force. No job automatically resumes field traffic after restart. Unsent confirmed requests are retired from the serial queue on timeout/cancel; see [serial request retirement](mstp-request-retirement.md).

## Validation and remaining limits

The service tests use real kernel pseudoterminals, pyserial, the production BACpypes application, complete legacy MS/TP frames and an authored BACnet peer. The peer supplies independently framed CRCs and upstream service encodings rather than mocked Studio reads. Actual serial traffic exercises ReadPropertyMultiple, rejected-RPM ReadProperty fallback, typed analog/binary/quality fields and multi-page AtomicReadFile. The peer rejects application services outside those read operations. Ordinary MS/TP poll/token control traffic continues as required by an open master.

Tests cover wrong source/Device, own/broadcast addresses, interface changes before and during reads, cancellation/deadline with retained partial values, prevention of late queued requests, changed archive interfaces, interrupted archive copies, report/job/archive restart and exact-source exports. Authored pre-feature IPv4 artifacts are opened over two application restarts and remain byte-identical. Browser tests intercept field calls and verify transport selection, request payloads, serial provenance, saved reopening/export, cancellation, worker failure and config-mismatch refusal.

Physical USB/RS-485 direction control, electrical wiring, driver latency, bus timing, coexistence and controller interoperability remain unverified. PTY success is not physical acceptance or BTL certification. BTCVT host initialization/framing, native JCI compilation/download and live program changes remain separate requirements. No field network, physical serial adapter, Bluetooth module or site credential is used in these tests.
