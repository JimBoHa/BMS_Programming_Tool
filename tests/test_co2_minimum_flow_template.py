"""Independent curve/hold arithmetic, live ports and guarded source/unit admission."""

import copy
import math

import pytest
from bms_tool.activities import instantiate, resolve
from bms_tool.co2_minimum_flow_template import (
    PROFILE,
    PROFILE_SHA,
    Choices,
    ImportRequest,
    TemplateRequest,
    archive,
    convert_units,
    definition,
    digest,
    flow_cap,
    import_reviewed,
    preview,
)
from bms_tool.engine import Engine, ScanError, validate
from bms_tool.equipment_wizard import CFM_TO_LPS
from bms_tool.models import Edge, Node, Program, canonical

PORTS = ("co2", "co2_reset_a", "co2_reset_b", "flow_low", "flow_high")


def parent(scan=1, choices=None):
    choices = choices or Choices()
    defaults = (
        choices.co2_default,
        choices.co2_reset_a_default,
        choices.co2_reset_b_default,
        choices.flow_low_default,
        choices.flow_high_default,
    )
    return Program(
        id="co2-flow-parent",
        scan_seconds=scan,
        metadata={
            "macros": {"version": 2, "definitions": []},
            "original_source": {"signed": -0.0, "integer": 0, "floating": 0.0, "small": 1e-6},
        },
        nodes=[
            Node(
                id=name,
                kind="Input",
                unit="ppm" if i < 3 else choices.flow_unit,
                params={"default": value},
            )
            for i, (name, value) in enumerate(zip(PORTS, defaults, strict=True))
        ],
    )


def caller(choices=None, scan=1, instances=1):
    choices = choices or Choices()
    p = parent(scan, choices)
    p = import_reviewed(
        ImportRequest(
            program=p,
            choices=choices,
            profile_sha256=PROFILE_SHA,
            reviewed_parent_sha256=p.digest(),
        )
    )
    for index in range(instances):
        p = instantiate(p, definition(choices).id)
        instance = p.nodes[-1].id
        suffix = f"_{index}" if index else ""
        if index:
            for node in list(p.nodes[:5]):
                p.nodes.append(node.model_copy(update={"id": node.id + suffix}, deep=True))
        for name in PORTS:
            p.edges.append(
                Edge(id=f"{name}{index}", source=name + suffix, target=instance, target_port=name)
            )
        p.nodes.extend(
            [
                Node(id=f"flow{index}", kind="Output", unit=choices.flow_unit),
                Node(id=f"valid{index}", kind="Output", value_type="boolean"),
            ]
        )
        p.edges.extend(
            [
                Edge(
                    id=f"flow{index}",
                    source=instance,
                    source_port="minimum_airflow",
                    target=f"flow{index}",
                ),
                Edge(
                    id=f"valid{index}",
                    source=instance,
                    source_port="reset_configuration_valid",
                    target=f"valid{index}",
                ),
            ]
        )
    return p


@pytest.mark.parametrize("unit", ["cfm", "L/s"])
@pytest.mark.parametrize("scan", [0.5, 3.0])
def test_exact38_by57_live_ports_profile_and_no_separate_scan_clock(unit, scan):
    choices = convert_units(Choices(), unit)
    p = parent(scan, choices)
    original = canonical(p)
    report = preview(TemplateRequest(program=p, choices=choices))
    graph = Program.model_validate(report["program"])
    assert len(graph.nodes) == 38 and len(graph.edges) == 57
    assert len([n for n in graph.nodes if n.kind == "Delay"]) == 1
    assert not any(n.kind in ("Activity", "Macro", "Scale", "TimerOn") for n in graph.nodes)
    assert [row["id"] for row in report["inputs"]] == list(PORTS)
    assert all(row["value_type"] == "number" and row["required"] for row in report["inputs"])
    assert [row["unit"] for row in report["inputs"]] == ["ppm"] * 3 + [unit] * 2
    assert [(row["id"], row["value_type"], row["unit"]) for row in report["outputs"]] == [
        ("minimum_airflow", "number", unit),
        ("reset_configuration_valid", "boolean", ""),
    ]
    assert graph.scan_seconds == 1.0 and report["parent_reference"]["scan_seconds"] == scan
    assert report["profile_sha256"] == PROFILE_SHA == digest(PROFILE)
    assert report["program_sha256"] == graph.digest()
    assert report["bundle_sha256"] == digest(report["bundle"])
    assert report["choices_sha256"] == digest(choices.model_dump())
    assert report["definition_sha256"] == digest(report["bundle"]["library"]["definitions"][0])
    assert report["program"] == report["bundle"]["library"]["definitions"][0]["program"]
    assert report["can_import"] and not report["native_compile"] and not report["controller_writes"]
    assert not [x for x in validate(graph) if x.level == "error"] and canonical(p) == original
    assert Engine(caller(choices, scan)).step({"co2": 900})["outputs"]["flow0"] == pytest.approx(
        625 * (CFM_TO_LPS if unit == "L/s" else 1)
    )


@pytest.mark.parametrize(
    "sample,expected",
    [(700, 425), (800, 425), (900, 625), (1000, 825), (1200, 825), (-1e308, 425), (1e308, 825)],
)
def test_documented_endpoints_authored_midpoint_and_finite_sample_saturation(sample, expected):
    assert Engine(caller()).step({"co2": sample})["outputs"] == {"flow0": expected, "valid0": True}


def test_all_endpoints_are_live_including_flat_flows_and_repair():
    engine = Engine(caller())
    assert engine.step(
        {"co2": 500, "co2_reset_a": 400, "co2_reset_b": 800, "flow_low": 100, "flow_high": 300}
    )["outputs"] == {"flow0": 150, "valid0": True}
    assert engine.step({"co2": 999999, "flow_low": 77, "flow_high": 77})["outputs"] == {
        "flow0": 77,
        "valid0": True,
    }
    assert engine.step({"co2": 900})["outputs"] == {"flow0": 625, "valid0": True}


@pytest.mark.parametrize(
    "changed",
    [
        {"co2_reset_b": 800},
        {"co2_reset_a": 1100},
        {"co2_reset_a": -1e308},
        {"co2_reset_b": 1e308},
        {"flow_low": -1e308},
        {"flow_high": 1e308},
        {"flow_low": 900, "flow_high": 100},
    ],
)
def test_every_invalid_good_configuration_has_safe_evaluated_branches_and_committed_hold(changed):
    fresh = Engine(caller())
    assert fresh.step({"co2": 1e308, **changed})["outputs"] == {"flow0": 0, "valid0": False}
    engine = Engine(caller())
    assert engine.step({"co2": 900})["outputs"] == {"flow0": 625, "valid0": True}
    assert engine.step({"co2": -1e308, **changed})["outputs"] == {"flow0": 625, "valid0": False}
    assert engine.time == 2
    assert engine.step({"co2": 1000})["outputs"] == {"flow0": 825, "valid0": True}


@pytest.mark.parametrize("name", list(PORTS))
def test_bad_quality_retains_whole_previous_transaction_including_true_diagnostic(name):
    engine = Engine(caller())
    engine.step({"co2": 900})
    previous = copy.deepcopy(engine.snapshot())
    with pytest.raises(ScanError):
        engine.step({"co2_reset_a": 1200, name: {"quality": "unreliable"}})
    assert engine.snapshot() == previous and engine.outputs == {"flow0": 625, "valid0": True}


def test_first_fault_has_no_preseeded_ventilation_and_terminal_forces_do_not_rewrite_hold():
    p = caller(instances=2)
    engine = Engine(p)
    with pytest.raises(ScanError):
        engine.step({"flow_high": {"quality": "open-circuit"}})
    assert engine.time == 0 and engine.outputs == {} and engine.state == {}
    assert engine.step({"co2": 900, "co2_1": 1000})["outputs"] == {
        "flow0": 625,
        "valid0": True,
        "flow1": 825,
        "valid1": True,
    }
    first = next(n.id for n in p.nodes if n.kind == "Activity")
    aliases = {
        row["output_id"]: row["alias_node_id"]
        for row in resolve(p)["outputs"]
        if row["instance_path"] == [first]
    }
    held = engine.step(
        {"co2": 900, "co2_1": 700},
        forces={aliases["minimum_airflow"]: 99, aliases["reset_configuration_valid"]: False},
    )
    assert held["outputs"] == {"flow0": 99, "valid0": False, "flow1": 425, "valid1": True}
    assert engine.step({"co2_reset_b": 800, "co2_1": 1000}, forces={})["outputs"] == {
        "flow0": 625,
        "valid0": False,
        "flow1": 825,
        "valid1": True,
    }


@pytest.mark.parametrize(
    "changed",
    [
        {"flow_unit": "%"},
        {"co2_default": True},
        {"co2_default": float("nan")},
        {"co2_default": float("inf")},
        {"co2_reset_a_default": -1},
        {"co2_reset_b_default": 1000001},
        {"co2_reset_b_default": 800},
        {"flow_low_default": -1},
        {"flow_high_default": 100},
        {"flow_high_default": flow_cap("cfm") + 1},
        {"flow_low_default": "20"},
    ],
)
def test_strict_default_domain_order_and_finite_types(changed):
    with pytest.raises(ValueError):
        Choices.model_validate(changed)


@pytest.mark.parametrize("mutation", ["nested-default", "parent-version", "profile", "source"])
def test_direct_typed_mutations_revalidate_without_parent_source_rewrite(mutation):
    p, choices = parent(), Choices()
    request = ImportRequest(
        program=p, choices=choices, profile_sha256=PROFILE_SHA, reviewed_parent_sha256=p.digest()
    )
    if mutation == "nested-default":
        request.choices.co2_reset_b_default = 800
    elif mutation == "parent-version":
        request.program.metadata["macros"]["version"] = 2.0
    elif mutation == "profile":
        request.profile_sha256 = "0" * 64
    else:
        request.reviewed_parent_sha256 = "0" * 64
    original = canonical(p)
    with pytest.raises(ValueError):
        import_reviewed(request)
    assert canonical(p) == original
    if mutation == "nested-default":
        with pytest.raises(ValueError):
            definition(request.choices)


def test_conversion_derived_defaults_sign_source_and_real_underflow_band_collapse_refusals():
    source = Choices()
    metric = convert_units(source, "L/s")
    assert (
        metric.flow_low_default == 425 * CFM_TO_LPS and metric.flow_high_default == 825 * CFM_TO_LPS
    )
    assert source.flow_low_default == 425.0 and source.flow_unit == "cfm"
    signed = Choices(flow_low_default=-0.0, flow_high_default=1e-6)
    converted = convert_units(signed, "L/s")
    assert (
        math.copysign(1, converted.flow_low_default) < 0
        and converted.flow_high_default == 1e-6 * CFM_TO_LPS
    )
    for low, high in [(5e-324, 5e-324), (1.063, 1.0630000000000002)]:
        value = Choices(flow_low_default=low, flow_high_default=high)
        before = value.model_dump_json()
        with pytest.raises(ValueError, match="underflow|collapse"):
            convert_units(value, "L/s")
        assert value.model_dump_json() == before
    assert (
        Choices(co2_default=-0.0).co2_default == 0
        and math.copysign(1, Choices(co2_default=-0.0).co2_default) < 0
    )


def test_incomplete_parent_idempotent_import_and_profile_response_copy():
    p = parent(0.5)
    p.nodes.append(Node(id="unwired", kind="Add"))
    choices = Choices(flow_low_default=-0.0, flow_high_default=1e-6)
    before = canonical(p)
    first = preview(TemplateRequest(program=p, choices=choices))
    adopted = import_reviewed(
        ImportRequest(
            program=p,
            choices=choices,
            profile_sha256=PROFILE_SHA,
            reviewed_parent_sha256=p.digest(),
        )
    )
    second = preview(TemplateRequest(program=adopted, choices=choices))
    assert all(
        first[k] == second[k]
        for k in ("definition_id", "definition_sha256", "program_sha256", "bundle_sha256")
    )
    assert canonical(
        import_reviewed(
            ImportRequest(
                program=adopted,
                choices=choices,
                profile_sha256=PROFILE_SHA,
                reviewed_parent_sha256=adopted.digest(),
            )
        )
    ) == canonical(adopted)
    assert canonical(p) == before
    first["profile"]["gaps"].clear()
    assert PROFILE["gaps"] and second["profile"]["gaps"]
    assert (
        archive(choices)["library"]["definitions"][0]["program"]["metadata"][
            "co2_minimum_flow_template"
        ]["choices"]["flow_low_default"]
        == -0.0
    )
