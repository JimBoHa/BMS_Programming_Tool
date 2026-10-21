"""Exercise source re-open and durable local scenarios through HTTP boundaries."""

from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.caf_scenarios import CafInputScenarios
from fastapi.testclient import TestClient

from tests.test_caf_scenarios import scenario
from tests.test_caf_simulation import make_caf


def opened(client):
    headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
    sha = client.post(
        "/api/caf", headers=headers, files={"file": ("authored.caf", make_caf())}
    ).json()["sha256"]
    return headers, f"/api/caf/{sha}/local-scenarios"


def test_save_preview_reopen_after_app_restart_and_native_startup_bridge(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers, base = opened(client)
        contract = client.get(base).json()
        assert len(contract["contract"]["inputs"]) == 2
        assert contract["saved"] == []
        assert contract["template"] == CafInputScenarios(CafArchive(make_caf())).template()
        saved = client.post(
            base + "/save", headers=headers, json={"scenario": scenario(), "expected_revision": 0}
        )
        assert saved.status_code == 200, saved.text
        saved = saved.json()
        preview = client.post(base + "/preview", headers=headers, json={"scenario": scenario()})
        assert preview.status_code == 200
        assert [row["time"] for row in preview.json()["frames"]] == [0, 0.25, 1, 1.5, 2]
        profile = client.post(
            base + "/startup-profile", headers=headers, json={"scenario": scenario(), "time": 2}
        ).json()["profile"]
        exported = client.post(
            base.replace("/local-scenarios", "/simulation"),
            headers=headers,
            json={"profile": profile},
        )
        assert exported.status_code == 200
        assert b"<float>+1.25e1</float>" in CafArchive(exported.content).xml
        assert not client.get("/api/bacnet/status").json()["connected"]
    # Source CAFs deliberately are not persisted. Reopen exact source to validate saved scenarios.
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(base).status_code == 422
        headers, reopened_base = opened(client)
        assert reopened_base == base
        assert client.get(base).json()["saved"][0]["id"] == saved["id"]
        assert client.get(base + "/" + saved["id"]).json() == saved
        conflict = client.post(
            base + "/save",
            headers=headers,
            json={"scenario": scenario(), "id": saved["id"], "expected_revision": 0},
        )
        assert conflict.status_code == 409
        deleted = client.request(
            "DELETE", base + "/" + saved["id"], headers=headers, json={"expected_revision": 1}
        )
        assert deleted.status_code == 200
        assert client.get(base).json()["saved"] == []
        assert not client.get("/api/bacnet/status").json()["connected"]
    assert not list(tmp_path.rglob("*.caf"))


def test_http_guards_native_quality_refusal_and_cached_source_unchanged(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers, base = opened(client)
        data = scenario()
        data["profile_sha256"] = "0" * 64
        for path in ("validate", "preview", "save"):
            payload = {"scenario": data}
            if path == "save":
                payload["expected_revision"] = 0
            assert client.post(base + "/" + path, json=payload, headers=headers).status_code == 422
        assert (
            client.post(
                base + "/save", json={"scenario": scenario(), "expected_revision": 0}
            ).status_code
            == 403
        )
        assert (
            client.post(
                base + "/save",
                json={"scenario": scenario(), "expected_revision": True},
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.post(
                base + "/startup-profile", json={"scenario": scenario(), "time": 1}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                base + "/validate",
                json={"scenario": scenario(), "unexpected": True},
                headers=headers,
            ).status_code
            == 422
        )
        exported = client.post(
            base.replace("/local-scenarios", "/export"), headers=headers, json={"changes": []}
        )
        assert exported.content == make_caf()
        assert client.get(base).json()["saved"] == []
