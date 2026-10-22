"""Sealed native schedule evidence and offline day drafts; no network operations."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import secrets
import threading
from collections import OrderedDict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from bacpypes3.basetypes import DailySchedule, Reliability, TimeValue
from bacpypes3.constructeddata import Array
from bacpypes3.object import DeviceObject, ScheduleObject
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import (
    Boolean,
    Double,
    Enumerated,
    Integer,
    Null,
    ObjectIdentifier,
    PropertyIdentifier,
    Real,
    TagList,
    Time,
    Unsigned,
)
from pydantic import Field, field_validator

from .file_access import file_lock, open_regular, regular_file, storage_profile, sync_directory
from .models import StrictModel
from .property_evidence import native_value
from .schedule_inventory import MAX_REPORT_BYTES
from .schedule_inventory import PROFILE as INVENTORY_PROFILE

CAPTURE_PROFILE = "native-calendar-schedule-capture/1"
DRAFT_PROFILE = "native-schedule-weekly-day-draft/1"
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024
MAX_CAPTURES, MAX_STORAGE, MAX_REVIEWS = 32, 64 * 1024 * 1024, 16
MAX_NAMESPACE_ENTRIES = 128
CONTEXT = (
    "present-value",
    "effective-period",
    "schedule-default",
    "priority-for-writing",
    "list-of-object-property-references",
    "status-flags",
    "reliability",
    "out-of-service",
)
UNCHANGED = (*CONTEXT, "exception-schedule")
PRIMITIVES = {
    "Null": Null,
    "Boolean": Boolean,
    "Unsigned": Unsigned,
    "Integer": Integer,
    "Enumerated": Enumerated,
    "Real": Real,
    "Double": Double,
}
SCOPE = (
    "Offline native evidence library and one weekly-day draft. Captures preserve sequential "
    "observations and source claims, not an authenticated/coherent controller backup. "
    "No queries on save/import/reopen/review, native writes, target/default/priority changes, "
    "schedule evaluation, inferred timezone, CAF generation or physical acceptance."
)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


RULES = {
    "id": DRAFT_PROFILE,
    "inventory_profile": INVENTORY_PROFILE,
    "stack": "bacpypes3/0.0.110",
    "selection": "One existing Schedule17 weekly-schedule index1..7, no write APDU.",
    "evidence": "Exact Device/object identity and decoded context3 tags; complete7days and0..32exceptions.",
    "datatype": "Supported non-Null Schedule_Default; all observed time/present values same datatype or Null.",
    "time": "At most32 strictly increasing specific TimeValues, fields0..23/59/59/99.",
    "integer": "Canonical decimal signed32 Integer or unsigned32 Unsigned/Enumerated.",
    "floating": "Finite decimal/exponent text to binary64 then Real32/Double64; refuse nonzero underflow and expose rounding.",
    "proof": "New DailySchedule native encode/decode exhausts tags and reencodes identically; old exact bytes must normalize identically.",
    "meaning": "Offline encoding review, not a native evaluator, write approval or physical acceptance.",
    "reviewed_sources": {
        "bacpypes3/basetypes.py": "ca1652ab4eae55ba0f66b424e0652f25802fcac6ffab2d077b38739400ee454d",
        "bacpypes3/object.py": "34f0ee7ec233a96435b4bd97f9692d726d54a8a175f6d04fe1a662198c174de9",
        "bacpypes3/primitivedata.py": "6cdbcfb6c05ea4ece9a877ead6cdd0c08ef2e12ce8b37677e283c601fbf6a39d",
        "CCT18/LIT-12011147/PDF235-236,247-248": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
        "SCT19/LIT-12011964/PDF328-329": "a8bd468067d46ad3509fdd40c73dcef967a8a7d517b43c5bd4561af45fa794d4",
    },
}
RULES_SHA256 = digest(RULES)


def strict_json(raw, limit):
    if len(raw) > limit:
        raise ValueError("Native schedule document exceeds its byte bound.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate native schedule document field.")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("Native schedule documents require finite JSON values.")

    def floating(text):
        value = float(text)
        try:
            requested = Decimal(text)
        except InvalidOperation:
            invalid(text)
        if not math.isfinite(value) or (requested != 0 and value == 0):
            invalid(text)
        return value

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=invalid,
            parse_float=floating,
        )
        pending = [(value, 0)]
        count = 0
        while pending:
            item, depth = pending.pop()
            count += 1
            if depth > 64 or count > 100000:
                raise ValueError("Native schedule document exceeds its structure bound.")
            if isinstance(item, dict):
                for key in item:
                    key.encode("utf-8", errors="strict")
                pending.extend((v, depth + 1) for v in item.values())
            elif isinstance(item, list):
                pending.extend((v, depth + 1) for v in item)
            elif isinstance(item, str):
                item.encode("utf-8", errors="strict")
        return value
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("Native schedule document requires bounded valid UTF-8 JSON.") from exc


def identifier(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Select an exact native schedule content identifier.")
    return value


def source_report(raw):
    report = strict_json(raw, MAX_REPORT_BYTES)
    if (
        type(report) is not dict
        or report.get("profile") != INVENTORY_PROFILE
        or type(report.get("id")) is not str
        or not re.fullmatch(r"[0-9a-f]{32}", report["id"])
        or type(report.get("target")) is not dict
        or type(report.get("objects")) is not list
        or len(report["objects"]) > 16
        or any(type(obj) is not dict for obj in report["objects"])
        or type(report.get("identity_verified")) is not bool
        or type(report.get("complete")) is not bool
        or type(report.get("status")) is not str
        or type(report.get("started_at")) is not str
        or type(report.get("finished_at")) is not str
    ):
        raise ValueError("Unknown or invalid native Calendar/Schedule inventory source profile.")
    seal = report.get("evidence_sha256")
    if type(seal) is not str or seal != digest(
        {k: v for k, v in report.items() if k != "evidence_sha256"}
    ):
        raise ValueError("Native inventory evidence seal does not match its source.")
    target = report["target"]
    try:
        if type(target.get("device")) is not str:
            raise ValueError("Device identity must use exact canonical text.")
        device = ObjectIdentifier(target.get("device"))
        if str(device) != target["device"] or int(device[0]) != 8 or not 0 <= device[1] <= 4194302:
            raise ValueError("Invalid Device identity.")
    except (TypeError, ValueError) as exc:
        raise ValueError("Native schedule source requires an explicit Device identity.") from exc
    return report


def decoded_row(row, obj, prop, index=None):
    try:
        return _decoded_row(row, obj, prop, index)
    except ValueError as exc:
        raise ValueError(str(exc)[:400] or "Invalid native property evidence.") from exc
    except Exception as exc:
        raise ValueError(f"Native {prop} evidence cannot be decoded by this profile.") from exc


def _decoded_row(row, obj, prop, index):
    if (
        type(row) is not dict
        or row.get("status") != "ok"
        or row.get("object") != obj
        or row.get("property") != prop
        or type(row.get("property_id")) is not int
        or row["property_id"] != int(PropertyIdentifier(prop))
        or row.get("array_index") != index
        or (index is not None and type(row.get("array_index")) is not int)
        or row.get("nested_decode_errors") != []
    ):
        raise ValueError(f"Complete native {prop} evidence is required.")
    evidence = row.get("encoded_value", {})
    text = evidence.get("hex")
    if type(text) is not str or len(text) > 32768 or not re.fullmatch(r"(?:[0-9a-f]{2})*", text):
        raise ValueError(f"Native {prop} encoded evidence is unavailable or oversized.")
    raw = bytes.fromhex(text)
    if (
        evidence.get("complete") is not True
        or type(evidence.get("bytes")) is not int
        or evidence["bytes"] != len(raw)
        or evidence.get("sha256") != hashlib.sha256(raw).hexdigest()
    ):
        raise ValueError(f"Native {prop} tag evidence is incomplete or changed.")
    tags = TagList.decode(PDU(raw))
    if len(tags) > 4096 or len(tags) < 2:
        raise ValueError(f"Native {prop} tag structure is outside the profile.")
    stack = []
    for tag in tags:
        if tag.tag_class == 2:
            stack.append(tag.tag_number)
            if len(stack) > 16:
                raise ValueError("Native schedule tags exceed their nesting bound.")
        elif tag.tag_class == 3:
            if not stack or stack.pop() != tag.tag_number:
                raise ValueError("Native schedule tags are unbalanced.")
    if stack or (
        tags[0].tag_class,
        tags[0].tag_number,
        tags[-1].tag_class,
        tags[-1].tag_number,
    ) != (2, 3, 3, 3):
        raise ValueError("Native schedule property context3 envelope is invalid.")
    object_type = int(ObjectIdentifier(obj)[0])
    cls = DeviceObject if object_type == 8 else ScheduleObject
    datatype = cls.get_property_type(prop)
    if datatype is None:
        raise ValueError("Native schedule property type is unsupported.")
    if issubclass(datatype, Array) and index is not None:
        datatype = Unsigned if index == 0 else datatype._subtype
    remaining = TagList(list(tags)[1:-1])
    native = datatype.decode(remaining)
    issues = []
    representation = native_value(native, issues)
    if len(remaining) or issues or encoded(representation) != encoded(row.get("value")):
        raise ValueError(f"Native {prop} decoded value differs from its exact tag evidence.")
    return native, raw


class CaptureAction(StrictModel):
    id: str = Field(pattern=r"^[0-9a-f]{64}$")


class NativeTransition(StrictModel):
    time: list[int] = Field(min_length=4, max_length=4)
    native_type: Literal["Null", "Boolean", "Unsigned", "Integer", "Enumerated", "Real", "Double"]
    value_text: str = Field(min_length=1, max_length=256)

    @field_validator("time", mode="before")
    @classmethod
    def specific_time(cls, value):
        if (
            type(value) is not list
            or len(value) != 4
            or any(
                type(v) is not int or not 0 <= v <= high
                for v, high in zip(value, (23, 59, 59, 99), strict=True)
            )
        ):
            raise ValueError("Use specific native hour/minute/second/hundredth fields.")
        return value


class WeeklyDayDraft(StrictModel):
    capture_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    object_id: str = Field(min_length=1, max_length=80)
    day: int = Field(ge=1, le=7, strict=True)
    transitions: list[NativeTransition] = Field(max_length=32)

    @field_validator("object_id")
    @classmethod
    def schedule_object(cls, value):
        obj = ObjectIdentifier(value)
        if int(obj[0]) != 17 or not 0 <= obj[1] <= 4194302:
            raise ValueError("Select one existing standard Schedule object.")
        return str(obj)


def primitive(row):
    kind, text = row.native_type, row.value_text
    if kind == "Null":
        if text != "null":
            raise ValueError("Native Null text must be exactly null.")
        value = Null(())
    elif kind == "Boolean":
        if text not in ("true", "false"):
            raise ValueError("Native Boolean text must be true or false.")
        value = Boolean(text == "true")
    elif kind in ("Unsigned", "Integer", "Enumerated"):
        if not re.fullmatch(r"0|-?[1-9][0-9]*", text):
            raise ValueError("Native integer text must be canonical decimal whole-number text.")
        number = int(text)
        low, high = (-2147483648, 2147483647) if kind == "Integer" else (0, 4294967295)
        if not low <= number <= high:
            raise ValueError("Native integer value exceeds this explicit32-bit draft profile.")
        value = PRIMITIVES[kind](number)
    else:
        if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", text):
            raise ValueError("Native floating value requires finite JSON-number text.")
        try:
            requested = Decimal(text)
            number = float(text)
            if (
                not requested.is_finite()
                or not math.isfinite(number)
                or (requested != 0 and number == 0)
            ):
                raise ValueError("Native floating text exceeds the finite binary64 profile.")
            value = PRIMITIVES[kind](number)
            wire = value.encode()
            decoded = PRIMITIVES[kind].decode(TagList(list(wire)))
            if not math.isfinite(float(decoded)) or (requested != 0 and decoded == 0):
                raise ValueError("Native floating value overflows/underflows its wire datatype.")
        except (OverflowError, InvalidOperation) as exc:
            raise ValueError("Native floating value exceeds its wire datatype.") from exc
    return value


def native_text(value):
    """Lossless operator seed for the supported, decoded primitive profile."""
    name = type(value).__name__
    if name == "Null":
        return "null"
    if name == "Boolean":
        return "true" if value else "false"
    if name in ("Real", "Double"):
        return repr(float(value))
    return str(int(value))


def date_pattern(value):
    year, month, day, weekday = value
    if not (
        0 <= year <= 255
        and (1 <= month <= 14 or month == 255)
        and (1 <= day <= 34 or day == 255)
        and (1 <= weekday <= 7 or weekday == 255)
    ):
        raise ValueError("Captured date contains unknown/invalid native pattern fields.")
    if month <= 12 and day <= 31:
        try:
            actual = datetime(year + 1900 if year != 255 else 2000, month, day)
        except ValueError as exc:
            raise ValueError("Captured native date is not a possible calendar date.") from exc
        if year != 255 and weekday != 255 and weekday != actual.isoweekday():
            raise ValueError("Captured native date/weekday fields conflict.")


def date_range(value):
    date_pattern(value.startDate)
    date_pattern(value.endDate)
    start, end = tuple(value.startDate), tuple(value.endDate)
    if all(v != 255 for v in (*start[:3], *end[:3])) and (
        start[1] <= 12 and end[1] <= 12 and start[2] <= 31 and end[2] <= 31
    ):
        if start[:3] > end[:3]:
            raise ValueError("Captured native effective/date range is reversed.")


def exception_period(period):
    if period._choice == "calendarReference":
        if int(period.calendarReference[0]) != 6 or not 0 <= period.calendarReference[1] <= 4194302:
            raise ValueError("Captured exception reference is not a Calendar object.")
        return
    if period._choice != "calendarEntry":
        raise ValueError("Captured exception period choice is unsupported.")
    entry = period.calendarEntry
    if entry._choice == "date":
        date_pattern(entry.date)
    elif entry._choice == "dateRange":
        date_range(entry.dateRange)
    elif entry._choice == "weekNDay":
        month, week, weekday = entry.weekNDay
        if not (
            (1 <= month <= 14 or month == 255)
            and (1 <= week <= 6 or week == 255)
            and (1 <= weekday <= 7 or weekday == 255)
        ):
            raise ValueError("Captured WeekNDay contains unknown native pattern fields.")
    else:
        raise ValueError("Captured exception CalendarEntry choice is unsupported.")


class NativeScheduleLibrary:
    def __init__(self, directory, inventory=None):
        self.directory = Path(directory) / "native-schedule-captures"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.inventory = inventory
        self.reviews = OrderedDict()
        self.review_lock = threading.RLock()

    def _files(self):
        if self._storage_bytes() > MAX_STORAGE:
            raise ValueError("Native schedule capture storage exceeds its bounded profile.")
        paths = []
        for path in self.directory.glob("capture-*.json"):
            info = path.lstat()
            identifier(path.stem.removeprefix("capture-"))
            if not regular_file(info):
                raise ValueError("Native schedule library contains a nonregular capture file.")
            paths.append(path)
            if len(paths) > MAX_CAPTURES:
                raise ValueError("Native schedule capture storage exceeds its bounded profile.")
        return sorted(paths)

    def _storage_bytes(self):
        # Count abandoned temporary files too: a crash must not bypass quota.
        # Unexpected entries are never deleted or followed to reclaim capacity.
        total = 0
        with os.scandir(self.directory) as entries:
            for count, entry in enumerate(entries, 1):
                if count > MAX_NAMESPACE_ENTRIES:
                    raise ValueError("Native schedule storage exceeds its namespace entry bound.")
                try:
                    information = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue  # another completed writer retired a temporary name
                if not regular_file(information):
                    raise ValueError(
                        "Native schedule storage contains a nonregular namespace entry."
                    )
                total += information.st_size
        return total

    @staticmethod
    def _archive(raw):
        wrapper = strict_json(raw, MAX_ARCHIVE_BYTES)
        if (
            type(wrapper) is not dict
            or set(wrapper)
            != {"format", "id", "source_sha256", "source_json", "ingest", "archive_sha256"}
            or wrapper.get("format") != CAPTURE_PROFILE
            or type(wrapper.get("source_json")) is not str
            or type(wrapper.get("ingest")) is not dict
            or set(wrapper["ingest"])
            not in ({"kind", "at"}, {"kind", "at", "incoming_archive_sha256"})
            or wrapper["ingest"]["kind"] not in ("session", "imported")
            or type(wrapper["ingest"]["at"]) is not str
            or len(wrapper["ingest"]["at"]) > 64
        ):
            raise ValueError("Unknown or invalid native schedule capture archive profile.")
        if "incoming_archive_sha256" in wrapper["ingest"]:
            identifier(wrapper["ingest"]["incoming_archive_sha256"])
            if wrapper["ingest"]["kind"] != "imported":
                raise ValueError("Incoming archive metadata requires an imported capture.")
        source = wrapper["source_json"].encode()
        expected = hashlib.sha256(source).hexdigest()
        if (
            wrapper["id"] != expected
            or wrapper["source_sha256"] != expected
            or wrapper["archive_sha256"]
            != digest({k: v for k, v in wrapper.items() if k != "archive_sha256"})
        ):
            raise ValueError("Native schedule capture archive seal does not match.")
        return wrapper, source_report(source)

    def archive(self, id):
        id = identifier(id)
        try:
            fd = open_regular(self.directory / ("capture-" + id + ".json"))
        except FileNotFoundError as exc:
            raise ValueError("Native schedule capture is unavailable.") from exc
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not regular_file(info) or info.st_size > MAX_ARCHIVE_BYTES:
                raise ValueError("Native schedule capture must be a bounded regular file.")
            raw = stream.read(MAX_ARCHIVE_BYTES + 1)
        wrapper, _ = self._archive(raw)
        if wrapper["id"] != id:
            raise ValueError("Native schedule capture identity differs from its filename.")
        return raw

    def _store(self, source, origin, incoming_archive_sha256=None):
        source_report(source)
        if origin not in ("session", "imported"):
            raise ValueError("Unknown native schedule capture origin.")
        if incoming_archive_sha256 is not None and origin != "imported":
            raise ValueError("Incoming archive metadata requires an imported capture.")
        id = hashlib.sha256(source).hexdigest()
        wrapper = {
            "format": CAPTURE_PROFILE,
            "id": id,
            "source_sha256": id,
            "source_json": source.decode(),
            "ingest": {"kind": origin, "at": datetime.now(UTC).isoformat()},
        }
        if incoming_archive_sha256 is not None:
            wrapper["ingest"]["incoming_archive_sha256"] = identifier(incoming_archive_sha256)
        wrapper["archive_sha256"] = digest(wrapper)
        raw = encoded(wrapper)
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise ValueError("Native schedule archive exceeds its4MiB bound.")
        with file_lock(
            self.directory / ".capture.lock",
            timeout=2,
            busy="Native schedule capture storage is busy.",
        ):
            path = self.directory / ("capture-" + id + ".json")
            if path.exists() or path.is_symlink():
                old, _ = self._archive(self.archive(id))
                if old["source_json"].encode() != source:
                    raise ValueError(
                        "Existing native schedule capture has conflicting source bytes."
                    )
                return self.detail(id)
            paths = self._files()
            if len(paths) >= MAX_CAPTURES or self._storage_bytes() + len(raw) > MAX_STORAGE:
                raise ValueError(
                    "Native schedule capture capacity reached; no evidence was overwritten."
                )
            temporary = self.directory / ("." + secrets.token_hex(16) + ".tmp")
            fd = open_regular(temporary, writable=True, create=True, exclusive=True)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, path)
                sync_directory(self.directory)
            finally:
                temporary.unlink(missing_ok=True)
        return self.detail(id)

    def save(self, report_id):
        if self.inventory is None:
            raise ValueError("No session inventory is available; import an existing capture.")
        return self._store(encoded(self.inventory.detail(report_id)), "session")

    def import_capture(self, raw):
        wrapper, _ = self._archive(raw)
        incoming = hashlib.sha256(raw).hexdigest()
        detail = self._store(wrapper["source_json"].encode(), "imported", incoming)
        return {
            **detail,
            "import_provenance": {
                "incoming_archive_sha256": incoming,
                "stored_archive_sha256": hashlib.sha256(self.archive(detail["id"])).hexdigest(),
                "meaning": "Original inventory source bytes retained; a new local archive wrapper may differ. Existing captures deduplicate without rewriting ingest metadata.",
            },
        }

    def source(self, id):
        wrapper, _ = self._archive(self.archive(id))
        return wrapper["source_json"].encode()

    @staticmethod
    def _weekly_context(report, object_id):
        try:
            return NativeScheduleLibrary._decoded_weekly_context(report, object_id)
        except ValueError as exc:
            raise ValueError(str(exc)[:400] or "Invalid native schedule context.") from exc
        except Exception as exc:
            raise ValueError(
                "Captured Schedule context cannot be interpreted by this draft profile."
            ) from exc

    @staticmethod
    def _decoded_weekly_context(report, object_id):
        if report.get("identity_verified") is not True:
            raise ValueError("Captured Device identity was not verified.")
        device = report["target"].get("device")
        if int(ObjectIdentifier(device)[0]) != 8:
            raise ValueError("Captured target is not a Device identity.")
        actual, _ = decoded_row(report.get("device_identity"), device, "object-identifier")
        if actual != ObjectIdentifier(device):
            raise ValueError("Captured Device tag identity differs from selection.")
        matches = [obj for obj in report["objects"] if obj.get("object") == object_id]
        if len(matches) != 1 or matches[0].get("identity_verified") is not True:
            raise ValueError("Select exactly one identity-verified captured Schedule.")
        item = matches[0]
        props = item.get("properties", {})
        actual, _ = decoded_row(props.get("object-identifier"), object_id, "object-identifier")
        if actual != ObjectIdentifier(object_id):
            raise ValueError("Captured Schedule tag identity differs from selection.")
        context = {prop: decoded_row(props.get(prop), object_id, prop)[0] for prop in CONTEXT}
        date_range(context["effective-period"])
        if int(context["reliability"]) not in set(Reliability._enum_map.values()):
            raise ValueError("Captured Reliability enum is unknown; draft interpretation deferred.")
        if len(context["status-flags"]) != 4:
            raise ValueError("Captured StatusFlags is not the standard four-bit context.")
        weekly = props.get("weekly-schedule", {})
        count, _ = decoded_row(weekly.get("count_read"), object_id, "weekly-schedule", 0)
        if (
            count != 7
            or weekly.get("complete") is not True
            or weekly.get("status") != "ok"
            or len(weekly.get("elements", [])) != 7
        ):
            raise ValueError("Complete fixed7-day native weekly array evidence is required.")
        days = [
            decoded_row(row, object_id, "weekly-schedule", i)[0]
            for i, row in enumerate(weekly["elements"], 1)
        ]
        exceptions = props.get("exception-schedule", {})
        exception_count, _ = decoded_row(
            exceptions.get("count_read"), object_id, "exception-schedule", 0
        )
        if (
            not 0 <= int(exception_count) <= 32
            or exceptions.get("complete") is not True
            or exceptions.get("status") != "ok"
            or len(exceptions.get("elements", [])) != exception_count
        ):
            raise ValueError("Complete bounded native exception array evidence is required.")
        events = [
            decoded_row(row, object_id, "exception-schedule", i)[0]
            for i, row in enumerate(exceptions["elements"], 1)
        ]
        for event in events:
            exception_period(event.period)
            if not 1 <= int(event.eventPriority) <= 16:
                raise ValueError("Captured exception event priority is outside1..16.")
        sequences = [day.daySchedule for day in days] + [event.listOfTimeValues for event in events]
        for sequence in sequences:
            if len(sequence) > 32:
                raise ValueError("Captured transition sequence exceeds the32-transition profile.")
            previous = None
            for transition in sequence:
                clock = list(transition.time)
                NativeTransition.specific_time(clock)
                if previous is not None and tuple(clock) <= previous:
                    raise ValueError("Captured daily times are duplicate/unsorted.")
                previous = tuple(clock)
        default = context["schedule-default"].get_value()
        observed = type(default).__name__
        if observed not in PRIMITIVES or observed == "Null":
            raise ValueError(
                "A supported non-Null Schedule_Default is required; Null/default-release interpretation is deferred."
            )
        for value in [
            default,
            context["present-value"].get_value(),
            *(entry.value.get_value() for sequence in sequences for entry in sequence),
        ]:
            name = type(value).__name__
            if name not in PRIMITIVES:
                raise ValueError(
                    "Captured schedule uses an unsupported/opaque native primitive type."
                )
            if name in ("Real", "Double") and not math.isfinite(float(value)):
                raise ValueError("Captured native floating value is nonfinite.")
            if name in ("Integer", "Unsigned", "Enumerated"):
                low, high = (-2147483648, 2147483647) if name == "Integer" else (0, 4294967295)
                if not low <= int(value) <= high:
                    raise ValueError("Captured integer exceeds the explicit32-bit draft profile.")
            if name not in (observed, "Null"):
                raise ValueError(
                    "Captured weekly/exception/present value datatype conflicts with Schedule_Default."
                )
        if not 1 <= int(context["priority-for-writing"]) <= 16:
            raise ValueError("Captured schedule writing priority is outside1..16.")
        return props, days, observed

    def detail(self, id):
        wrapper, report = self._archive(self.archive(id))
        objects = []
        for item in report["objects"]:
            name = item.get("object", "")
            try:
                if int(ObjectIdentifier(name)[0]) != 17:
                    continue
                props, days, observed = self._weekly_context(report, name)
                seeds = []
                for index, day in enumerate(days, 1):
                    _, raw = decoded_row(
                        props["weekly-schedule"]["elements"][index - 1],
                        name,
                        "weekly-schedule",
                        index,
                    )
                    seeds.append(
                        {
                            "day": index,
                            "encoded_hex": raw.hex(),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "encoding": "Captured property context3 envelope, not a write APDU",
                            "transitions": [
                                {
                                    "time": list(tv.time),
                                    "native_type": type(tv.value.get_value()).__name__,
                                    "value_text": native_text(tv.value.get_value()),
                                }
                                for tv in day.daySchedule
                            ],
                        }
                    )
                objects.append(
                    {
                        "object": name,
                        "eligible": True,
                        "native_type": observed,
                        "issues": [],
                        "days": seeds,
                    }
                )
            except Exception as exc:
                objects.append(
                    {
                        "object": name,
                        "eligible": False,
                        "issues": [str(exc)[:400] or type(exc).__name__],
                    }
                )
        summary = {
            "id": wrapper["id"],
            "source_report_id": report["id"],
            "source_sha256": wrapper["source_sha256"],
            "evidence_sha256": report["evidence_sha256"],
            "target": report["target"],
            "status": report["status"],
            "started_at": report["started_at"],
            "finished_at": report["finished_at"],
            "origin": wrapper["ingest"]["kind"],
            "ingest": wrapper["ingest"],
            "objects": objects,
        }
        return {
            **summary,
            "profile": CAPTURE_PROFILE,
            "draft_profile": DRAFT_PROFILE,
            "rules_sha256": RULES_SHA256,
            "report": report,
            "scope": SCOPE,
            "integrity": "Self-seal integrity verified; imported/source claims are not authenticated manufacturer provenance.",
        }

    def status(self):
        captures = [
            {
                k: v
                for k, v in self.detail(p.stem.removeprefix("capture-")).items()
                if k not in ("report",)
            }
            for p in self._files()
        ]
        for capture in captures:
            capture["objects"] = [
                {key: value for key, value in item.items() if key != "days"}
                for item in capture["objects"]
            ]
        return {
            "profile": CAPTURE_PROFILE,
            "draft_profile": DRAFT_PROFILE,
            "rules_sha256": RULES_SHA256,
            "rules": copy.deepcopy(RULES),
            "scope": SCOPE,
            "read_only": True,
            "auto_query": False,
            "field_writes": False,
            "limits": {
                "captures": MAX_CAPTURES,
                "storage_bytes": MAX_STORAGE,
                "source_bytes": MAX_REPORT_BYTES,
                "archive_bytes": MAX_ARCHIVE_BYTES,
                "transitions": 32,
                "reviews": MAX_REVIEWS,
                "namespace_entries": MAX_NAMESPACE_ENTRIES,
            },
            "storage": {
                **storage_profile(),
                "used_bytes": self._storage_bytes(),
                "pressure_policy": "All namespace files, including abandoned temporary files, count. No automatic deletion/overwrite/eviction.",
            },
            "draft_policy": {
                "primitives": list(PRIMITIVES),
                "default": "Supported non-Null Schedule_Default determines the exact native datatype; every captured weekly/exception/present value must match or be Null.",
                "null": "Explicit Null TimeValue encoding only; target release/fallback behavior is unverified.",
                "context": "Complete fixed seven-day and bounded exception arrays, source identities and effective-period/context tags are required. No schedule evaluation or referenced-object queries.",
                "retention": "Captures persist immutably. Drafts retain16 session reviews; export/import a review with its source capture to reopen after restart.",
            },
            "captures": captures,
        }

    def review(self, **arguments):
        request = WeeklyDayDraft(**arguments)
        return self._review(request, retain=True)

    def _review(self, request, *, retain):
        report = source_report(self.source(request.capture_id))
        props, days, observed = self._weekly_context(report, request.object_id)
        previous = None
        transitions, projections = [], []
        for row in request.transitions:
            clock = tuple(row.time)
            if previous is not None and clock <= previous:
                raise ValueError(
                    "Native daily transitions must be strictly increasing; duplicate/unsorted times are refused."
                )
            previous = clock
            if row.native_type not in (observed, "Null"):
                raise ValueError(
                    "Draft primitive type differs from the observed native schedule type."
                )
            value = primitive(row)
            tv = TimeValue(time=Time(clock), value=value)
            transitions.append(tv)
            tags = value.encode()
            wire = PRIMITIVES[row.native_type].decode(TagList(list(tags)))
            floating = row.native_type in ("Real", "Double")
            projections.append(
                {
                    **row.model_dump(),
                    "wire": native_value(wire, []),
                    "wire_encoded_hex": bytes(tags.encode().pduData).hex(),
                    "wire_encoding": "BACpypes3 native application-tag encoding",
                    "binary64_parse_hex": float(row.value_text).hex() if floating else None,
                    "wire_value_text": native_text(wire),
                    "decimal_text_changed": Decimal(row.value_text)
                    != Decimal.from_float(float(wire))
                    if floating
                    else False,
                    "binary64_to_wire_changed": float(row.value_text).hex() != float(wire).hex()
                    if floating
                    else False,
                    "precision": "Floating text parses to binary64 then declared wire type; inspect requested text and wire value. Native arithmetic/release behavior is unverified.",
                }
            )
        daily = DailySchedule(daySchedule=transitions)
        raw = bytes(daily.encode().encode().pduData)
        tags = TagList.decode(PDU(raw))
        restored = DailySchedule.decode(tags)
        if tags or bytes(restored.encode().encode().pduData) != raw:
            raise ValueError("Native daily encode/decode proof failed.")
        old = days[request.day - 1]
        _, old_property_raw = decoded_row(
            props["weekly-schedule"]["elements"][request.day - 1],
            request.object_id,
            "weekly-schedule",
            request.day,
        )
        old_raw = old_property_raw[1:-1]
        if bytes(old.encode().encode().pduData) != old_raw:
            raise ValueError("Captured daily tags require unsupported encoding normalization.")
        review = {
            "format": DRAFT_PROFILE,
            "profile": DRAFT_PROFILE,
            "rules_sha256": RULES_SHA256,
            "scope": SCOPE,
            "request": request.model_dump(),
            "source": {
                "capture_id": request.capture_id,
                "source_sha256": request.capture_id,
                "evidence_sha256": report["evidence_sha256"],
                "target": report["target"],
                "object": request.object_id,
                "day": request.day,
                "observed_native_type": observed,
                "context_sha256": digest({key: props[key] for key in UNCHANGED}),
                "weekly_evidence_sha256": digest(props["weekly-schedule"]),
            },
            "old": {
                "encoded_hex": old_raw.hex(),
                "sha256": hashlib.sha256(old_raw).hexdigest(),
                "value": native_value(old, []),
            },
            "new": {
                "encoded_hex": raw.hex(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "value": native_value(restored, []),
                "transitions": projections,
                "roundtrip_tags_exhausted": True,
            },
            "diff": {
                "changed": old_raw != raw,
                "old_transition_count": len(old.daySchedule),
                "new_transition_count": len(transitions),
                "property": "weekly-schedule",
                "array_index": request.day,
                "unchanged_context": list(UNCHANGED),
                "other_days_changed": False,
            },
            "interpretation": {
                "datatype_basis": "Exact captured non-Null Schedule_Default and every weekly/exception/present value; Null is an explicit wire tag only.",
                "null_behavior": "Native Null encodes a null TimeValue. Target release/fallback behavior is not evaluated or verified.",
                "context": "Effective period/exception shapes are checked and retained unchanged; referenced calendars, output targets, timezone and native evaluation are not queried or simulated.",
            },
            "field_writes": False,
        }
        review["id"] = digest(review)
        raw_review = encoded(review)
        if len(raw_review) > 256 * 1024:
            raise ValueError("Native weekly draft review exceeds its256KiB bound.")
        if retain:
            self._retain(review["id"], raw_review)
        return copy.deepcopy(review)

    def _retain(self, id, raw):
        with self.review_lock:
            self.reviews[id] = raw
            while len(self.reviews) > MAX_REVIEWS:
                self.reviews.popitem(last=False)

    def export_review(self, id):
        id = identifier(id)
        with self.review_lock:
            if id not in self.reviews:
                raise ValueError("Native draft review is not retained; review/import it again.")
            return self.reviews[id]

    def import_review(self, raw):
        body = strict_json(raw, 256 * 1024)
        if (
            type(body) is not dict
            or body.get("format") != DRAFT_PROFILE
            or body.get("profile") != DRAFT_PROFILE
            or type(body.get("request")) is not dict
            or body.get("id") != digest({k: v for k, v in body.items() if k != "id"})
        ):
            raise ValueError("Native weekly draft profile/seal is unknown or changed.")
        result = self._review(WeeklyDayDraft(**body["request"]), retain=False)
        if encoded(body) != encoded(result):
            raise ValueError("Imported draft differs from its source/native encoding proof.")
        self._retain(result["id"], encoded(result))
        return result
