"""Hierarchical macros preserve types, state, wiring, and deterministic identity."""

import copy

import pytest
from bms_tool.engine import Engine
from bms_tool.macros import (
    create_definition,
    delete_macro_definition,
    expand_macros,
    export_macro_library,
    import_macro_library,
    inspect_macro_definition,
    instantiate_macro,
    macro_catalog,
    update_macro_definition,
)
from bms_tool.models import Edge, Node, Program, Target
from pydantic import ValidationError


def definition(identifier="adder", *, unit=""):
    return {
        "id": identifier,
        "name": "Add two signals",
        "program": Program(
            id=identifier,
            nodes=[
                Node(id="x", kind="Input", unit=unit),
                Node(id="y", kind="Input", unit=unit),
                Node(id="sum", kind="Add", unit=unit),
                Node(id="result", kind="Output", unit=unit),
            ],
            edges=[
                Edge(id="xsum", source="x", target="sum", target_port="a"),
                Edge(id="ysum", source="y", target="sum", target_port="b"),
                Edge(id="publish", source="sum", target="result"),
            ],
        ).model_dump(mode="json"),
    }


def library(*definitions):
    return {"macros": {"version": 1, "definitions": list(definitions)}}


def caller(*definitions, unit=""):
    return Program(
        id="caller",
        nodes=[
            Node(id="a", kind="Input", unit=unit, params={"default": 2}),
            Node(id="b", kind="Input", unit=unit, params={"default": 3}),
            Node(id="instance", kind="Macro", unit=unit, params={"definition": "adder"}),
            Node(id="out", kind="Output", unit=unit),
        ],
        edges=[
            Edge(id="a_instance", source="a", target="instance", target_port="x"),
            Edge(id="b_instance", source="b", target="instance", target_port="y"),
            Edge(id="publish", source="instance", target="out"),
        ],
        metadata=library(*(definitions or [definition(unit=unit)])),
    )


def constant_definition(identifier="constant"):
    return {
        "id": identifier,
        "name": identifier,
        "program": Program(
            nodes=[
                Node(id="value", kind="Constant", params={"value": 42}),
                Node(id="out", kind="Output"),
            ],
            edges=[Edge(id="publish", source="value", target="out")],
        ).model_dump(mode="json"),
    }


def constant_caller(*definitions):
    return Program(
        nodes=[
            Node(id="instance", kind="Macro", params={"definition": definitions[0]["id"]}),
            Node(id="out", kind="Output"),
        ],
        edges=[Edge(id="publish", source="instance", target="out")],
        metadata=library(*definitions),
    )


def test_plain_graph_is_unchanged_and_copied_without_provenance():
    program = Program(nodes=[Node(id="value", kind="Constant")], metadata={"notes": "keep"})
    result = expand_macros(program)
    assert result == program
    assert result is not program
    result.nodes[0].params["value"] = 19
    assert not program.nodes[0].params


def test_flattening_executes_and_preserves_root_interfaces_and_source():
    program = caller()
    original = copy.deepcopy(program)
    result = expand_macros(program)
    assert program == original
    assert Engine(result).step()["outputs"] == {"out": 5}
    assert {node.id for node in result.nodes if node.kind == "Input"} == {"a", "b"}
    assert {node.id for node in result.nodes if node.kind == "Output"} == {"out"}
    assert next(node for node in result.nodes if node.id == "instance").kind == "Switch"
    assert not any(node.kind == "Macro" for node in result.nodes)
    assert "macros" not in result.metadata
    assert result.metadata["macro_expansion"]["source_sha256"] == program.digest()


def test_output_fanout_and_shared_input_wiring_are_preserved():
    program = caller()
    program.nodes.append(Node(id="other", kind="Output"))
    program.edges.append(Edge(id="fanout", source="instance", target="other"))
    program.edges[1].source = "a"
    assert Engine(expand_macros(program)).step()["outputs"] == {"out": 4, "other": 4}


def test_nested_instances_execute_and_catalog_exposes_typed_contracts():
    outer = definition("outer")
    graph = Program.model_validate(outer["program"])
    graph.nodes[2] = Node(id="sum", kind="Macro", params={"definition": "adder"})
    graph.edges[0].target_port = "x"
    graph.edges[1].target_port = "y"
    outer["program"] = graph.model_dump(mode="json")
    program = caller(outer, definition())
    program.nodes[2].params["definition"] = "outer"
    result = expand_macros(program)
    assert Engine(result).step()["outputs"]["out"] == 5
    assert [item["path"] for item in result.metadata["macro_expansion"]["instances"]] == [
        ["instance"],
        ["instance", "sum"],
    ]
    catalog = macro_catalog(program)
    assert catalog[0]["dependencies"] == ["adder"]
    assert catalog[0]["input_contracts"] == [
        {"id": "x", "label": "x", "value_type": "number", "unit": "", "required": True},
        {"id": "y", "label": "y", "value_type": "number", "unit": "", "required": True},
    ]
    assert catalog[0]["instances"] == 1


def test_boolean_interface_and_output_are_not_coerced_to_numbers():
    graph = Program(
        nodes=[
            Node(id="enable", kind="Input", value_type="boolean", params={"default": False}),
            Node(id="invert", kind="Not"),
            Node(id="result", kind="Output", value_type="boolean"),
        ],
        edges=[
            Edge(id="a", source="enable", target="invert"),
            Edge(id="b", source="invert", target="result"),
        ],
    )
    item = {"id": "invert", "name": "Invert", "program": graph.model_dump(mode="json")}
    program = Program(
        nodes=[
            Node(id="signal", kind="Input", value_type="boolean", params={"default": False}),
            Node(id="macro", kind="Macro", value_type="boolean", params={"definition": "invert"}),
            Node(id="result", kind="Output", value_type="boolean"),
        ],
        edges=[
            Edge(id="a", source="signal", target="macro", target_port="enable"),
            Edge(id="b", source="macro", target="result"),
        ],
        metadata=library(item),
    )
    engine = Engine(expand_macros(program))
    assert engine.step()["outputs"]["result"] is True
    assert engine.step({"signal": True})["outputs"]["result"] is False


def test_numeric_units_survive_interfaces_and_mismatch_is_rejected():
    program = caller(unit="degF")
    assert Engine(expand_macros(program)).step()["outputs"]["out"] == 5
    program.nodes[0].unit = "degC"
    with pytest.raises(ValueError, match="Unit mismatch"):
        expand_macros(program)
    program = caller(unit="degF")
    program.nodes[2].unit = ""
    with pytest.raises(ValueError, match="output must be number with unit 'degF'"):
        expand_macros(program)


def test_reused_stateful_instances_have_independent_retained_state():
    graph = Program(
        nodes=[
            Node(id="x", kind="Input"),
            Node(id="rate", kind="Slew", params={"rate": 1, "initial": 0}),
            Node(id="result", kind="Output"),
        ],
        edges=[
            Edge(id="a", source="x", target="rate"),
            Edge(id="b", source="rate", target="result"),
        ],
    )
    item = {"id": "rate", "name": "Independent limiter", "program": graph.model_dump(mode="json")}
    program = Program(
        nodes=[
            Node(id="a", kind="Input", params={"default": 100}),
            Node(id="b", kind="Input", params={"default": -100}),
            Node(id="first", kind="Macro", params={"definition": "rate"}),
            Node(id="second", kind="Macro", params={"definition": "rate"}),
            Node(id="out_a", kind="Output"),
            Node(id="out_b", kind="Output"),
        ],
        edges=[
            Edge(id="a", source="a", target="first", target_port="x"),
            Edge(id="b", source="b", target="second", target_port="x"),
            Edge(id="oa", source="first", target="out_a"),
            Edge(id="ob", source="second", target="out_b"),
        ],
        metadata=library(item),
    )
    engine = Engine(expand_macros(program))
    assert engine.step()["outputs"] == {"out_a": 1, "out_b": -1}
    assert engine.step()["outputs"] == {"out_a": 2, "out_b": -2}
    program.nodes.append(Node(id="unrelated", kind="Constant"))
    later = expand_macros(program)
    old_ids = {node.id for node in engine.program.nodes}
    assert old_ids == {node.id for node in later.nodes} - {"unrelated"}


def test_explicit_feedback_delay_is_preserved_without_added_scan_latency():
    graph = Program(
        nodes=[
            Node(id="one", kind="Constant", params={"value": 1}),
            Node(id="memory", kind="Delay"),
            Node(id="sum", kind="Add"),
            Node(id="result", kind="Output"),
        ],
        edges=[
            Edge(id="a", source="one", target="sum", target_port="a"),
            Edge(id="b", source="memory", target="sum", target_port="b"),
            Edge(id="c", source="sum", target="memory"),
            Edge(id="d", source="sum", target="result"),
        ],
    )
    item = {"id": "counter", "name": "Counter", "program": graph.model_dump(mode="json")}
    engine = Engine(expand_macros(constant_caller(item)))
    assert [engine.step()["outputs"]["out"] for _ in range(4)] == [1, 2, 3, 4]
    assert len([node for node in engine.program.nodes if node.kind == "Delay"]) == 1


def test_combinational_feedback_cannot_be_hidden_in_macro():
    item = definition()
    item["program"]["edges"][0]["source"] = "sum"
    with pytest.raises(ValueError, match="Combinational cycle"):
        expand_macros(caller(item))


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda p: p.metadata.pop("macros"), "require metadata.macros"),
        (lambda p: p.nodes[2].params.update(definition="unknown"), "unknown definition"),
        (lambda p: p.nodes[2].params.update(other=True), "parameters must contain only"),
        (lambda p: p.nodes[2].params.update(definition=12), "parameters must contain only"),
        (lambda p: p.edges.pop(0), "connect required inputs x"),
        (lambda p: setattr(p.edges[0], "target_port", "wrong"), "undefined input port"),
        (lambda p: setattr(p.edges[0], "source_port", "wrong"), "undefined source port"),
        (lambda p: setattr(p.edges[0], "source", "missing"), "missing node"),
        (
            lambda p: p.edges.append(p.edges[0].model_copy(update={"id": "duplicate_writer"})),
            "only one writer",
        ),
        (lambda p: p.edges.append(p.edges[0].model_copy()), "edge identifiers must be unique"),
        (lambda p: p.nodes.append(p.nodes[0].model_copy()), "node identifiers must be unique"),
        (lambda p: setattr(p.nodes[2], "value_type", "boolean"), "output must be number"),
    ],
)
def test_invalid_instance_or_connection_is_rejected(mutation, message):
    program = caller()
    mutation(program)
    with pytest.raises(ValueError, match=message):
        expand_macros(program)


@pytest.mark.parametrize("field,value", [("version", 2), ("unknown", True)])
def test_library_schema_is_strict(field, value):
    program = caller()
    program.metadata["macros"][field] = value
    with pytest.raises(ValidationError):
        expand_macros(program)
    program.metadata["macros"] = None
    with pytest.raises(ValidationError):
        expand_macros(program)


def test_unknown_definition_fields_and_duplicate_names_are_rejected():
    program = caller()
    program.metadata["macros"]["definitions"][0]["unknown"] = True
    with pytest.raises(ValidationError):
        expand_macros(program)
    with pytest.raises(ValueError, match="identifiers must be unique"):
        expand_macros(caller(definition(), definition()))


@pytest.mark.parametrize(
    "mutation,message",
    [
        (
            lambda graph: graph["metadata"].update(native_sedona={}),
            "native extensions are forbidden",
        ),
        (lambda graph: graph["metadata"].update(macros={}), "nested libraries"),
        (
            lambda graph: graph["nodes"][0]["params"].update(terminal="UI1"),
            "terminal bindings are forbidden",
        ),
        (
            lambda graph: graph["nodes"].append({"id": "extra", "kind": "Output"}),
            "exactly one Output",
        ),
        (lambda graph: graph["nodes"].pop(), "exactly one Output"),
        (lambda graph: graph["nodes"][2].update(kind="Unknown"), "no execution semantics"),
    ],
)
def test_definition_cannot_hide_unsupported_or_bound_logic(mutation, message):
    item = definition()
    mutation(item["program"])
    with pytest.raises(ValueError, match=message):
        expand_macros(caller(item))


def test_unused_invalid_definition_is_still_rejected():
    unused = definition("unused")
    unused["program"]["edges"].pop()
    with pytest.raises(ValueError, match="Connect required input in"):
        expand_macros(caller(definition(), unused))


def chain(length):
    result = []
    for index in range(length):
        item = constant_definition(f"level{index}")
        if index + 1 < length:
            item["program"]["nodes"][0].update(
                kind="Macro", params={"definition": f"level{index + 1}"}
            )
        result.append(item)
    return result


def test_recursion_and_depth_limits_are_explicit_even_for_unused_definitions():
    items = chain(2)
    items[1]["program"]["nodes"][0].update(kind="Macro", params={"definition": "level0"})
    with pytest.raises(ValueError, match="Recursive macro definitions"):
        expand_macros(constant_caller(*items))
    with pytest.raises(ValueError, match="nesting exceeds 8"):
        expand_macros(constant_caller(*chain(9)))
    assert Engine(expand_macros(constant_caller(*chain(8)))).step()["outputs"]["out"] == 42


def test_parent_resource_limit_counts_expanded_aliases_and_internal_nodes():
    program = caller()
    program.target = Target(max_nodes=5)
    with pytest.raises(ValueError, match="target node limit"):
        expand_macros(program)


def test_expansion_rejects_deliberate_root_identifier_collision():
    program = caller()
    expanded = expand_macros(program)
    generated = next(node.id for node in expanded.nodes if node.id.startswith("mn_"))
    program.nodes.insert(0, Node(id=generated, kind="Constant"))
    with pytest.raises(ValueError, match="identifier collision"):
        expand_macros(program)


def test_extract_selection_rewires_fanout_and_deduplicates_shared_source():
    original = Program(
        nodes=[
            Node(id="a", kind="Input", params={"default": 2}),
            Node(id="sum", kind="Add"),
            Node(id="scale", kind="Multiply"),
            Node(id="out", kind="Output"),
            Node(id="also", kind="Output"),
        ],
        edges=[
            Edge(id="a1", source="a", target="sum", target_port="a"),
            Edge(id="a2", source="a", target="sum", target_port="b"),
            Edge(id="s", source="sum", target="scale", target_port="a"),
            Edge(id="a3", source="a", target="scale", target_port="b"),
            Edge(id="o", source="scale", target="out"),
            Edge(id="o2", source="scale", target="also"),
        ],
    )
    extracted = create_definition(original, ["sum", "scale"], "Double and scale")
    assert (
        Engine(original).step()["outputs"]
        == Engine(expand_macros(extracted)).step()["outputs"]
        == {"out": 8, "also": 8}
    )
    assert [node.id for node in extracted.nodes if node.kind == "Input"] == ["a"]
    catalog = macro_catalog(extracted)
    assert len(catalog) == 1
    assert len(catalog[0]["inputs"]) == 1
    assert len([edge for edge in extracted.edges if edge.target.startswith("use_")]) == 1
    assert not original.metadata
    assert len([node for node in extracted.nodes if node.kind == "Macro"]) == 1


def test_nested_extraction_preserves_existing_library_and_execution():
    program = caller()
    extracted = create_definition(program, ["instance"], "Nested add")
    assert len(macro_catalog(extracted)) == 2
    assert Engine(expand_macros(extracted)).step()["outputs"]["out"] == 5


@pytest.mark.parametrize(
    "selection,name,message",
    [
        ([], "Empty", "Select at least"),
        (["a"], "Input", "Keep root Input"),
        (["instance", "instance"], "Duplicate", "must be unique"),
        (["missing"], "Missing", "unknown node"),
        (["instance"], "", "name must contain"),
    ],
)
def test_invalid_extraction_is_rejected(selection, name, message):
    with pytest.raises(ValueError, match=message):
        create_definition(caller(), selection, name)


def test_multivariate_output_selection_is_rejected_without_modifying_source():
    program = caller()
    program.nodes.extend([Node(id="other", kind="Constant"), Node(id="other_out", kind="Output")])
    program.edges.append(Edge(id="other_edge", source="other", target="other_out"))
    before = program.model_dump_json()
    with pytest.raises(ValueError, match="exactly one distinct outgoing result"):
        create_definition(program, ["instance", "other"], "Two results")
    assert program.model_dump_json() == before


def test_instantiation_creates_unique_typed_unwired_nodes_without_changing_source():
    program = caller(unit="degF")
    instantiated = instantiate_macro(program, "adder", 120, 240)
    node = instantiated.nodes[-1]
    assert (node.kind, node.params, node.unit, node.value_type, node.x, node.y) == (
        "Macro",
        {"definition": "adder"},
        "degF",
        "number",
        120,
        240,
    )
    assert len(program.nodes) == 4
    repeated = instantiate_macro(instantiated, "adder")
    assert repeated.nodes[-1].id != node.id
    assert macro_catalog(repeated)[0]["instances"] == 3
    with pytest.raises(ValueError, match="connect required inputs"):
        expand_macros(instantiated)


@pytest.mark.parametrize(
    "coordinate",
    [True, float("nan"), float("inf"), "42", 10**1000],
    ids=["boolean", "nan", "infinity", "numeric-string", "huge-integer"],
)
def test_instantiation_rejects_invalid_coordinates(coordinate):
    with pytest.raises(ValueError, match="coordinates must be finite numbers"):
        instantiate_macro(caller(), "adder", coordinate, 0)


def test_portable_export_includes_only_dependency_closure_and_import_is_idempotent():
    items = chain(3)
    program = constant_caller(*items, definition("unrelated"))
    archive = export_macro_library(program, "level0")
    assert archive["format"] == "bms-macro-library/1"
    assert {item["id"] for item in archive["library"]["definitions"]} == {
        "level0",
        "level1",
        "level2",
    }
    blank = Program()
    imported = import_macro_library(blank, archive)
    assert not blank.metadata
    assert import_macro_library(imported, archive) == imported
    assert [item["id"] for item in macro_catalog(imported)] == ["level0", "level1", "level2"]
    instantiated = instantiate_macro(imported, "level0")
    instantiated.nodes.append(Node(id="result", kind="Output"))
    instantiated.edges.append(Edge(id="publish", source=instantiated.nodes[-2].id, target="result"))
    assert Engine(expand_macros(instantiated)).step()["outputs"]["result"] == 42


def test_import_never_overwrites_conflicting_definitions_or_accepts_extra_fields():
    program = caller()
    archive = export_macro_library(program, "adder")
    archive["library"]["definitions"][0]["name"] = "Different definition under same ID"
    before = program.model_dump_json()
    with pytest.raises(ValueError, match="identifier conflict"):
        import_macro_library(program, archive)
    assert program.model_dump_json() == before
    archive = export_macro_library(program, "adder")
    archive["execute"] = "arbitrary code"
    with pytest.raises(ValidationError):
        import_macro_library(Program(), archive)


def test_import_rejects_missing_dependencies_and_unrelated_hidden_definitions():
    archive = export_macro_library(constant_caller(*chain(2)), "level0")
    incomplete = copy.deepcopy(archive)
    incomplete["library"]["definitions"].pop()
    with pytest.raises(ValueError, match="unknown definition"):
        import_macro_library(Program(), incomplete)
    archive["library"]["definitions"].append(constant_definition("unrelated"))
    with pytest.raises(ValueError, match="outside its root dependency closure"):
        import_macro_library(Program(), archive)


def test_deletion_guards_root_and_nested_references_and_preserves_other_definitions():
    program = constant_caller(*chain(3), definition("unused"))
    with pytest.raises(ValueError, match="in use by root program:instance"):
        delete_macro_definition(program, "level0")
    with pytest.raises(ValueError, match="in use by level0:value"):
        delete_macro_definition(program, "level1")
    deleted = delete_macro_definition(program, "unused")
    assert len(macro_catalog(program)) == 4
    assert len(macro_catalog(deleted)) == 3
    assert Engine(expand_macros(deleted)).step()["outputs"]["out"] == 42
    catalog = {item["id"]: item for item in macro_catalog(program)}
    assert catalog["level1"]["instances"] == 1
    assert catalog["level1"]["root_instances"] == 0


def test_inspection_returns_independent_nested_graph_with_parent_clock_and_target():
    program = constant_caller(*chain(3))
    program.scan_seconds = 0.25
    program.target.model = "Parent target"
    inspected = inspect_macro_definition(program, "level1")
    assert inspected.scan_seconds == 0.25
    assert inspected.target.model == "Parent target"
    assert {item["id"] for item in macro_catalog(inspected)} == {"level1", "level2"}
    assert Engine(expand_macros(inspected)).step()["outputs"]["out"] == 42
    inspected.nodes[0].label = "Changed view"
    assert not program.metadata["macros"]["definitions"][1]["program"]["nodes"][0]["label"]


def test_unknown_definition_actions_are_explicit_errors():
    for action in (
        instantiate_macro,
        export_macro_library,
        delete_macro_definition,
        inspect_macro_definition,
    ):
        with pytest.raises(ValueError, match="Unknown macro definition"):
            action(caller(), "missing")


def test_macro_instance_count_is_bounded_before_graph_growth_exceeds_capacity():
    program = constant_caller(constant_definition())
    program.nodes.extend(
        Node(id=f"instance{index}", kind="Macro", params={"definition": "constant"})
        for index in range(256)
    )
    with pytest.raises(ValueError, match="exceeds 256 instances"):
        expand_macros(program)


def test_definition_editor_changes_logic_name_labels_and_layout_for_all_instances():
    program = caller()
    draft = inspect_macro_definition(program, "adder")
    draft.name = "Multiply two signals"
    draft.nodes[2].kind = "Multiply"
    draft.nodes[0].label = "First signal"
    draft.nodes[0].x = 120
    updated = update_macro_definition(program, "adder", draft)
    assert Engine(expand_macros(updated)).step()["outputs"]["out"] == 6
    assert Engine(expand_macros(program)).step()["outputs"]["out"] == 5
    assert macro_catalog(updated)[0]["name"] == "Multiply two signals"
    saved = updated.metadata["macros"]["definitions"][0]["program"]
    assert "macros" not in saved["metadata"]
    assert saved["nodes"][0]["x"] == 120
    assert saved["nodes"][0]["label"] == "First signal"


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda draft: draft.metadata.pop("macros"), "preview library changed or is stale"),
        (
            lambda draft: draft.metadata["macros"]["definitions"][0].update(name="Hidden edit"),
            "preview library changed or is stale",
        ),
        (lambda draft: draft.metadata.update(native_sedona={}), "Native extensions are forbidden"),
        (lambda draft: setattr(draft, "scan_seconds", 0.5), "inherits its parent scan period"),
        (
            lambda draft: setattr(draft.target, "model", "Changed parent"),
            "inherits its parent scan period",
        ),
        (
            lambda draft: setattr(draft.nodes[0], "id", "different"),
            "input identifiers, value types, and units",
        ),
        (
            lambda draft: setattr(draft.nodes[0], "unit", "degF"),
            "input identifiers, value types, and units",
        ),
        (
            lambda draft: setattr(draft.nodes[0], "value_type", "boolean"),
            "input identifiers, value types, and units",
        ),
        (lambda draft: setattr(draft.nodes[-1], "unit", "degF"), "output value type and unit"),
        (
            lambda draft: setattr(draft.nodes[-1], "value_type", "boolean"),
            "output value type and unit",
        ),
        (
            lambda draft: draft.nodes[0].params.update(terminal="UI1"),
            "terminal bindings are forbidden",
        ),
    ],
)
def test_isolated_edit_rejects_hidden_context_or_contract_changes(mutate, message):
    program = caller()
    before = program.model_dump_json()
    draft = inspect_macro_definition(program, "adder")
    mutate(draft)
    with pytest.raises(ValueError, match=message):
        update_macro_definition(program, "adder", draft)
    assert program.model_dump_json() == before


def test_definition_edit_can_apply_while_new_root_instance_is_still_unwired():
    program = instantiate_macro(caller(), "adder")
    draft = inspect_macro_definition(program, "adder")
    draft.nodes[2].kind = "Multiply"
    updated = update_macro_definition(program, "adder", draft)
    assert macro_catalog(updated)[0]["instances"] == 2
    with pytest.raises(ValueError, match="connect required inputs"):
        expand_macros(updated)


def test_definition_edit_cannot_remove_feedback_memory_and_create_root_cycle():
    inner = Program(
        nodes=[
            Node(id="signal", kind="Input"),
            Node(id="memory", kind="Delay"),
            Node(id="out", kind="Output"),
        ],
        edges=[
            Edge(id="a", source="signal", target="memory"),
            Edge(id="b", source="memory", target="out"),
        ],
    )
    program = Program(
        nodes=[
            Node(id="one", kind="Constant", params={"value": 1}),
            Node(id="sum", kind="Add"),
            Node(id="instance", kind="Macro", params={"definition": "memory"}),
            Node(id="out", kind="Output"),
        ],
        edges=[
            Edge(id="a", source="one", target="sum", target_port="a"),
            Edge(id="b", source="instance", target="sum", target_port="b"),
            Edge(id="c", source="sum", target="instance", target_port="signal"),
            Edge(id="d", source="instance", target="out"),
        ],
        metadata=library(
            {"id": "memory", "name": "Feedback memory", "program": inner.model_dump(mode="json")}
        ),
    )
    engine = Engine(expand_macros(program))
    assert [engine.step()["outputs"]["out"] for _ in range(3)] == [0, 1, 2]
    draft = inspect_macro_definition(program, "memory")
    draft.nodes[1].kind = "Abs"
    draft.nodes[1].params = {}
    with pytest.raises(ValueError, match="Combinational cycle"):
        update_macro_definition(program, "memory", draft)
