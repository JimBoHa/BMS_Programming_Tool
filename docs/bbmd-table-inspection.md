# Read-only BBMD table inspection

This focused profile covers the read-only portion of manual feature
**MF-7558ea4aa8** and audit **IA-120b496d86**. It inspects one existing IPv4
BBMD's Broadcast Distribution Table (BDT) and Foreign Device Table (FDT), using
only BVLC Read-BDT (`0x02`) and Read-FDT (`0x06`). It does not change either table,
registration settings, routing, or point values. Explicit Write-BDT and
Delete-FDT-entry have a separate [reviewed administration profile](bbmd-table-administration.md).
BBMD hosting, BACnet/SC and IPv6 administration remain pending work.
No site, physical JCI device, MS/TP trunk, or BTCVT adapter was contacted.

## Operator workflow

1. Open a BACnet/IPv4 interface in **Connect**. A normal IP connection or an
   already registered foreign-device connection can reuse its existing socket.
2. In **Read BBMD administration tables**, enter one literal IPv4 endpoint and
   optional port. The default port is 47808. Hostnames, prefixes, multicast,
   unspecified/limited-broadcast addresses, the client's own socket and known
   local network/broadcast addresses are refused. Unknown remote subnet masks
   are never guessed.
3. Select BDT, FDT, or both. Choose a per-table response deadline from 0.1 to
   5 seconds. Press **Inspect BBMD tables** explicitly. Loading the panel or
   inspecting saved status sends no network queries.
4. Review each table's separate outcome and timestamps. A valid empty ACK is
   displayed as an empty table; silence remains unknown. **Cancel BBMD
   inspection** ends owned waiting/dispatch work and restores the receive hook.
   Previously transmitted reads cannot be recalled.
5. **Export BBMD snapshot** saves JSON with the original endpoint, exact interface
   configuration, process-local interface identity, actual local UDP endpoint,
   request bytes, local send/receipt times, native rows, response hashes and raw
   response evidence. Editing the draft target never relabels an earlier result.
   **Load table inspections** reopens retained session snapshots without querying
   the BBMD. Export before application restart; these snapshots are not durable
   database recordings.

BDT rows preserve all four native distribution-mask bytes, including noncontiguous
or unexpected values, with a separate contiguous-netmask flag/prefix. A native
mask such as `0.0.0.255` is not silently interpreted as hostmask shorthand. FDT
rows preserve native TTL and remaining-lease seconds independently. Remaining
lease may include server grace; it is not constrained to TTL, converted to an
inferred expiration time, or presented as proof that a device is alive. Addresses
in either table are configuration/lease evidence, not a discovered controller
inventory. The feature does not infer Device instance IDs or program names.

## Correlation and result limits

A table ACK is accepted only from the exact selected IPv4 address **and UDP
port**, addressed to the actual bound client endpoint, while the original app,
link binding, socket object and configuration remain unchanged. Normal APDU/NPDU
traffic, foreign-registration Results, other peers and unrelated native BVLC
handlers retain their existing paths. A pending native table collector prevents
an inspection; a collector that appears during an inspection ends it rather than
stealing its responses. Queries use directly awaited native request dispatch,
not detached library management futures.

Native Read-BDT NACK is Result `0x0020`; Read-FDT NACK is `0x0040`. A NACK does
not state whether the service is unsupported, disabled, or denied by policy, so
those causes remain unresolved. Other Result codes, including generic success
`0x0000`, are recorded as unattributed evidence and never substituted for an ACK.
They remain available to native registration/management handlers. Foreign
registration accepts only its success or native Register-Foreign-Device NACK
`0x0030`; a late read-table NACK cannot reject a pending registration renewal.
Existing registration traffic and renewals continue independently.

BVLC table reads carry **no transaction/invoke identifier**. A late reply from a
previous read of the same table at the same endpoint cannot be distinguished
from a current reply. Queries are serialized and paced; no stronger freshness
claim is made. BDT and FDT arrive in separate replies and do not form an atomic
configuration snapshot. Times are local UTC send/receipt observations, not BBMD
source timestamps. UDP loss, suppression and timeout do not prove an empty table
or unsupported BBMD.

Bounds are explicit:

- One active inspection; at most 16 retained session snapshots, with evictions
  counted. Each table is requested once, without retry or automatic continuation.
- At most 256 complete ten-byte entries per table. An oversized table is refused
  wholly; it is not displayed as a complete truncated table.
- At most 4,096 raw bytes retained per response. Every response retains its exact
  wire length and full-datagram SHA-256; `raw_complete=false` identifies a bounded
  raw prefix. At most eight unattributed Results are retained, with extra Results
  counted.
- At least 100 ms between inspection requests, a 3-second interface-lock wait,
  and a 14-second whole-operation deadline after lock acquisition. The caller
  waits at most 17 seconds plus cleanup under normal event-loop scheduling.
- Malformed type/declared lengths, incomplete entry lengths, entry bounds, native
  NACK, timeout, cancellation, interface loss and operation deadline remain
  separate outcomes. They never become fabricated rows.

## API and verification

- `GET /api/bacnet/bbmd-tables/status`: local profile/limits/session snapshots.
- `GET /api/bacnet/bbmd-tables/jobs/{id}`: immutable-source snapshot for export.
- `POST /api/bacnet/bbmd-tables/start`: `endpoint`, optional distinct `tables`
  (`bdt`, `fdt`), optional `timeout_seconds` (default 2 seconds).
- `POST /api/bacnet/bbmd-tables/cancel`: `id`.

POST routes use existing loopback/session protections. Shutdown cancels and joins
owned jobs before closing the shared interface. Restart opens no network and
resumes no inspection.

Implementation follows pinned BACpypes3 0.0.110 request/codec/service definitions;
upstream primary sources are [BVLC packet definitions](https://github.com/JoelBender/BACpypes3/blob/main/bacpypes3/ipv4/bvll.py)
and [IPv4 service handling](https://github.com/JoelBender/BACpypes3/blob/main/bacpypes3/ipv4/service.py).
Read-table replies in tests are independently encoded raw UDP bytes. Tests cover
masks/leases, exact peers and native-handler composition, malformed/oversized and
empty ACKs, native NACK versus timeout, bounded Results, owner conflicts, actual
socket replacement, cancellation/deadlines/shutdown, HTTP/session guards and
restart. Concurrent standard point reads and real foreign renewal traffic retain
operation. Browser tests exercise both tables, original-source/raw JSON export,
history reopen and cancellation against these raw UDP peers. Loopback tests do
not establish physical BBMD or vendor interoperability.
