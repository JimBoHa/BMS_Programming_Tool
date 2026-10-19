"""Time-zone and exception priority contracts for controller schedules."""

import copy
from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from bms_tool.calendar_schedule import (
    compile_schedule,
    schedule_active,
    validate_schedule_params,
)


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def exception(day, start=None, end=None, enabled=True):
    row = {"date": day, "enabled": enabled}
    if start is not None:
        row["start"] = start
    if end is not None:
        row["end"] = end
    return row


def test_defaults_and_boundaries_keep_original_weekly_behavior():
    calendar = compile_schedule({})
    assert not calendar.active(utc("2026-01-05T07:59:59"))
    assert calendar.active(utc("2026-01-05T08:00:00"))
    assert calendar.active(utc("2026-01-05T17:59:59"))
    assert not calendar.active(utc("2026-01-05T18:00:00"))
    assert not calendar.active(utc("2026-01-10T12:00:00"))
    assert not schedule_active({"start": "08:00", "end": "08:00"}, utc("2026-01-05T08:00"))
    assert not schedule_active({"days": []}, utc("2026-01-05T12:00"))


def test_empty_timezone_uses_provided_wall_fields_and_accepts_naive_clock():
    calendar = compile_schedule({})
    assert calendar.active(datetime(2026, 1, 5, 9))
    assert calendar.active(datetime(2026, 1, 5, 9, tzinfo=timezone(timedelta(hours=10))))
    assert not calendar.active(utc("2026-01-05T19:00"))


def test_timezone_converts_instant_before_weekday_and_date_decisions():
    calendar = compile_schedule({"timezone": "America/Los_Angeles"})
    assert calendar.active(utc("2026-01-05T16:00"))  # Monday 08:00 PST
    assert not calendar.active(utc("2026-01-06T02:00"))  # Monday 18:00 PST
    assert not calendar.active(utc("2026-01-05T01:00"))  # Sunday 17:00 PST
    assert not calendar.active(utc("2026-07-06T14:59"))  # Monday 07:59 PDT
    assert calendar.active(utc("2026-07-06T15:00"))  # Monday 08:00 PDT
    with pytest.raises(ValueError, match="aware clock"):
        calendar.active(datetime(2026, 1, 5, 9))


def test_overnight_weekly_period_belongs_to_start_date_across_week_boundary():
    calendar = compile_schedule({"start": "22:00", "end": "06:00", "days": [6]})
    assert not calendar.active(utc("2026-01-04T21:59"))
    assert calendar.active(utc("2026-01-04T22:00"))
    assert calendar.active(utc("2026-01-05T00:00"))
    assert calendar.active(utc("2026-01-05T05:59:59"))
    assert not calendar.active(utc("2026-01-05T06:00"))
    assert not calendar.active(utc("2026-01-05T22:00"))


def test_spring_dst_gap_never_activates_missing_period():
    calendar = compile_schedule(
        {"start": "02:15", "end": "02:45", "days": [6], "timezone": "America/Los_Angeles"}
    )
    # 01:59:59 PST is followed by 03:00:00 PDT on this Sunday.
    assert not calendar.active(utc("2026-03-08T09:59:59"))
    assert not calendar.active(utc("2026-03-08T10:00:00"))
    assert not calendar.active(utc("2026-03-08T10:30:00"))
    # An artificially constructed 02:30 PST is normalized to its real 03:30 PDT instant.
    imaginary = datetime(2026, 3, 8, 2, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert calendar.local_clock(imaginary).hour == 3
    assert not calendar.active(imaginary)


def test_spring_dst_window_spans_jump_using_wall_boundaries():
    calendar = compile_schedule(
        {"start": "01:30", "end": "03:30", "days": [6], "timezone": "America/Los_Angeles"}
    )
    assert not calendar.active(utc("2026-03-08T09:29:59"))
    assert calendar.active(utc("2026-03-08T09:30:00"))
    assert calendar.active(utc("2026-03-08T09:59:59"))
    assert calendar.active(utc("2026-03-08T10:00:00"))
    assert not calendar.active(utc("2026-03-08T10:30:00"))


def test_autumn_dst_repeated_window_runs_in_both_folds():
    calendar = compile_schedule(
        {"start": "01:15", "end": "01:45", "days": [6], "timezone": "America/Los_Angeles"}
    )
    for hour, fold in ((8, 0), (9, 1)):
        instant = datetime(2026, 11, 1, hour, 30, tzinfo=UTC)
        assert calendar.local_clock(instant).fold == fold
        assert calendar.active(instant)
        assert not calendar.active(instant.replace(minute=14))
        assert not calendar.active(instant.replace(minute=45))
    zone = ZoneInfo("America/Los_Angeles")
    assert calendar.active(datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0))
    assert calendar.active(datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1))


def test_dst_overnight_uses_local_start_date_and_exclusive_end():
    calendar = compile_schedule(
        {"start": "23:00", "end": "03:30", "days": [5], "timezone": "America/Los_Angeles"}
    )
    assert calendar.active(utc("2026-03-08T07:00"))  # Saturday 23:00
    assert calendar.active(utc("2026-03-08T10:00"))  # Sunday 03:00 after jump
    assert not calendar.active(utc("2026-03-08T10:30"))


def test_closed_exception_overrides_weekly_and_previous_night():
    params = {
        "start": "22:00",
        "end": "06:00",
        "days": [0, 1, 2, 3, 4],
        "exceptions": [exception("2026-01-06", enabled=False)],
    }
    calendar = compile_schedule(params)
    assert calendar.active(utc("2026-01-05T23:59"))
    assert not calendar.active(utc("2026-01-06T00:00"))
    assert not calendar.active(utc("2026-01-06T05:00"))
    assert not calendar.active(utc("2026-01-06T23:00"))
    assert not calendar.active(utc("2026-01-07T05:00"))  # Closed start day has no carry.
    assert calendar.active(utc("2026-01-07T22:00"))


def test_enabled_exception_replaces_whole_day_and_allows_multiple_windows():
    rows = [
        exception("2026-01-05", "06:00", "07:00"),
        exception("2026-01-05", "19:00", "20:00"),
    ]
    params = {"exceptions": rows}
    calendar = compile_schedule(params)
    for text, expected in (
        ("2026-01-05T06:00", True),
        ("2026-01-05T07:00", False),
        ("2026-01-05T12:00", False),
        ("2026-01-05T19:00", True),
        ("2026-01-05T20:00", False),
        ("2026-01-06T12:00", True),
    ):
        assert calendar.active(utc(text)) is expected
        assert schedule_active({"exceptions": rows[::-1]}, utc(text)) is expected


def test_overnight_exception_carries_only_into_day_without_own_exception():
    rows = [exception("2026-01-10", "23:00", "03:00")]
    calendar = compile_schedule({"days": [], "exceptions": rows})
    assert calendar.active(utc("2026-01-10T23:00"))
    assert calendar.active(utc("2026-01-11T02:59:59"))
    assert not calendar.active(utc("2026-01-11T03:00"))
    for next_exception in (
        exception("2026-01-11", enabled=False),
        exception("2026-01-11", "10:00", "11:00"),
    ):
        calendar = compile_schedule({"days": [], "exceptions": [*rows, next_exception]})
        assert not calendar.active(utc("2026-01-11T02:00"))


def test_next_day_exception_replaces_previous_weekly_carry_with_own_window():
    calendar = compile_schedule(
        {
            "start": "22:00",
            "end": "06:00",
            "days": [0],
            "exceptions": [exception("2026-01-06", "02:00", "03:00")],
        }
    )
    assert not calendar.active(utc("2026-01-06T01:00"))
    assert calendar.active(utc("2026-01-06T02:00"))
    assert not calendar.active(utc("2026-01-06T03:00"))


def test_exception_date_follows_selected_timezone_not_utc_date():
    calendar = compile_schedule(
        {"timezone": "America/Los_Angeles", "exceptions": [exception("2026-01-05", enabled=False)]}
    )
    assert not calendar.active(utc("2026-01-06T01:00"))  # Jan 5 17:00, closed.
    assert calendar.active(utc("2026-01-06T17:00"))  # Jan 6 09:00, normal.


def test_leap_date_and_minimum_date_are_supported_without_overflow():
    calendar = compile_schedule({"exceptions": [exception("2028-02-29", "09:00", "10:00")]})
    assert calendar.active(utc("2028-02-29T09:00"))
    assert not calendar.active(utc("2028-02-29T10:00"))
    assert not compile_schedule({"days": []}).active(datetime.min)
    assert date.min not in calendar.exceptions


def test_compiled_schedule_copies_mutable_source_and_is_immutable():
    params = {"days": [0], "exceptions": [exception("2026-01-06", "09:00", "10:00")]}
    calendar = compile_schedule(params)
    params["days"].clear()
    params["exceptions"][0]["start"] = "11:00"
    assert calendar.active(utc("2026-01-05T09:00"))
    assert calendar.active(utc("2026-01-06T09:00"))
    with pytest.raises(TypeError):
        calendar.exceptions[date(2026, 1, 6)] = ()
    assert copy.deepcopy(calendar) is calendar


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ([], "parameters must be an object"),
        ({"unknown": 1}, "Unknown schedule parameters"),
        ({"start": "8:00"}, "start must use HH:MM"),
        ({"start": "24:00"}, "start must use HH:MM"),
        ({"end": "12:60"}, "end must use HH:MM"),
        ({"end": "08:00:00"}, "end must use HH:MM"),
        ({"end": 800}, "end must use HH:MM"),
        ({"days": [True]}, "days must be a list of integers"),
        ({"days": [7]}, "days must be a list of integers"),
        ({"days": [-1]}, "days must be a list of integers"),
        ({"days": [1.0]}, "days must be a list of integers"),
        ({"days": "0,1"}, "days must be a list of integers"),
        ({"timezone": False}, "timezone must be an IANA"),
        ({"timezone": "x" * 129}, "timezone must be an IANA"),
        ({"timezone": "Invalid/Nowhere"}, "not an available IANA time zone"),
        ({"timezone": "/etc/passwd"}, "not an available IANA time zone"),
        ({"exceptions": {}}, "exceptions must be a list"),
        ({"exceptions": [None]}, "exceptions\\[0\\] must be an object"),
        ({"exceptions": [{}]}, "date must be a valid YYYY-MM-DD"),
        ({"exceptions": [{"date": "20260105"}]}, "date must be a valid YYYY-MM-DD"),
        ({"exceptions": [{"date": "2026-02-29"}]}, "date must be a valid YYYY-MM-DD"),
        ({"exceptions": [{"date": "2026-13-01"}]}, "date must be a valid YYYY-MM-DD"),
        ({"exceptions": [exception("2026-01-05", enabled=0)]}, "enabled must be boolean"),
        ({"exceptions": [exception("2026-01-05")]}, "start must use HH:MM"),
        ({"exceptions": [exception("2026-01-05", "08:00")]}, "end must use HH:MM"),
        (
            {"exceptions": [{"date": "2026-01-05", "start": "08:00", "end": "09:00", "foo": 1}]},
            "has unknown fields: foo",
        ),
        (
            {"exceptions": [exception("2026-01-05", "08:00", "09:00", enabled=False)]},
            "disabled date cannot contain times",
        ),
        (
            {"exceptions": [exception("2026-01-05", enabled=False)] * 2},
            "duplicate closed date",
        ),
        (
            {"exceptions": [exception("2026-01-05", "08:00", "09:00")] * 2},
            "duplicate window",
        ),
    ],
)
def test_invalid_parameters_produce_diagnostic_ready_value_errors(params, message):
    with pytest.raises(ValueError, match=message):
        validate_schedule_params(params)


def test_closed_and_enabled_rows_conflict_regardless_of_order():
    rows = [exception("2026-01-05", enabled=False), exception("2026-01-05", "08:00", "09:00")]
    for ordered in (rows, rows[::-1]):
        with pytest.raises(ValueError, match="closed date cannot also contain enabled windows"):
            compile_schedule({"exceptions": ordered})


def test_exception_count_and_clock_type_are_bounded_and_checked():
    with pytest.raises(ValueError, match="at most 1000"):
        compile_schedule({"exceptions": [{}] * 1001})
    with pytest.raises(ValueError, match="clock must be a datetime"):
        schedule_active({}, "2026-01-05T09:00")
    with pytest.raises(ValueError, match="supported local date range"):
        schedule_active({"timezone": "America/Los_Angeles"}, datetime.min.replace(tzinfo=UTC))
