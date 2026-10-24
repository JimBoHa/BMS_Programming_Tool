# Finite BACnet event-notification reception

**Connect → Receive BACnet event notifications** receives standard confirmed
(`0x02`) and unconfirmed (`0x03`) EventNotification APDUs during an explicitly
started finite window. This implements a scoped reception portion of
**IA-e35c4d605e / IA-5f71db3ed0**. It is separate from
[GetEventInformation](bacnet-field-events.md),
[operator AcknowledgeAlarm](bacnet-event-acknowledgement.md), and
[recorded Event Log history](bacnet-event-log.md).

The sender must already address its notifications to this client's bound IPv4
endpoint with the selected process identifier. Starting a listener does not
subscribe, modify a Notification Class `Recipient_List`, configure a device or
router, or cause existing devices to send events here. No field/site equipment
was contacted while developing or testing this profile.

## Operator workflow

1. Explicitly open a normal BACnet/IPv4 interface in **Connect**. Foreign-device
   registration, direct serial, BTCVT, BACnet/SC and IPv6 reception are outside
   this profile.
2. Enter the exact source address and Device identity. For an MS/TP source behind
   an IP router, enter its explicit one-byte `DNET:MAC`, router IPv4:port and DNET.
   These are selected route details, not inferred routes or a trunk scan.
3. Enter the recipient process identifier (0–4,294,967,295), confirmed,
   unconfirmed or both modes, and a 5–3,600-second duration. An optional event
   object filter restricts reception to one exact object. Without it, events
   from any object of the verified Device can be retained. It does not prove
   that each reported object's configuration has been independently read.
4. Press **Verify identity and start finite listener**. The application reads
   back the exact Device identifier and the optional filtered object's identifier
   before installing its receiver. Identity failures, native rejects/errors and
   timeouts end the attempt. No listener or automatic reconnect remains.
5. Review received rows and raw evidence. A matching confirmed event receives a
   protocol SimpleACK with its original invoke ID. This is **reception only**;
   it does not perform operator `AcknowledgeAlarm`, prove human receipt, establish
   resolution, or guarantee delivery. `ackRequired`, native states and notify type
   remain received fields, not a locally generated alarm lifecycle.
6. Press **Stop event listener**, or allow its finite window to expire. Stop
   joins owned ACK callbacks; it sends no recipient cancellation or device write.
   Interface replacement/closure also ends the listener. There is no automatic
   restart, renewal, resubscription or recipient editing.
   Leaving Connect keeps the explicitly chosen finite window running; return and
   refresh listeners to stop or inspect it.
7. **Export event reception receipt** saves a source-qualified JSON receipt.
   **Save stopped event receipt** explicitly commits a final immutable snapshot
   to the existing local journal. **Load saved event receipts** reopens snapshots
   without network queries. Loading the panel starts no listener or device query.

Draft edits do not relabel an earlier receipt: the original source, process,
mode, router, DNET and actual local UDP endpoint stay visible. Saved snapshots
retain their original fields after a complete workspace copy and restart;
restart opens no listener or field interface.

## Source validation and protocol boundaries

Owned traffic must match the configured Device and process, optional object,
confirmation mode and finite listen window. It must arrive on the original
adapter and socket with matching local endpoint provenance. On the pinned
Windows shared socket, this requires owned raw BVLC Original-Unicast evidence;
the physical IP destination is unavailable. See the exact
[receive provenance profile and limits](ipv4-receive-provenance.md). Routed
events must carry the exact configured NPDU source network/MAC and arrive from
the exact configured IPv4 next hop and UDP port. The supported final-hop incoming
NPDU has no remaining destination address; broadcasts, transit traffic and
segmented notifications are outside the accepted profile. Socket identity,
configuration and health remain pinned throughout the session.

These are protocol identity checks, **not cryptographic authentication**.
Another sender able to spoof the exact network source can impersonate it.
Native device policy/errors are preserved; this feature provides no permission
or authentication bypass.

The receiver intercepts its owned unsegmented event APDUs before native
ServerSSM dispatch. Wrong source, route, mode or object cannot receive this
receiver's ACK. Other native processes and other initiating Devices retain
their original handlers. A native handler may independently respond to its own
traffic; such responses are not this receiver's acceptance evidence. Receiver
teardown cooperatively retires its wrappers without overwriting unrelated
handlers installed before or during the session.
An existing native EventNotification recipient handler refuses Start before any
identity query. If such a handler appears later, active reception stops rather
than replacing it. While active, this receiver owns its explicitly configured
Device/process tuple; a separate raw consumer must not claim that same tuple.
Only one active listener per Device/process tuple is admitted, even if another
route is proposed; stop it before replacing that tuple's source or mode.
Native tag decoding recognizes valid extended/nonminimal encodings of the
bounded process/Device prefix. Prefixes outside the Unsigned32 profile remain
unattributed to this receiver and cannot produce its ACK; default native error or
Reject handling remains possible.

Confirmed ACKs go directly through the verified local adapter to the pinned
IPv4 peer. Routed ACKs include the explicit original DNET:MAC destination and
network priority, without trusting mutable route caches or globally redirecting
other services. Temporary explicit-read filters admit only independently pinned
matching event traffic, including another route's receiver for the same DNET/MAC.
This path is exercised with actual UDP next hops; it does not test physical
MS/TP token timing, a BTCVT adapter or any exact manufacturer's alarm support.

## Native evidence and clocks

The pinned BACpypes3 0.0.110 schema supplies the standard envelope fields,
`TimeStamp` choices and known `NotificationParameters` types. Structural tag
balance, nesting/count bounds and trailing unmatched tags are checked before
decoding. Native enum numbers and names remain separate; unrecognized enum
numbers stay explicitly unknown.

Known native `eventValues` preserve all decoded fields and status flags.
An unsupported or undecodable nested choice retains opaque BACnet tag evidence,
its decode error, and the exact full accepted APDU/hash. Its semantics are not
invented. Opaque reception is not a claim that proprietary contents are valid or
understood. Unsupported/malformed envelope or `TimeStamp` choices instead remain
discarded raw evidence and do not receive an owned ACK.

Every accepted receipt retains its exact APDU bytes, SHA-256, length, local UTC
receipt time, Device/object/process, invoke ID if present, source/next-hop route,
network priority, native states/priority/notify type, raw event timestamp,
optional message/ackRequired and native values. Source UTC remains unresolved:
time-only, sequence-number or date/time timestamps never become an inferred UTC
clock. Quality remains unknown; received status flags are not independently
validated sensor reliability. Repeated identical APDUs are marked possible
duplicates, not collapsed into a fabricated single alarm or delivery count.

ACK status distinguishes unconfirmed/not-applicable, local dispatch returned,
and unknown after cancellation/error. A dispatch return does not prove the sender
received the ACK. Retained receipt count is a count of accepted notifications,
including retransmissions, not a count of unique alarms.

## Bounds, storage and shutdown

- At most 8 active listeners and 32 retained session receipts. Completed sessions
  are evicted first, with a session counter. Export or explicitly save before
  eviction/restart; in-memory receipt capture is not a durable live recorder.
- At most 100 accepted events per session. Older receipts are evicted with an
  explicit counter. Discards retain a counter, last reason and one bounded raw
  rejected frame with source evidence; the application does not keep an
  unbounded rejected-packet log.
- Accepted APDUs are at most 4,096 bytes, retained evidence at most 16 KiB, native
  envelopes at most 512 tags and 16 constructed levels. Oversized/malformed
  messages receive no owned ACK. Larger raw rejected frames retain a bounded
  prefix, full APDU length/hash and explicit incompleteness.
- At most 16 concurrent owned callbacks per session; excess traffic is discarded
  and counted without ACK. ACK dispatch has a 0.5-second deadline. Stop, expiry,
  shutdown and interface loss cancel/join owned callbacks. These bounds do not
  impose a system-wide firewall or bound unrelated native consumers.
- Start waits at most 3 seconds for this application's shared interface lock,
  then bounds identity verification to 10 seconds (2 seconds per property by
  default). Listener expiry uses a monotonic clock and a 50 ms health check under
  normal event-loop scheduling.
- Explicit stopped-session snapshots use a separate
  `event_reception_snapshots` table in `studio.sqlite3`. They never enter simulated
  alarms, COV receipts, trend samples, native Event Log history or webhooks.
  SQLite transaction/FULL synchronization precedes success. Failed saves return
  an error; the in-memory receipt remains exportable. Owned off-loop saves are
  joined even through repeated cancellation, so operating-system disk stalls can
  extend cleanup beyond network deadlines.
- At most 32 immutable saved snapshots, each at most 2 MiB, without automatic
  overwrite or deletion. Capacity refuses a new save; archive/reset UI remains
  future work. Exporting does not free capacity. Hash/identity validation detects
  corruption, not malicious changes by someone controlling the journal directory.
  JSON export downloads exact HTTP response bytes, preserving negative zero and
  integral native float spelling for independent Python hash verification.
  Selection, source changes or leaving the panel discard a delayed export.

There is no automatic durable recording while listening. A crash before explicit
save can lose any retained tail; no received event or gap is synthesized after
restart. Durable streaming reception, recipient-list management, event-summary
queries, operator acknowledgment and Event Log retrieval remain distinct features.

## API and verification

GET routes read local state/evidence only:

- `/api/bacnet/event-reception/status`: profile, limits and bounded sessions.
- `/api/bacnet/event-reception/sessions/{id}`: full session receipt/export.
- `/api/bacnet/event-reception/snapshots`: immutable saved inventory.
- `/api/bacnet/event-reception/snapshots/{id}`: verified saved receipt/export.

Session/origin-guarded POST routes:

- `/api/bacnet/event-reception/start`: exact `address`, `device`,
  `process_identifier`, `mode`, optional `object_id`, `router`, `dnet`,
  `duration_seconds`.
- `/api/bacnet/event-reception/stop`: `id`.
- `/api/bacnet/event-reception/save`: stopped session `id`.

Primary schema references are [BACpypes3 APDUs](https://github.com/JoelBender/BACpypes3/blob/main/bacpypes3/apdu.py),
[native event/timestamp datatypes](https://github.com/JoelBender/BACpypes3/blob/main/bacpypes3/basetypes.py),
and [NPDU routing fields](https://github.com/JoelBender/BACpypes3/blob/main/bacpypes3/npdu.py).
Implementation was checked against the locally pinned package, not an assumed
future upstream version. Independent raw UDP fixtures author event APDUs,
identity responses, routed headers and ACK expectations without the native event
encoder. Tests cover direct/routed reception, unknown choices, malformed and
spoofed traffic, route-cache poisoning, concurrent route filters, callback/ring
bounds, finite expiry, teardown, storage faults/integrity, repeated cancellation,
HTTP/session guards, restart and browser snapshot/export/reopen. They establish
local protocol behavior, not physical manufacturer interoperability.
