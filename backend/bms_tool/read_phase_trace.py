"""Opt-in, request-owned phase observations; never native evidence or transport control."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

PROFILE = "studio-readproperty-phase-trace/1"
MAX_BYTES = 64 * 1024
MAX_EVENTS = 256
MAX_PACKETS = 32
PREFIX_BYTES = 512
MAX_HASH_BYTES = 256 * 1024
MAX_DATAGRAM = 65507
LIMITS = {
    "encoded_trace_bytes": MAX_BYTES,
    "events": MAX_EVENTS,
    "packet_prefixes": MAX_PACKETS,
    "prefix_bytes": PREFIX_BYTES,
    "hashed_bytes": MAX_HASH_BYTES,
    "largest_hashable_packet": MAX_DATAGRAM,
}
VISIBILITY = (
    "APDU observations are owned native handoffs, not socket transmission. Receive bytes are "
    "observed at the native multiplexer, downstream of the UDP callback and server dispatch. "
    "This is not all UDP ingress, physical IP destination or device-processing timing. "
    "Nominal wait deadlines are call-site references, not actual timer firing observations. "
    "Activity after span/collector retirement is not observed."
)
_CURRENT = ContextVar("bms-read-phase-trace", default=None)


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def unavailable(reason):
    return {
        "profile": PROFILE,
        "state": "unavailable",
        "reason": reason,
        "visibility": VISIBILITY,
        "limits": LIMITS,
        "events": [],
    }


class Collector:
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.started = self.loop.time()
        self.started_at = datetime.now(UTC).isoformat(timespec="microseconds")
        self.active = True
        self.events = []
        self.event_bytes = 0
        self.requests = 0
        self.packets = 0
        self.hashed_bytes = 0
        self.dropped_events = 0
        self.dropped_packets = 0
        self.omitted_hash_bytes = 0
        self.truncated_prefixes = 0
        self.errors = 0
        self.finished_ms = None

    def elapsed(self):
        return round((self.loop.time() - self.started) * 1000, 6)

    def span(self, obj, prop, index, timeout):
        if not self.active:
            return None
        self.requests += 1
        span = Span(self, self.requests)
        span.note(
            "read_started", object=obj, property=prop, array_index=index, timeout_seconds=timeout
        )
        return span

    def note(self, identifier, event, fields):
        if not self.active:
            return
        if len(self.events) >= MAX_EVENTS:
            self.dropped_events += 1
            return
        # Call sites supply only bounded primitive metadata. Never retain SDK objects.
        clean = {}
        for key, value in fields.items():
            if value is None or type(value) in (bool, int):
                clean[key] = value
            elif type(value) is float and math.isfinite(value):
                clean[key] = value
            elif type(value) is str:
                clean[key] = value[:256]
        row = {"read": identifier, "event": event, "elapsed_ms": self.elapsed(), **clean}
        raw = encoded(row)
        # Reserve independently bounded header/counter space; do not borrow native budgets.
        if self.event_bytes + len(raw) + 1 > MAX_BYTES - 4096:
            self.dropped_events += 1
            return
        self.events.append(row)
        self.event_bytes += len(raw) + 1

    def packet(self, identifier, event, data, fields):
        if not self.active:
            return
        if self.packets >= MAX_PACKETS:
            self.dropped_packets += 1
            return
        self.packets += 1
        size = len(data)
        prefix = bytes(data[:PREFIX_BYTES])
        complete = size == len(prefix)
        self.truncated_prefixes += not complete
        digest = None
        if size <= MAX_DATAGRAM and self.hashed_bytes + size <= MAX_HASH_BYTES:
            digest = hashlib.sha256(data).hexdigest()
            self.hashed_bytes += size
        else:
            self.omitted_hash_bytes += size
        # Prefix hex is explicitly bounded and is not subject to the metadata string clipping.
        payload = {
            "packet_bytes": size,
            "prefix_hex": prefix.hex(),
            "prefix_complete": complete,
            "sha256": digest,
            "hash_complete": digest is not None,
        }
        previous = len(self.events)
        self.note(identifier, event, fields)
        if len(self.events) > previous:
            row = self.events[-1]
            before = len(encoded(row))
            candidate = row | payload
            after = len(encoded(candidate))
            if self.event_bytes + after - before <= MAX_BYTES - 4096:
                self.events[-1] = candidate
                self.event_bytes += after - before
            else:
                self.dropped_packets += 1
        else:
            self.dropped_packets += 1

    def close(self):
        if self.active:
            self.active = False
            try:
                self.finished_ms = self.elapsed()
            except BaseException:
                self.finished_ms = None
                self.errors += 1

    def freeze(self):
        self.close()
        result = {
            "profile": PROFILE,
            "state": "truncated"
            if (
                self.dropped_events
                or self.dropped_packets
                or self.omitted_hash_bytes
                or self.truncated_prefixes
                or self.errors
            )
            else "complete",
            "started_at": self.started_at,
            "finished_elapsed_ms": self.finished_ms,
            "visibility": VISIBILITY,
            "limits": dict(LIMITS),
            "counts": {
                "reads": self.requests,
                "retained_events": len(self.events),
                "packet_prefix_attempts": self.packets,
                "hashed_bytes": self.hashed_bytes,
                "dropped_events": self.dropped_events,
                "dropped_packets": self.dropped_packets,
                "omitted_hash_bytes": self.omitted_hash_bytes,
                "truncated_prefixes": self.truncated_prefixes,
                "observation_errors": self.errors,
            },
            "events": list(self.events),
        }
        # A serialization failure/limit can omit diagnostics, never native core bytes.
        if len(encoded(result)) > MAX_BYTES:
            return unavailable("Trace could not fit its independent encoded-byte bound.")
        return result


class Span:
    def __init__(self, collector, identifier):
        self.collector, self.identifier, self.active = collector, identifier, True

    def note(self, event, **fields):
        if self.active:
            self.collector.note(self.identifier, event, fields)

    def packet(self, event, data, **fields):
        if self.active:
            self.collector.packet(self.identifier, event, data, fields)

    def close(self):
        self.active = False


def _error(span):
    try:
        if span.collector.active:
            span.collector.errors += 1
    except BaseException:
        pass


def observe(span, event, **fields):
    if span is not None:
        try:
            span.note(event, **fields)
        except BaseException:
            _error(span)


def observe_packet(span, event, data, **fields):
    if span is not None:
        try:
            span.packet(event, data, **fields)
        except BaseException:
            _error(span)


def handoff(span, packet):
    if span is not None:
        try:
            # BACpypes3 ConfirmedRequestPDU.encode creates a new PDU; native input stays intact.
            span.packet(
                "native_apdu_handoff",
                packet.encode().pduData,
                invoke_id=packet.apduInvokeID,
                service=packet.apduService,
            )
        except BaseException:
            _error(span)


def start_span(obj, prop, index, timeout):
    collector = _CURRENT.get()
    if collector is None:
        return None
    try:
        return collector.span(obj, prop, index, timeout)
    except BaseException:
        try:
            collector.errors += 1
        except BaseException:
            pass
        return None


def retire(span, **fields):
    if span is not None:
        observe(span, "read_retired", **fields)
        try:
            span.close()
        except BaseException:
            _error(span)
        finally:
            # Even a diagnostic cleanup failure cannot retain callback authority.
            span.active = False


@contextmanager
def capture():
    try:
        collector = Collector()
    except BaseException:
        collector = None
    token = _CURRENT.set(collector)
    try:
        yield collector
    finally:
        _CURRENT.reset(token)
        if collector is not None:
            try:
                collector.close()
            except BaseException:
                collector.errors += 1
            finally:
                collector.active = False


def freeze(collector):
    if collector is None:
        return unavailable("Trace collector initialization was unavailable.")
    try:
        return collector.freeze()
    except BaseException:
        return unavailable("Trace finalization was unavailable.")


def multiplexer_packet(span, packet):
    if span is not None:
        try:
            span.packet(
                "multiplexer_callback_enter", packet.pduData, next_hop=str(packet.pduSource)
            )
        except BaseException:
            _error(span)


def wait_started(span, timeout):
    if span is not None:
        try:
            span.note(
                "outer_wait_enter",
                timeout_seconds=timeout,
                nominal_deadline_elapsed_ms=round(span.collector.elapsed() + timeout * 1000, 6),
            )
        except BaseException:
            _error(span)
