"""Independent declared fan/valve state matrices; no native JCI semantics."""

import copy

import pytest
from bms_tool.engine import Engine, ScanError
from bms_tool.equipment_wizard import (
    DUAL_PROFILE_SHA,
    FAN_PROFILE_SHA,
    Choices,
    choice_document,
    convert_units,
    digest,
    generate,
    preview,
)
from bms_tool.formats import export_program, import_program


def fan_choices(fan="variable-speed", policy="continuous-occupied", condensate="none", **changes):
    nested = {
        "coils": "separate-modulating",
        "fan": fan,
        "fan_policy": policy,
        "condensate": condensate,
    } | changes.pop("fan_coil", {})
    return Choices(
        project_id="fan-authored",
        name="Authored fan coil",
        equipment="fan-coil",
        control="not-applicable",
        fan_coil=nested,
        **changes,
    )


@pytest.mark.parametrize("fan", ["single-speed", "variable-speed"])
@pytest.mark.parametrize("policy", ["continuous-occupied", "cycle-on-demand"])
@pytest.mark.parametrize("condensate", ["none", "disable-cooling", "shutdown-unit"])
@pytest.mark.parametrize(
    "zone,cooling,heating",
    [(74, 40.2, 0), (66, 0, 40.2), (70, 0, 0), (100, 100, 0), (40, 0, 100)],
)
def test_declared_occupied_modes_have_independent_valve_and_fan_calculations(
    fan, policy, condensate, zone, cooling, heating
):
    program = generate(fan_choices(fan, policy, condensate))
    result = Engine(program).step({"zone": zone})["outputs"]
    running = policy == "continuous-occupied" or cooling > 0 or heating > 0
    expected = {
        "setpoints_ordered": True,
        "control_permitted": True,
        "cooling_permitted": True,
        "heating_permitted": True,
        "cooling_demand": pytest.approx(cooling),
        "heating_demand": pytest.approx(heating),
        "cooling_valve": pytest.approx(cooling),
        "heating_valve": pytest.approx(heating),
        "fan_enable": running,
    }
    if fan == "variable-speed":
        expected["fan_speed"] = pytest.approx((20 + 0.8 * max(cooling, heating)) if running else 0)
    assert result == expected
    inputs = {n.id for n in program.nodes if n.kind == "Input"}
    assert inputs == {"zone", "occupied", "unit_enable", "energy_holdoff"} | (
        {"condensate_alarm"} if condensate != "none" else set()
    )
    assert not {"damper", "fan", "reheat", "airflow"}.intersection(n.id for n in program.nodes)
    assert program.target.physical_inputs is None and program.target.physical_outputs is None


@pytest.mark.parametrize("fan", ["single-speed", "variable-speed"])
@pytest.mark.parametrize("policy", ["continuous-occupied", "cycle-on-demand"])
@pytest.mark.parametrize("condensate", ["disable-cooling", "shutdown-unit"])
@pytest.mark.parametrize("zone", [74, 66, 70])
def test_condensate_cooling_inhibit_is_distinct_from_unit_shutdown(fan, policy, condensate, zone):
    result = Engine(generate(fan_choices(fan, policy, condensate))).step(
        {"zone": zone, "condensate_alarm": True}
    )["outputs"]
    shutdown = condensate == "shutdown-unit"
    heating = 40.2 if not shutdown and zone == 66 else 0
    running = not shutdown and (policy == "continuous-occupied" or heating > 0)
    assert result["control_permitted"] is (not shutdown)
    assert result["cooling_permitted"] is False and result["heating_permitted"] is (not shutdown)
    assert result["cooling_valve"] == 0 and result["heating_valve"] == pytest.approx(heating)
    assert result["fan_enable"] is running
    if fan == "variable-speed":
        assert result["fan_speed"] == pytest.approx((20 + 0.8 * heating) if running else 0)


@pytest.mark.parametrize("fan", ["single-speed", "variable-speed"])
@pytest.mark.parametrize("policy", ["continuous-occupied", "cycle-on-demand"])
@pytest.mark.parametrize(
    "change",
    [
        {"occupied": False},
        {"unit_enable": False},
        {"energy_holdoff": True},
        {"heat_sp": 72.0},
        {"heat_sp": 75.0},
    ],
    ids=["unoccupied", "disabled", "holdoff", "equal-setpoints", "crossed-setpoints"],
)
def test_off_permissions_gate_all_commands_and_hold_integrals_until_resume(fan, policy, change):
    engine = Engine(generate(fan_choices(fan, policy, setpoints="inputs")))
    assert engine.step()["outputs"]["cooling_valve"] == pytest.approx(40.2)
    state = copy.deepcopy(engine.state)
    result = engine.step(change)["outputs"]
    assert not result["control_permitted"] and not result["fan_enable"]
    assert result["cooling_valve"] == result["heating_valve"] == 0
    assert engine.state == state
    if fan == "variable-speed":
        assert result["fan_speed"] == 0
    assert engine.step()["outputs"]["cooling_valve"] == pytest.approx(40.4)


def test_condensate_inhibit_holds_only_inhibited_temperature_loop_and_resumes_retained_integral():
    engine = Engine(generate(fan_choices(condensate="disable-cooling")))
    engine.step()
    state = copy.deepcopy(engine.state)
    result = engine.step({"condensate_alarm": True})["outputs"]
    assert engine.state == state and result["cooling_valve"] == 0 and result["fan_enable"]
    assert result["fan_speed"] == 20
    assert engine.step()["outputs"]["cooling_valve"] == pytest.approx(40.4)
    result = engine.step({"zone": 66.0, "condensate_alarm": True})["outputs"]
    assert result["heating_valve"] == pytest.approx(40.2) and result["fan_enable"]


@pytest.mark.parametrize("policy", ["continuous-occupied", "cycle-on-demand"])
def test_declared_variable_speed_limits_and_zero_gain_are_not_physical_fan_proof(policy):
    value = fan_choices(
        policy=policy,
        fan_coil={"fan_min": 35.0, "fan_max": 75.0},
        temperature_loop="P",
        temperature_ki=0.0,
    )
    result = Engine(generate(value)).step()["outputs"]
    assert result["fan_speed"] == pytest.approx(51)
    result = Engine(generate(value)).step({"zone": 100.0})["outputs"]
    assert result["cooling_valve"] == 100 and result["fan_speed"] == 75
    stopped = generate(value.model_copy(update={"temperature_kp": 0.0}))
    result = Engine(stopped).step()["outputs"]
    assert result["cooling_valve"] == 0
    assert result["fan_enable"] is (policy == "continuous-occupied")
    assert result["fan_speed"] == (35 if policy == "continuous-occupied" else 0)


@pytest.mark.parametrize(
    "nested",
    [
        {"occupied_default": False},
        {"unit_enable_default": False},
        {"energy_holdoff_default": True},
        {"condensate_default": True},
    ],
    ids=["unoccupied", "disabled", "holdoff", "condensate-shutdown"],
)
def test_declared_boolean_input_defaults_apply_on_first_scan(nested):
    program = generate(fan_choices(condensate="shutdown-unit", fan_coil=nested))
    result = Engine(program).step()["outputs"]
    assert result["fan_enable"] is False
    assert result["cooling_valve"] == result["heating_valve"] == result["fan_speed"] == 0


@pytest.mark.parametrize(
    "key", ["zone", "occupied", "unit_enable", "energy_holdoff", "condensate_alarm"]
)
def test_bad_quality_is_atomic_retained_output_fault_not_a_physical_shutdown(key):
    engine = Engine(generate(fan_choices(condensate="shutdown-unit")))
    engine.step()
    before = engine.snapshot()
    assert before["outputs"]["cooling_valve"] > 0
    with pytest.raises(ScanError, match="open-circuit"):
        engine.step({key: {"value": False if key != "zone" else 0.0, "quality": "open-circuit"}})
    assert engine.snapshot() == before


@pytest.mark.parametrize("fan", ["single-speed", "variable-speed"])
@pytest.mark.parametrize("policy", ["continuous-occupied", "cycle-on-demand"])
def test_temperature_conversion_preserves_valves_fan_trajectory_and_percentage_limits(fan, policy):
    original = fan_choices(fan, policy, condensate="disable-cooling")
    metric = convert_units(original, "degC", "L/s")
    assert metric.temperature_kp == 36 and metric.temperature_ki == pytest.approx(0.18)
    assert metric.fan_coil == original.fan_coil
    a, b = Engine(generate(original)), Engine(generate(metric))
    for zone in (74, 66, 70, 74):
        left = a.step({"zone": zone})["outputs"]
        right = b.step({"zone": (zone - 32) * 5 / 9})["outputs"]
        for key, value in left.items():
            if type(value) is bool:
                assert right[key] is value
            else:
                assert right[key] == pytest.approx(value)
    assert "flow_unit" in generate(metric).metadata["equipment_wizard"]["inactive_choices"]


@pytest.mark.parametrize(
    "strategy,ki,expected", [("P", 0.0, [40, 40, 40]), ("PI", 0.1, [40.2, 40.4, 40.6])]
)
def test_fixed_p_vs_pi_has_independent_retained_demand_trajectory(strategy, ki, expected):
    engine = Engine(generate(fan_choices(temperature_loop=strategy, temperature_ki=ki)))
    assert [engine.step()["outputs"]["cooling_valve"] for _ in range(3)] == pytest.approx(expected)


@pytest.mark.parametrize("fan", ["single-speed", "variable-speed"])
@pytest.mark.parametrize("policy", ["continuous-occupied", "cycle-on-demand"])
@pytest.mark.parametrize("format", ["json", "st", "plcopen", "graphml"])
def test_new_profile_choices_and_editable_graph_survive_interchange(fan, policy, format):
    value = fan_choices(fan, policy, condensate="shutdown-unit", setpoints="inputs")
    program = generate(value)
    data, _, extension = export_program(program, format)
    reopened = import_program(data, "fan." + extension)
    assert reopened == program and reopened.digest() == program.digest()
    report = preview(value)
    assert report["profile_sha256"] == FAN_PROFILE_SHA and report["can_create"]
    assert report["profile"]["source"]["pdf_pages"] == [479, 480, 481, 482, 483]
    assert report["native_compile"] is False and report["controller_writes"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"coils": "two-pipe"},
        {"fan": "three-speed"},
        {"fan_policy": "automatic-native"},
        {"condensate": "ignore-and-cool"},
        {"fan_min": True},
        {"occupied_default": 1},
        {"unit_enable_default": "true"},
        {"energy_holdoff_default": None},
        {"fan_max": float("nan")},
        {"fan_min": 100.0},
        {"actuator": "0-10V"},
    ],
    ids=[
        "two-pipe",
        "three-speed",
        "unknown-policy",
        "unknown-condensate",
        "bool-number",
        "numeric-bool",
        "string-bool",
        "null-bool",
        "nonfinite",
        "equal-range",
        "native-allocation",
    ],
)
def test_explicit_supported_equipment_choices_and_strict_types(change):
    with pytest.raises(ValueError):
        fan_choices(fan_coil=change)


def test_inactive_limits_do_not_allocate_hardware_or_constrain_single_speed_and_missing_schema_is_refused():
    value = fan_choices(
        fan="single-speed", fan_coil={"fan_min": 100.0, "fan_max": 0.0, "condensate_default": True}
    )
    report = preview(value)
    assert report["can_create"]
    assert {"fan_coil.fan_min", "fan_coil.fan_max", "fan_coil.condensate_default"}.issubset(
        report["program"]["metadata"]["equipment_wizard"]["inactive_choices"]
    )
    assert "condensate_alarm" not in {n.id for n in generate(value).nodes}
    for changes in ({"fan_coil": None}, {"control": "position"}, {"dual_duct": {"layout": "none"}}):
        data = value.model_dump() | changes
        with pytest.raises(ValueError):
            Choices.model_validate(data)
    with pytest.raises(ValueError):
        Choices(project_id="a", name="a", fan_coil=value.fan_coil)


# Literal hashes measured from the published dual graph before adding FC fields.
@pytest.mark.parametrize(
    "layout,program_hash,choice_hash",
    [
        (
            "none",
            "fc376299ccbaa825b917578c1acbd40b4453eac817d69aae26a988ce5a678023",
            "1013c24bbfc71d8e4a20a83497eb62350957cbc3e798a7c66c7465254a276588",
        ),
        (
            "hot-cold",
            "a0d36aa4eb3d31875494364225139bf78a657302abbc93a2a11bffb11c50cde0",
            "2760ad802c8aba56311437b1e20b76c44c958874f431084597eb1919e8ad6f61",
        ),
        (
            "hot-total",
            "1010fb22145c294ddd23b2946f480149d31bcc8fcd80d01ab20d220297cd5f9e",
            "e298f7c918cefebf6a2b89e2d1eda2845880c8d75dacfad54e19c51069d5a077",
        ),
        (
            "cold-total",
            "d6515be4ca10921901726a72fb8fd7a7ff65f0bf490c2987d66cff0ede1ad7b3",
            "efa7fbe1cc3ba32aa9ccb638c81039d6fdceab673b93111085434686757491d0",
        ),
    ],
    ids=["position", "hot-cold", "hot-total", "cold-total"],
)
def test_published_dual_duct_profile_program_and_choice_hashes_stay_exact(
    layout, program_hash, choice_hash
):
    value = Choices(
        project_id="prior-dual",
        name="Prior dual",
        equipment="dual-duct",
        control="position" if layout == "none" else "flow-feedback",
        dual_duct={"layout": layout},
    )
    assert DUAL_PROFILE_SHA == "b68ad19ed818f03d6766d678d23f19f96221bb8e521fd315a88d465986bb73d2"
    assert "fan_coil" not in value.model_dump()
    assert (
        generate(value).digest() == program_hash and digest(choice_document(value)) == choice_hash
    )
