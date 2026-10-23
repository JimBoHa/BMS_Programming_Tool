"""Private namespace allocation and exact old/new source compatibility."""

import ast
import base64
import copy
import hashlib
import json
import re
from pathlib import Path

import pytest
from bms_tool import iec, sedona
from bms_tool.engine import Engine
from bms_tool.formats import (
    BMS,
    PLC,
    XML,
    export_plcopen,
    export_st,
    iec_source_parts,
    import_program,
    structured_text_parts,
)
from bms_tool.iec_symbols import CURRENT as SYMBOL_CURRENT
from bms_tool.iec_symbols import LEGACY as SYMBOL_LEGACY
from bms_tool.iec_symbols import (
    SymbolTable,
    allocate_ids,
    digest,
    read_source_document,
    symbol_profile,
)
from bms_tool.models import Edge, Node, Program, canonical
from bms_tool.source_profiles import CURRENT, LEGACY, source_profile

FIXTURES = Path(__file__).parent / "fixtures/iec-symbol-legacy"
COLLISION = Path(__file__).parent / "fixtures/iec-symbol-collision"


def alias_graph():
    names = ["x", "X", "a-b", "a_b", "bms000000", "StudioFault", "A" * 80]
    nodes, edges = [], []
    for index, name in enumerate(names):
        nodes.extend(
            [
                Node(id=name, kind="Input", params={"default": index + 1}),
                Node(id=name + "_valid" if len(name) < 70 else "long_valid", kind="Output"),
            ]
        )
        edges.append(Edge(id=f"edge{index}", source=name, target=nodes[-1].id))
    return Program(id="formerly-colliding", nodes=nodes, edges=edges)


def state_graph():
    program = Program.model_validate_json((FIXTURES / "state-calendar/program.json").read_bytes())
    helpers = [
        "controller_integral",
        "controller_candidate",
        "controller_error",
        "controller_raw",
        "memory_memory",
        "hysteresis_memory",
        "timer_elapsed",
        "timer_next",
        "alarm_elapsed",
        "alarm_next",
        "ramp_memory",
        "calendar_calendar",
        "calendar_calendar_valid",
        "controller_out_stage",
    ]
    for index, name in enumerate(helpers):
        program.nodes.extend(
            [
                Node(id=name, kind="Constant", params={"value": 50 + index}),
                Node(id=name + "_published", kind="Output"),
            ]
        )
        program.edges.append(Edge(id="publish_" + name, source=name, target=name + "_published"))
    return program


def calendar_graph():
    return Program(
        id="calendar-aliases",
        nodes=[
            Node(
                id="cal",
                kind="Schedule",
                value_type="boolean",
                params={
                    "timezone": "UTC",
                    "exceptions": [
                        {"date": "2026-01-05", "enabled": True, "start": "00:00", "end": "23:59"}
                    ],
                },
            ),
            Node(id="cal_calendar", kind="Input", value_type="boolean", params={"default": False}),
            Node(id="cal_calendar_valid", kind="Output", value_type="boolean"),
            Node(id="actual_calendar", kind="Output", value_type="boolean"),
        ],
        edges=[
            Edge(id="a", source="cal_calendar", target="cal_calendar_valid"),
            Edge(id="b", source="cal", target="actual_calendar"),
        ],
    )


def nested_graph():
    program = Program.model_validate_json((FIXTURES / "nested-macro/program.json").read_bytes())
    program.nodes[0].id, program.nodes[1].id = "a-b", "a_b"
    for edge in program.edges:
        if edge.source == "a":
            edge.source = "a-b"
        if edge.source == "b":
            edge.source = "a_b"
    return program


def original_series_graph():
    raw = (COLLISION / "series-fan-before-diagnostic-rename.json").read_bytes()
    provenance = json.loads((COLLISION / "provenance.json").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == provenance["program_sha256"]
    return Program.model_validate_json(raw)


def boolean_graph():
    return Program(
        id="boolean-aliases",
        nodes=[
            Node(id="switch", kind="Input", value_type="boolean", params={"default": True}),
            Node(id="Switch", kind="Input", value_type="boolean", params={"default": False}),
            Node(id="switch_valid", kind="Output", value_type="boolean"),
            Node(id="Switch_valid", kind="Output", value_type="boolean"),
        ],
        edges=[
            Edge(id="a", source="switch", target="switch_valid"),
            Edge(id="b", source="Switch", target="Switch_valid"),
        ],
    )


def unicode_host_graph():
    # Existing HTTP/serialized IR validators are unchanged. Exercise the generic
    # low-level Engine/host graph with distinct Unicode identifiers, which must
    # never be sanitized or used as C members by the private allocator.
    program = Program(
        id="unicode-host",
        nodes=[
            Node(id="value", kind="Input", params={"default": 2}),
            Node(id="memory", kind="Delay", params={"initial": 3}),
            Node(id="out", kind="Output"),
        ],
        edges=[
            Edge(id="a", source="value", target="memory"),
            Edge(id="b", source="memory", target="out"),
        ],
    )
    mapping = {"value": "é", "memory": "记忆", "out": "温度"}
    for node in program.nodes:
        node.id = mapping[node.id]
    for edge in program.edges:
        edge.source, edge.target = mapping[edge.source], mapping[edge.target]
    return program


@pytest.mark.parametrize(
    "factory", [alias_graph, state_graph, calendar_graph, nested_graph, original_series_graph]
)
def test_actual_whole_namespace_roles_are_unique_typed_and_original_graph_stays_unchanged(factory):
    program = factory()
    before = canonical(program)
    declarations, _, symbols = iec_source_parts(program)
    names = [name.casefold() for group in declarations.values() for name, _, _ in group]
    assert len(names) == len(set(names))
    assert max(map(len, names)) < 40
    evidence = symbols.evidence()
    assert evidence["sha256"] == digest(
        {key: value for key, value in evidence.items() if key != "sha256"}
    )
    assert evidence["profile"] == symbol_profile()
    for node in evidence["nodes"]:
        assert node["private_id"].startswith("bms") and node["private_id"][-1].isdigit()
        for role, descriptor in node["roles"].items():
            assert symbols.role(node["id"], role) == descriptor["symbol"]
    evidence["nodes"].clear()
    assert symbols.evidence()["nodes"]
    symbols.lowered().nodes.clear()
    assert canonical(program) == before
    for source, name in [(export_st(program), "new.st"), (export_plcopen(program), "new.xml")]:
        assert import_program(source, name).digest() == program.digest()
    assert canonical(program) == before


def test_unicode_codepoint_order_case_and_normalization_are_not_an_allocator_restriction():
    identifiers = ["é", "e\u0301", "温度", "Δ", "X", "x", "a-b", "a_b", "a" * 80]
    allocated = allocate_ids(identifiers)
    assert list(allocated) == sorted(identifiers)
    assert allocated == allocate_ids(reversed(identifiers))
    assert len(set(allocated.values())) == len(identifiers)
    assert allocated["é"] != allocated["e\u0301"] and allocated["X"] != allocated["x"]
    # This tests generic allocation, not a change to the existing HTTP/IR ID schema.


@pytest.mark.parametrize("identifiers", [["a", "a"], ["a", 3]])
def test_allocator_rejects_duplicate_or_nonstring_authority(identifiers):
    with pytest.raises(ValueError):
        allocate_ids(identifiers)


def test_deterministic_mapping_preserves_original_execution_order_and_every_derived_role():
    program = state_graph()
    table = SymbolTable(program)
    from bms_tool.engine import execution_order

    original_order = execution_order(program)
    lowered = table.lowered()
    mapping = {row["id"]: row["private_id"] for row in table.evidence()["nodes"]}
    assert execution_order(lowered) == [mapping[identifier] for identifier in original_order]
    expected = {
        "value",
        "valid",
        "stage",
        "calendar",
        "calendar_valid",
        "memory",
        "integral",
        "candidate",
        "error",
        "raw",
        "elapsed",
        "next",
    }
    assert {role for node in table.evidence()["nodes"] for role in node["roles"]} == expected
    reordered = program.model_copy(deep=True)
    reordered.nodes.reverse()
    assert SymbolTable(reordered).evidence() == table.evidence()
    declarations, _, _ = iec_source_parts(program)
    altered = copy.deepcopy(declarations)
    name, _, initial = altered["inputVars"][0]
    altered["inputVars"][0] = (name, "BOOL", initial)
    with pytest.raises(ValueError, match="typed symbol"):
        table.verify_declarations(altered)


def test_reversible_state_labels_keep_simple_legacy_names_and_distinguish_unsanitized_ids():
    p = Program(
        nodes=[
            Node(id="a-b", kind="Delay"),
            Node(id="a_b", kind="Delay"),
            Node(id="A_b", kind="Delay"),
        ]
    )
    labels = [row["state_label"] for row in SymbolTable(p).state_rows()]
    assert set(labels) == {"n_a-b_memory", "n_a_b_memory", "n_A_b_memory"}


@pytest.mark.parametrize("name", ["numbers", "state-calendar", "nested-macro"])
def test_original_frozen_v1_v2_st_plcopen_and_sedona_bytes_regenerate_without_execution(
    name, monkeypatch
):
    provenance = json.loads((FIXTURES / "provenance.json").read_bytes())
    program = Program.model_validate_json((FIXTURES / name / "program.json").read_bytes())

    def forbidden(*a, **k):
        pytest.fail("Legacy archive comparison must not execute/compile")

    monkeypatch.setattr(Engine, "__init__", forbidden)
    monkeypatch.setattr(iec, "toolchain", forbidden)
    monkeypatch.setattr(sedona, "toolchain", forbidden)
    for profile, label in [(LEGACY, "v1"), (CURRENT, "v2")]:
        generated = {
            "st": export_st(program, profile=profile, symbols=SYMBOL_LEGACY),
            "xml": export_plcopen(program, profile=profile, symbols=SYMBOL_LEGACY),
            "sedona": sedona.kit_source(program, profile=profile),
            "sax": sedona.application_xml(
                sedona.kit_name(program, profile=profile), scan_seconds=program.scan_seconds
            ),
        }
        for extension, raw in generated.items():
            path = FIXTURES / name / (label + "." + extension)
            assert raw == path.read_bytes()
            assert (
                hashlib.sha256(raw).hexdigest()
                == provenance["files_sha256"][str(path.relative_to(FIXTURES))]
            )
            if extension in ("st", "xml"):
                assert (
                    import_program(raw, path.name).digest()
                    == provenance["cases"][name]["program_sha256"]
                )
        assert (
            sedona.kit_name(program, profile=profile) == provenance["cases"][name]["kits"][profile]
        )


def test_old_expression_emitter_and_literal_rules_stay_frozen():
    import bms_tool.formats as formats

    provenance = json.loads((FIXTURES / "provenance.json").read_bytes())
    node = next(
        n
        for n in ast.parse(Path(formats.__file__).read_text()).body
        if isinstance(n, ast.FunctionDef) and n.name == "structured_text_parts"
    )
    assert (
        hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        == provenance["frozen_emitter_ast_sha256"]
    )
    assert {profile: source_profile(profile) for profile in (LEGACY, CURRENT)} == provenance[
        "numeric_profiles"
    ]


@pytest.mark.parametrize("name", ["numbers", "state-calendar", "nested-macro"])
def test_old_control_statements_and_tie_order_are_identical_after_only_private_alpha_renaming(name):
    program = Program.model_validate_json((FIXTURES / name / "program.json").read_bytes())
    old_declarations, old_body = structured_text_parts(program)
    new_declarations, new_body, symbols = iec_source_parts(program)
    replacements = {}
    for row in symbols.evidence()["nodes"]:
        old = "n_" + re.sub("[^A-Za-z0-9_]", "_", row["id"])
        for role, value in row["roles"].items():
            replacements[value["symbol"]] = old + ("" if role == "value" else "_" + role)
    restored = re.sub(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b", lambda match: replacements.get(match[0], match[0]), new_body
    )
    assert restored == old_body
    assert {
        group: [
            (replacements.get(identifier, identifier), typ, initial)
            for identifier, typ, initial in rows
        ]
        for group, rows in new_declarations.items()
    } == old_declarations


def test_new_st_marker_carries_original_program_and_separate_fixed_symbol_rules():
    program = alias_graph()
    raw = export_st(program)
    assert b"BMS_STUDIO_IR_V3" in raw and b"BMS_STUDIO_IR_V2" not in raw
    encoded = re.search(rb"BMS_STUDIO_IR_V3 ([A-Za-z0-9+/=]+)", raw)[1]
    document = json.loads(base64.b64decode(encoded))
    assert set(document) == {"source_generator", "symbol_generator", "program"}
    assert document["source_generator"] == source_profile()
    assert document["symbol_generator"] == symbol_profile()
    assert Program.model_validate(document["program"]).digest() == program.digest()
    assert {node["id"] for node in document["program"]["nodes"]} == {
        node.id for node in program.nodes
    }
    assert import_program(raw, "new.st").digest() == program.digest()


@pytest.mark.parametrize(
    "change",
    [
        "wrong-symbol-id",
        "wrong-symbol-rules",
        "wrong-literal",
        "missing-symbol",
        "extra-field",
        "duplicate",
        "body",
        "unknown-marker",
        "mixed-markers",
    ],
)
def test_strict_v3_source_never_falls_back_to_legacy_or_reseals(change):
    raw = export_st(alias_graph())
    encoded = re.search(rb"BMS_STUDIO_IR_V3 ([A-Za-z0-9+/=]+)", raw)[1]
    document = json.loads(base64.b64decode(encoded))
    if change == "wrong-symbol-id":
        document["symbol_generator"]["id"] = "unknown/1"
    elif change == "wrong-symbol-rules":
        document["symbol_generator"]["rules_sha256"] = "0" * 64
    elif change == "wrong-literal":
        document["source_generator"] = source_profile(LEGACY)
    elif change == "missing-symbol":
        del document["symbol_generator"]
    elif change == "extra-field":
        document["extra"] = True
    elif change == "duplicate":
        original = base64.b64decode(encoded)
        raw = raw.replace(encoded, base64.b64encode(b'{"symbol_generator":{},' + original[1:]))
    elif change == "body":
        raw = raw.replace(b"n_bms000000_valid", b"n_forged_flag")
    elif change == "unknown-marker":
        raw = raw.replace(b"BMS_STUDIO_IR_V3", b"BMS_STUDIO_IR_V99")
    else:
        raw += raw
    if change in {
        "wrong-symbol-id",
        "wrong-symbol-rules",
        "wrong-literal",
        "missing-symbol",
        "extra-field",
    }:
        raw = raw.replace(encoded, base64.b64encode(json.dumps(document).encode()))
    with pytest.raises(ValueError):
        import_program(raw, "tampered.st")


@pytest.mark.parametrize(
    "change",
    [
        "symbol-id",
        "symbol-rules",
        "missing-symbol",
        "missing-numeric",
        "extra",
        "body",
        "declaration",
    ],
)
def test_strict_new_plcopen_profiles_and_original_graph_bind_complete_source(change):
    root = XML.fromstring(export_plcopen(alias_graph()))
    embedded = root.find(".//{" + BMS + "}program")
    assert embedded.get("iecSymbols") == symbol_profile()["id"]
    assert embedded.get("sourceProfile") == source_profile()["id"]
    if change == "symbol-id":
        embedded.set("iecSymbols", "unknown/1")
    elif change == "symbol-rules":
        embedded.set("iecSymbolsRules", "0" * 64)
    elif change == "missing-symbol":
        del embedded.attrib["iecSymbolsRules"]
    elif change == "missing-numeric":
        del embedded.attrib["sourceProfileRules"]
    elif change == "extra":
        embedded.set("other", "no")
    elif change == "body":
        root.find(".//{" + PLC + "}body/{" + PLC + "}ST/*").text += "\nStudioFault := FALSE;"
    else:
        root.find(".//{" + PLC + "}interface//{" + PLC + "}variable").set("name", "forged")
    with pytest.raises(ValueError):
        import_program(XML.tostring(root, encoding="utf-8", xml_declaration=True), "tampered.xml")


def test_symbol_document_and_source_import_keep_existing_byte_bounds():
    with pytest.raises(ValueError, match="byte bound"):
        read_source_document(b" " * (8 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="8 MiB"):
        import_program(b" " * (8 * 1024 * 1024 + 1), "too-large.st")
    with pytest.raises(ValueError):
        export_st(alias_graph(), symbols="unknown/1")
    with pytest.raises(ValueError):
        export_st(alias_graph(), symbols=SYMBOL_CURRENT, profile=LEGACY)
