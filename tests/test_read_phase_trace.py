"""Independent bounds and retired-observer laws; no field transports."""

import copy
import hashlib
import json

import pytest
from bms_tool import read_phase_trace as trace


async def test_opt_in_context_and_retired_callbacks_cannot_mutate_frozen_trace():
    assert trace.start_span("device,42", "object-name", None, 0.1) is None
    with trace.capture() as collector:
        span = trace.start_span("device,42", "object-name", None, 0.1)
        trace.observe(span, "phase")
        trace.observe_packet(span, "packet", b"actual bytes")
        trace.retire(span, phase_status="ok")
        before = copy.deepcopy(collector.events)
        trace.observe(span, "late_callback")
        trace.observe_packet(span, "late_packet", b"late")
        assert collector.events == before
    frozen = trace.freeze(collector)
    original = trace.encoded(frozen)
    trace.observe(span, "after_collector_close")
    assert trace.encoded(trace.freeze(collector)) == original
    assert trace.start_span("device,42", "object-name", None, 0.1) is None
    packet = next(row for row in frozen["events"] if row["event"] == "packet")
    assert bytes.fromhex(packet["prefix_hex"]) == b"actual bytes"
    assert packet["sha256"] == hashlib.sha256(b"actual bytes").hexdigest()
    assert packet["prefix_complete"] and packet["hash_complete"]


async def test_fixed_event_prefix_hash_and_encoded_limits_are_independent():
    with trace.capture() as collector:
        span = trace.start_span("device,42", "object-name", None, 0.1)
        data = b"x" * 16384
        for index in range(1000):
            trace.observe_packet(span, "packet", data, sequence=index)
            trace.observe(span, "phase", detail='"\\\n' * 1000)
    result = trace.freeze(collector)
    assert len(trace.encoded(result)) <= 65536
    assert len(result["events"]) <= 256
    packets = [r for r in result["events"] if "prefix_hex" in r]
    assert len(packets) <= 32 and all(len(bytes.fromhex(r["prefix_hex"])) <= 512 for r in packets)
    assert result["counts"]["hashed_bytes"] <= 256 * 1024
    assert result["counts"]["omitted_hash_bytes"] > 0
    assert result["counts"]["dropped_events"] > 0 and result["counts"]["dropped_packets"] > 0
    assert result["counts"]["truncated_prefixes"] > 0 and result["state"] == "truncated"
    assert all(not r["prefix_complete"] for r in packets)


async def test_dropped_packet_does_not_replace_an_earlier_packet(monkeypatch):
    monkeypatch.setattr(trace, "MAX_EVENTS", 2)
    with trace.capture() as collector:
        span = trace.start_span("device,42", "object-name", None, 0.1)
        trace.observe_packet(span, "packet", b"first")
        first = copy.deepcopy(collector.events[-1])
        trace.observe_packet(span, "packet", b"second")
        assert collector.events[-1] == first
    assert trace.freeze(collector)["counts"]["dropped_packets"] == 1


async def test_nested_contexts_do_not_share_owner_events():
    with trace.capture() as first:
        outer = trace.start_span("device,1", "object-name", None, 0.1)
        with trace.capture() as second:
            inner = trace.start_span("device,2", "object-name", None, 0.1)
            trace.observe(inner, "inner_only")
        trace.observe(outer, "outer_only")
    assert "inner_only" not in json.dumps(trace.freeze(first))
    assert "outer_only" not in json.dumps(trace.freeze(second))


async def test_erroring_observer_and_finalizer_remain_diagnostic_only(monkeypatch):
    with trace.capture() as collector:
        span = trace.start_span("device,1", "object-name", None, 0.1)

        def broken(*args, **kwargs):
            raise RuntimeError("Diagnostic observer deliberately unavailable")

        monkeypatch.setattr(span, "note", broken)
        trace.observe(span, "phase")
        assert collector.errors == 1
    monkeypatch.setattr(collector, "freeze", broken)
    assert trace.freeze(collector)["state"] == "unavailable"


async def test_wire_callback_calls_original_once_and_restores_foreign_owner():
    from types import SimpleNamespace

    from bacpypes3.pdu import PDU
    from bms_tool.property_evidence import PropertyEvidence, ReadBudget
    from bms_tool.scoped_hooks import ScopedAttribute

    calls = []

    async def original(packet):
        calls.append(packet)
        raise RuntimeError("Original handler error")

    mux = SimpleNamespace(confirmation=original)
    transport = SimpleNamespace(get_extra_info=lambda key: ("127.0.0.1", 50000))
    layer = SimpleNamespace(multiplexer=mux, server=SimpleNamespace(local_transport=transport))
    session = {
        "app": SimpleNamespace(
            nsap=SimpleNamespace(local_adapter=SimpleNamespace(clientPeer=layer))
        ),
        "target": "127.0.0.1:50001",
    }
    reader = PropertyEvidence(None)
    packet = PDU(b"\x81")
    with trace.capture() as collector:
        span = trace.start_span("device,42", "object-name", None, 0.1)
        context = reader.wire(session, ReadBudget(), SimpleNamespace(apduInvokeID=1), observer=span)
        await context.__aenter__()
        callback = mux.confirmation
        with pytest.raises(RuntimeError, match="Original handler error"):
            await callback(packet)
        assert calls == [packet]
        foreign_calls = []

        async def foreign(value):
            foreign_calls.append(value)
            return await callback(value)

        hook = ScopedAttribute(mux, "confirmation", foreign)
        await context.__aexit__(None, None, None)
        trace.retire(span, phase_status="protocol_error")
        before = trace.encoded(trace.freeze(collector))
        assert mux.confirmation is foreign
        with pytest.raises(RuntimeError, match="Original handler error"):
            await mux.confirmation(packet)
        assert calls == [packet, packet] and foreign_calls == [packet]
        assert trace.encoded(trace.freeze(collector)) == before
        hook.close()
        assert mux.confirmation is original
    events = json.loads(before)["events"]
    assert sum(e["event"] == "native_handler_exception" for e in events) == 1


async def test_failed_diagnostic_span_close_still_retires_observer(monkeypatch):
    with trace.capture() as collector:
        span = trace.start_span("device,42", "object-name", None, 0.1)

        def broken():
            raise RuntimeError("Diagnostic span cleanup unavailable")

        monkeypatch.setattr(span, "close", broken)
        trace.retire(span, phase_status="ok")
        before = copy.deepcopy(collector.events)
        trace.observe(span, "late_after_cleanup_error")
        assert collector.events == before
        assert collector.errors == 1


async def test_clock_failure_during_close_is_explicit_and_cannot_leave_active_capture(monkeypatch):
    with trace.capture() as collector:
        trace.start_span("device,42", "object-name", None, 0.1)

        def broken():
            raise RuntimeError("Diagnostic clock unavailable")

        monkeypatch.setattr(collector, "elapsed", broken)
    assert collector.active is False
    result = trace.freeze(collector)
    assert result["state"] == "truncated"
    assert result["counts"]["observation_errors"] == 1
    assert result["finished_elapsed_ms"] is None


async def test_failing_collector_close_cannot_leave_callback_authority(monkeypatch):
    with trace.capture() as collector:
        span = trace.start_span("device,42", "object-name", None, 0.1)

        def broken():
            raise RuntimeError("Diagnostic collector close unavailable")

        monkeypatch.setattr(collector, "close", broken)
    assert collector.active is False
    original = copy.deepcopy(collector.events)
    trace.observe(span, "late_after_collector_close_error")
    assert collector.events == original
    assert trace.freeze(collector)["state"] == "unavailable"
