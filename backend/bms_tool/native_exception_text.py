"""Bounded source-bound restoration of raw exception editor text, without review authority."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json

from fastapi import APIRouter, Response, UploadFile

from .native_schedule_exceptions import ExceptionDraft, NativeScheduleExceptions
from .native_schedule_library import identifier, strict_json

DOCUMENT_PROFILE = "native-schedule-unfinished-exceptions/1"
IMPORT_PROFILE = "native-schedule-unfinished-exception-import/1"
# The workspace retains its existing 4 MiB bound. Legacy exports use pretty JSON,
# so their separate input-file ceiling includes formatting overhead.
MAX_DOCUMENT = 8 * 1024 * 1024
MAX_BUFFER = 4 * 1024 * 1024
PERIODS = {"date", "dateRange", "weekNDay", "calendarReference"}


def keys(value, required, optional=()):
    if (
        type(value) is not dict
        or not set(required) <= value.keys()
        or not value.keys() <= set(required) | set(optional)
    ):
        raise ValueError("Unfinished exception document has unknown or incomplete fields.")


def text(value, maximum, *, nonempty=False):
    if (
        type(value) is not str
        or (nonempty and not value)
        or len(value.encode("utf-16-le")) // 2 > maximum
    ):
        raise ValueError("Unfinished exception text exceeds its raw editor limit.")
    return value


def fields(value, count, maximum):
    if type(value) is not list or len(value) != count:
        raise ValueError("Unfinished exception field list has an invalid shape.")
    for item in value:
        text(item, maximum)


def provenance(value):
    if value is None:
        return
    keys(value, ("filename", "review_id"))
    text(value["filename"], 1024, nonempty=True)
    identifier(value["review_id"])


def buffer(value, observed):
    keys(value, ("rows", "imported"), ("rawImported",))
    provenance(value["imported"])
    if "rawImported" in value:
        keys(value["rawImported"], ("filename", "file_sha256"))
        text(value["rawImported"]["filename"], 1024, nonempty=True)
        identifier(value["rawImported"]["file_sha256"])
    rows = value["rows"]
    if type(rows) is not list or len(rows) > 32:
        raise ValueError("Unfinished exceptions require at most 32 event rows.")
    row_ids, time_ids = set(), set()
    for row in rows:
        keys(
            row,
            (
                "key",
                "kind",
                "date",
                "start",
                "end",
                "fields",
                "reference",
                "priority",
                "transitions",
            ),
        )
        key = text(row["key"], 80, nonempty=True)
        if key in row_ids:
            raise ValueError("Unfinished exception row keys must be unique.")
        row_ids.add(key)
        if type(row["kind"]) is not str or row["kind"] not in PERIODS:
            raise ValueError("Unfinished exception period kind is unsupported.")
        for name, count in (("date", 4), ("start", 4), ("end", 4), ("fields", 3)):
            fields(row[name], count, 4)
        text(row["reference"], 80)
        text(row["priority"], 2)
        transitions = row["transitions"]
        if type(transitions) is not list or len(transitions) > 32:
            raise ValueError("Unfinished exceptions require at most 32 time rows per event.")
        for time in transitions:
            keys(time, ("key", "time", "native_type", "value_text", "string_json"))
            key = text(time["key"], 80, nonempty=True)
            if key in time_ids:
                raise ValueError("Unfinished exception time keys must be unique.")
            time_ids.add(key)
            fields(time["time"], 4, 2)
            if type(time["native_type"]) is not str or time["native_type"] not in (
                observed,
                "Null",
            ):
                raise ValueError(
                    "Unfinished exception value type differs from its captured default."
                )
            text(time["value_text"], 256)
            text(time["string_json"], 1538)
    # Match JSON.stringify/TextEncoder workspace accounting without changing it.
    if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()) > MAX_BUFFER:
        raise ValueError("Unfinished exception buffer exceeds the existing 4 MiB workspace bound.")
    return copy.deepcopy(value)


class NativeExceptionText:
    def __init__(self, library):
        self.drafts = NativeScheduleExceptions(library)

    def import_document(self, raw):
        document = strict_json(raw, MAX_DOCUMENT)
        keys(document, ("profile", "field_authority", "source", "buffer"))
        if document["profile"] != DOCUMENT_PROFILE or document["field_authority"] is not False:
            raise ValueError("Unfinished exception profile or local-only declaration is unknown.")
        source = document["source"]
        if type(source) is not list or len(source) != 2:
            raise ValueError(
                "Unfinished exception source requires its original capture and Schedule."
            )
        capture_id, object_id = identifier(source[0]), text(source[1], 80, nonempty=True)
        ExceptionDraft.schedule(object_id)
        _, _, _, observed, _ = self.drafts.context(capture_id, object_id)
        return {
            "profile": IMPORT_PROFILE,
            "document_profile": DOCUMENT_PROFILE,
            "field_authority": False,
            "controller_queries": False,
            "capture_mutations": False,
            "native_review_created": False,
            "file_sha256": hashlib.sha256(raw).hexdigest(),
            "source": [capture_id, object_id],
            "native_type": observed,
            "buffer": buffer(document["buffer"], observed),
            "provenance_policy": "Retained filenames/review IDs are unverified references, not native encoding or field authority.",
        }


def exception_text_router(library):
    service = NativeExceptionText(library)
    router = APIRouter(prefix="/api/bacnet/schedules/library/exceptions/unfinished")

    @router.post("/import")
    async def import_text(file: UploadFile):
        result = await asyncio.to_thread(service.import_document, await file.read(MAX_DOCUMENT + 1))
        return Response(
            json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(),
            media_type="application/json",
        )

    return router
