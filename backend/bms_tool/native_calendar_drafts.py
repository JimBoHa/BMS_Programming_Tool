"""Source-bound Calendar value drafts; no controller or capture mutation path."""

import asyncio
import copy
from typing import Annotated, Literal

from bacpypes3.basetypes import CalendarEntry, DateRange, WeekNDay
from bacpypes3.object import CalendarObject
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import Boolean, Date, ObjectIdentifier, TagList
from fastapi import APIRouter, Response, UploadFile
from pydantic import Field, StrictInt, field_validator, model_validator

from .models import StrictModel
from .moi_identity import sha
from .native_schedule_library import (
    RULES as WEEKLY_RULES,
)
from .native_schedule_library import (
    CaptureAction,
    date_pattern,
    date_range,
    decoded_row,
    digest,
    encoded,
    source_report,
    strict_json,
)

PROFILE = "native-calendar-date-list-draft/1"
MAX_ENTRIES, MAX_DOCUMENT = 32, 128 * 1024
SCOPE = (
    "Offline replacement value for one captured standard Calendar Date_List. "
    "Original source and other properties are retained. Native tag encoding only; "
    "no field queries, writes, native CAF generation, calendar evaluation, timezone "
    "inference, controller write authority or physical acceptance."
)
RULES = {
    "profile": PROFILE,
    "stack": "bacpypes3/0.0.110",
    "source": "Immutable captured source SHA-256, verified Device/Calendar tag identities, exact Boolean Present_Value and complete canonical Date_List tags.",
    "selection": "One existing Calendar of object type 6; the complete non-array Date_List value, at most 32 CalendarEntry choices.",
    "date": "Strict four integer native bytes: year 0..255, month 1..14/255, day 1..34/255, weekday 1..7/255; possible concrete dates and nonconflicting concrete weekdays.",
    "range": "Two valid native Date patterns; concrete start must not follow concrete end. Wildcard/special pattern evaluation is not inferred.",
    "weekNDay": "Strict three integer bytes: month 1..14/255, week 1..9/255, weekday 1..7/255. Values 7..9 were added in protocol revision 18; target compatibility is not inferred by this local encoder.",
    "preservation": "Retain input order and duplicates. No sorting, coalescing, inferred controller date or timezone. Unsupported/partial/noncanonical source stays ineligible.",
    "proof": "Exact old native value re-encoding; new ListOfCalendarEntry decode exhausts tags and re-encodes byte-identically.",
    "authority": "Deterministic local encoding review only. Export regenerates the source proof and checks its expected review ID; import reproves the entire body. No review cache, write APDU or transfer grant.",
    "integrity": "Captured self-seals and source claims are not authenticated manufacturer provenance or a current controller measurement.",
    "reviewed_sources": {
        **copy.deepcopy(WEEKLY_RULES["reviewed_sources"]),
        "ASHRAE135-2012bg-4/PDF7": "4f2b5bce008118288388532db4c8b6646005fb03be458c53f39d51b8b7d1ce06",
        "ASHRAE135.1-2019s/ScheduleWeekNDay/PDF194-196": "13e6c5fcc4664776acf50b94befcacceb70c433a4e12cef6fb45d127df721951",
    },
}
RULES_SHA256 = digest(RULES)
DATE_LIST = CalendarObject.get_property_type("date-list")


class CalendarDate(StrictModel):
    kind: Literal["date"]
    date: list[StrictInt] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def pattern(self):
        date_pattern(self.date)
        return self


class CalendarRange(StrictModel):
    kind: Literal["dateRange"]
    start: list[StrictInt] = Field(min_length=4, max_length=4)
    end: list[StrictInt] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def pattern(self):
        date_pattern(self.start)
        date_pattern(self.end)
        date_range(DateRange(startDate=Date(tuple(self.start)), endDate=Date(tuple(self.end))))
        return self


class CalendarWeek(StrictModel):
    kind: Literal["weekNDay"]
    fields: list[StrictInt] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def pattern(self):
        month, week, weekday = self.fields
        if not (
            (1 <= month <= 14 or month == 255)
            and (1 <= week <= 9 or week == 255)
            and (1 <= weekday <= 7 or weekday == 255)
        ):
            raise ValueError("WeekNDay requires supported month, week and weekday fields.")
        return self


Entry = Annotated[CalendarDate | CalendarRange | CalendarWeek, Field(discriminator="kind")]


class CalendarDraft(StrictModel):
    capture_id: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    object_id: str = Field(min_length=1, max_length=80, strict=True)
    entries: list[Entry] = Field(max_length=MAX_ENTRIES)

    @field_validator("object_id")
    @classmethod
    def calendar_object(cls, value):
        obj = ObjectIdentifier(value)
        if str(obj) != value or int(obj[0]) != 6 or not 0 <= obj[1] <= 4194302:
            raise ValueError("Select an exact existing standard Calendar object identifier.")
        return value


class CalendarDraftExport(StrictModel):
    draft: CalendarDraft
    expected_review_id: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)


def native_entry(entry):
    if entry.kind == "date":
        return CalendarEntry(date=Date(tuple(entry.date)))
    if entry.kind == "dateRange":
        return CalendarEntry(
            dateRange=DateRange(
                startDate=Date(tuple(entry.start)),
                endDate=Date(tuple(entry.end)),
            )
        )
    return CalendarEntry(weekNDay=WeekNDay(bytes(entry.fields)))


def seed_entry(entry):
    if entry._choice == "date":
        result = CalendarDate(kind="date", date=list(entry.date))
    elif entry._choice == "dateRange":
        result = CalendarRange(
            kind="dateRange",
            start=list(entry.dateRange.startDate),
            end=list(entry.dateRange.endDate),
        )
    elif entry._choice == "weekNDay":
        result = CalendarWeek(kind="weekNDay", fields=list(entry.weekNDay))
    else:
        raise ValueError("Captured CalendarEntry choice is unsupported.")
    return result.model_dump()


def envelope():
    return {
        "profile": PROFILE,
        "rules_sha256": RULES_SHA256,
        "scope": SCOPE,
        "field_writes": False,
        "controller_queries": False,
        "capture_mutations": False,
    }


class NativeCalendarDrafts:
    def __init__(self, library):
        self.library = library

    def context(self, capture_id, object_id):
        try:
            return self._context(source_report(self.library.source(capture_id)), object_id)
        except ValueError as error:
            raise ValueError(str(error)[:400] or "Captured Calendar source is invalid.") from error
        except Exception as error:
            raise ValueError(
                "Captured Calendar context cannot be interpreted by this draft profile."
            ) from error

    def _context(self, report, object_id):
        obj = ObjectIdentifier(object_id)
        if str(obj) != object_id or int(obj[0]) != 6 or not 0 <= obj[1] <= 4194302:
            raise ValueError("Select an exact existing standard Calendar object identifier.")
        if report["identity_verified"] is not True:
            raise ValueError("Captured Device identity was not verified.")
        device = report["target"]["device"]
        actual, _ = decoded_row(report.get("device_identity"), device, "object-identifier")
        if actual != ObjectIdentifier(device):
            raise ValueError("Captured Device tag identity differs from its selected source.")
        matches = [row for row in report["objects"] if row.get("object") == object_id]
        if len(matches) != 1 or matches[0].get("identity_verified") is not True:
            raise ValueError("Select exactly one identity-verified captured Calendar.")
        item = matches[0]
        props = item.get("properties", {})
        actual, _ = decoded_row(props.get("object-identifier"), object_id, "object-identifier")
        if actual != ObjectIdentifier(object_id) or int(actual[0]) != 6:
            raise ValueError("Captured Calendar tag identity differs from its selected source.")
        present, _ = decoded_row(props.get("present-value"), object_id, "present-value")
        if not isinstance(present, Boolean):
            raise ValueError("Captured Calendar Present_Value is not a native Boolean.")
        value, raw_property = decoded_row(props.get("date-list"), object_id, "date-list")
        if len(value) > MAX_ENTRIES:
            raise ValueError("Captured Date_List exceeds the 32-entry draft profile.")
        entries = [seed_entry(row) for row in value]
        raw = raw_property[1:-1]
        if bytes(value.encode().encode().pduData) != raw:
            raise ValueError(
                "Captured Date_List requires unsupported native encoding normalization."
            )
        return report, props, entries, raw_property, raw

    def source(self, capture_id):
        capture_id = CaptureAction(id=capture_id).id
        report = source_report(self.library.source(capture_id))
        calendars, seen = [], set()
        for item in report["objects"]:
            name = item.get("object")
            try:
                obj = ObjectIdentifier(name)
                if int(obj[0]) != 6 or str(obj) != name or name in seen:
                    continue
            except (ValueError, TypeError):
                continue
            seen.add(name)
            try:
                _, _, entries, raw_property, raw = self._context(report, name)
                calendars.append(
                    {
                        "object": name,
                        "eligible": True,
                        "issues": [],
                        "entries": entries,
                        "property_encoded_hex": raw_property.hex(),
                        "property_sha256": sha(raw_property),
                        "value_encoded_hex": raw.hex(),
                        "value_sha256": sha(raw),
                    }
                )
            except Exception as error:
                calendars.append(
                    {
                        "object": name,
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
            "calendars": calendars,
        }

    def review(self, request):
        draft = CalendarDraft.model_validate(request)
        report, props, old_entries, raw_property, old = self.context(
            draft.capture_id, draft.object_id
        )
        value = DATE_LIST([native_entry(row) for row in draft.entries])
        raw = bytes(value.encode().encode().pduData)
        tags = TagList.decode(PDU(raw))
        restored = DATE_LIST.decode(tags)
        if tags or bytes(restored.encode().encode().pduData) != raw:
            raise ValueError("Native Calendar value encode/decode proof failed.")
        entries = [seed_entry(row) for row in restored]
        if entries != [row.model_dump() for row in draft.entries]:
            raise ValueError("Native Calendar value changed its declared entry patterns.")
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
                "property": "date-list",
                "array_index": None,
                "property_evidence_sha256": digest(props["date-list"]),
                "property_sha256": sha(raw_property),
                "unchanged_context_sha256": digest(
                    {key: row for key, row in props.items() if key != "date-list"}
                ),
            },
            "old": {"entries": old_entries, "encoded_hex": old.hex(), "sha256": sha(old)},
            "new": {
                "entries": entries,
                "encoded_hex": raw.hex(),
                "sha256": sha(raw),
                "roundtrip_tags_exhausted": True,
                "minimum_known_protocol_revision": 18
                if any(row["kind"] == "weekNDay" and 7 <= row["fields"][1] <= 9 for row in entries)
                else None,
                "target_revision_verified": False,
            },
            "diff": {
                "changed": raw != old,
                "old_count": len(old_entries),
                "new_count": len(entries),
                "other_properties_changed": False,
            },
            "interpretation": "Entry order and duplicates are retained. Wildcard/special patterns are encoded, not evaluated. Captured Present_Value is an observation, not a preview of this draft.",
        }
        body["id"] = digest(body)
        if len(encoded(body)) > MAX_DOCUMENT:
            raise ValueError("Native Calendar review exceeds its 128 KiB bound.")
        return body

    def export(self, request):
        options = CalendarDraftExport.model_validate(request)
        result = self.review(options.draft.model_dump())
        if result["id"] != options.expected_review_id:
            raise ValueError("Calendar review changed; review the exact source and draft again.")
        return encoded(result)

    def import_review(self, raw):
        body = strict_json(raw, MAX_DOCUMENT)
        if (
            type(body) is not dict
            or body.get("profile") != PROFILE
            or body.get("format") != PROFILE
            or body.get("rules_sha256") != RULES_SHA256
            or body.get("id") != digest({key: row for key, row in body.items() if key != "id"})
        ):
            raise ValueError("Native Calendar draft profile or source proof is unknown or changed.")
        result = self.review(body.get("request"))
        if encoded(body) != encoded(result):
            raise ValueError(
                "Imported Calendar draft differs from its original source and native proof."
            )
        return result


def calendar_draft_router(library):
    service = NativeCalendarDrafts(library)
    router = APIRouter(prefix="/api/bacnet/schedules/library/calendar")

    @router.post("/source")
    def source(body: CaptureAction):
        return service.source(body.id)

    @router.post("/review")
    def review(body: CalendarDraft):
        return service.review(body.model_dump())

    @router.post("/export")
    def export(body: CalendarDraftExport):
        return Response(
            service.export(body.model_dump()),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="native-calendar-draft-{body.expected_review_id}.json"',
            },
        )

    @router.post("/import")
    async def import_review(file: UploadFile):
        return await asyncio.to_thread(service.import_review, await file.read(MAX_DOCUMENT + 1))

    return router
