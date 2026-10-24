"""Independent thermal timelines, raw purge continuity and exact source admission."""

import copy
import math

import pytest
from bms_tool.activities import instantiate, resolve
from bms_tool.engine import Engine, ScanError, validate
from bms_tool.models import Edge, Node, Program, canonical
from bms_tool.parallel_fan_purge_template import (
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

PORTS = (
    "heating_percent_command",
    "cooling_percent_command",
    "fan_on_threshold",
    "fan_off_threshold",
    "heating_purge_duration",
)


def parent(choices=None, scan=None):
    choices = choices or Choices()
    return Program(
        id="parallel-purge-parent",
        scan_seconds=choices.scan_seconds if scan is None else scan,
        metadata={
            "macros": {"version": 2, "definitions": []},
            "original_source": {"signed": -0.0, "integer": 0, "floating": 0.0, "small": 1e-6},
        },
        nodes=[
            Node(
                id=name,
                kind="Input",
                unit="s" if name == "heating_purge_duration" else "%",
                params={"default": getattr(choices, name + "_default")},
            )
            for name in PORTS
        ],
    )


def caller(choices=None, instances=1):
    choices = choices or Choices()
    p = parent(choices)
    p = import_reviewed(
        ImportRequest(
            program=p,
            choices=choices,
            profile_sha256=PROFILE_SHA,
            reviewed_parent_sha256=p.digest(),
        )
    )
    for i in range(instances):
        p = instantiate(p, definition(choices).id)
        instance = p.nodes[-1].id
        suffix = f"_{i}" if i else ""
        if i:
            p.nodes.extend(
                n.model_copy(update={"id": n.id + suffix}, deep=True) for n in list(p.nodes[:5])
            )
        p.edges.extend(
            Edge(id=f"{name}{i}", source=name + suffix, target=instance, target_port=name)
            for name in PORTS
        )
        for out, port in (
            (f"request{i}", "fan_request"),
            (f"valid{i}", "request_configuration_valid"),
        ):
            p.nodes.append(Node(id=out, kind="Output", value_type="boolean"))
            p.edges.append(Edge(id=out, source=instance, source_port=port, target=out))
    return p


def elapsed(engine):
    (node,) = [n for n in engine.graph.nodes if n.kind == "Delay" and n.value_type == "number"]
    return engine.state.get(node.id, {}).get("previous", 0)


def assert_step(engine, values, request, seconds, valid=True):
    result = engine.step(values)
    assert result["outputs"] == {"request0": request, "valid0": valid}
    assert elapsed(engine) == seconds
    return result


@pytest.mark.parametrize("h", [1, 2, 60])
def test_five_live_ports_two_shared_memories_and_exact_profile_source_graph(h):
    choices = Choices(scan_seconds=h)
    p = parent(choices)
    original = canonical(p)
    review = preview(TemplateRequest(program=p, choices=choices))
    graph = Program.model_validate(review["program"])
    assert len(graph.nodes) == 51 and len(graph.edges) == 73
    assert [(n.value_type, n.params["initial"]) for n in graph.nodes if n.kind == "Delay"] == [
        ("boolean", False),
        ("number", 0),
    ]
    assert [r["id"] for r in review["inputs"]] == list(PORTS)
    assert [r["unit"] for r in review["inputs"]] == ["%"] * 4 + ["s"]
    assert all(r["required"] and r["value_type"] == "number" for r in review["inputs"])
    assert [(r["id"], r["value_type"], r["unit"]) for r in review["outputs"]] == [
        ("fan_request", "boolean", ""),
        ("request_configuration_valid", "boolean", ""),
    ]
    assert not any(e.source in ("fan_request", "request_configuration_valid") for e in graph.edges)
    assert not any(n.kind in ("Activity", "Macro", "TimerOn", "Divide") for n in graph.nodes)
    assert graph.scan_seconds == review["parent_reference"]["scan_seconds"] == h
    assert review["profile_sha256"] == digest(PROFILE) == PROFILE_SHA
    assert review["program_sha256"] == graph.digest()
    assert review["bundle_sha256"] == digest(review["bundle"])
    assert review["choices_sha256"] == digest(choices.model_dump())
    assert review["program"] == review["bundle"]["library"]["definitions"][0]["program"]
    assert review["can_import"] and not review["native_compile"] and not review["controller_writes"]
    assert not [r for r in validate(graph) if r.level == "error"] and canonical(p) == original
    assert_step(Engine(caller(choices)), {}, False, h)


def test_raw_heat_rising_inside_band_restarts_full_purge_even_without_start():
    engine = Engine(caller(Choices(heating_purge_duration_default=3)))
    assert_step(engine, {"heating_percent_command": 10}, True, 0)
    assert_step(engine, {}, True, 1)
    assert_step(engine, {}, True, 2)
    assert_step(engine, {"heating_percent_command": 1}, True, 0)
    assert_step(engine, {}, True, 1)
    assert_step(engine, {}, True, 2)
    assert_step(engine, {}, False, 3)
    assert_step(engine, {}, False, 4)


def test_cooling_start_inband_hold_and_strict_threshold_equalities():
    engine = Engine(caller(Choices(heating_purge_duration_default=0)))
    assert_step(engine, {"heating_percent_command": 5}, False, 0)
    assert_step(engine, {"cooling_percent_command": 5}, False, 1)
    assert_step(engine, {"cooling_percent_command": 6}, True, 2)
    assert_step(engine, {"cooling_percent_command": 1}, True, 3)
    assert_step(engine, {"cooling_percent_command": 0.1}, True, 4)
    assert_step(engine, {"heating_percent_command": 0.1}, True, 0)
    assert_step(engine, {}, False, 1)
    assert_step(engine, {"heating_percent_command": 6, "cooling_percent_command": 6}, True, 0)
    assert_step(engine, {}, False, 1)


def test_live_duration_never_caps_elapsed_and_increases_decreases_use_current_scan():
    engine = Engine(caller(Choices(heating_purge_duration_default=3)))
    for seconds in range(1, 5):
        assert_step(engine, {"heating_purge_duration": 0}, False, seconds)
    assert_step(engine, {"cooling_percent_command": 6, "heating_purge_duration": 8}, True, 5)
    assert_step(engine, {"heating_purge_duration": 8}, True, 6)
    assert_step(engine, {"heating_purge_duration": 10}, True, 7)
    assert_step(engine, {"heating_purge_duration": 7.5}, False, 8)
    assert_step(engine, {"heating_percent_command": 6}, True, 0)
    assert_step(engine, {"heating_purge_duration": 60}, True, 1)
    assert_step(engine, {"heating_purge_duration": 1}, False, 2)


def test_whole_scan_counter_saturates_at_fixed_cap_and_fractional_duration_quantizes():
    engine = Engine(caller(Choices(scan_seconds=60, heating_purge_duration_default=0)))
    for _ in range(1442):
        result = engine.step()
    assert result["outputs"] == {"request0": False, "valid0": True} and elapsed(engine) == 86400
    assert_step(
        engine, {"cooling_percent_command": 6, "heating_purge_duration": 86400}, True, 86400
    )
    assert_step(engine, {"heating_purge_duration": 86400}, False, 86400)
    short = Engine(caller(Choices(scan_seconds=2, heating_purge_duration_default=2.5)))
    assert_step(short, {"heating_percent_command": 6}, True, 0)
    assert_step(short, {}, True, 2)
    assert_step(short, {}, False, 4)


def test_dt_override_leaves_declared_scan_qualification_without_a_global_clock_gate():
    engine = Engine(caller(Choices(heating_purge_duration_default=2)))
    engine.step({"heating_percent_command": 6}, dt=0.5)
    engine.step({}, dt=0.5)
    assert elapsed(engine) == 1 and engine.time == 1
    result = engine.step({}, dt=0.5)
    assert result["outputs"] == {"request0": False, "valid0": True}
    assert elapsed(engine) == 2 and engine.time == 1.5


@pytest.mark.parametrize(
    "changed",
    [
        {"heating_percent_command": -1e308},
        {"cooling_percent_command": 1e308},
        {"fan_off_threshold": 0},
        {"fan_on_threshold": 100},
        {"fan_on_threshold": 0.05},
        {"heating_purge_duration": 1e308},
    ],
    ids=[
        "negative-heat",
        "huge-cool",
        "zero-off",
        "hundred-on",
        "reversed-thresholds",
        "huge-duration",
    ],
)
def test_invalid_good_values_evaluate_safely_hold_request_reset_elapsed_and_repair(changed):
    choices = Choices(heating_purge_duration_default=2)
    assert_step(Engine(caller(choices)), changed, False, 0, False)
    engine = Engine(caller(choices))
    assert_step(engine, {"heating_percent_command": 6}, True, 0)
    assert_step(engine, {}, True, 1)
    assert_step(engine, changed, True, 0, False)
    assert_step(engine, {}, True, 1)
    assert_step(engine, {}, False, 2)


@pytest.mark.parametrize("name", PORTS)
def test_bad_quality_rolls_back_request_elapsed_time_and_diagnostic(name):
    engine = Engine(caller(Choices(heating_purge_duration_default=3)))
    assert_step(engine, {"heating_percent_command": 6}, True, 0)
    assert_step(engine, {}, True, 1)
    previous = copy.deepcopy(engine.snapshot())
    with pytest.raises(ScanError):
        engine.step({name: {"quality": "unreliable"}})
    assert engine.snapshot() == previous
    assert_step(engine, {}, True, 2)
    assert_step(engine, {}, False, 3)


def test_empty_first_fault_two_instance_state_and_terminal_force_isolation():
    p = caller(Choices(heating_purge_duration_default=3), instances=2)
    engine = Engine(p)
    with pytest.raises(ScanError):
        engine.step({"heating_percent_command": {"quality": "open-circuit"}})
    assert engine.time == 0 and engine.outputs == {} and engine.state == {}
    first = next(n.id for n in p.nodes if n.kind == "Activity")
    aliases = {
        r["output_id"]: r["alias_node_id"]
        for r in resolve(p)["outputs"]
        if r["instance_path"] == [first]
    }
    engine.step({"heating_percent_command": 6})
    result = engine.step(
        {}, forces={aliases["fan_request"]: False, aliases["request_configuration_valid"]: False}
    )
    assert result["outputs"] == {
        "request0": False,
        "valid0": False,
        "request1": False,
        "valid1": True,
    }
    result = engine.step({"cooling_percent_command_1": 6}, forces={})
    assert result["outputs"] == {"request0": True, "valid0": True, "request1": True, "valid1": True}
    assert engine.step({})["outputs"] == {
        "request0": False,
        "valid0": True,
        "request1": False,
        "valid1": True,
    }


@pytest.mark.parametrize(
    "changed",
    [
        {"scan_seconds": True},
        {"scan_seconds": 1.0},
        {"scan_seconds": 0},
        {"scan_seconds": 61},
        {"heating_percent_command_default": True},
        {"cooling_percent_command_default": "5"},
        {"fan_off_threshold_default": 0},
        {"fan_on_threshold_default": 100},
        {"fan_off_threshold_default": 6},
        {"heating_purge_duration_default": -1},
        {"heating_purge_duration_default": float("inf")},
        {"fan_on_threshold_default": float("nan")},
    ],
    ids=[
        "boolean-scan",
        "float-scan",
        "zero-scan",
        "large-scan",
        "boolean-command",
        "string-command",
        "zero-off",
        "hundred-on",
        "bad-order",
        "negative-duration",
        "infinite-duration",
        "nan-threshold",
    ],
)
def test_strict_defaults_and_authored_domain(changed):
    with pytest.raises(ValueError):
        Choices.model_validate(changed)


@pytest.mark.parametrize("mutation", ["default", "clock", "profile", "source"])
def test_mutated_typed_requests_are_revalidated_without_parent_rewrite(mutation):
    p = parent()
    request = ImportRequest(
        program=p, choices=Choices(), profile_sha256=PROFILE_SHA, reviewed_parent_sha256=p.digest()
    )
    if mutation == "default":
        request.choices.fan_off_threshold_default = 0
    elif mutation == "clock":
        request.program.scan_seconds = 2
    elif mutation == "profile":
        request.profile_sha256 = "0" * 64
    else:
        request.program.metadata["changed"] = -0.0
    before = canonical(request.program)
    with pytest.raises(ValueError):
        import_reviewed(request)
    assert canonical(request.program) == before


def test_incomplete_parent_idempotence_canonical_conflict_profile_copy_and_fixed_clock_scope():
    p, choices = parent(), Choices()
    original = canonical(p)
    review = preview(TemplateRequest(program=p, choices=choices))
    adopted = import_reviewed(
        ImportRequest(
            program=p,
            choices=choices,
            profile_sha256=PROFILE_SHA,
            reviewed_parent_sha256=p.digest(),
        )
    )
    repeat = preview(TemplateRequest(program=adopted, choices=choices))
    for key in ("definition_sha256", "program_sha256", "bundle_sha256"):
        assert repeat[key] == review[key]
    assert canonical(p) == original and canonical(
        import_reviewed(
            ImportRequest(
                program=adopted,
                choices=choices,
                profile_sha256=PROFILE_SHA,
                reviewed_parent_sha256=adopted.digest(),
            )
        )
    ) == canonical(adopted)
    adopted.metadata["macros"]["definitions"][0]["program"]["metadata"]["operator_edit"] = -0.0
    with pytest.raises(ValueError):
        preview(TemplateRequest(program=adopted, choices=choices))
    with pytest.raises(ValueError):
        TemplateRequest(program=parent(scan=0.5), choices=choices)
    review["profile"]["gaps"].clear()
    assert PROFILE["gaps"]
    negative = Choices(heating_percent_command_default=-0.0)
    assert math.copysign(1, definition(negative).program.nodes[0].params["default"]) < 0
    assert archive(choices)["root"] == review["definition_id"]
