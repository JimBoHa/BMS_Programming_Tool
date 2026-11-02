"""Restore bounded unfinished weekly editor text without creating native authority."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json

from bacpypes3.primitivedata import ObjectIdentifier
from fastapi import APIRouter, Response, UploadFile

from .native_schedule_library import identifier, source_report, strict_json

DOCUMENT_PROFILE = "native-schedule-unfinished-weekly/1"
IMPORT_PROFILE = "native-schedule-unfinished-weekly-import/1"
MAX_DOCUMENT = 512 * 1024


def keys(value, required, optional=()):
    if (
        type(value) is not dict
        or not set(required) <= value.keys()
        or not value.keys() <= set(required) | set(optional)
    ):
        raise ValueError("Unfinished weekly document has unknown or incomplete fields.")


def text(value, maximum, *, nonempty=False):
    if (
        type(value) is not str
        or (nonempty and not value)
        or len(value.encode("utf-16-le")) // 2 > maximum
    ):
        raise ValueError("Unfinished weekly text exceeds its raw editor limit.")
    return value


def buffer(value, observed):
    keys(value, ("rows", "imported"), ("rawImported",))
    if value["imported"] is not None:
        keys(value["imported"], ("filename", "review_id"))
        text(value["imported"]["filename"], 1024, nonempty=True)
        identifier(value["imported"]["review_id"])
    if "rawImported" in value:
        keys(value["rawImported"], ("filename", "file_sha256"))
        text(value["rawImported"]["filename"], 1024, nonempty=True)
        identifier(value["rawImported"]["file_sha256"])
    rows = value["rows"]
    if type(rows) is not list or len(rows) > 32:
        raise ValueError("Unfinished weekly text requires at most 32 transition rows.")
    for row in rows:
        keys(row, ("time", "native_type", "value_text"), ("string_json",))
        if type(row["time"]) is not list or len(row["time"]) != 4:
            raise ValueError("Unfinished weekly time requires four raw text fields.")
        for field in row["time"]:
            text(field, 2)
        if type(row["native_type"]) is not str or row["native_type"] not in (
            observed,
            "Null",
        ):
            raise ValueError("Unfinished weekly type differs from its captured default.")
        text(row["value_text"], 256)
        if "string_json" in row:
            text(row["string_json"], 1538)
    return copy.deepcopy(value)


class NativeWeeklyText:
    def __init__(self, library):
        self.library = library

    def import_document(self, raw):
        document = strict_json(raw, MAX_DOCUMENT)
        keys(document, ("profile", "field_authority", "source", "buffer"))
        if document["profile"] != DOCUMENT_PROFILE or document["field_authority"] is not False:
            raise ValueError("Unfinished weekly profile or local-only declaration is unknown.")
        source = document["source"]
        if type(source) is not list or len(source) != 3:
            raise ValueError("Unfinished weekly source requires its capture, Schedule and day.")
        capture_id = identifier(source[0])
        object_id = text(source[1], 80, nonempty=True)
        obj = ObjectIdentifier(object_id)
        if int(obj[0]) != 17 or obj[1] > 4194302 or str(obj) != object_id:
            raise ValueError("Select one canonical existing standard Schedule object.")
        if type(source[2]) is not str or source[2] not in tuple("1234567"):
            raise ValueError("Unfinished weekly day must be text 1 through 7.")
        report = source_report(self.library.source(capture_id))
        _, _, observed = self.library._weekly_context(report, object_id)
        return {
            "profile": IMPORT_PROFILE,
            "document_profile": DOCUMENT_PROFILE,
            "field_authority": False,
            "controller_queries": False,
            "capture_mutations": False,
            "native_review_created": False,
            "file_sha256": hashlib.sha256(raw).hexdigest(),
            "source": [capture_id, object_id, source[2]],
            "native_type": observed,
            "buffer": buffer(document["buffer"], observed),
            "provenance_policy": "Retained filenames/review IDs are unverified references, not native encoding or field authority.",
        }


def weekly_text_router(library):
    service = NativeWeeklyText(library)
    router = APIRouter(prefix="/api/bacnet/schedules/library/weekly/unfinished")

    @router.post("/import")
    async def import_text(file: UploadFile):
        result = await asyncio.to_thread(service.import_document, await file.read(MAX_DOCUMENT + 1))
        return Response(
            json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(),
            media_type="application/json",
        )

    return router
