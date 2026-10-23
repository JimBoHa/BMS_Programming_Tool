# Reviewed replacement of one native weekly day

This backend/API feature (`COMM-SCHED-003`, profile `native-schedule-reviewed-weekly-day-write/1`) builds on the [native capture and draft library](native-schedule-drafts.md). It replaces **one existing Schedule object's weekly-schedule array index1..7**. It does not create objects, change targets/defaults/priorities, write Calendar or exception data, toggle Out_Of_Service, evaluate schedules or compile native CAF applications. The [browser Apply workflow](native-weekly-day-write-ui.md) is tracked separately as `COMM-SCHED-004`.

An already-open plain BACnet/IPv4 interface is required. Direct unicast and an explicitly supplied, pinned router/DNET:MAC from the captured target are supported. BBMD/foreign-device and serial/Bluetooth writes are refused. A capture can be imported, but its self-seals establish integrity only: they do not authenticate its device/manufacturer or operator claims. Review the actual target before authorizing a write. No physical JCI/firmware acceptance is established by this implementation's loopback tests.

## Preview and fresh conflict checks

Select a retained, strict weekly-day draft. Preview regenerates its native proof from the immutable source capture, verifies its exact identifier/bytes and requires a visible user-declared operator name and rationale. These declarations are not authenticated identities.

Preview performs owned, single-attempt ReadProperty calls for the exact Device and Schedule identities, remote Max_APDU_Length_Accepted, all seven weekly days, the complete bounded exception array, native Schedule_Default, Effective_Period, references, Priority_For_Writing, Out_Of_Service, flags/reliability and Present_Value. Array counts are re-read. Native context and all value types must satisfy the strict draft profile. Device date/time/offset/DST fields are retained as dated observations; unsupported clock reads remain visible.

Static equality uses **exact native property tags**, not JSON values or evidence-row hashes that contain timestamps/invoke IDs. It covers the weekly array, exception array, effective period, default, writing priority, references and Out_Of_Service. Present_Value, flags/reliability and device clocks are typed observations, not static equality conditions. Unknown context remains deferred. This distinction lets a normal changing Present_Value or clock remain observable without fabricating a stale-configuration conflict.

The new DailySchedule is encoded server-side into one WriteProperty service15 for that fixed day. The request omits command priority and cannot resize the array. Preview exposes native requested/wire values, precision, exact service-body bytes, full unsegmented APDU size and remote limit. The APDU must fit both the explicit480-byte profile and the freshly read remote maximum. Oversized values are refused; no segmentation or split writes are attempted. Identical old/new native tags produce `no_change` with no Apply token.

A successful preview yields a30-second, one-use token bound to the exact draft/source, operator declarations, fresh native state, APDU body and current app/configuration/adapter/layer/server/socket/protocol identities. A newer preview of the same target/object/day retires its earlier token. At most16 plans are retained in memory. Restart/disconnect invalidates plans.

## Apply, acknowledgement and readback

Apply consumes the token before waiting, revalidates its source/draft proof, reacquires the same interface and repeats the bounded native checks. A changed identity, old day, neighbor, exception, static context, remote APDU limit, interface or socket prevents dispatch. Requests have a finite operation deadline15seconds, at most128 reads per fresh observation and bounded retained property bytes. The final dispatch callback checks exact service/body/size, interface and deadline before and after committing durable intent.

The unchanged reply budget begins at the one admitted downstream handoff, after durable intent and the final interface/deadline checks succeed. Synchronous local journal work consumes the overall operation deadline, but does not consume the response interval. Only this owned transaction's already-started native APDU timer is paused during preparation and restarted with its original configured duration at that handoff; its retry count remains zero. The caller's reply timer starts at the same boundary. The overall operation deadline can still end the operation sooner. Journal failure or an expired final deadline sends no packet. A post-send reply timeout remains uncertain and never triggers a retry. Other confirmed-service callers retain their existing timer behavior unless they explicitly opt into this single-attempt response-budget profile.

The native transaction is owned by the caller and permits **one unsegmented send, zero retries**. There is no detached send, automatic reconnect, retry or compensating inverse write. `dispatch_started` records admission immediately before the native send; a subsequent local send failure can still leave an uncertain receipt without proving a packet reached the device.

A dedicated service15 response guard accepts only complete Original-Unicast BVLC10 on the owned endpoint/socket, pinned next hop and exact NPDU source/invoke/service. Reserved NPDU control bits, unexpected routing, forwarding/broadcast, trailing ACK/Error bytes, wrong service/invoke and client-origin Abort cannot establish protocol acceptance. Server-origin Abort is explicit. Raw datagram bytes/hash and receive provenance are preserved; the shared-socket Windows provenance does not expose the physical IP destination. Unrelated responses and observers retain their own handlers/transactions.

The receipt separates these independent facts:

- `may_have_applied` stays **true after every admitted dispatch**, including native Error, Reject, server Abort, timeout, cancellation or interface failure. Negative replies do not prove unchanged remote configuration.
- `protocol_status` is `accepted`, `rejected`, `unknown` or `not_sent`. SimpleACK proves protocol acceptance only.
- `readback.status` is `match`, `mismatch`, `unavailable` or `not_attempted` for completed receipts, and `unknown` for recovered intent-only evidence. A complete readback compares the selected replacement and the other static configuration separately. Interrupted attempted readback is `unavailable`.

For example, an applied write with a dropped ACK can have `protocol_status=unknown` and `readback.status=match`. An implementation can apply data and return Error; that remains `may_have_applied=true`, with its actual readback reported. Neither matching readback nor a successful ACK proves future ownership, output behavior or persistence across device restart.

BACnet WriteProperty has no old-value/CAS field. Fresh sequential reads reduce stale-write risk but cannot prevent another writer changing configuration after the last check. They are not an atomic snapshot, compare-and-swap or rollback guarantee. Cancellation cannot undo a transmitted write. A new attempt requires a new source-qualified review; the API never automatically retries an uncertain result.

## Durable evidence and explicit reconciliation

The local SQLite journal holds at most64 records and64MiB, with an8MiB,1,000,000-value, depth64 profile per intent/result body. The larger value profile belongs only to combined receipts containing several observations; capture/source/draft parsing keeps its existing100,000-value default. Both intent and result must pass their receipt reader before persistence. A pending intent reserves8MiB for its possible result. Transactions use a bounded0.25-second database lock wait. Capacity pressure fails closed; there is no automatic evidence eviction. The local state namespace must be trusted. SQLite commit is durable local intent under the host/filesystem's guarantees; this is not a power-loss or remote application guarantee.

Intent commits before dispatch. A failed intent commit means no write is admitted. A post-dispatch result-save failure leaves the durable intent unresolved and returns a visible journal error. On reopening, an intent without a sealed result reports `unknown`, `may_have_applied=true`, `dispatch_started=null`, `protocol_status=unknown`, `protocol_accepted=null` and `readback.status=unknown`; a crash between intent and send cannot prove whether transmission or readback occurred. Its explicitly named `intent_snapshot` preserves the pre-send dispatch/protocol/readback fields, and `intent_sha256` binds the exact original intent bytes. Normal completed receipts retain observed Booleans. Sealed result bytes are immutable and bind their exact retained intent hash. Empty/TEXT/missing bodies, wrong identities/seals or mismatched intent hashes fail closed. Hashes are integrity checks, not authentication. Original server JSON must be downloaded as bytes: browser parse/stringify is not an equivalent export for signed zero or integral native floats.

`reconcile` is an explicit read-only operation. It regenerates the exact saved native proof from the receipt and capture, including after the in-memory draft list has been lost, reads the same target and compares the replacement/other static configuration. It sends zero writes, does not change the original receipt and never turns an uncertain protocol result into a historical ACK claim.

## HTTP contract

All POST routes require the existing local Studio token. Apply accepts no address, day, priority or retry override. The prefix is `/api/bacnet/schedules/writes`.

| Method/path | Request / result |
| --- | --- |
| `GET /profile` | Local capability, rule/source hashes, active operation, limits and journal summaries; no field traffic. |
| `POST /preview` | `{operation_id,draft_id,operator_name,rationale}`; fresh reads and original JSON review. |
| `POST /apply` | `{operation_id,token,review_sha256}`; one-use guarded dispatch and sealed original receipt bytes. |
| `POST /cancel` | `{operation_id}`; cancel only the named owned operation. |
| `GET /receipts/{id32}` | Exact sealed result, or explicitly unresolved intent evidence after interruption. |
| `POST /reconcile` | `{operation_id,receipt_id}`; explicit bounded reads and a new sealed observation, no write. |

Operation IDs contain8..80 ASCII letters/digits/underscore/hyphen. Draft IDs are64 lowercase hex characters; receipt IDs are32. Tokens are32 URL-safe characters. Unknown/extra fields, malformed IDs and reused/expired/replaced tokens fail before dispatch.

## Source evidence and verification

- Controller Tool Help18.0, LIT-12011147, PDF235–236/247–248: weekly/exception editing, native output/default/effective-period/writing-priority context. Downloaded SHA256 `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`. These pages do not certify this tool or legacy controller write support.
- SCT Help19.0, LIT-12011964, PDF328–329, SHA256 `a8bd468067d46ad3509fdd40c73dcef967a8a7d517b43c5bd4561af45fa794d4`: native schedule purpose/context. Supervisory archive engineering remains separate.
- Pinned BACpypes3 **0.0.110** `apdu.py`: WriteProperty fields/service15 and exact ACK/Error/Reject/Abort forms; `appservice.py`: owned native ClientSSM dispatch/retry behavior. Reviewed SHA256 values appear in the versioned profile/rule hash. The strict draft rule hash is also pinned.
- `tests/test_native_schedule_write.py`: independently authored literal UDP direct/routed peer, exact expected bytes and every day index; type/source/context/size/token guards; protocol/readback separation; one-send counts; raw source/BVLC/NPDU spoofing; cancellation, journal failures, restart/seals and observer coexistence.
- `tests/test_native_schedule_write_api.py`: authenticated real loopback source acquisition, preview/apply, independent receipt seals, exact original bytes including signed zero, one-use refusal, offline restart and explicit read-only reconciliation.
- `tests/test_native_write_deadline.py`: independent literal ACKs with delayed synchronous durable intent isolate both caller and native APDU timers, plus strict budget admission, elapsed pre-send deadline refusal, unchanged post-send timeout and one-packet checks. Original Windows acceptance failures remain retained separately; passing host regressions do not establish a Windows or physical-device acceptance result.

Physical JCI/other manufacturer acceptance, scheduling execution, output effects, native CAF/CCT compilation/download, Calendar/exception/context edits, object provisioning, proprietary global calendars/timezones, serial/BTCVT/BBMD writes and unrestricted cross-brand conversion remain unverified or outside this profile.
