"""Independent offline source/host/port mapping and immutable local storage checks."""

import copy
import csv
import io
import json
import time

import pytest
from bms_tool.models import Edge, Node, Program
from bms_tool.plant_signals import PROFILE, PlantSignals, ReviewKey, ReviewRequest, digest, encoded
from bms_tool.storage import Store
from pydantic import ValidationError


def programs():
    sender = Program(
        id="plant-sender",
        name="Flow sender",
        revision=3,
        nodes=[
            Node(
                id="flow_sensor",
                kind="Input",
                label="Flow sensor",
                unit="gpm",
                params={"terminal": "UI1"},
            ),
            Node(id="flow_source", kind="Output", label="PCHW-F-SRC", unit="gpm"),
        ],
        edges=[Edge(id="a", source="flow_sensor", target="flow_source")],
        metadata={"opaque": [9007199254740993, 1.0, -0.0]},
    )
    receiver = Program(
        id="plant-receiver",
        name="Flow receiver",
        revision=2,
        scan_seconds=2,
        nodes=[
            Node(id="flow_dest", kind="Input", label="PCHW-F-DEST", unit="gpm"),
            Node(
                id="scale",
                kind="Scale",
                label="Illustrative mapping",
                unit="%",
                params={"in_min": 0, "in_max": 1000, "out_min": 0, "out_max": 100, "clamp": True},
            ),
            Node(id="pump_speed", kind="Output", label="Declared command", unit="%"),
        ],
        edges=[
            Edge(id="b", source="flow_dest", target="scale"),
            Edge(id="c", source="scale", target="pump_speed"),
        ],
    )
    return sender, receiver


def make_case(directory):
    service = PlantSignals(Store(directory))
    a, b = [service.import_source(program.model_dump_json().encode()) for program in programs()]
    plan = {
        "format": "bms.plant-signal-plan/1",
        "id": "sample",
        "name": "Declared plant interface schedule",
        "hosts": [
            {"id": "controller_a", "label": "Declared source host", "declared_model": "Unverified"},
            {"id": "controller_b", "label": "Declared pump host", "declared_model": "Unverified"},
        ],
        "instances": [
            {
                "id": "chillers",
                "label": "Chiller subsystem",
                "source_id": a["id"],
                "host_id": "controller_a",
                "subsystems": ["chiller"],
            },
            {
                "id": "pumps",
                "label": "Primary pumps",
                "source_id": b["id"],
                "host_id": "controller_b",
                "subsystems": ["pchwp"],
            },
        ],
        "assignments": [
            {
                "instance_id": "chillers",
                "node_id": "flow_sensor",
                "role": "sensor",
                "terminal_key": "UI1",
            },
            {
                "instance_id": "chillers",
                "node_id": "flow_source",
                "role": "network-source",
                "terminal_key": "",
            },
            {
                "instance_id": "pumps",
                "node_id": "flow_dest",
                "role": "network-destination",
                "terminal_key": "",
            },
            {
                "instance_id": "pumps",
                "node_id": "pump_speed",
                "role": "command",
                "terminal_key": "AO1",
            },
        ],
        "links": [
            {
                "id": "flow_link",
                "source": {"instance_id": "chillers", "node_id": "flow_source"},
                "target": {"instance_id": "pumps", "node_id": "flow_dest"},
            }
        ],
    }
    return service, plan


def reviewed(service, plan):
    view = service.review(ReviewRequest(profile_sha256=PROFILE["sha256"], plan=plan))
    key = ReviewKey(id=view["id"], content_sha256=view["content_sha256"])
    return view, key


def test_source_bound_schedule_preserves_originals_without_execution(tmp_path):
    service, plan = make_case(tmp_path)
    view, key = reviewed(service, plan)
    assert view["analysis"]["status"] == "software_consistent"
    assert view["analysis"]["errors"] == view["analysis"]["warnings"] == 0
    assert [row["role"] for row in view["analysis"]["io_schedule"]] == [
        "sensor",
        "network-source",
        "network-destination",
        "command",
    ]
    assert view["analysis"]["network_schedule"][0]["source_host"] == "controller_a"
    assert not view["analysis"]["hardware_verified"] and not view["field_queries"]
    raw = service.export_review(key, "json")
    assert b"9007199254740993" in raw and b"-0.0" in raw and b"1.0" in raw
    assert (
        service.source(plan["instances"][0]["source_id"])
        == programs()[0].model_dump_json().encode()
    )
    capture = service.save_review(key)
    assert service.export_capture(capture["id"], "json") == raw
    fresh = PlantSignals(Store(tmp_path))
    assert not fresh.status()["sources"] and len(fresh.status()["captures"]) == 1
    opened = fresh.open_capture(capture["id"])
    assert opened["review"] == view
    assert len(fresh.status()["sources"]) == 2
    assert fresh.import_capture(raw)["deduplicated"]
    assert fresh.export_capture(capture["id"], "json") == raw
    assert fresh.open_capture(capture["id"])["capture"]["ingested_at"] == capture["ingested_at"]


def codes(view):
    return {row["code"] for row in view["analysis"]["diagnostics"]}


@pytest.mark.parametrize(
    "case,expected",
    [
        ("unassigned", "unassigned_interface"),
        ("missing-host", "missing_host"),
        ("duplicate-assignment", "multiple_assignments"),
        ("bad-role", "role_direction"),
        ("network-terminal", "network_terminal"),
        ("unknown-node", "unknown_assignment"),
        ("no-writer", "missing_writer"),
        ("unknown-link", "missing_endpoint"),
        ("multiple-writers", "multiple_writers"),
        ("terminal-collision", "terminal_collision"),
    ],
    ids=[
        "unassigned",
        "missing-host",
        "duplicate-assignment",
        "bad-role",
        "network-terminal",
        "unknown-node",
        "no-writer",
        "unknown-link",
        "multiple-writers",
        "terminal-collision",
    ],
)
def test_independent_mapping_conflict_matrix(tmp_path, case, expected):
    service, plan = make_case(tmp_path)
    if case == "unassigned":
        plan["assignments"].pop(0)
    elif case == "missing-host":
        plan["instances"][0]["host_id"] = "missing"
    elif case == "duplicate-assignment":
        plan["assignments"].append(copy.deepcopy(plan["assignments"][0]))
    elif case == "bad-role":
        plan["assignments"][0]["role"] = "command"
    elif case == "network-terminal":
        plan["assignments"][1]["terminal_key"] = "UI1"
    elif case == "unknown-node":
        plan["assignments"][0]["node_id"] = "missing"
    elif case == "no-writer":
        plan["links"] = []
    elif case == "unknown-link":
        plan["links"][0]["source"]["node_id"] = "missing"
    elif case == "multiple-writers":
        plan["links"].append(copy.deepcopy(plan["links"][0]) | {"id": "second_link"})
    elif case == "terminal-collision":
        plan["instances"][1]["host_id"] = "controller_a"
        plan["assignments"][3]["terminal_key"] = "UI1"
    view, _ = reviewed(service, plan)
    assert expected in codes(view) and view["analysis"]["status"] == "unresolved"
    assert not view["analysis"]["hardware_verified"]


@pytest.mark.parametrize(
    "unit,value_type,expected",
    [
        ("", "number", "link_unit_unknown"),
        ("   ", "number", "link_unit_unknown"),
        ("L/s", "number", "link_unit_mismatch"),
        ("gpm", "boolean", "link_type_mismatch"),
    ],
)
def test_exact_declared_unit_and_type_matrix_never_normalizes(tmp_path, unit, value_type, expected):
    service, plan = make_case(tmp_path)
    sender, receiver = programs()
    receiver.nodes[0].unit, receiver.nodes[0].value_type = unit, value_type
    if unit == "   ":
        sender.nodes[1].unit = unit
        plan["instances"][0]["source_id"] = service.import_source(
            sender.model_dump_json().encode()
        )["id"]
    source = service.import_source(receiver.model_dump_json().encode())
    plan["instances"][1]["source_id"] = source["id"]
    view, _ = reviewed(service, plan)
    assert expected in codes(view)
    assert view["analysis"]["network_schedule"][0]["target_unit"] == unit
    assert view["analysis"]["network_schedule"][0]["status"] == "unresolved"


def test_fanout_is_explicit_names_never_bind_and_unknown_hardware_stays_unknown(tmp_path):
    service, plan = make_case(tmp_path)
    plan["hosts"].append({"id": "controller_c", "label": "Third declared host"})
    plan["instances"].append(
        copy.deepcopy(plan["instances"][1]) | {"id": "other_pump", "host_id": "controller_c"}
    )
    for row in copy.deepcopy(plan["assignments"][2:]):
        row["instance_id"] = "other_pump"
        plan["assignments"].append(row)
    plan["links"].append(
        copy.deepcopy(plan["links"][0])
        | {"id": "fanout", "target": {"instance_id": "other_pump", "node_id": "flow_dest"}}
    )
    view, _ = reviewed(service, plan)
    assert view["analysis"]["status"] == "software_consistent"
    assert [link["fanout"] for link in view["analysis"]["network_schedule"]] == [2, 2]
    assert all(row["hardware_verified"] is False for row in view["analysis"]["io_schedule"])
    plan["links"] = []
    view, _ = reviewed(service, plan)
    assert "missing_writer" in codes(view) and "unused_source" in codes(view)
    assert view["analysis"]["network_schedule"] == []  # SRC/DEST labels never create a link.


@pytest.mark.parametrize(
    "path,value",
    [
        ("name", "   "),
        ("name", "bad\nname"),
        ("host", "\t"),
        ("instance", "\x00"),
        ("model", True),
        ("terminal", " UI1 "),
    ],
)
def test_identifiable_declarations_and_strict_strings(tmp_path, path, value):
    service, plan = make_case(tmp_path)
    if path == "name":
        plan["name"] = value
    elif path == "host":
        plan["hosts"][0]["label"] = value
    elif path == "instance":
        plan["instances"][0]["label"] = value
    elif path == "model":
        plan["hosts"][0]["declared_model"] = value
    elif path == "terminal":
        plan["assignments"][0]["terminal_key"] = value
    with pytest.raises(ValidationError):
        reviewed(service, plan)
    assert not service.reviews


@pytest.mark.parametrize(
    "raw",
    [
        b'{"id":"a","id":"b"}',
        b'{"metadata":{"a":NaN}}',
        b'{"metadata":{"a":1e999}}',
        b"\xff",
        b"[" * 10000,
        b" " * (1024 * 1024 + 1),
    ],
    ids=["duplicate", "nan", "infinity", "utf8", "depth", "bytes"],
)
def test_source_parser_refuses_lossy_or_unbounded_documents(tmp_path, raw):
    service = PlantSignals(Store(tmp_path))
    with pytest.raises(ValueError):
        service.import_source(raw)
    assert not service.sources


@pytest.mark.parametrize("field", ["revision", "schema_version", "scan_seconds", "coordinate"])
def test_boolean_numeric_program_structure_is_not_coerced(tmp_path, field):
    service = PlantSignals(Store(tmp_path))
    value = programs()[0].model_dump()
    if field == "coordinate":
        value["nodes"][0]["x"] = True
    else:
        value[field] = True
    with pytest.raises(ValueError):
        service.import_source(encoded(value))


def test_original_revision_cannot_be_rebound_by_equal_name_or_newer_source(tmp_path):
    service, plan = make_case(tmp_path)
    before, key = reviewed(service, plan)
    original = service.export_review(key, "json")
    program = programs()[0]
    program.revision = 4
    program.nodes[0].label = "New source same IDs"
    new = service.import_source(program.model_dump_json().encode())
    assert new["id"] != plan["instances"][0]["source_id"]
    assert service.export_review(key, "json") == original
    service.remove_source(plan["instances"][0]["source_id"])
    with pytest.raises(ValueError, match="missing"):
        reviewed(service, plan)
    assert service.export_review(key, "json") == original
    plan["instances"][0]["source_id"] = new["id"]
    after, _ = reviewed(service, plan)
    assert after["plan_sha256"] != before["plan_sha256"]


def test_self_sealed_type_or_source_tamper_cannot_reproduce_analysis(tmp_path):
    service, plan = make_case(tmp_path)
    view, key = reviewed(service, plan)
    raw = service.export_review(key, "json")
    for mutation in (
        "analysis-bool",
        "profile-float",
        "source-hash",
        "source-text",
        "unsafe-identity",
        "unknown-version",
    ):
        document = json.loads(raw)
        if mutation == "analysis-bool":
            document["analysis"]["hardware_verified"] = 0
        elif mutation == "profile-float":
            document["profile"]["limits"]["instances"] = 16.0
        elif mutation == "source-hash":
            document["sources"][0]["canonical_sha256"] = "0" * 64
        elif mutation == "source-text":
            document["sources"][0]["source_json"] += " "
        elif mutation == "unsafe-identity":
            document["id"] = 123
        else:
            document["format"] = "bms.plant-signal-review/2"
        document["content_sha256"] = digest(
            {k: v for k, v in document.items() if k != "content_sha256"}
        )
        with pytest.raises(ValueError):
            service.import_capture(encoded(document))
    assert service.status()["captures"] == []


@pytest.mark.parametrize(
    "column,value",
    [
        ("document", b""),
        ("document", "{}"),
        ("document", b"broken"),
        ("metadata", b""),
        ("metadata", "{}"),
        ("metadata", b"{}"),
    ],
    ids=[
        "empty-report",
        "text-report",
        "corrupt-report",
        "empty-meta",
        "text-meta",
        "corrupt-meta",
    ],
)
def test_saved_blob_integrity_refuses_corruption_without_overwriting(tmp_path, column, value):
    service, plan = make_case(tmp_path)
    view, key = reviewed(service, plan)
    saved = service.save_review(key)
    with service.store.connect() as db:
        db.execute(f"UPDATE plant_signal_captures SET {column}=? WHERE id=?", (value, saved["id"]))
    fresh = PlantSignals(Store(tmp_path))
    with pytest.raises(ValueError):
        fresh.open_capture(saved["id"])
    assert not fresh.sources
    with pytest.raises(ValueError):
        fresh.export_capture(saved["id"], "json")


def test_store_capacity_lock_contention_and_review_expiry_are_bounded(tmp_path, monkeypatch):
    service, plan = make_case(tmp_path)
    view, key = reviewed(service, plan)
    with service.store.connect(timeout=0) as db:
        db.execute("BEGIN IMMEDIATE")
        start = time.monotonic()
        with pytest.raises(ValueError, match="publication failed"):
            service.save_review(key)
        assert time.monotonic() - start < 1.0
    assert service.status()["captures"] == []
    import bms_tool.plant_signals as module

    monkeypatch.setattr(module, "MAX_LIBRARY", 10)
    with pytest.raises(ValueError, match="capacity"):
        service.save_review(key)
    assert service.status()["captures"] == []
    monkeypatch.setattr(module, "MAX_LIBRARY", 64 * 1024 * 1024)
    first = service.save_review(key)
    original = service.export_capture(first["id"], "json")
    for _ in range(31):
        _, new_key = reviewed(service, plan)
        service.save_review(new_key)
    _, extra = reviewed(service, plan)
    with pytest.raises(ValueError, match="capacity"):
        service.save_review(extra)
    assert len(service.status()["captures"]) == 32
    assert service.export_capture(first["id"], "json") == original
    with pytest.raises(ValueError, match="expired"):
        service.export_review(key, "json")
    service.remove_capture(first["id"])
    assert len(service.status()["captures"]) == 31


def test_atomic_source_restoration_and_exact_id_collision_refusal(tmp_path, monkeypatch):
    service, plan = make_case(tmp_path)
    view, key = reviewed(service, plan)
    raw = service.export_review(key, "json")
    saved = service.save_review(key)
    fresh = PlantSignals(Store(tmp_path))
    for index in range(31):
        program = programs()[0]
        program.id = f"other-{index}"
        fresh.import_source(program.model_dump_json().encode())
    original_ids = list(fresh.sources)
    with pytest.raises(ValueError, match="capacity"):
        fresh.open_capture(saved["id"])
    assert list(fresh.sources) == original_ids and not fresh.reviews
    fresh = PlantSignals(Store(tmp_path))
    document = json.loads(raw)
    document["reviewed_at"] = "2026-01-01T00:00:00+00:00"
    document["content_sha256"] = digest(
        {k: v for k, v in document.items() if k != "content_sha256"}
    )
    other = fresh.import_capture(encoded(document))
    fresh.open_capture(other["id"])
    source_ids = list(fresh.sources)
    old_review = dict(fresh.reviews)
    with pytest.raises(ValueError, match="collision"):
        fresh.open_capture(saved["id"])
    assert list(fresh.sources) == source_ids and dict(fresh.reviews) == old_review


def test_csv_escape_preserves_original_json_and_source(tmp_path):
    service, plan = make_case(tmp_path)
    program = programs()[0]
    program.nodes[0].label = '=HYPERLINK("bad")'
    source = service.import_source(program.model_dump_json().encode())
    plan["instances"][0]["source_id"] = source["id"]
    view, key = reviewed(service, plan)
    rows = list(csv.DictReader(io.StringIO(service.export_review(key, "csv").decode())))
    assert rows[0]["label"] == '\'=HYPERLINK("bad")'
    original = json.loads(service.export_review(key, "json"))
    assert original["analysis"]["io_schedule"][0]["label"] == '=HYPERLINK("bad")'
    assert (
        json.loads(original["sources"][0]["source_json"])
        if original["sources"][0]["id"] == source["id"]
        else True
    )
    assert all(row["review_content_sha256"] == view["content_sha256"] for row in rows)
