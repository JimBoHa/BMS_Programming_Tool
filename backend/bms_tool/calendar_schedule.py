"""Weekly wall-clock schedules with explicit time zones and dated exceptions.

A dated exception replaces the whole local calendar day, including any overnight
period that would otherwise carry in from the preceding day. Enabled exception
windows may carry into the following day only when that day has no exception.
Multiple enabled windows on one date form a union; their list order has no effect.
A disabled exception closes its whole date and cannot be combined with windows.

Periods include their start and exclude their end. Equal start and end times are
empty, preserving the original Schedule block's behavior. An overnight period
belongs to its start date. Named zones evaluate real instants: skipped spring
wall-clock minutes never occur and repeated autumn minutes run in both folds.
An empty zone preserves the supplied clock's fields, including naive clocks.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from types import MappingProxyType
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_DEFAULTS = {
    "start": "08:00",
    "end": "18:00",
    "days": [0, 1, 2, 3, 4],
    "timezone": "",
    "exceptions": [],
}
_MAX_EXCEPTIONS = 1000
_TIME_PATTERN = re.compile(r"[0-9]{2}:[0-9]{2}\Z")
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


def _minute(value: object, field: str) -> int:
    if not isinstance(value, str) or not _TIME_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must use HH:MM (00:00 through 23:59)")
    hour, minute = (int(part) for part in value.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError(f"{field} must use HH:MM (00:00 through 23:59)")
    return hour * 60 + minute


@lru_cache(maxsize=256)
def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"timezone {name!r} is not an available IANA time zone") from exc


@dataclass(frozen=True, slots=True)
class _Window:
    start: int
    end: int

    def active_on_start_date(self, minute: int) -> bool:
        if self.start <= self.end:
            return self.start <= minute < self.end
        return minute >= self.start

    def carries_into(self, minute: int) -> bool:
        return self.start > self.end and minute < self.end


@dataclass(frozen=True, slots=True)
class ScheduleCalendar:
    """Validated immutable schedule, suitable for retaining between scans."""

    start: int
    end: int
    days: frozenset[int]
    timezone: str
    exceptions: Mapping[date, tuple[_Window, ...]]
    zone: ZoneInfo | None = None

    def __deepcopy__(self, memo):
        # Compiled values are immutable. Runtime plans and native simulator
        # preflights copy Engines; mappingproxy itself cannot be deep-copied.
        return self

    def local_clock(self, clock: datetime) -> datetime:
        """Return the local wall clock used for all date and period decisions."""
        if not isinstance(clock, datetime):
            raise ValueError("schedule clock must be a datetime")
        if self.zone is None:
            return clock
        if clock.tzinfo is None or clock.utcoffset() is None:
            raise ValueError("a schedule with a timezone requires an aware clock")
        try:
            # Normalize through UTC even if clock already uses this zone. This
            # also resolves an explicitly constructed imaginary spring time.
            return clock.astimezone(UTC).astimezone(self.zone)
        except (OverflowError, ValueError) as exc:
            raise ValueError("schedule clock is outside the supported local date range") from exc

    def _windows(self, day: date) -> tuple[_Window, ...]:
        if day in self.exceptions:
            return self.exceptions[day]
        if day.weekday() in self.days:
            return (_Window(self.start, self.end),)
        return ()

    def active(self, clock: datetime) -> bool:
        """Evaluate a single instant without changing schedule or clock state."""
        local = self.local_clock(clock)
        today = local.date()
        minute = local.hour * 60 + local.minute
        if any(window.active_on_start_date(minute) for window in self._windows(today)):
            return True
        if today in self.exceptions or today == date.min:
            return False
        yesterday = today - timedelta(days=1)
        return any(window.carries_into(minute) for window in self._windows(yesterday))


def compile_schedule(params: Mapping[str, object]) -> ScheduleCalendar:
    """Validate Schedule block parameters and compile them without coercion.

    Optional new parameters preserve existing weekly behavior. Exception rows
    accept exactly ``date``, ``enabled`` (default true), ``start``, and ``end``.
    Enabled rows require both times. A false ``enabled`` row accepts only a date.
    Up to 1,000 rows are accepted so imported calendars remain bounded.
    """
    if not isinstance(params, Mapping):
        raise ValueError("schedule parameters must be an object")
    unknown = params.keys() - _DEFAULTS.keys()
    if unknown:
        raise ValueError("Unknown schedule parameters: " + ", ".join(sorted(map(str, unknown))))
    values = {**_DEFAULTS, **params}
    start = _minute(values["start"], "start")
    end = _minute(values["end"], "end")
    days = values["days"]
    if not isinstance(days, list) or any(type(day) is not int or not 0 <= day <= 6 for day in days):
        raise ValueError("days must be a list of integers 0..6 (Monday=0)")
    timezone = values["timezone"]
    if not isinstance(timezone, str) or len(timezone) > 128:
        raise ValueError("timezone must be an IANA time zone name or an empty string")
    zone = _zone(timezone) if timezone else None
    rows = values["exceptions"]
    if not isinstance(rows, list) or len(rows) > _MAX_EXCEPTIONS:
        raise ValueError(f"exceptions must be a list of at most {_MAX_EXCEPTIONS} rows")
    windows: dict[date, list[_Window]] = {}
    closed: set[date] = set()
    for index, row in enumerate(rows):
        field = f"exceptions[{index}]"
        if not isinstance(row, dict):
            raise ValueError(f"{field} must be an object")
        extra = row.keys() - {"date", "enabled", "start", "end"}
        if extra:
            raise ValueError(f"{field} has unknown fields: {', '.join(sorted(map(str, extra)))}")
        day_value = row.get("date")
        if not isinstance(day_value, str) or not _DATE_PATTERN.fullmatch(day_value):
            raise ValueError(f"{field}.date must be a valid YYYY-MM-DD date")
        try:
            day = date.fromisoformat(day_value)
        except ValueError as exc:
            raise ValueError(f"{field}.date must be a valid YYYY-MM-DD date") from exc
        enabled = row.get("enabled", True)
        if type(enabled) is not bool:
            raise ValueError(f"{field}.enabled must be boolean")
        if not enabled:
            if "start" in row or "end" in row:
                raise ValueError(f"{field}: a disabled date cannot contain times")
            if day in windows:
                raise ValueError(f"{field}: a closed date cannot also contain enabled windows")
            if day in closed:
                raise ValueError(f"{field}: duplicate closed date")
            closed.add(day)
            continue
        if day in closed:
            raise ValueError(f"{field}: a closed date cannot also contain enabled windows")
        window = _Window(
            _minute(row.get("start"), f"{field}.start"),
            _minute(row.get("end"), f"{field}.end"),
        )
        existing = windows.setdefault(day, [])
        if window in existing:
            raise ValueError(f"{field}: duplicate window for this date")
        existing.append(window)
    exceptions = {day: tuple(entries) for day, entries in windows.items()}
    exceptions.update({day: () for day in closed})
    return ScheduleCalendar(
        start, end, frozenset(days), timezone, MappingProxyType(exceptions), zone
    )


def validate_schedule_params(params: Mapping[str, object]) -> None:
    """Raise ValueError with a diagnostic-ready message for invalid parameters."""
    compile_schedule(params)


def schedule_active(params: Mapping[str, object], clock: datetime) -> bool:
    """Convenience evaluation; use compile_schedule once for repeated scans."""
    return compile_schedule(params).active(clock)
