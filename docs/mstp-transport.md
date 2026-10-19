# Direct BACnet MS/TP transport

The direct serial adapter carries real BACnet point services over a fixed-address, legacy MS/TP master. An actual BACpypes3 application performs unicast Who-Is/I-Am discovery and ReadProperty through the serial link. Local tests exercise the complete HTTP-to-BACnet-to-pyserial path using kernel pseudoterminals and an independent fixed-wire peer.

This is an experimental software transport. Physical RS-485, USB adapters, bus timing and controller interoperability have not been tested. It is not a Johnson Controls BTCVT driver or an application compiler/downloader.

## Setup and connection behavior

Use an RS-485 adapter that provides automatic transmit-direction control and suppresses local transmit echo. The current implementation does not control direction through software RTS, support adapters that require that control, or compensate for an echoing interface. USB adapter and operating-system latency must be measured on the intended hardware. Python thread scheduling is not a real-time guarantee.

Select a currently enumerated serial device from `GET /api/ports`. The connector rejects arbitrary file paths. Install the adapter's operating-system driver if needed, and use the bus's configured baud rate. The allowed software settings are:

| Parameter | Supported setting |
|---|---|
| UART framing | Eight data bits, no parity, one stop bit; software and hardware handshaking disabled |
| Baud rate | 9600, 19200, 38400, 57600, 76800 or 115200 |
| Client MAC | An unused, explicitly configured master address from 0 through 127 |
| Max master | Client MAC through 127; configure consistently with the intended bus |
| Max info frames | 1 through 255; default 1 |
| BACnet device instance | 0 through 4194302; choose an unused instance |
| Point-service target | A remote one-octet local MAC from 0 through 254 |

Connecting activates a transmitting MS/TP master. It participates in token handling and sends master-poll control frames as needed, even before a discovery request. It does not issue automatic Who-Is discovery. The public point-service connector requires a unicast target and rejects an IP address, routed address, broadcast address or its own MAC.

`connected: true` means the selected serial worker is running without a recorded fault. It does not establish that a controller has answered. A successful directed discovery or property read supplies that separate evidence.

## Local HTTP API

All modifying HTTP requests require the local session token from `GET /api/session`, supplied as `X-Studio-Token`. Existing Host and Origin protections apply.

Open the selected interface with `POST /api/bacnet/connect-mstp`:

```json
{
  "port": "/dev/cu.usbserial-EXAMPLE",
  "mac": 126,
  "instance": 4190001,
  "baudrate": 38400,
  "max_master": 127,
  "max_info_frames": 1
}
```

The example port is a placeholder; the actual path must appear in `/api/ports`. The MAC and instance must be chosen for the actual network. Opening a port is an explicit user action, not part of application startup.

The existing point-service routes then use the serial interface:

| Route | Example request or response purpose |
|---|---|
| `GET /api/bacnet/status` | Connection configuration, command recovery entries and `serial_link` status |
| `POST /api/bacnet/discover` | `{"address":"1","low":4190012,"high":4190012}` |
| `POST /api/bacnet/read` | `{"address":"1","object_id":"analog-input,1","property_id":"present-value"}` |
| `POST /api/bacnet/objects` | Bounded, sequential object-list reads for an explicit device |
| `POST /api/bacnet/write-plan` | Existing point-command preflight and unused-priority checks |
| `POST /api/bacnet/write-apply` | Apply a prepared point-command plan |
| `POST /api/bacnet/release` | Explicitly relinquish an owned point command |

The shared command journal binds recovery to the exact saved interface configuration. Pending owned commands prevent changing the bus, MAC, baud rate or transport. Reopening the same stopped interface is permitted for recovery. Invalid settings are checked before closing an existing working interface. The serial integration tests cover this configuration/ownership guard; they do not transmit a field command or independently validate a serial WriteProperty/readback/relinquish exchange.

A fatal serial error or duplicate-source-MAC frame stops transmission. Status reports `connected: false` and the fault. Point-service requests then require reconnection instead of continuing against a dead worker. A duplicate-source fault can indicate a conflicting station or local adapter echo; correct that condition before reconnecting.

## Python interfaces

The normal connector is `Bacnet.connect_mstp(...)` in [connections.py](../backend/bms_tool/connections.py). It shares the BACnet/IP connector's point services, audit records and ownership recovery policies.

For an application-level integration, [mstp_bacnet.py](../backend/bms_tool/mstp_bacnet.py) exposes:

```python
from bms_tool.mstp_bacnet import create_mstp_application

# Inside an async function; port and mac come from the selected interface.
app = await create_mstp_application(
    port,
    mac,
    instance=4190001,
    baudrate=38400,
    max_master=127,
    max_info_frames=1,
)
try:
    value = await app.read_property("1", "analog-input,1", "present-value")
    status = app.mstp_link.status()
finally:
    app.close()
```

The factory creates a real BACpypes3 `Application`, binds its network-service access point to a one-octet local address and advertises a 480-octet accepted APDU with no application segmentation. The receive pump processes at most 32 packets per event-loop turn. It exposes malformed-packet counters and serial-worker failures. The factory does not open a BACnet/IP socket.

The lower-level [mstp.py](../backend/bms_tool/mstp.py) interfaces are:

- `Frame` and `FrameDecoder`: validate, encode and incrementally receive legacy frames.
- `MstpMaster`: deterministic token state driven by explicitly supplied monotonic times; it does not open a serial device.
- `SerialMstpLink`: `start()`, `send_npdu(...)`, `send_reply(...)`, `receive(timeout)`, `status()` and `close()`. Construction does not open a device. `receive` returns a `ReceivedNPDU` or `None` and permits a bounded timeout of up to 60 seconds.

The raw NPDU interface leaves BACnet APDU transaction and invoke-ID handling to its caller. The BACpypes3 integration supplies those application services. A response outside the immediate-reply window waits for a subsequent token.

## Implemented protocol scope

The receiver handles the two-octet preamble, big-endian payload length, Annex G header CRC-8, and little-endian data CRC-16. Legacy payloads are limited to 501 octets. It accepts repeated first-preamble octets and padding, rejects corrupt or malformed frames, and skips declared unsupported/oversized payloads without interpreting embedded preambles as tokens.

The master handles token receipt/use/pass, periodic master discovery, successor discovery, one token retry, failed-successor search, silent-bus token generation in its address slot, sole-master operation, reply timeout, immediate replies and Reply Postponed. Incoming Test Request frames receive a Test Response. Application packets wait for a token except for a response in an open immediate-reply window. If other traffic interrupts turnaround, an unsent application packet returns to the bounded queue.

Current timing policy uses a 500 ms loss-of-token interval, 10 ms address slots, a 35 ms usage timeout, 255 ms reply timeout, 245 ms reply-delay threshold, 95 ms receive-frame abort and a minimum 40-bit turnaround. UART wire duration is accounted for separately from the OS write returning. The worker uses a 1 ms wait between iterations and bounded writes. It avoids an unbounded `tcdrain`/`Serial.flush` call, which blocked in the macOS pseudoterminal investigation. These software choices still require physical timing verification.

Transmit application capacity is 64 packets including a pending application frame. Receive queues are bounded at 256 packets, with overrun counters. The decoder buffers at most one legacy frame; unsupported lengths use a counter rather than allocating the declared payload. Duplicate-source-MAC detection suspends transmission.

Unsupported protocol scope includes extended/COBS frames, vendor-specific frame types, automatic baud detection, automatic MAC selection, a direct serial BACnet router, BTCVT host initialization/framing, and proprietary controller application transfer.

## Verification and remaining gaps

Run the focused checks with:

```sh
.venv/bin/pytest -q tests/test_mstp.py tests/test_mstp_bacnet.py tests/test_mstp_connection.py
```

The recorded local run passed **65 tests** in 4.13 seconds on macOS. One existing upstream Starlette TestClient deprecation warning remained. POSIX pseudoterminal cases are skipped on platforms without that facility; Windows serial behavior has not been verified.

The checks include public Annex G vectors; fixed C-verified wire frames; fragmentation, corruption, timeouts and bounded hostile input; token timing/state transitions; direct response and deferred response; queue pressure; duplicate-MAC faults; two simulated masters; actual BACpypes3 discovery/read through pyserial; production HTTP endpoints; command-journal restart guards; and recovery after a dead worker. Only serial-port enumeration is substituted to permit the test-owned pseudoterminal. The positive service tests do not replace the BACnet application or serial implementation with mocks.

Six frozen request/response frames were separately reproduced by compiling unchanged upstream BACnet-stack C sources and calling `MSTP_Create_Frame`. That comparison independently verifies those encodings, not every master-state transition or physical timing requirement. Details and licenses are recorded in [MS/TP provenance](mstp-provenance.md).

No physical serial port, BTCVT, building controller, E2/F2 NAE, Tailscale peer or site credential was accessed for this work. The implementation is not BTL-certified. A bench test must still establish adapter direction/echo behavior, actual inter-octet gaps and turnaround, coexistence with existing masters, controller responses, recovery after cable/device loss, and any required command/readback/relinquish behavior.

Standard BACnet object/property services do not create a controller program, compile a CAF, add a physical input definition, or modify running proprietary logic. JCI FX/VMA native compilation, BTCVT support, other vendor application loaders and six verified Title 24 CAFs remain separate requirements. Completing this transport does not establish completion of a universal programming tool.
