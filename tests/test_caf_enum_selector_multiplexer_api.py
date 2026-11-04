"""Source-bound local variable-object review/export, never a controller action."""

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.moi_identity import seal, sha
from fastapi.testclient import TestClient

from tests.test_caf_enum_selector_multiplexer_copy import PROTOTYPE, REF, example


@pytest.fixture
def opened(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        original = example(zero=True)
        identity = sha(original)
        assert (
            client.post(
                "/api/caf", headers=h, files={"file": ("float_multiplexer.caf", original)}
            ).status_code
            == 200
        )
        base = f"/api/caf/{identity}/float-multiplexer-copy"
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


def test_seven_object_copy_has_exact_review_proof_and_unchanged_original(opened, monkeypatch):
    client, h, base, request, proposal, original = opened

    def field(*args, **kwargs):
        raise AssertionError("Local float_multiplexer attempted field access")

    monkeypatch.setattr("socket.create_connection", field)
    review = client.post(base + "/preview", headers=h, json=proposal)
    assert review.status_code == 200
    data = review.json()
    s = data["creation"]["selection"]
    assert (
        s["object_count"] == 7
        and len(s["children"]) == 6
        and s["operator_meaning_verified"] is False
    )
    assert [r["new_instance"] for r in s["children"]] == [32, 33, 34, 35, 36, 37]
    assert (
        s["new_output_instance"] == 32
        and data["creation"]["new_output_sha256"] == data["creation"]["new_child_sha256"][0]
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
    assert response.headers["Content-Disposition"].endswith('caf-float-multiplexer-copy.caf"')
    assert len(CafArchive(response.content).objects) == len(CafArchive(original).objects) + 7
    assert (
        client.post(
            base.replace("/float-multiplexer-copy", "/export"), headers=h, json={"changes": []}
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
def test_stale_forged_or_unknown_float_multiplexer_request_is_refused(opened, change):
    client, h, base, _, proposal, _ = opened
    assert client.post(base + "/preview", headers=h, json=proposal | change).status_code == 422


def test_float_multiplexer_token_review_and_profile_isolation(opened):
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
        "boolean-logic-copy",
        "reliability-copy",
    ):
        assert (
            client.post(
                base.replace("float-multiplexer-copy", kind) + "/source", headers=h, json=request
            ).status_code
            == 422
        )


@pytest.mark.parametrize("zero", [False, True])
@pytest.mark.parametrize("spelling", ["100", "100.000000"])
def test_zip_attribute_variants_have_exact_typed_review_and_export(tmp_path, zero, spelling):
    original = example(zero=zero, spelling=spelling)
    identity = sha(original)
    with TestClient(create_app(tmp_path)) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/caf", headers=h, files={"file": ("multiplexer.caf", original)}
            ).status_code
            == 200
        )
        base = f"/api/caf/{identity}/float-multiplexer-copy"
        request = {"source_sha256": identity, "diagram_ref": REF, "prototype_ref": PROTOTYPE}
        s = client.post(base + "/source", headers=h, json=request).json()
        assert (
            s["object_count"] == 7
            and s["setup_code"] is None
            and s["multiplexer_semantics_verified"] is False
        )
        assert (
            s["recorded_property_2381"] == ["0", "2", "0", "0", "3", "4"]
            and s["recorded_property_3122"] == "1"
        )
        assert (
            s["enum_semantics_verified"] is False
            and s["children"][5]["number_of_states"] == 6
            and s["children"][4]["recorded_default"] == spelling
        )
        proposal = {
            **request,
            "selection_sha256": s["selection_sha256"],
            "x": "81.000",
            "y": "42.000",
        }
        review = client.post(base + "/preview", headers=h, json=proposal)
        assert review.status_code == 200
        creation = review.json()["creation"]
        assert (
            creation["new_output_sha256"] == creation["new_child_sha256"][0]
            and len(creation["new_child_sha256"]) == 6
        )
        response = client.post(
            base + "/export",
            headers=h,
            json={**proposal, "review_sha256": review.json()["review_sha256"]},
        )
        assert (
            response.status_code == 200
            and sha(response.content) == creation["output_sha256"]
            and len(CafArchive(response.content).objects) == len(CafArchive(original).objects) + 7
        )
        assert (
            CafArchive(response.content).info.external_attr
            == CafArchive(original).info.external_attr
        )


def test_repeated_local_export_is_deterministic_without_mutating_source(opened):
    client, h, base, request, proposal, original = opened
    review = client.post(base + "/preview", headers=h, json=proposal).json()
    body = {**proposal, "review_sha256": review["review_sha256"]}
    first = client.post(base + "/export", headers=h, json=body)
    second = client.post(base + "/export", headers=h, json=body)
    assert first.status_code == second.status_code == 200 and first.content == second.content
    assert (
        client.post(
            base.replace("/float-multiplexer-copy", "/export"), headers=h, json={"changes": []}
        ).content
        == original
    )
    assert (
        client.post(base + "/source", headers=h, json=request).json()
        == review["creation"]["selection"]
    )
