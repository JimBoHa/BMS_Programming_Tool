"""Focused observations retain original Schedule evidence and read admission laws."""

import asyncio
import hashlib
import json

import pytest
from bms_tool import read_phase_trace as trace
from bms_tool.app import create_app
from bms_tool.native_schedule_library import NativeScheduleLibrary
from bms_tool.schedule_diagnostics import ScheduleDiagnosticRequest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_connections import free_udp
from .test_schedule_inventory import make_peer, options, retired, verify_hash

FOCUS = {
    "object_id": "schedule,1",
    "property": "list-of-object-property-references",
    "array_index": None,
}


def body(peer, focus=None, **changes):
    return {"request": options(peer, **changes), "trace_focus": focus or FOCUS}


def signed(peer):
    original = peer.value

    def value(obj, prop, index):
        if str(obj) == "schedule,1":
            if prop in ("present-value", "schedule-default"):
                return bytes.fromhex("31ff")
            if prop == "weekly-schedule" and index:
                return bytes.fromhex("0eb40800000031ff0f")
            if prop == "exception-schedule" and index:
                period = "0e0cff021dff0f" if index == 1 else "1c01800002"
                return bytes.fromhex(period + "2eb4091e000031ff2f3908")
        return original(obj, prop, index)

    peer.value = value


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
@pytest.mark.parametrize("missing", [False, True], ids=["complete", "dropped-reference"])
async def test_original_signed_reference_shape_has_exact_focused_trace_and_core(
    tmp_path, routed, missing
):
    app = create_app(tmp_path / "app")
    peer = await make_peer(routed=routed)
    signed(peer)
    raw = []
    receive = peer.datagram_received

    def observed(data, source):
        raw.append(bytes(data))
        receive(data, source)

    peer.datagram_received = observed
    if missing:
        peer.drop_reference = ("schedule,1", FOCUS["property"], None)
    service = app.state.schedule_inventory
    service.timeout, service.operation_timeout, service.request_gap = 0.2, 5, 0
    limits = service.status()["limits"]
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
                "/api/bacnet/schedules/read-diagnostics", headers=headers, json=body(peer)
            )
            assert response.status_code == 200, response.text
            document = response.json()
            assert document["format"] == "bms.native-read-diagnostic-envelope/1"
            assert document["trace_focus"] == FOCUS
            core = document["core_report_json"].encode()
            assert hashlib.sha256(core).hexdigest() == document["core_report_sha256"]
            report = json.loads(core)
            assert report["id"] == document["core_report_id"] and report["complete"] is (
                not missing
            )
            verify_hash(report)
            assert "trace" not in report and "trace_focus" not in report
            row = report["objects"][1]["properties"][FOCUS["property"]]
            assert row["status"] == ("timeout" if missing else "ok")
            assert row["request_diagnostics"]["request_timeout_seconds"] == 0.2
            details = document["trace"]
            assert details["state"] == "complete" and details["counts"]["reads"] == 1
            assert details["counts"]["dropped_events"] == 0
            starts = [e for e in details["events"] if e["event"] == "read_started"]
            assert [(e["object"], e["property"], e["array_index"]) for e in starts] == [
                tuple(FOCUS.values())
            ]
            handoffs = [e for e in details["events"] if e["event"] == "native_apdu_handoff"]
            assert len(handoffs) == 1
            index = peer.requests.index(("schedule,1", FOCUS["property"], None))
            assert index > 5 and len(raw) == len(peer.requests) == report["requests"]
            expected = raw[index][11 if routed else 6 :]
            assert bytes.fromhex(handoffs[0]["prefix_hex"]) == expected
            assert handoffs[0]["sha256"] == hashlib.sha256(expected).hexdigest()
            matched = [
                e for e in details["events"] if e.get("reason") == "retained_matching_candidate"
            ]
            assert bool(matched) is (not missing)
            assert peer.requests.count(("schedule,1", FOCUS["property"], None)) == 1
            count = len(peer.requests)
            exported = await client.post(
                "/api/bacnet/schedules/export", headers=headers, json={"id": report["id"]}
            )
            assert exported.content == core and len(peer.requests) == count
            library = NativeScheduleLibrary(tmp_path / "library")
            captured = library._store(core, "imported")
            assert captured["objects"][0]["eligible"] is (not missing)
            assert library.source(captured["id"]) == core
            if missing:
                with pytest.raises(ValueError):
                    library.review(
                        capture_id=captured["id"], object_id="schedule,1", day=1, transitions=[]
                    )
            else:
                assert captured["objects"][0]["native_type"] == "Integer"
            assert not peer.errors and service.status()["limits"] == limits
            retired(app.state.bacnet)
    finally:
        await service.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)


@pytest.mark.parametrize(
    "mode",
    [
        "late-index",
        "not-reached",
        "observer-error",
        "trace-full",
        "render-error",
        "calendar",
        "count-zero",
    ],
)
async def test_trace_failures_never_add_reads_or_change_core_eligibility(
    tmp_path, monkeypatch, mode
):
    app = create_app(tmp_path)
    peer = await make_peer()
    focus = {"object_id": "schedule,1", "property": "exception-schedule", "array_index": 2}
    if mode == "calendar":
        focus = {"object_id": "calendar,1", "property": "date-list", "array_index": None}
    if mode == "count-zero":
        focus = {"object_id": "schedule,1", "property": "weekly-schedule", "array_index": 0}
    if mode == "not-reached":
        focus["array_index"] = 32
    if mode == "observer-error":

        def broken(*args, **kwargs):
            raise RuntimeError("Deliberate diagnostic failure")

        monkeypatch.setattr(trace.Collector, "note", broken)
    if mode == "trace-full":
        monkeypatch.setattr(trace, "MAX_EVENTS", 1)
    if mode == "render-error":
        import bms_tool.app as module

        monkeypatch.setattr(
            module,
            "freeze_read_trace",
            lambda *args: (_ for _ in ()).throw(ValueError("Deliberate wrapper failure")),
        )
    app.state.schedule_inventory.request_gap = 0
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
                "/api/bacnet/schedules/read-diagnostics", headers=headers, json=body(peer, focus)
            )
            assert response.status_code == 200, response.text
            document = response.json()
            if mode == "render-error":
                assert response.headers["X-Studio-Diagnostics"] == "unavailable"
                core = response.content
            else:
                core = document["core_report_json"].encode()
                observed = document["trace"]
                assert observed["counts"]["reads"] == (0 if mode == "not-reached" else 1)
                if mode in ("observer-error", "trace-full"):
                    assert observed["state"] == "truncated"
                elif mode == "late-index":
                    assert observed["state"] == "complete"
                    assert any(e["event"] == "native_apdu_handoff" for e in observed["events"])
                    assert peer.requests[-1] == (
                        focus["object_id"],
                        focus["property"],
                        focus["array_index"],
                    )
                if mode != "not-reached" and mode not in ("observer-error", "trace-full"):
                    starts = [e for e in observed["events"] if e["event"] == "read_started"]
                    assert len(starts) == 1
                    assert starts[0]["object"] == focus["object_id"]
                    assert starts[0]["property"] == focus["property"]
                    assert starts[0]["array_index"] == focus["array_index"]
            report = json.loads(core)
            verify_hash(report)
            assert report["complete"] and len(peer.requests) == 28 and not peer.errors
            count = len(peer.requests)
            exported = await client.post(
                "/api/bacnet/schedules/export", headers=headers, json={"id": report["id"]}
            )
            assert exported.content == core and len(peer.requests) == count
            retired(app.state.bacnet)
    finally:
        await app.state.schedule_inventory.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)


@pytest.mark.parametrize(
    "change",
    [
        {"object_id": "device,42"},
        {"object_id": "schedule,2"},
        {"property": "object-list"},
        {"property": "date-list"},
        {"array_index": 1},
        {"property": "weekly-schedule"},
        {"property": "weekly-schedule", "array_index": 8},
        {"property": "exception-schedule", "array_index": True},
        {"property": "exception-schedule", "array_index": 1.0},
        {"property": "exception-schedule", "array_index": 33},
    ],
)
def test_invalid_or_unselected_focus_is_rejected_before_interface_admission(tmp_path, change):
    with TestClient(create_app(tmp_path)) as client:
        token = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        payload = {
            "request": {
                "operation_id": "diagnostic_admission",
                "address": "127.0.0.1",
                "device": "device,42",
                "object_ids": ["schedule,1"],
            },
            "trace_focus": FOCUS | change,
        }
        assert (
            client.post(
                "/api/bacnet/schedules/read-diagnostics", headers=token, json=payload
            ).status_code
            == 422
        )
        assert client.get("/api/bacnet/schedules/profile").json()["reports"] == []
        assert not client.get("/api/session").json()["field_network_open"]


def test_explicit_selection_session_and_ordinary_endpoint_contract(tmp_path):
    payload = {
        "request": {
            "operation_id": "diagnostic_admission",
            "address": "127.0.0.1",
            "device": "device,42",
            "object_ids": ["schedule,1"],
        },
        "trace_focus": FOCUS,
    }
    ScheduleDiagnosticRequest.model_validate(payload)
    with TestClient(create_app(tmp_path)) as client:
        assert (
            client.post("/api/bacnet/schedules/read-diagnostics", json=payload).status_code == 403
        )
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for selected in (None, [], ["calendar,1"]):
            assert (
                client.post(
                    "/api/bacnet/schedules/read-diagnostics",
                    headers=headers,
                    json=payload | {"request": payload["request"] | {"object_ids": selected}},
                ).status_code
                == 422
            )
        assert (
            client.post("/api/bacnet/schedules/read", headers=headers, json=payload).status_code
            == 422
        )


async def test_filtered_and_unfiltered_nested_observers_keep_separate_ownership():
    with trace.capture(focus=("schedule,1", "weekly-schedule", 0)) as focused:
        for _index in range(1000):
            assert trace.start_span("schedule,1", "weekly-schedule", 1, 0.2) is None
        with trace.capture() as ordinary:
            nested = trace.start_span("calendar,1", "date-list", None, 0.2)
            trace.observe(nested, "nested")
        chosen = trace.start_span("schedule,1", "weekly-schedule", 0, 0.2)
        trace.observe(chosen, "focused")
    result = trace.freeze(focused)
    assert result["counts"]["reads"] == 1 and result["counts"]["dropped_events"] == 0
    assert len(result["events"]) == 2 and "nested" not in trace.encoded(result).decode()
    assert "focused" not in trace.encoded(trace.freeze(ordinary)).decode()


@pytest.mark.parametrize("ending", ["cancel", "interface-change"])
async def test_focused_pending_read_retires_without_replaying_or_observing_late_reply(
    tmp_path, ending
):
    app = create_app(tmp_path)
    peer = await make_peer()
    peer.hold_property = FOCUS["property"]
    app.state.schedule_inventory.request_gap = 0
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
            native = app.state.bacnet.app
            pending = asyncio.create_task(
                client.post(
                    "/api/bacnet/schedules/read-diagnostics", headers=headers, json=body(peer)
                )
            )
            await asyncio.wait_for(peer.entered.wait(), 1)
            if ending == "cancel":
                response = await client.post(
                    "/api/bacnet/schedules/cancel",
                    headers=headers,
                    json={"operation_id": "schedule_test_operation"},
                )
                assert response.json()["cancel_requested"]
            else:
                app.state.bacnet.close()
            response = await pending
            assert response.status_code == 200, response.text
            original = response.content
            document = response.json()
            core = json.loads(document["core_report_json"])
            verify_hash(core)
            assert not core["complete"]
            assert core["status"] in ("cancelled", "interface_changed")
            assert any(e["event"] == "read_retired" for e in document["trace"]["events"])
            count = len(peer.requests)
            peer.release.set()
            await asyncio.sleep(0.03)
            assert response.content == original and len(peer.requests) == count
            assert not native._requests and not native.asap.clientTransactions
            assert not native.nsap.local_adapter.clientPeer.multiplexer.__dict__.get("confirmation")
            assert not peer.errors
    finally:
        await app.state.schedule_inventory.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)
