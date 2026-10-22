"""Program-only source transport never changes storage or evidence canonicalization."""

import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.models import Node, Program, canonical
from bms_tool.program_source import (
    MAX_DEPTH,
    source_response,
    strict_source_json,
    unwrap_program_source,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError


def example(value=1.0):
    return Program(
        id="exact-numeric-source",
        name="Exact numeric source",
        nodes=[Node(id="number", kind="Constant", params={"value": value})],
        metadata={"opaque": {"array": [1.0, -0.0, 9007199254740993], "quoted": "1.0"}},
    )


def envelope(program):
    source = program.model_dump_json() if isinstance(program, Program) else program
    document = json.loads(source)
    return {
        "format": "bms.program-source/1",
        "source_json": source,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "program_id": document["id"],
        "revision_text": str(document.get("revision", 0)),
    }


def decode(response):
    body = response.json()
    assert body["format"] == "bms.program-source-response/1"
    assert hashlib.sha256(body["source_json"].encode()).hexdigest() == body["source_sha256"]
    return json.loads(body["source_json"]), body


@pytest.mark.parametrize(
    "value", [1.0, -0.0, 9007199254740993], ids=["float", "signed-zero", "large-integer"]
)
def test_envelope_model_and_response_keep_exact_canonical_program(value):
    program = example(value)
    restored = Program.model_validate(envelope(program))
    assert canonical(restored) == canonical(program)
    assert restored.digest() == program.digest()
    response = source_response(program, True)
    assert Program.model_validate_json(response["source_json"]).digest() == program.digest()
    assert response["programs"] == [
        {
            "path": [],
            "program_id": program.id,
            "revision_text": "0",
            "canonical_sha256": program.digest(),
            "canonical_format": "canonical-json/1",
        }
    ]
    assert source_response(program) is program


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e.update(source_sha256="0" * 64),
        lambda e: e.update(program_id="other"),
        lambda e: e.update(revision_text="00"),
        lambda e: e.update(extra="unknown"),
    ],
    ids=["hash", "identity", "revision", "fields"],
)
def test_bad_source_envelopes_are_rejected(mutation):
    body = envelope(example())
    mutation(body)
    with pytest.raises((ValueError, ValidationError)):
        Program.model_validate(body)


@pytest.mark.parametrize(
    "source",
    [
        '{"x":1,"x":2}',
        '{"x":NaN}',
        '{"x":1e999}',
        "[" * (MAX_DEPTH + 2) + "0" + "]" * (MAX_DEPTH + 2),
        "null trailing",
    ],
    ids=["duplicate-key", "nan", "overflow", "depth", "trailing"],
)
def test_source_json_is_strict_and_bounded(source):
    with pytest.raises(ValueError):
        strict_source_json(source)


def test_response_stops_at_program_metadata_and_tracks_independent_roots():
    program = example()
    program.metadata["another_graph"] = example(-0.0).model_dump()
    result = source_response({"first": program, "other": [example(9007199254740993)]}, True)
    assert [row["path"] for row in result["programs"]] == [["first"], ["other", 0]]
    assert unwrap_program_source({"ordinary": 1.0}) == {"ordinary": 1.0}


@pytest.mark.parametrize(
    "value", [1.0, -0.0, 9007199254740993], ids=["float", "signed-zero", "large-integer"]
)
def test_project_save_open_export_and_conformance_binding_unchanged(tmp_path, value):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        exact = headers | {"X-Studio-Program-Source": "true"}
        program = example(value)
        saved_response = client.post(
            "/api/projects",
            headers=exact,
            json={"program": envelope(program), "expected_revision": 0},
        )
        assert saved_response.status_code == 200, saved_response.text
        saved, descriptor = decode(saved_response)
        restored = Program.model_validate(saved)
        ordinary = client.get("/api/projects/" + program.id)
        assert ordinary.json() == saved
        assert ordinary.content == client.get("/api/projects/" + program.id).content
        opened, result = decode(client.get("/api/projects/" + program.id, headers=exact))
        assert result["programs"][0]["canonical_sha256"] == restored.digest()
        assert canonical(Program.model_validate(opened)) == canonical(restored)
        body = {"program": envelope(json.dumps(opened, ensure_ascii=False)), "format": "json"}
        export = client.post("/api/export", headers=headers, json=body)
        assert export.status_code == 200, export.text
        assert Program.model_validate_json(export.content).digest() == restored.digest()
        # Existing binding lookup is source-only, without JavaScript numeric projections.
        if type(value) is not int or int(float(value)) == value:
            catalog = client.post(
                "/api/conformance/catalog", headers=headers, json={"program": envelope(restored)}
            )
            assert catalog.status_code == 200, catalog.text
            assert catalog.json()["template"]["program_sha256"] == restored.digest()
        assert descriptor["programs"][0]["canonical_sha256"] == restored.digest()


def test_templates_and_block_defaults_opt_in_without_default_api_changes(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        templates_before = client.get("/api/templates").content
        blocks_before = client.get("/api/blocks").content
        headers = {"X-Studio-Program-Source": "true"}
        templates, source = decode(client.get("/api/templates", headers=headers))
        assert len(templates) == len(source["programs"])
        blocks, source = decode(client.get("/api/blocks", headers=headers))
        assert source["kind"] == "blocks" and not source["programs"]
        assert isinstance(blocks, list)
        assert client.get("/api/templates").content == templates_before
        assert client.get("/api/blocks").content == blocks_before


def test_nested_macro_archive_accepts_exact_program_envelopes(tmp_path):
    from tests.test_macro_integration import nested_rate_program

    source = nested_rate_program()
    for definition in source.metadata["macros"]["definitions"]:
        definition["program"]["metadata"]["opaque"] = example().metadata["opaque"]
    with TestClient(create_app(tmp_path)) as client:
        headers = {
            "X-Studio-Token": client.get("/api/session").json()["token"],
            "X-Studio-Program-Source": "true",
        }
        inspected, _ = decode(
            client.post(
                "/api/macros/definition",
                headers=headers,
                json={"program": envelope(source), "definition": "limiter"},
            )
        )
        assert inspected["metadata"]["opaque"]["array"] == [1.0, -0.0, 9007199254740993]
        archive, descriptors = decode(
            client.post(
                "/api/macros/export",
                headers=headers,
                json={"program": envelope(source), "definition": "outer"},
            )
        )
        expected = {
            row["id"]: Program.model_validate(row["program"]).digest()
            for row in archive["library"]["definitions"]
        }
        assert len(descriptors["programs"]) == len(expected)
        for row in archive["library"]["definitions"]:
            row["program"] = envelope(json.dumps(row["program"], ensure_ascii=False))
        imported, _ = decode(
            client.post(
                "/api/macros/import",
                headers=headers,
                json={"program": envelope(Program(id="destination")), "bundle": archive},
            )
        )
        assert {
            row["id"]: Program.model_validate(row["program"]).digest()
            for row in imported["metadata"]["macros"]["definitions"]
        } == expected


def test_group_definition_programs_keep_opaque_source_across_start_step_reset(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {
            "X-Studio-Token": client.get("/api/session").json()["token"],
            "X-Studio-Program-Source": "true",
        }
        definition = {
            "format": "bms-simulation-workspace/1",
            "name": "Source group",
            "programs": [
                {"alias": "a", "program": envelope(example(1.0))},
                {"alias": "b", "program": envelope(example(-0.0))},
            ],
            "links": [],
        }
        response = client.post(
            "/api/groups/start", headers=headers, json={"definition": definition}
        )
        assert response.status_code == 200, response.text
        started, _ = decode(response)
        sources = [
            Program.model_validate(row["program"]).digest()
            for row in started["definition"]["programs"]
        ]
        for path, body in [
            ("/api/groups/step", {"session": started["session"], "steps": 1}),
            ("/api/groups/reset", {"session": started["session"]}),
        ]:
            result = client.post(path, headers=headers, json=body)
            assert result.status_code == 200, result.text
            state, _ = decode(result)
            assert [
                Program.model_validate(row["program"]).digest()
                for row in state["definition"]["programs"]
            ] == sources
        assert (
            client.post(
                "/api/groups/close", headers=headers, json={"session": started["session"]}
            ).status_code
            == 200
        )


def test_opt_in_load_does_not_rewrite_legacy_revision_bytes_or_hash(tmp_path):
    from bms_tool.storage import Store

    from tests.test_revision_integrity import legacy_database, raw_revision

    source, _, _ = legacy_database(tmp_path)
    store = Store(tmp_path)
    before = raw_revision(store)
    with TestClient(create_app(tmp_path)) as client:
        loaded, _ = decode(
            client.get("/api/projects/" + source.id, headers={"X-Studio-Program-Source": "true"})
        )
        assert Program.model_validate(loaded).digest() == source.digest()
    assert raw_revision(store) == before


@pytest.mark.parametrize(
    "source",
    ['"\\ud800"', '{"\\udfff":0}', "1" * 4097, "1." + "0" * 4096],
    ids=["surrogate-value", "surrogate-key", "integer-token", "float-token"],
)
def test_source_unicode_and_numeric_token_profile(source):
    with pytest.raises(ValueError):
        strict_source_json(source)
