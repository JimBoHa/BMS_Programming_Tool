"""Actual native compiler/runtime midpoint results, using only owned local hosts."""

import math
import struct

import pytest
from bms_tool.iec import NativeIEC, profile
from bms_tool.native_simulator import NativeSimulator
from bms_tool.source_profiles import source_profile
from bms_tool.storage import Store

from .test_executable_numbers import passthrough
from .test_native_sedona import has_sdk


@pytest.mark.skipif(
    not profile()["available"], reason="Optional pinned MatIEC toolchain unavailable"
)
def test_actual_iec_midpoint_uses_original_value_before_binary32_rounding():
    value = math.nextafter(1.0 + 2**-24, math.inf)
    with NativeIEC(passthrough(value=value, kind="Constant")) as native:
        row = native.step()
        assert not row["fault"] and row["matches_reference"]
        assert struct.pack("!f", row["outputs"]["out"]).hex() == "3f800001"
        assert row["source_generator"] == source_profile()
        assert native.compilation()["source_generator"] == source_profile()


@pytest.mark.skipif(not has_sdk(), reason="Optional pinned Sedona toolchain unavailable")
def test_actual_sedona_midpoint_uses_original_value_and_profile_bound_kit(tmp_path):
    value = math.nextafter(1.0 + 2**-24, math.inf)
    native = NativeSimulator(Store(tmp_path))
    try:
        started = native.start(passthrough(value=value, kind="Constant"))
        row = native.step()
        assert not row["fault"] and row["matches_reference"]
        assert struct.pack("!f", row["outputs"]["out"]).hex() == "3f800001"
        assert row["source_generator"] == started["source_generator"] == source_profile()
    finally:
        native.stop()
