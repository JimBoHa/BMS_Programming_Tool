"""Source-qualified Schedule exception values, local review and exact JSON copies."""

from __future__ import annotations

import asyncio
import copy
from typing import Annotated, Literal

from bacpypes3.basetypes import SpecialEvent, SpecialEventPeriod, TimeValue
from bacpypes3.object import ScheduleObject
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import ObjectIdentifier, TagList, Time
from fastapi import APIRouter, Response, UploadFile
from pydantic import Field, StrictInt, field_validator, model_validator

from .models import StrictModel
from .moi_identity import sha
from .native_calendar_drafts import RULES as CALENDAR_RULES
from .native_calendar_drafts import (
    CalendarDate,
    CalendarRange,
    CalendarWeek,
    native_entry,
    seed_entry,
)
from .native_calendar_write import qualify_calendar_ranges
from .native_schedule_library import (
    RULES as WEEKLY_RULES,
)
from .native_schedule_library import (
    CaptureAction,
    NativeScheduleLibrary,
    NativeTransition,
    decoded_row,
    digest,
    encoded,
    native_text,
    primitive,
    source_report,
    strict_json,
)

PROFILE = "native-schedule-exception-draft/1"
MAX_EVENTS, MAX_TRANSITIONS, MAX_DOCUMENT = 32, 32, 512 * 1024
EXCEPTION_ARRAY = ScheduleObject.get_property_type("exception-schedule")
SCOPE = (
    "Local whole Exception_Schedule value for one captured standard Schedule. "
    "Original source, weekly rows, defaults, priorities and references remain unchanged. "
    "Native typed encoding only: no field query/write, Calendar reference lookup, "
    "schedule evaluation, timezone inference, CAF generation or controller authority."
)
RULES = {
    "profile": PROFILE,
    "stack": "bacpypes3/0.0.110",
    "source": "Immutable original capture SHA, verified Device/Schedule native identities and complete bounded weekly/context/exception evidence. Separate exception WeekNDay1..9 qualification; original weekly/String eligibility stays unchanged.",
    "selection": "One existing Schedule17; complete ordered Exception_Schedule array, 0..32 SpecialEvents, 0..32 strictly increasing specific TimeValues per event.",
    "period": "Inline Calendar Date/DateRange/WeekNDay or canonical same-Device Calendar6 reference; no lookup or inferred match. Specific DateRange endpoints include the matching weekday, or are wholly unspecified.",
    "priority": "Strict integer EventPriority1..16, retained independently of captured Priority_For_Writing. Preserve event order and duplicates; no overlap or winning-event evaluation.",
    "datatype": "Captured non-Null Schedule_Default supplies the exact native datatype. Each proposed transition matches that type or explicit Null. Existing signed32/unsigned32/finite Real32/Double64 and strict UTF8/256 wire-byte rules apply.",
    "revision": "Captured or proposed WeekNDay7..9 records a minimum-known revision18 requirement in this separate exception domain; no current target revision is queried or inferred. Older weekly/String domains retain their original WeekNDay qualification.",
    "proof": "Every old SpecialEvent context3 value and the complete array re-encode byte-identically. New whole-array native decode exhausts tags and re-encodes identically; normalized primitives expose exact native types/text/tags.",
    "authority": "Stateless local review only. Export regenerates exact source/draft proof and expected ID; import reproves the entire body. No review eviction, transfer plan, service APDU or write token.",
    "integrity": "Capture self-seals and source claims do not establish authenticated manufacturer provenance or a coherent current controller state.",
    "reviewed_sources": {
        **copy.deepcopy(WEEKLY_RULES["reviewed_sources"]),
        **copy.deepcopy(CALENDAR_RULES["reviewed_sources"]),
        "ASHRAE135-2008ac.pdf": "5debdb31e0cd67de6f5b5876edc04abda552ba355fbda8bfe48448e20ac6e24c",
    },
}
RULES_SHA256 = digest(RULES)


class CalendarReference(StrictModel):
    kind: Literal["calendarReference"]
    object_id: str = Field(min_length=1, max_length=80, strict=True)

    @field_validator("object_id")
    @classmethod
    def canonical(cls, value):
        obj = ObjectIdentifier(value)
        if str(obj) != value or int(obj[0]) != 6 or not 0 <= obj[1] <= 4194302:
            raise ValueError("Use a canonical Calendar object identifier.")
        return value


Period = Annotated[
    CalendarDate | CalendarRange | CalendarWeek | CalendarReference,
    Field(discriminator="kind"),
]


class ExceptionEvent(StrictModel):
    period: Period
    priority: StrictInt = Field(ge=1, le=16)
    transitions: list[NativeTransition] = Field(max_length=MAX_TRANSITIONS)

    @model_validator(mode="after")
    def specific_range(self):
        if self.period.kind == "dateRange":
            qualify_calendar_ranges([self.period.model_dump()])
        return self


class ExceptionDraft(StrictModel):
    capture_id: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    object_id: str = Field(min_length=1, max_length=80, strict=True)
    events: list[ExceptionEvent] = Field(max_length=MAX_EVENTS)

    @field_validator("object_id")
    @classmethod
    def schedule(cls, value):
        obj = ObjectIdentifier(value)
        if str(obj) != value or int(obj[0]) != 17 or not 0 <= obj[1] <= 4194302:
            raise ValueError("Use one canonical existing standard Schedule object identifier.")
        return value


class ExceptionExport(StrictModel):
    draft: ExceptionDraft
    expected_review_id: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)


def envelope():
    return {
        "profile": PROFILE,
        "rules_sha256": RULES_SHA256,
        "scope": SCOPE,
        "field_writes": False,
        "controller_queries": False,
        "capture_mutations": False,
    }


def seed_event(event):
    if event.period._choice == "calendarReference":
        period = {"kind": "calendarReference", "object_id": str(event.period.calendarReference)}
    else:
        period = seed_entry(event.period.calendarEntry)
    return {
        "period": period,
        "priority": int(event.eventPriority),
        "transitions": [
            {
                "time": list(row.time),
                "native_type": type(row.value.get_value()).__name__,
                "value_text": native_text(row.value.get_value()),
            }
            for row in event.listOfTimeValues
        ],
    }


def minimum_revision(events):
    return (
        18
        if any(
            event["period"]["kind"] == "weekNDay" and 7 <= event["period"]["fields"][1] <= 9
            for event in events
        )
        else None
    )


class NativeScheduleExceptions:
    def __init__(self, library):
        self.library = library

    @staticmethod
    def _context(report, object_id):
        # Reuse strict observed-default/UTF8/context evidence. Only this new
        # exception domain opts into separately qualified modern week patterns.
        ExceptionDraft.schedule(object_id)
        props, _, observed = NativeScheduleLibrary._weekly_context(
            report, object_id, exception_week_limit=9
        )
        rows = props["exception-schedule"]["elements"]
        events, raw_parts = [], []
        for index, row in enumerate(rows, 1):
            event, raw = decoded_row(row, object_id, "exception-schedule", index)
            if bytes(event.encode().encode().pduData) != raw[1:-1]:
                raise ValueError("Captured exception requires unsupported native normalization.")
            events.append(event)
            raw_parts.append(raw[1:-1])
        value = EXCEPTION_ARRAY(events)
        original = b"".join(raw_parts)
        if bytes(value.encode().encode().pduData) != original:
            raise ValueError("Captured exception array does not retain its exact native entries.")
        return props, events, observed, original

    def context(self, capture_id, object_id):
        report = source_report(self.library.source(capture_id))
        return report, *self._context(report, object_id)

    def source(self, capture_id):
        capture_id = CaptureAction(id=capture_id).id
        report = source_report(self.library.source(capture_id))
        schedules, seen = [], set()
        for item in report["objects"]:
            object_id = item.get("object")
            try:
                obj = ObjectIdentifier(object_id)
                if int(obj[0]) != 17 or str(obj) != object_id or object_id in seen:
                    continue
            except (ValueError, TypeError):
                continue
            seen.add(object_id)
            try:
                _, events, observed, original = self._context(report, object_id)
                schedules.append(
                    {
                        "object": object_id,
                        "eligible": True,
                        "issues": [],
                        "native_type": observed,
                        "events": [seed_event(event) for event in events],
                        "minimum_known_protocol_revision": minimum_revision(
                            [seed_event(event) for event in events]
                        ),
                        "value_encoded_hex": original.hex(),
                        "value_sha256": sha(original),
                        "Calendar_references_queried": False,
                    }
                )
            except Exception as error:
                schedules.append(
                    {
                        "object": object_id,
                        "eligible": False,
                        "issues": [str(error)[:400] or type(error).__name__],
                    }
                )
        return {
            **envelope(),
            "capture_id": capture_id,
            "source_sha256": capture_id,
            "evidence_sha256": report["evidence_sha256"],
            "target": report["target"],
            "started_at": report["started_at"],
            "finished_at": report["finished_at"],
            "schedules": schedules,
        }

    def review(self, request):
        draft = ExceptionDraft.model_validate(request)
        report, props, old_events, observed, original = self.context(
            draft.capture_id, draft.object_id
        )
        events = []
        for event in draft.events:
            period = (
                SpecialEventPeriod(calendarReference=ObjectIdentifier(event.period.object_id))
                if event.period.kind == "calendarReference"
                else SpecialEventPeriod(calendarEntry=native_entry(event.period))
            )
            times, previous = [], None
            for row in event.transitions:
                if row.native_type not in (observed, "Null"):
                    raise ValueError(
                        "Exception values must match captured Schedule_Default or Null."
                    )
                clock = tuple(row.time)
                if previous is not None and clock <= previous:
                    raise ValueError(
                        "Exception times must be strictly increasing without duplicates."
                    )
                previous = clock
                times.append(TimeValue(time=Time(clock), value=primitive(row)))
            events.append(
                SpecialEvent(period=period, listOfTimeValues=times, eventPriority=event.priority)
            )
        value = EXCEPTION_ARRAY(events)
        raw = bytes(value.encode().encode().pduData)
        tags = TagList.decode(PDU(raw))
        restored = EXCEPTION_ARRAY.decode(tags)
        if tags or bytes(restored.encode().encode().pduData) != raw:
            raise ValueError("Exception array native encode/decode proof failed.")
        seeds = [seed_event(event) for event in restored]
        if [row["period"] for row in seeds] != [
            event.period.model_dump() for event in draft.events
        ]:
            raise ValueError("Exception native period choices changed during encoding.")
        body = {
            **envelope(),
            "format": PROFILE,
            "request": draft.model_dump(),
            "source": {
                "capture_id": draft.capture_id,
                "source_sha256": draft.capture_id,
                "evidence_sha256": report["evidence_sha256"],
                "target": report["target"],
                "object": draft.object_id,
                "property": "exception-schedule",
                "array_index": None,
                "native_type": observed,
                "exception_evidence_sha256": digest(props["exception-schedule"]),
                "unchanged_context_sha256": digest(
                    {key: row for key, row in props.items() if key != "exception-schedule"}
                ),
            },
            "old": {
                "events": [seed_event(event) for event in old_events],
                "encoded_hex": original.hex(),
                "sha256": sha(original),
            },
            "new": {
                "events": seeds,
                "encoded_hex": raw.hex(),
                "sha256": sha(raw),
                "roundtrip_tags_exhausted": True,
                "minimum_known_protocol_revision": minimum_revision(
                    [seed_event(event) for event in old_events] + seeds
                ),
                "target_revision_verified": False,
                "Calendar_references_queried": False,
            },
            "diff": {
                "changed": raw != original,
                "old_count": len(old_events),
                "new_count": len(events),
                "other_properties_changed": False,
            },
            "interpretation": "Native encoding proof only. Event order/priority, Null release and Calendar references are retained without schedule evaluation, reference lookup or timezone inference. Review exact native text/tags for numeric rounding and signed zero.",
        }
        body["id"] = digest(body)
        if len(encoded(body)) > MAX_DOCUMENT:
            raise ValueError("Exception review exceeds its 512 KiB document bound.")
        return body

    def export(self, request):
        options = ExceptionExport.model_validate(request)
        result = self.review(options.draft.model_dump())
        if result["id"] != options.expected_review_id:
            raise ValueError("Exception source or draft changed; review it again.")
        return encoded(result)

    def import_review(self, raw):
        body = strict_json(raw, MAX_DOCUMENT, max_values=100000)
        if (
            type(body) is not dict
            or body.get("profile") != PROFILE
            or body.get("format") != PROFILE
            or body.get("rules_sha256") != RULES_SHA256
            or body.get("id") != digest({key: value for key, value in body.items() if key != "id"})
        ):
            raise ValueError("Exception draft profile or source proof is unknown or changed.")
        result = self.review(body.get("request"))
        if encoded(result) != encoded(body):
            raise ValueError("Imported exceptions differ from their original source/native proof.")
        return result


def exception_draft_router(library):
    service = NativeScheduleExceptions(library)
    router = APIRouter(prefix="/api/bacnet/schedules/library/exceptions")

    @router.post("/source")
    def source(body: CaptureAction):
        return service.source(body.id)

    @router.post("/review")
    def review(body: ExceptionDraft):
        return service.review(body.model_dump())

    @router.post("/export")
    def export(body: ExceptionExport):
        return Response(
            service.export(body.model_dump()),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="native-schedule-exceptions-{body.expected_review_id}.json"'
            },
        )

    @router.post("/import")
    async def import_review(file: UploadFile):
        return await asyncio.to_thread(service.import_review, await file.read(MAX_DOCUMENT + 1))

    return router
