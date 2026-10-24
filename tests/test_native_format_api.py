"""Exercise new native format boundaries through the production HTTP API."""

import io
import zipfile

from bms_tool.app import create_app
from bms_tool.models import Edge, Node, Program
from fastapi.testclient import TestClient


def primitive():
    return Program(
        id="native-api",
        nodes=[
            Node(id="sensor", kind="Input", params={"default": 40}),
            Node(id="delta", kind="Constant", params={"value": 2}),
            Node(id="sum", kind="Add"),
            Node(id="result", kind="Output"),
        ],
        edges=[
            Edge(id="a", source="sensor", target="sum", target_port="a"),
            Edge(id="b", source="delta", target="sum", target_port="b"),
            Edge(id="c", source="sum", target="result"),
        ],
    )


def test_native_bog_and_basic_exports_are_real_reimportable_source(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        program = primitive()
        profile = client.get("/api/niagara/profile").json()
        assert len(profile["native_types"]) == 23
        assert {"Clamp", "Scale", "Convert"} <= set(profile["native_types"])
        assert profile["native_runtime_verified"] is False
        for format, extension in [("bog", "bog"), ("temco-bas", "bas")]:
            response = client.post(
                "/api/export",
                json={"program": program.model_dump(), "format": format},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            assert response.headers["content-disposition"].endswith(f'.{extension}"')
            if format == "bog":
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    assert archive.namelist() == ["file.xml"]
                    assert b"kitControl" in archive.read("file.xml")
            else:
                assert response.content.startswith(b"10 REM BMS STUDIO CONTROL BASIC")
                assert b"END" in response.content
            restored = client.post(
                "/api/import",
                files={"file": (f"native.{extension}", response.content)},
                headers=headers,
            )
            assert restored.status_code == 200, restored.text
            # BOG source fidelity; native BASIC source is parsed semantically.
            if format == "bog":
                assert Program.model_validate(restored.json()) == program
            scan = client.post(
                "/api/simulation/step",
                json={
                    "program": restored.json(),
                    "inputs": {
                        n["id"]: 40 for n in restored.json()["nodes"] if n["kind"] == "Input"
                    },
                },
                headers=headers,
            )
            assert scan.status_code == 200, scan.text
            assert list(scan.json()["last"]["outputs"].values()) == [42]
        assert client.get("/api/session").json()["field_network_open"] is False


def test_native_export_refuses_invalid_graph_and_unsafe_foreign_source(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        program = primitive()
        program.nodes[2].kind = "PI"
        for format in ["bog", "temco-bas"]:
            response = client.post(
                "/api/export",
                json={"program": program.model_dump(), "format": format},
                headers=headers,
            )
            assert response.status_code == 422
        for name, content in [
            (
                "bad.bog",
                b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><bajaObjectGraph version="4.0">&x;</bajaObjectGraph>',
            ),
            ("bad.bas", b"10 REM no remote operations\n20 REMOTE_SET 1 2\n30 END\n"),
        ]:
            response = client.post("/api/import", files={"file": (name, content)}, headers=headers)
            assert response.status_code == 422
        assert not client.get("/api/bacnet/status").json()["connected"]
