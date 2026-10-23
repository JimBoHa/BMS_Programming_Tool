"""Real direct/routed UDP core evidence remains separate from opt-in diagnostics."""

import asyncio
import hashlib
import json

import pytest
from bms_tool import read_phase_trace as trace
from bms_tool.app import create_app
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from tests.test_connections import free_udp
from tests.test_point_status import make_point_peer, options
from tests.test_schedule_inventory import retired, verify_hash


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_diagnostic_core_is_exact_existing_export_and_only_existing_reads(tmp_path, routed):
    app = create_app(tmp_path)
    peer = await make_point_peer(routed=routed)
    raw_requests = []
    original = peer.datagram_received

    def receive(data, source):
        raw_requests.append(bytes(data))
        original(data, source)

    peer.datagram_received = receive
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            service = app.state.point_status
            original_limits = service.status()["limits"]
            response = await client.post(
                "/api/bacnet/point-status/read-diagnostics",
                headers=headers,
                json=options(peer, object_ids=["analog-input,1"]),
            )
            assert response.status_code == 200, response.text
            envelope = response.json()
            assert envelope["format"] == "bms.native-read-diagnostic-envelope/1"
            core = envelope["core_report_json"].encode()
            assert hashlib.sha256(core).hexdigest() == envelope["core_report_sha256"]
            report = json.loads(core)
            assert report["complete"] and report["id"] == envelope["core_report_id"]
            verify_hash(report)
            assert "trace" not in core.decode() and "diagnostic_envelope" not in core.decode()
            count = len(peer.requests)
            exported = await client.post(
                "/api/bacnet/point-status/export", headers=headers, json={"id": report["id"]}
            )
            assert exported.content == core and len(peer.requests) == count
            assert service.detail(report["id"]) == report
            assert service.status()["limits"] == original_limits
            details = envelope["trace"]
            assert details["profile"] == trace.PROFILE and details["state"] == "complete"
            assert len(trace.encoded(details)) <= 65536
            events = details["events"]
            handoffs = [event for event in events if event["event"] == "native_apdu_handoff"]
            assert len(handoffs) == len(peer.requests) == len(raw_requests)
            offset = 11 if routed else 6
            assert [bytes.fromhex(event["prefix_hex"]) for event in handoffs] == [
                packet[offset:] for packet in raw_requests
            ]
            assert all(event["prefix_complete"] and event["hash_complete"] for event in handoffs)
            assert all(
                event["sha256"] == hashlib.sha256(packet[offset:]).hexdigest()
                for event, packet in zip(handoffs, raw_requests, strict=True)
            )
            assert any(event["event"] == "owned_future_done_callback" for event in events)
            assert any(
                event["event"] == "candidate_classification"
                and event["reason"] == "retained_matching_candidate"
                for event in events
            )
            assert any(event["event"] == "read_retired" for event in events)
            assert "not socket transmission" in details["visibility"]
            assert "not all UDP ingress" in details["visibility"]
            retired(app.state.bacnet)
            # Default endpoint still returns its ordinary native report, not an envelope.
            peer.requests.clear()
            raw_requests.clear()
            ordinary = await client.post(
                "/api/bacnet/point-status/read",
                headers=headers,
                json=options(
                    peer, operation_id="ordinary_after_trace", object_ids=["analog-input,1"]
                ),
            )
            old = ordinary.json()
            verify_hash(old)
            assert old["profile"] == report["profile"] and "trace" not in old
            assert len(peer.requests) == count
    finally:
        await app.state.point_status.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)


@pytest.mark.parametrize(
    "mode", ["dropped", "wrong-invoke", "observer-error", "exhausted", "preparation-error"]
)
async def test_incomplete_or_unavailable_trace_never_changes_core_guards(
    tmp_path, monkeypatch, mode
):
    app = create_app(tmp_path)
    peer = await make_point_peer()
    if mode == "dropped":
        peer.hold_property = "reliability"
    if mode == "wrong-invoke":
        peer.rogue = peer.transport
        peer.rogue_kind = "wrong_invoke"
    if mode == "observer-error":

        def broken(*args, **kwargs):
            raise RuntimeError("Deliberate diagnostic failure")

        monkeypatch.setattr(trace.Collector, "note", broken)
    if mode == "exhausted":
        monkeypatch.setattr(trace, "MAX_EVENTS", 1)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            app.state.point_status.timeout = 0.1
            app.state.point_status.request_gap = 0
            if mode == "preparation-error":

                async def missing(*args, **kwargs):
                    raise RuntimeError("Deliberate device cache failure")

                monkeypatch.setattr(
                    app.state.bacnet.app.asap.device_info_cache, "get_device_info", missing
                )
            response = await client.post(
                "/api/bacnet/point-status/read-diagnostics",
                headers=headers,
                json=options(peer, object_ids=["analog-input,1"]),
            )
            assert response.status_code == 200, response.text
            envelope = response.json()
            report = json.loads(envelope["core_report_json"])
            verify_hash(report)
            observed = envelope["trace"]
            events = observed["events"]
            if mode == "dropped":
                assert (
                    not report["complete"]
                    and report["objects"][0]["properties"]["reliability"]["status"] == "timeout"
                )
                assert peer.requests.count(("analog-input,1", "reliability", None)) == 1
                assert any(
                    e["event"] == "exchange_exception" and e["exception"] == "CancelledError"
                    for e in events
                )
            elif mode == "preparation-error":
                assert not report["identity_verified"] and not peer.requests
                assert not any(e["event"] == "native_apdu_handoff" for e in events)
            else:
                assert report["complete"]
                if mode == "wrong-invoke":
                    assert any(
                        e["event"] == "candidate_classification"
                        and e["reason"] == "unrelated_invoke"
                        for e in events
                    )
                    assert report["read_budget"]["ignored_transport_candidates"] == 0
                elif mode == "observer-error":
                    assert observed["counts"]["observation_errors"] > 0
                else:
                    assert (
                        observed["state"] == "truncated"
                        and observed["counts"]["dropped_events"] > 0
                    )
            retired(app.state.bacnet)
    finally:
        await app.state.point_status.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)


async def test_diagnostic_render_failure_returns_original_core_response_without_another_read(
    tmp_path, monkeypatch
):
    import bms_tool.app as module

    app = create_app(tmp_path)
    peer = await make_point_peer()

    def broken(*args, **kwargs):
        raise RuntimeError("Diagnostic freeze unavailable")

    monkeypatch.setattr(module, "freeze_read_trace", broken)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            response = await client.post(
                "/api/bacnet/point-status/read-diagnostics",
                headers=headers,
                json=options(peer, object_ids=["analog-input,1"]),
            )
            assert (
                response.status_code == 200
                and response.headers["X-Studio-Diagnostics"] == "unavailable"
            )
            report = response.json()
            verify_hash(report)
            assert report["complete"]
            count = len(peer.requests)
            exported = await client.post(
                "/api/bacnet/point-status/export", headers=headers, json={"id": report["id"]}
            )
            assert response.content == exported.content and len(peer.requests) == count
    finally:
        await app.state.point_status.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)


def test_new_endpoint_uses_existing_session_admission_and_request_model(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        body = {
            "operation_id": "read_trace_no_interface",
            "address": "127.0.0.1:47808",
            "device": "device,42",
            "object_ids": ["analog-input,1"],
        }
        assert (
            client.post("/api/bacnet/point-status/read-diagnostics", json=body).status_code == 403
        )
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/bacnet/point-status/read-diagnostics", headers=headers, json=body
            ).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]
        assert client.get("/api/bacnet/point-status/profile").json()["reports"] == []


@pytest.mark.parametrize("ending", ["cancel", "interface-change"])
async def test_cancel_or_interface_change_retires_trace_and_preserves_another_owner(
    tmp_path, ending
):
    first = create_app(tmp_path / "first")
    second = create_app(tmp_path / "second")
    peer = await make_point_peer()
    other = await make_point_peer()
    peer.hold_property = "reliability"
    try:
        async with (
            AsyncClient(transport=ASGITransport(app=first), base_url="http://127.0.0.1") as client,
            AsyncClient(
                transport=ASGITransport(app=second), base_url="http://127.0.0.1"
            ) as separate,
        ):
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            other_headers = {"X-Studio-Token": (await separate.get("/api/session")).json()["token"]}
            for caller, identity in ((client, headers), (separate, other_headers)):
                await caller.post(
                    "/api/bacnet/connect",
                    headers=identity,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                )
            native = first.state.bacnet.app
            task = asyncio.create_task(
                client.post(
                    "/api/bacnet/point-status/read-diagnostics",
                    headers=headers,
                    json=options(
                        peer, object_ids=["analog-input,1"], operation_id="owned_trace_cancel"
                    ),
                )
            )
            await asyncio.wait_for(peer.entered.wait(), 1)
            other_task = asyncio.create_task(
                separate.post(
                    "/api/bacnet/point-status/read",
                    headers=other_headers,
                    json=options(
                        other, object_ids=["analog-input,1"], operation_id="other_untraced_owner"
                    ),
                )
            )
            if ending == "cancel":
                await client.post(
                    "/api/bacnet/point-status/cancel",
                    headers=headers,
                    json={"operation_id": "owned_trace_cancel"},
                )
            else:
                first.state.bacnet.close()
            response = await task
            assert response.status_code == 200, response.text
            original = response.content
            envelope = response.json()
            report = json.loads(envelope["core_report_json"])
            verify_hash(report)
            assert report["status"] == ("cancelled" if ending == "cancel" else "interface_changed")
            assert not report["complete"]
            independent = (await other_task).json()
            assert independent["complete"] and "trace" not in independent
            peer.release.set()
            await asyncio.sleep(0.03)
            assert response.content == original
            assert not native.asap.clientTransactions and not any(native._requests.values())
            retired(second.state.bacnet)
    finally:
        await first.state.point_status.close()
        await second.state.point_status.close()
        first.state.bacnet.close()
        second.state.bacnet.close()
        peer.close()
        other.close()
        await asyncio.sleep(0.03)


@pytest.mark.parametrize("failure", ["initialization", "oversized-diagnostics"])
async def test_trace_initialization_or_wrapper_capacity_does_not_spend_native_budgets(
    tmp_path, monkeypatch, failure
):
    import bms_tool.app as module

    app = create_app(tmp_path)
    peer = await make_point_peer()
    if failure == "initialization":

        def broken(*args, **kwargs):
            raise RuntimeError("Diagnostic initialization unavailable")

        monkeypatch.setattr(trace.Collector, "__init__", broken)
    else:
        monkeypatch.setattr(
            module,
            "freeze_read_trace",
            lambda _: {
                "profile": trace.PROFILE,
                "state": "complete",
                "events": [{"detail": "x" * (5 * 1024 * 1024)}],
            },
        )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            limits = app.state.point_status.status()["limits"]
            response = await client.post(
                "/api/bacnet/point-status/read-diagnostics",
                headers=headers,
                json=options(peer, object_ids=["analog-input,1"]),
            )
            envelope = response.json()
            report = json.loads(envelope["core_report_json"])
            verify_hash(report)
            assert report["complete"] and envelope["trace"]["state"] == "unavailable"
            assert app.state.point_status.status()["limits"] == limits
            assert len(response.content) <= 4 * 1024 * 1024 + 65536 + 4096
            count = len(peer.requests)
            exported = await client.post(
                "/api/bacnet/point-status/export", headers=headers, json={"id": report["id"]}
            )
            assert (
                envelope["core_report_json"].encode() == exported.content
                and len(peer.requests) == count
            )
    finally:
        await app.state.point_status.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)
