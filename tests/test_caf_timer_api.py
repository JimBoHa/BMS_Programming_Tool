"""Source-bound local eight-object review/export, never a controller action."""

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.moi_identity import seal, sha
from fastapi.testclient import TestClient

from tests.test_caf_timer_copy import PROTOTYPE, REF, example


@pytest.fixture
def opened(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        original = example(zero=True)
        identity = sha(original)
        assert (
            client.post("/api/caf", headers=h, files={"file": ("timer.caf", original)}).status_code
            == 200
        )
        base = f"/api/caf/{identity}/timer-copy"
        request = {"source_sha256": identity, "diagram_ref": REF, "prototype_ref": PROTOTYPE}
        source = client.post(base + "/source", headers=h, json=request)
        assert source.status_code == 200
        proposal = {
            **request,
            "selection_sha256": source.json()["selection_sha256"],
            "x": "81.000",
            "y": "42.000",
        }
        yield client, h, base, request, proposal, original


def test_five_object_copy_has_exact_review_proof_and_unchanged_original(opened, monkeypatch):
    client, h, base, request, proposal, original = opened

    def field(*args, **kwargs):
        raise AssertionError("Local timer attempted field access")

    monkeypatch.setattr("socket.create_connection", field)
    review = client.post(base + "/preview", headers=h, json=proposal)
    assert review.status_code == 200
    data = review.json()
    s = data["creation"]["selection"]
    assert (
        s["object_count"] == 8
        and len(s["children"]) == 7
        and s["operator_meaning_verified"] is False
    )
    assert [r["new_instance"] for r in s["children"]] == [32, 33, 34, 35, 36, 37, 38]
    assert s["setup_code"] is None and s["timer_semantics_verified"] is False
    assert [r["port"] for r in s["children"] if r["direction"] == "output"] == [85, 1081]
    assert data["review_sha256"] == seal({k: v for k, v in data.items() if k != "review_sha256"})
    response = client.post(
        base + "/export", headers=h, json={**proposal, "review_sha256": data["review_sha256"]}
    )
    assert response.status_code == 200
    assert (
        response.headers["X-Studio-Artifact-Sha256"]
        == sha(response.content)
        == data["creation"]["output_sha256"]
    )
    assert response.headers["X-Studio-Review-Sha256"] == data["review_sha256"]
    assert response.headers["X-Studio-Source-Sha256"] == request["source_sha256"]
    assert response.headers["X-Studio-Creation-Sha256"] == data["creation"]["creation_sha256"]
    assert response.headers["Content-Disposition"].endswith('caf-timer-copy.caf"')
    assert len(CafArchive(response.content).objects) == len(CafArchive(original).objects) + 8
    assert (
        client.post(base.replace("/timer-copy", "/export"), headers=h, json={"changes": []}).content
        == original
    )
    assert client.post(base + "/apply", headers=h, json=proposal).status_code in {404, 405}
    assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize(
    "change",
    [
        {"source_sha256": "0" * 64},
        {"selection_sha256": "0" * 64},
        {"prototype_ref": REF + ".5_20"},
        {"x": "NaN"},
        {"y": "1e100"},
        {"kind": "float"},
        {"operator_meaning_verified": True},
        {"x": True},
        {"object_count": 8},
        {"setup_code": 0},
    ],
)
def test_stale_forged_or_unknown_timer_request_is_refused(opened, change):
    client, h, base, _, proposal, _ = opened
    assert client.post(base + "/preview", headers=h, json=proposal | change).status_code == 422


def test_timer_token_review_and_profile_isolation(opened):
    client, h, base, request, proposal, _ = opened
    assert client.post(base + "/source", json=request).status_code == 403
    assert client.post(base + "/preview", json=proposal).status_code == 403
    review = client.post(base + "/preview", headers=h, json=proposal).json()
    for change in ({"review_sha256": "0" * 64}, {"x": "82"}):
        assert (
            client.post(
                base + "/export",
                headers=h,
                json={**proposal, "review_sha256": review["review_sha256"], **change},
            ).status_code
            == 422
        )
    for kind in (
        "constant-copy",
        "boolean-constant-copy",
        "enum-constant-copy",
        "comparison-copy",
        "math-copy",
    ):
        assert (
            client.post(
                base.replace("timer-copy", kind) + "/source", headers=h, json=request
            ).status_code
            == 422
        )


@pytest.mark.parametrize("encoding,mode", [(647, "2"), (647, "4"), (21, "2"), (21, "4")])
def test_timer_api_preserves_recorded_mode_namespace_and_all_hidden_ports(tmp_path, encoding, mode):
    original = example(encoding=encoding, mode=mode, zero=True)
    identity = sha(original)
    with TestClient(create_app(tmp_path)) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post("/api/caf", headers=h, files={"file": ("timer.caf", original)}).status_code
            == 200
        )
        base = f"/api/caf/{identity}/timer-copy"
        request = {"source_sha256": identity, "diagram_ref": REF, "prototype_ref": PROTOTYPE}
        source = client.post(base + "/source", headers=h, json=request).json()
        assert (
            source["object_count"] == 8
            and source["children"][3]["default_encoding_set"] == encoding
            and source["children"][3]["recorded_default"] == mode
        )
        assert (
            sum(not r["exposed"] for r in source["children"]) == 4 and source["setup_code"] is None
        )
        proposal = {
            **request,
            "selection_sha256": source["selection_sha256"],
            "x": "81.000",
            "y": "42.000",
        }
        review = client.post(base + "/preview", headers=h, json=proposal)
        assert review.status_code == 200
        exported = client.post(
            base + "/export",
            headers=h,
            json={**proposal, "review_sha256": review.json()["review_sha256"]},
        )
        assert (
            exported.status_code == 200
            and sha(exported.content) == review.json()["creation"]["output_sha256"]
        )
        assert len(CafArchive(exported.content).objects) == 19
