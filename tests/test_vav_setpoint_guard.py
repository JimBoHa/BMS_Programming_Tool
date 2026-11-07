"""Independent declared VAV policy trajectories, extreme inputs and legacy byte hashes."""

import hashlib
import json
from pathlib import Path

import pytest
from bms_tool.engine import Engine, ScanError, validate
from bms_tool.equipment_wizard import (
    Choices,
    choice_document,
    convert_units,
    digest,
    generate,
    preview,
)
from bms_tool.formats import export_program, import_program

GOLDEN = json.loads((Path(__file__).parent / "fixtures/vav_guard_legacy_hashes.json").read_text())


def guarded(**changes):
    return Choices(
        **(
            {
                "project_id": "vav-guard-test",
                "name": "Authored VAV guard",
                "equipment": "parallel-fan-reheat",
                "cooling_setpoint": 73,
                "heating_setpoint": 68,
                "setpoints": "inputs",
                "temperature_loop": "P",
                "temperature_ki": 0,
                "flow_loop": "P",
                "flow_ki": 0,
                "setpoint_guard": {"minimum": 50, "maximum": 90, "minimum_deadband": 5},
            }
            | changes
        )
    )


@pytest.mark.parametrize("row", GOLDEN["cases"], ids=[str(i) for i in range(len(GOLDEN["cases"]))])
def test_absent_guard_preserves_reviewed_original_program_choices_and_export_bytes(row):
    value = Choices.model_validate(row["choices"])
    program = generate(value)
    assert "setpoint_guard" not in choice_document(value)
    assert digest(choice_document(value)) == row["choices_sha256"]
    assert program.digest() == row["program_sha256"]
    assert (
        hashlib.sha256(export_program(program, "json")[0]).hexdigest() == row["json_export_sha256"]
    )


@pytest.mark.parametrize("variant", ["cooling-only", "inline-reheat", "parallel-fan-reheat"])
@pytest.mark.parametrize(
    "zone,cooling,heating", [(75, 40, 0), (66, 0, 40), (70, 0, 0), (68, 0, 0), (73, 0, 0)]
)
def test_independent_position_and_deadband_requests(variant, zone, cooling, heating):
    program = generate(guarded(equipment=variant))
    row = Engine(program).step({"zone": zone})["outputs"]
    assert row["spguard_configuration_valid"] is True
    assert row["damper"] == pytest.approx(20 + 80 * cooling / 100)
    assert row["spguard_cool_permitted_output"] is (cooling > 0)
    if variant != "cooling-only":
        assert row["reheat"] == pytest.approx(heating)
        assert row["spguard_heat_permitted_output"] is (heating > 0)
    else:
        assert "reheat" not in row and "spguard_heat_permitted_output" not in row
    if variant == "parallel-fan-reheat":
        assert row["fan"] is (heating > 0)
    assert not any(issue.level == "error" for issue in validate(program))
    assert program.target.physical_inputs is None and program.target.physical_outputs is None


@pytest.mark.parametrize("variant", ["cooling-only", "inline-reheat", "parallel-fan-reheat"])
@pytest.mark.parametrize("control", ["position", "flow-feedback"])
def test_invalid_setpoints_hold_temperature_integrals_and_preserve_minimum_request(
    variant, control
):
    engine = Engine(
        generate(
            guarded(equipment=variant, control=control, temperature_loop="PI", temperature_ki=0.1)
        )
    )
    engine.step({"zone": 66 if variant != "cooling-only" else 75})
    before = {
        key: dict(value) for key, value in engine.state.items() if key in ("cool_loop", "heat_loop")
    }
    for inputs in [
        {"cool_sp": 1e308, "heat_sp": -1e308},
        {"cool_sp": 49, "heat_sp": 68},
        {"cool_sp": 91, "heat_sp": 68},
    ]:
        if variant == "cooling-only":
            inputs = {"cool_sp": inputs["cool_sp"]}
        row = engine.step(inputs)["outputs"]
        assert row["spguard_configuration_valid"] is False
        assert row["spguard_cool_permitted_output"] is False
        if variant != "cooling-only":
            assert row["reheat"] == 0 and row["spguard_heat_permitted_output"] is False
        if variant == "parallel-fan-reheat":
            assert row["fan"] is False
        if control == "position":
            assert row["damper"] == 20
        else:
            assert row["flow_setpoint"] == 200 and row["damper"] == 0
        assert {key: value for key, value in engine.state.items() if key in before} == before
    repaired = engine.step(
        {"zone": 66, "cool_sp": 73, "heat_sp": 68}
        if variant != "cooling-only"
        else {"zone": 75, "cool_sp": 73}
    )["outputs"]
    assert repaired["spguard_configuration_valid"] is True
    assert repaired["reheat" if variant != "cooling-only" else "damper"] > 0


@pytest.mark.parametrize(
    "cool,heat,valid",
    [
        (73, 68, True),
        (72.999999, 68, False),
        (73 - 0.5e-9, 68, True),
        (70, 75, False),
        (50, 45, False),
        (95, 68, False),
    ],
)
def test_live_range_and_gap_boundaries_are_independent_of_nominal_choices(cool, heat, valid):
    engine = Engine(generate(guarded()))
    row = engine.step({"cool_sp": cool, "heat_sp": heat, "zone": 70})["outputs"]
    assert row["spguard_configuration_valid"] is valid
    assert not (row["spguard_cool_permitted_output"] and row["spguard_heat_permitted_output"])
    if not valid:
        assert row["damper"] == 20 and row["reheat"] == 0 and row["fan"] is False


def test_zero_declared_gap_still_rejects_reversed_setpoints_and_has_no_overlap():
    engine = Engine(
        generate(guarded(setpoint_guard={"minimum": 50, "maximum": 90, "minimum_deadband": 0}))
    )
    for zone in (65, 70, 75):
        row = engine.step({"cool_sp": 70, "heat_sp": 70, "zone": zone})["outputs"]
        assert row["spguard_configuration_valid"] is True
        assert not (row["spguard_cool_permitted_output"] and row["spguard_heat_permitted_output"])
    row = engine.step({"cool_sp": 70, "heat_sp": 70 + 0.5e-9, "zone": 70})["outputs"]
    assert row["spguard_configuration_valid"] is False


def test_thermal_transition_trajectory_and_retained_integrals_have_independent_expected_values():
    engine = Engine(generate(guarded(temperature_loop="PI", temperature_ki=0.1)))
    expected = [
        (66, 20, 40.2, True),
        (70, 20, 0, False),
        (75, 52.16, 0, False),
        (70, 20, 0, False),
        (66, 20, 40.4, True),
    ]
    for zone, damper, reheat, fan in expected:
        row = engine.step({"zone": zone})["outputs"]
        assert (
            row["damper"] == pytest.approx(damper)
            and row["reheat"] == pytest.approx(reheat)
            and row["fan"] is fan
        )
        assert not (row["spguard_cool_permitted_output"] and row["spguard_heat_permitted_output"])


@pytest.mark.parametrize("name", ["zone", "cool_sp", "heat_sp"])
def test_bad_quality_retains_complete_transaction_including_diagnostics(name):
    engine = Engine(generate(guarded()))
    engine.step({"zone": 66})
    before = engine.snapshot()
    with pytest.raises(ScanError, match="open-circuit"):
        engine.step({name: {"value": 70, "quality": "open-circuit"}})
    assert engine.snapshot() == before


@pytest.mark.parametrize("variant", ["cooling-only", "inline-reheat", "parallel-fan-reheat"])
@pytest.mark.parametrize("control", ["position", "flow-feedback"])
def test_guard_bounds_gap_inverse_gains_and_trajectories_convert_as_physical_units(
    variant, control
):
    value = guarded(equipment=variant, control=control, temperature_loop="PI", temperature_ki=0.1)
    metric = convert_units(value, "degC", "L/s")
    assert metric.setpoint_guard.minimum == 10
    assert metric.setpoint_guard.maximum == pytest.approx((90 - 32) * 5 / 9)
    assert metric.setpoint_guard.minimum_deadband == pytest.approx(5 * 5 / 9)
    first, second = Engine(generate(value)), Engine(generate(metric))
    for zone, cool, heat in [
        (66, 73, 68),
        (70, 73, 68),
        (75, 73, 68),
        (70, 72.99, 68),
        (70, 90, 85),
        (70, 50, 50),
        (66, 73, 68),
    ]:
        supplied = {"zone": zone, "cool_sp": cool}
        if variant != "cooling-only":
            supplied["heat_sp"] = heat
        converted = {key: (number - 32) * 5 / 9 for key, number in supplied.items()}
        a, b = first.step(supplied)["outputs"], second.step(converted)["outputs"]
        assert a["spguard_configuration_valid"] == b["spguard_configuration_valid"]
        for key in a:
            if key == "flow_setpoint":
                assert b[key] == pytest.approx(a[key] * 0.4719474432)
            elif type(a[key]) is bool:
                assert b[key] is a[key]
            else:
                assert b[key] == pytest.approx(a[key], abs=1e-10)
    restored = convert_units(metric, "degF", "cfm")
    assert restored.setpoint_guard.model_dump() == pytest.approx(value.setpoint_guard.model_dump())


@pytest.mark.parametrize("variant", ["cooling-only", "inline-reheat", "parallel-fan-reheat"])
@pytest.mark.parametrize("source", ["fixed", "inputs"])
def test_preview_original_json_and_source_provenance_bind_the_declared_policy(variant, source):
    value = guarded(equipment=variant, setpoints=source)
    report = preview(value)
    program = generate(value)
    assert report["can_create"] and not report["native_compile"] and not report["controller_writes"]
    assert report["profile_sha256"] == program.metadata["equipment_wizard"]["profile_sha256"]
    provenance = program.metadata["equipment_wizard"]["setpoint_guard"]
    assert provenance["rules_sha256"] == digest(provenance["rules"])
    assert provenance["choices"] == choice_document(value)["setpoint_guard"]
    assert "runtime external-setpoint range/deadband enforcement" not in report["profile"]["gaps"]
    assert not program.metadata["native_deployment_verified"]
    raw, _, _ = export_program(program, "json")
    restored = import_program(raw, "guarded-vav.bms.json")
    assert restored == program
    assert Engine(restored).step()["outputs"] == Engine(program).step()["outputs"]
    inputs = {n.id for n in program.nodes if n.kind == "Input"}
    assert ("cool_sp" in inputs) is (source == "inputs")
    assert ("heat_sp" in inputs) is (source == "inputs" and variant != "cooling-only")


@pytest.mark.parametrize(
    "guard,changes",
    [
        ({"minimum": True, "maximum": 90, "minimum_deadband": 5}, {}),
        ({"minimum": 50, "maximum": float("nan"), "minimum_deadband": 5}, {}),
        ({"minimum": 50, "maximum": float("inf"), "minimum_deadband": 5}, {}),
        ({"minimum": 90, "maximum": 50, "minimum_deadband": 5}, {}),
        ({"minimum": 50, "maximum": 50, "minimum_deadband": 0}, {}),
        ({"minimum": 50, "maximum": 90, "minimum_deadband": -1}, {}),
        ({"minimum": 50, "maximum": 90, "minimum_deadband": 41}, {}),
        ({"minimum": 50, "maximum": 90, "minimum_deadband": 5}, {"cooling_setpoint": 72}),
        ({"minimum": 50, "maximum": 90, "minimum_deadband": 5}, {"heating_setpoint": 49}),
        ({"minimum": 50, "maximum": 90, "minimum_deadband": 5}, {"cooling_setpoint": 91}),
    ],
)
def test_declared_guard_and_nominal_choices_require_strict_finite_coherent_values(guard, changes):
    with pytest.raises(ValueError):
        guarded(setpoint_guard=guard, **changes)


@pytest.mark.parametrize("family", ["dual-duct", "fan-coil"])
def test_excluded_families_do_not_silently_inherit_single_duct_policy(family):
    with pytest.raises(ValueError, match="single-duct"):
        guarded(equipment=family)
