"""Test saved native simulation profiles through the production API boundaries."""

import copy

from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.caf_simulation import CafSimulationProfile
from fastapi.testclient import TestClient

from tests.test_caf_simulation import make_caf


def test_native_simulation_profile_api_edits_and_preserves_cached_source(tmp_path):
    original = make_caf()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        opened = client.post(
            "/api/caf", files={"file": ("synthetic.caf", original)}, headers=headers
        )
        assert opened.status_code == 200
        sha = opened.json()["sha256"]
        summary = client.get(f"/api/caf/{sha}/simulation")
        assert summary.status_code == 200
        assert summary.json()["counts"]["editable"] == 3
        profile = client.get(f"/api/caf/{sha}/simulation/profile").json()
        profile["entries"][0]["value"] = "73.25"
        profile["entries"][2]["value"] = "1"
        exported = client.post(
            f"/api/caf/{sha}/simulation", json={"profile": profile}, headers=headers
        )
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-disposition"].endswith('.caf"')
        assert CafArchive(exported.content).xml == CafArchive(original).xml.replace(
            b"<float>70.000</float>", b"<float>73.25</float>"
        ).replace(b"<boolean>0</boolean>", b"<boolean>1</boolean>")
        assert (
            client.get(f"/api/caf/{sha}/simulation/profile").json()
            == CafSimulationProfile(original).export_profile()
        )
        cached = client.post(f"/api/caf/{sha}/export", json={"changes": []}, headers=headers)
        assert cached.content == original
        assert not client.get("/api/bacnet/status").json()["connected"]


def test_native_simulation_profile_api_rejects_stale_unsupported_and_unsafe_values(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        sha = client.post(
            "/api/caf", files={"file": ("synthetic.caf", make_caf())}, headers=headers
        ).json()["sha256"]
        profile = client.get(f"/api/caf/{sha}/simulation/profile").json()
        bad = []
        stale = copy.deepcopy(profile)
        stale["source_sha256"] = "0" * 64
        bad.append(stale)
        nonfinite = copy.deepcopy(profile)
        nonfinite["entries"][0]["value"] = "NaN"
        bad.append(nonfinite)
        enum = copy.deepcopy(profile)
        enum["entries"][3]["value"] = "2"
        bad.append(enum)
        for item in bad:
            response = client.post(
                f"/api/caf/{sha}/simulation", json={"profile": item}, headers=headers
            )
            assert response.status_code == 422
        assert (
            client.post(f"/api/caf/{sha}/simulation", json={"profile": profile}).status_code == 403
        )
        assert client.get("/api/caf/missing/simulation").status_code == 422
