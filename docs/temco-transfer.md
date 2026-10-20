# Temco native program transfer

`backend/bms_tool/temco_transfer.py` implements the manufacturer’s private BACnet
program service. This transfers real native Control Basic application bytes into
an exact program slot. It is separate from BACnet priority-array point commands.
It does not transfer applications to Johnson Controls, Honeywell, ALC or Tridium.

The adapter has been tested against an isolated controller emulator using actual
BACpypes3 UDP packets, including an IP router and a virtual field link. No physical
Temco controller, USB MS/TP cable, Bluetooth adapter, building address or Tailscale
connection was used. Physical compatibility and power-cycle persistence remain
unverified. The reference compiler/VM and transfer profile have different limits;
see [native compiler support](temco-native.md).

## Pinned manufacturer evidence

Two independent upstream implementations define this profile:

- [T3000 client, commit ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b](https://github.com/temcocontrols/T3000_Building_Automation_System/tree/ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b).
  `T3000/global_function.cpp` functions `GetProgramData`, `WriteProgramData`,
  `GetPrivateData`, `WritePrivateData`; `T3000/CM5/ud_str.h` packed headers and
  program descriptors; `T3000/BacnetProgramEdit.cpp` native program padding;
  `BacNetDllforVc/Src/ptransfer.c` BACnet service encoder.
- [ESP32 controller firmware, commit 845973a37b91ac5ddac9c465787f2ab3a5037708](https://github.com/temcocontrols/T3-programmable-controller-on-ESP32/tree/845973a37b91ac5ddac9c465787f2ab3a5037708).
  `temco_bacnet/private/ptransfer.c` actual read/write handler;
  `temco_bacnet/private/ud_str.h` 16 slots, 128 VARs, five 400-byte code blocks;
  `temco_bacnet/private/bac_interface.c` device vendor identifier defaults to 148.

The device vendor identifier is **148**. The historical T3000 private-service
namespace is **260**, service **1**. These fields serve different purposes.
Model, firmware revision and BACnet device instance must match explicit caller
values; vendor 148 is required. A user-supplied JCI model cannot bypass the vendor
check. These unauthenticated BACnet fields are identity checks, not cryptographic
device attestation.

The protocol implementation is original Python. Upstream C encoders carry
GPL-2.0-or-later with a linking exception; they remain outside this repository in
`Reference_Sources`. The fixture generator compiles and executes them unchanged,
and records source hashes and emitted protocol data. It also compiles the actual
T3000 C++ header to verify sizes and offsets. No GPL encoder source is bundled
into the application. The header harness supplies unused UI type declarations
for `CString`/Windows `WORD`; neither changes the wire structures.

The firmware checkout has no repository-root license file at the pinned commit.
Its inspected `temco_bacnet/private/ptransfer.c` explicitly carries the same
GPL-2.0-or-later/linking-exception notice. Other firmware files may have different
or unspecified terms; this work does not label the whole firmware repository MIT
or redistribute its implementation. It is retained as protocol reference only.

Run `python scripts/validate_temco_wire.py` to regenerate
`tests/fixtures/temco_private_transfer.json`. The six complete APDU fixtures cover
metadata read, fourth code package read/write, unconfirmed code-read reply,
complex-ACK code-read reply and the firmware’s NULL write reply. Production
BACpypes3 encodings must match those emitted by the real C encoder byte for byte.

## Wire profile

All slot and package indices are zero based. Only slots **0..15** are accepted.
Each request contains one BACnet application OCTET STRING with this packed,
little-endian seven-byte header:

| Offset | Width | Meaning |
| --- | --- | --- |
| 0 | 2 | Request total length, including header |
| 2 | 1 | Command: metadata read 7/write 107, program read 16/write 116 |
| 3 | 1 | Exact slot start |
| 4 | 1 | Exact slot end, equal to start |
| 5 | 2 | Entity size; program high bits encode package as `400 | package << 9` |

Program writes append exactly 400 bytes; packages 0..4 replace the complete
2000-byte slot. Native compiler output retains its exact length before transport
padding. Legitimate trailing zero bytes are never stripped. All five packages
are read for backup, even though the first two native bytes report only base-code
length and exclude other native tables/state.

The target's standard accepted-APDU-size property must be at least 480 bytes,
enough for this profile's complete private block. Smaller devices are refused
before sending a private request.

The descriptor is 37 bytes. Description occupies 0..20, label 21..29, base-code
length 30..31, run state 32, auto/manual 33. Remaining bytes differ between client
and firmware revisions and are preserved from a fresh read. The adapter patches
only run state; firmware updates code-length bookkeeping during code writes.
Read responses may report body length or total length, but command, slot, package,
entity size and exact payload length must all match.

The pinned ESP32 handler answers confirmed requests using **unconfirmed private
transfers**. Its write path returns an application NULL, which has no slot or
package identity. The adapter also accepts standard complex ACKs. An unconfirmed
NULL is only a delivery hint: every mutation requires independent readback.
Read replies must match source address, vendor namespace, service, command, slot
and package. Only one private exchange is pending under the shared connection
lock. BACpypes confirmed transaction state is retired locally after each exchange
so a late library retry cannot repeat a write. This cleanup uses the pinned
BACpypes3 0.0.110 transaction interface.
Request bookkeeping is cleared before returning, and the previous private-message
handler is restored even if BACpypes rejects admission synchronously.

## Planning, backup and replacement

`TemcoTransfer(bacnet, store_or_directory=None, timeout=1.0)` reuses an already
connected production `Bacnet` instance. It does not open another interface or
discover/broadcast to unknown devices. The configured connection supplies IP,
explicit routed BACnet DNET/DADR or an established MS/TP link. Protocol routing
was tested; electrical MS/TP timing and USB/Bluetooth hardware were not.

The public methods are:

```python
adapter.status()
adapter.backups()
adapter.backup(backup_id)
await adapter.inspect(address, device_instance, slot,
                      expected_model=model, expected_firmware=firmware)
await adapter.plan_replace(address, device_instance, slot, control_basic_source,
                           expected_model=model, expected_firmware=firmware,
                           resume=True)
await adapter.plan_restore(backup_id, address, device_instance, slot,
                           expected_model=model, expected_firmware=firmware,
                           resume=True)
await adapter.apply(plan_token)
```

Planning compiles real source with the pinned native compiler. A replacement
must fit the native image profile and physical VAR1..128 limit. Generated
Schedule programs are refused because the transfer adapter does not provision
the required calendar host. Local simulation/export still supports its larger
host profile. The source compiler’s existing expression, table and statement
guards apply before any transfer.

The slot image is read twice and its stable descriptor fields checked before and
after. A changing slot produces no plan. Plans preserve exact address, device
instance, model, firmware, slot, image hash, generation, connection object/config,
original run state and the durable backup ID. They expire after 300 seconds,
are consumed once and are limited to 32 in memory. A reconnect invalidates them.
Generation includes all 2000 image bytes plus descriptor bytes 0..33; runtime-only
descriptor fields are omitted. Running programs whose locals change in the image
may therefore fail coherent snapshot or stale-plan checks. The tool refuses
instead of pretending the backup represents one scan.

Backups contain the complete image and raw descriptor, explicit target,
generation and SHA256 hashes. A further SHA256 seal covers every saved field,
including unknown descriptor bytes and target. Backups and the journal are
written with mode 0600, atomic rename and file/directory fsync under
`temco-program-transfers` in the local data directory. The original backup and
durable operation intent exist before the first stop request. This is a program
slot backup, not a whole-device configuration or point-value backup.

Apply holds `bacnet.lock` through verification, mutation and any recovery. It
rechecks identity, connection, generation and resource budget. It uses the
T3000 small-panel 10,000-byte code budget conservatively: other slots’ declared
base-code sizes plus the replacement’s full native image length. This is the
manufacturer client’s capacity precheck, not a measurement of all device RAM or
flash. Changes to other programs are checked again immediately before transfer.
An original readback has no trustworthy full compiler-file length: its base-code
length excludes tables/state, and trailing zeros can be meaningful. A backup
restore therefore reserves the complete 2000-byte image for this conservative
budget check. A near-capacity device can refuse such a restore plan even when
the original application once fit. The adapter does not guess a shorter length
or bypass this profile limit. Automatic rollback of the immediately replaced
original remains separate from creation of a later explicit restore plan.

The slot is stopped and stop state read back. Before each code write, the whole
image must equal the expected original/partially replaced image. Every 400-byte
write is read back; the entire final image is then checked. Description, label,
manual mode and unknown fresh descriptor bytes are preserved. Replacement
resumes only if the slot was originally running and `resume=True`; otherwise it
stays stopped. Explicit backup restore uses the backup’s recorded run state when
`resume=True`. Restore also creates a backup of the current image before changes.

Stop state and slot description/label/manual mode are checked again before each
chunk, so a concurrently resumed slot is detected before the next program write.

An apply result with `ok=True` means program-image and run-state readback passed.
It does not prove that the controller executed a scan or retained bytes after a
power cycle. `power_cycle_persistence_verified` is always false. No global flash
commit command is issued because it can persist unrelated device changes.

## Failure and recovery limits

Private requests time out within the configured 0.05..2 seconds, with no
automatic write retry. After a mutation error, the operation is journaled as
uncertain and the adapter attempts a bounded original-image restore. Each current
chunk must equal either the original or planned replacement chunk. Unrelated
bytes or changed slot identity/manual mode cause restore refusal, preserving the
external edit and reporting manual recovery required. Successful restore reads
back the full original image and original run state. Journal failures do not
bypass this attempt; the original error and separate journal errors are returned.
Cancellation keeps the connection locked until recovery finishes.
If the recovery child itself is cancelled, the tool records manual recovery
required and exits; it does not spin on a finished task or hold the lock forever.
Repeated cancellation of the outer HTTP task still waits for a pending recovery.
Transfer status uses the connector's current link health, including a stopped
MS/TP worker, instead of treating an allocated application as a healthy link.

Restart never automatically connects or restores a field device. Incomplete
intent/stopped/verified/recovery-required journal entries remain visible in
`status().uncertain`. The user can inspect the device and create an explicit
fresh restore plan using the saved backup. Backups cannot be applied to a
different address, instance, model, firmware or slot.

This firmware has no compare-and-swap generation service, atomic image swap or
authenticated transaction ID for unconfirmed replies. Another writer can race
between a read and write; delayed matching unconfirmed replies cannot be fully
distinguished from fresh ones. Per-chunk/full-image checks detect many conflicts
but cannot eliminate those protocol limits. Keep other commissioning writers
off the slot while replacing it. Stopping a program does not automatically
relinquish outputs, establish safe plant conditions, preserve live scan state or
ensure a physical interpreter runs at the source’s declared scan interval.

The emulator independently models the manufacturer layout and handlers. Tests
cover both response styles, actual source compilation, native VM execution of the
received image, all five chunks, preserved descriptor fields, backup/restore,
stale generation/session/identity/TTL, capacity changes, corruption, partial and
permanent network loss, external edits, journal failure and cancellation. A routed
UDP-to-virtual-field test exercises real BACnet network forwarding. These are
local protocol/compiler tests; they are not physical-controller certification.

Validation: `python -m pytest -q tests/test_temco_transfer.py` passed **36 tests**
locally, including the production HTTP inspect/plan/apply/backup/restore endpoints,
more than 256 repeated private exchanges across invoke-ID wraparound, and both
client and emulator transaction cleanup. The browser UI transfer/backup download/
restore workflow also passed against this same separate-process emulator.
The cancelled-recovery regression runs the real UDP emulator in a subprocess
with an external watchdog, so a frozen asyncio event loop is detected safely.
