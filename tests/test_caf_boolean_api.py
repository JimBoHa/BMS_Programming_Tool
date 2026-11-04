"""Boolean-only local routes preserve the original Float source/review contract."""

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.moi_identity import seal, sha
from fastapi.testclient import TestClient

from tests.test_caf_boolean_copy import PROTOTYPE, REF, example


@pytest.fixture
def opened(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        original = example(zero=True)
        identity = sha(original)
        assert (
            client.post(
                "/api/caf", headers=headers, files={"file": ("boolean.caf", original)}
            ).status_code
            == 200
        )
        base = f"/api/caf/{identity}/boolean-constant-copy"
        request = {"source_sha256": identity, "diagram_ref": REF, "prototype_ref": PROTOTYPE}
        source = client.post(base + "/source", headers=headers, json=request)
        assert source.status_code == 200
        proposal = {
            **request,
            "selection_sha256": source.json()["selection_sha256"],
            "x": "81.000",
            "y": "42.000",
        }
        yield client, headers, base, request, proposal, original


def test_boolean_export_requires_exact_review_headers_and_keeps_original(opened, monkeypatch):
    client, h, base, request, proposal, original = opened

    def field(*args, **kwargs):
        raise AssertionError("Local Boolean copy attempted field access")

    monkeypatch.setattr("socket.create_connection", field)
    review = client.post(base + "/preview", headers=h, json=proposal)
    assert review.status_code == 200
    data = review.json()
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
    assert response.headers["Content-Disposition"].endswith('caf-boolean-constant-copy.caf"')
    assert len(CafArchive(response.content).objects) == len(CafArchive(original).objects) + 2
    assert (
        client.post(
            base.replace("/boolean-constant-copy", "/export"), headers=h, json={"changes": []}
        ).content
        == original
    )
    assert client.post(base + "/apply", headers=h, json=proposal).status_code in {404, 405}
    assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize(
    "change",
    [
        {"source_sha256": "0" * 64},
        {"selection_sha256": "0" * 64},
        {"prototype_ref": REF + ".558_20"},
        {"x": "NaN"},
        {"y": "1e100"},
        {"kind": "float"},
        {"field_transfer_enabled": True},
        {"x": True},
    ],
)
def test_stale_unknown_or_cross_profile_boolean_request_is_refused(opened, change):
    client, h, base, _, proposal, _ = opened
    assert client.post(base + "/preview", headers=h, json=proposal | change).status_code == 422


def test_boolean_token_and_review_proof_cannot_be_reused_for_changed_position_or_float(opened):
    client, h, base, request, proposal, _ = opened
    assert client.post(base + "/source", json=request).status_code == 403
    assert client.post(base + "/preview", json=proposal).status_code == 403
    reviewed = client.post(base + "/preview", headers=h, json=proposal).json()
    for change in ({"review_sha256": "0" * 64}, {"x": "82"}):
        assert (
            client.post(
                base + "/export",
                headers=h,
                json={**proposal, "review_sha256": reviewed["review_sha256"], **change},
            ).status_code
            == 422
        )
    assert (
        client.post(
            base.replace("/boolean-constant-copy", "/constant-copy") + "/source",
            headers=h,
            json=request,
        ).status_code
        == 422
    )
