"""Real local HTTP/SQLite workflows; every field transport is forbidden."""

import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.plant_signals import PROFILE, encoded
from fastapi.testclient import TestClient

from .test_plant_signals import make_case, programs


def test_http_exact_sources_reviews_import_restart_and_no_field_operations(tmp_path, monkeypatch):
    app = create_app(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Engineering source library must never access field transport")

    monkeypatch.setattr(app.state.bacnet, "require", forbidden)
    monkeypatch.setattr(app.state.bacnet, "connect", forbidden)
    with TestClient(app) as client:
        profile = client.get("/api/plant-signals/profile").json()
        assert profile["profile"] == PROFILE and profile["sources"] == profile["captures"] == []
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for path in [
            "sources/import",
            "sources/export",
            "sources/remove",
            "review",
            "reviews/export/json",
            "captures/save",
            "captures/import",
            "captures/open",
            "captures/export/json",
            "captures/remove",
        ]:
            assert client.post("/api/plant-signals/" + path, json={}).status_code == 403
        imported = []
        for program in programs():
            raw = program.model_dump_json().encode()
            response = client.post(
                "/api/plant-signals/sources/import",
                files={"file": ("program.json", raw)},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            source = response.json()
            imported.append(source)
            assert source["id"] == hashlib.sha256(raw).hexdigest() and "source_json" not in source
            original = client.post(
                "/api/plant-signals/sources/export", json={"id": source["id"]}, headers=headers
            )
            assert original.content == raw and original.headers["x-file-sha256"] == source["id"]
        _, plan = make_case(tmp_path / "fixture-only")
        assert [row["source_id"] for row in plan["instances"]] == [row["id"] for row in imported]
        response = client.post(
            "/api/plant-signals/review",
            json={"profile_sha256": PROFILE["sha256"], "plan": plan},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        view = response.json()
        assert view["analysis"]["status"] == "software_consistent"
        key = {"id": view["id"], "content_sha256": view["content_sha256"]}
        exported = client.post("/api/plant-signals/reviews/export/json", json=key, headers=headers)
        raw = exported.content
        assert hashlib.sha256(raw).hexdigest() == exported.headers["x-file-sha256"]
        assert b"9007199254740993" in raw and b"-0.0" in raw
        report = json.loads(raw)
        assert encoded(report) + b"\n" == raw
        assert all("source_json" in source for source in report["sources"])
        csv_result = client.post("/api/plant-signals/reviews/export/csv", json=key, headers=headers)
        assert csv_result.status_code == 200 and b"revision_text" in csv_result.content
        assert (
            b"hardware_verified" in csv_result.content
            and b"native_mapping_verified" in csv_result.content
        )
        assert (
            b"Flow sender" in csv_result.content and b"Declared source host" in csv_result.content
        )
        saved = client.post("/api/plant-signals/captures/save", json=key, headers=headers)
        assert saved.status_code == 200, saved.text
        capture = saved.json()
        assert capture["origin"] == "local-review"
        duplicate = client.post(
            "/api/plant-signals/captures/import",
            files={"file": ("review.json", raw)},
            headers=headers,
        )
        assert (
            duplicate.json()["deduplicated"]
            and duplicate.json()["ingested_at"] == capture["ingested_at"]
        )
        bad_key = client.post(
            "/api/plant-signals/captures/save",
            json=key | {"content_sha256": "0" * 64},
            headers=headers,
        )
        assert bad_key.status_code == 422 and len(app.state.plant_signals.status()["captures"]) == 1
        assert not client.get("/api/session").json()["field_network_open"]
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        profile = client.get("/api/plant-signals/profile").json()
        assert not profile["sources"] and len(profile["captures"]) == 1
        opened = client.post(
            "/api/plant-signals/captures/open", json={"id": capture["id"]}, headers=headers
        )
        assert opened.status_code == 200 and opened.json()["review"] == view
        assert (
            client.post("/api/plant-signals/reviews/export/json", json=key, headers=headers).content
            == raw
        )
        assert (
            client.post(
                "/api/plant-signals/captures/export/json",
                json={"id": capture["id"]},
                headers=headers,
            ).content
            == raw
        )
        assert len(client.get("/api/plant-signals/profile").json()["sources"]) == 2
        assert (
            client.post(
                "/api/plant-signals/captures/remove", json={"id": capture["id"]}, headers=headers
            ).status_code
            == 200
        )
        assert client.get("/api/plant-signals/profile").json()["captures"] == []
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize(
    "raw",
    [b'{"plan":{},"plan":{}}', b'{"plan":NaN}', b'{"plan":1e999}', b"null", b"[]", b"\xff"],
    ids=["duplicate", "nan", "overflow", "null", "array", "unicode"],
)
def test_http_malformed_documents_have_no_retained_side_effects(tmp_path, raw):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        result = client.post(
            "/api/plant-signals/review",
            content=raw,
            headers=headers | {"Content-Type": "application/json"},
        )
        assert result.status_code == 422
        for path in ["sources/import", "captures/import"]:
            assert (
                client.post(
                    "/api/plant-signals/" + path, files={"file": ("bad.json", raw)}, headers=headers
                ).status_code
                == 422
            )
        status = client.get("/api/plant-signals/profile").json()
        assert status["sources"] == status["captures"] == []
        assert not client.get("/api/session").json()["field_network_open"]


def test_import_recomputes_self_sealed_analysis_exact_types_and_never_opens_field(tmp_path):
    service, plan = make_case(tmp_path / "fixture")
    from .test_plant_signals import reviewed

    _, key = reviewed(service, plan)
    raw = service.export_review(key, "json")
    from bms_tool.plant_signals import digest

    document = json.loads(raw)
    document["analysis"]["hardware_verified"] = 0
    document["content_sha256"] = digest(
        {k: v for k, v in document.items() if k != "content_sha256"}
    )
    with TestClient(create_app(tmp_path / "api")) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/plant-signals/captures/import",
                files={"file": ("bad.json", encoded(document))},
                headers=headers,
            ).status_code
            == 422
        )
        good = client.post(
            "/api/plant-signals/captures/import",
            files={"file": ("report.json", raw)},
            headers=headers,
        )
        assert good.status_code == 200 and good.json()["origin"] == "import"
        profile = client.get("/api/plant-signals/profile").json()
        assert profile["sources"] == []
        assert (
            client.post(
                "/api/plant-signals/captures/open", json={"id": good.json()["id"]}, headers=headers
            ).status_code
            == 200
        )
        assert not client.get("/api/session").json()["field_network_open"]
