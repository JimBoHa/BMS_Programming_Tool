"""HTTP admission and exact local artifact/review proof for constant copies."""

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.moi_identity import seal, sha
from fastapi.testclient import TestClient

from tests.test_caf_constant_copy import PROTOTYPE, REF, example


@pytest.fixture
def opened(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        original = example(zero=True)
        identity = client.post(
            "/api/caf", headers=headers, files={"file": ("authored.caf", original)}
        ).json()["sha256"]
        base = f"/api/caf/{identity}/constant-copy"
        source_request = {"source_sha256": identity, "diagram_ref": REF, "prototype_ref": PROTOTYPE}
        source = client.post(base + "/source", headers=headers, json=source_request)
        assert source.status_code == 200
        proposal = {
            **source_request,
            "selection_sha256": source.json()["selection_sha256"],
            "x": "81.000",
            "y": "42.000",
        }
        yield client, headers, base, source_request, proposal, original


def test_exact_review_export_and_original_reopen_without_any_field_operation(opened, monkeypatch):
    client, headers, base, source, proposal, original = opened

    # Any field call would fail this offline API test.
    def field(*args, **kwargs):
        raise AssertionError("Local CAF creation attempted a field operation")

    monkeypatch.setattr("socket.create_connection", field)
    review = client.post(base + "/preview", headers=headers, json=proposal)
    assert review.status_code == 200
    reviewed = review.json()
    assert reviewed["review_sha256"] == seal(
        {k: v for k, v in reviewed.items() if k != "review_sha256"}
    )
    export = client.post(
        base + "/export",
        headers=headers,
        json={**proposal, "review_sha256": reviewed["review_sha256"]},
    )
    assert export.status_code == 200
    assert (
        sha(export.content)
        == reviewed["creation"]["output_sha256"]
        == export.headers["X-Studio-Artifact-Sha256"]
    )
    assert export.headers["X-Studio-Review-Sha256"] == reviewed["review_sha256"]
    assert export.headers["X-Studio-Source-Sha256"] == source["source_sha256"]
    assert export.headers["X-Studio-Creation-Sha256"] == reviewed["creation"]["creation_sha256"]
    assert len(CafArchive(export.content).objects) == len(CafArchive(original).objects) + 2
    unchanged = client.post(
        base.replace("/constant-copy", "/export"), headers=headers, json={"changes": []}
    )
    assert unchanged.content == original
    assert not reviewed["controller_write"] and not reviewed["field_transfer_enabled"]
    patterns = {
        route.path for route in client.app.routes if "/constant-copy/" in getattr(route, "path", "")
    }
    # FastAPI may keep included routers lazy; assert actual absence of an Apply operation too.
    assert not any(path.endswith("/apply") for path in patterns)
    assert client.post(base + "/apply", headers=headers, json=proposal).status_code in {404, 405}


@pytest.mark.parametrize(
    "update",
    [
        {"source_sha256": "0" * 64},
        {"selection_sha256": "0" * 64},
        {"prototype_ref": REF + ".2_20"},
        {"diagram_ref": "absent"},
        {"x": "NaN"},
        {"y": "1e100"},
    ],
)
def test_stale_or_unsupported_proposals_refused(opened, update):
    client, headers, base, _, proposal, _ = opened
    response = client.post(base + "/preview", headers=headers, json=proposal | update)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "update",
    [
        {"new_instance": 31},
        {"controller_write": True},
        {"x": 81},
        {"y": True},
        {"source_sha256": 2},
        {"prototype_ref": "a" * 513},
        {"selection_sha256": "bad"},
        {"x": "1" * 81},
    ],
)
def test_strict_request_rejects_unknown_authority_and_coercion(opened, update):
    client, headers, base, _, proposal, _ = opened
    assert (
        client.post(base + "/preview", headers=headers, json=proposal | update).status_code == 422
    )


def test_token_review_and_changed_position_are_enforced(opened):
    client, headers, base, source, proposal, _ = opened
    assert client.post(base + "/source", json=source).status_code == 403
    assert client.post(base + "/preview", json=proposal).status_code == 403
    review = client.post(base + "/preview", headers=headers, json=proposal).json()
    for update in ({"review_sha256": "0" * 64}, {"x": "82"}):
        assert (
            client.post(
                base + "/export",
                headers=headers,
                json={**proposal, "review_sha256": review["review_sha256"], **update},
            ).status_code
            == 422
        )
    unopened = base.replace(source["source_sha256"], "1" * 64)
    assert client.post(unopened + "/source", headers=headers, json=source).status_code == 422
