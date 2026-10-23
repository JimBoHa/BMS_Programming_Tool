"""Independent authored UV Cycle III lifecycle, control and engineering contracts."""

import copy
import itertools
import random

import pytest
from bms_tool.engine import Engine, ScanError, validate
from bms_tool.models import Program
from bms_tool.unit_ventilator_cycle3 import (
    PROFILE,
    PROFILE_SHA,
    Choices,
    PreviewRequest,
    catalog_document,
    choice_document,
    convert_units,
    digest,
    generate,
    preview,
)
from pydantic import ValidationError

COMPOSITIONS = list(itertools.product(("degF", "degC"), ("P", "PI"), (1, 3)))


def temperature(f, unit):
    return f if unit == "degF" else (f - 32) * 5 / 9


def choices(*, unit="degF", control="PI", scan=1, **changes):
    data = dict(
        project_id="authored-uv-cycle3",
        name="Authored UV Cycle III",
        condensate_policy="disable-cooling",
        occupied_default=True,
        unit_enable_default=True,
        airflow_proven_default=True,
        proof_seconds=2 * scan,
        startup_timeout_seconds=3 * scan,
        scan_seconds=scan,
    )
    if control == "P":
        data.update(heating_ki=0, cooling_ki=0, mixed_air_ki=0, zone_limit_ki=0)
    data.update(changes)
    return convert_units(Choices.model_validate(data), unit)


def step(engine, zone=72, mat=55, **inputs):
    unit = engine.program.metadata["unit_ventilator_cycle3_wizard"]["choices"]["temperature_unit"]
    return engine.step(
        {
            "zone_temperature": temperature(zone, unit),
            "mixed_air_temperature": temperature(mat, unit),
            **inputs,
        }
    )["outputs"]


def ready(engine, zone=72, mat=55):
    a, b = step(engine, zone, mat), step(engine, zone, mat)
    assert [a["unit_state"], b["unit_state"]] == [1, 2]
    return b


class FanOracle:
    """Small independent interval/fault machine, no generated node introspection."""

    def __init__(self, value):
        self.value = value
        self.fault = False
        self.ready = False
        self.reset = False
        self.proof = 0
        self.deadline = 0

    def step(self, *, request=True, admitted=True, proof=True, reset=False, shutdown=False):
        edge = not request and reset and not self.reset
        fan = request and admitted and not shutdown and not self.fault
        self.proof = self.proof + self.value.scan_seconds if fan and proof else 0
        self.deadline = self.deadline + self.value.scan_seconds if fan and not self.ready else 0
        candidate = fan and proof and self.proof >= self.value.proof_seconds
        trip = (fan and self.deadline >= self.value.startup_timeout_seconds and not candidate) or (
            request and self.ready and not proof
        )
        self.fault = (self.fault and not edge) or trip
        self.ready = candidate and not self.fault
        self.reset = reset
        fan = fan and not self.fault
        return dict(
            unit_state=3 if self.fault else 2 if self.ready else 1 if fan else 0,
            fan_enable=fan,
            fan_ready=self.ready,
            fan_fault=self.fault,
            reset_accepted=edge,
        )


@pytest.mark.parametrize("unit,control,scan", COMPOSITIONS)
def test_declared_compositions_are_real_graphs_with_exact_source_and_interfaces(
    unit, control, scan
):
    v = choices(unit=unit, control=control, scan=scan)
    p = generate(v)
    report = preview(PreviewRequest(choices=v))
    assert not [x for x in validate(p) if x.level == "error"]
    assert len(p.nodes) == len({n.id for n in p.nodes}) == 198
    assert len(report["inputs"]) == 13 and len(report["outputs"]) == 29
    assert {r["id"] for r in report["inputs"]} == {
        "occupied",
        "unit_enable",
        "energy_holdoff",
        "airflow_proven",
        "fan_reset",
        "condensate_alarm",
        "heating_available",
        "cooling_available",
        "zone_temperature",
        "mixed_air_temperature",
        "heating_setpoint",
        "cooling_setpoint",
        "mixed_air_setpoint",
    }
    assert {r["unit"] for r in report["inputs"] if r["value_type"] == "number"} == {unit}
    assert report["can_create"] and not report["native_compile"] and not report["controller_writes"]
    assert (
        p.metadata["application"] == "occupied-uv-cycle3"
        and not p.metadata["native_deployment_verified"]
    )
    assert (
        PROFILE_SHA
        == digest(PROFILE)
        == p.metadata["unit_ventilator_cycle3_wizard"]["profile_sha256"]
    )
    assert p.metadata["unit_ventilator_cycle3_wizard"]["choices"] == choice_document(v)
    out = ready(Engine(p), zone=80, mat=65)
    assert (
        out["cooling_valve"] > 0
        and out["heating_valve"] == 0
        and out["outdoor_damper"] > v.minimum_outdoor_position
    )


@pytest.mark.parametrize(
    "proofs", [[True, True, True], [False, True, True], [True, False, True], [False, False, False]]
)
def test_startup_clock_spans_chatter_and_exact_deadline_proof_wins(proofs):
    v = choices()
    e = Engine(generate(v))
    o = FanOracle(v)
    for proof in proofs:
        actual = step(e, airflow_proven=proof)
        expected = o.step(proof=proof)
        assert {k: actual[k] for k in expected} == expected
    assert actual["fan_ready"] is (proofs in [[True, True, True], [False, True, True]])
    if proofs == [False, True, True]:
        assert actual["startup_deadline_reached"] and not actual["fan_fault"]


def test_no_series_fan_close_delay_and_default_five_second_proof_are_elapsed_intervals():
    v = Choices(project_id="reference", name="Reference", condensate_policy="disable-cooling")
    e = Engine(generate(v))
    assert e.step()["outputs"]["unit_state"] == 0
    rows = [
        e.step({"occupied": True, "unit_enable": True, "airflow_proven": True})["outputs"]
        for _ in range(5)
    ]
    assert all(r["fan_enable"] for r in rows)
    assert [r["fan_ready"] for r in rows] == [False, False, False, False, True]
    assert catalog_document()["defaults"]["condensate_policy"] == ""


@pytest.mark.parametrize("policy", ["disable-cooling", "shutdown-unit"])
def test_random_good_quality_lifecycle_matches_interval_oracle_without_field_assumptions(policy):
    v = choices(condensate_policy=policy)
    e = Engine(generate(v))
    o = FanOracle(v)
    rng = random.Random(920)
    for i in range(120):
        request = rng.choice([True, True, False])
        proof = rng.choice([True, True, False])
        reset = rng.choice([True, False])
        admitted = rng.choice([True, True, False])
        alarm = rng.choice([True, False])
        inputs = {
            "unit_enable": request,
            "airflow_proven": proof,
            "fan_reset": reset,
            "condensate_alarm": alarm,
            "heating_setpoint": 70 if admitted else 90,
        }
        actual = step(e, **inputs)
        expected = o.step(
            request=request,
            admitted=admitted,
            proof=proof,
            reset=reset,
            shutdown=alarm and policy == "shutdown-unit",
        )
        assert {k: actual[k] for k in expected} == expected, (i, inputs)
        if not actual["fan_ready"]:
            assert (
                actual["heating_valve"] == actual["cooling_valve"] == actual["outdoor_damper"] == 0
            )


def test_running_proof_loss_latches_and_invalid_values_or_held_reset_cannot_impersonate_off():
    e = Engine(generate(choices()))
    ready(e, zone=80, mat=65)
    out = step(e, airflow_proven=False)
    assert out["fan_fault"] and not out["fan_enable"]
    assert out["heating_valve"] == out["cooling_valve"] == out["outdoor_damper"] == 0
    assert step(e, heating_setpoint=90, fan_reset=True)["fan_fault"]
    assert step(e, unit_enable=False, fan_reset=True)["fan_fault"]
    assert step(e, unit_enable=False, fan_reset=False)["fan_fault"]
    reset = step(e, unit_enable=False, fan_reset=True)
    assert reset["reset_accepted"] and not reset["fan_fault"]
    ready(e)


@pytest.mark.parametrize(
    "field,bad,flag",
    [
        ("zone_temperature", -100, "temperature_range_valid"),
        ("mixed_air_temperature", -100, "temperature_range_valid"),
        ("heating_setpoint", 90, "setpoints_valid"),
        ("mixed_air_setpoint", -100, "setpoints_valid"),
    ],
)
def test_good_invalid_input_inhibits_without_fault_and_restarts_proof(field, bad, flag):
    e = Engine(generate(choices()))
    ready(e, zone=80, mat=65)
    out = step(e, **{field: bad})
    assert (
        out["raw_run_request"]
        and not out[flag]
        and not out["fan_fault"]
        and not out["fan_ready"]
        and not out["fan_enable"]
    )
    assert out["heating_valve"] == out["cooling_valve"] == out["outdoor_damper"] == 0
    ready(e)


@pytest.mark.parametrize(
    "field",
    [
        "occupied",
        "unit_enable",
        "energy_holdoff",
        "airflow_proven",
        "fan_reset",
        "condensate_alarm",
        "heating_available",
        "cooling_available",
        "zone_temperature",
        "mixed_air_temperature",
        "heating_setpoint",
        "cooling_setpoint",
        "mixed_air_setpoint",
    ],
)
def test_every_required_bad_quality_rolls_back_complete_positive_scan_even_when_other_permission_off(
    field,
):
    e = Engine(generate(choices()))
    ready(e, zone=80, mat=65)
    before = copy.deepcopy(e.snapshot())
    with pytest.raises(ScanError):
        step(
            e, unit_enable=False, **{field: {"quality": "stale"}}
        ) if field != "unit_enable" else step(e, unit_enable={"quality": "stale"}, occupied=False)
    assert e.snapshot() == before


def test_first_bad_quality_scan_has_no_seeded_output_state_or_elapsed_time():
    e = Engine(generate(choices()))
    with pytest.raises(ScanError):
        step(e, mixed_air_temperature={"quality": "open-circuit"}, unit_enable=False)
    assert e.outputs == {} and e.state == {} and e.time == 0


@pytest.mark.parametrize("policy", ["disable-cooling", "shutdown-unit"])
def test_condensate_and_availability_are_separate_from_raw_request_and_fan(policy):
    e = Engine(generate(choices(control="P", condensate_policy=policy)))
    before = ready(e, zone=80, mat=65)
    assert before["cooling_valve"] > 0
    off = step(e, zone=80, mat=65, cooling_available=False)
    assert (
        off["cooling_requested"]
        and not off["cooling_active"]
        and off["cooling_valve"] == 0
        and off["fan_ready"]
        and off["outdoor_damper"] > 10
    )
    alarm = step(e, zone=80, mat=65, condensate_alarm=True)
    assert (
        alarm["condensate_inhibits_cooling"]
        and alarm["raw_run_request"]
        and alarm["cooling_valve"] == 0
    )
    if policy == "shutdown-unit":
        assert (
            alarm["condensate_shutdown"]
            and not alarm["fan_enable"]
            and alarm["outdoor_damper"] == alarm["heating_valve"] == 0
        )
    else:
        assert (
            not alarm["condensate_shutdown"] and alarm["fan_ready"] and alarm["outdoor_damper"] > 10
        )


@pytest.mark.parametrize("minimum", [0, 10, 100])
def test_minimum_oa_is_defined_including100_and_no_return_air_or_flow_output_is_invented(minimum):
    e = Engine(generate(choices(control="P", minimum_outdoor_position=minimum)))
    out = ready(e, zone=72, mat=55)
    assert out["outdoor_damper"] == out["mixed_air_damper_demand"] == minimum
    assert not any("return" in x or "flow" in x for x in out if x not in ("raw_run_request",))
    out = step(e, zone=72, mat=80)
    assert minimum <= out["outdoor_damper"] <= 100


def test_zone_heating_is_direct_and_limiter_uses_previous_selected_saturation_only():
    e = Engine(generate(choices(control="P")))
    out = ready(e, zone=40, mat=80)
    assert (
        out["heating_valve"] == 100
        and out["outdoor_damper"] == 100
        and not out["zone_limit_active"]
    )
    out = step(e, zone=40, mat=80)
    assert out["zone_limit_active"] and out["thermal_state"] == 3
    assert (
        out["zone_limit_correction"] == 100
        and out["zone_limit_allowed"] == 0
        and out["outdoor_damper"] == 10
        and out["zone_limit_restricting"]
    )
    assert out["heating_valve"] == 100
    out = step(e, zone=72, mat=80)
    assert (
        not out["zone_limit_active"] and out["outdoor_damper"] == 100 and out["heating_valve"] == 0
    )
    assert out["heating_requested"]  # One previous-selected-command release interval.
    out = step(e, zone=72, mat=80)
    assert not out["heating_requested"]


def test_unavailable_heat_can_select_zone_limit_but_mat_does_not_boost_heating():
    e = Engine(generate(choices(control="P")))
    out = ready(e, zone=65, mat=80)
    assert out["heating_valve"] == 20 and not out["zone_limit_active"]
    out = step(e, zone=65, mat=80, heating_available=False)
    assert (
        out["heating_requested"]
        and not out["heating_active"]
        and out["heating_valve"] == 0
        and out["zone_limit_active"]
    )
    assert (
        out["zone_limit_correction"] == 25
        and out["zone_limit_allowed"] == 75
        and out["outdoor_damper"] == 75
    )
    out = step(e, zone=65, mat=40)
    assert (
        out["heating_valve"] == 20 and not out["zone_limit_active"] and out["outdoor_damper"] == 10
    )


def test_independent_pi_trace_at_target_and_off_holds_committed_integrals_not_selected_commands():
    e = Engine(generate(choices(cooling_kp=4, cooling_ki=0.5, mixed_air_kp=5, mixed_air_ki=0.1)))
    out = ready(e, zone=76, mat=60)
    assert out["cooling_valve"] == 9 and out["outdoor_damper"] == pytest.approx(32.95)
    out = step(e, zone=74, mat=60)
    assert out["cooling_requested"] and out["cooling_valve"] == 1
    before = copy.deepcopy(e.state)
    out = step(e, zone=74, mat=60, unit_enable=False)
    assert out["cooling_valve"] == out["outdoor_damper"] == 0 and not out["cooling_requested"]
    assert (
        e.state["uv_cooling_loop"] == before["uv_cooling_loop"]
        and e.state["uv_mixed_air_loop"] == before["uv_mixed_air_loop"]
    )
    out = ready(e, zone=76, mat=60)
    assert out["cooling_valve"] == 10


def test_entry_inclusive_release_strict_and_modes_are_exclusive():
    e = Engine(generate(choices(control="P")))
    out = ready(e, zone=69)
    assert out["heating_requested"] and out["heating_valve"] == 4
    out = step(e, zone=70)
    assert out["heating_requested"] and out["heating_valve"] == 0
    out = step(e, zone=70)
    assert out["heating_requested"]  # strict beyond release, not equality
    out = step(e, zone=70.1)
    assert not out["heating_requested"] and out["thermal_state"] == 0
    out = step(e, zone=75)
    assert out["cooling_requested"] and not out["heating_requested"]
    out = step(e, zone=69)
    assert out["heating_requested"] and not out["cooling_requested"]


@pytest.mark.parametrize(
    "patch",
    [
        {"fan": "variable-speed"},
        {"coils": "DX"},
        {"mixing_action": "warm-outdoor"},
        {"condensate_policy": ""},
        {"condensate_policy": None},
        {"heating_setpoint": 74},
        {"entry_delta": 0},
        {"entry_delta": 1, "release_delta": 1},
        {"proof_seconds": 1.5},
        {"scan_seconds": 3},
        {"startup_timeout_seconds": 1},
        {"minimum_outdoor_position": 101},
        {"airflow_proven_default": 1},
        {"heating_kp": 1000001},
        {"unknown": True},
    ],
)
def test_strict_choices_refuse_unsupported_or_incoherent_values(patch):
    with pytest.raises(ValidationError):
        choices(**patch)


def test_coupled_units_preserve_identity_percent_flags_and_seconds_without_roundtrip_promise():
    original = choices(heating_ki=1e-6, minimum_outdoor_position=100)
    c = convert_units(original, "degC")
    assert (
        c.zone_default == (72 - 32) * 5 / 9
        and c.entry_delta == 5 / 9
        and c.heating_kp == 4 / (5 / 9)
    )
    assert (
        c.zone_limit_ki == 0.1 / (5 / 9)
        and c.minimum_outdoor_position == 100
        and c.proof_seconds == original.proof_seconds
    )
    assert (
        c.airflow_proven_default == original.airflow_proven_default
        and c.project_id == original.project_id
    )
    adjacent = choices(unit="degC").model_copy(
        update={"entry_delta": 1.5000000000000007, "release_delta": 1.5000000000000004}
    )
    Choices.model_validate(adjacent.model_dump())
    with pytest.raises(ValidationError):
        convert_units(adjacent, "degF")


def test_authored_negative_zero_and_scientific_params_survive_choices_graph_units_and_source():
    import math

    value = choices(heating_ki=-0.0, zone_limit_ki=-0.0, cooling_ki=1e-6)
    for original in (value, convert_units(value, "degC")):
        document = choice_document(original)
        program = generate(original)
        params = {node.id: node.params for node in program.nodes}
        assert math.copysign(1, document["heating_ki"]) < 0
        assert math.copysign(1, document["zone_limit_ki"]) < 0
        assert math.copysign(1, params["uv_heating_loop"]["ki"]) < 0
        assert math.copysign(1, params["uv_zone_limit_loop"]["ki"]) < 0
        assert math.copysign(1, params["uv_negative_release"]["value"]) < 0
        assert params["uv_cooling_loop"]["ki"] == original.cooling_ki
        raw = program.model_dump_json().encode()
        assert b"-0.0" in raw and Program.model_validate_json(raw).digest() == program.digest()
    assert choice_document(value)["minimum_outdoor_position"] == 10
