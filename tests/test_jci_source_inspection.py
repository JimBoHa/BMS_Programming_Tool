"""Read-only source evidence, including hostile, partial and unknown inputs."""

import gzip
import hashlib
import socket

import pytest
from bms_tool.app import create_app
from bms_tool.jci_source_inspection import FLAGS, MAX_BYTES, encoded, inspect_source, inventory
from fastapi.testclient import TestClient

from .jci_engineering_fixtures import XML, caf_source, native_source, program_source


def proof(raw, name):
    result = inspect_source(raw, name)
    assert result["source"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["source"]["bytes"] == len(raw)
    assert {key: result[key] for key in FLAGS} == FLAGS
    body = {key: value for key, value in result.items() if key != "report_sha256"}
    assert result["report_sha256"] == hashlib.sha256(encoded(body)).hexdigest()
    assert result["coverage"]["complete_native_semantics"] is False
    assert [row["status"] for row in result["operations"]][-3:] == [
        "not-qualified",
        "not-qualified",
        "not-granted",
    ]
    return result


@pytest.mark.parametrize("filename", ["authored.caf", "renamed.DbExport", "unknown.bin"])
def test_content_reader_does_not_prove_tool_or_supervisory_origin(filename):
    source = caf_source()
    result = proof(source, filename)
    assert result["detected"] == {
        "state": "readable",
        "reader_profile": "jci-single-xml-objects/1",
        "container_hint": "zip",
        "artifact_identity_proved": False,
    }
    assert result["summary"]["objects"] == 2
    assert result["summary"]["classes"] == [
        {"id": "194", "objects": 1},
        {"id": "575", "objects": 1},
    ]
    assert result["summary"]["class_versions"] == ["60", "62"]
    assert (
        result["summary"]["root_metadata_records"] == 1
        and result["summary"]["tool_release"] is None
    )
    assert b"opaque original data" in source and inspect_source(source, filename) == result
    if filename.lower().endswith(".dbexport"):
        assert result["source"]["declared_family"] == "sct-xml-export-proposed"
        assert any("separately qualified native codec" in line for line in result["diagnostics"])


@pytest.mark.parametrize("compressed", [False, True])
def test_tagged_field_records_supply_projection_without_capture_authority(compressed):
    result = proof(native_source(compressed=compressed), "field.moz")
    assert result["detected"]["reader_profile"] == "jci-moi-tagged/1"
    assert result["detected"]["state"] == "readable"
    assert result["summary"]["objects"] == 3 and result["summary"]["readable_diagrams"] == 1
    assert result["summary"]["reader_errors"] == 0 and result["summary"]["tool_release"] is None
    assert any("saved-file directory" in s for s in result["diagnostics"])


def test_unresolved_native_graph_has_partial_coverage():
    result = proof(native_source(partial=True), "partial.moi")
    assert result["detected"]["state"] == "partial"
    assert result["summary"]["reader_errors"] > 0 and result["summary"]["readable_diagrams"] == 0
    assert result["summary"]["objects"] == 3


@pytest.mark.parametrize("bom", [False, True])
def test_portable_program_keeps_exact_source_and_large_revision(bom):
    result = proof(program_source(bom=bom, name="Authored café graph"), "graph.json")
    assert result["detected"]["reader_profile"] == "bms-portable-program/1"
    assert result["summary"]["revision_text"] == "9007199254740993"
    assert result["summary"]["name"] == "Authored café graph"
    assert result["summary"]["nodes"] == result["summary"]["edges"] == 0


@pytest.mark.parametrize(
    "source",
    [
        b"{}",
        b'{"schema_version":2,"id":"future","nodes":[],"edges":[]}',
        b'{"schema_version":true,"id":"bad","nodes":[],"edges":[]}',
        b'{"schema_version":1,"id":"bad","nodes":[],"edges":[],"revision":true}',
        b'{"schema_version":1,"id":"bad","nodes":[],"edges":[],"revision":-1}',
        b'{"schema_version":1,"id":"bad","nodes":[],"nodes":[],"edges":[]}',
        b'{"schema_version":1,"id":"bad","nodes":[],"edges":[],"metadata":{"x":NaN}}',
        b'{"schema_version":1,"id":"bad","nodes":[],"edges":[],"metadata":{"x":1e400}}',
        b'{"schema_version":1,"id":"bad","nodes":[],"edges":[],"metadata":'
        + b"[" * 66
        + b"0"
        + b"]" * 66
        + b"}",
        b'{"schema_version":1,"id":"bad","nodes":[],"edges":[],"metadata":{"x":"'
        + b"\xff"
        + b'"}}',
    ],
)
def test_ambiguous_or_malformed_json_is_not_normalized(source):
    result = proof(source, "bad.json")
    assert result["detected"]["state"] == "unrecognized" and result["summary"] == {}
    assert result["operations"][1]["status"] == "unavailable"


@pytest.mark.parametrize(
    "source",
    [
        b"PKbad",
        caf_source(second=True),
        caf_source(encrypted=True),
        caf_source(b'<objects xmlns="wrong-namespace"/>'),
        caf_source(
            b'<!DOCTYPE objects [<!ENTITY external SYSTEM "file:///never-read-me">]><objects/>'
        ),
        b"\x1f\x8bbroken",
        native_source(compressed=True) + b"trailing",
        gzip.compress(b"x" * (8 * 1024 * 1024 + 1), mtime=0),
        b"\x02\x00MOI\x00\x00\x00\x01\x00\x00\x00\x00\x00",
    ],
)
def test_malformed_encrypted_multiple_and_excessive_containers_remain_unrecognized(source):
    result = proof(source, "claimed.caf")
    assert result["detected"]["state"] == "unrecognized"
    assert result["detected"]["reader_profile"] is None and result["diagnostics"]


@pytest.mark.parametrize(
    "name",
    [
        "engine.dbexport",
        "engine.sDbExport",
        "engine.backup",
        "engine.sBackup",
        "items.imp",
        "drawing.svg",
    ],
)
def test_proposed_supervisory_or_graphics_name_grants_no_support(name):
    result = proof(b"<unknown source='authored'/>", name)
    assert result["detected"]["state"] == "unrecognized"
    assert result["source"]["declared_family"] != "unspecified"
    assert result["native_sct_archive_decoded"] is result["native_jct_graphics_decoded"] is False


@pytest.mark.parametrize("name", ["", "..", ".", "bad\nlabel.caf", "bad\x00label", "x" * 513])
def test_invalid_file_labels_are_rejected(name):
    with pytest.raises(ValueError, match="file|source"):
        inspect_source(b"authored", name)


def test_file_labels_are_not_paths_and_large_metadata_is_explicitly_unrepresented(tmp_path):
    forbidden = tmp_path / "never-opened.caf"
    forbidden.write_bytes(b"untouched")
    assert proof(caf_source(), str(forbidden))["source"]["name"] == forbidden.name
    assert forbidden.read_bytes() == b"untouched"
    assert proof(caf_source(), r"C:\unread\source.caf")["source"]["name"] == "source.caf"
    source = caf_source(
        XML.replace(b'classid="194"', b'classid="' + b"x" * 20000 + b'"').replace(
            b'classVersion="60"', b'classVersion="' + b"v" * 20000 + b'"'
        )
    )
    result = proof(source, "bounded.caf")
    assert (
        result["summary"]["unrepresented_class_ids"] == 1
        and not result["summary"]["class_list_complete"]
    )
    assert (
        result["summary"]["omitted_class_versions"] == 1
        and not result["summary"]["class_versions_complete"]
    )
    assert len(encoded(result)) < 10000


@pytest.mark.parametrize("source", [b"", b"x" * (MAX_BYTES + 1), "wrong-type"])
def test_source_size_and_type_limits_are_explicit(source):
    with pytest.raises(ValueError, match="8 MiB"):
        inspect_source(source, "source.bin")


def test_inventory_tracks_actual_evidence_and_preserves_all_parent_dependencies():
    catalog = inventory()
    assert (
        catalog["profile"] == "jci-engineering-inventory/1"
        and catalog["manual_operation_mapping"] == "partial"
    )
    ids = {row["id"] for row in catalog["packages"]}
    assert len(ids) == len(catalog["packages"]) == 48
    assert sum(row["product"] == "SCT" for row in catalog["packages"]) == 24
    assert sum(row["product"] == "JCT" for row in catalog["packages"]) == 18
    assert all(row["status"] in ("planned", "partial") for row in catalog["packages"])
    assert len(catalog["artifact_families"]) == 9 and len(catalog["operations"]) == 5
    assert all(
        row["implementation"] and row["tests"] and row["evidence_level"]
        for row in catalog["operations"]
    )
    assert all(
        row["origin"].startswith("independently authored")
        and not row["native_supervisory_reference"]
        and not row["physical_evidence"]
        for row in catalog["fixture_manifest"]
    )

    def visit(key, parents):
        assert key not in parents
        row = next(r for r in catalog["packages"] if r["id"] == key)
        for dep in row["dependencies"]:
            assert dep in ids or dep == "active-native-restore-delivery"
            if dep in ids:
                visit(dep, {*parents, key})

    for key in ids:
        visit(key, set())


def test_http_report_is_session_protected_byte_exact_and_read_only(tmp_path, monkeypatch):
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Inspection attempted a field or transfer action")

    for key in ("connect", "disconnect", "require", "_read", "apply_write"):
        monkeypatch.setattr(app.state.bacnet, key, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    original_socket = socket.socket

    def local_event_loop_only(family=socket.AF_INET, *args, **kwargs):
        if family in (socket.AF_INET, socket.AF_INET6):
            forbidden()
        return original_socket(family, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", local_event_loop_only)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        # The normal ASGI lifespan creates its notification outbox. Measure the
        # inspection against that initialized application, not before startup.
        before = {
            str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
        }
        source = caf_source()
        assert (
            client.post(
                "/api/jci/engineering/inspect", files={"file": ("input.caf", source)}
            ).status_code
            == 403
        )
        token = client.get("/api/session").json()["token"]
        response = client.post(
            "/api/jci/engineering/inspect",
            headers={"X-Studio-Token": token},
            files={"file": ("input.caf", source)},
        )
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert (
            response.headers["X-BMS-Report-SHA256"] == hashlib.sha256(response.content).hexdigest()
        )
        assert response.headers["X-BMS-Source-SHA256"] == hashlib.sha256(source).hexdigest()
        assert response.content == encoded(proof(source, "input.caf"))
        assert (
            client.get("/api/jci/engineering/inventory").json()["profile"]
            == "jci-engineering-inventory/1"
        )
        assert (
            client.post(
                "/api/jci/engineering/inspect",
                headers={"X-Studio-Token": token, "Origin": "https://foreign.invalid"},
                files={"file": ("input.caf", source)},
            ).status_code
            == 403
        )
        assert not app.state.native_applications.plans
        after = {
            str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
        }
        assert before == after


@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "target", "oversize", "request-limit", "path-only"]
)
def test_http_admission_refuses_target_path_and_duplicate_fields(tmp_path, fault):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        source = caf_source()
        if fault == "missing":
            response = client.post("/api/jci/engineering/inspect", headers=headers, data={})
        elif fault == "duplicate":
            response = client.post(
                "/api/jci/engineering/inspect",
                headers=headers,
                files=[("file", ("one.caf", source)), ("file", ("two.caf", source))],
            )
        elif fault == "target":
            response = client.post(
                "/api/jci/engineering/inspect",
                headers=headers,
                files={"file": ("one.caf", source)},
                data={"target": "not-accepted"},
            )
        elif fault == "oversize":
            response = client.post(
                "/api/jci/engineering/inspect",
                headers=headers,
                files={"file": ("large.bin", b"x" * (MAX_BYTES + 1))},
            )
        elif fault == "request-limit":
            response = client.post(
                "/api/jci/engineering/inspect",
                headers={**headers, "Content-Length": str(10 * 1024 * 1024)},
                content=b"small",
            )
        else:
            response = client.post(
                "/api/jci/engineering/inspect",
                headers=headers,
                json={"path": "/never-opened", "target": "ignored"},
            )
        assert response.status_code == (413 if fault == "request-limit" else 422)
        assert not app.state.native_applications.plans
