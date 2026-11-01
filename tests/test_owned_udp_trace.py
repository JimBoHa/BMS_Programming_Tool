"""Real owned UDP callback observations never decide native read acceptance."""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager

import pytest
from bms_tool import ipv4_ingress as ingress
from bms_tool import read_phase_trace as trace
from bms_tool.app import create_app
from httpx import ASGITransport, AsyncClient

from .test_connections import free_udp
from .test_ipv4_ingress import shared_socket
from .test_schedule_diagnostics import FOCUS, body
from .test_schedule_inventory import make_peer, retired, verify_hash


@asynccontextmanager
async def network(tmp_path, *, routed=False, shared=False, hold=False):
    app = create_app(tmp_path)
    peer = await make_peer(routed=routed)
    app.state.schedule_inventory.request_gap = 0
    if hold:
        peer.hold_property = FOCUS["property"]
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            response = await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            assert response.status_code == 200, response.text
            if shared:
                shared_socket(app.state.bacnet)
            owner = app.state.bacnet.app._bms_ipv4_ingress_hooks[0]
            yield app, peer, client, headers, owner
    finally:
        await app.state.schedule_inventory.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)


async def read(client, headers, peer, *, enabled=True):
    response = await client.post(
        "/api/bacnet/schedules/read-diagnostics",
        headers=headers,
        json=body(peer) | {"include_udp_ingress": enabled},
    )
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["include_udp_ingress"] is enabled
    core = document["core_report_json"].encode()
    assert hashlib.sha256(core).hexdigest() == document["core_report_sha256"]
    report = json.loads(core)
    verify_hash(report)
    count = len(peer.requests)
    exported = await client.post(
        "/api/bacnet/schedules/export", headers=headers, json={"id": report["id"]}
    )
    assert exported.content == core and len(peer.requests) == count
    assert "udp_ingress_requested" not in report
    return document, report


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
@pytest.mark.parametrize("shared", [False, True], ids=["native-posix", "shared-socket-contract"])
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "opt-in"])
async def test_exact_callback_bytes_and_existing_source_proof_are_independent(
    tmp_path, routed, shared, enabled
):
    async with network(tmp_path, routed=routed, shared=shared) as (
        app,
        peer,
        client,
        headers,
        owner,
    ):
        outgoing = []
        send = peer.transport.sendto

        def observed(data, source):
            outgoing.append(bytes(data))
            send(data, source)

        peer.transport.sendto = observed
        limits = app.state.schedule_inventory.status()["limits"]
        document, report = await read(client, headers, peer, enabled=enabled)
        assert report["complete"] and len(peer.requests) == len(outgoing) == 28
        assert report["ignored_transport_candidates"] == 0 and not peer.errors
        assert app.state.schedule_inventory.status()["limits"] == limits
        details = document["trace"]
        assert details["state"] == "complete" and details["udp_ingress_requested"] is enabled
        events = details["events"]
        packets = [e for e in events if e["event"] == "owned_udp_callback_enter"]
        assert len(packets) == int(enabled)
        if enabled:
            row = report["objects"][1]["properties"][FOCUS["property"]]
            expected = next(p for p in outgoing if p[11 if routed else 7] == row["invoke_id"])
            packet = packets[0]
            assert bytes.fromhex(packet["prefix_hex"]) == expected
            assert packet["sha256"] == hashlib.sha256(expected).hexdigest()
            assert packet["hash_complete"] and packet["prefix_complete"]
            assert packet["peer_ip"] == "127.0.0.1" and packet["peer_port"] == int(
                peer.endpoint.rsplit(":", 1)[1]
            )
            assert (
                packet["local_ip"] == owner.endpoint[0]
                and packet["local_port"] == owner.endpoint[1]
            )
            assert "not a matched response" in packet["association"]
            assert next(
                i for i, e in enumerate(events) if e["event"] == "owned_udp_callback_enter"
            ) < next(i for i, e in enumerate(events) if e["event"] == "multiplexer_callback_enter")
            assert "not all network UDP" in details["visibility"]
            assert owner.valid()  # the original provenance hook was never replaced
            if shared:
                assert (
                    row["transport_evidence"]["receive_provenance"]["physical_ip_destination"]
                    is None
                )
                assert (
                    "shared IPv4 socket" in row["transport_evidence"]["receive_provenance"]["basis"]
                )
        assert not owner.udp_observers
        retired(app.state.bacnet)


@pytest.mark.parametrize("shared", [False, True], ids=["native-posix", "shared-socket-contract"])
async def test_reflected_datagram_is_observed_before_native_pre_multiplexer_discard(
    tmp_path, shared
):
    async with network(tmp_path, shared=shared, hold=True) as (app, peer, client, headers, owner):
        pending = asyncio.create_task(
            client.post(
                "/api/bacnet/schedules/read-diagnostics",
                headers=headers,
                json=body(peer) | {"include_udp_ingress": True},
            )
        )
        await asyncio.wait_for(peer.entered.wait(), 1)
        assert len(owner.udp_observers) == 1
        span = next(iter(owner.udp_observers.values()))
        raw = b"\x81\x0a\x00\x04"
        # Real local UDP reflection. The pinned SDK explicitly discards a PDU
        # from its own local_address before calling the multiplexer.
        owner.transport.sendto(raw, owner.endpoint)
        async with asyncio.timeout(0.5):
            while not any(
                e["event"] == "owned_udp_callback_enter" and e.get("prefix_hex") == raw.hex()
                for e in span.collector.events
            ):
                await asyncio.sleep(0)
        peer.release.set()
        response = await pending
        assert response.status_code == 200, response.text
        document = response.json()
        report = json.loads(document["core_report_json"])
        verify_hash(report)
        assert report["complete"] and len(peer.requests) == 28 and not peer.errors
        events = document["trace"]["events"]
        reflected = [
            e
            for e in events
            if e["event"] == "owned_udp_callback_enter" and e.get("prefix_hex") == raw.hex()
        ]
        assert len(reflected) == 1 and reflected[0]["peer_port"] == owner.endpoint[1]
        assert not any(
            e["event"] == "multiplexer_callback_enter" and e.get("prefix_hex") == raw.hex()
            for e in events
        )
        assert any(e.get("reason") == "retained_matching_candidate" for e in events)
        assert not owner.udp_observers
        retired(app.state.bacnet)


@pytest.mark.parametrize(
    "fault",
    ["observer-error", "callback-error", "capacity", "packets-full", "collector-unavailable"],
)
async def test_observer_failure_and_independent_exhaustion_preserve_native_core(
    tmp_path, monkeypatch, fault
):
    if fault == "observer-error":

        def broken(*args, **kwargs):
            raise RuntimeError("Deliberate packet observation failure")

        monkeypatch.setattr(trace.Collector, "packet", broken)
    elif fault == "callback-error":

        def broken(*args, **kwargs):
            raise RuntimeError("Deliberate callback observation failure")

        monkeypatch.setattr(ingress, "udp_callback", broken)
    elif fault == "capacity":
        monkeypatch.setattr(ingress, "MAX_UDP_OBSERVERS", 0)
    elif fault == "packets-full":
        monkeypatch.setattr(trace, "MAX_PACKETS", 0)
    else:

        def broken(*args, **kwargs):
            raise RuntimeError("Deliberate collector initialization failure")

        monkeypatch.setattr(trace, "Collector", broken)
    async with network(tmp_path, shared=True) as (app, peer, client, headers, owner):
        document, report = await read(client, headers, peer)
        assert report["complete"] and len(peer.requests) == 28 and not peer.errors
        details = document["trace"]
        if fault == "collector-unavailable":
            assert details["state"] == "unavailable" and not owner.udp_observers
            retired(app.state.bacnet)
            return
        assert details["state"] == "truncated"
        assert (
            details["counts"]["observation_errors"] > 0 or details["counts"]["dropped_packets"] > 0
        )
        if fault == "capacity":
            assert any(e.get("reason") == "owned_udp_observer_capacity" for e in details["events"])
        assert len(trace.encoded(details)) <= 65536 and len(details["events"]) <= 256
        assert not owner.udp_observers and owner.valid()
        retired(app.state.bacnet)


@pytest.mark.parametrize("ending", ["cancel", "interface-change"])
async def test_registration_and_span_retire_before_late_callback_can_mutate_trace(tmp_path, ending):
    async with network(tmp_path, hold=True) as (app, peer, client, headers, owner):
        native = app.state.bacnet.app
        pending = asyncio.create_task(
            client.post(
                "/api/bacnet/schedules/read-diagnostics",
                headers=headers,
                json=body(peer) | {"include_udp_ingress": True},
            )
        )
        await asyncio.wait_for(peer.entered.wait(), 1)
        span = next(iter(owner.udp_observers.values()))
        if ending == "cancel":
            cancelled = await client.post(
                "/api/bacnet/schedules/cancel",
                headers=headers,
                json={"operation_id": "schedule_test_operation"},
            )
            assert cancelled.json()["cancel_requested"]
        else:
            app.state.bacnet.close()
        response = await pending
        assert response.status_code == 200, response.text
        report = json.loads(response.json()["core_report_json"])
        verify_hash(report)
        assert not report["complete"] and report["status"] in ("cancelled", "interface_changed")
        assert not owner.udp_observers and not span.active
        before = trace.encoded(trace.freeze(span.collector))
        peer.release.set()
        trace.udp_callback(span, b"late callback", ("127.0.0.1", 55555), owner.endpoint)
        await asyncio.sleep(0.03)
        assert trace.encoded(trace.freeze(span.collector)) == before
        assert not native._requests and not native.asap.clientTransactions and not peer.errors


@pytest.mark.parametrize("value", [1, 0, "true", "false", [], {}])
async def test_optional_udp_flag_is_strict_and_does_not_issue_native_reads(tmp_path, value):
    async with network(tmp_path) as (app, peer, client, headers, owner):
        response = await client.post(
            "/api/bacnet/schedules/read-diagnostics",
            headers=headers,
            json=body(peer) | {"include_udp_ingress": value},
        )
        assert response.status_code == 422
        assert not peer.requests and not owner.udp_observers
        assert app.state.schedule_inventory.status()["reports"] == []


async def test_one_observer_retirement_preserves_another_socket_observer(tmp_path):
    async with network(tmp_path) as (app, peer, _client, _headers, owner):
        native = app.state.bacnet.app
        with trace.capture(include_udp_ingress=True) as first:
            first_span = trace.start_span("schedule,1", "present-value", None, 1)
            with ingress.observe_owned_udp(native, owner.layer, first_span):
                with trace.capture(include_udp_ingress=True) as second:
                    second_span = trace.start_span("schedule,2", "present-value", None, 1)
                    with ingress.observe_owned_udp(native, owner.layer, second_span):
                        assert len(owner.udp_observers) == 2
                        owner.transport.sendto(b"\x81\x0a\x00\x04", owner.endpoint)
                        async with asyncio.timeout(0.5):
                            while not any(
                                e["event"] == "owned_udp_callback_enter" for e in second.events
                            ):
                                await asyncio.sleep(0)
                    trace.retire(second_span)
                frozen = trace.encoded(trace.freeze(second))
                assert list(owner.udp_observers.values()) == [first_span]
                owner.transport.sendto(b"\x81\x0a\x00\x04", owner.endpoint)
                async with asyncio.timeout(0.5):
                    while sum(e["event"] == "owned_udp_callback_enter" for e in first.events) < 2:
                        await asyncio.sleep(0)
                assert trace.encoded(trace.freeze(second)) == frozen
            trace.retire(first_span)
        assert not owner.udp_observers and owner.valid() and not peer.requests
