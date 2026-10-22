"""Actual bounded batch execution and receipts used by the monotonic browser runner."""

from datetime import datetime, timedelta

from bms_tool.app import create_app
from bms_tool.models import Edge, Node, Program
from fastapi.testclient import TestClient

from tests.test_observation_api import divide_feedback_program


def timer_program():
    return Program(
        id="clock-test",
        scan_seconds=0.25,
        nodes=[
            Node(id="enable", kind="Input", value_type="boolean", params={"default": True}),
            Node(
                id="timer",
                x=280,
                y=100,
                kind="TimerOn",
                value_type="boolean",
                params={"seconds": 1},
            ),
            Node(id="out", x=560, y=100, kind="Output", value_type="boolean"),
        ],
        edges=[
            Edge(id="1", source="enable", target="timer"),
            Edge(id="2", source="timer", target="out"),
        ],
    ).model_dump()


def test_fixed_scan_batches_preserve_timer_utc_forces_quality_and_exact_receipt(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        source = timer_program()

        def run(**extra):
            response = client.post(
                "/api/simulation/step",
                json={"program": source, "operation_id": "a" * 32, **extra},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            return response.json()

        first = run(clock="2026-10-21T12:00:00Z")
        assert (
            first["operation_id"] == "a" * 32
            and first["requested_steps"] == first["completed_steps"] == 1
        )
        assert (
            first["program_id"] == "clock-test"
            and first["program_revision"] == 0
            and first["applied_dt"] == 0.25
        )
        assert not first["last"]["outputs"]["out"]
        second = run(session=first["session"], steps=2)
        assert (
            second["session"] == first["session"]
            and second["last"]["time"] == 0.75
            and not second["last"]["outputs"]["out"]
        )
        assert datetime.fromisoformat(second["last"]["clock"]) == datetime.fromisoformat(
            first["last"]["clock"]
        ) + timedelta(seconds=0.5)
        third = run(session=first["session"])
        assert third["last"]["outputs"]["out"] and third["last"]["time"] == 1
        forced = run(session=first["session"], forces={"out": False})
        assert (
            forced["last"]["outputs"]["out"] is False and forced["last"]["computed"]["out"] is True
        )
        fault = client.post(
            "/api/simulation/step",
            json={
                "program": source,
                "session": first["session"],
                "steps": 5,
                "inputs": {"enable": {"value": True, "quality": "open-circuit"}},
            },
            headers=headers,
        )
        assert fault.status_code == 422 and "open-circuit" in fault.json()["detail"]
        recovered = run(session=first["session"])
        assert recovered["last"]["time"] == 1.5  # fault batch committed no scan
        assert not client.get("/api/session").json()["field_network_open"]


def test_partial_committed_receipt_and_observation_identity_survive_later_fault(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            "/api/simulation/step",
            json={
                "program": divide_feedback_program(),
                "steps": 5,
                "record": True,
                "operation_id": "b" * 32,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        value = response.json()
        assert (
            value["operation_id"] == "b" * 32
            and value["requested_steps"] == 5
            and value["completed_steps"] == 1
        )
        assert "division by zero" in value["scan_error"] and value["last"]["time"] == 1
        samples = client.get(
            "/api/observations/trends", params={"source": value["recording_source"]}
        ).json()
        assert len(samples) == 5 and {datetime.fromisoformat(row["clock"]) for row in samples} == {
            datetime.fromisoformat(value["last"]["clock"])
        }
        again = client.post(
            "/api/simulation/step",
            json={"program": divide_feedback_program(), "session": value["session"]},
            headers=headers,
        )
        assert again.status_code == 422
        assert (
            len(
                client.get(
                    "/api/observations/trends", params={"source": value["recording_source"]}
                ).json()
            )
            == 5
        )


def test_failed_new_sessions_do_not_exhaust_capacity_or_create_observations(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for _ in range(30):
            failure = client.post(
                "/api/simulation/step",
                json={"program": divide_feedback_program(initial=0), "record": True, "session": ""},
                headers=headers,
            )
            assert failure.status_code == 422 and "division by zero" in failure.json()["detail"]
        assert client.get("/api/observations/status").json()["samples"] == 0
        assert client.get("/api/observations/sources").json() == []
        valid = client.post(
            "/api/simulation/step", json={"program": timer_program()}, headers=headers
        )
        assert valid.status_code == 200, valid.text
        assert valid.json()["operation_id"] is None  # legacy callers unchanged
        for changes in [
            {"operation_id": "x" * 33},
            {"operation_id": "z" * 32},
            {"clock": "2026-10-21T12:00:00Z", "steps": 2},
        ]:
            response = client.post(
                "/api/simulation/step",
                json={"program": timer_program(), **changes},
                headers=headers,
            )
            assert response.status_code == 422
        assert (
            client.post("/api/simulation/step", json={"program": timer_program()}).status_code
            == 403
        )


def test_opt_in_zero_commit_fault_receipt_retains_known_state_and_clock_and_new_fault_has_no_source(
    tmp_path,
):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        source = timer_program()
        request = {"program": source, "operation_id": "d" * 32, "record": True}
        fault_inputs = {"enable": {"value": True, "quality": "open-circuit"}}
        initial = client.post(
            "/api/simulation/step", json=request | {"inputs": fault_inputs}, headers=headers
        )
        assert initial.status_code == 200, initial.text
        initial = initial.json()
        assert initial["session"] is None and initial["last"] is None
        assert (
            initial["completed_steps"] == 0
            and initial["history"] == []
            and initial["snapshot"]["time"] == 0
        )
        assert initial["recording_source"] is None and "open-circuit" in initial["scan_error"]
        assert client.get("/api/observations/sources").json() == []
        good = client.post("/api/simulation/step", json=request, headers=headers).json()
        failed = client.post(
            "/api/simulation/step",
            json=request
            | {"session": good["session"], "inputs": fault_inputs, "clock": "2020-01-01T00:00:00Z"},
            headers=headers,
        )
        assert failed.status_code == 200, failed.text
        failed = failed.json()
        assert failed["session"] == good["session"] and failed["last"] is None
        assert (
            failed["completed_steps"] == 0
            and failed["snapshot"] == good["snapshot"]
            and failed["history"] == good["history"]
        )
        recovered = client.post(
            "/api/simulation/step", json=request | {"session": good["session"]}, headers=headers
        ).json()
        assert recovered["last"]["time"] == 0.5 and recovered["session"] == good["session"]
        assert (
            len(
                client.get(
                    "/api/observations/trends", params={"source": good["recording_source"]}
                ).json()
            )
            == 6
        )


def test_batched_pi_integrates_once_per_fixed_scan_and_legacy_dt_override_is_preserved(tmp_path):
    source = Program(
        id="paced-pi",
        scan_seconds=0.25,
        nodes=[
            Node(id="measured", kind="Input", params={"default": 74}, unit="degF"),
            Node(id="setpoint", kind="Constant", params={"value": 72}, unit="degF"),
            Node(
                id="pi",
                kind="PI",
                params={"kp": 3, "ki": 4, "reverse": True, "min": 0, "max": 100},
                unit="%",
            ),
            Node(id="out", kind="Output", unit="%"),
        ],
        edges=[
            Edge(id="1", source="measured", target="pi", target_port="measured"),
            Edge(id="2", source="setpoint", target="pi", target_port="setpoint"),
            Edge(id="3", source="pi", target="out"),
        ],
    ).model_dump()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        value = client.post(
            "/api/simulation/step",
            json={"program": source, "steps": 3, "operation_id": "e" * 32},
            headers=headers,
        ).json()
        # Error2degF: P=6%; integral grows4*2*.25=2% every scan.
        assert [row["outputs"]["out"] for row in value["history"]] == [8, 10, 12]
        assert [row["time"] for row in value["history"]] == [0.25, 0.5, 0.75]
        old = client.post(
            "/api/simulation/step", json={"program": source, "dt": 0.5}, headers=headers
        )
        assert old.status_code == 200, old.text
        assert old.json()["applied_dt"] == 0.5 and old.json()["last"]["outputs"]["out"] == 10
