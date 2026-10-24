# Reviewed BBMD table administration

This profile adds explicit IPv4 BVLC Write-BDT (`0x01`) and targeted
Delete-Foreign-Device-Table-Entry (`0x08`). It covers the table-change portion of
manual feature **MF-7558ea4aa8** and audit **IA-120b496d86**. The separate
[read-only inspector](bbmd-table-inspection.md) still performs only table reads.
BBMD hosting, BACnet/SC, IPv6 administration, controller programming and physical
vendor acceptance remain outside this profile. Verification used independent
loopback UDP peers; it contacted no site, physical JCI device or BTCVT adapter.

On the pinned Windows shared IPv4 socket, [owned receive provenance](ipv4-receive-provenance.md)
pins the actual callback/socket/peer and exact raw management frame. Its physical
IP destination is unavailable. This preserves malformed/native Result evidence
and the existing uncertain-authorship rules; it does not strengthen BVLC's
unversioned read/write semantics.

## Review and apply

1. Open a normal BACnet/IPv4 interface in **Connect**. Administration refuses
   foreign-device connections, a bound native BVLC service owner, or a custom
   link/multiplexer management observer. It preserves those services instead of
   interrupting registration or stealing ambiguous Results. The read-only
   inspector supports a broader interface profile.
2. In **Reviewed BBMD table changes**, select one literal IPv4 BBMD endpoint.
   Hostnames, prefixes, multicast, unspecified/broadcast transport destinations,
   the client's own socket and known local network/broadcast addresses are
   refused. A remote subnet mask is never guessed.
3. For BDT replacement, explicitly **Load current BDT into draft**, edit the
   ordered rows, then **Prepare BBMD change review**. A BDT write replaces the
   entire table. **Zero rows clears the entire BDT.** Every native IP, port and
   four-byte distribution mask is preserved, including port zero or
   noncontiguous masks. The BBMD decides whether native entries are acceptable.
   Loading the table or preparing an unchanged replacement never sends a write.
4. For FDT deletion, enter one exact native IPv4:port endpoint and prepare a
   review. Exactly one matching row must exist. The receipt preserves its native
   TTL and remaining lease separately; neither is inferred from the other.
5. Review the immutable source endpoint, interface configuration and process-local
   identity, actual local socket, raw original table, desired replacement or
   deletion, exact write bytes, hash, expiry and protocol limits. Changing a
   browser draft/source discards the browser's approval. A late response for an
   earlier draft remains labelled with its original source.
6. Check the explicit acknowledgment, then **Apply reviewed BBMD change once**
   within 60 seconds. The first well-formed acknowledged Apply attempt consumes
   its in-memory token, including invalid-token/hash refusals and later failures.
   It cannot be retried automatically.
   Restart discards tokens and opens no interface or background operation.
7. Review the final receipt and **Export BBMD change receipt** as JSON. **Load
   BBMD change history** reopens durable receipts without field queries. **Review
   restoring BDT before-state** creates a new proposal against the original
   endpoint and currently open interface; it requires fresh review and Apply.
   It is not an automatic rollback. FDT registration recreation is unsupported.

## Guards and evidence

The original app, configuration, link adapter, socket object, actual local UDP
endpoint and exact remote IPv4 address **and port** must remain unchanged.
Replies addressed to a different local endpoint or received from another peer
cannot complete a request. Native/custom management ownership that appears
during an operation stops administration. Its observer remains intact; retired
cooperating wrappers can be removed without leaving a chain of inactive hooks.
Normal NPDU/APDU traffic keeps its existing handlers. The existing interface
lock serializes this application's table work and point operations; it cannot
lock another client or the BBMD itself.

Before exposing Apply, the application commits the original table and the sealed
proposal to a dedicated SQLite journal. Apply reopens and verifies that sealed
proposal, commits admission, and reads the entire relevant table again. BDT
comparison uses exact ordered native response bytes. FDT comparison uses the
ordered address/TTL membership; naturally changing remaining leases are evidence,
not a version. Changed membership, order or TTL refuses the write. An identical
address and TTL **cannot identify a lease generation**.

Immediately before dispatch, the application commits the raw before-state,
pre-Apply read, exact proposed packet and an **unknown dispatch intent**, using
SQLite `synchronous=FULL`. If proposal/admission/intent persistence fails, it
sends no mutation. There is exactly one mutation request. No write retry,
verification retry, automatic reconnection or rollback occurs.

After the request, a separate read observes the relevant table. Receipts distinguish:

- `desired-state-observed`: a BDT reply contains the desired exact ordered bytes,
  or the specified FDT endpoint is absent in the observed table.
- `different-state-observed`: the observed table differs from the desired state.
- `unknown`: a mutation may have been sent but cancellation, timeout, lost
  ownership/interface or failed readback prevents an observation.
- `not-dispatched`: this application did not enter its mutation dispatch call.

**No observation proves authorship or atomic compare-and-swap.** BVLC reads and
Results have no invoke ID. A same-peer reply can be late, unsolicited or caused by
another client's operation. A generic Result `0x0000` is not proof that this
write succeeded. Write-BDT NACK `0x0010` and Delete-FDT NACK `0x0050` remain native
evidence, without an invented unsupported/denied cause or attribution. Receipts
always report `write_outcome=unknown` after mutation dispatch, even if the desired
state is later observed. The application exposes no authentication bypass.

Eight Result frames are retained with omissions counted. Fixed counters track
each defined native Result code, other codes and malformed Results. The last
administration NACK is retained separately, so generic-success traffic cannot
hide it when the list fills. This NACK still has no proven relationship to the
current mutation. Raw response bytes, lengths, hashes, local UTC send/receipt
times and request phase remain available. No BBMD clock is invented.

A concurrent edit can occur after the last baseline read and before the write.
It can also produce the desired state independently. The application does not
claim atomicity, a coherent multi-table backup or exclusive BBMD ownership. An
FDT renewal can recreate an entry immediately after deletion; absence is one
observation, not permanent removal. Remaining lease may include server grace;
TTL/remaining are not interpreted as proof of a live controller.

## Cancellation, failure and retention

Cancel ends owned waiting/verification work; it cannot recall a transmitted UDP
packet. After local dispatch starts, cancellation, interface change, shutdown or
deadline leaves the write outcome unknown. Hooks and pending waits are retired,
and no further request is sent. Shutdown joins owned tasks before closing the
interface. Disk work runs off the event loop but remains owned and joined even
through repeated cancellation; a stalled operating-system write can extend
cleanup beyond network deadlines.

Receipts live in `bbmd-administration/receipts.sqlite3` under the configured state
directory. A cross-process OS writer lock prevents concurrent journal ownership.
History can be read while another process owns the writer. POSIX and Windows lock
implementations use the existing outbox helper; Windows execution was not
verified in this feature's Mac test run. A corrupt/unavailable optional journal
disables administration while leaving the session, monitor and read-only tools
available. Receipt SHA-256/identity mismatches fail closed; hashes detect accidental
or partial corruption, not modification by an attacker controlling the state
directory.

If final persistence fails, the runtime receipt explicitly reports that its
observation may be absent from disk. The durable earlier intent remains unknown.
On restart, unfinished durable operations become interrupted/unknown; they are
never replayed, verified or rolled back automatically. Export live evidence
before stopping if the final storage update failed.

Bounds are explicit:

- At most 256 entries per complete table/replacement; oversized tables are
  refused, never treated as a complete truncated table.
- At most 16 unexpired review tokens, each valid for 60 seconds. One Apply runs
  at a time. Expired tokens are pruned at subsequent explicit preview admission.
- At least 100 ms between table/mutation requests, a 3-second interface-lock
  wait, up to 8 seconds for preview network work and 20 seconds for Apply network
  work after lock acquisition. Per-response deadlines are 0.1–3 seconds.
- At most 4,096 raw response bytes retained per frame, with full length/hash and
  an explicit completeness flag. Valid table ACKs fit within this raw bound.
- At most 512 durable receipts, each at most 512 KiB. Existing receipts can still
  be finalized at capacity; new proposals are refused. There is no automatic
  history eviction or archive/reset UI in this profile. Exporting does not free
  capacity; do not delete the journal during an active operation.

## API and verification

GET routes inspect local state only:

- `/api/bacnet/bbmd-admin/status`: profile, limits and active local work, or an
  explicit unavailable reason.
- `/api/bacnet/bbmd-admin/history`: durable receipt summaries.
- `/api/bacnet/bbmd-admin/receipts/{id}`: source-preserving full receipt for export.

POST routes use the existing session/origin guards:

- `/api/bacnet/bbmd-admin/preview`: `endpoint`, `operation`, optional BDT `rows`
  (omitted to clone current table), or exact `delete_target`, and optional
  `timeout_seconds`.
- `/api/bacnet/bbmd-admin/apply`: `id`, `review_hash`, one-use `apply_token`, and
  explicit `acknowledge_limits=true`.
- `/api/bacnet/bbmd-admin/cancel`: `id`.
- `/api/bacnet/bbmd-admin/restore-preview`: original `id` and optional deadline;
  creates a new BDT proposal, never a restoration write.

Pinned BACpypes3 0.0.110 definitions establish the native framing and Result
codes; primary upstream references are [BVLC packet definitions](https://github.com/JoelBender/BACpypes3/blob/main/bacpypes3/ipv4/bvll.py)
and [IPv4 service handling](https://github.com/JoelBender/BACpypes3/blob/main/bacpypes3/ipv4/service.py).
Independently authored raw UDP peers verify exact write/delete packets, masks,
lease evidence, native Results/NACKs, rogue peers, stale state, unavoidable
concurrent races, observation versus authorship, one-use/expiry, journal failures,
repeated cancellation, observer conflicts/retirement, restart and shutdown.
HTTP/session and browser checks exercise review, source invalidation, actual
mutation packets, history/export, fresh restoration proposals and cancellation.
These checks do not establish physical BBMD or JCI interoperability.
