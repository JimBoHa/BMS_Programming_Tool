# Standard BACnet Trend Log Multiple history

Device history now has a separate **Multiple-channel device history** panel. It explicitly reads standard `trend-log-multiple` objects (BACnet object type 27) through the existing BACnet/IPv4 connector, including a pinned IP router and DNET:MAC destination. It does not open another connection, poll automatically, write a device property, fetch a native controller program, or claim to read proprietary JCI historian storage.

This implements the standard Trend Log Multiple retrieval portion of the history feature backlog. Support must be checked on the exact device and firmware. Authored loopback peers exercise the native protocol; no field devices, building credentials, or private controller files were used. Successful loopback tests do not establish availability on a particular FX-PCV, VMA, or NAE.

## Use and evidence

1. Connect the intended BACnet/IP interface in Connect, then open Device history. Refresh multiple-history status after an interface change.
2. Enter the exact address, Device object, and Trend Log Multiple object. Routed reads also require the literal IP next hop and DNET. Device and log object identifiers are verified by actual ReadProperty responses before reading records.
3. Select a forward list-position, sequence-number, or time range, count (1–1000), and page size (1–100). This profile accepts actual sequence numbers 1–4294967295. Time-based selection requires the explicitly supplied IANA device timezone and an aware UTC reference. Whole hundredths and BACnet's date range are enforced.
4. Read explicitly. The table preserves each native row and channel index; log status, clock changes, nulls, failures, bitstrings and opaque tags remain distinct. Inspect the full evidence and channel-reference metadata when interpreting data.
5. Export JSON or CSV, or save a sealed local capture. A continuation begins a separate explicit read/report, using the native next sequence/position anchor; it does not append a possibly stale page to a previous report.

`complete` describes the bounded acquisition and its native range result, not all historical data on a device. A device can have records outside the requested sequence/time window. `records_complete` separately records whether a native last/empty page completed the selected range; a later reference-check interruption may still leave the overall operation incomplete. Count/page bounds, failures, cancellation and unstable pagination remain visible alongside acquired pages.

## Channel references and quality

The tool reads the current `Log_DeviceObjectProperty` array length and each bounded indexed reference before acquisition, then rereads them afterward. Both metadata snapshots and receipt times remain evidence. A changed count, changed same-length references, failed recheck, or channel/reference-count mismatch prevents assigning those current references to historical channel entries. Raw historical indices and values are preserved.

Even matching current snapshots establish current metadata coherence only. They do not independently prove an old record's historical channel assignment, and the export says so. Uninitialized wildcard references remain explicitly marked. The tool never follows a referenced remote Device or assumes that another channel's logged status bits describe a numeric channel.

Scalar channel quality stays `unknown`: the native multi-channel record has no implicit per-channel historical status flags or reliability. A native failure datum is preserved and marked `fault`, without inventing a sensor reading. A bitstring that a device explicitly logged as a separate property remains its own channel. Nonfinite numbers, opaque BACnet tags and large integers retain the shared typed evidence representation; opaque values are not interpreted as proprietary controller data.

## Source clocks and consistency

Native `LogMultipleRecord.timestamp` is BACnet DateTime, not the event service's separate TimeStamp choice type. Raw date/time fields are always retained. With no operator-supplied timezone, UTC stays null. With an explicit IANA zone, the existing clock interpreter checks wildcards, invalid dates, weekday conflicts, DST gaps and ambiguous times. Ambiguous timestamps stay unresolved unless the operator explicitly chooses a fold. Local receipt UTC remains separate from interpreted source time. Logged clock adjustments are retained in native order; records are never reordered to hide clock changes.

Sequence-based continuation checks request windows, exact next anchors, duplicate/stale pages and Unsigned32 wrap from 4294967295 to 1. A failed/gapped new page is not imported. Position-only pages without sequence metadata stop automatic pagination and retain a visible explicit position cursor. No atomic device snapshot is implied; a rolling or reset buffer can interrupt a read. Native log-status records and errors remain evidence of interruption or purge, not fabricated process samples.

## Bounds, cancellation and capture storage

The profile allows at most 32 channels, 1000 records, 100 pages, 256 KiB per native ACK, and a 2 MiB report/capture. Requests use a 1.5-second exchange timeout, 15-second overall deadline and 50 ms request spacing. One multiple-history operation runs at a time. The report cache holds eight results and cancellation tombstones are capped at 64.

Explicit cancellation, leaving Device history, interface replacement, disconnect and shutdown retire owned exchanges and restore temporary router/source hooks. Completed pages remain available after an explicit service cancellation. A caller task cancellation propagates after cleanup. The service does not start a replacement read.

Captures use a separate profile and storage namespace from single Trend Logs. They reuse immutable, hash-verified, regular-file-only storage, atomic publication, private file permissions, cross-process locking and quotas. Repeated saves preserve original evidence. Up to 32 captures / 32 MiB are retained; a full store refuses another capture without deleting evidence. Captures reload after restart without network traffic. Hashes establish content integrity, not manufacturer authenticity or an authenticated device clock.

## Primary references and tests

- [ASHRAE Addendum b to Standard 135-2004](https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-2004-135b.pdf), approved October 2008: introduces Trend Log Multiple, ordered property references, native multi-value records, ReadRange retrieval, status/clock-change entries and sequence wrap. It describes purge/error behavior when logged references change. These original definitions do not assert support on a particular product release.
- [Pinned BACpypes3 native datatypes](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/basetypes.py), [object schema](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/object.py), and [APDU schema](https://github.com/JoelBender/BACpypes3/blob/21f918c0396c72c95e7e635abde18514e58feb8d/bacpypes3/apdu.py): reviewed against installed BACpypes3 0.0.110. The implementation decodes `LogMultipleRecord` rather than treating multiple logs as single-channel `LogRecord` values.

The local research library indexes the ASHRAE source as `ASHRAE-135-2004-Addendum-b-Trend-Log-Multiple.pdf` (60 pages; SHA-256 `bdd344526494e1b0a05f53f4b7675aa6148c449cfb8b37f402b7bf60a9db0449`). The PDF is not redistributed in this repository.

Tests use real native UDP applications and an independent literal IPv4/NPDU routed peer. They cover range choices, exact identities, rogue next-hop replies, corrupted object/property/count/flag/datatype/invoke metadata, stale pages, sequence wrap, unknown/wildcard clocks, native choices and opaque values, current-reference changes, missing metadata, byte/channel/page limits, native rejection, deadline/cancel/teardown, pre-invoke cancellation, capture restart/tampering, API tokens, browser queries/continuation/cancellation, JSON/CSV export and local capture loading. Existing single-history and shared read/storage tests protect the reused behavior.
