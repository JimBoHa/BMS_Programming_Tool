"""Same-ID imports must not erase canonical numeric source distinctions."""

import copy
import json
import math
import os
from pathlib import Path

import pytest
from bms_tool.app import create_app
from bms_tool.macros import import_macro_library
from bms_tool.models import Edge, Node, Program, canonical
from fastapi.testclient import TestClient


def bundle(default=0.0, *, metadata_value=None, name="Source identity"):
    graph = Program(
        id="identity",
        nodes=[
            Node(id="value", kind="Input", params={"default": default}),
            Node(id="result", kind="Output"),
        ],
        edges=[Edge(id="publish", source="value", target="result")],
        metadata={"nested": {"a": metadata_value, "b": "keep"}},
    )
    return {
        "format": "bms-macro-library/1",
        "root": "identity",
        "library": {
            "version": 1,
            "definitions": [{"id": "identity", "name": name, "program": graph.model_dump()}],
        },
    }


def parent(value):
    return import_macro_library(Program(id="existing", metadata={"notes": "preserve"}), value)


PAIRS = pytest.mark.parametrize(
    "before,after",
    [pytest.param(-0.0, 0.0, id="negative-zero"), pytest.param(0, 0.0, id="integral-float")],
)


@PAIRS
def test_default_numeric_identity_conflict_is_refused_without_mutating_input(before, after):
    root = parent(bundle(before))
    prior = canonical(root)
    candidate = bundle(after)
    assert canonical(
        Program.model_validate(candidate["library"]["definitions"][0]["program"])
    ) != canonical(Program.model_validate(root.metadata["macros"]["definitions"][0]["program"]))
    with pytest.raises(ValueError, match="identifier conflict"):
        import_macro_library(root, candidate)
    assert canonical(root) == prior


@PAIRS
def test_metadata_numeric_identity_is_also_part_of_the_definition(before, after):
    root = parent(bundle(metadata_value=before))
    prior = canonical(root)
    with pytest.raises(ValueError, match="identifier conflict"):
        import_macro_library(root, bundle(metadata_value=after))
    assert canonical(root) == prior


def test_name_conflict_and_canonical_identical_reordering():
    root = parent(bundle(-0.0, metadata_value=1.0))
    prior = canonical(root)
    with pytest.raises(ValueError, match="identifier conflict"):
        import_macro_library(root, bundle(-0.0, metadata_value=1.0, name="Other name"))
    candidate = reordered(bundle(-0.0, metadata_value=1.0))
    result = import_macro_library(root, candidate)
    assert canonical(result) == prior == canonical(root)
    assert (
        math.copysign(
            1,
            result.metadata["macros"]["definitions"][0]["program"]["nodes"][0]["params"]["default"],
        )
        < 0
    )


def reordered(value):
    if isinstance(value, dict):
        return {key: reordered(child) for key, child in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reordered(child) for child in value]
    return copy.deepcopy(value)


@PAIRS
def test_actual_API_conflict_returns_original_editor_authority(before, after, tmp_path):
    root = parent(bundle(before))
    prior = canonical(root)
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            "/api/macros/import",
            json={"program": root.model_dump(), "bundle": bundle(after)},
            headers=headers | {"X-Studio-Program-Source": "true"},
        )
        evidence = os.environ.get("BMS_MACRO_IDENTITY_EVIDENCE")
        if evidence:
            folder = Path(evidence) / (
                "negative-zero" if math.copysign(1, before) < 0 else "integral-float"
            )
            folder.mkdir(parents=True, exist_ok=False)
            (folder / "original-response.json").write_bytes(response.content)
            (folder / "original-program.json").write_bytes(prior)
            (folder / "response-status.json").write_text(
                json.dumps({"status_code": response.status_code}) + "\n"
            )
        assert response.status_code == 422, response.text
        assert "identifier conflict" in response.json()["detail"]
        assert canonical(root) == prior
        assert client.get("/api/projects").json() == []
        assert not client.get("/api/session").json()["field_network_open"]


def test_actual_API_canonical_reorder_is_idempotent(tmp_path):
    root = parent(bundle(-0.0, metadata_value=1.0))
    prior = canonical(root)
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            "/api/macros/import",
            json={
                "program": root.model_dump(),
                "bundle": reordered(bundle(-0.0, metadata_value=1.0)),
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert canonical(Program.model_validate(response.json())) == prior == canonical(root)
