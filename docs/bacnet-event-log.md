# Native BACnet Event Log history

Device history → Native Event Log history explicitly reads standard `event-log` objects (type 25). It reuses the bounded forward ReadRange, exact Device/log identity checks, pinned IP routing, owned exchange cleanup and sealed capture framework used for Trend Log Multiple. Its source kind, capture directory and format are separate: `device-history-event-log` / `bacnet-event-log-history/1`.

This is a tested native retrieval profile, not a claim of physical support on a particular JCI model, firmware or protocol revision. No site devices, credentials or private controller data were used. It does not subscribe to notifications, acknowledge events, write device properties, feed the simulation alarm lifecycle, deliver alarms, retrieve proprietary JCI historian data, or copy a controller program.

## Three separate clocks and native meanings

The outer `EventLogRecord.timestamp` is the logger's local date/time when it entered that record. Leave the logger timezone blank to retain unresolved native date/time, or explicitly supply the logger's IANA timezone and optional DST fold for the existing validated UTC interpretation. Wildcards, inconsistent weekdays, DST gaps and unresolved ambiguity remain visible. Logged clock changes retain their numeric/typed value and native sequence order.

A stored notification has its own initiating Device and embedded `TimeStamp`. DateTime, time-only and sequence-number choices remain native. That event source can be a different device with a different clock; choosing a logger timezone never converts the embedded event timestamp to UTC. The separate `read_received_at` / `recorded_at` values are this application's local read receipt UTC.

The logger can record a received notification or a locally generated event represented as notification parameters. Retrieval does not establish a network-delivery path or human receipt. Native `notifyType`, `ackRequired`, states and acknowledgement-notification records remain recorded fields; they are not reconstructed into an operator acknowledgement or resolution lifecycle.

## Native values and unsupported encodings

Known `EventLogRecord` choices—notification, log status and time change—remain distinct. Native notification parameters include source/object identifiers, process identifier, notification class, priority, event type, message, notify type, optional acknowledgement requirement/from-state, to-state, event timestamp and event-values choice. Unknown numeric enumeration values remain numeric with `known: false`; absent optional fields stay absent in the native raw representation. Quality stays unknown rather than inheriting current logger reliability.

The pinned BACpypes3 0.0.110 `NotificationParameters` Choice recognizes a finite set of alternatives. Unrecognized nested choices and values beyond the bounded JSON projection cannot be safely interpreted as typed notifications by that decoder. After validating the actual ReadRange source, invoke, service, object/property, request window and native ACK byte cap, this profile retains the native itemData tags as opaque evidence and stops. No records from that undecodable page are guessed or partially imported. Earlier valid pages remain separate evidence.

Opaque evidence records native item count, first sequence metadata, flags, source, receipt UTC, decoded-ACK SHA-256, tag byte count, tag SHA-256 and base64. The report budget is calculated before base64 expansion. When the remaining budget cannot hold the full bounded native tags, a labelled 3072-byte prefix is retained with `truncated: true` and the full tag count/hash. This is loss-explicit preservation, not full typed support for unknown or newer vendor event schemas. The JSON/CSV export distinguishes an `undecoded_native_page` from actual native records. Malformed outer APDUs or invalid response identities remain failures/timeouts, not notification records.

## Current configuration and acquisition

The tool reads current logger properties before and after acquisition. Snapshot comparison covers current name, enable/stop policy, buffer size and notification class; current counters/status/reliability are preserved separately because they can change naturally while logging. Each metadata value is capped at 4 KiB; an oversized value retains its decoded size/hash and is withheld from typed current configuration. Changed or unavailable current snapshots remain explicit. Neither matching snapshots nor the current Notification Class prove historical source configuration or delivery policy.

Enter the exact Device, Event Log object and address. Routed queries require both the literal IPv4 next hop and DNET:MAC. Select a forward position, sequence or time range. Sequence numbers use 1–4294967295 and wrap to 1. Time-based range selection uses the explicitly supplied logger timezone and aware UTC reference. Native order is retained; repeated/stale pages, gaps, request-window errors, inconsistent counts and invalid flags do not become new records. An explicit continuation starts another report; position-only pages without sequence anchors stop automatic pagination.

`records_complete` describes a native last/empty result for the selected range. Overall `complete` also includes finishing the bounded acquisition/configuration check. Neither means every historical record on a device was retrieved. Bounds, partial errors, cancellation and current configuration uncertainty remain in the evidence.

## Bounds, cancellation and captures

The profile is bounded to 1000 records, 100 records/request, 100 pages, 256 KiB/native ACK and a 2 MiB final report/capture. Exchanges have a 1.5-second timeout, overall operations a 15-second deadline and requests 50 ms spacing. Diagnostics retain a bounded text prefix and hash when truncated. Only one Event Log operation runs at a time; the shared connector serializes field reads. No automatic replacement read, subscription or polling job starts.

Cancel explicitly, leave Device history, replace the interface, disconnect or shut down to retire owned requests and restore temporary route/source hooks. Explicit cancellation returns completed pages, which can be exported or saved. Caller task cancellation propagates after cleanup. There is no device write to retry or undo.

Save preserves an immutable, hash-verified local capture under private regular-file storage with atomic publication, cross-process locking and bounded quotas. Repeated saves retain the original evidence. Up to 32 captures / 32 MiB are allowed; a full store refuses another capture without deleting evidence. Captures reload after restart without field traffic. Loading a capture restores its visible source/range controls. Hashes establish captured content integrity, not authenticated device identity, clock accuracy or manufacturer acceptance.

## Evidence and validation

- [ASHRAE Addendum b to Standard 135-2004](https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-2004-135b.pdf), section 135-2004b-1 / printed pages 1–11: original Event Log object, local entry timestamp, recorded notification/status/clock choices, ReadRange access and sequence behavior. Later protocol revisions and each device's supported services must be checked independently. The indexed local source has SHA-256 `bdd344526494e1b0a05f53f4b7675aa6148c449cfb8b37f402b7bf60a9db0449` (60 pages); the PDF is not redistributed.
- [Pinned EventLogRecord and EventNotificationParameters definitions](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/basetypes.py), [EventLogObject schema](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/object.py), and [ReadRange APDUs](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/apdu.py): reviewed against installed BACpypes3 0.0.110. Recognized schema choices are not an unrestricted claim about every EventType/vendor extension.

Authored real UDP peers and an independently framed IPv4/NPDU router test native notification/status/time choices, unknown enums, all three embedded event timestamp choices, logger clock isolation, unsupported nested choices, full/prefix opaque evidence, segmented >60 KiB payloads, bounded diagnostics and metadata, corrupted response identities/counts/flags/invokes, source spoofing, sequence wrap, partial/error/cancel/deadline paths, native rejection, capture restart/tampering and API session tokens. Browser tests cover explicit reads, native/opaque JSON and CSV, clock semantics, capture save/load and navigation cancellation. Existing single and multiple history suites protect the shared framework.
