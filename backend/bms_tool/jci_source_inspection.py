"""Read-only, bounded JCI engineering source inspection; no field authority."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Request, UploadFile
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from .caf import CafArchive
from .models import Program
from .moi_application import MoiApplication
from .program_source import strict_source_json

PROFILE = "jci-engineering-source-inspection/1"
CATALOG_PROFILE = "jci-engineering-inventory/1"
MAX_BYTES = 8 * 1024 * 1024
FLAGS = {
    "read_only": True,
    "network_requests": False,
    "controller_queries": False,
    "field_actions": False,
    "source_retained_on_server": False,
    "native_sct_archive_decoded": False,
    "native_jct_graphics_decoded": False,
    "compile_authority": False,
    "apply_authority": False,
    "physical_acceptance": False,
}
DATA = Path(__file__).parent / "data" / "jciEngineeringInventory.json"


def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def inventory():
    value = json.loads(DATA.read_text(encoding="utf-8"))
    if (
        value.get("profile") != CATALOG_PROFILE
        or value.get("manual_operation_mapping") != "partial"
    ):
        raise ValueError(
            "The engineering inventory requires a supported, explicit coverage profile."
        )
    return value


def _name(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError(
            "Choose a source with a nonempty file label of at most 512 characters and no control characters."
        )
    # A client-supplied file label is never used as a local filesystem path.
    name = value.replace("\\", "/").rsplit("/", 1)[-1]
    if not name or name in (".", ".."):
        raise ValueError("Choose a source with an ordinary file name.")
    return name


def _declared(extension):
    return {
        ".caf": "caf-proposed",
        ".moi": "native-field-image-proposed",
        ".moz": "native-field-image-proposed",
        ".dbexport": "sct-xml-export-proposed",
        ".sdbexport": "sct-protected-export-proposed",
        ".backup": "sct-database-backup-proposed",
        ".sbackup": "sct-protected-backup-proposed",
        ".imp": "jci-item-import-proposed",
        ".svg": "vector-graphic-proposed",
        ".json": "json-document-proposed",
    }.get(extension, "unspecified")


def _classes(rows):
    values = [str(row) if row is not None else "unknown" for row in rows]
    unrepresented = sum(len(row) > 64 or any(ord(c) < 32 for c in row) for row in values)
    counts = Counter(
        row if len(row) <= 64 and not any(ord(c) < 32 for c in row) else "unrepresented"
        for row in values
    )
    ordered = sorted(counts.items())
    return {
        "class_count": len(ordered),
        "classes": [{"id": key, "objects": count} for key, count in ordered[:64]],
        "class_list_complete": len(ordered) <= 64 and not unrepresented,
        "unrepresented_class_ids": unrepresented,
    }


def inspect_source(source: bytes, filename: str):
    if not isinstance(source, bytes) or not 1 <= len(source) <= MAX_BYTES:
        raise ValueError("Choose a nonempty source within the 8 MiB inspection profile.")
    name = _name(filename)
    extension = Path(name).suffix.lower()
    digest = hashlib.sha256(source).hexdigest()
    prefix = source.removeprefix(b"\xef\xbb\xbf").lstrip()
    container = (
        "zip"
        if source.startswith(b"PK")
        else "gzip"
        if source.startswith(b"\x1f\x8b")
        else "native-moi"
        if source.startswith(b"\x02\x00MOI\x00")
        else "json-looking"
        if prefix.startswith((b"{", b"["))
        else "xml-looking"
        if prefix.startswith(b"<")
        else "opaque"
    )
    result = {
        "profile": PROFILE,
        "source": {
            "name": name,
            "bytes": len(source),
            "sha256": digest,
            "extension": extension,
            "declared_family": _declared(extension),
        },
        "detected": {
            "state": "unrecognized",
            "reader_profile": None,
            "container_hint": container,
            "artifact_identity_proved": False,
        },
        "summary": {},
        "diagnostics": [],
        "operations": [],
        "coverage": {
            "source_bytes_fingerprinted": True,
            "complete_native_semantics": False,
            "unknown_sections_preserved_in_original_only": True,
        },
        **FLAGS,
    }
    if container == "zip":
        try:
            archive = CafArchive(source)
        except ValueError as exc:
            result["diagnostics"].append(
                "Not admitted by the existing single-XML CAF reader: " + str(exc)[:240]
            )
        else:
            result["detected"].update(state="readable", reader_profile="jci-single-xml-objects/1")
            versions = sorted(
                {str(obj.get("classVersion", "")) for obj in archive.objects.values()}
            )
            bounded_versions = [value for value in versions if len(value) <= 128]
            result["summary"] = {
                "objects": len(archive.objects),
                "xml_bytes": len(archive.xml),
                "class_versions": bounded_versions[:32],
                "class_versions_complete": len(versions) <= 32
                and len(bounded_versions) == len(versions),
                "omitted_class_versions": len(versions) - min(32, len(bounded_versions)),
                "root_metadata_records": len(archive.extra_entries),
                "tool_release": None,
                **_classes(obj.get("classid") for obj in archive.objects.values()),
            }
            result["diagnostics"].append(
                "The CAF reader recognizes this object container. Its namespace and file name do not prove CCT/PCT versus SCT origin, tool release, or complete native archive semantics."
            )
    elif container in ("gzip", "native-moi"):
        try:
            application = MoiApplication(source)
        except ValueError as exc:
            result["diagnostics"].append(
                "Not admitted by the existing tagged MOI reader: " + str(exc)[:240]
            )
        else:
            summary = application.summary()
            errors = summary["errors"]
            result["detected"].update(
                state="partial" if errors else "readable", reader_profile=application.format
            )
            result["summary"] = {
                "objects": len(application.records),
                "metadata_records": len(application.metadata_records),
                "record_framing": application.record_framing,
                "readable_diagrams": len(summary["diagrams"]),
                "reader_errors": len(errors),
                "tool_release": None,
                **_classes(row["class_id"] for row in application.records.values()),
            }
            result["diagnostics"].extend(
                "Partial native record coverage: "
                + str(error.get("error", "unexamined diagram"))[:200]
                for error in errors[:8]
            )
            if len(errors) > 8:
                result["diagnostics"].append(
                    str(len(errors) - 8)
                    + " additional reader errors are omitted from this bounded report."
                )
            result["diagnostics"].append(
                "This detached field image supplies no saved-file directory, verified controller identity, current values, or supervisory archive."
            )
    elif container == "json-looking":
        try:
            document = strict_source_json(source.decode("utf-8-sig"))
            if (
                not isinstance(document, dict)
                or type(document.get("schema_version")) is not int
                or document["schema_version"] != 1
                or not all(key in document for key in ("id", "nodes", "edges"))
            ):
                raise ValueError(
                    "The JSON does not declare the supported portable Program shape and schema."
                )
            if type(document.get("revision", 0)) is not int or document.get("revision", 0) < 0:
                raise ValueError("Portable source revision must be a nonnegative integer.")
            program = Program.model_validate(document)
        except (ValueError, UnicodeError, TypeError):
            result["diagnostics"].append(
                "The JSON is not a valid, explicitly identified schema-1 portable Program. Duplicate, nonfinite, deep, malformed and future-schema documents are not normalized into a replacement."
            )
        else:
            result["detected"].update(
                state="readable",
                reader_profile="bms-portable-program/1",
                artifact_identity_proved=True,
            )
            result["summary"] = {
                "program_id": program.id,
                "name": program.name,
                "revision_text": str(program.revision),
                "nodes": len(program.nodes),
                "edges": len(program.edges),
                "schema_version": 1,
            }
            result["diagnostics"].append(
                "This is a portable field-program graph, separately from native SCT archives, supervisory LCT and JCT graphics."
            )
    if result["detected"]["state"] == "unrecognized":
        result["diagnostics"].append(
            "No qualified decoder identified this source. Keep the original; recognition of a name or container does not establish import, conversion, compilation or deployment."
        )
    if extension in (".dbexport", ".sdbexport", ".backup", ".sbackup", ".imp", ".svg"):
        result["diagnostics"].append(
            "The proposed archive/item/graphics family requires a separately qualified native codec, even if another reader exposes a local projection."
        )
    parsed = result["detected"]["reader_profile"] is not None
    result["operations"] = [
        {
            "id": "fingerprint",
            "status": "available-local",
            "reason": "Exact selected bytes are hashed without changing or retaining the source.",
            "implementation": "jci_source_inspection.inspect_source",
        },
        {
            "id": "inspect-projection",
            "status": "available-local" if parsed else "unavailable",
            "reason": "Only the admitted reader's represented scope is reported."
            if parsed
            else "No admitted reader identified this content.",
            "implementation": result["detected"]["reader_profile"],
        },
        {
            "id": "export-inspection-report",
            "status": "available-local",
            "reason": "Save this exact report; it is evidence and grants no field authority.",
            "implementation": "jci_source_inspection.inspection_router",
        },
        {
            "id": "native-sct-import-export",
            "status": "not-qualified",
            "reason": "Native SCT schema, original sections and independent native round-trip evidence are still required.",
            "implementation": None,
        },
        {
            "id": "native-jct-graphics",
            "status": "not-qualified",
            "reason": "Graphics, resources, aliases and native publication need their own codec and verification.",
            "implementation": None,
        },
        {
            "id": "compile-or-deploy",
            "status": "not-granted",
            "reason": "Local inspection creates no compilation, device review, write plan or transfer authority.",
            "implementation": None,
        },
    ]
    result["report_sha256"] = hashlib.sha256(encoded(result)).hexdigest()
    return result


def inspection_router():
    router = APIRouter(prefix="/api/jci/engineering")

    @router.get("/inventory")
    def catalog():
        return inventory()

    @router.post("/inspect")
    async def inspect(request: Request, file: Annotated[UploadFile, File()]):
        try:
            form = await request.form()
            if set(form) != {"file"} or len(form.getlist("file")) != 1:
                raise ValueError(
                    "Inspect exactly one file; target, path and write fields are not accepted."
                )
            source = await file.read(MAX_BYTES + 1)
            result = await run_in_threadpool(inspect_source, source, file.filename or "")
        finally:
            await file.close()
        raw = encoded(result)
        return Response(
            raw,
            media_type="application/json",
            headers={
                "X-BMS-Report-SHA256": hashlib.sha256(raw).hexdigest(),
                "X-BMS-Source-SHA256": result["source"]["sha256"],
                "Cache-Control": "no-store",
            },
        )

    return router
