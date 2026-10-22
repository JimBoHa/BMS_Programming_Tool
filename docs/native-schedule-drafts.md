# Native schedule captures and offline day drafts

This feature retains an existing standard BACnet Calendar/Schedule inventory and reviews a replacement for one existing Schedule's weekly day. It makes no controller calls when saving, importing, reopening, reviewing or exporting. There is no native write or Apply action in this feature.

In **Connect**, explicitly read native schedules using the existing inventory workflow. Save the returned report to the local library. The library remains usable after disconnection and application restart. Select a capture and an eligible Schedule, choose Monday1 through Sunday7, and edit its typed time/value rows. Review the exact old/new day, requested versus wire values and source hashes before exporting the draft. Export the sealed capture with the draft; importing a draft requires its original capture to be present.

Calendar and unsupported Schedule values remain available in the original capture. This feature does not author Calendar Date_List, exceptions, new objects, output references, defaults, writing priorities, Out_Of_Service, vendor Enabled, timezone or cleanup settings. It does not evaluate a native schedule, simulate target release behavior, generate CAFs, provision JCI objects, or establish physical device acceptance. Portable host calendar/schedule simulation is a separate profile.

## Exact source and durable library

The capture profile is `native-calendar-schedule-capture/1`. A capture contains the exact original inventory-export UTF-8 bytes in `source_json`, their SHA256 content identifier, the original inventory evidence seal, local ingest metadata and an archive-body seal. Saving uses the same server serialization as `/api/bacnet/schedules/export`. Original float spelling and signed zero survive; copying a parsed browser object is not an equivalent export. Downloads use authoritative server bytes.

Import checks UTF-8, structure/byte bounds, duplicate fields, finite numbers, the exact known profile, source-byte hash, archive-body hash and original inventory evidence seal. Nonzero numeric underflow is rejected instead of silently becoming zero. Unknown/opaque native evidence and unsuccessful/partial inventory observations remain intact in the original source. A partial capture may be useful for inspection but cannot supply missing draft prerequisites.

These are integrity checks, not authentication of a manufacturer, operator, controller or imported source. The inventory is a series of dated observations, not an atomic backup or proof that configuration remains unchanged. A caller able to construct a complete new document can create new self-seals.

The library holds at most32 immutable source captures and64MiB. Each source is at most2MiB and each archive4MiB. A fresh import records the incoming archive SHA256 in local ingest metadata and emits an import receipt with incoming/stored archive digests. The local wrapper may be repackaged with a new seal; only the original inventory source identity stays identical across imports. Duplicate source bytes reopen the existing capture without replacing it or its ingest timestamp; the incoming digest remains available in that operation’s response. Capacity pressure fails without overwriting or silently evicting evidence. Regular-file/no-symlink/reparse checks, portable process locking, exclusive temporary files, file-data flush and hard-link publication protect the storage boundary. Unsupported filesystem operations fail closed. POSIX namespace synchronization is attempted; Windows does not claim directory/namespace or power-loss durability. The local state directory and its parent namespace must be trusted. Corrupted or substituted capture files fail validation on reopening.

## Strict weekly-day profile

The draft profile is `native-schedule-weekly-day-draft/1`; its explicit rule definition/hash and reviewed source hashes appear in the profile and review. The selection is an existing Schedule object17, one array index1..7. No count/index0 or whole-array replacement is generated.

Eligibility requires exact captured Device and Schedule identities, native tag/JSON agreement, all seven weekly days, the complete bounded exception array, and complete Effective_Period, Schedule_Default, Present_Value, references, writing priority, flags, reliability and Out_Of_Service evidence. Exception priorities and calendar-reference object types are checked. Unknown native primitive types, unknown Reliability enums, unqualified WeekNDay week codes7..9, missing/opaque fields, invalid date patterns and inconsistent context defer editing; their source evidence is still retained. Referenced calendars/output points are not queried. Date patterns and effective periods are retained and checked structurally; no timezone or runtime interpretation is inferred.

A supported **non-Null Schedule_Default** establishes the exact native datatype. Every captured weekly/exception/present value must use that datatype or explicit Null. A Boolean is not interchangeable with Enumerated, Unsigned, Integer, Real or Double. Null Schedule_Default and unknown release/default interpretations are deferred. The supported TimeValue primitives are Null, Boolean, Unsigned, Integer, Enumerated, Real and Double. Null authoring means an explicit native null tag only; device release/fallback behavior remains unverified.

Each day contains at most32 strictly increasing transitions. Times have explicit integer hour/minute/second/hundredth fields in0..23/59/59/99; Boolean, wildcard, duplicate and unsorted fields are refused. Empty days are explicit. Values use strings in the editor/API: `true`/`false`, `null`, canonical integer text or finite JSON decimal/exponent text. Integers use a signed32-bit or unsigned32-bit profile. Floating text parses to binary64 and then its declared wire type. Nonfinite values, overflow and nonzero underflow fail. The review exposes the original text, binary64 parse bits, native value text and both decimal/wire rounding indicators. Ordinary decimal/binary32 precision differences remain visible, not silently treated as exact.

Server-generated day seeds come from decoded native values. `repr(float)` preserves original `-0.0`; integer, Boolean and Null seeds retain their exact type. The capture list omits day seeds to bound its response size; a selected capture includes them.

The new DailySchedule is natively encoded, decoded with no trailing tags and reencoded byte-identically. The old day must match the captured native bytes without unsupported normalization. The review binds original capture/evidence/context/weekly hashes, Device/route, selected day, old/new tag bytes and SHA256 values. It shows which context and other days remain unchanged **in the draft**. This is not a fresh conflict check or remote compare-and-swap guarantee.

At most16 reviews of at most256KiB are retained in one application session. Capture files persist; reviews persist through explicit export/import. Draft import verifies its seal, strict request and exact known rules by regenerating the entire proof from the saved source before retaining it. Invalid imports do not add reviews. Every imported capture/review remains offline.

## HTTP contract

All POST requests require the existing local Studio token. The prefix is `/api/bacnet/schedules/library`.

| Method/path | Operation |
| --- | --- |
| `GET /profile` | Local limits, rule/source hashes and capture summaries. |
| `POST /save` `{id: report32}` | Save an existing session inventory. |
| `GET /captures/{sha64}` | Reopen source preview, eligibility and typed day seeds. |
| `POST /import` multipart `file` | Verify and store a sealed capture. |
| `POST /export` `{id: sha64}` | Download exact stored capture bytes. |
| `POST /source-export` `{id: sha64}` | Download exact original inventory bytes. |
| `POST /drafts/review` | Review `{capture_id, object_id, day, transitions:[{time:[h,m,s,hs],native_type,value_text}]}`. |
| `POST /drafts/export` `{id: sha64}` | Download exact retained review bytes. |
| `POST /drafts/import` multipart `file` | Verify/regenerate a review against its saved source. |

The `old/new.encoded_hex` fields describe a DailySchedule sequence, not a WriteProperty APDU. Seed `encoded_hex` preserves the original inventory property context3 envelope. A separate future native-write feature must acquire fresh identity/context, establish a one-use operator review, suppress retransmission and report uncertain outcomes; this offline draft supplies no such authorization.

## Evidence and verification

- [Controller Tool Help18.0, LIT-12011147](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0), PDF235–236 and247–248: weekly/exception editing, output types, effective period, writing priority and release restrictions. Reviewed downloaded SHA256 `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`. The corrupted Week/Day extraction on248 is not a protocol definition. CCT16/17 have related but release-qualified descriptions; none proves legacy controller support.
- [SCT Help19.0, LIT-12011964](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/SCT-System-Configuration-Tool-Help/19.0), PDF328–329: weekly/exception purpose, effective-period wildcards, native output categories and conditional release support. SHA256 `a8bd468067d46ad3509fdd40c73dcef967a8a7d517b43c5bd4561af45fa794d4`.
- Pinned BACpypes3 **0.0.110** `object.py` Schedule2571–2589, `basetypes.py` TimeValue1976/DailySchedule2685/SpecialEvent3671–3680 and `primitivedata.py`: verified native datatype/encoding contracts. Reviewed source hashes are included in the versioned rule definition. The local evaluator is not used as a standards or JCI runtime oracle.
- `tests/test_native_schedule_library.py` and `tests/test_native_schedule_library_api.py`: independently encoded real direct/routed UDP source reads; literal native expected tags; primitive/default/context mismatch and range cases; signed zero and readable rounding; exact exports, restart/import with no field queries; tamper/unknown-profile/duplicate-key checks; bounded retention/capacity, actual cross-process ownership, nonregular files and failed publication. Browser coverage exercises the library/editor/import/export flow and stale ownership guards.

These tests use local loopback and temporary storage. They establish no physical manufacturer/firmware, Bluetooth, native CCT/PCT compilation/download or unrestricted conversion acceptance.
