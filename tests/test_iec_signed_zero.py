"""Exercise actual C output/state transport, including fault-retained IEEE zero."""

import math

import pytest
from bms_tool import iec
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.models import Edge, Node, Program
from fastapi.testclient import TestClient

requires_compiler = pytest.mark.skipif(
    not iec.profile()["available"], reason="Build optional pinned MatIEC compiler first"
)


def signed_zero_program():
    return Program(
        id="native-signed-zero",
        nodes=[
            Node(id="input", kind="Input"),
            Node(id="output", kind="Output"),
            Node(id="delay", kind="Delay", params={"initial": -0.0}),
            Node(id="stored", kind="Output"),
        ],
        edges=[
            Edge(id="direct", source="input", target="output"),
            Edge(id="retain", source="input", target="delay"),
            Edge(id="delayed", source="delay", target="stored"),
        ],
    )


def assert_zero(value, sign):
    assert value == 0
    assert math.copysign(1.0, value) == sign, (repr(value), sign)


@requires_compiler
def test_actual_native_ieee_zero_outputs_and_retained_state_survive_fault():
    with iec.NativeIEC(signed_zero_program()) as native:
        process = native.process
        first = native.step({"input": -0.0})
        assert first["matches_reference"] and not first["fault"]
        assert_zero(first["outputs"]["output"], -1)
        assert_zero(first["outputs"]["stored"], -1)
        assert_zero(first["native_state"]["n_delay_memory"], -1)

        positive = native.step({"input": 0.0})
        assert_zero(positive["outputs"]["output"], 1)
        assert_zero(positive["outputs"]["stored"], -1)
        assert_zero(positive["native_state"]["n_delay_memory"], 1)

        negative = native.step({"input": -0.0})
        assert_zero(negative["outputs"]["output"], -1)
        assert_zero(negative["outputs"]["stored"], 1)
        assert_zero(negative["native_state"]["n_delay_memory"], -1)
        fault = native.step({"input": {"quality": "open-circuit"}})
        assert fault["fault"] and fault["matches_reference"]
        assert fault["successful_scans"] == 3
        assert_zero(fault["outputs"]["output"], -1)
        assert_zero(fault["outputs"]["stored"], 1)
        assert_zero(fault["native_state"]["n_delay_memory"], -1)

        recovered = native.step({"input": 1.25})
        assert recovered["matches_reference"] and not recovered["fault"]
        assert recovered["outputs"]["output"] == 1.25
        assert_zero(recovered["outputs"]["stored"], -1)
        ordinary = native.step({"input": -1e-20})
        assert ordinary["matches_reference"] and not ordinary["fault"]
        assert ordinary["outputs"]["output"] == pytest.approx(-1e-20, rel=1e-6, abs=0)
        assert ordinary["outputs"]["stored"] == 1.25
    assert process.poll() is not None


@requires_compiler
def test_http_verifier_keeps_negative_zero_native_output_and_state(tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Local IEC verifier attempted a field operation")

    for method in ("connect", "connect_mstp", "discover", "read", "apply_write", "release"):
        monkeypatch.setattr(Bacnet, method, forbidden)
    with TestClient(create_app(tmp_path)) as client:
        client.headers["X-Studio-Token"] = client.get("/api/session").json()["token"]
        response = client.post(
            "/api/iec/verify",
            json={"program": signed_zero_program().model_dump(), "inputs": {"input": -0.0}},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["matches_reference"] and result["native_runtime_verified"]
        row = result["rows"][0]
        assert_zero(row["outputs"]["output"], -1)
        assert_zero(row["outputs"]["stored"], -1)
        assert_zero(row["native_state"]["n_delay_memory"], -1)
        assert client.get("/api/session").json()["field_network_open"] is False
