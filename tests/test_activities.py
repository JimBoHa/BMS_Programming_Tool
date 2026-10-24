"""Named mixed outputs lower once, retaining hierarchy and independent state."""

import copy
import hashlib
import json

import pytest
from bms_tool import activities as a
from bms_tool.engine import Engine, ScanError, validate
from bms_tool.formats import export_plcopen, export_program, export_st, import_program
from bms_tool.iec_symbols import LEGACY as LEGACY_SYMBOLS
from bms_tool.macros import expand_macros
from bms_tool.models import Edge, Node, Program, canonical
from bms_tool.source_profiles import LEGACY
from pydantic import ValidationError


def definition(identifier="controller"):
    """One shared Slew supplies two numeric ports and a Boolean comparison."""
    graph = Program(
        id=identifier,
        nodes=[
            Node(id="demand", kind="Input", unit="kW"),
            Node(id="ramp", kind="Slew", unit="kW", params={"rate": 2, "initial": 0}),
            Node(id="zero", kind="Constant", unit="kW", params={"value": 0}),
            Node(id="positive", kind="Greater"),
            Node(id="first", kind="Output", unit="kW"),
            Node(id="second", kind="Output", unit="kW"),
            Node(id="enabled", kind="Output", value_type="boolean"),
        ],
        edges=[
            Edge(id="request", source="demand", target="ramp"),
            Edge(id="gt_a", source="ramp", target="positive", target_port="a"),
            Edge(id="gt_b", source="zero", target="positive", target_port="b"),
            Edge(id="first", source="ramp", target="first"),
            Edge(id="second", source="ramp", target="second"),
            Edge(id="flag", source="positive", target="enabled"),
        ],
        metadata={"original": {"negative_zero": -0.0, "integer": 0, "float": 0.0, "tiny": 1e-6}},
    )
    return {"id": identifier, "name": "Shared three-port controller", "program": graph.model_dump()}


def caller(*, nested=False, instances=1):
    base = definition()
    definitions = [base]
    requested = "controller"
    if nested:
        graph = Program(
            id="outer",
            nodes=[
                Node(id="request", kind="Input", unit="kW"),
                Node(id="inner", kind="Activity", params={"definition": "controller"}),
                Node(id="power", kind="Output", unit="kW"),
                Node(id="running", kind="Output", value_type="boolean"),
            ],
            edges=[
                Edge(id="input", source="request", target="inner", target_port="demand"),
                Edge(id="power", source="inner", source_port="second", target="power"),
                Edge(id="running", source="inner", source_port="enabled", target="running"),
            ],
        )
        definitions.append(
            {"id": "outer", "name": "Nested mixed controller", "program": graph.model_dump()}
        )
        requested = "outer"
    program = Program(
        id="activity-caller", metadata={"macros": {"version": 2, "definitions": definitions}}
    )
    for index in range(instances):
        key = f"use{index}"
        program.nodes.extend(
            [
                Node(
                    id=f"request{index}",
                    kind="Input",
                    unit="kW",
                    params={"default": 10 if index == 0 else -10},
                ),
                Node(id=key, kind="Activity", params={"definition": requested}),
                Node(id=f"value{index}", kind="Output", unit="kW"),
                Node(id=f"active{index}", kind="Output", value_type="boolean"),
            ]
        )
        program.edges.extend(
            [
                Edge(
                    id=f"request{index}",
                    source=f"request{index}",
                    target=key,
                    target_port="request" if nested else "demand",
                ),
                Edge(
                    id=f"value{index}",
                    source=key,
                    source_port="power" if nested else "first",
                    target=f"value{index}",
                ),
                Edge(
                    id=f"active{index}",
                    source=key,
                    source_port="running" if nested else "enabled",
                    target=f"active{index}",
                ),
            ]
        )
    return program


@pytest.mark.parametrize("nested", [False, True])
def test_one_shared_state_graph_per_path_and_named_mixed_output_fanout(nested):
    program = caller(nested=nested, instances=2)
    original = canonical(program)
    engine = Engine(program)
    assert engine.program.digest() == program.digest()
    assert not [d for d in validate(program) if d.level == "error"]
    assert [n.kind for n in engine.graph.nodes].count("Slew") == 2
    assert not any(n.kind in ("Macro", "Activity") for n in engine.graph.nodes)
    assert set(n.id for n in engine.graph.nodes if n.kind == "Output") == {
        "value0",
        "active0",
        "value1",
        "active1",
    }
    assert engine.step()["outputs"] == {
        "value0": 2,
        "active0": True,
        "value1": -2,
        "active1": False,
    }
    assert engine.step()["outputs"] == {
        "value0": 4,
        "active0": True,
        "value1": -4,
        "active1": False,
    }
    bindings = a.resolve(program)
    assert (
        bindings["source_sha256"]
        == engine.program.digest()
        == engine.graph.metadata["activity_expansion"]["source_sha256"]
    )
    assert bindings["expanded_sha256"] == engine.graph.digest()
    for row in bindings["outputs"]:
        expected = (
            "ao2_"
            + hashlib.sha256(
                json.dumps(
                    ["output", *row["instance_path"], row["output_id"]], separators=(",", ":")
                ).encode()
            ).hexdigest()[:24]
        )
        assert row["alias_node_id"] == expected
        assert engine.nodes[expected].value_type == row["value_type"]
        assert engine.nodes[expected].unit == row["unit"]
    if not nested:
        values = engine.snapshot()["values"]
        first = next(
            r["alias_node_id"]
            for r in bindings["outputs"]
            if r["instance_path"] == ["use0"] and r["output_id"] == "first"
        )
        second = next(
            r["alias_node_id"]
            for r in bindings["outputs"]
            if r["instance_path"] == ["use0"] and r["output_id"] == "second"
        )
        assert values[first] == values[second] == 4
    assert canonical(program) == original


def test_quality_rolls_back_shared_state_and_positive_outputs_then_resumes():
    engine = Engine(caller())
    engine.step()
    previous = engine.snapshot()
    with pytest.raises(ScanError, match="quality"):
        engine.step({"request0": {"quality": "open-circuit"}})
    assert engine.snapshot() == previous
    assert engine.step({"request0": 10})["outputs"] == {"value0": 4, "active0": True}


def test_portable_force_targets_only_one_named_alias_not_container_or_shared_state():
    program = caller()
    binding = a.resolve(program)
    alias = next(r["alias_node_id"] for r in binding["outputs"] if r["output_id"] == "first")
    engine = Engine(program)
    first = engine.step(forces={alias: 99})
    assert first["outputs"] == {"value0": 99, "active0": True}
    assert first["computed"][alias] == 2
    assert engine.step(forces={})["outputs"] == {"value0": 4, "active0": True}
    with pytest.raises(ScanError, match="force"):
        engine.step(forces={"use0": 1})


@pytest.mark.parametrize("port", ["out", "First", "absent", ""])
def test_no_implicit_first_output_or_unknown_named_port(port):
    program = caller()
    program.edges[1].source_port = port
    with pytest.raises(ValueError, match="undefined named"):
        expand_macros(program)


@pytest.mark.parametrize(
    "change",
    [
        "missing-library",
        "v1-library",
        "float-version",
        "bool-version",
        "sentinel-type",
        "sentinel-unit",
        "extra-parameter",
        "missing-definition",
    ],
)
def test_explicit_activity_admission_before_any_scalar_execution(change):
    program = caller()
    if change == "missing-library":
        program.metadata.clear()
    elif change == "v1-library":
        program.metadata["macros"]["version"] = 1
    elif change == "float-version":
        program.metadata["macros"]["version"] = 2.0
    elif change == "bool-version":
        program.metadata["macros"]["version"] = True
    elif change == "sentinel-type":
        program.nodes[1].value_type = "boolean"
    elif change == "sentinel-unit":
        program.nodes[1].unit = "kW"
    elif change == "extra-parameter":
        program.nodes[1].params["first"] = "first"
    else:
        program.nodes[1].params["definition"] = "missing"
    with pytest.raises(ValueError):
        Engine(program)


@pytest.mark.parametrize(
    "failure",
    [
        "missing-input",
        "duplicate-writer",
        "input-type",
        "input-unit",
        "output-type",
        "output-unit",
        "ordinary-source-port",
        "cycle",
    ],
)
def test_incomplete_or_wrong_contracts_cannot_gain_resolve_force_authority(failure):
    program = caller()
    if failure == "missing-input":
        program.edges.pop(0)
    elif failure == "duplicate-writer":
        program.edges.append(program.edges[0].model_copy(update={"id": "duplicate"}))
    elif failure == "input-type":
        program.nodes[0].value_type = "boolean"
        program.nodes[0].params["default"] = True
    elif failure == "input-unit":
        program.nodes[0].unit = "A"
    elif failure == "output-type":
        program.nodes[2].value_type = "boolean"
    elif failure == "output-unit":
        program.nodes[2].unit = "A"
    elif failure == "ordinary-source-port":
        program.edges[0].source_port = "first"
    else:
        program.edges[0].source = "use0"
        program.edges[0].source_port = "first"
    with pytest.raises(ValueError):
        a.resolve(program)
    assert a.catalog(program)["bindings"] is None


def test_original_mutable_control_source_hash_and_opaque_atoms_agree_with_active_engine():
    program = caller()
    program.nodes[0].x = 1
    program.nodes[0].y = -0.0
    program.metadata["opaque"] = {"n": -0.0, "int": 0, "float": 0.0, "small": 1e-6}
    original = canonical(program)
    engine = Engine(program)
    report = a.resolve(program)
    assert report["source_sha256"] == engine.program.digest() == program.digest()
    assert engine.graph.metadata["activity_expansion"]["source_sha256"] == report["source_sha256"]
    assert a.catalog(program)["source_sha256"] == report["source_sha256"]
    assert a.catalog(program)["bindings"] == report
    assert b'"n": -0.0' in canonical(engine.program)
    assert canonical(program) == original
    invalid = program.model_copy(update={"scan_seconds": 1000})
    with pytest.raises(ValidationError):
        a.resolve(invalid)


def test_catalog_definition_and_exact_dependency_archive_hashes_and_response_copy():
    program = caller(nested=True)
    report = a.catalog(program)
    assert report["source_sha256"] == program.digest()
    for row in report["definitions"]:
        source = next(d for d in program.metadata["macros"]["definitions"] if d["id"] == row["id"])
        assert row["program_sha256"] == Program.model_validate(source["program"]).digest()
        assert row["definition_sha256"] == a.digest(source)
        assert row["archive_sha256"] == a.digest(a.export_bundle(program, row["id"]))
    report["profile"]["limits"]["outputs"] = 999
    report["bindings"]["profile"]["aliases"]["output"] = "wrong"
    assert a.PROFILE["limits"]["outputs"] == 32
    assert a.digest(a.PROFILE) == a.PROFILE_SHA


@pytest.mark.parametrize(
    "format,suffix",
    [("json", "bms.json"), ("st", "st"), ("plcopen", "xml"), ("graphml", "graphml")],
)
def test_current_interchange_retains_named_ports_original_hierarchy_and_source_atoms(
    format, suffix
):
    program = caller(nested=True)
    original = canonical(program)
    data, _, _ = export_program(program, format)
    restored = import_program(data, "activity." + suffix)
    assert canonical(restored) == original
    assert Engine(restored).step()["outputs"] == {"value0": 2, "active0": True}


@pytest.mark.parametrize("export", [export_st, export_plcopen])
@pytest.mark.parametrize("profile", [None, LEGACY])
def test_old_numeric_and_symbol_envelopes_cannot_mislabel_v2_activities(export, profile):
    kwargs = {"symbols": LEGACY_SYMBOLS}
    if profile is not None:
        kwargs["profile"] = profile
    with pytest.raises(ValueError, match="current V3"):
        export(caller(), **kwargs)


@pytest.mark.parametrize("change", ["sign", "number-kind", "name"])
def test_same_id_import_conflicts_use_exact_source_identity_without_overwrite(change):
    program = caller()
    bundle = a.export_bundle(program, "controller")
    if change == "sign":
        bundle["library"]["definitions"][0]["program"]["metadata"]["original"]["negative_zero"] = (
            0.0
        )
    elif change == "number-kind":
        bundle["library"]["definitions"][0]["program"]["metadata"]["original"]["integer"] = 0.0
    else:
        bundle["library"]["definitions"][0]["name"] = "Different"
    original = canonical(program)
    with pytest.raises(ValueError, match="conflict"):
        a.import_bundle(program, bundle)
    assert canonical(program) == original
    assert canonical(a.import_bundle(program, a.export_bundle(program, "controller"))) == original


def test_definition_edit_context_contract_lock_delete_and_unused_contract_changes():
    program = caller()
    editing = a.inspect(program, "controller")
    editing.name = "Changed logic"
    next(n for n in editing.nodes if n.id == "ramp").params["rate"] = 3
    changed = a.update(program, "controller", editing)
    assert Engine(changed).step()["outputs"] == {"value0": 3, "active0": True}
    bad = editing.model_copy(deep=True)
    bad.metadata["macros"]["definitions"][0]["program"]["metadata"]["original"]["integer"] = 0.0
    with pytest.raises(ValueError, match="context"):
        a.update(program, "controller", bad)
    bad = editing.model_copy(deep=True)
    next(n for n in bad.nodes if n.id == "enabled").id = "renamed"
    next(e for e in bad.edges if e.target == "enabled").target = "renamed"
    with pytest.raises(ValueError, match="unchanged while instances"):
        a.update(program, "controller", bad)
    with pytest.raises(ValueError, match="referenced"):
        a.delete(program, "controller")
    unused = Program(metadata=copy.deepcopy(program.metadata))
    editing = a.inspect(unused, "controller")
    next(n for n in editing.nodes if n.id == "enabled").id = "renamed"
    next(e for e in editing.edges if e.target == "enabled").target = "renamed"
    changed = a.update(unused, "controller", editing)
    assert a.catalog(changed)["definitions"][0]["outputs"][-1]["id"] == "renamed"
    assert a.delete(changed, "controller").metadata["macros"]["definitions"] == []


def test_selection_groups_boundary_by_source_port_and_nested_lowering_once():
    program = caller()
    before = Engine(program).step()["outputs"]
    selected = a.create(program, ["use0"], "Container around mixed outputs")
    outer = selected.metadata["macros"]["definitions"][-1]
    graph = Program.model_validate(outer["program"])
    assert len([n for n in graph.nodes if n.kind == "Output"]) == 2
    assert len([n for n in graph.nodes if n.kind == "Activity"]) == 1
    assert {e.source_port for e in graph.edges if e.source == "use0"} == {"first", "enabled"}
    assert Engine(selected).step()["outputs"] == before
    assert [n.kind for n in expand_macros(selected).nodes].count("Slew") == 1


def test_selection_incoming_multiple_ports_from_one_activity_remain_distinct():
    program = caller()
    program.nodes.extend(
        [Node(id="add", kind="Add", unit="kW"), Node(id="sum", kind="Output", unit="kW")]
    )
    program.edges.extend(
        [
            Edge(
                id="first-input", source="use0", source_port="first", target="add", target_port="a"
            ),
            Edge(
                id="second-input",
                source="use0",
                source_port="second",
                target="add",
                target_port="b",
            ),
            Edge(id="sum", source="add", target="sum"),
        ]
    )
    selected = a.create(program, ["add"], "Distinct named incoming ports")
    graph = Program.model_validate(selected.metadata["macros"]["definitions"][-1]["program"])
    assert len([n for n in graph.nodes if n.kind == "Input"]) == 2
    assert Engine(selected).step()["outputs"]["sum"] == 4


def test_explicit_whole_v1_migration_nested_shared_definitions_and_unwired_editor_draft():
    from tests.test_macro_integration import nested_rate_program

    source = nested_rate_program()
    source.nodes.append(Node(id="unwired", kind="Add"))
    source.edges.pop(0)  # New unwired Macro instance is valid editor draft.
    original = canonical(source)
    report = a.migration_preview(source)
    promoted = Program.model_validate(report["program"])
    assert len(promoted.metadata["macros"]["definitions"]) == 2
    assert {n.kind for n in promoted.nodes} >= {"Activity", "Add"}
    assert len(promoted.edges) == len(source.edges)
    assert any(d["code"] == "unwired" for d in report["after_diagnostics"])
    assert report["source_sha256"] == source.digest()
    assert report["program_sha256"] == promoted.digest()
    assert report["review_sha256"] == a.digest(
        {
            k: report[k]
            for k in (
                "format",
                "version",
                "profile_sha256",
                "source_sha256",
                "program_sha256",
                "rewrites_sha256",
            )
        }
    )
    assert any(r["scope"] == "definition" and r["kind"] == "container" for r in report["rewrites"])
    assert all(e.source_port == "result" for e in promoted.edges if e.source in ("first", "second"))
    applied = a.migration_apply(
        a.MigrationApply(
            program=source, profile_sha256=a.PROFILE_SHA, review_sha256=report["review_sha256"]
        )
    )
    assert canonical(applied) == canonical(promoted)
    promoted.nodes = [n for n in promoted.nodes if n.id != "unwired"]
    promoted.edges.insert(0, Edge(id="a", source="a", target="first", target_port="demand"))
    assert Engine(promoted).step()["outputs"] == {"out_a": 1, "out_b": -1}
    assert canonical(source) == original
    report["profile"]["limits"]["outputs"] = 1
    assert a.PROFILE["limits"]["outputs"] == 32


@pytest.mark.parametrize(
    "failure",
    ["review", "profile", "source", "unknown-reference", "wrong-port", "mixed-source", "repeat"],
)
def test_migration_rejects_stale_ambiguous_mixed_or_repeat_without_source_mutation(failure):
    from tests.test_macros import caller as legacy_caller

    source = legacy_caller()
    report = a.migration_preview(source)
    original = canonical(source)
    request = a.MigrationApply(
        program=source, profile_sha256=a.PROFILE_SHA, review_sha256=report["review_sha256"]
    )
    if failure == "review":
        request.review_sha256 = "0" * 64
    elif failure == "profile":
        request.profile_sha256 = "0" * 64
    elif failure == "source":
        request.program.metadata["changed"] = -0.0
    elif failure == "unknown-reference":
        request.program.nodes[2].params["definition"] = "missing"
    elif failure == "wrong-port":
        request.program.edges[-1].source_port = "named"
    elif failure == "mixed-source":
        request.program.nodes[2].kind = "Activity"
    else:
        request.program = Program.model_validate(report["program"])
    with pytest.raises(ValueError):
        a.migration_apply(request)
    if failure in ("source", "unknown-reference", "wrong-port", "mixed-source"):
        # Pydantic references the supplied Program; the deliberate mutation is
        # the test setup. The service must leave exactly that current source.
        before = canonical(request.program)
        with pytest.raises(ValueError):
            a.migration_apply(request)
        assert canonical(request.program) == before
    else:
        assert canonical(source) == original


def test_explicit_empty_initialization_and_archive_promotion_are_source_bound():
    from bms_tool.macros import export_macro_library

    from tests.test_macros import caller as legacy_caller

    empty = Program(nodes=[Node(id="draft", kind="Add")])
    report = a.migration_preview(empty)
    assert report["program"]["metadata"]["macros"] == {"version": 2, "definitions": []}
    bundle = export_macro_library(legacy_caller(), "adder")
    original = a.canonical(bundle)
    report = a.bundle_migration_preview(bundle)
    assert report["bundle"]["format"] == "bms-macro-library/2"
    assert report["source_bundle_sha256"] == a.digest(bundle)
    converted = a.bundle_migration_export(
        a.BundleMigrationExport(
            bundle=bundle, profile_sha256=a.PROFILE_SHA, review_sha256=report["review_sha256"]
        )
    )
    assert converted == report["bundle"]
    assert a.canonical(bundle) == original
    imported = a.import_bundle(Program(), converted)
    assert a.catalog(imported)["definitions"][0]["outputs"][0]["id"] == "result"
    report["profile"]["aliases"].clear()
    assert a.digest(a.PROFILE) == a.PROFILE_SHA


@pytest.mark.parametrize(
    "failure",
    [
        "zero-output",
        "33-outputs",
        "33-inputs",
        "duplicate-definition",
        "nested-library",
        "native-extension",
        "terminal",
        "v1-container",
        "recursive",
        "unused-cycle",
        "bad-default",
        "library-bytes",
        "library-depth",
        "node-capacity",
    ],
)
def test_new_library_bounds_context_and_all_definitions_are_validated(failure):
    program = caller()
    item = program.metadata["macros"]["definitions"][0]
    graph = item["program"]
    if failure == "zero-output":
        graph["nodes"] = [n for n in graph["nodes"] if n["kind"] != "Output"]
    elif failure == "33-outputs":
        graph["nodes"].extend(
            Node(id=f"extra{i}", kind="Output", unit="kW").model_dump() for i in range(31)
        )
    elif failure == "33-inputs":
        graph["nodes"].extend(Node(id=f"extra{i}", kind="Input").model_dump() for i in range(33))
    elif failure == "duplicate-definition":
        program.metadata["macros"]["definitions"].append(copy.deepcopy(item))
    elif failure == "nested-library":
        graph["metadata"]["macros"] = {"version": 2, "definitions": []}
    elif failure == "native-extension":
        graph["metadata"]["native_sedona"] = {}
    elif failure == "terminal":
        graph["nodes"][0]["params"]["terminal"] = "UI-1"
    elif failure == "v1-container":
        graph["nodes"][1]["kind"] = "Macro"
    elif failure == "recursive":
        graph["nodes"][1]["kind"] = "Activity"
        graph["nodes"][1]["unit"] = ""
        graph["nodes"][1]["params"] = {"definition": "controller"}
    elif failure == "unused-cycle":
        bad = definition("unused")
        bad["program"]["edges"][0]["source"] = "first"
        program.metadata["macros"]["definitions"].append(bad)
    elif failure == "bad-default":
        graph["nodes"][0]["params"]["default"] = True
    elif failure == "library-bytes":
        graph["metadata"]["large"] = "x" * 4194304
    elif failure == "library-depth":
        value = 0
        for _ in range(70):
            value = [value]
        graph["metadata"]["deep"] = value
    else:
        program.target.max_nodes = 5
    original = canonical(program)
    with pytest.raises(ValueError):
        a.resolve(program)
    assert canonical(program) == original


def test_32_outputs_are_all_named_typed_and_unused_ports_still_expand_once():
    graph = Program(nodes=[Node(id="value", kind="Constant", params={"value": 7})])
    for index in range(32):
        graph.nodes.append(Node(id=f"port{index}", kind="Output"))
        graph.edges.append(Edge(id=f"wire{index}", source="value", target=f"port{index}"))
    program = Program(
        nodes=[Node(id="instance", kind="Activity", params={"definition": "many"})],
        metadata={
            "macros": {
                "version": 2,
                "definitions": [
                    {"id": "many", "name": "All outputs", "program": graph.model_dump()}
                ],
            }
        },
    )
    binding = a.resolve(program)
    assert len(binding["outputs"]) == 32
    assert [n.kind for n in expand_macros(program).nodes].count("Constant") == 2
    assert all(
        Engine(program).step()["values"][row["alias_node_id"]] == 7 for row in binding["outputs"]
    )


def test_generated_alias_collision_refuses_instead_of_reseeding():
    program = caller()
    identifier = a.resolve(program)["outputs"][0]["alias_node_id"]
    program.nodes.append(Node(id=identifier, kind="Constant"))
    with pytest.raises(ValueError, match="collision"):
        a.resolve(program)


def test_root_input_output_conformance_remains_usable_without_scalar_activity_signals():
    from bms_tool import conformance as c

    program = caller(nested=True)
    suite = c.template(program)
    assert {s["id"] for s in suite["signals"]} == {"request0", "value0", "active0"}
    suite["cases"][0].update(
        duration=2.0,
        checks=[
            {"id": "numeric", "time": 2.0, "signal": "value0", "unit": "kW", "expected": 4},
            {"id": "boolean", "time": 1.0, "signal": "active0", "unit": "", "expected": True},
            {"id": "input", "time": 1.0, "signal": "request0", "unit": "kW", "expected": 10},
        ],
    )
    report = c.run_suite(program, suite)
    assert report["status"] == "passed"
    assert not report["native_execution"] and not report["controller_writes"]
    suite["cases"][0]["checks"][0]["signal"] = "use0"
    with pytest.raises(ValueError):
        c.run_suite(program, suite)


def test_direct_service_mutations_and_coordinate_types_are_revalidated_privately():
    program = caller()
    request = a.ActivityInstance(program=program, definition="controller", x=1)
    request.x = True
    with pytest.raises(ValidationError):
        a.instantiate(request.program, request.definition, request.x, request.y)
    original = canonical(program)
    request = a.ActivityImport(program=program, bundle=a.export_bundle(program, "controller"))
    request.bundle["library"]["version"] = 2.0
    with pytest.raises(ValueError):
        a.import_bundle(request.program, request.bundle)
    assert canonical(program) == original


def test_valid_prototype_like_names_are_plain_case_sensitive_ids_and_explicit_out_is_allowed():
    program = caller()
    item = program.metadata["macros"]["definitions"][0]
    item["id"] = "constructor"
    renames = {
        "demand": "constructor",
        "first": "toString",
        "enabled": "hasOwnProperty",
        "second": "out",
    }
    for node in item["program"]["nodes"]:
        node["id"] = renames.get(node["id"], node["id"])
    for edge in item["program"]["edges"]:
        edge["source"] = renames.get(edge["source"], edge["source"])
        edge["target"] = renames.get(edge["target"], edge["target"])
    program.nodes[1].params["definition"] = "constructor"
    program.edges[0].target_port = "constructor"
    program.edges[1].source_port = "toString"
    program.edges[2].source_port = "hasOwnProperty"
    assert Engine(program).step()["outputs"] == {"value0": 2, "active0": True}
    program.edges[1].source_port = "out"
    assert Engine(program).step()["outputs"] == {"value0": 2, "active0": True}
    assert {row["output_id"] for row in a.resolve(program)["outputs"]} == {
        "toString",
        "out",
        "hasOwnProperty",
    }


def minimal_definition(identifier="value"):
    graph = Program(
        nodes=[
            Node(id="constant", kind="Constant", params={"value": 3}),
            Node(id="out", kind="Output"),
        ],
        edges=[Edge(id="result", source="constant", target="out")],
    )
    return {"id": identifier, "name": identifier, "program": graph.model_dump()}


def test_instance256_and_definition64_bounds_are_actual_expansion_admissions():
    program = Program(
        nodes=[
            Node(id=f"use{i}", kind="Activity", params={"definition": "value"}) for i in range(256)
        ],
        metadata={"macros": {"version": 2, "definitions": [minimal_definition()]}},
    )
    assert len(a.resolve(program)["outputs"]) == 256
    assert len(expand_macros(program).nodes) == 768
    program.nodes.append(Node(id="use256", kind="Activity", params={"definition": "value"}))
    with pytest.raises(ValueError, match="256instances"):
        a.resolve(program)
    program = Program(
        metadata={
            "macros": {
                "version": 2,
                "definitions": [minimal_definition(f"def{i}") for i in range(64)],
            }
        }
    )
    assert len(a.catalog(program)["definitions"]) == 64
    program.metadata["macros"]["definitions"].append(minimal_definition("extra"))
    with pytest.raises(ValueError):
        a.catalog(program)


def test_dependency_depth8_accepts_and9_refuses_without_replaying_shared_definition_state():
    definitions = [minimal_definition("depth1")]
    for depth in range(2, 10):
        graph = Program(
            nodes=[
                Node(id="child", kind="Activity", params={"definition": f"depth{depth - 1}"}),
                Node(id="out", kind="Output"),
            ],
            edges=[Edge(id="result", source="child", source_port="out", target="out")],
        )
        definitions.append(
            {"id": f"depth{depth}", "name": str(depth), "program": graph.model_dump()}
        )
    program = Program(
        nodes=[Node(id="root", kind="Activity", params={"definition": "depth8"})],
        metadata={"macros": {"version": 2, "definitions": definitions[:8]}},
    )
    assert len(a.resolve(program)["outputs"]) == 8
    assert len([n for n in expand_macros(program).nodes if n.kind == "Constant"]) == 9
    program.metadata["macros"]["definitions"] = definitions
    with pytest.raises(ValueError, match="8levels"):
        a.resolve(program)
