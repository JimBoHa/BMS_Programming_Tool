"""LAN access admission and genuine one-attempt forwarding to a local editor."""

import base64
import ipaddress
import json
import socket
import threading
import time

import pytest
import uvicorn
from bms_tool.lan import LANConfig, create_gateway
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.testclient import TestClient

CODE = b"authored-example-" + b"access-code-0123456789"


def configuration():
    return LANConfig("127.0.0.1", 18773, (ipaddress.IPv4Network("127.0.0.0/8"),), CODE)


def headers():
    return {"Authorization": "Basic " + base64.b64encode(b"operator:" + CODE).decode()}


@pytest.fixture
def backend():
    calls = []
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def receive(request: Request, path: str):
        data = {
            "path": path,
            "query": request.url.query,
            "method": request.method,
            "host": request.headers.get("host"),
            "origin": request.headers.get("origin"),
            "token": request.headers.get("x-studio-token"),
            "authorization": request.headers.get("authorization"),
            "forwarded": request.headers.get("x-forwarded-for"),
            "body": (await request.body()).decode(),
        }
        calls.append(data)
        return Response(
            json.dumps(data), media_type="application/json", headers={"Cache-Control": "no-store"}
        )

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(10)
    server = uvicorn.Server(uvicorn.Config(app, access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    yield f"http://127.0.0.1:{sock.getsockname()[1]}", calls
    server.should_exit = True
    thread.join(5)
    sock.close()
    assert not thread.is_alive()


def test_authentication_subnet_host_and_origin_refuse_before_upstream(backend):
    upstream, calls = backend
    app = create_gateway(configuration(), upstream)
    with TestClient(app, base_url="http://127.0.0.1:18773", client=("127.0.0.1", 40000)) as client:
        assert client.get("/").status_code == 401
        assert client.get("/", headers={"Authorization": "Basic invalid"}).status_code == 401
        assert (
            client.get("/", headers={**headers(), "Origin": "http://unrelated.example"}).status_code
            == 403
        )
        assert (
            client.get("/", headers={**headers(), "Host": "unrelated.example"}).status_code == 403
        )
    with TestClient(
        app, base_url="http://127.0.0.1:18773", client=("198.51.100.10", 40000)
    ) as client:
        assert (
            client.get("/", headers={**headers(), "X-Forwarded-For": "127.0.0.1"}).status_code
            == 403
        )
    assert calls == []


def test_one_attempt_preserves_body_query_and_token_without_forwarding_gateway_credentials(backend):
    upstream, calls = backend
    with TestClient(
        create_gateway(configuration(), upstream),
        base_url="http://127.0.0.1:18773",
        client=("127.0.0.1", 40000),
    ) as client:
        result = client.post(
            "/api/example?source=authored",
            content=b'{"example":true}',
            headers={
                **headers(),
                "Origin": "http://127.0.0.1:18773",
                "X-Studio-Token": "authored-session",
                "X-Forwarded-For": "198.51.100.20",
            },
        )
        assert result.status_code == 200
        value = result.json()
        assert value["body"] == '{"example":true}'
        assert value["query"] == "source=authored" and value["method"] == "POST"
        assert value["host"] == upstream.removeprefix("http://") and value["origin"] == upstream
        assert value["token"] == "authored-session"
        assert value["authorization"] is None and value["forwarded"] is None
        assert result.headers["cache-control"] == "no-store"
    assert len(calls) == 1


def test_lost_backend_response_reports_uncertainty_without_retry():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with TestClient(
        create_gateway(configuration(), f"http://127.0.0.1:{port}"),
        base_url="http://127.0.0.1:18773",
        client=("127.0.0.1", 40000),
    ) as client:
        response = client.post("/api/example", headers=headers(), json={})
        assert response.status_code == 502
        assert "read back before any retry" in response.text


@pytest.mark.parametrize(
    "upstream",
    [
        "https://127.0.0.1:8765",
        "http://192.0.2.1:8765",
        "http://127.0.0.1:8765/path",
        "http://operator:secret@127.0.0.1:8765",
    ],
)
def test_gateway_cannot_become_a_general_proxy(upstream):
    with pytest.raises(ValueError, match="loopback"):
        create_gateway(configuration(), upstream)


def test_private_configuration_requires_restricted_code_file_and_explicit_network(tmp_path):
    code = tmp_path / "access-code"
    code.write_bytes(CODE)
    code.chmod(0o600)
    config = tmp_path / "sharing.json"
    document = {
        "profile": "bms-studio-lan/1",
        "host": "127.0.0.1",
        "port": 18773,
        "allowed_networks": ["127.0.0.0/8"],
        "access_code_file": str(code),
    }
    config.write_text(json.dumps(document))
    assert LANConfig.load(config).code == CODE
    document["allowed_networks"] = ["0.0.0.0/0"]
    config.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="values withheld"):
        LANConfig.load(config)
