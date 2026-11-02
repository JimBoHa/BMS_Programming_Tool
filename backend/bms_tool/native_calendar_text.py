"""Bounded recovery of unfinished Calendar fields without native or field authority."""

import asyncio
import copy
import hashlib
import json

from fastapi import APIRouter, Response, UploadFile

from .native_calendar_drafts import CalendarDraft, NativeCalendarDrafts
from .native_schedule_library import identifier, strict_json

DOCUMENT_PROFILE = "native-calendar-unfinished-text/1"
IMPORT_PROFILE = "native-calendar-unfinished-text-import/1"
MAX_DOCUMENT = 128 * 1024


def keys(value, required, optional=()):
    if (
        type(value) is not dict
        or not set(required) <= value.keys()
        or not value.keys() <= set(required) | set(optional)
    ):
        raise ValueError("Unfinished Calendar document has unknown or incomplete fields.")


def text(value, maximum, *, nonempty=False):
    if (
        type(value) is not str
        or (nonempty and not value)
        or len(value.encode("utf-16-le")) // 2 > maximum
    ):
        raise ValueError("Unfinished Calendar text exceeds its raw editor limit.")
    return value


def buffer(value):
    keys(value, ("rows", "imported"), ("rawImported",))
    if value["imported"] != "":
        identifier(value["imported"])
    if "rawImported" in value:
        keys(value["rawImported"], ("filename", "file_sha256"))
        text(value["rawImported"]["filename"], 1024, nonempty=True)
        identifier(value["rawImported"]["file_sha256"])
    rows = value["rows"]
    if type(rows) is not list or len(rows) > 32:
        raise ValueError("Unfinished Calendar text requires at most 32 raw entries.")
    for row in rows:
        keys(row, ("kind", "date", "start", "end", "fields"))
        if type(row["kind"]) is not str or row["kind"] not in ("date", "dateRange", "weekNDay"):
            raise ValueError("Unfinished Calendar entry kind is unsupported.")
        for name, count in (("date", 4), ("start", 4), ("end", 4), ("fields", 3)):
            if type(row[name]) is not list or len(row[name]) != count:
                raise ValueError("Unfinished Calendar field list has an invalid shape.")
            for field in row[name]:
                text(field, 4)
    return copy.deepcopy(value)


class NativeCalendarText:
    def __init__(self, library):
        self.drafts = NativeCalendarDrafts(library)

    def import_document(self, raw):
        document = strict_json(raw, MAX_DOCUMENT)
        keys(document, ("profile", "field_authority", "source", "buffer"))
        if document["profile"] != DOCUMENT_PROFILE or document["field_authority"] is not False:
            raise ValueError("Unfinished Calendar profile or local-only declaration is unknown.")
        source = document["source"]
        if type(source) is not list or len(source) != 2:
            raise ValueError("Unfinished Calendar source requires its original capture and object.")
        capture_id = identifier(source[0])
        object_id = text(source[1], 80, nonempty=True)
        try:
            CalendarDraft.calendar_object(object_id)
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError("Select an exact existing standard Calendar object.") from error
        self.drafts.context(capture_id, object_id)
        return {
            "profile": IMPORT_PROFILE,
            "document_profile": DOCUMENT_PROFILE,
            "field_authority": False,
            "controller_queries": False,
            "capture_mutations": False,
            "native_review_created": False,
            "file_sha256": hashlib.sha256(raw).hexdigest(),
            "source": [capture_id, object_id],
            "buffer": buffer(document["buffer"]),
            "provenance_policy": "Retained filenames/review IDs are unverified references, not native encoding or field authority.",
        }


def calendar_text_router(library):
    service = NativeCalendarText(library)
    router = APIRouter(prefix="/api/bacnet/schedules/library/calendar/unfinished")

    @router.post("/import")
    async def import_text(file: UploadFile):
        result = await asyncio.to_thread(service.import_document, await file.read(MAX_DOCUMENT + 1))
        return Response(
            json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(),
            media_type="application/json",
        )

    return router
