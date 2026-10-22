"""Independent authored VAV calculations and source/schema bounds; no field I/O."""

import hashlib
import json

import pytest
from bms_tool.engine import Engine, ScanError
from bms_tool.equipment_wizard import Choices, convert_units, generate, preview
from bms_tool.formats import export_program, import_program
from bms_tool.models import Program


def choices(**kwargs):
    return Choices(**({"project_id": "wizard-authored", "name": "Authored VAV"} | kwargs))


@pytest.mark.parametrize("loop,ki,expected", [("P", 0.0, 52.0), ("PI", 0.1, 52.16)])
def test_position_is_not_airflow_hand_calculated_pi(loop, ki, expected):
    p = generate(choices(temperature_loop=loop, temperature_ki=ki))
    assert Engine(p).step()["outputs"] == {"damper": pytest.approx(expected)}
    assert "airflow" not in {n.id for n in p.nodes}
    assert next(n for n in p.nodes if n.id == "position_map").label == "Damper position mapping"
    assert p.target.physical_inputs is None and p.target.physical_outputs is None
    assert all("terminal" not in n.params for n in p.nodes)


def test_measured_airflow_has_distinct_input_setpoint_and_loop_with_hand_calculation():
    p = generate(choices(control="flow-feedback"))
    row = Engine(p).step()
    # Zone2degF high =>40+.2=40.2%; desired200+800*.402=521.6cfm.
    # Flow error121.6cfm =>.1*121.6+.001*121.6*1=12.2816%.
    assert row["outputs"] == {
        "flow_setpoint": pytest.approx(521.6),
        "damper": pytest.approx(12.2816),
    }
    assert row["values"]["airflow"] == 400
    assert next(n for n in p.nodes if n.id == "flow_loop").kind == "PI"
    assert next(n for n in p.nodes if n.id == "flow_sp").unit == "cfm"
    assert next(n for n in p.nodes if n.id == "airflow").kind == "Input"


def test_flow_p_only_and_retained_pi_have_distinct_expected_trajectories():
    p = generate(
        choices(
            control="flow-feedback",
            temperature_loop="P",
            temperature_ki=0.0,
            flow_loop="P",
            flow_ki=0.0,
        )
    )
    engine = Engine(p)
    assert [engine.step()["outputs"]["damper"] for _ in range(3)] == pytest.approx(
        [12.0, 12.0, 12.0]
    )
    p = generate(choices(control="flow-feedback", temperature_loop="P", temperature_ki=0.0))
    engine = Engine(p)
    assert [engine.step()["outputs"]["damper"] for _ in range(3)] == pytest.approx(
        [12.12, 12.24, 12.36]
    )


@pytest.mark.parametrize("variant,fan", [("inline-reheat", False), ("parallel-fan-reheat", True)])
def test_heat_and_fan_choices_generate_actual_different_topology(variant, fan):
    p = generate(choices(equipment=variant, zone_default=66.0))
    result = Engine(p).step()["outputs"]
    assert result["reheat"] == pytest.approx(40.2)
    assert result["damper"] == 20
    assert ("fan" in result) == fan
    if fan:
        assert result["fan"] is True


def test_fan_hysteresis_and_quality_failure_do_not_fake_physical_proof():
    p = generate(choices(equipment="parallel-fan-reheat", temperature_loop="P", temperature_ki=0.0))
    engine = Engine(p)
    assert engine.step({"zone": 67.0})["outputs"]["fan"] is True
    assert engine.step({"zone": 67.9})["outputs"]["fan"] is True  # 2% demand holds between1/5.
    assert engine.step({"zone": 68.0})["outputs"]["fan"] is False
    before = engine.snapshot()
    with pytest.raises(ScanError, match="open-circuit"):
        engine.step({"zone": {"value": 66.0, "quality": "open-circuit"}})
    assert engine.snapshot() == before
    assert "fan proof" in json.dumps(p.metadata)


@pytest.mark.parametrize("variant", ["cooling-only", "inline-reheat", "parallel-fan-reheat"])
@pytest.mark.parametrize("control", ["position", "flow-feedback"])
def test_absolute_temperature_and_inverse_degree_flow_gains_preserve_physical_behavior(
    variant, control
):
    value = choices(equipment=variant, control=control)
    metric = convert_units(value, "degC", "L/s")
    assert metric.zone_default == pytest.approx(23.33333333333333)
    assert metric.cooling_setpoint == pytest.approx(22.22222222222222)
    assert metric.heating_setpoint == 20
    assert metric.temperature_kp == 36 and metric.temperature_ki == pytest.approx(0.18)
    assert metric.flow_min == pytest.approx(94.38948864)
    assert metric.flow_kp == pytest.approx(0.1 / 0.4719474432)
    assert metric.flow_ki == pytest.approx(0.001 / 0.4719474432)
    assert metric.scan_seconds == value.scan_seconds and metric.fan_on == value.fan_on
    first, second = Engine(generate(value)), Engine(generate(metric))
    for _ in range(4):
        f = first.step()
        s = second.step()
        assert f["outputs"]["damper"] == pytest.approx(s["outputs"]["damper"])
        if control == "flow-feedback":
            assert s["outputs"]["flow_setpoint"] == pytest.approx(
                f["outputs"]["flow_setpoint"] * 0.4719474432
            )
        if variant != "cooling-only":
            assert s["outputs"]["reheat"] == pytest.approx(f["outputs"]["reheat"])
    restored = convert_units(metric, "degF", "cfm")
    for key in (
        "zone_default",
        "cooling_setpoint",
        "heating_setpoint",
        "temperature_kp",
        "temperature_ki",
        "flow_min",
        "flow_max",
        "flow_kp",
        "flow_ki",
    ):
        assert getattr(restored, key) == pytest.approx(getattr(value, key))


def test_input_setpoint_choice_changes_signal_roles_and_is_editable():
    p = generate(
        choices(
            setpoints="inputs", equipment="inline-reheat", temperature_loop="P", temperature_ki=0.0
        )
    )
    assert {n.id for n in p.nodes if n.kind == "Input"} == {"zone", "cool_sp", "heat_sp"}
    assert Engine(p).step({"cool_sp": 73.0})["outputs"]["damper"] == 36
    content, _, _ = export_program(p, "json")
    assert import_program(content, "authored.bms.json") == p


def test_preview_profile_choice_and_program_hash_survive_browser_number_round_trip():
    report = preview(
        choices(
            control="flow-feedback",
            family="johnson-fx",
            model="FX-PCV1630-0",
            firmware="declared-6.2",
            release_mode="declared-10.2",
        )
    )
    assert report["can_create"] and not report["native_compile"] and not report["controller_writes"]
    assert any(row["code"] == "native_deployment" for row in report["issues"])
    assert report["topology"]["airflow_feedback"]
    raw = json.dumps(report["program"])

    def browser_numbers(v):
        if type(v) is float and v.is_integer():
            return int(v)
        if isinstance(v, list):
            return [browser_numbers(x) for x in v]
        if isinstance(v, dict):
            return {k: browser_numbers(x) for k, x in v.items()}
        return v

    transported = Program.model_validate(browser_numbers(json.loads(raw)))
    assert transported.digest() == report["program_sha256"]
    choice_raw = json.dumps(
        report["choices"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert hashlib.sha256(choice_raw).hexdigest() == report["choices_sha256"]
    assert transported.metadata["equipment_wizard"]["choices_sha256"] == report["choices_sha256"]
    assert transported.target.physical_inputs is None


@pytest.mark.parametrize(
    "changes",
    [
        {"control": "pressure-independent-native"},
        {"equipment": "series-fan"},
        {"family": "native-vma"},
        {"temperature_unit": "K"},
        {"flow_unit": "raw-volts"},
        {"temperature_kp": float("inf")},
        {"zone_default": True},
        {"name": "   "},
        {"project_id": "../../bad"},
        {"damper_min": 100.0, "damper_max": 100.0},
        {"control": "flow-feedback", "flow_min": 1000.0, "flow_max": 200.0},
        {"equipment": "inline-reheat", "heating_setpoint": 75.0},
        {"equipment": "parallel-fan-reheat", "fan_off": 10.0},
        {"temperature_loop": "P"},
        {"control": "flow-feedback", "flow_loop": "P"},
        {"scan_seconds": 0.0},
        {"model": "x" * 81},
        {"zone_default": 1000.0},
    ],
)
def test_bounded_strict_parameters_and_equipment_dependencies(changes):
    with pytest.raises(ValueError):
        choices(**changes)


def test_inactive_choices_are_recorded_but_do_not_constrain_unrelated_active_strategy():
    value = choices(
        cooling_setpoint=60.0,
        heating_setpoint=68.0,
        flow_min=1000.0,
        flow_max=200.0,
        fan_on=1.0,
        fan_off=5.0,
    )
    report = preview(value)
    assert report["can_create"]
    assert (
        "heating_setpoint" in report["program"]["metadata"]["equipment_wizard"]["inactive_choices"]
    )


@pytest.mark.parametrize("variant", ["cooling-only", "inline-reheat", "parallel-fan-reheat"])
@pytest.mark.parametrize("control", ["position", "flow-feedback"])
@pytest.mark.parametrize("format", ["json", "st", "plcopen", "graphml"])
def test_generated_editable_interchange_retains_choices_and_topology(variant, control, format):
    source = generate(choices(equipment=variant, control=control, setpoints="inputs"))
    data, _, extension = export_program(source, format)
    reopened = import_program(data, "wizard." + extension)
    assert reopened == source
    assert reopened.digest() == source.digest()


@pytest.mark.parametrize("control", ["position", "flow-feedback"])
@pytest.mark.parametrize("metric", [False, True])
def test_optional_independent_native_st_matches_hand_calculated_first_scan(control, metric):
    from bms_tool.iec import NativeIEC, profile

    if not profile()["available"]:
        pytest.skip("Optional pinned MatIEC/native C toolchain unavailable")
    value = choices(equipment="parallel-fan-reheat", control=control)
    if metric:
        value = convert_units(value, "degC", "L/s")
    # These are authored expectations, not outputs sampled from the graph engine.
    expected_damper = 52.16 if control == "position" else 12.2816
    with NativeIEC(generate(value)) as native:
        result = native.step()
        assert not result["fault"]
        assert result["outputs"]["damper"] == pytest.approx(expected_damper, abs=0.0001)
        assert result["outputs"]["reheat"] == 0
        assert result["outputs"]["fan"] is False
        if control == "flow-feedback":
            # Celsius subtraction runs in float32: explicit 0.001-flow-unit tolerance.
            expected_flow = 521.6 * (0.4719474432 if metric else 1)
            assert result["outputs"]["flow_setpoint"] == pytest.approx(expected_flow, abs=0.001)
