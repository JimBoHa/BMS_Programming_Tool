"""Actual MatIEC polarity, initial-mode, fan, condensate and temperature-unit matrix."""

import copy

import pytest
from bms_tool import iec
from bms_tool.heat_pump import convert_units, generate

from tests.test_heat_pump import COMPOSITIONS, choices, fahrenheit


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Build optional pinned MatIEC compiler first"
)
@pytest.mark.parametrize("polarity,initial,fan,condensate,unit", COMPOSITIONS)
def test_actual_compiled_compressor_valve_timers_permissions_and_quality_rollback(
    polarity, initial, fan, condensate, unit
):
    value = convert_units(
        choices(
            reversing_polarity=polarity, initial_mode=initial, fan_policy=fan, condensate=condensate
        ),
        unit,
    )
    program = generate(value)
    with iec.NativeIEC(program) as native:
        process = native.process
        rows = []

        def step(**inputs):
            result = native.step(inputs)
            assert result["matches_reference"], result
            assert not result["fault"], result
            rows.append(result)
            return result["outputs"]

        def temperature(value, **inputs):
            return step(zone=fahrenheit(value, unit), **inputs)

        for _ in range(4):
            out = temperature(80)
        assert out["compressor"] and out["cooling_active"]
        held = temperature(70)
        assert held["compressor"] and held["minimum_on_hold"] and held["fan"]
        for _ in range(3):
            out = temperature(70)
        assert not out["compressor"]
        for _ in range(8):
            out = temperature(60)
        assert out["compressor"] and out["heating_active"]
        assert out["reversing_valve"] == (polarity == "on-for-heating")
        for _ in range(3):
            out = temperature(60, airflow_proven=False)
        assert not out["compressor"] and out["fan"]
        for requested in (80, 60, 80, 60):
            temperature(requested)
        for _ in range(8):
            out = temperature(80)
        assert out["compressor"] and out["cooling_active"]
        before = copy.deepcopy(rows[-1])
        fault = native.step({"zone": {"quality": "open-circuit"}})
        assert fault["fault"] and fault["matches_reference"]
        assert (
            fault["outputs"] == before["outputs"]
            and fault["native_state"] == before["native_state"]
        )
        assert fault["successful_scans"] == before["successful_scans"]
        for _ in range(8):
            out = temperature(60)
        assert out["compressor"] and out["heating_active"]
        if condensate != "none":
            out = temperature(60, condensate_alarm=True)
            assert out["compressor"] is (condensate == "disable-cooling")
        for previous, current in zip(rows, rows[1:], strict=False):
            if previous["outputs"]["reversing_valve"] != current["outputs"]["reversing_valve"]:
                assert (
                    not previous["outputs"]["compressor"] and not current["outputs"]["compressor"]
                )
    assert process.poll() is not None
