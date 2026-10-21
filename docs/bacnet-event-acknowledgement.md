# Reviewed native BACnet event acknowledgement

Connect → Device event states → Inspect event → Acknowledge a device transition now supports the confirmed BACnet `AcknowledgeAlarm` service (APDU service choice 0). This is an explicit write to the selected device. The existing `GetEventInformation` query remains read-only. No alarm subscriptions, notification delivery, generated alarms, hardware changes, or program transfers are added by this feature.

The implementation is applicable to JCI and other BACnet devices only when the exact device implements this optional service and accepts the selected transition. Loopback direct and routed protocol tests do not establish support on any particular FX-PCV, VMA, NAE model, firmware release, or live installation. No field acknowledgement was sent during development.

## Review and write sequence

1. Explicitly query native event summaries for an exact Device object and address. Routed requests require both the explicit IPv4 next hop and destination network. Inspect one of the returned objects.
2. Select an unacknowledged transition, enter the operator identity and process identifier, and explicitly select an installed IANA timezone for the client acknowledgement clock. The UI does not infer a device timezone or site identity.
3. Preview verifies the actual Device identity and rereads native event pages over the exact original interface and route. It compares all native summary fields with the selected acquired report, including state, transition acknowledgement bits, timestamp choices, enable flags, notify type, and priorities. A changed, missing, unverifiable, unsupported, or ambiguous transition receives no apply token.
4. Review the exact source, object, transition, native event state and timestamp, declared identity, process identifier, clock policy, and expiry. A successful preview creates a one-use token bound to the full review hash, source report hash, native event, interface, and route. It expires after 30 seconds. Preview sends no `AcknowledgeAlarm` request.
5. Apply consumes the token before awaiting anything, then verifies the Device identity and full selected native summary again. If unchanged, it constructs the native request from the server-held fresh evidence, records a durable dispatch intent, and sends a single unsegmented confirmed request. Client-supplied event values are never substituted into the request.
6. Export the receipt and explicitly query events again before another acknowledgement. Every apply attempt invalidates the browser review and displayed event selection. A lost HTTP response can be investigated using the session receipt list or local audit.

A fresh read cannot prevent the device from changing between the read and write. The device's native timestamp/state checks and protocol rejection remain authoritative. A timeout or cancellation after dispatch cannot establish whether the device accepted the write. The application does not retry that write.

## Native transition and timestamp policy

- Only a transition whose acquired acknowledgement bit is false is selectable. Native notify types `alarm` and `event` are eligible for review; unknown values and acknowledgement-notification summaries are deferred.
- `TO_FAULT` uses native state `fault` (1); `TO_NORMAL` uses `normal` (0), each with its own transition timestamp.
- `TO_OFFNORMAL` uses the current, explicitly reported standard offnormal state when it is `offnormal`, `high-limit`, `low-limit`, or `life-safety-alarm` (2–5). If the current state is normal, fault, vendor-specific, or otherwise unresolved, the exact historical offnormal state is unavailable from `EventSummary`. The application visibly defers that case. It does not guess a historical state from the acknowledgement bit.
- Native `TimeStamp` choices `time`, `sequenceNumber`, and `dateTime` are preserved exactly, including sequence number zero. Sequence numbers must fit Unsigned16. Unset, wildcard, invalid-calendar, inconsistent-weekday, or incomplete event time/date values remain visible in retrieval but are not used for acknowledgement. An unspecified weekday is allowed when the calendar date is otherwise complete.
- `timeOfAcknowledgment` is newly generated at Apply from current client UTC converted to the explicitly selected IANA timezone. The receipt separately records UTC, timezone, offset, and DST fold. This does not reinterpret the source event timestamp as UTC or claim the client's clock is synchronized with the device.

The source string is `BMS Studio / <declared operator>`. The visible, single-line declared identity is limited to 48 UTF-8 bytes and excludes control characters. It is not authenticated by this tool and is not derived from OS users or site credentials. The explicit process identifier is an unsigned 32-bit value; follow the site's device/notification process policy. The tool does not invent a universal requirement that it match a Notification Class recipient.

## Outcomes, bounds, and cleanup

`accepted` requires an exact-source/invoke/service native SimpleACK. It confirms protocol acceptance only; it does not establish human receipt, notification delivery, event resolution, or physical correction. `rejected` records an exact native Error or Reject. `unknown` means dispatch began but a valid conclusive response was not obtained. `not_sent` or pre-dispatch `cancelled` records a stopped local operation. Receipts retain the reviewed evidence, fresh proof, native request, request APDU SHA-256 when prepared, source metadata, phase, timestamps, errors, and evidence hash.

This write uses an owned BACpypes3 transaction with its own retry count set to zero **before first dispatch**, and segmentation disabled. Global Device/SAP retry defaults are unchanged. An additional guard refuses a second confirmed send. The native request body plus header must fit the conservative 128-byte unsegmented profile. Freshness reads retain their ordinary read-only transaction behavior.

Preview and Apply each have a 15-second overall deadline and 1.5-second exchange timeout. Fresh verification is bounded to 20 pages, 500 summaries, and 1 MiB; each native page retains the event inventory's 64 KiB cap. Only one acknowledgement operation runs at a time. Plans are capped at 16, session receipts at 32, and cancellation tombstones at 64. The audit database lock wait is at most 0.25 seconds for intent/result recording. A failed intent prevents dispatch; a failed result append is visible and the previously recorded intent must be reconciled.

Explicit cancellation, leaving Connect, changing the interface, disconnecting, and server shutdown retire the exact owned invoke/peer and restore temporary route/source hooks. Cancelling after transmission cannot undo the device write. Session receipts are bounded memory; export important receipts and retain the local audit before restarting.

## Protocol references and verification

- [ASHRAE Addendum g to Standard 135.1-2009](https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-135-1-2009g.pdf): acknowledgement-initiation tests use the event notification's state/timestamp, and the process identifier tests prevent assuming that every recipient must reject an unmatched process ID. Applicability depends on the tested protocol revision.
- [ASHRAE Addendum f to Standard 135.1-2009](https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-135-1-2009f.pdf): distinguishes original event timestamp from the current acknowledgement time and corresponding acknowledgement-notification timestamp.
- [BACpypes3 APDU definitions](https://github.com/JoelBender/BACpypes3/blob/main/bacpypes3/apdu.py) and [transaction implementation](https://github.com/JoelBender/BACpypes3/blob/main/bacpypes3/appservice.py): implementation reviewed against the locally pinned 0.0.110 package. Its `AcknowledgeAlarmRequest` defines the six native fields; the owned per-write transaction avoids changing unrelated application defaults.

Authored tests use real loopback UDP BACnet applications and an independently framed IPv4/NPDU routed peer. They cover each native timestamp choice; unique historical normal/fault transitions; unresolved historical offnormal state; changed/missing/already-acknowledged events; expired, modified and replayed reviews; identity/interface guards; native rejection and wrong service; timeout; rogue router replies; pre-invoke and post-dispatch cancellation; audit lock failure; exact transaction cleanup; API token checks; and browser review, Apply, cancellation, recovery, and export. A short native APDU timer with retries configured globally verifies exactly one acknowledgement datagram on the wire and unchanged global defaults.
