"""Real local API round trips with independent report seals and persisted reopen."""

import copy
import hashlib
import json

from bms_tool.app import create_app
from fastapi.testclient import TestClient

from tests.test_conformance import program, suite, verify_report


def token(client):
    return {"X-Studio-Token": client.get("/api/session").json()["token"]}


def test_authoring_run_export_restart_and_no_field_connection(tmp_path):
    p = program()
    source = p.model_dump(mode="json")
    body = {"program": source, "suite": suite(p)}
    with TestClient(create_app(tmp_path)) as client:
        headers = token(client)
        catalog = client.post("/api/conformance/catalog", json={"program": source}, headers=headers)
        assert catalog.status_code == 200
        assert catalog.json()["template"]["cases"][0]["checks"] == []
        assert catalog.json()["saved"] == []
        validated = client.post("/api/conformance/validate", json=body, headers=headers)
        assert validated.status_code == 200, validated.text
        exported = client.post("/api/conformance/export", json=body, headers=headers)
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]
        raw = exported.content
        assert hashlib.sha256(raw.rstrip(b"\n")).hexdigest() == validated.json()["suite_sha256"]
        imported = client.post(
            "/api/conformance/import",
            json={"program": source, "text": raw.decode()},
            headers=headers,
        )
        assert imported.json()["suite"] == validated.json()["suite"]
        response = client.post("/api/conformance/run", json=body, headers=headers)
        assert response.status_code == 200, response.text
        report = response.json()
        verify_report(report)
        assert report["status"] == "passed"
        assert report["suite_sha256"] == validated.json()["suite_sha256"]
        assert report["cases"][0]["coverage"]["unasserted_signals"] == ["sensor", "state", "unused"]
        saved = client.post(
            "/api/conformance/save", json=body | {"expected_revision": 0}, headers=headers
        )
        assert saved.status_code == 200, saved.text
        saved = saved.json()
        assert not client.get("/api/bacnet/status").json()["connected"]
    with TestClient(create_app(tmp_path)) as client:
        headers = token(client)
        loaded = client.post(
            f"/api/conformance/saved/{saved['id']}", json={"program": source}, headers=headers
        )
        assert loaded.json() == saved
        assert (
            client.post(
                "/api/conformance/catalog", json={"program": source}, headers=headers
            ).json()["saved"][0]["id"]
            == saved["id"]
        )
        stale = copy.deepcopy(source)
        stale["revision"] += 1
        assert (
            client.post(
                f"/api/conformance/saved/{saved['id']}", json={"program": stale}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/conformance/run",
                json={"program": stale, "suite": body["suite"]},
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/conformance/save",
                json=body | {"id": saved["id"], "expected_revision": 0},
                headers=headers,
            ).status_code
            == 409
        )
        deleted = client.post(
            f"/api/conformance/saved/{saved['id']}/delete",
            json={"program": source, "expected_revision": 1},
            headers=headers,
        )
        assert deleted.json() == {"deleted": saved["id"]}


def test_session_origin_strict_import_and_unknown_fields(tmp_path):
    p = program()
    source = p.model_dump(mode="json")
    with TestClient(create_app(tmp_path)) as client:
        headers = token(client)
        for path in ("catalog", "validate", "import", "export", "run", "save"):
            assert (
                client.post("/api/conformance/" + path, json={"program": source}).status_code == 403
            )
        assert (
            client.post(
                "/api/conformance/catalog",
                json={"program": source},
                headers=headers | {"Origin": "https://elsewhere.test"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/conformance/catalog",
                json={"program": source},
                headers=headers | {"Host": "field.example"},
            ).status_code
            == 403
        )
        for text in ('{"a":1,"a":2}', '{"a":NaN}', "{", '"\\ud800"'):
            assert (
                client.post(
                    "/api/conformance/import",
                    json={"program": source, "text": text},
                    headers=headers,
                ).status_code
                == 422
            )
        assert (
            client.post(
                "/api/conformance/catalog",
                json={"program": source, "surprise": True},
                headers=headers,
            ).status_code
            == 422
        )
        body = {"program": source, "suite": suite(p)}
        body["suite"]["cases"][0]["script"] = "do anything"
        assert client.post("/api/conformance/run", json=body, headers=headers).status_code == 422


def test_authoritative_report_retains_native_float_spellings(tmp_path):
    p = program()
    p.nodes[1].params["initial"] = -0.0
    value = suite(p)
    value["cases"][0].update(
        duration=1.0,
        events=[],
        checks=[
            {
                "id": "zero",
                "signal": "result",
                "time": 1.0,
                "unit": "degF",
                "expected": -0.0,
                "abs_tol": 1e-7,
                "rel_tol": 0.0,
            }
        ],
    )
    with TestClient(create_app(tmp_path)) as client:
        raw = client.post(
            "/api/conformance/run",
            json={"program": p.model_dump(mode="json"), "suite": value},
            headers=token(client),
        ).content
        assert b'"actual":-0.0' in raw and b'"expected":-0.0' in raw
        assert b'"abs_tol":1e-07' in raw
        verify_report(json.loads(raw))
