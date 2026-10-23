"""Independent AHU state, proof-deadline, PI and declared-source contracts."""

import itertools

import pytest
from bms_tool.engine import Engine, ScanError, validate
from bms_tool.masd_ahu import (
    Choices,
    Economizer,
    PreviewRequest,
    VariableFan,
    catalog_document,
    convert_units,
    generate,
    preview,
)
from pydantic import ValidationError

COMPOSITIONS = list(
    itertools.product(
        ("constant-speed", "variable-speed"),
        ("off", "fixed-drybulb", "differential-drybulb"),
        ("P", "PI"),
        ("degF", "degC"),
    )
)


def choices(*, fan="constant-speed", economizer="off", control="PI", unit="degF", **changes):
    options = Economizer(kp=4, ki=0.5 if control == "PI" else 0, assist_seconds=2)
    if economizer == "differential-drybulb":
        options = options.model_copy(
            update={"ra_default": 72, "differential_on": 3, "differential_off": 1}
        )
    value = {
        "project_id": "authored-ahu",
        "name": "Authored mixed-air AHU",
        "fan": fan,
        "variable_fan": VariableFan(kp=0.1, ki=0.001 if control == "PI" else 0).model_dump()
        if fan == "variable-speed"
        else None,
        "economizer": economizer,
        "economizer_control": options.model_dump() if economizer != "off" else None,
        "proof_seconds": 2,
        "stabilize_seconds": 2,
        "startup_timeout_seconds": 5,
        "recovery_timeout_seconds": 5,
        "release_seconds": 2,
        "heating_kp": 4,
        "heating_ki": 0.5 if control == "PI" else 0,
        "cooling_kp": 4,
        "cooling_ki": 0.5 if control == "PI" else 0,
        "occupied_default": True,
        "unit_enable_default": True,
        "fan_proven_default": True,
    }
    value.update(changes)
    return convert_units(Choices.model_validate(value), unit)


def temperature(value, unit):
    return value if unit == "degF" else (value - 32) * 5 / 9


def step(engine, sat=58, **inputs):
    return engine.step(
        {
            "sat": temperature(
                sat, engine.program.metadata["masd_ahu_wizard"]["choices"]["temperature_unit"]
            ),
            **inputs,
        }
    )["outputs"]


def ready(engine, sat=58):
    rows = [step(engine, sat) for _ in range(4)]
    assert [row["fan_ready"] for row in rows] == [False, False, False, True]
    return rows[-1]


@pytest.mark.parametrize("fan,economizer,control,unit", COMPOSITIONS)
def test_genuine_core_graph_port_dependencies_and_default_lifecycle(fan, economizer, control, unit):
    value = choices(fan=fan, economizer=economizer, control=control, unit=unit)
    program = generate(value)
    assert not [d for d in validate(program) if d.level == "error"]
    assert len(program.nodes) == len({n.id for n in program.nodes}) < 320
    assert {n.kind for n in program.nodes} <= {
        "Input",
        "Output",
        "Constant",
        "Delay",
        "TimerOn",
        "And",
        "Or",
        "Not",
        "Switch",
        "Less",
        "Greater",
        "Equal",
        "Max",
        "PI",
        "Scale",
        "TemperatureOffset",
        "TemperatureDifference",
        "Deadband",
    }
    ports = {n.id for n in program.nodes if n.kind == "Input"}
    base = {
        "occupied",
        "unit_enable",
        "energy_holdoff",
        "fan_proven",
        "fan_reset",
        "sat",
        "sat_setpoint",
    }
    if fan == "variable-speed":
        base |= {"duct_pressure", "duct_pressure_setpoint"}
    if economizer != "off":
        base |= {"outdoor_temperature", "economizer_enable"}
    if economizer == "differential-drybulb":
        base |= {"return_temperature"}
    assert ports == base
    result = ready(Engine(program))
    assert result["fan_enable"] and not result["fan_fault"]
    assert ("fan_speed" in result) == (fan == "variable-speed")
    assert result["heating_valve"] == 0
    metadata = program.metadata["masd_ahu_wizard"]
    assert metadata["inputs"] == [
        {
            "id": n.id,
            "label": n.label,
            "value_type": n.value_type,
            "unit": n.unit,
            "default": n.params["default"],
        }
        for n in program.nodes
        if n.kind == "Input"
    ]
    assert not program.metadata["native_deployment_verified"]


def test_unconfigured_defaults_are_explicitly_off_and_catalog_branch_units_are_source_bound():
    catalog = catalog_document()
    assert catalog["defaults"]["fan"] == catalog["defaults"]["economizer"] == ""
    value = Choices(
        project_id="off", name="Explicitly disabled AHU", fan="constant-speed", economizer="off"
    )
    result = Engine(generate(value)).step()["outputs"]
    assert (
        not result["fan_enable"]
        and result["mixing_damper"] == result["heating_valve"] == result["cooling_valve"] == 0
    )
    for unit in ("degF", "degC"):
        branch = catalog["branch_defaults"][unit]
        for mode in ("fixed-drybulb", "differential-drybulb"):
            source = catalog["branch_defaults"]["degF"]["economizers"][mode]
            reference = Choices(
                project_id="reference",
                name="Reference",
                fan="constant-speed",
                economizer=mode,
                economizer_control=source,
            )
            assert (
                branch["economizers"][mode]
                == convert_units(reference, unit).model_dump()["economizer_control"]
            )
        assert branch["variable_fan"]["setpoint_pa"] == 250


@pytest.mark.parametrize("proofs", [[True, False, True, False, True], [False] * 5])
def test_proof_startup_chatter_cannot_postpone_deadline_and_trip_stays_latched(proofs):
    engine = Engine(generate(choices()))
    rows = [step(engine, fan_proven=v) for v in proofs]
    assert not any(row["fan_ready"] for row in rows)
    assert rows[-1]["fan_fault"] and not rows[-1]["fan_enable"]
    assert all(r["heating_valve"] == r["cooling_valve"] == r["mixing_damper"] == 0 for r in rows)
    assert step(engine, fan_reset=True)["fan_fault"]
    assert step(engine, unit_enable=False, fan_reset=True)["fan_fault"]
    assert step(engine, unit_enable=False, fan_reset=False)["fan_fault"]
    reset = step(engine, unit_enable=False, fan_reset=True)
    assert not reset["fan_fault"] and not reset["fan_enable"]
    restart = step(engine, fan_reset=True)
    assert restart["fan_enable"] and not restart["fan_ready"]


def test_ready_at_exact_start_deadline_wins_before_trip():
    engine = Engine(generate(choices()))
    rows = [step(engine, fan_proven=False)] + [step(engine, fan_proven=True) for _ in range(4)]
    assert not any(r["fan_ready"] for r in rows[:4])
    assert rows[-1]["fan_ready"] and not rows[-1]["fan_fault"] and rows[-1]["cooling_valve"] > 0


def test_proof_loss_closes_coils_and_oa_now_then_chatter_uses_recovery_deadline():
    engine = Engine(generate(choices()))
    assert ready(engine)["cooling_valve"] > 0
    rows = [step(engine, fan_proven=v) for v in [False, True, False, True, False]]
    assert all(
        not r["fan_ready"] and r["cooling_valve"] == r["heating_valve"] == r["mixing_damper"] == 0
        for r in rows
    )
    assert all(r["fan_enable"] for r in rows[:4])
    assert rows[-1]["fan_fault"] and not rows[-1]["fan_enable"]


def test_ready_at_exact_recovery_deadline_wins():
    engine = Engine(generate(choices()))
    ready(engine)
    rows = [step(engine, fan_proven=False)] + [step(engine, fan_proven=True) for _ in range(4)]
    assert not any(r["fan_ready"] for r in rows[:4])
    assert rows[-1]["fan_ready"] and not rows[-1]["fan_fault"]


@pytest.mark.parametrize(
    "mode,warm,target,output,state",
    [
        ("cool", 58, 56, "cooling_valve", 4),
        ("heat", 52, 54, "heating_valve", 1),
        ("econ", 58, 56, "mixing_damper", 2),
    ],
)
def test_active_pi_at_setpoint_retains_nonzero_integral_and_state(
    mode, warm, target, output, state
):
    engine = Engine(
        generate(
            choices(economizer="fixed-drybulb" if mode == "econ" else "off", minimum_oa_percent=0)
        )
    )
    first = ready(engine, warm)
    assert first["ahu_state"] == state and first[output] == pytest.approx(9)
    held = [step(engine, target) for _ in range(3)]
    assert all(row["ahu_state"] == state and row[output] == pytest.approx(1) for row in held)
    loop = {"cool": "cooling_loop", "heat": "heating_loop", "econ": "economizer_loop"}[mode]
    assert engine.state[loop]["integral"] == pytest.approx(1)


def test_high_test_uses_selected_floor100_command_not_small_economizer_demand():
    engine = Engine(generate(choices(economizer="fixed-drybulb", minimum_oa_percent=100)))
    out = ready(engine, 57)
    assert out["ahu_state"] == 2 and out["mixing_damper"] == 100
    assert engine.values["economizer_loop"] < 99
    assert step(engine, 57)["ahu_state"] == 2
    integrated = step(engine, 57)
    assert (
        integrated["ahu_state"] == 3
        and integrated["mixing_damper"] == 100
        and integrated["cooling_valve"] > 0
    )
    held = step(engine, 56)
    assert held["ahu_state"] == 3 and held["cooling_valve"] > 0


def test_integrated_release_then_econ_low_release_ignores_nonzero_position_floor():
    engine = Engine(generate(choices(economizer="fixed-drybulb", minimum_oa_percent=10)))
    ready(engine, 90)
    assert step(engine, 90)["ahu_state"] == 2
    assert step(engine, 90)["ahu_state"] == 3
    rows = [step(engine, 55) for _ in range(5)]
    assert [r["ahu_state"] for r in rows] == [3, 3, 2, 2, 0]
    assert (
        rows[-1]["mixing_damper"] == 10
        and rows[-1]["cooling_valve"] == rows[-1]["heating_valve"] == 0
    )


def test_economizer_eligibility_loss_mechanical_then_suitable_integrated_handoff():
    engine = Engine(generate(choices(economizer="fixed-drybulb")))
    assert ready(engine, 58)["ahu_state"] == 2
    mechanical = step(engine, 58, outdoor_temperature=70)
    assert (
        mechanical["ahu_state"] == 4
        and mechanical["mixing_damper"] == 10
        and mechanical["cooling_valve"] > 0
    )
    integrated = step(engine, 58, outdoor_temperature=50)
    assert integrated["ahu_state"] == 3 and integrated["mixing_damper"] == 100
    heating = step(engine, 50)
    assert (
        heating["ahu_state"] == 1 and heating["cooling_valve"] == 0 and heating["heating_valve"] > 0
    )


@pytest.mark.parametrize(
    "change", [{"unit_enable": False}, {"occupied": False}, {"energy_holdoff": True}]
)
def test_good_permission_loss_zeroes_commands_and_holds_integral(change):
    engine = Engine(generate(choices(fan="variable-speed")))
    ready(engine)
    before = engine.state["cooling_loop"]["integral"]
    out = step(engine, **change)
    assert (
        not out["fan_enable"]
        and out["fan_speed"]
        == out["mixing_damper"]
        == out["heating_valve"]
        == out["cooling_valve"]
        == 0
    )
    assert engine.state["cooling_loop"]["integral"] == before


@pytest.mark.parametrize(
    "fan,economizer,sensor",
    [
        ("constant-speed", "off", "sat"),
        ("variable-speed", "off", "duct_pressure"),
        ("constant-speed", "fixed-drybulb", "outdoor_temperature"),
        ("constant-speed", "differential-drybulb", "return_temperature"),
    ],
)
def test_bad_required_quality_rolls_back_full_transaction_even_false_permission(
    fan, economizer, sensor
):
    engine = Engine(generate(choices(fan=fan, economizer=economizer)))
    ready(engine)
    before = engine.snapshot()
    history = len(engine.history)
    with pytest.raises(ScanError):
        step(engine, unit_enable=False, **{sensor: {"quality": "unreliable"}})
    assert engine.snapshot() == before and len(engine.history) == history


@pytest.mark.parametrize(
    "fan,economizer",
    list(
        itertools.product(
            ("constant-speed", "variable-speed"), ("off", "fixed-drybulb", "differential-drybulb")
        )
    ),
)
def test_coupled_temperature_delta_gain_conversion_keeps_pa_and_ordinary_output_traces(
    fan, economizer
):
    f = choices(fan=fan, economizer=economizer)
    c = convert_units(f, "degC")
    assert c.heating_kp == pytest.approx(f.heating_kp * 9 / 5) and c.release_delta == pytest.approx(
        f.release_delta * 5 / 9
    )
    assert c.variable_fan == f.variable_fan
    engines = [Engine(generate(f)), Engine(generate(c))]
    for sat in [58] * 8 + [56] * 3 + [50] * 5 + [54] * 2 + [80] * 5:
        frames = [step(engine, sat) for engine in engines]
        for name in frames[0]:
            assert frames[0][name] == pytest.approx(frames[1][name], abs=1e-8)


@pytest.mark.parametrize(
    "mutation",
    [
        {"fan": "constant-speed", "variable_fan": {}},
        {"fan": "variable-speed"},
        {"economizer": "off", "economizer_control": {}},
        {"economizer": "fixed-drybulb"},
        {"proof_seconds": True},
        {"scan_seconds": 1.0},
        {"startup_timeout_seconds": 4},
        {"temperature_band": 0.5},
        {"heating_kp": 0, "heating_ki": 0},
        {"occupied_default": 1},
    ],
)
def test_strict_incoherent_or_irrelevant_choices_refused(mutation):
    value = choices().model_dump()
    value.update(mutation)
    with pytest.raises(ValidationError):
        Choices.model_validate(value)


def test_fixed_drybulb_refuses_irrelevant_ra_and_differential_requires_ordered_values():
    base = choices(economizer="fixed-drybulb").model_dump()
    base["economizer_control"]["ra_default"] = 72
    with pytest.raises(ValidationError):
        Choices.model_validate(base)
    base = choices(economizer="differential-drybulb").model_dump()
    base["economizer_control"]["differential_off"] = 4
    with pytest.raises(ValidationError):
        Choices.model_validate(base)


def test_preview_is_real_valid_program_source_and_declared_target_is_not_native_acceptance():
    value = choices(
        fan="variable-speed",
        economizer="differential-drybulb",
        family="johnson-fx",
        model="FX-PCG2611-0",
        firmware="declared",
        release_mode="declared",
    )
    result = preview(PreviewRequest(choices=value))
    assert result["can_create"] and not result["native_compile"] and not result["controller_writes"]
    assert result["program_sha256"] == generate(value).digest()
    assert result["program"]["metadata"]["application"] == "mixed-air-single-duct-ahu"


@pytest.mark.parametrize(
    "path",
    ["heating_kp", "heating_ki", "cooling_kp", "cooling_ki", "economizer.kp", "economizer.ki"],
)
def test_accepted_maximum_fahrenheit_thermal_gains_convert_both_directions(path):
    data = choices(economizer="fixed-drybulb").model_dump()
    if path.startswith("economizer."):
        data["economizer_control"][path.split(".")[1]] = 1e6
    else:
        data[path] = 1e6
    original = Choices.model_validate(data)
    metric = convert_units(original, "degC")
    converted = (
        metric.economizer_control.model_dump()[path.split(".")[1]]
        if path.startswith("economizer.")
        else getattr(metric, path)
    )
    assert converted == pytest.approx(1.8e6)
    restored = convert_units(metric, "degF")
    returned = (
        restored.economizer_control.model_dump()[path.split(".")[1]]
        if path.startswith("economizer.")
        else getattr(restored, path)
    )
    assert returned == pytest.approx(1e6)
    invalid = original.model_dump()
    if path.startswith("economizer."):
        invalid["economizer_control"][path.split(".")[1]] = 1.1e6
    else:
        invalid[path] = 1.1e6
    with pytest.raises(ValidationError, match="Thermal gains"):
        Choices.model_validate(invalid)


@pytest.mark.parametrize(
    "format,extension", [("json", "json"), ("st", "st"), ("plcopen", "xml"), ("graphml", "graphml")]
)
def test_genuine_generated_graph_roundtrips_supported_source_formats(format, extension):
    from bms_tool.formats import export_program, import_program

    program = generate(choices(fan="variable-speed", economizer="differential-drybulb"))
    content, _, _ = export_program(program, format)
    assert import_program(content, "ahu." + extension) == program
