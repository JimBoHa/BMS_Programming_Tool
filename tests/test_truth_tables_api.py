"""Actual HTTP raw parsing, authoritative downloads and zero field side effects."""

import hashlib
import json

from bms_tool.app import create_app
from bms_tool.truth_tables import MAX_SOURCE_BYTES
from fastapi.testclient import TestClient


def identity(review):
    return {
        "review_id": review["id"],
        "table_sha256": review["table_sha256"],
        "profile_sha256": review["source_profile"]["sha256"],
    }


def test_http_authoritative_download_import_replay_and_offline_evaluation(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        catalog = client.get("/api/truth-tables/profile").json()
        table = catalog["template"]
        assert not client.get("/api/session").json()["field_network_open"]
        assert client.post("/api/truth-tables/review", json={"table": table}).status_code == 403
        response = client.post(
            "/api/truth-tables/review",
            json={"table": table, "profile_sha256": catalog["profile"]["sha256"]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        review = response.json()
        key = identity(review)
        evaluated = client.post(
            "/api/truth-tables/evaluate",
            json=key | {"values": {"mode": 1, "override": False}},
            headers=headers,
        )
        assert evaluated.status_code == 200 and evaluated.json()["case"]["output"]["value"] is True
        for kind in ("table", "review"):
            response = client.post("/api/truth-tables/export/" + kind, json=key, headers=headers)
            assert response.status_code == 200
            raw = response.content
            assert response.headers["x-file-sha256"] == hashlib.sha256(raw).hexdigest()
            document = json.loads(raw)
            supplied = document.pop("content_sha256")
            canonical = json.dumps(
                document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
            assert (
                response.headers["x-content-sha256"]
                == supplied
                == hashlib.sha256(canonical).hexdigest()
            )
            if kind == "table":
                imported = client.post(
                    "/api/truth-tables/import",
                    files={"file": ("source.json", raw, "application/json")},
                    headers=headers,
                )
                assert (
                    imported.status_code == 200
                    and imported.json()["table_sha256"] == review["table_sha256"]
                )
                assert imported.json()["source_file_sha256"] == hashlib.sha256(raw).hexdigest()
                damaged = raw.replace(b"Mode and override example", b"Mode and override altered")
                rejected = client.post(
                    "/api/truth-tables/import",
                    files={"file": ("tampered.json", damaged)},
                    headers=headers,
                )
                assert rejected.status_code == 422 and "seal" in rejected.text
        forged = client.post(
            "/api/truth-tables/export/review",
            json=key | {"report": {"accepted": True}},
            headers=headers,
        )
        assert forged.status_code == 422
        stale = client.post(
            "/api/truth-tables/cases", json=key | {"table_sha256": "0" * 64}, headers=headers
        )
        assert stale.status_code == 422
        assert client.get("/api/projects").json() == []
        assert not client.get("/api/session").json()["field_network_open"]


def test_http_strict_raw_requests_and_bounded_uploads_reject_before_creating_reviews(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        headers = {
            "X-Studio-Token": client.get("/api/session").json()["token"],
            "Content-Type": "application/json",
        }
        profile = client.get("/api/truth-tables/profile").json()
        valid_table = json.dumps(profile["template"]).encode()
        profile_field = b',"profile_sha256":' + json.dumps(profile["profile"]["sha256"]).encode()
        for raw in (
            b'{"table":' + valid_table + b',"table":' + valid_table + profile_field + b"}",
            b'{"table":{"value":NaN}}',
            b'{"table":' + b"[" * 10000 + b"0" + b"]" * 10000 + b"}",
            b"\xff",
            b" " * (MAX_SOURCE_BYTES + 1),
        ):
            response = client.post("/api/truth-tables/review", content=raw, headers=headers)
            assert response.status_code == 422, response.text
        response = client.post(
            "/api/truth-tables/review",
            content=b'{"table":{}}',
            headers={**headers, "Content-Type": "text/plain"},
        )
        assert response.status_code == 422
        response = client.post(
            "/api/truth-tables/import",
            files={"file": ("large.json", b" " * (MAX_SOURCE_BYTES + 1))},
            headers={"X-Studio-Token": headers["X-Studio-Token"]},
        )
        assert response.status_code == 422
        valid_request = b'{"table":' + valid_table + profile_field + b"}"
        padded = valid_request + b" " * (MAX_SOURCE_BYTES + 1 - len(valid_request))
        response = client.post("/api/truth-tables/review", content=padded, headers=headers)
        assert response.status_code == 422 and "exceeds1MiB" in response.text
        response = client.post(
            "/api/truth-tables/review",
            json={"table": profile["template"], "profile_sha256": "0" * 64},
            headers={"X-Studio-Token": headers["X-Studio-Token"]},
        )
        assert response.status_code == 422 and "profile changed" in response.text
        assert not app.state.truth_tables._reports
        assert not client.get("/api/session").json()["field_network_open"]
