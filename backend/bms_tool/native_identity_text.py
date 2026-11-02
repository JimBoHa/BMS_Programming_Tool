"""Recover unreviewed identity text from exact local source references."""

import asyncio
import copy
import hashlib
import json
import re

from fastapi import APIRouter, Response, UploadFile

from .application_store import encoded
from .native_backup_records import NativeBackupRecords
from .native_schedule_library import strict_json

DOCUMENT_PROFILE = "native-identity-local-draft/1"
IMPORT_PROFILE = "native-identity-local-draft-import/1"
MAX_DOCUMENT = 128 * 1024


def keys(value, required, optional=()):
    if (
        type(value) is not dict
        or not set(required) <= value.keys()
        or not value.keys() <= set(required) | set(optional)
    ):
        raise ValueError("Local identity draft has unknown or incomplete fields.")


def text(value, maximum, *, nonempty=False):
    if (
        type(value) is not str
        or (nonempty and not value)
        or len(value.encode("utf-16-le")) // 2 > maximum
    ):
        raise ValueError("Local identity text exceeds its raw file limit.")


def reference(value, length):
    if value is not None and (
        type(value) is not str or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None
    ):
        raise ValueError("Local identity source reference has an invalid shape.")


def document(value):
    keys(
        value,
        (
            "profile",
            "field_authority",
            "selection",
            "new_name",
            "new_instance_text",
            "capture_id",
            "captured_target",
            "snapshot_sha256",
            "receipt_id",
            "recovery_origin_sha256",
        ),
        ("raw_imported",),
    )
    if value["profile"] != DOCUMENT_PROFILE or value["field_authority"] is not False:
        raise ValueError("Local identity draft profile or local-only declaration is unknown.")
    selection = value["selection"]
    keys(
        selection,
        (
            "connected_context",
            "interface_identity",
            "address",
            "device",
            "router",
            "dnet",
            "change_kind",
        ),
    )
    if (
        type(selection["connected_context"]) is not bool
        or type(selection["change_kind"]) is not str
        or selection["change_kind"] not in ("name", "instance")
    ):
        raise ValueError("Local identity draft requires its exact name/instance context.")
    for name, limit in (("interface_identity", 16384), ("address", 1024), ("device", 256)):
        text(selection[name], limit)
    if selection["router"] is not None:
        text(selection["router"], 1024, nonempty=True)
    if selection["dnet"] is not None and (
        type(selection["dnet"]) is not int or not 0 <= selection["dnet"] <= 65535
    ):
        raise ValueError("Local identity context requires a bounded raw network number.")
    text(value["new_name"], 128)
    text(value["new_instance_text"], 65536)
    reference(value["capture_id"], 32)
    reference(value["snapshot_sha256"], 64)
    reference(value["receipt_id"], 32)
    reference(value["recovery_origin_sha256"], 64)
    if value["capture_id"] is None:
        if value["captured_target"] is not None or value["snapshot_sha256"] is not None:
            raise ValueError("Local identity capture references are incomplete.")
    else:
        if value["snapshot_sha256"] is None:
            raise ValueError("Local identity capture requires its original snapshot hash.")
        target = value["captured_target"]
        keys(target, ("address", "router", "dnet"), ("device",))
        text(target["address"], 1024, nonempty=True)
        if target["router"] is not None:
            text(target["router"], 1024, nonempty=True)
        if target["dnet"] is not None and (
            type(target["dnet"]) is not int or not 0 <= target["dnet"] <= 65535
        ):
            raise ValueError("Captured identity route has an invalid shape.")
        if "device" in target:
            text(target["device"], 256, nonempty=True)
    if "raw_imported" in value:
        keys(value["raw_imported"], ("filename", "file_sha256"))
        text(value["raw_imported"]["filename"], 1024, nonempty=True)
        reference(value["raw_imported"]["file_sha256"], 64)
        if value["raw_imported"]["file_sha256"] is None:
            raise ValueError("Raw identity provenance requires its unverified file hash.")
    return copy.deepcopy(value)


class NativeIdentityText:
    def __init__(self, storage):
        self.records = NativeBackupRecords(storage)

    def import_document(self, raw):
        value = document(strict_json(raw, MAX_DOCUMENT))
        source_text = None
        if value["capture_id"] is not None:
            snapshot, _ = self.records.load_files(
                {"capture_id": value["capture_id"], "snapshot_sha256": value["snapshot_sha256"]}
            )
            if value["captured_target"] not in (
                snapshot["target"],
                {**snapshot["target"], "device": snapshot["device"]},
            ):
                raise ValueError("Local identity draft differs from its original captured target.")
            # Hash original Python JSON spelling without asking JavaScript to
            # reproduce native metadata numbers or Unicode escapes.
            source = encoded({k: v for k, v in snapshot.items() if k != "evidence_sha256"})
            if (
                len(source) > MAX_DOCUMENT
                or hashlib.sha256(source).hexdigest() != value["snapshot_sha256"]
            ):
                raise ValueError("Original identity source evidence cannot be verified.")
            source_text = source.decode("utf-8")
        return {
            "profile": IMPORT_PROFILE,
            "document_profile": DOCUMENT_PROFILE,
            "field_authority": False,
            "controller_queries": False,
            "capture_mutations": False,
            "native_review_created": False,
            "recovery_prepared": False,
            "file_sha256": hashlib.sha256(raw).hexdigest(),
            "document": value,
            "source_evidence_text": source_text,
            "local_source_verified": source_text is not None,
        }


def identity_text_router(storage):
    service = NativeIdentityText(storage)
    router = APIRouter(prefix="/api/bacnet/controller/native-application/local-drafts")

    @router.post("/import")
    async def import_text(file: UploadFile):
        result = await asyncio.to_thread(service.import_document, await file.read(MAX_DOCUMENT + 1))
        return Response(
            json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(),
            media_type="application/json",
        )

    return router
