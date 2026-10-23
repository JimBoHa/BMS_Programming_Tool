"""Inspectable compressor/valve sequence boundaries, not native hardware acceptance."""

import copy
import itertools

import pytest
from bms_tool.engine import Engine, validate
from bms_tool.formats import export_program, import_program
from bms_tool.heat_pump import (
    OUTPUTS,
    PROFILE,
    PROFILE_SHA,
    Choices,
    PreviewRequest,
    choice_document,
    convert_units,
    digest,
    generate,
    preview,
)
from pydantic import ValidationError


def choices(**patch):
    return Choices.model_validate(
        {
            "project_id": "authored-heat-pump",
            "name": "Authored heat pump",
            "reversing_polarity": "on-for-heating",
            "initial_mode": "cooling",
            "fan_policy": "cycle-on-demand",
            "condensate": "none",
            "minimum_on_seconds": 4,
            "minimum_off_seconds": 2,
            "valve_off_seconds": 2,
            "valve_settle_seconds": 2,
            "airflow_proven_default": True,
        }
        | patch
    )


def fahrenheit(value, unit):
    return value if unit == "degF" else (value - 32) * 5 / 9


def steady(engine, inputs=None, scans=10):
    result = None
    for _ in range(scans):
        result = engine.step(inputs)
    return result["outputs"]


COMPOSITIONS = list(
    itertools.product(
        ["on-for-heating", "on-for-cooling"],
        ["heating", "cooling"],
        ["continuous-occupied", "cycle-on-demand"],
        ["none", "disable-cooling", "shutdown-unit"],
        ["degF", "degC"],
    )
)


@pytest.mark.parametrize("polarity,initial,fan,condensate,unit", COMPOSITIONS)
def test_all_compositions_are_typed_editable_unit_correct_and_source_bound(
    polarity, initial, fan, condensate, unit
):
    value = choices(
        reversing_polarity=polarity, initial_mode=initial, fan_policy=fan, condensate=condensate
    )
    value = convert_units(value, unit)
    report = preview(PreviewRequest(choices=value))
    assert report["can_create"] and report["diagnostics"] == []
    assert report["profile"] == PROFILE and report["profile_sha256"] == PROFILE_SHA
    assert report["choices_sha256"] == digest(choice_document(value))
    assert not report["native_compile"] and not report["controller_writes"]
    program = generate(value)
    assert program.digest() == report["program_sha256"]
    assert len(program.nodes) <= PROFILE["limits"]["nodes"]
    assert {n.id for n in program.nodes if n.kind == "Output"} == set(OUTPUTS)
    provenance = program.metadata["heat_pump_wizard"]
    assert provenance["choices"] == report["choices"]
    assert provenance["outputs"] == OUTPUTS
    assert not program.metadata["native_deployment_verified"]
    engine = Engine(program)
    cold = steady(engine, {"zone": fahrenheit(80, unit)})
    assert cold["compressor"] and cold["cooling_active"] and cold["fan"]
    assert not cold["heating_active"]
    assert cold["reversing_valve"] == (polarity == "on-for-cooling")
    first_reverse = engine.step({"zone": fahrenheit(60, unit)})["outputs"]
    assert (
        not first_reverse["compressor"]
        and first_reverse["reversing_valve"] == cold["reversing_valve"]
    )
    hot = steady(engine, {"zone": fahrenheit(60, unit)})
    assert hot["compressor"] and hot["heating_active"] and hot["fan"]
    assert not hot["cooling_active"]
    assert hot["reversing_valve"] == (polarity == "on-for-heating")


@pytest.mark.parametrize("fmt,suffix", [("json", "json"), ("st", "st"), ("plcopen", "xml")])
def test_real_editable_interchange_roundtrip_retains_full_graph_and_provenance(fmt, suffix):
    program = generate(choices(condensate="disable-cooling", setpoints="inputs"))
    content, _, _ = export_program(program, fmt)
    assert import_program(content, "heat-pump." + suffix) == program


def test_default_airflow_permission_stays_false_while_fan_starts_before_proof():
    value = choices(
        minimum_on_seconds=120,
        minimum_off_seconds=120,
        valve_off_seconds=6,
        valve_settle_seconds=6,
        airflow_proven_default=False,
    )
    engine = Engine(generate(value))
    for _ in range(120):
        out = engine.step()["outputs"]
        assert out["fan"] and out["cooling_request"] and not out["compressor"]
    assert engine.step({"airflow_proven": True})["outputs"]["compressor"]


def test_exact_start_minimum_on_ordinary_demand_loss_and_fan_hold():
    engine = Engine(generate(choices(valve_off_seconds=1, valve_settle_seconds=1)))
    first = engine.step()["outputs"]
    assert not first["compressor"]
    assert engine.step()["outputs"]["compressor"]
    for _ in range(3):
        out = engine.step({"zone": 70})["outputs"]
        assert not out["cooling_request"] and not out["heating_request"]
        assert out["compressor"] and out["minimum_on_hold"] and out["fan"]
    out = engine.step({"zone": 70})["outputs"]
    assert not out["compressor"] and not out["minimum_on_hold"] and not out["fan"]
    # Restart needs a fresh full off interval even though the valve mode stays.
    assert not engine.step({"zone": 80})["outputs"]["compressor"]
    assert engine.step({"zone": 80})["outputs"]["compressor"]


def test_off_before_valve_and_after_valve_are_distinct_from_minimum_off():
    engine = Engine(
        generate(choices(minimum_off_seconds=2, valve_off_seconds=4, valve_settle_seconds=3))
    )
    rows = [engine.step({"zone": 80})["outputs"] for _ in range(3)]
    assert rows[-1]["compressor"]
    rows += [engine.step({"zone": 60})["outputs"] for _ in range(8)]
    # t4 stops, keeps cooling valve; t8 switches after4 full off intervals;
    # t11 starts after3 additional settled intervals despite minoff2 alreadyready.
    assert all(not r["compressor"] for r in rows[3:10])
    assert all(not r["reversing_valve"] for r in rows[:7])
    assert all(r["reversing_valve"] for r in rows[7:])
    assert rows[10]["compressor"]
    for previous, current in zip(rows, rows[1:], strict=False):
        if previous["reversing_valve"] != current["reversing_valve"]:
            assert not previous["compressor"] and not current["compressor"]


def test_rapid_reversal_resets_valve_stability_and_never_switches_while_running():
    engine = Engine(
        generate(choices(minimum_off_seconds=1, valve_off_seconds=1, valve_settle_seconds=3))
    )
    assert not engine.step({"zone": 80})["outputs"]["compressor"]
    assert not engine.step({"zone": 80})["outputs"]["compressor"]
    running = engine.step({"zone": 80})["outputs"]
    assert running["compressor"]
    rows = [running]
    for temperature in (60, 60, 80, 60, 80, 80, 80, 80):
        rows.append(engine.step({"zone": temperature})["outputs"])
    assert all(not row["compressor"] for row in rows[1:-1])
    assert rows[-1]["compressor"]
    # Off-state valve changes are intentionally not rate-limited. Each flip
    # resets settling; compressor start still waits for stability.
    assert [r["reversing_valve"] for r in rows[2:6]] == [True, False, True, False]
    for previous, current in zip(rows, rows[1:], strict=False):
        if previous["reversing_valve"] != current["reversing_valve"]:
            assert not previous["compressor"] and not current["compressor"]
    assert not rows[5]["valve_settled"] and not rows[6]["valve_settled"]


@pytest.mark.parametrize(
    "input_name,value,fan",
    [
        ("occupied", False, False),
        ("unit_enable", False, False),
        ("energy_holdoff", True, False),
        ("airflow_proven", False, True),
    ],
)
def test_hard_permissions_override_unexpired_minimum_on(input_name, value, fan):
    engine = Engine(generate(choices()))
    engine.step()
    assert engine.step()["outputs"]["compressor"]
    out = engine.step({input_name: value})["outputs"]
    assert not out["compressor"] and not out["minimum_on_hold"]
    assert out["fan"] is fan
    assert not out["reversing_valve"]


@pytest.mark.parametrize(
    "condensate,mode,fan",
    [
        ("disable-cooling", "cooling", False),
        ("disable-cooling", "heating", True),
        ("shutdown-unit", "cooling", False),
        ("shutdown-unit", "heating", False),
    ],
)
def test_condensate_policy_differs_for_cooling_only_and_unit_shutdown(condensate, mode, fan):
    value = choices(condensate=condensate, initial_mode=mode)
    engine = Engine(generate(value))
    temperature = 80 if mode == "cooling" else 60
    steady(engine, {"zone": temperature}, scans=2)
    out = engine.step({"zone": temperature, "condensate_alarm": True})["outputs"]
    assert out["compressor"] is (condensate == "disable-cooling" and mode == "heating")
    assert out["fan"] is fan


def test_condensate_cooling_inhibit_leaves_continuous_fan_and_idle_valve_hold():
    engine = Engine(
        generate(
            choices(
                condensate="disable-cooling",
                fan_policy="continuous-occupied",
                initial_mode="heating",
            )
        )
    )
    before = steady(engine, {"zone": 60})
    out = engine.step({"unit_enable": False, "zone": 80})["outputs"]
    assert not out["compressor"] and not out["fan"]
    assert out["reversing_valve"] == before["reversing_valve"]
    out = steady(engine, {"condensate_alarm": True, "zone": 80})
    assert out["fan"] and not out["compressor"]


def test_external_crossed_setpoints_stop_without_waiting_minimum_on():
    engine = Engine(generate(choices(setpoints="inputs")))
    engine.step()
    assert engine.step()["outputs"]["compressor"]
    out = engine.step({"heat_sp": 75, "cool_sp": 70})["outputs"]
    assert not out["unit_permitted"] and not out["fan"] and not out["compressor"]
    assert not out["heating_request"] and not out["cooling_request"]


def test_hysteresis_boundary_and_mutually_exclusive_modes():
    engine = Engine(generate(choices()))
    for temperature, heat, cool in [
        (73, False, True),
        (72.5, False, True),
        (72, False, False),
        (67, True, False),
        (67.5, True, False),
        (68, False, False),
    ]:
        out = engine.step({"zone": temperature})["outputs"]
        assert out["heating_request"] is heat and out["cooling_request"] is cool


@pytest.mark.parametrize(
    "input_name", ["zone", "airflow_proven", "unit_enable", "condensate_alarm"]
)
def test_bad_quality_rolls_back_clock_timers_valve_and_running_outputs(input_name):
    engine = Engine(generate(choices(condensate="shutdown-unit")))
    steady(engine, scans=2)
    snapshot = (
        copy.deepcopy(engine.state),
        copy.deepcopy(engine.outputs),
        engine.time,
        engine.clock,
    )
    with pytest.raises(ValueError):
        engine.step({input_name: {"quality": "open-circuit"}})
    assert (engine.state, engine.outputs, engine.time, engine.clock) == snapshot
    assert engine.outputs["compressor"]
    assert engine.step()["outputs"]["compressor"]


@pytest.mark.parametrize("unit", ["degF", "degC"])
def test_unit_conversion_preserves_temperatures_differences_and_all_nonunit_choices(unit):
    original = choices(
        zone_default=32,
        heating_setpoint=-148,
        cooling_setpoint=392,
        demand_on_delta=180,
        demand_off_delta=18,
    )
    converted = convert_units(original, unit)
    back = convert_units(converted, "degF")
    for name in (
        "zone_default",
        "heating_setpoint",
        "cooling_setpoint",
        "demand_on_delta",
        "demand_off_delta",
    ):
        assert getattr(back, name) == pytest.approx(getattr(original, name), abs=1e-12)
    unchanged = original.model_dump().keys() - {
        "temperature_unit",
        "zone_default",
        "heating_setpoint",
        "cooling_setpoint",
        "demand_on_delta",
        "demand_off_delta",
    }
    assert all(getattr(converted, key) == getattr(original, key) for key in unchanged)
    if unit == "degC":
        assert (
            converted.zone_default == 0
            and converted.demand_on_delta == 100
            and converted.demand_off_delta == 10
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"minimum_on_seconds": True},
        {"minimum_off_seconds": "120"},
        {"valve_off_seconds": 0},
        {"valve_settle_seconds": 3601},
        {"scan_seconds": 0.5},
        {"scan_seconds": True},
        {"scan_seconds": 61},
        {"scan_seconds": 4, "valve_off_seconds": 6},
        {"demand_on_delta": 0},
        {"demand_off_delta": 2},
        {"demand_on_delta": True},
        {"demand_on_delta": float("inf")},
        {"heating_setpoint": 72},
        {"zone_default": -149},
        {"zone_default": 393},
        {"zone_default": "74"},
        {"temperature_unit": "degC", "demand_on_delta": 101},
        {"airflow_proven_default": 1},
        {"reversing_polarity": "automatic"},
        {"initial_mode": "auto"},
        {"fan_policy": "variable-speed"},
        {"condensate": "alarm-only"},
        {"native_compile": True},
        {"family": "unverified"},
        {"name": " \n"},
    ],
)
def test_malformed_or_unsupported_choices_refuse_without_generation(patch):
    with pytest.raises(ValidationError):
        choices(**patch)


@pytest.mark.parametrize("family", ["universal-runtime", "johnson-fx", "johnson-metasys"])
def test_declared_family_is_not_native_acceptance(family):
    p = generate(choices(family=family, model="FX-PCV1630-0", firmware="declared"))
    assert p.target.family == family and p.target.model == "FX-PCV1630-0"
    assert not p.metadata["native_deployment_verified"]
    assert not [d for d in validate(p) if d.level == "error"]
