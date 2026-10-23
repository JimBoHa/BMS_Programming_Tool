"""Actual host-calendar IEC execution; no autonomous field-calendar claim."""

from datetime import datetime

import pytest
from bms_tool import iec
from bms_tool.calendar_schedule import compile_schedule
from bms_tool.schedule_coordination import generate

from tests.test_schedule_coordination import choices, group

CASES = [
    (
        "regular",
        {"days": [0]},
        [
            "2026-01-05T04:59:59Z",
            "2026-01-05T05:00:00Z",
            "2026-01-05T08:00:00Z",
            "2026-01-05T17:59:59Z",
            "2026-01-05T18:00:00Z",
        ],
    ),
    (
        "overnight",
        {"days": [6], "start": "01:00", "end": "23:00"},
        [
            "2026-01-10T21:59:59Z",
            "2026-01-10T22:00:00Z",
            "2026-01-11T00:00:00Z",
            "2026-01-11T01:00:00Z",
            "2026-01-11T23:00:00Z",
        ],
    ),
    (
        "overlap",
        {"days": [0, 1], "start": "22:00", "end": "20:00"},
        [
            "2026-01-05T19:00:00Z",
            "2026-01-06T19:30:00Z",
            "2026-01-06T20:00:00Z",
            "2026-01-06T21:00:00Z",
            "2026-01-07T20:00:00Z",
        ],
    ),
    (
        "all-day",
        {"mode": "all-day", "days": [0]},
        [
            "2026-01-04T21:00:00Z",
            "2026-01-05T00:00:00Z",
            "2026-01-05T12:00:00Z",
            "2026-01-06T00:00:00Z",
        ],
    ),
    (
        "full-week",
        {"mode": "all-day", "days": list(range(7)), "lead_minutes": 1440},
        ["2026-01-05T00:00:00Z", "2026-01-11T23:59:59Z", "2026-01-12T00:00:00Z"],
    ),
    ("disabled", {"mode": "disabled"}, ["2026-01-05T05:00:00Z", "2026-01-05T12:00:00Z"]),
    ("empty", {"start": "08:00", "end": "08:00"}, ["2026-01-05T05:00:00Z", "2026-01-05T08:00:00Z"]),
    (
        "spring",
        {"timezone": "America/Los_Angeles", "days": [6], "start": "03:30", "end": "08:00"},
        [
            "2026-03-08T08:29:59Z",
            "2026-03-08T08:30:00Z",
            "2026-03-08T10:30:00Z",
            "2026-03-08T15:00:00Z",
        ],
    ),
    (
        "fall",
        {
            "timezone": "America/Los_Angeles",
            "days": [6],
            "start": "01:15",
            "end": "01:45",
            "lead_minutes": 0,
        },
        [
            "2026-11-01T08:30:00Z",
            "2026-11-01T08:50:00Z",
            "2026-11-01T09:10:00Z",
            "2026-11-01T09:30:00Z",
            "2026-11-01T09:45:00Z",
        ],
    ),
]


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional pinned MatIEC/clang unavailable"
)
@pytest.mark.parametrize("case,configuration,clocks", CASES, ids=[row[0] for row in CASES])
def test_real_compiled_schedule_composition_boundaries_and_host_binding_faults(
    case, configuration, clocks
):
    program, _ = generate(choices(group(**configuration), group(id="other", mode="disabled")))
    with iec.NativeIEC(program) as native:
        process = native.process
        for text in clocks:
            result = native.step(clock=datetime.fromisoformat(text))
            assert not result["fault"] and result["matches_reference"], result
        calendars = {
            n.id: compile_schedule(n.params) for n in program.nodes if n.kind == "Schedule"
        }
        if calendars:
            clock = datetime.fromisoformat(clocks[-1])
            before = result
            bindings = {
                id: {"value": calendar.active(clock), "valid": True}
                for id, calendar in calendars.items()
            }
            bindings[next(iter(bindings))]["valid"] = False
            fault = native.step(clock=clock, calendar_bindings=bindings)
            assert fault["fault"] and fault["matches_reference"], fault
            assert (
                fault["outputs"] == before["outputs"]
                and fault["native_state"] == before["native_state"]
            )
            assert native.step(clock=clock)["matches_reference"]
        assert native.attempts == len(clocks) + (2 if calendars else 0)
    assert process.poll() is not None


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional pinned MatIEC/clang unavailable"
)
def test_actual_native_symbols_for_suffix_and_case_variant_declarations_are_unique():
    program, _ = generate(
        choices(
            *(group(id=id, mode="all-day") for id in ("zone", "zone_pre_or", "Zone", "zone_not"))
        )
    )
    with iec.NativeIEC(program) as native:
        process = native.process
        result = native.step(clock=datetime.fromisoformat("2026-01-05T12:00:00Z"))
        assert not result["fault"] and result["matches_reference"], result
        assert all(result["outputs"][f"zg{i}_occupied"] for i in range(1, 5))
        assert native.attempts == 1
    assert process.poll() is not None
