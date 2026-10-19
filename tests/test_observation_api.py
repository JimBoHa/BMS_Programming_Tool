"""End-to-end local observation API evidence and failure semantics."""

import sqlite3

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.models import Edge, Node, Program
from bms_tool.observability import ObservabilityStore
from bms_tool.storage import Store
from fastapi.testclient import TestClient


def alarm_program():
    return Program(
        id="observed-zone",
        name="Observed zone",
        nodes=[
            Node(id="temperature", kind="Input", params={"default": 70}, unit="°F"),
            Node(id="limited", kind="Slew", params={"rate": 10, "initial": 0}, unit="°F"),
            Node(id="out", kind="Output", unit="°F"),
            Node(id="high", kind="Alarm", label="Zone too hot", params={"limit": 80}, unit="°F"),
            Node(id="alarm_out", kind="Output", value_type="boolean"),
        ],
        edges=[
            Edge(id="rate", source="temperature", target="limited"),
            Edge(id="out", source="limited", target="out"),
            Edge(id="alarm", source="temperature", target="high"),
            Edge(id="alarm_out", source="high", target="alarm_out"),
        ],
    ).model_dump()


def headers(client):
    return {"X-Studio-Token": client.get("/api/session").json()["token"]}


def step(client, token, *, session=None, temperature=90, **changes):
    request = {
        "program": alarm_program(),
        "inputs": {"temperature": temperature},
        "record": True,
        **changes,
    }
    if session is not None:
        request["session"] = session
    response = client.post("/api/simulation/step", json=request, headers=token)
    assert response.status_code == 200, response.text
    return response.json()


def assert_field_interfaces_closed(client):
    assert not client.get("/api/session").json()["field_network_open"]
    bacnet = client.get("/api/bacnet/status").json()
    assert not bacnet["connected"]
    assert bacnet["commands"] == []
    assert not client.get("/api/native/status").json()["running"]


def test_recording_is_opt_in_and_status_trends_and_sources_survive_restart(tmp_path, monkeypatch):
    async def field_connection_forbidden(*args, **kwargs):
        raise AssertionError("Observation APIs must not open field interfaces.")

    monkeypatch.setattr(Bacnet, "connect", field_connection_forbidden)
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        unrecorded = step(client, token, record=False)
        assert unrecorded["recording_source"] is None
        assert unrecorded["recording_error"] is None
        assert client.get("/api/observations/status").json()["samples"] == 0
        result = step(client, token, session=unrecorded["session"])
        source = result["recording_source"]
        assert source.startswith("simulation/observed-zone/")
        assert result["recording_error"] is None
        status = client.get("/api/observations/status").json()
        assert status["samples"] == 5 and status["active_alarms"] == 1
        assert status["source_kind"] == "simulation"
        samples = client.get("/api/observations/trends", params={"source": source}).json()
        assert len(samples) == 5
        temperature = next(row for row in samples if row["signal"] == "temperature")
        assert temperature["value"] == 90 and temperature["unit"] == "°F"
        alarm = next(row for row in samples if row["signal"] == "high")
        assert alarm["value"] is True
        assert client.get("/api/observations/sources").json()[0]["source"] == source
        assert_field_interfaces_closed(client)
    with TestClient(create_app(tmp_path)) as restarted:
        assert restarted.get("/api/observations/status").json() == status
        assert (
            restarted.get("/api/observations/trends", params={"source": source}).json() == samples
        )
        assert len(restarted.get("/api/observations/events").json()) == 1
        # Trend evidence survives restart; execution sessions intentionally do not.
        expired = restarted.post(
            "/api/simulation/step",
            json={"program": alarm_program(), "session": result["session"], "record": True},
            headers=headers(restarted),
        )
        assert expired.status_code == 422 and "expired" in expired.json()["detail"]
        assert_field_interfaces_closed(restarted)


def test_alarm_lifecycle_ack_return_reactivation_and_source_retirement(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        first = step(client, token)
        source, session = first["recording_source"], first["session"]
        alarm = client.get("/api/observations/alarms").json()[0]
        assert alarm["active"] and not alarm["acknowledged"]
        assert alarm["message"] == "Zone too hot"
        ack_body = {"alarm_id": alarm["id"], "note": "Investigating simulated zone", "actor": "Jim"}
        acknowledged = client.post("/api/observations/acknowledge", json=ack_body, headers=token)
        assert acknowledged.status_code == 200
        assert acknowledged.json()["active"] and acknowledged.json()["acknowledged"]
        assert (
            client.post("/api/observations/acknowledge", json=ack_body, headers=token).status_code
            == 200
        )
        assert len(client.get("/api/observations/events").json()) == 2
        blocked = client.post("/api/observations/retire", json={"source": source}, headers=token)
        assert blocked.status_code == 422
        step(client, token, session=session, temperature=70)
        returned = client.get("/api/observations/alarms").json()[0]
        assert returned["state"] == "returned" and returned["acknowledged"]
        step(client, token, session=session, temperature=95)
        new_alarm = client.get("/api/observations/alarms", params={"active": True}).json()[0]
        assert new_alarm["id"] != alarm["id"]
        assert not new_alarm["acknowledged"]
        unacknowledged = client.get(
            "/api/observations/alarms", params={"unacknowledged": True}
        ).json()
        assert [a["id"] for a in unacknowledged] == [new_alarm["id"]]
        step(client, token, session=session, temperature=70)
        assert (
            client.post(
                "/api/observations/retire", json={"source": source}, headers=token
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/observations/acknowledge",
                json={"alarm_id": new_alarm["id"], "note": "Reviewed after return"},
                headers=token,
            ).status_code
            == 200
        )
        events = client.get("/api/observations/events", params={"source": source}).json()
        assert [e["event"] for e in events] == [
            "activated",
            "acknowledged",
            "returned",
            "activated",
            "returned",
            "acknowledged",
        ]
        retired = client.post("/api/observations/retire", json={"source": source}, headers=token)
        assert retired.status_code == 200 and retired.json()["retired"]
        assert retired.json()["removed"]["samples"] == 20
        assert client.get("/api/observations/sources").json() == []
        assert client.get("/api/observations/trends", params={"source": source}).json() == []
        assert client.get("/api/observations/events", params={"source": source}).json() == []
        assert_field_interfaces_closed(client)


def test_clock_rewind_reports_recording_error_but_preserves_executed_scan(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        first = step(client, token, clock="2026-05-01T00:00:00Z", temperature=90)
        assert first["last"]["outputs"]["out"] == 10
        rewound = step(
            client, token, session=first["session"], clock="2026-01-01T00:00:00Z", temperature=95
        )
        assert "Out-of-order" in rewound["recording_error"]
        assert rewound["recording_source"] == first["recording_source"]
        assert rewound["last"]["outputs"]["out"] == 20
        assert rewound["snapshot"]["time"] == 2
        assert rewound["snapshot"]["values"]["temperature"] == 95
        assert rewound["snapshot"]["clock"].startswith("2026-01-01")
        assert len(rewound["history"]) == 2
        assert client.get("/api/observations/status").json()["samples"] == 5
        recovered = step(
            client, token, session=first["session"], clock="2026-05-01T00:00:01Z", temperature=70
        )
        assert recovered["recording_error"] is None
        assert recovered["snapshot"]["time"] == 3
        assert client.get("/api/observations/status").json()["samples"] == 10
        assert_field_interfaces_closed(client)


def test_recording_disk_error_is_separate_from_executed_scan_and_retry_can_continue(
    tmp_path, monkeypatch
):
    original = ObservabilityStore.record_scan

    def fail_recording(*args, **kwargs):
        raise sqlite3.OperationalError("simulated disk full")

    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        monkeypatch.setattr(ObservabilityStore, "record_scan", fail_recording)
        result = step(client, token, temperature=95)
        assert result["recording_error"] == "simulated disk full"
        assert result["snapshot"]["time"] == 1
        assert result["last"]["outputs"]["out"] == 10
        assert client.get("/api/observations/status").json()["samples"] == 0
        monkeypatch.setattr(ObservabilityStore, "record_scan", original)
        next_scan = step(client, token, session=result["session"], temperature=95)
        assert next_scan["last"]["outputs"]["out"] == 20
        assert next_scan["recording_error"] is None
        assert client.get("/api/observations/status").json()["samples"] == 5


def test_failed_program_scan_adds_no_durable_observations_or_execution_state(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        first = step(client, token)
        before = client.get("/api/observations/status").json()
        response = client.post(
            "/api/simulation/step",
            json={
                "program": alarm_program(),
                "session": first["session"],
                "record": True,
                "inputs": {"temperature": {"value": None, "quality": "open-circuit"}},
            },
            headers=token,
        )
        assert response.status_code == 422 and "open-circuit" in response.json()["detail"]
        assert client.get("/api/observations/status").json() == before
        resumed = step(client, token, session=first["session"])
        assert resumed["snapshot"]["time"] == 2
        assert resumed["last"]["outputs"]["out"] == 20


@pytest.mark.parametrize(
    "endpoint,params",
    [
        ("trends", {"after": -1}),
        ("trends", {"after": "NaN"}),
        ("trends", {"limit": 1001}),
        ("trends", {"limit": 0}),
        ("trends", {"start": "2026-01-01T00:00:00"}),
        ("trends", {"start": "2026-02-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"}),
        ("events", {"after": -1}),
        ("events", {"alarm_id": 0}),
        ("events", {"limit": 1001}),
        ("alarms", {"active": "not-a-boolean"}),
        ("alarms", {"limit": 0}),
    ],
)
def test_invalid_query_cursors_bounds_and_filters_are_validation_errors(tmp_path, endpoint, params):
    with TestClient(create_app(tmp_path)) as client:
        response = client.get(f"/api/observations/{endpoint}", params=params)
        assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "acknowledgement",
    [
        {},
        {"alarm_id": 1},
        {"alarm_id": 1, "note": ""},
        {"alarm_id": 1, "note": "   "},
        {"alarm_id": True, "note": "Bad boolean identifier"},
        {"alarm_id": "1", "note": "Bad string identifier"},
        {"alarm_id": 1, "note": {"not": "a string"}},
        {"alarm_id": 1, "note": "Reviewed", "unexpected": True},
        {"alarm_id": 1, "note": "Reviewed", "actor": "\n"},
    ],
)
def test_malformed_acknowledgement_cannot_change_real_occurrence(tmp_path, acknowledgement):
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        step(client, token)
        response = client.post("/api/observations/acknowledge", json=acknowledgement, headers=token)
        assert response.status_code == 422, response.text
        assert not client.get("/api/observations/alarms").json()[0]["acknowledged"]
        assert len(client.get("/api/observations/events").json()) == 1


def test_unknown_sources_are_empty_queries_and_unknown_mutation_targets_are_rejected(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        for endpoint in ("trends", "alarms", "events"):
            assert (
                client.get(f"/api/observations/{endpoint}", params={"source": "missing"}).json()
                == []
            )
        retired = client.post("/api/observations/retire", json={"source": "missing"}, headers=token)
        assert retired.status_code == 422 and "not found" in retired.json()["detail"]
        acknowledged = client.post(
            "/api/observations/acknowledge",
            json={"alarm_id": 999, "note": "Reviewed"},
            headers=token,
        )
        assert acknowledged.status_code == 422 and "not found" in acknowledged.json()["detail"]
        assert_field_interfaces_closed(client)


def divide_feedback_program(initial=1):
    """One successful scan changes the next divisor from one to zero."""
    return Program(
        id="batch-fault",
        nodes=[
            Node(id="one", kind="Constant", params={"value": 1}),
            Node(id="divisor", kind="Delay", params={"initial": initial}),
            Node(id="decrement", kind="Subtract"),
            Node(id="quotient", kind="Divide"),
            Node(id="out", kind="Output"),
        ],
        edges=[
            Edge(id="a", source="divisor", target="decrement", target_port="a"),
            Edge(id="b", source="one", target="decrement", target_port="b"),
            Edge(id="feedback", source="decrement", target="divisor"),
            Edge(id="numerator", source="one", target="quotient", target_port="a"),
            Edge(id="denominator", source="divisor", target="quotient", target_port="b"),
            Edge(id="out", source="quotient", target="out"),
        ],
    ).model_dump()


def test_partial_batch_failure_returns_and_records_only_completed_scans(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        response = client.post(
            "/api/simulation/step",
            json={"program": divide_feedback_program(), "steps": 3, "record": True},
            headers=token,
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["completed_steps"] == 1
        assert "division by zero" in result["scan_error"]
        assert result["recording_error"] is None
        assert result["last"]["outputs"] == {"out": 1}
        assert result["snapshot"]["time"] == 1
        assert result["snapshot"]["state"]["divisor"]["previous"] == 0
        assert result["snapshot"]["values"]["decrement"] == 0
        assert len(result["history"]) == 1
        assert result["history"][0] == result["last"]
        samples = client.get(
            "/api/observations/trends", params={"source": result["recording_source"]}
        ).json()
        assert len(samples) == 5
        assert {r["clock"] for r in samples} == {"2026-01-05T00:00:01.000000+00:00"}
        assert next(r["value"] for r in samples if r["signal"] == "divisor") == 1
        # The failed second scan never committed its candidate decrement of -1.
        assert next(r["value"] for r in samples if r["signal"] == "decrement") == 0
        failed_again = client.post(
            "/api/simulation/step",
            json={
                "program": divide_feedback_program(),
                "session": result["session"],
                "record": True,
            },
            headers=token,
        )
        assert failed_again.status_code == 422
        assert client.get("/api/observations/status").json()["samples"] == 5
        assert_field_interfaces_closed(client)


def test_first_scan_failure_still_returns_validation_error_and_records_nothing(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post(
            "/api/simulation/step",
            json={"program": divide_feedback_program(initial=0), "steps": 3, "record": True},
            headers=headers(client),
        )
        assert response.status_code == 422
        assert "division by zero" in response.json()["detail"]
        assert client.get("/api/observations/status").json()["samples"] == 0
        assert client.get("/api/observations/sources").json() == []


def mutation_target(client, token, operation):
    if operation == "acknowledge":
        step(client, token)
        alarm_id = client.get("/api/observations/alarms").json()[0]["id"]
        return {"alarm_id": alarm_id, "note": "Reviewed"}, (
            "simulation.alarm.acknowledgement.requested",
            "simulation.alarm.acknowledged",
        )
    if operation == "end":
        result = step(client, token)
        return {"source": result["recording_source"], "note": "Session no longer exists"}, (
            "simulation.observations.end.requested",
            "simulation.observations.ended",
        )
    result = step(client, token, temperature=70)
    return {"source": result["recording_source"]}, (
        "simulation.observations.retirement.requested",
        "simulation.observations.retired",
    )


def mutation_was_committed(directory, operation):
    observations = ObservabilityStore(directory)
    if operation == "acknowledge":
        return observations.alarms()[0]["acknowledged"]
    if operation == "end":
        return observations.list_sources()[0]["ended"]
    return observations.list_sources() == []


@pytest.mark.parametrize("operation", ["acknowledge", "retire", "end"])
def test_audit_intent_precedes_mutation_and_completion_follows_it(tmp_path, monkeypatch, operation):
    original = Store.record
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        body, (intent, completion) = mutation_target(client, token, operation)
        calls = []

        def inspect_order(store, name, detail):
            if name == intent:
                assert not mutation_was_committed(tmp_path, operation)
                calls.append("intent")
            elif name == completion:
                assert mutation_was_committed(tmp_path, operation)
                calls.append("completion")
            return original(store, name, detail)

        monkeypatch.setattr(Store, "record", inspect_order)
        response = client.post(f"/api/observations/{operation}", json=body, headers=token)
        assert response.status_code == 200, response.text
        assert calls == ["intent", "completion"]
        assert "audit_error" not in response.json()


@pytest.mark.parametrize("operation", ["acknowledge", "retire", "end"])
def test_completion_audit_failure_reports_committed_mutation(tmp_path, monkeypatch, operation):
    original = Store.record
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        body, (intent, completion) = mutation_target(client, token, operation)

        def fail_completion_only(store, name, detail):
            if name == completion:
                raise sqlite3.OperationalError("simulated completion audit failure")
            return original(store, name, detail)

        monkeypatch.setattr(Store, "record", fail_completion_only)
        response = client.post(f"/api/observations/{operation}", json=body, headers=token)
        assert response.status_code == 200, response.text
        assert ("Source ended" if operation == "end" else "committed") in response.json()[
            "audit_error"
        ]
        assert "simulated completion audit failure" in response.json()["audit_error"]
        assert mutation_was_committed(tmp_path, operation)
        audit_operations = [entry["operation"] for entry in client.get("/api/audit").json()]
        assert intent in audit_operations and completion not in audit_operations


@pytest.mark.parametrize("operation", ["acknowledge", "retire", "end"])
def test_failed_audit_intent_prevents_mutation(tmp_path, monkeypatch, operation):
    original = Store.record
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        body, (intent, completion) = mutation_target(client, token, operation)

        def fail_intent_only(store, name, detail):
            if name == intent:
                raise sqlite3.OperationalError("simulated intent audit failure")
            return original(store, name, detail)

        monkeypatch.setattr(Store, "record", fail_intent_only)
        response = client.post(f"/api/observations/{operation}", json=body, headers=token)
        assert response.status_code == 503, response.text
        assert not mutation_was_committed(tmp_path, operation)
        audit_operations = [entry["operation"] for entry in client.get("/api/audit").json()]
        assert intent not in audit_operations and completion not in audit_operations


def test_explicitly_end_old_session_preserves_alarm_evidence_and_allows_ack_then_retire(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        old = step(client, token)
        source = old["recording_source"]
        newer = step(client, token)
        assert newer["recording_source"] != source
        body = {"source": source, "note": "Editor simulation was reset", "actor": "Jim"}
        response = client.post("/api/observations/end", json=body, headers=token)
        assert response.status_code == 200, response.text
        ended = response.json()
        assert ended["ended"] and ended["ended_alarms"] == 1
        assert ended["ended_note"] == body["note"] and ended["ended_by"] == "Jim"
        assert client.post("/api/observations/end", json=body, headers=token).json() == ended
        alarms = client.get("/api/observations/alarms", params={"source": source}).json()
        assert len(alarms) == 1
        alarm = alarms[0]
        assert alarm["state"] == "source-ended" and alarm["returned_at"] is None
        assert alarm["ended_at"] == ended["ended_at"] and not alarm["acknowledged"]
        assert len(client.get("/api/observations/events", params={"source": source}).json()) == 2
        assert client.get("/api/observations/status").json()["ended_sources"] == 1
        assert client.get(
            "/api/observations/alarms", params={"source": newer["recording_source"]}
        ).json()[0]["active"]
        # A late execution request may run, but an ended source cannot capture it.
        late = step(client, token, session=old["session"])
        assert late["completed_steps"] == 1 and late["snapshot"]["time"] == 2
        assert "source has ended" in late["recording_error"]
        assert len(client.get("/api/observations/trends", params={"source": source}).json()) == 5
        assert (
            client.post(
                "/api/observations/retire", json={"source": source}, headers=token
            ).status_code
            == 422
        )
        assert_field_interfaces_closed(client)
    with TestClient(create_app(tmp_path)) as restarted:
        token = headers(restarted)
        selected = next(
            s for s in restarted.get("/api/observations/sources").json() if s["source"] == source
        )
        assert selected["ended"] and selected["ended_note"] == body["note"]
        acknowledgement = restarted.post(
            "/api/observations/acknowledge",
            json={"alarm_id": alarm["id"], "note": "Reviewed ended session"},
            headers=token,
        )
        assert acknowledgement.status_code == 200
        assert acknowledgement.json()["state"] == "source-ended"
        retired = restarted.post("/api/observations/retire", json={"source": source}, headers=token)
        assert retired.status_code == 200 and retired.json()["retired"]
        assert restarted.get("/api/observations/status").json()["ended_sources"] == 0
        assert [s["source"] for s in restarted.get("/api/observations/sources").json()] == [
            newer["recording_source"]
        ]


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "missing"},
        {"note": ""},
        {"note": "   "},
        {"actor": ""},
        {"actor": "bad\nactor"},
        {"unexpected": True},
    ],
)
def test_malformed_source_end_cannot_end_or_acknowledge_an_active_occurrence(tmp_path, changes):
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        observed = step(client, token)
        body = {"source": observed["recording_source"], "note": "Finished"} | changes
        response = client.post("/api/observations/end", json=body, headers=token)
        assert response.status_code == 422, response.text
        assert not client.get("/api/observations/sources").json()[0]["ended"]
        alarm = client.get("/api/observations/alarms").json()[0]
        assert alarm["active"] and not alarm["acknowledged"] and alarm["ended_at"] is None
