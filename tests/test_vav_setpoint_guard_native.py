"""Actual compiled host IEC trajectories; these do not establish JCI acceptance."""

import copy

import pytest
from bms_tool import iec
from bms_tool.equipment_wizard import convert_units, generate

from tests.test_vav_setpoint_guard import guarded


@pytest.mark.skipif(not iec.profile()["available"], reason="Pinned MatIEC/clang unavailable")
@pytest.mark.parametrize("family", ["cooling-only", "inline-reheat", "parallel-fan-reheat"])
@pytest.mark.parametrize("unit", ["degF", "degC"])
@pytest.mark.parametrize("control", ["position", "flow-feedback"])
def test_compiled_thermal_modes_invalid_configuration_integral_hold_and_quality_rollback(
    family, unit, control
):
    value = guarded(equipment=family, control=control, temperature_loop="PI", temperature_ki=0.1)
    if unit == "degC":
        value = convert_units(value, unit, "L/s")

    def inputs(zone, cool=73, heat=68):
        values = {"zone": zone, "cool_sp": cool}
        if family != "cooling-only":
            values["heat_sp"] = heat
        return values if unit == "degF" else {k: (v - 32) * 5 / 9 for k, v in values.items()}

    with iec.NativeIEC(generate(value)) as native:
        process = native.process
        for zone, allowed in [(75, "cool"), (70, None), (66, "heat"), (70, None)]:
            row = native.step(inputs(zone))
            assert not row["fault"] and row["matches_reference"], row
            out = row["outputs"]
            assert out["spguard_configuration_valid"] is True
            assert out["spguard_cool_permitted_output"] is (allowed == "cool")
            if family != "cooling-only":
                assert out["spguard_heat_permitted_output"] is (allowed == "heat")
                assert (out["reheat"] > 40) is (allowed == "heat")
            if family == "parallel-fan-reheat":
                assert out["fan"] is (allowed == "heat")
            if allowed is None and control == "position":
                assert out["damper"] == 20
            if allowed is None and control == "flow-feedback":
                assert out["flow_setpoint"] == pytest.approx(
                    200 if unit == "degF" else 200 * 0.4719474432, abs=0.0001
                )
        thermal_keys = ["n_cool_loop_integral"]
        if family != "cooling-only":
            thermal_keys.append("n_heat_loop_integral")
        assert all(key in row["native_state"] for key in thermal_keys)
        before = {key: copy.deepcopy(row["native_state"][key]) for key in thermal_keys}
        for supplied in [inputs(66, 91), inputs(75, 49), inputs(75, 72, 68)]:
            # Cooling-only has no pair/deadband constraint; 72 remains in range.
            if family == "cooling-only" and supplied == inputs(75, 72, 68):
                continue
            row = native.step(supplied)
            assert not row["fault"] and row["matches_reference"], row
            assert row["outputs"]["spguard_configuration_valid"] is False
            assert row["outputs"]["spguard_cool_permitted_output"] is False
            if family != "cooling-only":
                assert row["outputs"]["reheat"] == 0
            assert {key: row["native_state"][key] for key in thermal_keys} == before
        resumed = native.step(inputs(75))
        assert resumed["matches_reference"] and not resumed["fault"], resumed
        fault = native.step({"zone": {"value": 70, "quality": "open-circuit"}})
        assert fault["fault"] and fault["matches_reference"], fault
        assert fault["outputs"] == resumed["outputs"]
        assert fault["native_state"] == resumed["native_state"]
    assert process.poll() is not None
