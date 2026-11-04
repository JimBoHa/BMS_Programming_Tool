"""Source-bound local variable-object review/export, never a controller action."""

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.moi_identity import seal, sha
from fastapi.testclient import TestClient

from tests.test_caf_boolean_logic_copy import ORDERS, PROTOTYPE, REF, example


@pytest.fixture
def opened(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        original = example(order=ORDERS[1], zero=True)
        identity = sha(original)
        assert (
            client.post(
                "/api/caf", headers=h, files={"file": ("boolean-logic.caf", original)}
            ).status_code
            == 200
        )
        base = f"/api/caf/{identity}/boolean-logic-copy"
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
        raise AssertionError("Local boolean-logic attempted field access")

    monkeypatch.setattr("socket.create_connection", field)
    review = client.post(base + "/preview", headers=h, json=proposal)
    assert review.status_code == 200
    data = review.json()
    s = data["creation"]["selection"]
    assert (
        s["object_count"] == 5
        and len(s["children"]) == 4
        and s["operator_meaning_verified"] is False
    )
    assert [r["new_instance"] for r in s["children"]] == [32, 33, 34, 35]
    assert (
        s["new_output_instance"] == 33
        and data["creation"]["new_output_sha256"] == data["creation"]["new_child_sha256"][1]
    )
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
    assert response.headers["Content-Disposition"].endswith('caf-boolean-logic-copy.caf"')
    assert len(CafArchive(response.content).objects) == len(CafArchive(original).objects) + 5
    assert (
        client.post(
            base.replace("/boolean-logic-copy", "/export"), headers=h, json={"changes": []}
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
        {"prototype_ref": REF + ".5_20"},
        {"x": "NaN"},
        {"y": "1e100"},
        {"kind": "float"},
        {"operator_meaning_verified": True},
        {"x": True},
        {"object_count": 5},
        {"setup_code": 17},
    ],
)
def test_stale_forged_or_unknown_boolean_logic_request_is_refused(opened, change):
    client, h, base, _, proposal, _ = opened
    assert client.post(base + "/preview", headers=h, json=proposal | change).status_code == 422


def test_boolean_logic_token_review_and_profile_isolation(opened):
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
        "timer-copy",
    ):
        assert (
            client.post(
                base.replace("boolean-logic-copy", kind) + "/source", headers=h, json=request
            ).status_code
            == 422
        )


@pytest.mark.parametrize("order", [ORDERS[0], ORDERS[1], ORDERS[1]])
def test_each_size_and_output_position_has_its_own_exact_export(tmp_path, order):
    original = example(order=order, zero=True)
    identity = sha(original)
    with TestClient(create_app(tmp_path)) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/caf", headers=h, files={"file": ("boolean-logic.caf", original)}
            ).status_code
            == 200
        )
        base = f"/api/caf/{identity}/boolean-logic-copy"
        request = {"source_sha256": identity, "diagram_ref": REF, "prototype_ref": PROTOTYPE}
        source = client.post(base + "/source", headers=h, json=request).json()
        assert source["object_count"] == len(order) + 1 and source[
            "new_output_instance"
        ] == 32 + order.index(85)
        proposal = {
            **request,
            "selection_sha256": source["selection_sha256"],
            "x": "81.000",
            "y": "42.000",
        }
        review = client.post(base + "/preview", headers=h, json=proposal)
        assert review.status_code == 200
        creation = review.json()["creation"]
        assert creation["new_output_sha256"] == creation["new_child_sha256"][order.index(85)]
        exported = client.post(
            base + "/export",
            headers=h,
            json={**proposal, "review_sha256": review.json()["review_sha256"]},
        )
        assert exported.status_code == 200 and sha(exported.content) == creation["output_sha256"]
        assert (
            len(CafArchive(exported.content).objects)
            == len(CafArchive(original).objects) + len(order) + 1
        )
