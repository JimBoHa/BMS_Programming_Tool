"""Independent series topology, discrete-clock, feedback and fault contracts."""

import copy
import itertools

import pytest
from bms_tool.engine import Engine, ScanError, validate
from bms_tool.equipment_wizard import CFM_TO_LPS
from bms_tool.series_fan_vav import (
    PROFILE,
    PROFILE_SHA,
    Choices,
    PreviewRequest,
    catalog_document,
    convert_units,
    digest,
    generate,
    preview,
)
from pydantic import ValidationError

COMPOSITIONS = list(itertools.product(("degF", "degC"), ("cfm", "L/s"), ("P", "PI"), (1, 3)))


def choices(*, unit="degF", flow="cfm", control="PI", scan=1, **changes):
    values = {
        "project_id": "authored-series-vav",
        "name": "Authored occupied series VAV",
        "occupied_default": True,
        "unit_enable_default": True,
        "fan_proven_default": True,
        "close_seconds": 2 * scan,
        "proof_seconds": 2 * scan,
        "startup_timeout_seconds": 3 * scan,
        "scan_seconds": scan,
        "heating_kp": 4,
        "cooling_kp": 4,
        "heating_ki": 0.5 if control == "PI" else 0,
        "cooling_ki": 0.5 if control == "PI" else 0,
        "flow_kp": 0.2,
        "flow_ki": 0.01 if control == "PI" else 0,
    }
    values.update(changes)
    return convert_units(Choices.model_validate(values), unit, flow)


def temperature(number, unit):
    return number if unit == "degF" else (number - 32) * 5 / 9


def airflow(number, unit):
    return number if unit == "cfm" else number * CFM_TO_LPS


def step(engine, zone=74, **inputs):
    options = engine.program.metadata["series_fan_vav_wizard"]["choices"]
    return engine.step(
        {"zone_temperature": temperature(zone, options["temperature_unit"]), **inputs}
    )["outputs"]


def ready(engine, zone=74):
    rows = [step(engine, zone) for _ in range(4)]
    assert [r["series_state"] for r in rows] == [1, 1, 2, 3]
    return rows[-1]


class StartupOracle:
    """Independent phase machine over elapsed requested intervals, not graph IDs."""

    def __init__(self, value):
        self.value = value
        self.close_elapsed = self.proof_elapsed = self.start_elapsed = 0
        self.closed_before = self.ready_before = self.fault = self.reset_before = False

    def step(self, *, request=True, admitted=True, proof=True, reset=False):
        value = self.value
        clear = not request and reset and not self.reset_before
        self.reset_before = reset
        previous_ready = self.ready_before
        if self.fault and clear:
            self.fault = False
        elif request and previous_ready and not proof:
            self.fault = True
        active = request and admitted and not self.fault
        fan_requested = active and self.closed_before
        self.close_elapsed = self.close_elapsed + value.scan_seconds if active else 0
        self.closed_before = active and self.close_elapsed >= value.close_seconds
        self.proof_elapsed = (
            self.proof_elapsed + value.scan_seconds if fan_requested and proof else 0
        )
        candidate = fan_requested and proof and self.proof_elapsed >= value.proof_seconds
        self.start_elapsed = (
            self.start_elapsed + value.scan_seconds if fan_requested and not previous_ready else 0
        )
        if fan_requested and not candidate and self.start_elapsed >= value.startup_timeout_seconds:
            self.fault = True
        fan = fan_requested and not self.fault
        self.ready_before = candidate and not self.fault
        state = 4 if self.fault else 3 if self.ready_before else 2 if fan else 1 if active else 0
        return {
            "series_state": state,
            "fan_enable": fan,
            "fan_ready": self.ready_before,
            "fan_fault": self.fault,
            "reset_accepted": clear,
        }


@pytest.mark.parametrize("unit,flow,control,scan", COMPOSITIONS)
def test_real_series_graph_has_primary_feedback_and_separate_hotwater_topology(
    unit, flow, control, scan
):
    value = choices(unit=unit, flow=flow, control=control, scan=scan)
    program = generate(value)
    assert not [issue for issue in validate(program) if issue.level == "error"]
    assert len(program.nodes) == len({node.id for node in program.nodes}) == 167
    assert {node.kind for node in program.nodes} <= {
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
        "PI",
        "Scale",
        "TemperatureDifference",
    }
    inputs = {node.id for node in program.nodes if node.kind == "Input"}
    assert inputs == {
        "occupied",
        "unit_enable",
        "energy_holdoff",
        "fan_proven",
        "fan_reset",
        "zone_temperature",
        "heating_setpoint",
        "cooling_setpoint",
        "primary_airflow",
    }
    report = preview(PreviewRequest(choices=value))
    assert report["can_create"] and len(report["outputs"]) == 24
    assert report["profile_sha256"] == digest(PROFILE) == PROFILE_SHA
    assert not report["native_compile"] and not report["controller_writes"]
    assert not program.metadata["native_deployment_verified"]
    assert {row["id"] for row in report["inputs"]} == inputs
    result = ready(Engine(program))
    assert result["fan_enable"] and result["cooling_active"]
    assert result["primary_flow_target"] > value.primary_flow_min
    assert result["primary_damper"] > 0 and result["reheat_valve"] == 0


def test_default_off_and_source_estimate90_then_proof15_are_real_elapsed_scan_counts():
    value = Choices(project_id="reference", name="Reference defaults")
    assert catalog_document()["defaults"]["close_seconds"] == 90
    assert value.proof_seconds == 15 and value.startup_timeout_seconds == 60
    engine = Engine(generate(value))
    off = engine.step()["outputs"]
    assert off["series_state"] == 0 and off["primary_damper"] == off["reheat_valve"] == 0
    rows = [
        engine.step({"occupied": True, "unit_enable": True, "fan_proven": True})["outputs"]
        for _ in range(105)
    ]
    assert not any(r["fan_enable"] for r in rows[:90])
    assert rows[89]["close_complete"] and rows[90]["fan_enable"]
    assert not any(r["fan_proof_stable"] for r in rows[:104])
    assert rows[104]["fan_ready"] and not rows[104]["fan_fault"]


@pytest.mark.parametrize(
    "proofs", [[False, False, False], [True, False, True], [False, True, True]]
)
def test_independent_startup_deadline_spans_chatter_and_exact_deadline_proof_wins(proofs):
    value = choices()
    engine, oracle = Engine(generate(value)), StartupOracle(value)
    for proof in [True, True, *proofs]:
        actual = step(engine, fan_proven=proof)
        expected = oracle.step(proof=proof)
        assert {key: actual[key] for key in expected} == expected
    assert actual["fan_ready"] is (proofs == [False, True, True])
    assert actual["fan_fault"] is not actual["fan_ready"]
    assert actual["startup_deadline_reached"]


def test_no_proof_can_accumulate_during_close_and_equal_proof_deadline_is_allowed():
    engine = Engine(generate(choices(proof_seconds=3, startup_timeout_seconds=3)))
    rows = [step(engine) for _ in range(5)]
    assert not any(r["fan_proof_stable"] for r in rows[:4])
    assert rows[4]["fan_ready"] and not rows[4]["fan_fault"]
    assert rows[4]["startup_deadline_reached"]


def test_running_proof_loss_immediately_latches_all_commands_and_only_raw_off_fresh_edge_resets():
    engine = Engine(generate(choices()))
    before = ready(engine, zone=60)
    assert before["reheat_valve"] > 0
    lost = step(engine, fan_proven=False)
    assert lost["fan_fault"] and lost["series_state"] == 4
    assert not lost["fan_enable"] and lost["primary_damper"] == lost["reheat_valve"] == 0
    assert step(engine)["fan_fault"]
    # Bad engineering values are not raw operator off, even with a reset edge.
    assert step(engine, heating_setpoint=90, cooling_setpoint=80, fan_reset=True)["fan_fault"]
    assert step(engine, unit_enable=False, fan_reset=True)["fan_fault"]
    assert step(engine, unit_enable=False, fan_reset=False)["fan_fault"]
    cleared = step(engine, unit_enable=False, fan_reset=True)
    assert not cleared["fan_fault"] and cleared["reset_accepted"] and not cleared["fan_enable"]
    assert [step(engine)["series_state"] for _ in range(4)] == [1, 1, 2, 3]


@pytest.mark.parametrize("phase_scans", [1, 3, 4])
@pytest.mark.parametrize(
    "invalid",
    [
        {"heating_setpoint": 80, "cooling_setpoint": 70},
        {"heating_setpoint": -100},
        {"cooling_setpoint": 250},
        {"primary_airflow": -1},
        {"primary_airflow": 3000000},
        {"zone_temperature": -100},
    ],
)
def test_good_invalid_values_inhibit_and_restart_startup_without_becoming_off_or_new_fault(
    phase_scans, invalid
):
    engine = Engine(generate(choices()))
    for _ in range(phase_scans):
        step(engine)
    inhibited = step(engine, **invalid)
    assert inhibited["raw_run_request"] and not inhibited["control_permitted"]
    assert not inhibited["fan_enable"] and not inhibited["fan_ready"] and not inhibited["fan_fault"]
    assert inhibited["primary_damper"] == inhibited["reheat_valve"] == 0
    assert [step(engine)["series_state"] for _ in range(4)] == [1, 1, 2, 3]


@pytest.mark.parametrize(
    "field,value", [("occupied", False), ("unit_enable", False), ("energy_holdoff", True)]
)
def test_each_raw_permission_loss_immediately_stops_and_restarts_full_close(field, value):
    engine = Engine(generate(choices()))
    ready(engine)
    off = step(engine, **{field: value})
    assert not off["raw_run_request"] and not off["fan_enable"] and not off["fan_ready"]
    assert off["primary_damper"] == off["reheat_valve"] == 0 and not off["fan_fault"]
    assert [step(engine)["series_state"] for _ in range(4)] == [1, 1, 2, 3]


@pytest.mark.parametrize("phase_scans", [0, 1, 3, 4])
def test_every_required_bad_quality_rolls_back_complete_scan_even_false_permission(phase_scans):
    engine = Engine(generate(choices()))
    for _ in range(phase_scans):
        step(engine, zone=60)
    before = copy.deepcopy(
        (engine.state, engine.values, engine.outputs, engine.time, engine.history)
    )
    for node in (node for node in engine.program.nodes if node.kind == "Input"):
        with pytest.raises(ScanError, match="unreliable"):
            engine.step({"unit_enable": False, node.id: {"quality": "unreliable"}})
        assert (engine.state, engine.values, engine.outputs, engine.time, engine.history) == before
    if phase_scans == 0:
        assert engine.outputs == engine.state == {} and engine.time == 0
    if phase_scans == 4:
        assert engine.outputs["reheat_valve"] > 0 and engine.outputs["fan_enable"]


def test_primary_feedback_p_controls_and_zero_primary_hotwater_are_not_total_coil_flow_proof():
    engine = Engine(generate(choices(control="P")))
    cooling = ready(engine)
    assert cooling["zone_cooling_demand"] == 8
    assert cooling["primary_flow_target"] == 156
    assert cooling["primary_damper"] == pytest.approx(31.2)
    over_target = step(engine, primary_airflow=200)
    assert over_target["primary_damper"] == 0 and over_target["fan_ready"]
    heating = step(engine, zone=60, primary_airflow=0)
    assert heating["heating_active"] and not heating["cooling_active"]
    assert heating["reheat_valve"] == 32 and heating["primary_flow_target"] == 100
    assert heating["primary_damper"] == 20
    assert "no primary threshold" in PROFILE["semantics"]["coil"]


def test_active_integral_at_setpoint_is_held_and_disabled_loop_integrals_are_not_reset():
    value = choices(cooling_kp=0, cooling_ki=1, heating_kp=0, heating_ki=1)
    engine = Engine(generate(value))
    current = ready(engine)
    assert current["zone_cooling_demand"] == 2
    held = step(engine, zone=72)
    assert held["cooling_active"] and held["zone_cooling_demand"] == 2
    before = {
        key: copy.deepcopy(engine.state[key])
        for key in ("zone_cooling_loop", "zone_heating_loop", "primary_flow_loop")
    }
    disabled = step(engine, unit_enable=False)
    assert disabled["primary_damper"] == disabled["reheat_valve"] == 0
    assert {key: engine.state[key] for key in before} == before
    ready(engine)
    cooling_integral = engine.state["zone_cooling_loop"]["integral"]
    heat = step(engine, zone=60)
    assert (
        heat["heating_active"] and not heat["cooling_active"] and heat["zone_cooling_demand"] == 0
    )
    assert engine.state["zone_cooling_loop"]["integral"] == cooling_integral


@pytest.mark.parametrize("unit,flow", list(itertools.product(("degF", "degC"), ("cfm", "L/s"))))
def test_coupled_units_preserve_identity_flags_seconds_and_convert_all_abs_delta_inverse_gains(
    unit, flow
):
    source = choices(heating_kp=1000000, flow_kp=1000000)
    converted = convert_units(source, unit, flow)
    ratio = 5 / 9 if unit == "degC" else 1
    flow_ratio = CFM_TO_LPS if flow == "L/s" else 1
    for key in ("zone_default", "heating_setpoint", "cooling_setpoint"):
        assert getattr(converted, key) == temperature(getattr(source, key), unit)
    for key in ("entry_delta", "release_delta"):
        assert getattr(converted, key) == getattr(source, key) * ratio
    for key in ("heating_kp", "heating_ki", "cooling_kp", "cooling_ki"):
        assert getattr(converted, key) == getattr(source, key) / ratio
    for key in ("primary_flow_min", "primary_flow_max", "primary_flow_default"):
        assert getattr(converted, key) == getattr(source, key) * flow_ratio
    for key in ("flow_kp", "flow_ki"):
        assert getattr(converted, key) == getattr(source, key) / flow_ratio
    for key in (
        "project_id",
        "name",
        "occupied_default",
        "fan_proven_default",
        "close_seconds",
        "proof_seconds",
        "startup_timeout_seconds",
        "scan_seconds",
    ):
        assert getattr(converted, key) == getattr(source, key)
    restored = convert_units(converted, "degF", "cfm")
    assert restored.heating_setpoint == pytest.approx(source.heating_setpoint)
    assert restored.flow_kp == pytest.approx(source.flow_kp)


@pytest.mark.parametrize(
    "patch",
    [
        {"fan": "parallel"},
        {"heating": "electric"},
        {"operation": "unoccupied"},
        {"flow_feedback": "position"},
        {"heat_flow_threshold": 10},
        {"occupied_default": 1},
        {"scan_seconds": True},
        {"close_seconds": 2.0},
        {"proof_seconds": 4},
        {"entry_delta": 0},
        {"release_delta": 2},
        {"primary_flow_min": 800},
        {"primary_flow_default": -1},
        {"flow_kp": 2000000},
        {"heating_kp": 1000001},
        {"cooling_setpoint": 60},
        {"zone_default": 400},
        {"name": "bad\nname"},
    ],
)
def test_strict_choices_refuse_irrelevant_paths_ranges_timings_and_native_assumptions(patch):
    with pytest.raises(ValidationError):
        choices(**patch)
