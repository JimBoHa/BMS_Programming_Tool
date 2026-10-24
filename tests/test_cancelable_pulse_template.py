"""Independent finite pulse timelines, parent admission and unchanged macro lowering."""

import copy

import pytest
from bms_tool.cancelable_pulse_template import (
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
from bms_tool.macros import import_macro_library, instantiate_macro
from bms_tool.models import Edge, Node, Program, canonical
from pydantic import ValidationError


def parent(scan=1):
    return Program(
        id="pulse-parent",
        name="Independent pulse callers",
        scan_seconds=scan,
        nodes=[
            Node(id=name, kind="Input", value_type="boolean", params={"default": False})
            for name in ("first_request", "second_request")
        ],
        metadata={"original_source": {"negative_zero": -0.0, "small": 1e-6, "integer": 0}},
    )


def caller(duration=5, scan=1):
    choices = Choices(duration_seconds=duration, scan_seconds=scan)
    root = parent(scan)
    root = import_reviewed(
        ImportRequest(
            program=root,
            choices=choices,
            profile_sha256=PROFILE_SHA,
            reviewed_parent_sha256=root.digest(),
        )
    )
    identifier = definition(choices).id
    for name in ("first", "second"):
        root = instantiate_macro(root, identifier)
        instance = root.nodes[-1].id
        root.nodes.append(Node(id=name, kind="Output", value_type="boolean"))
        root.edges.extend(
            [
                Edge(
                    id=name + "_request",
                    source=name + "_request",
                    target=instance,
                    target_port="request",
                ),
                Edge(id=name + "_result", source=instance, target=name),
            ]
        )
    return root


@pytest.mark.parametrize("duration,scan", [(1, 1), (5, 1), (5, 5), (6, 2), (60, 60), (86400, 60)])
def test_exact_six_ordinary_nodes_edges_ports_profile_and_parent_source(duration, scan):
    root = parent(float(scan))
    original = canonical(root)
    choices = Choices(duration_seconds=duration, scan_seconds=scan)
    report = preview(TemplateRequest(program=root, choices=choices))
    graph = Program.model_validate(report["program"])
    assert [n.kind for n in graph.nodes] == ["Input", "TimerOn", "Delay", "Not", "And", "Output"]
    assert len(graph.nodes) == len(graph.edges) == 6
    assert all(n.value_type == "boolean" and n.unit == "" for n in graph.nodes)
    assert report["inputs"] == [
        {"id": "request", "label": "Request", "value_type": "boolean", "unit": "", "required": True}
    ]
    assert report["output"]["id"] == "result" and report["output"]["value_type"] == "boolean"
    assert graph.scan_seconds == float(scan)
    assert graph.nodes[1].params == {"seconds": duration}
    assert graph.nodes[2].params == {"initial": False}
    assert report["profile_sha256"] == PROFILE_SHA == digest(PROFILE)
    assert report["choices_sha256"] == digest(choices.model_dump())
    assert report["program_sha256"] == graph.digest()
    assert report["program"] == report["bundle"]["library"]["definitions"][0]["program"]
    assert report["definition_sha256"] == digest(report["bundle"]["library"]["definitions"][0])
    assert report["bundle_sha256"] == digest(report["bundle"])
    assert report["parent_reference"] == {
        "id": root.id,
        "revision": 0,
        "scan_seconds": float(scan),
        "program_sha256": root.digest(),
    }
    assert report["can_import"] and not report["native_compile"] and not report["controller_writes"]
    assert not [d for d in validate(graph) if d.level == "error"]
    assert canonical(root) == original


@pytest.mark.parametrize(
    "body",
    [
        {"duration_seconds": 0},
        {"duration_seconds": 86401},
        {"duration_seconds": True},
        {"duration_seconds": 1.0},
        {"duration_seconds": "5"},
        {"scan_seconds": 0},
        {"scan_seconds": 61},
        {"scan_seconds": True},
        {"scan_seconds": 1.0},
        {"scan_seconds": "1"},
        {"duration_seconds": 1, "scan_seconds": 2},
        {"duration_seconds": 5, "scan_seconds": 2},
        {"duration_seconds": 6, "scan_seconds": 2, "reset_action": "Wait"},
    ],
)
def test_invalid_or_unaligned_choices_never_silently_coerce(body):
    with pytest.raises(ValidationError):
        Choices.model_validate(body)


@pytest.mark.parametrize(
    "duration,scan,requests,expected",
    [
        (1, 1, [False, True, True, True], [False, True, False, False]),
        (5, 5, [True, True, True], [True, False, False]),
        (6, 2, [True, True, True, True, True], [True, True, True, False, False]),
        (6, 2, [True, False, True, True, True, True], [True, False, True, True, True, False]),
        (5, 1, [True] * 6 + [False, True], [True] * 5 + [False, False, True]),
        (2, 1, [True, False, False, True, False, True], [True, False, False, True, False, True]),
    ],
    ids=["one-second", "one-step", "held-expiry", "early-cancel", "expired-rise", "chatter"],
)
def test_independent_discrete_output_timeline(duration, scan, requests, expected):
    engine = Engine(caller(duration, scan))
    rows = [engine.step({"first_request": value}) for value in requests]
    assert [row["outputs"]["first"] for row in rows] == expected
    assert all(not row["outputs"]["second"] for row in rows)
    assert [row["time"] for row in rows] == [scan * (i + 1) for i in range(len(rows))]


def test_two_instances_are_independent_and_fresh_engine_restarts_from_false_memory():
    program = caller(3)
    engine = Engine(program)
    requests = [
        (True, False),
        (True, True),
        (True, True),
        (True, True),
        (True, True),
        (False, True),
        (True, False),
    ]
    expected = [
        (True, False),
        (True, True),
        (True, True),
        (False, True),
        (False, False),
        (False, False),
        (True, False),
    ]
    for (first, second), result in zip(requests, expected, strict=True):
        assert (
            tuple(
                engine.step({"first_request": first, "second_request": second})["outputs"].values()
            )
            == result
        )
    fresh = Engine(program)
    assert fresh.step()["outputs"] == {"first": False, "second": False}
    assert fresh.step({"first_request": True})["outputs"] == {"first": True, "second": False}


@pytest.mark.parametrize("quality", ["stale", "fault", "unreliable", "unknown"])
def test_false_bad_quality_retains_positive_pulse_state_clock_and_does_not_cancel(quality):
    engine = Engine(caller(2))
    assert engine.step({"first_request": True})["outputs"]["first"]
    previous = copy.deepcopy(engine.snapshot())
    with pytest.raises(ScanError, match="input quality"):
        engine.step({"first_request": {"value": False, "quality": quality}})
    assert engine.snapshot() == previous
    assert engine.step({"first_request": True})["outputs"]["first"]
    assert not engine.step({"first_request": True})["outputs"]["first"]
    assert not engine.step({"first_request": False})["outputs"]["first"]
    assert engine.step({"first_request": True})["outputs"]["first"]


def test_first_fault_leaves_empty_output_then_valid_true_starts_new_pulse():
    engine = Engine(caller(1))
    previous = copy.deepcopy(engine.snapshot())
    with pytest.raises(ScanError):
        engine.step({"first_request": {"value": True, "quality": "stale"}})
    assert engine.snapshot() == previous and engine.outputs == {} and engine.time == 0
    assert engine.step({"first_request": True})["outputs"]["first"]
    previous = copy.deepcopy(engine.snapshot())
    with pytest.raises(ScanError, match="boolean"):
        engine.step({"first_request": 1})
    assert engine.snapshot() == previous


def test_parent_source_profile_and_clock_admission_preserve_original_numeric_atoms():
    root = parent(1.0)
    original = canonical(root)
    choices = Choices()
    request = ImportRequest(
        program=root,
        choices=choices,
        profile_sha256=PROFILE_SHA,
        reviewed_parent_sha256=root.digest(),
    )
    imported = import_reviewed(request)
    assert canonical(root) == original
    assert imported.metadata["original_source"] == root.metadata["original_source"]
    assert b"-0.0" in canonical(imported) and b"1e-06" in canonical(imported)
    assert (
        import_reviewed(
            ImportRequest(
                program=imported,
                choices=choices,
                profile_sha256=PROFILE_SHA,
                reviewed_parent_sha256=imported.digest(),
            )
        ).digest()
        == imported.digest()
    )
    for changes in ({"profile_sha256": "0" * 64}, {"reviewed_parent_sha256": "0" * 64}):
        with pytest.raises(ValidationError):
            ImportRequest.model_validate(request.model_dump() | changes)
    changed = root.model_copy(deep=True)
    changed.metadata["original_source"]["negative_zero"] = 0.0
    assert changed == root and changed.digest() != root.digest()
    with pytest.raises(ValidationError, match="reviewed parent source"):
        ImportRequest.model_validate(request.model_dump() | {"program": changed.model_dump()})
    with pytest.raises(ValidationError, match="scan seconds"):
        TemplateRequest(program=parent(0.5), choices=choices)
    with pytest.raises(ValidationError, match="scan seconds"):
        TemplateRequest(program=parent(2.0), choices=choices)


def test_required_boolean_writer_conflicts_and_later_clock_scope_remain_explicit():
    root = caller()
    missing = root.model_copy(deep=True)
    missing.edges.pop(0)
    with pytest.raises(ValueError, match="required inputs request"):
        Engine(missing)
    wrong = root.model_copy(deep=True)
    wrong.nodes[0].value_type = "number"
    wrong.nodes[0].params["default"] = 1
    with pytest.raises(ValueError, match="requires boolean"):
        Engine(wrong)
    conflicting = root.model_copy(deep=True)
    conflicting.metadata["macros"]["definitions"][0]["program"]["nodes"][1]["params"]["seconds"] = 6
    previous = canonical(conflicting)
    with pytest.raises(ValueError, match="identifier conflict"):
        import_macro_library(conflicting, archive(Choices()))
    assert canonical(conflicting) == previous
    # Deliberate generic import/clock edits remain possible, outside the generated qualification.
    other = import_macro_library(parent(0.5), archive(Choices()))
    assert other.scan_seconds == 0.5 and other.metadata["macros"]


@pytest.mark.parametrize(
    "operation",
    [
        "duration-upper",
        "duration-bool",
        "duration-float",
        "archive-type",
        "preview-nested",
        "preview-parent",
        "import-profile",
        "import-parent",
    ],
)
def test_mutated_direct_call_models_are_freshly_validated_without_rewriting_inputs(operation):
    choices = Choices()
    root = parent()
    request = TemplateRequest(program=root, choices=choices)
    imported = ImportRequest(
        program=root,
        choices=choices,
        profile_sha256=PROFILE_SHA,
        reviewed_parent_sha256=root.digest(),
    )
    if operation == "duration-upper":
        choices.duration_seconds = 86401
        action, argument = definition, choices
    elif operation == "duration-bool":
        choices.duration_seconds = True
        action, argument = definition, choices
    elif operation == "duration-float":
        choices.duration_seconds = 5.0
        action, argument = definition, choices
    elif operation == "archive-type":
        choices.scan_seconds = True
        action, argument = archive, choices
    elif operation == "preview-nested":
        request.choices.duration_seconds = 86401
        action, argument = preview, request
    elif operation == "preview-parent":
        request.program.revision = -1
        action, argument = preview, request
    elif operation == "import-profile":
        imported.profile_sha256 = "0" * 64
        action, argument = import_reviewed, imported
    else:
        imported.program.metadata["original_source"]["negative_zero"] = 0.0
        action, argument = import_reviewed, imported
    before = copy.deepcopy((choices.model_dump(), request.model_dump(), imported.model_dump()))
    with pytest.raises(ValidationError):
        action(argument)
    assert (choices.model_dump(), request.model_dump(), imported.model_dump()) == before
