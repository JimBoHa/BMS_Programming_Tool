"""HTTP IEC operations execute native code without opening controller transports."""

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.iec import profile
from fastapi.testclient import TestClient

from tests.test_iec import block_program

requires_compiler = pytest.mark.skipif(
    not profile()["available"], reason="Build optional pinned IEC compiler first"
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("IEC-only HTTP action attempted to use a field transport")

    for method in ("connect", "connect_mstp", "discover", "read", "apply_write", "release"):
        monkeypatch.setattr(Bacnet, method, forbidden)
    with TestClient(create_app(tmp_path)) as local:
        local.headers["X-Studio-Token"] = local.get("/api/session").json()["token"]
        yield local
        assert local.get("/api/session").json()["field_network_open"] is False
        status = local.get("/api/bacnet/status").json()
        assert not status["connected"] and not status["commands"]


@requires_compiler
def test_http_iec_compiles_real_st_and_reports_native_c_provenance(client):
    status = client.get("/api/iec/status")
    assert status.status_code == 200
    assert status.json()["available"] and not status.json()["controller_download"]
    response = client.post("/api/iec/compile", json={"program": block_program("Add").model_dump()})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["compiled"] and result["native_runtime_verified"] is False
    assert "PROGRAM MAIN" in result["source_st"]
    assert "MAIN_body__" in result["generated_c"]
    assert result["profile"]["provenance"]["revision"] == status.json()["revision"]
    assert result["warnings"]["count"] > 0


@requires_compiler
def test_http_iec_native_stateful_execution_quality_fault_and_timed_scenario(client):
    program = block_program("Slew").model_dump()
    response = client.post(
        "/api/iec/verify",
        json={"program": program, "inputs": {"input0": 10}, "scans": 3, "dt": 0.5},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["matches_reference"] and result["native_runtime_verified"]
    assert [row["outputs"]["out"] for row in result["rows"]] == [0.5, 1, 1.5]
    failed = client.post(
        "/api/iec/verify",
        json={"program": program, "inputs": {"input0": {"quality": "open-circuit"}}},
    )
    assert failed.status_code == 200, failed.text
    row = failed.json()["rows"][0]
    assert row["fault"] and row["matches_reference"] and row["successful_scans"] == 0
    assert row["outputs"] == {"out": 0}
    scenario = client.post(
        "/api/iec/scenario",
        json={
            "program": program,
            "events": [
                {"time": 0, "inputs": {"input0": 10}},
                {"time": 2, "inputs": {"input0": -10}},
            ],
            "duration": 4,
            "dt": 1,
            "clock": "2026-01-05T00:00:00+00:00",
        },
    )
    assert scenario.status_code == 200, scenario.text
    assert scenario.json()["matches_reference"]
    assert [row["outputs"]["out"] for row in scenario.json()["rows"]] == [1, 2, 1, 0]


def test_http_iec_local_session_security_and_arbitrary_code_rejection(client):
    program = block_program("Add").model_dump()
    body = {"program": program}
    token = client.headers.pop("X-Studio-Token")
    assert client.post("/api/iec/compile", json=body).status_code == 403
    client.headers["X-Studio-Token"] = token
    assert (
        client.post("/api/iec/compile", json=body, headers={"Host": "foreign.example"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/iec/compile", json=body, headers={"Origin": "https://foreign.example"}
        ).status_code
        == 403
    )
    for payload in (
        {"source_st": "PROGRAM P VAR x:INT; END_VAR END_PROGRAM"},
        {"program": program, "source_c": "int main(void){return 0;}"},
        {"program": {**program, "nodes": [{"id": "x", "kind": "NativeC"}]}},
    ):
        response = client.post("/api/iec/compile", json=payload)
        assert response.status_code == 422, response.text


@requires_compiler
def test_http_iec_validation_does_not_silently_coerce_values_or_ignore_events(client):
    program = block_program("Slew").model_dump()
    for extra in (
        {"scans": 1001},
        {"scans": True},
        {"dt": 0},
        {"dt": True},
        {"dt": "1"},
        {"dt": 1e-50},
        {"inputs": {"not-a-point": 10}},
        {"inputs": {"input0": "10"}},
        {"clock": "2026-01-05T00:00:00"},
    ):
        response = client.post("/api/iec/verify", json={"program": program, **extra})
        assert response.status_code == 422, (extra, response.text)
    for extra in (
        {"duration": 1001},
        {"duration": True},
        {"duration": "4"},
        {"events": [{"time": -1, "inputs": {}}]},
        {"events": [{"time": 1, "inputs": {}, "forces": {"out": 9}}]},
    ):
        response = client.post(
            "/api/iec/scenario",
            json={"program": program, "duration": 4, "dt": 1, "events": [], **extra},
        )
        assert response.status_code == 422, (extra, response.text)


def test_http_iec_missing_optional_compiler_is_explicit_and_does_not_simulate_instead(
    client, monkeypatch, tmp_path
):
    monkeypatch.setenv("BMS_IEC_HOME", str(tmp_path / "not-installed"))
    assert client.get("/api/iec/status").json()["available"] is False
    response = client.post("/api/iec/verify", json={"program": block_program("Add").model_dump()})
    assert response.status_code == 422 and "unavailable" in response.text
