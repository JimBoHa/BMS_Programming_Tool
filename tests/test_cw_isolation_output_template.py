"""Hand-calculated command ramps, asymmetric disable and exact source admission."""

import copy
import math

import pytest
from bms_tool.activities import instantiate, resolve
from bms_tool.cw_isolation_output_template import (
    PROFILE,
    PROFILE_SHA,
    Choices,
    ImportRequest,
    TemplateRequest,
    archive,
    definition,
    digest,
    import_reviewed,
    preview,
)
from bms_tool.engine import Engine, ScanError, validate
from bms_tool.models import Edge, Node, Program, canonical
from pydantic import ValidationError


def parent(scan=1):
    return Program(
        id="cw-output-parent",
        scan_seconds=scan,
        metadata={
            "macros": {"version": 2, "definitions": []},
            "original_source": {"signed": -0.0, "integer": 0, "floating": 0.0, "small": 1e-6},
        },
        nodes=[
            Node(id="enable", kind="Input", value_type="boolean", params={"default": False}),
            Node(id="requested", kind="Input", unit="%", params={"default": 0}),
        ],
    )


def caller(minimum=20.0, stroke=4, scan=1, instances=1):
    choices = Choices(minimum_command=minimum, stroke_seconds=stroke, scan_seconds=scan)
    program = parent(scan)
    program = import_reviewed(
        ImportRequest(
            program=program,
            choices=choices,
            profile_sha256=PROFILE_SHA,
            reviewed_parent_sha256=program.digest(),
        )
    )
    for index in range(instances):
        program = instantiate(program, definition(choices).id)
        identifier = program.nodes[-1].id
        if index:
            program.nodes.extend(
                [
                    Node(
                        id=f"enable{index}",
                        kind="Input",
                        value_type="boolean",
                        params={"default": False},
                    ),
                    Node(id=f"requested{index}", kind="Input", unit="%", params={"default": 0}),
                ]
            )
        program.nodes.extend(
            [
                Node(id=f"on{index}", kind="Output", value_type="boolean"),
                Node(id=f"effective{index}", kind="Output", unit="%"),
            ]
        )
        program.edges.extend(
            [
                Edge(
                    id=f"enable{index}",
                    source=f"enable{index}" if index else "enable",
                    target=identifier,
                    target_port="device_enable",
                ),
                Edge(
                    id=f"request{index}",
                    source=f"requested{index}" if index else "requested",
                    target=identifier,
                    target_port="command",
                ),
                Edge(
                    id=f"on{index}",
                    source=identifier,
                    source_port="device_on_off",
                    target=f"on{index}",
                ),
                Edge(
                    id=f"effective{index}",
                    source=identifier,
                    source_port="effective_command",
                    target=f"effective{index}",
                ),
            ]
        )
    return program


@pytest.mark.parametrize(
    "minimum,stroke,scan",
    [(0.0, 60, 1), (-0.0, 60, 1), (20.0, 4, 1), (100.0, 1, 1), (12.5, 6, 3), (0.0, 86400, 60)],
)
def test_exact13_nodes14_edges_two_typed_ports_and_reusable_profile(minimum, stroke, scan):
    p = parent(float(scan))
    original = canonical(p)
    report = preview(
        TemplateRequest(
            program=p,
            choices=Choices(minimum_command=minimum, stroke_seconds=stroke, scan_seconds=scan),
        )
    )
    graph = Program.model_validate(report["program"])
    assert len(graph.nodes) == 13 and len(graph.edges) == 14
    assert [n.kind for n in graph.nodes].count("Delay") == 1
    assert not any(n.kind in ("Activity", "Macro", "Slew") for n in graph.nodes)
    assert [r["id"] for r in report["inputs"]] == ["device_enable", "command"]
    assert all(r["required"] for r in report["inputs"])
    assert report["outputs"] == [
        {
            "id": "device_on_off",
            "label": "Logical device on/off",
            "value_type": "boolean",
            "unit": "",
        },
        {
            "id": "effective_command",
            "label": "Effective percent command",
            "value_type": "number",
            "unit": "%",
        },
    ]
    assert report["profile_sha256"] == PROFILE_SHA == digest(PROFILE)
    assert report["program_sha256"] == graph.digest()
    assert report["bundle_sha256"] == digest(report["bundle"])
    assert report["definition_sha256"] == digest(report["bundle"]["library"]["definitions"][0])
    assert report["program"] == report["bundle"]["library"]["definitions"][0]["program"]
    assert report["choices_sha256"] == digest(report["choices"])
    assert report["parent_reference"] == {
        "id": p.id,
        "revision": p.revision,
        "scan_seconds": float(scan),
        "program_sha256": p.digest(),
    }
    assert not [d for d in validate(graph) if d.level == "error"]
    assert report["can_import"] and not report["native_compile"] and not report["controller_writes"]
    if minimum == 0:
        value = next(n.params["value"] for n in graph.nodes if n.id == "minimum")
        assert math.copysign(1, value) == math.copysign(1, minimum)
    assert canonical(p) == original


def test_independent_exact_rise_decrease_minimum_disable_and_reenable_timeline():
    engine = Engine(caller())
    rows = [
        (False, 100, 0),
        (True, 100, 25),
        (True, 100, 50),
        (True, 100, 75),
        (True, 10, 50),
        (True, 10, 25),
        (True, 10, 20),
        (False, 100, 0),
        (True, 80, 25),
    ]
    for index, (enabled, command, expected) in enumerate(rows, 1):
        observed = engine.step({"enable": enabled, "requested": command})
        assert observed["outputs"] == {"on0": enabled, "effective0": expected}
        assert observed["time"] == index
    assert len([n for n in engine.graph.nodes if n.kind == "Delay"]) == 1
    delay = next(n.id for n in engine.graph.nodes if n.kind == "Delay")
    assert engine.state[delay] == {"previous": 25}


@pytest.mark.parametrize(
    "command,minimum,expected",
    [(-50, 0.0, 0), (250, 0.0, 100), (-1, 20.0, 20), (0, 100.0, 100), (0, 0.0, 0)],
)
def test_one_scan_stroke_finite_clipping_and_boolean_proxy_independent_of_percent(
    command, minimum, expected
):
    engine = Engine(caller(minimum, 1))
    assert engine.step({"enable": True, "requested": command})["outputs"] == {
        "on0": True,
        "effective0": expected,
    }
    assert engine.step({"enable": False, "requested": command})["outputs"] == {
        "on0": False,
        "effective0": 0,
    }


def test_default_nominal_ramp_and_minimum_is_target_floor_not_output_jump():
    engine = Engine(caller(20.0, 60))
    first = engine.step({"enable": True, "requested": 0})
    assert first["outputs"] == {"on0": True, "effective0": 100 / 60}
    assert 0 < first["outputs"]["effective0"] < 20
    engine = Engine(caller(0.0, 6, 3))
    assert engine.step({"enable": True, "requested": 100})["outputs"]["effective0"] == 50
    assert engine.step({"enable": True, "requested": 100})["outputs"]["effective0"] == 100


@pytest.mark.parametrize(
    "quality", ["open-circuit", "short-circuit", "unreliable", "out-of-service"]
)
@pytest.mark.parametrize("input_name", ["enable", "requested"])
def test_fault_retains_positive_both_outputs_memory_and_time_even_requested_disable(
    quality, input_name
):
    engine = Engine(caller())
    engine.step({"enable": True, "requested": 100})
    previous = copy.deepcopy(engine.snapshot())
    with pytest.raises(ScanError):
        engine.step({"enable": False, "requested": 100, input_name: {"quality": quality}})
    assert engine.snapshot() == previous
    assert engine.outputs == {"on0": True, "effective0": 25}
    assert engine.step({"enable": True, "requested": 100})["outputs"]["effective0"] == 50


def test_first_quality_fault_does_not_establish_a_physical_disabled_output():
    engine = Engine(caller())
    with pytest.raises(ScanError):
        engine.step({"enable": False, "requested": {"quality": "open-circuit"}})
    assert engine.time == 0 and engine.values == {} and engine.outputs == {} and engine.state == {}
    assert engine.step({"enable": False, "requested": 0})["outputs"] == {
        "on0": False,
        "effective0": 0,
    }


def test_two_instances_independent_state_and_terminal_output_force_does_not_change_q():
    p = caller(instances=2)
    engine = Engine(p)
    assert engine.step({"enable": True, "requested": 100, "enable1": True, "requested1": 10})[
        "outputs"
    ] == {"on0": True, "effective0": 25, "on1": True, "effective1": 20}
    assert len([n for n in engine.graph.nodes if n.kind == "Delay"]) == 2
    alias = next(
        r["alias_node_id"]
        for r in resolve(p)["outputs"]
        if r["instance_path"] == [next(n.id for n in p.nodes if n.kind == "Activity")]
        and r["output_id"] == "effective_command"
    )
    assert engine.step({"enable": True, "requested": 100, "enable1": False}, forces={alias: 91})[
        "outputs"
    ] == {"on0": True, "effective0": 91, "on1": False, "effective1": 0}
    assert engine.step({"enable": True, "requested": 100}, forces={})["outputs"]["effective0"] == 75


@pytest.mark.parametrize(
    "field,value",
    [
        ("minimum_command", True),
        ("minimum_command", -1),
        ("minimum_command", 101),
        ("minimum_command", float("nan")),
        ("minimum_command", float("inf")),
        ("minimum_command", "20"),
        ("stroke_seconds", True),
        ("stroke_seconds", 1.0),
        ("stroke_seconds", 0),
        ("stroke_seconds", 86401),
        ("scan_seconds", True),
        ("scan_seconds", 1.0),
        ("scan_seconds", 0),
        ("scan_seconds", 61),
    ],
)
def test_strict_configuration_bounds_without_global_schema_changes(field, value):
    with pytest.raises(ValidationError):
        Choices.model_validate({field: value})


@pytest.mark.parametrize("stroke,scan", [(2, 3), (5, 2), (60, 7)])
def test_stroke_scan_must_align(stroke, scan):
    with pytest.raises(ValidationError):
        Choices(stroke_seconds=stroke, scan_seconds=scan)


@pytest.mark.parametrize(
    "mutation",
    [
        "upper",
        "boolean",
        "nested-choices",
        "parent-clock",
        "parent-bounds",
        "parent-version",
        "profile",
        "source",
    ],
)
def test_direct_already_typed_mutations_are_revalidated_without_input_rewrite(mutation):
    p = parent()
    choices = Choices()
    request = TemplateRequest(program=p, choices=choices)
    imported = ImportRequest(
        program=p, choices=choices, profile_sha256=PROFILE_SHA, reviewed_parent_sha256=p.digest()
    )
    if mutation == "upper":
        choices.stroke_seconds = 86401
    elif mutation == "boolean":
        choices.minimum_command = True
    elif mutation == "nested-choices":
        request.choices.scan_seconds = True
    elif mutation == "parent-clock":
        p.scan_seconds = 2
    elif mutation == "parent-bounds":
        p.target.max_nodes = 20001
    elif mutation == "parent-version":
        p.metadata["macros"]["version"] = 2.0
    elif mutation == "profile":
        imported.profile_sha256 = "0" * 64
    else:
        imported.reviewed_parent_sha256 = "0" * 64
    original = canonical(p)
    with pytest.raises(ValueError):
        import_reviewed(imported) if mutation in ("profile", "source") else preview(request)
    assert canonical(p) == original
    if mutation in ("upper", "boolean"):
        with pytest.raises(ValueError):
            definition(choices)


def test_parent_clock_source_profile_guards_idempotence_and_unfinished_editing():
    p = parent()
    p.nodes.append(Node(id="unwired", kind="Add"))
    choices = Choices()
    first = preview(TemplateRequest(program=p, choices=choices))
    imported = import_reviewed(
        ImportRequest(
            program=p,
            choices=choices,
            profile_sha256=PROFILE_SHA,
            reviewed_parent_sha256=p.digest(),
        )
    )
    second = preview(TemplateRequest(program=imported, choices=choices))
    assert (
        first["parent_reference"]["program_sha256"] != second["parent_reference"]["program_sha256"]
    )
    for key in ("definition_id", "definition_sha256", "program_sha256", "bundle_sha256"):
        assert first[key] == second[key]
    assert canonical(imported) == canonical(
        import_reviewed(
            ImportRequest(
                program=imported,
                choices=choices,
                profile_sha256=PROFILE_SHA,
                reviewed_parent_sha256=imported.digest(),
            )
        )
    )
    assert "parent_reference" not in first["program"]["metadata"]["cw_isolation_output_template"]
    first["profile"]["limits"]["minimum_command"][1] = 999
    assert digest(PROFILE) == PROFILE_SHA


def test_signed_zero_minimum_choices_constants_and_definition_identity_stay_distinct():
    negative, positive = (
        definition(Choices(minimum_command=-0.0)),
        definition(Choices(minimum_command=0.0)),
    )
    assert negative.id != positive.id and negative.program.digest() != positive.program.digest()
    assert b'"value": -0.0' in canonical(negative.program)
    assert b'"minimum_command": -0.0' in canonical(negative.program)
    assert archive(Choices(minimum_command=-0.0))["library"]["version"] == 2
