# Durable alarm webhook delivery

`NotificationOutbox` provides an explicitly enabled HTTP(S) webhook profile for recorded alarm events. The application uses its simulation observation store. The event's original `source_kind`, source name, sequence, occurrence identifier, event timestamp and recording timestamp remain in the payload. A webhook receipt does not acknowledge an alarm, prove human receipt, or implement native controller alarm acquisition.

Creating a route sends nothing. Every route starts disabled, and enablement is held only in process memory. Restart never resumes sending. The service creates no background worker itself; the application can call `await cycle(limit=20)` manually or from its explicitly controlled worker, then `await close()` during shutdown.

## Routes and credentials

Create an immutable route with `create_route(name, url=None, *, url_env=None, sources=None, events=None, bearer_env=None, start_after=None)`. Exactly one of a fixed `url` or a URL environment-variable `url_env` name is required. HTTP and HTTPS are supported; user information, fragments, control characters, whitespace, backslashes and invalid ports are rejected. URL configuration is validated without opening a connection.

For an endpoint whose path/query contains credentials, use `url_env`: the actual URL is read and validated only when an attempt begins. It is never stored in the route, delivery payload, history or application logs. The route exposes `url: null` and its environment-variable name. A fixed URL is persisted as ordinary configuration. Optional `bearer_env` likewise contains only a variable name; the bearer value is fetched at each attempt and is never stored or returned. An absent or invalid environment value fails that delivery before network traffic and requires explicit operator retry after correction.

The dedicated outbox directory uses POSIX mode 0700; its SQLite database and ownership lock use mode 0600. Windows uses its user-directory access controls and the Windows file-lock implementation; POSIX permission enforcement was tested locally. No authentication values or receiver response bodies are placed in error messages.

Source filters are exact source-name matches; an empty list accepts any source. Event filters support `activated`, `returned`, `acknowledged` and `source-ended`. Filters, credentials' environment references, endpoint reference and retry policy cannot be edited after route creation. A different route is needed for a different definition.

The default `start_after=None` starts after the observation store's current latest alarm-event sequence. Explicit `0` opts into retained history. `status().latest_alarm_event_sequence` makes the starting position reviewable. Disabled routes do not ingest events; re-enabling resumes from their durable cursor and exposes any intervening retention gap.

## Durable queue, ordering and evidence

SQLite commits each enqueued event and the route cursor together. The `(route, record_key)` uniqueness constraint prevents duplicate queue entries. Payload bytes are canonical JSON containing `schema: bms.alarm-webhook.v1`, route identifier, explicit source kind and the complete original alarm event. Each delivery has a stable `Idempotency-Key` and full-payload SHA-256, also sent as `X-BMS-Payload-SHA256`. Retries preserve the exact same body, key and hash. The hash is checked before inspection and sending.

Delivery history and configuration persist. Defaults allow 32 routes and 10,000 delivery/history rows. Capacity never silently evicts evidence or advances past an event that could not be queued. `prune_completed(through_id, limit=1000)` explicitly removes only delivered, discarded or gap history; cumulative removed-count and cursor metadata remain visible. Uncertain, failed, queued and in-flight records cannot be pruned.

Missing source event sequences produce durable `kind: retention_gap`, `state: gap` history, including the unavailable sequence range. These records are never sent as invented alarm events. The cursor advances across a gap only after its evidence is saved. Source highwater regression records a gap and blocks the existing route. The outbox binds to the observation store's persisted logical `store_id` UUID and source kind. Copying or relocating the complete workspace preserves that identity and history; all routes still restart disabled. Substituting a different logical observation database is rejected, even when its path and event sequence numbers look the same. Source identity is checked in the same read snapshot as the ingested events, without depending on machine-specific paths or inode numbers.

If the source becomes unavailable or changes identity, status retains the outbox's durable counts and exposes `source_error` with an unknown (`null`) latest source sequence. Delivery history remains reviewable while dispatch is blocked. A startup failure disables only the notification service; other application workspaces remain available and no state is deleted.

The earliest unresolved event blocks later events on that route. Other routes can continue. A nonblocking OS ownership lock permits one active service per database, and a SQLite sending claim records the owning instance. Another live process cannot recover or send its in-flight request. After a crash, acquiring exclusive ownership proves the old service is gone; abandoned sending rows become uncertain. A later serialized cycle likewise reconciles a request whose receipt could not be saved because storage failed.

## Attempts and uncertainty

The transport uses HTTPX's [public transport API](https://www.python-httpx.org/advanced/transports/), a total asynchronous deadline, TLS verification, zero hidden connection retries and no redirect handling. [Environment proxy/CA configuration](https://www.python-httpx.org/environment_variables/) is disabled with `trust_env=False`. Direct transport avoids the high-level client's full-URL INFO log without suppressing unrelated clients' logs.

HTTP 2xx records delivery. Redirects and permanent rejection statuses fail the head delivery. Explicit HTTP 408/425/429/5xx responses and connection-establishment failures use bounded backoff. Defaults permit five attempts, starting at five seconds and capped at 300 seconds; exhaustion becomes failed. Each request's default total deadline is five seconds, configurable up to 30 seconds. Cycle limits bound attempted sends, not a guarantee that an entire batch finishes within one request timeout.

Read/write/response loss, total timeout, cancellation after claim and interrupted requests become uncertain. They are never retried automatically. `retry(id, note, actor=...)` explicitly accepts possible duplicate receiver effects and resets that attempt budget; lifetime attempts remain visible. `discard(id, note, actor=...)` records an operator decision and releases route ordering. Neither operation acknowledges the originating alarm. Disabling a route stops subsequent attempts; an already transmitted request cannot be recalled.

Receiver effects can precede a failed HTTP response, so even explicit failure responses can cause duplicates when retried. The stable key enables receiver deduplication; this profile does not claim exactly-once delivery, email support or human acknowledgement.

## Local verification

Forty-seven focused tests pass using actual loopback TCP/HTTP receivers only. They cover preserved original event timestamps/kinds, filtering, idempotency hashes, route ordering, successful receipts, explicit backoff/exhaustion, dropped responses, deadlines/cancellation, restart-off behavior, real cross-process ownership/crash recovery, SQLite receipt-write failure, retention and capacity gaps, portable workspace copying, different-source replacement/regression, explicit pruning, immutable definitions, disabled routes, payload corruption, credential environment references and INFO-log privacy. Independent review additionally reproduced real SQLite write-lock contention and verified recovery to uncertain without retransmission. No third-party notification endpoint, site device or Bluetooth interface was contacted by these tests.
