"""Independent fixed-gain dual-deck calculations; no vendor/native execution."""

import copy

import pytest
from bms_tool.engine import Engine, ScanError
from bms_tool.equipment_wizard import (
    DUAL_PROFILE_SHA,
    PROFILE_SHA,
    Choices,
    choice_document,
    convert_units,
    digest,
    generate,
    preview,
)
from bms_tool.formats import export_program, import_program


def dual(layout="hot-cold", **changes):
    nested = {"layout": layout} | changes.pop("dual_duct", {})
    return Choices(
        project_id="dual-authored",
        name="Authored dual duct",
        equipment="dual-duct",
        control="position" if layout == "none" else "flow-feedback",
        dual_duct=nested,
        **changes,
    )


@pytest.mark.parametrize("layout", ["hot-cold", "hot-total", "cold-total"])
@pytest.mark.parametrize(
    "zone,cold_demand,hot_demand,cold_target,hot_target,cold_command,hot_command",
    [
        (74, 40.2, 0, 521.6, 100, 12.2816, 0),
        (66, 0, 40.2, 200, 381.4, 0, 18.3214),
        (70, 0, 0, 200, 100, 0, 0),
        (80, 100, 0, 1000, 100, 60.6, 0),
        (60, 0, 100, 200, 800, 0, 60.6),
    ],
)
def test_three_pickup_layouts_have_independent_declared_deck_calculations(
    layout, zone, cold_demand, hot_demand, cold_target, hot_target, cold_command, hot_command
):
    program = generate(dual(layout))
    row = Engine(program).step({"zone": zone})["outputs"]
    assert row == {
        "setpoints_ordered": True,
        "airflow_consistent": True,
        "control_permitted": True,
        "cold_flow": 400,
        "hot_flow": 200,
        "total_flow": 600,
        "cold_demand": pytest.approx(cold_demand),
        "hot_demand": pytest.approx(hot_demand),
        "cold_flow_setpoint": pytest.approx(cold_target),
        "hot_flow_setpoint": pytest.approx(hot_target),
        "total_flow_setpoint": pytest.approx(cold_target + hot_target),
        "cold_damper": pytest.approx(cold_command),
        "hot_damper": pytest.approx(hot_command),
    }
    inputs = {node.id for node in program.nodes if node.kind == "Input"}
    expected = {"zone"} | {deck + "_airflow" for deck in layout.split("-")}
    assert inputs == expected
    assert program.target.physical_inputs is None and program.target.physical_outputs is None
    assert not any("terminal" in node.params for node in program.nodes)
    assert not {"reheat", "fan", "damper"}.intersection(node.id for node in program.nodes)


@pytest.mark.parametrize("zone,expected", [(74, (52.16, 10)), (66, (20, 46.18)), (70, (20, 10))])
def test_position_mapping_is_two_commands_with_explicit_simultaneous_minima(zone, expected):
    program = generate(dual("none", dual_duct={"hot_damper_min": 10.0}))
    row = Engine(program).step({"zone": zone})["outputs"]
    assert (row["cold_damper"], row["hot_damper"]) == pytest.approx(expected)
    assert row["control_permitted"] and "airflow_consistent" not in row
    assert {n.id for n in program.nodes if n.kind == "Input"} == {"zone"}
    assert (
        "simultaneous" in str(program.metadata) and "Uncertified" in program.metadata["compliance"]
    )


@pytest.mark.parametrize(
    "flow_loop,ki,expected", [("P", 0.0, [12.0, 12.0, 12.0]), ("PI", 0.001, [12.12, 12.24, 12.36])]
)
def test_declared_p_and_pi_flow_strategies_have_independent_retained_trajectories(
    flow_loop, ki, expected
):
    engine = Engine(
        generate(dual(temperature_loop="P", temperature_ki=0.0, flow_loop=flow_loop, flow_ki=ki))
    )
    assert [engine.step()["outputs"]["cold_damper"] for _ in range(3)] == pytest.approx(expected)


@pytest.mark.parametrize(
    "layout,bad,raw_deck",
    [
        ("hot-cold", {"cold_airflow": -1.0}, "cold_flow"),
        ("hot-total", {"total_airflow": 199.0}, "cold_flow"),
        ("cold-total", {"total_airflow": 399.0}, "hot_flow"),
    ],
)
def test_negative_measurement_or_derived_flow_preserves_raw_value_gates_commands_and_holds_integrals(
    layout, bad, raw_deck
):
    engine = Engine(generate(dual(layout)))
    assert engine.step()["outputs"]["cold_damper"] == pytest.approx(12.2816)
    state = copy.deepcopy(engine.state)
    row = engine.step(bad)["outputs"]
    assert row[raw_deck] == -1
    assert not row["airflow_consistent"] and not row["control_permitted"]
    assert row["setpoints_ordered"]
    assert row["cold_damper"] == row["hot_damper"] == 0
    assert engine.state == state
    # A resumed valid scan advances from the first valid scan's integrals only.
    restored = {"cold_airflow": 400.0} if layout == "hot-cold" else {"total_airflow": 600.0}
    assert engine.step(restored)["outputs"]["cold_damper"] == pytest.approx(12.5648)


@pytest.mark.parametrize("layout", ["none", "hot-cold", "hot-total", "cold-total"])
def test_crossed_or_equal_external_setpoints_gate_both_decks_without_losing_integral_state(layout):
    engine = Engine(generate(dual(layout, setpoints="inputs")))
    engine.step()
    state = copy.deepcopy(engine.state)
    for heating in (72.0, 75.0):
        row = engine.step({"heat_sp": heating})["outputs"]
        assert not row["setpoints_ordered"] and not row["control_permitted"]
        assert row["cold_damper"] == row["hot_damper"] == 0
        assert engine.state == state


@pytest.mark.parametrize("layout", ["none", "hot-cold", "hot-total", "cold-total"])
def test_mode_transition_retains_but_does_not_publish_inactive_temperature_integral(layout):
    engine = Engine(generate(dual(layout)))
    engine.step({"zone": 74.0})
    cold_integral = engine.state["cold_temperature_loop"]["integral"]
    row = engine.step({"zone": 66.0})["outputs"]
    assert row["cold_demand"] == 0 and row["hot_demand"] == pytest.approx(40.2)
    assert engine.state["cold_temperature_loop"]["integral"] == cold_integral
    row = engine.step({"zone": 70.0})["outputs"]
    assert row["cold_demand"] == row["hot_demand"] == 0


@pytest.mark.parametrize("layout", ["none", "hot-cold", "hot-total", "cold-total"])
def test_open_circuit_flow_or_zone_fault_rolls_back_every_state_and_output(layout):
    engine = Engine(generate(dual(layout)))
    engine.step()
    before = engine.snapshot()
    key = "zone" if layout == "none" else layout.split("-")[0] + "_airflow"
    with pytest.raises(ScanError, match="open-circuit"):
        engine.step({key: {"value": 0.0, "quality": "open-circuit"}})
    assert engine.snapshot() == before


@pytest.mark.parametrize("layout", ["none", "hot-cold", "hot-total", "cold-total"])
@pytest.mark.parametrize(
    "temperature_unit,flow_unit", [("degC", "cfm"), ("degF", "L/s"), ("degC", "L/s")]
)
def test_coupled_unit_and_gain_conversion_preserves_both_deck_trajectories(
    layout, temperature_unit, flow_unit
):
    source = dual(layout)
    converted = convert_units(source, temperature_unit, flow_unit)
    factor = 0.4719474432 if flow_unit == "L/s" else 1
    assert converted.dual_duct.hot_flow_min == pytest.approx(source.dual_duct.hot_flow_min * factor)
    assert converted.dual_duct.total_flow_default == pytest.approx(
        source.dual_duct.total_flow_default * factor
    )
    original, metric = Engine(generate(source)), Engine(generate(converted))
    for _ in range(3):
        a, b = original.step()["outputs"], metric.step()["outputs"]
        for name in ("cold_damper", "hot_damper", "cold_demand", "hot_demand"):
            assert b[name] == pytest.approx(a[name])
        if layout != "none":
            for name in (
                "cold_flow",
                "hot_flow",
                "total_flow",
                "cold_flow_setpoint",
                "hot_flow_setpoint",
                "total_flow_setpoint",
            ):
                assert b[name] == pytest.approx(a[name] * factor)
    assert convert_units(converted, "degF", "cfm").dual_duct.model_dump() == pytest.approx(
        source.dual_duct.model_dump()
    )


@pytest.mark.parametrize("layout", ["none", "hot-cold", "hot-total", "cold-total"])
@pytest.mark.parametrize("format", ["json", "st", "plcopen", "graphml"])
def test_dual_generated_editable_formats_preserve_new_profile_choices_and_source(layout, format):
    source = generate(dual(layout, setpoints="inputs"))
    data, _, extension = export_program(source, format)
    reopened = import_program(data, "dual." + extension)
    assert reopened == source and reopened.digest() == source.digest()
    result = preview(dual(layout))
    assert result["can_create"] and result["profile_sha256"] == DUAL_PROFILE_SHA
    assert result["profile"]["source"]["pdf_pages"] == [594, 595, 596]
    assert result["native_compile"] is False and result["controller_writes"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"layout": "total-only"},
        {"layout": ""},
        {"layout": None},
        {"layout": "hot-total", "total_flow_default": 199.0},
        {"layout": "cold-total", "total_flow_default": 399.0},
        {"hot_flow_min": 800.0},
        {"hot_flow_max": float("inf")},
        {"hot_flow_default": True},
        {"total_flow_default": "600"},
        {"hot_flow_max": 1e12},
        {"native_actuator": "integrated"},
    ],
)
def test_explicit_supported_pickup_layout_and_strict_active_bounds(changes):
    layout = changes.get("layout", "hot-cold")
    with pytest.raises(ValueError):
        dual(layout, dual_duct=changes)


def test_strategy_layout_dependencies_and_inactive_values_are_not_silently_reinterpreted():
    for control, layout in (("position", "hot-cold"), ("flow-feedback", "none")):
        with pytest.raises(ValueError):
            Choices(
                project_id="a",
                name="a",
                equipment="dual-duct",
                control=control,
                dual_duct={"layout": layout},
            )
    with pytest.raises(ValueError):
        Choices(project_id="a", name="a", equipment="dual-duct")
    with pytest.raises(ValueError):
        Choices(project_id="a", name="a", dual_duct={"layout": "none"})
    assert preview(dual("hot-total", flow_default=1e12))["can_create"]
    assert (
        "flow_default"
        in generate(dual("hot-total")).metadata["equipment_wizard"]["inactive_choices"]
    )


# Literal hashes measured from published cohort18, before this feature existed.
@pytest.mark.parametrize(
    "equipment,control,program_hash,choice_hash",
    [
        (
            "cooling-only",
            "position",
            "3f2f0ffbaa04772c7b826cd20f197c6057cac297982c2438a315e62755b9c7c4",
            "d39a917e647e9b23131dc74a989b0a00b111a1a2add4827627fe3bb748be489e",
        ),
        (
            "cooling-only",
            "flow-feedback",
            "bed1b7a4ba1df08d609358521978b5e3bfe0343523a990e9d87e56338e4857f7",
            "c614add9fc83ba0687ea0b0d0aa3c0a0971e40a4e48c44ffb1c327f3a880ecdd",
        ),
        (
            "inline-reheat",
            "position",
            "51b43ffb502f2690e007a866b4c22f963182942f0dc6b74aadae03f29e472408",
            "a9e45b731def7a62189d4194ad20071cf046fe94c52c2f41a9378881656ecac1",
        ),
        (
            "inline-reheat",
            "flow-feedback",
            "ffb4d815ae721f573d24bc409505ec6e5ad1dd1dba0a078eb83b0599c39992d4",
            "0254452b4ac4547ad1b37a6e0167601e4eea02db5ae719813032df0af6b8f77f",
        ),
        (
            "parallel-fan-reheat",
            "position",
            "15f639a5001f036553f799a4edcef5c439b6ded7b896c5bc711b6452fb077694",
            "bfecd71086713a0fbde003db74f2eba8c8bd0aad85c197810182665322fe55b4",
        ),
        (
            "parallel-fan-reheat",
            "flow-feedback",
            "ac91931d8af4ec48397af80a6d3408083059f6aa3d29006ddd333cd0943c8c23",
            "7a2ab2b2166344f45f608ba0ab325c0f39888c2ddd132785d5edea9f41131565",
        ),
    ],
    ids=[
        "cooling-position",
        "cooling-feedback",
        "inline-position",
        "inline-feedback",
        "parallel-position",
        "parallel-feedback",
    ],
)
def test_published_single_duct_generation_profile_choices_and_program_hashes_are_unchanged(
    equipment, control, program_hash, choice_hash
):
    value = Choices(
        project_id="legacy-wizard", name="Legacy wizard", equipment=equipment, control=control
    )
    assert PROFILE_SHA == "ae49076cd8ccba78b44ba07a12bcf3a1737200fdb2f9d373ec10925d5680cf0c"
    assert "dual_duct" not in choice_document(value)
    assert digest(choice_document(value)) == choice_hash
    assert generate(value).digest() == program_hash
