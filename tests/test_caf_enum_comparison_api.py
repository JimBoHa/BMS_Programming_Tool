"""Source-bound local five-object review/export, never a controller action."""

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.moi_identity import seal, sha
from fastapi.testclient import TestClient

from tests.test_caf_enum_comparison_copy import PROTOTYPE, REF, example


@pytest.fixture
def opened(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        original = example(zero=True)
        identity = sha(original)
        assert (
            client.post(
                "/api/caf", headers=h, files={"file": ("comparison.caf", original)}
            ).status_code
            == 200
        )
        base = f"/api/caf/{identity}/comparison-copy"
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


def test_enum_input_copy_has_exact_review_proof_and_unchanged_original(opened, monkeypatch):
    client, h, base, request, proposal, original = opened

    def field(*args, **kwargs):
        raise AssertionError("Local comparison attempted field access")

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
    assert s["enum_semantics_verified"] is False and not s["children"][1]["exposed"]
    assert (
        s["children"][2]["states_text_code"] == 387
        and s["children"][2]["default_encoding_set"] == 647
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
    assert response.headers["Content-Disposition"].endswith('caf-comparison-copy.caf"')
    assert len(CafArchive(response.content).objects) == len(CafArchive(original).objects) + 5
    assert (
        client.post(
            base.replace("/comparison-copy", "/export"), headers=h, json={"changes": []}
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
        {"setup_code": 5},
    ],
)
def test_stale_forged_or_unknown_comparison_request_is_refused(opened, change):
    client, h, base, _, proposal, _ = opened
    assert client.post(base + "/preview", headers=h, json=proposal | change).status_code == 422


def test_comparison_token_review_and_profile_isolation(opened):
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
    for kind in ("constant-copy", "boolean-constant-copy", "enum-constant-copy", "math-copy"):
        assert (
            client.post(
                base.replace("comparison-copy", kind) + "/source", headers=h, json=request
            ).status_code
            == 422
        )


@pytest.mark.parametrize(
    "states,encoding,omitted",
    [
        (4, 647, False),
        (4, "matching", False),
        (6, 647, False),
        (6, "matching", False),
        (4, 647, True),
        (6, 647, True),
    ],
)
def test_actual_enum_metadata_and_default_namespaces_survive_same_comparison_api(
    tmp_path, states, encoding, omitted
):
    original = example(states=states, encoding=encoding, omitted=omitted, zero=True)
    identity = sha(original)
    with TestClient(create_app(tmp_path)) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/caf", headers=h, files={"file": ("comparison.caf", original)}
            ).status_code
            == 200
        )
        base = f"/api/caf/{identity}/comparison-copy"
        request = {"source_sha256": identity, "diagram_ref": REF, "prototype_ref": PROTOTYPE}
        source = client.post(base + "/source", headers=h, json=request).json()
        assert (
            source["profile"] == "caf-recorded-enumeration-comparison-copy/1"
            and source["enum_semantics_verified"] is False
        )
        expected = None if omitted else 647 if encoding == 647 else 366 if states == 4 else 387
        assert (
            source["children"][3]["default_encoding_set"] == expected
            and source["children"][3]["number_of_states"] == states
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
        assert len(CafArchive(exported.content).objects) == 13
