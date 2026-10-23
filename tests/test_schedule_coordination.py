"""Independent minute-of-week interval laws and actual generated graph behavior."""

import copy
from datetime import UTC, datetime, timedelta

import pytest
from bms_tool.calendar_schedule import compile_schedule
from bms_tool.engine import Engine
from bms_tool.formats import export_program, import_program
from bms_tool.schedule_coordination import (
    PROFILE_SHA,
    Choices,
    Group,
    PreviewRequest,
    generate,
    preview,
    weekly_minutes,
    windows,
)


def group(**changes):
    return Group(
        **(
            {
                "id": "zone",
                "label": "Zone group",
                "timezone": "UTC",
                "mode": "window",
                "days": [0, 1, 2, 3, 4],
                "start": "08:00",
                "end": "18:00",
                "lead_minutes": 180,
            }
            | changes
        )
    )


def choices(*groups, **changes):
    return Choices(
        **(
            {
                "project_id": "authored-schedules",
                "name": "Authored occupancy",
                "ahu_label": "Declared AHU",
                "groups": list(groups) or [group()],
            }
            | changes
        )
    )


def at(program, text):
    return Engine(program).step(clock=datetime.fromisoformat(text))["outputs"]


@pytest.mark.parametrize(
    "start,end,days,lead",
    [
        ("08:00", "18:00", [0, 1, 2, 3, 4], 180),
        ("01:00", "23:00", [0], 180),
        ("01:00", "22:00", [6], 180),
        ("22:00", "06:00", [0, 6], 180),
        ("22:00", "20:00", [0, 1], 180),
        ("00:00", "23:59", [1, 4], 1440),
        ("23:59", "00:00", [6], 1),
        ("08:00", "08:00", list(range(7)), 180),
        ("08:00", "18:00", [], 180),
        ("08:00", "18:00", [0, 2, 6], 0),
    ],
)
def test_every_week_minute_matches_independent_absolute_interval_oracle_and_core_lowering(
    start, end, days, lead
):
    g = group(start=start, end=end, days=days, lead_minutes=lead)
    start_min = int(start[:2]) * 60 + int(start[3:])
    end_min = int(end[:2]) * 60 + int(end[3:])
    duration = end_min - start_min
    if duration < 0:
        duration += 1440
    baseline = datetime(2026, 1, 5, tzinfo=UTC)
    for extra in (0, lead):
        grid = weekly_minutes(g, extra)
        lowered = [compile_schedule(row | {"timezone": "UTC"}) for row in windows(grid)]
        for point in range(10080):
            expected = duration > 0 and any(
                day * 1440 + start_min - extra + week * 10080
                <= point
                < day * 1440 + start_min + duration + week * 10080
                for day in days
                for week in (-1, 0, 1)
            )
            assert bool(grid[point]) is expected
            assert (
                any(window.active(baseline + timedelta(minutes=point)) for window in lowered)
                is expected
            )


@pytest.mark.parametrize(
    "mode,days,lead,occupied,expanded",
    [
        ("window", [0], 180, 600, 780),
        ("all-day", [0], 180, 1440, 1620),
        ("all-day", list(range(7)), 1440, 10080, 10080),
        ("disabled", list(range(7)), 1440, 0, 0),
        ("all-day", [], 180, 0, 0),
    ],
)
def test_explicit_full_day_full_week_disabled_and_empty_day_counts(
    mode, days, lead, occupied, expanded
):
    g = group(mode=mode, days=days, lead_minutes=lead)
    program, summaries = generate(choices(g))
    assert summaries[0]["occupied_week_minutes"] == occupied
    assert summaries[0]["pre_week_minutes"] == expanded
    assert all(n.params["start"] != n.params["end"] for n in program.nodes if n.kind == "Schedule")
    assert len(program.nodes) <= 1000
    if occupied == 10080:
        assert at(program, "2026-01-05T00:00:00Z")["ahu_occupied"]
        assert at(program, "2026-01-11T23:59:59Z")["ahu_occupied"]
        assert not at(program, "2026-01-12T00:00:00Z")["zg1_pre_only"]


@pytest.mark.parametrize(
    "clock,occupied,pre,only",
    [
        ("2026-01-04T21:59:59Z", False, False, False),
        ("2026-01-04T22:00:00Z", False, True, True),
        ("2026-01-05T00:00:00Z", False, True, True),
        ("2026-01-05T01:00:00Z", True, True, False),
        ("2026-01-05T22:59:59Z", True, True, False),
        ("2026-01-05T23:00:00Z", False, False, False),
    ],
)
def test_greater_than_full_day_pre_union_preserves_end_and_rotates_start_weekday(
    clock, occupied, pre, only
):
    program, _ = generate(choices(group(start="01:00", end="23:00", days=[0])))
    assert at(program, clock) == {
        "zg1_occupied": occupied,
        "zg1_pre_or_occupied": pre,
        "zg1_pre_only": only,
        "ahu_occupied": occupied,
    }


@pytest.mark.parametrize(
    "clock,occupied,only",
    [
        ("2026-01-05T19:00:00Z", False, True),
        ("2026-01-06T19:30:00Z", True, False),
        ("2026-01-06T20:00:00Z", False, True),
        ("2026-01-06T21:00:00Z", False, True),
        ("2026-01-06T22:00:00Z", True, False),
        ("2026-01-07T20:00:00Z", False, False),
    ],
)
def test_union_originals_before_subtracting_pre_only_across_overlapping_expansions(
    clock, occupied, only
):
    program, _ = generate(choices(group(start="22:00", end="20:00", days=[0, 1])))
    row = at(program, clock)
    assert row["zg1_occupied"] is occupied and row["zg1_pre_only"] is only
    assert row["ahu_occupied"] is occupied


@pytest.mark.parametrize("a,b", [(False, False), (False, True), (True, False), (True, True)])
def test_ahu_truth_matrix_uses_original_group_occupancy_not_pre_only(a, b):
    program, _ = generate(
        choices(
            group(id="a", mode="all-day" if a else "disabled"),
            group(id="b", mode="all-day" if b else "disabled"),
        )
    )
    row = at(program, "2026-01-05T12:00:00Z")
    assert row["ahu_occupied"] is (a or b)
    assert row["zg1_occupied"] is a and row["zg2_occupied"] is b
    early, _ = generate(choices(group()))
    row = at(early, "2026-01-05T05:00:00Z")
    assert row["zg1_pre_only"] and not row["ahu_occupied"]


@pytest.mark.parametrize(
    "pre,occupied,elapsed",
    [
        ("2026-03-08T08:30:00Z", "2026-03-08T10:30:00Z", 120),
        ("2026-11-01T07:30:00Z", "2026-11-01T11:30:00Z", 240),
    ],
)
def test_dst_wall_lead_is_explicitly_not_three_elapsed_hours(pre, occupied, elapsed):
    # 03:30 occupies after either transition; expanded local start is00:30.
    program, _ = generate(
        choices(group(timezone="America/Los_Angeles", days=[6], start="03:30", end="08:00"))
    )
    assert at(program, pre)["zg1_pre_only"]
    assert not at(program, pre)["ahu_occupied"]
    assert at(program, occupied)["ahu_occupied"]
    assert (
        datetime.fromisoformat(occupied) - datetime.fromisoformat(pre)
    ).total_seconds() == elapsed * 60


def test_dst_repeated_hour_pointwise_window_has_real_off_gap_and_spring_gap_never_occurs():
    program, _ = generate(
        choices(
            group(
                timezone="America/Los_Angeles", days=[6], start="01:15", end="01:45", lead_minutes=0
            )
        )
    )
    assert [
        at(program, c)["ahu_occupied"]
        for c in [
            "2026-11-01T08:30:00Z",
            "2026-11-01T08:50:00Z",
            "2026-11-01T09:10:00Z",
            "2026-11-01T09:30:00Z",
            "2026-11-01T09:45:00Z",
        ]
    ] == [True, False, False, True, False]
    gap, _ = generate(
        choices(
            group(
                timezone="America/Los_Angeles", days=[6], start="02:15", end="02:45", lead_minutes=0
            )
        )
    )
    assert not any(
        at(gap, f"2026-03-08T{hour:02d}:{minute:02d}:00Z")["ahu_occupied"]
        for hour in (9, 10, 11)
        for minute in (0, 15, 30, 45)
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"lead_minutes": True},
        {"lead_minutes": 1.5},
        {"lead_minutes": "180"},
        {"lead_minutes": -1},
        {"lead_minutes": 1441},
        {"days": [True]},
        {"days": [0, 0]},
        {"days": [7]},
        {"mode": ""},
        {"timezone": ""},
        {"timezone": "Unknown/Zone"},
        {"exceptions": [{"date": "2026-01-05", "enabled": False}]},
        {"start": "24:00"},
        {"end": "1:00"},
        {"label": "   "},
        {"label": "A\nB"},
    ],
    ids=[
        "bool-lead",
        "float-lead",
        "text-lead",
        "negative",
        "too-large",
        "bool-day",
        "duplicate-day",
        "unknown-day",
        "no-mode",
        "no-zone",
        "unknown-zone",
        "exceptions",
        "24hour",
        "short-time",
        "blank-label",
        "control-label",
    ],
)
def test_strict_declarations_refuse_guessed_or_unsupported_semantics(patch):
    with pytest.raises(ValueError):
        group(**patch)


def test_group_clock_and_work_bounds_and_labels_fail_before_generation():
    for change in (
        {"groups": []},
        {"groups": [group()] * 9},
        {"groups": [group(), group()]},
        {"scan_seconds": True},
        {"scan_seconds": 0.001},
        {"scan_seconds": float("nan")},
        {"ahu_label": "\t"},
    ):
        with pytest.raises(ValueError):
            choices(**change)
    for clocks in (
        ["2026-01-05T12:00:00"],
        ["2026-01-05T12:00:00+01:00"],
        [True],
        ["bad"],
        ["2026-01-05T00:00:00Z"] * 129,
    ):
        with pytest.raises(ValueError):
            PreviewRequest(choices=choices(), clocks=clocks)
    maximum = choices(
        *(
            group(
                id=f"zone{i}",
                label="L" * 160,
                mode="all-day",
                days=list(range(7)),
                lead_minutes=1440,
            )
            for i in range(8)
        ),
        ahu_label="A" * 140,
    )
    report = preview(PreviewRequest(choices=maximum, clocks=["2026-01-05T00:00:00Z"] * 128))
    assert report["can_create"] and len(report["evaluation"]) == 128
    assert report["evaluation"][0]["outputs"]["ahu_occupied"]


@pytest.mark.parametrize(
    "format,extension", [("json", "json"), ("st", "st"), ("plcopen", "xml"), ("graphml", "graphml")]
)
def test_complete_program_profile_and_evidence_survive_interchange_without_source_mutation(
    format, extension
):
    source = choices(
        group(start="01:00", end="23:00", days=[0]),
        group(id="other", mode="all-day", timezone="America/Los_Angeles"),
    )
    before = copy.deepcopy(source)
    program, _ = generate(source)
    encoded, _, _ = export_program(program, format)
    reopened = import_program(encoded, "schedule." + extension)
    assert reopened == program and reopened.digest() == program.digest() and source == before
    assert reopened.metadata["schedule_coordination"]["profile_sha256"] == PROFILE_SHA


def test_valid_suffix_and_case_variant_ids_never_alias_generated_or_native_symbols():
    from bms_tool.engine import validate

    source = choices(
        *(group(id=id, mode="all-day") for id in ("zone", "zone_pre_or", "Zone", "zone_not"))
    )
    program, summary = generate(source)
    assert not [issue for issue in validate(program) if issue.level == "error"]
    assert len({node.id.casefold() for node in program.nodes}) == len(program.nodes)
    assert [row["outputs"]["occupied"] for row in summary] == [
        f"zg{i}_occupied" for i in range(1, 5)
    ]
    for format, extension in (("st", "st"), ("plcopen", "xml")):
        data, _, _ = export_program(program, format)
        assert import_program(data, "schedule." + extension) == program
    assert at(program, "2026-01-05T12:00:00Z")["ahu_occupied"]
