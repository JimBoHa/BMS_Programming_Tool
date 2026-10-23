"""Ordinary actual fixed-host IEC execution; never JCI controller acceptance."""

import copy

import pytest
from bms_tool import iec
from bms_tool.equipment_wizard import convert_units, generate

from tests.test_fan_coil_wizard import fan_choices


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional pinned MatIEC/clang toolchain unavailable"
)
@pytest.mark.parametrize("fan", ["single-speed", "variable-speed"])
@pytest.mark.parametrize("policy", ["continuous-occupied", "cycle-on-demand"])
@pytest.mark.parametrize("condensate", ["none", "disable-cooling", "shutdown-unit"])
@pytest.mark.parametrize("unit", ["degF", "degC"])
def test_actual_compiled_fan_modes_permissions_retained_integrals_and_quality_rollback(
    fan, policy, condensate, unit
):
    value = fan_choices(fan, policy, condensate, setpoints="inputs")
    if unit == "degC":
        value = convert_units(value, unit, "L/s")

    def temperature(fahrenheit):
        return fahrenheit if unit == "degF" else (fahrenheit - 32) * 5 / 9

    with iec.NativeIEC(generate(value)) as native:
        process = native.process
        first = native.step()
        assert not first["fault"] and first["matches_reference"], first
        assert first["outputs"]["cooling_valve"] == pytest.approx(40.2, abs=0.0002)
        assert first["outputs"]["fan_enable"] is True
        for inputs in (
            {"zone": temperature(70)},
            {"zone": temperature(66)},
            {"occupied": False},
            {"unit_enable": False},
            {"energy_holdoff": True},
            {"heat_sp": temperature(72)},
            {"heat_sp": temperature(75)},
        ):
            row = native.step(inputs)
            assert not row["fault"] and row["matches_reference"], row
            if "zone" not in inputs:
                assert row["outputs"]["cooling_valve"] == 0
                assert row["outputs"]["heating_valve"] == 0
                assert row["outputs"]["fan_enable"] is False
                if fan == "variable-speed":
                    assert row["outputs"]["fan_speed"] == 0
        if condensate != "none":
            for zone in (74, 66, 70):
                row = native.step({"zone": temperature(zone), "condensate_alarm": True})
                assert not row["fault"] and row["matches_reference"], row
                assert row["outputs"]["cooling_valve"] == 0
                if condensate == "shutdown-unit":
                    assert row["outputs"]["heating_valve"] == 0
                    assert row["outputs"]["fan_enable"] is False
        resumed = native.step()
        assert not resumed["fault"] and resumed["matches_reference"], resumed
        before = copy.deepcopy(resumed)
        fault = native.step({"occupied": {"value": False, "quality": "open-circuit"}})
        assert fault["fault"] and fault["matches_reference"], fault
        assert fault["outputs"] == before["outputs"]
        assert fault["native_state"] == before["native_state"]
        assert native.step()["matches_reference"]
    assert process.poll() is not None
