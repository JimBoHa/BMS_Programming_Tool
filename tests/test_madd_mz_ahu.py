"""Independent two-deck AHU state, proof, quality and units contracts."""

import itertools

import pytest
from bms_tool.engine import Engine, ScanError, validate
from bms_tool.madd_mz_ahu import (
    PROFILE_SHA,
    Choices,
    Economizer,
    PreviewRequest,
    catalog_document,
    convert_units,
    generate,
    preview,
)
from pydantic import ValidationError

COMPOSITIONS = list(
    itertools.product(
        ("off", "fixed-drybulb", "differential-drybulb"), ("P", "PI"), ("degF", "degC"), (1, 2)
    )
)


def choices(*, economizer="off", control="PI", unit="degF", scan=1, **changes):
    options = Economizer(kp=4, ki=0.5 if control == "PI" else 0, assist_seconds=2 * scan)
    if economizer == "differential-drybulb":
        options = options.model_copy(
            update={"ra_default": 72, "differential_on": 3, "differential_off": 1}
        )
    value = {
        "project_id": "authored-decks",
        "name": "Authored independent hot/cold deck AHU",
        "economizer": economizer,
        "economizer_control": options.model_dump() if economizer != "off" else None,
        "proof_seconds": 2 * scan,
        "stabilize_seconds": 2 * scan,
        "startup_timeout_seconds": 5 * scan,
        "recovery_timeout_seconds": 5 * scan,
        "release_seconds": 2 * scan,
        "scan_seconds": scan,
        "hot_kp": 4,
        "hot_ki": 0.5 if control == "PI" else 0,
        "cold_kp": 4,
        "cold_ki": 0.5 if control == "PI" else 0,
        "occupied_default": True,
        "unit_enable_default": True,
        "fan_proven_default": True,
    }
    value.update(changes)
    return convert_units(Choices.model_validate(value), unit)


def temperature(value, unit):
    return value if unit == "degF" else (value - 32) * 5 / 9


def step(engine, hot=83, cold=57, **inputs):
    unit = engine.program.metadata["madd_mz_ahu_wizard"]["choices"]["temperature_unit"]
    return engine.step(
        {
            "hot_deck_temperature": temperature(hot, unit),
            "cold_deck_temperature": temperature(cold, unit),
            **inputs,
        }
    )["outputs"]


def ready(engine, hot=83, cold=57):
    rows = [step(engine, hot, cold) for _ in range(4)]
    assert [r["fan_ready"] for r in rows] == [False, False, False, True]
    return rows[-1]


@pytest.mark.parametrize("economizer,control,unit,scan", COMPOSITIONS)
def test_genuine_two_deck_core_graph_and_concurrent_controls(economizer, control, unit, scan):
    value = choices(economizer=economizer, control=control, unit=unit, scan=scan)
    program = generate(value)
    assert not [d for d in validate(program) if d.level == "error"]
    assert len(program.nodes) == len({n.id for n in program.nodes}) < 320
    assert not any(n.kind == "Macro" for n in program.nodes)
    ports = {n.id for n in program.nodes if n.kind == "Input"}
    expected = {
        "occupied",
        "unit_enable",
        "energy_holdoff",
        "fan_proven",
        "fan_reset",
        "hot_deck_temperature",
        "cold_deck_temperature",
        "hot_deck_setpoint",
        "cold_deck_setpoint",
    }
    if economizer != "off":
        expected |= {"outdoor_temperature", "economizer_enable"}
    if economizer == "differential-drybulb":
        expected.add("return_temperature")
    assert ports == expected
    engine = Engine(program)
    out = ready(engine)
    assert out["fan_enable"] and out["setpoints_valid"] and not out["fan_fault"]
    assert out["hot_heating_active"] and out["hot_heating_valve"] > 0
    assert out["cold_deck_state"] == (3 if economizer == "off" else 1)
    if economizer == "off":
        assert out["cold_mechanical_active"] and out["cold_cooling_valve"] > 0
    else:
        assert out["cold_economizer_active"] and out["mixing_damper"] > 0
        assert out["cold_cooling_valve"] == 0
    assert out["nominal_deck_spread"] == pytest.approx(30 if unit == "degF" else 30 * 5 / 9)
    assert out["measured_deck_spread"] == pytest.approx(26 if unit == "degF" else 26 * 5 / 9)
    meta = program.metadata["madd_mz_ahu_wizard"]
    assert meta["profile_sha256"] == PROFILE_SHA
    assert meta["inputs"] == [
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


@pytest.mark.parametrize("unit", ["degF", "degC"])
def test_both_decks_hold_required_nonzero_pi_at_independent_setpoints(unit):
    engine = Engine(generate(choices(unit=unit)))
    out = ready(engine)
    assert out["hot_heating_valve"] == out["cold_cooling_valve"] == pytest.approx(9)
    for _ in range(3):
        out = step(engine, hot=85, cold=55)
        assert out["hot_heating_valve"] == out["cold_cooling_valve"] == pytest.approx(1)
        assert out["hot_heating_active"] and out["cold_deck_state"] == 3
    assert (
        engine.state["hot_loop"]["integral"]
        == engine.state["cold_loop"]["integral"]
        == pytest.approx(1)
    )


def test_hot_stays_active_through_economizer_mechanical_integrated_and_cold_idle():
    engine = Engine(generate(choices(economizer="fixed-drybulb", minimum_oa_percent=0)))
    assert ready(engine)["cold_deck_state"] == 1
    mech = step(engine, hot=85, cold=57, outdoor_temperature=70)
    assert (
        mech["cold_deck_state"] == 3
        and mech["hot_heating_valve"] == pytest.approx(1)
        and mech["cold_cooling_valve"] > 0
    )
    integrated = step(engine, hot=85, cold=57, outdoor_temperature=50)
    assert (
        integrated["cold_deck_state"] == 2
        and integrated["mixing_damper"] == 100
        and integrated["hot_heating_valve"] == pytest.approx(1)
    )
    rows = [step(engine, hot=85, cold=54) for _ in range(5)]
    assert [r["cold_deck_state"] for r in rows] == [2, 2, 1, 1, 0]
    assert all(r["hot_heating_active"] and r["hot_heating_valve"] == pytest.approx(1) for r in rows)
    assert rows[-1]["cold_cooling_valve"] == 0


def test_hot_deck_release_does_not_release_cold_and_cold_undershoot_does_not_request_hot_preheat():
    engine = Engine(generate(choices()))
    ready(engine)
    rows = [step(engine, hot=86) for _ in range(3)]
    assert [r["hot_heating_active"] for r in rows] == [True, True, False]
    assert all(r["cold_deck_state"] == 3 and r["cold_cooling_valve"] > 0 for r in rows)
    assert rows[-1]["hot_heating_valve"] == 0
    # A cold-deck undershoot cannot select the hot loop while its own deck is warm.
    rows = [step(engine, hot=86, cold=40) for _ in range(3)]
    assert all(not r["hot_heating_active"] and r["hot_heating_valve"] == 0 for r in rows)
    assert rows[-1]["cold_deck_state"] == 0


@pytest.mark.parametrize("unit", ["degF", "degC"])
def test_floor100_drives_assist_even_when_econ_demand_small_and_low_release_ignores_floor(unit):
    engine = Engine(
        generate(choices(economizer="fixed-drybulb", unit=unit, minimum_oa_percent=100))
    )
    out = ready(engine, hot=85, cold=56)
    assert out["cold_deck_state"] == 1 and out["mixing_damper"] == 100
    assert engine.values["economizer_loop"] < 99
    assert step(engine, hot=85, cold=56)["cold_deck_state"] == 1
    out = step(engine, hot=85, cold=56)
    assert out["cold_deck_state"] == 2 and out["cold_cooling_valve"] > 0
    rows = [step(engine, hot=85, cold=54) for _ in range(5)]
    assert [r["cold_deck_state"] for r in rows] == [2, 2, 1, 1, 0]
    assert rows[-1]["mixing_damper"] == 100


@pytest.mark.parametrize("proofs", [[True, False, True, False, True], [False] * 5])
def test_startup_proof_chatter_does_not_postpone_deadline_and_reset_needs_off_edge(proofs):
    engine = Engine(generate(choices()))
    rows = [step(engine, fan_proven=v) for v in proofs]
    assert not any(r["fan_ready"] for r in rows)
    assert rows[-1]["fan_fault"] and not rows[-1]["fan_enable"]
    assert step(engine, fan_reset=True)["fan_fault"]
    assert step(engine, unit_enable=False, fan_reset=True)["fan_fault"]
    step(engine, unit_enable=False, fan_reset=False)
    reset = step(engine, unit_enable=False, fan_reset=True)
    assert not reset["fan_fault"] and not reset["fan_enable"]
    assert not step(engine)["fan_ready"]


@pytest.mark.parametrize("recover", [False, True])
def test_ready_on_exact_startup_or_recovery_deadline_wins(recover):
    engine = Engine(generate(choices()))
    if recover:
        ready(engine)
    rows = [step(engine, fan_proven=False)] + [step(engine) for _ in range(4)]
    assert not any(r["fan_ready"] for r in rows[:4])
    assert rows[-1]["fan_ready"] and not rows[-1]["fan_fault"]
    assert rows[-1]["hot_heating_valve"] > 0 and rows[-1]["cold_cooling_valve"] > 0


def test_good_proof_loss_closes_both_coils_and_oa_now_then_recovery_chatter_trips():
    engine = Engine(generate(choices()))
    ready(engine)
    rows = [step(engine, fan_proven=v) for v in [False, True, False, True, False]]
    assert all(
        not r["fan_ready"]
        and r["hot_heating_valve"] == r["cold_cooling_valve"] == r["mixing_damper"] == 0
        for r in rows
    )
    assert all(r["fan_enable"] for r in rows[:4])
    assert rows[-1]["fan_fault"] and not rows[-1]["fan_enable"]


@pytest.mark.parametrize("unit", ["degF", "degC"])
@pytest.mark.parametrize(
    "sensor,invalid",
    [
        ("hot_deck_setpoint", -149),
        ("hot_deck_setpoint", 393),
        ("cold_deck_setpoint", -149),
        ("cold_deck_setpoint", 393),
    ],
)
def test_good_out_of_profile_runtime_setpoint_inhibits_commands_resets_readiness_and_holds_integrals(
    unit, sensor, invalid
):
    engine = Engine(generate(choices(unit=unit)))
    ready(engine)
    integrals = {k: engine.state[k]["integral"] for k in ("hot_loop", "cold_loop")}
    out = step(engine, **{sensor: temperature(invalid, unit)})
    assert (
        not out["setpoints_valid"]
        and not out["control_permitted"]
        and not out["fan_enable"]
        and not out["fan_ready"]
        and not out["fan_fault"]
    )
    assert not out["hot_heating_active"] and out["cold_deck_state"] == 0
    assert out["hot_heating_valve"] == out["cold_cooling_valve"] == out["mixing_damper"] == 0
    assert {k: engine.state[k]["integral"] for k in integrals} == integrals
    assert ready(engine)["setpoints_valid"]


def test_invalid_setpoint_does_not_enable_reset_while_raw_operator_request_remains_on():
    engine = Engine(generate(choices()))
    for _ in range(5):
        out = step(engine, fan_proven=False)
    assert out["fan_fault"]
    inhibited = step(engine, hot_deck_setpoint=500, fan_reset=True)
    assert inhibited["fan_fault"] and not inhibited["setpoints_valid"]
    step(engine, hot_deck_setpoint=500, fan_reset=False)
    still_latched = step(engine, hot_deck_setpoint=500, fan_reset=True)
    assert still_latched["fan_fault"]
    step(engine, unit_enable=False, fan_reset=False)
    assert not step(engine, unit_enable=False, fan_reset=True)["fan_fault"]


@pytest.mark.parametrize(
    "hot_sp,cold_sp,hot,cold,ordered",
    [(55, 85, 53, 87, False), (70, 70, 68, 72, False), (85, 55, 53, 87, True)],
)
def test_equal_reversed_targets_and_measured_decks_are_diagnostics_not_interlocks(
    hot_sp, cold_sp, hot, cold, ordered
):
    engine = Engine(generate(choices(hot_deck_setpoint=hot_sp, cold_deck_setpoint=cold_sp)))
    out = ready(engine, hot, cold)
    assert out["setpoints_valid"] and out["fan_ready"]
    assert out["hot_target_above_cold"] is ordered
    assert out["nominal_deck_spread"] == hot_sp - cold_sp
    assert out["measured_deck_spread"] == hot - cold
    assert out["hot_heating_valve"] > 0 and out["cold_cooling_valve"] > 0


@pytest.mark.parametrize(
    "sensor,economizer",
    [
        ("hot_deck_temperature", "off"),
        ("cold_deck_temperature", "off"),
        ("hot_deck_setpoint", "off"),
        ("cold_deck_setpoint", "off"),
        ("outdoor_temperature", "fixed-drybulb"),
        ("return_temperature", "differential-drybulb"),
    ],
)
def test_bad_required_quality_rolls_back_both_decks_fan_and_timers_even_with_permission_false(
    sensor, economizer
):
    engine = Engine(generate(choices(economizer=economizer)))
    ready(engine)
    before, history = engine.snapshot(), len(engine.history)
    with pytest.raises(ScanError):
        step(engine, unit_enable=False, **{sensor: {"quality": "unreliable"}})
    assert engine.snapshot() == before and len(engine.history) == history


@pytest.mark.parametrize(
    "change", [{"unit_enable": False}, {"occupied": False}, {"energy_holdoff": True}]
)
def test_good_operator_permission_loss_zeroes_commands_and_holds_both_integrals(change):
    engine = Engine(generate(choices()))
    ready(engine)
    integrals = {k: engine.state[k]["integral"] for k in ("hot_loop", "cold_loop")}
    out = step(engine, **change)
    assert (
        not out["fan_enable"]
        and out["hot_heating_valve"] == out["cold_cooling_valve"] == out["mixing_damper"] == 0
    )
    assert {k: engine.state[k]["integral"] for k in integrals} == integrals


@pytest.mark.parametrize("economizer", ["off", "fixed-drybulb", "differential-drybulb"])
def test_coupled_deck_econ_units_preserve_command_state_trace(economizer):
    f = choices(economizer=economizer)
    c = convert_units(f, "degC")
    engines = [Engine(generate(f)), Engine(generate(c))]
    assert c.hot_deck_setpoint == pytest.approx((85 - 32) * 5 / 9)
    assert c.cold_entry_delta == pytest.approx(f.cold_entry_delta * 5 / 9)
    assert c.hot_kp == pytest.approx(f.hot_kp * 9 / 5)
    # These off-boundary values test coupled conversion. Exact antiwindup
    # cancellation below has its own explicit divergence regression.
    for hot, cold in [(83, 57)] * 8 + [(85, 55)] * 3 + [(90, 50)] * 5 + [(75, 90)] * 5:
        rows = [step(e, hot, cold) for e in engines]
        for key in rows[0]:
            if key.endswith("spread"):
                assert rows[1][key] == pytest.approx(rows[0][key] * 5 / 9)
            else:
                assert rows[0][key] == pytest.approx(rows[1][key], abs=1e-8)


def test_existing_finite_precision_pi_antiwindup_boundary_diverges_between_coupled_units():
    """Known limitation, predicted from parameter arithmetic rather than outputs."""
    f = choices()
    c = convert_units(f, "degC")
    engines = [Engine(generate(f)), Engine(generate(c))]
    for hot, cold in [(83, 57)] * 8 + [(85, 55)] * 3:
        for engine in engines:
            step(engine, hot, cold)

    # Five admitted2F heating-error scans leave5% integral. The two subsequent
    # -1F correction scans mathematically reach the zero-output boundary.
    # Celsius subtraction rounds slightly below that boundary on scan2.
    expected = []
    for value in (f, c):
        warm_error = value.hot_deck_setpoint - temperature(83, value.temperature_unit)
        integral = 0.0
        for _ in range(5):
            integral += value.hot_ki * warm_error
        release_error = value.hot_deck_setpoint - temperature(86, value.temperature_unit)
        corrections = []
        for _ in range(2):
            candidate = integral + value.hot_ki * release_error
            raw = value.hot_kp * release_error + candidate
            accepted = raw >= 0  # Both values are far below the100% upper limit.
            if accepted:
                integral = candidate
            command = max(0, value.hot_kp * release_error + integral)
            corrections.append((raw, accepted, integral, command))
        expected.append(corrections)
    assert expected[0][-1][0] == 0 and expected[0][-1][1]
    assert expected[1][-1][0] < 0 and not expected[1][-1][1]
    for scan in range(2):
        for index, engine in enumerate(engines):
            out = step(engine, hot=86, cold=54)
            assert out["hot_heating_active"] and out["cold_deck_state"] == 3
            assert out["hot_heating_valve"] == pytest.approx(expected[index][scan][3])
            assert engine.state["hot_loop"]["integral"] == expected[index][scan][2]
    assert engines[0].values["hot_heating_valve"] == 0
    assert engines[1].values["hot_heating_valve"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    "path", ["hot_kp", "hot_ki", "cold_kp", "cold_ki", "economizer.kp", "economizer.ki"]
)
def test_gain_boundary_converts_both_directions_and_rejects_canonical_overflow(path):
    data = choices(economizer="fixed-drybulb").model_dump()
    target = data["economizer_control"] if path.startswith("economizer.") else data
    key = path.split(".")[-1]
    target[key] = 1e6
    f = Choices.model_validate(data)
    c = convert_units(f, "degC")
    converted = (
        c.economizer_control.model_dump()[key]
        if path.startswith("economizer.")
        else getattr(c, key)
    )
    assert converted == pytest.approx(1.8e6)
    restored = convert_units(c, "degF")
    assert (
        restored.economizer_control.model_dump()[key]
        if path.startswith("economizer.")
        else getattr(restored, key)
    ) == pytest.approx(1e6)
    target[key] = 1.1e6
    with pytest.raises(ValidationError, match="Thermal gains"):
        Choices.model_validate(data)


@pytest.mark.parametrize(
    "mutation",
    [
        {"configuration": "zones-only"},
        {"fan": "variable-speed"},
        {"zone_requests": []},
        {"economizer_control": {}},
        {"economizer": "fixed-drybulb"},
        {"hot_kp": 0, "hot_ki": 0},
        {"cold_kp": 0, "cold_ki": 0},
        {"hot_entry_delta": 0.1},
        {"proof_seconds": True},
        {"occupied_default": 1},
        {"scan_seconds": 1.0},
        {"startup_timeout_seconds": 4},
    ],
)
def test_incoherent_or_irrelevant_choices_refused(mutation):
    data = choices().model_dump() | mutation
    with pytest.raises(ValidationError):
        Choices.model_validate(data)


def test_catalog_defaults_are_off_branches_source_bound_and_preview_is_not_native():
    catalog = catalog_document()
    assert catalog["defaults"]["economizer"] == ""
    assert (
        catalog["defaults"]["fan"] == "single-speed"
        and catalog["defaults"]["configuration"] == "ahu-only"
    )
    base = Choices(project_id="off", name="Off", economizer="off")
    out = Engine(generate(base)).step()["outputs"]
    assert (
        not out["fan_enable"]
        and out["hot_heating_valve"] == out["cold_cooling_valve"] == out["mixing_damper"] == 0
    )
    for unit in ("degF", "degC"):
        assert set(catalog["branch_defaults"][unit]) == {"economizers"}
        for mode in ("fixed-drybulb", "differential-drybulb"):
            controls = catalog["branch_defaults"]["degF"]["economizers"][mode]
            original = Choices(
                project_id="source", name="Source", economizer=mode, economizer_control=controls
            )
            assert (
                catalog["branch_defaults"][unit]["economizers"][mode]
                == convert_units(original, unit).model_dump()["economizer_control"]
            )
    result = preview(
        PreviewRequest(
            choices=choices(
                family="johnson-fx", model="declared", firmware="declared", release_mode="declared"
            )
        )
    )
    assert result["can_create"] and not result["native_compile"] and not result["controller_writes"]
    assert result["program"]["metadata"]["application"] == "madd-mz-ahu-only"


@pytest.mark.parametrize(
    "format,extension", [("json", "json"), ("st", "st"), ("plcopen", "xml"), ("graphml", "graphml")]
)
def test_supported_source_formats_roundtrip_genuine_graph(format, extension):
    from bms_tool.formats import export_program, import_program

    program = generate(choices(economizer="differential-drybulb"))
    raw, _, _ = export_program(program, format)
    assert import_program(raw, "decks." + extension) == program
