"""Bounded, explicit historical CAF/source selections; never application authority."""

import hashlib
import json
import re
import secrets
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import Field, TypeAdapter

from .caf_native_correlation import PROFILE as BACKUP_PROFILE
from .caf_native_correlation import correlate
from .caf_native_file_correlation import PROFILE as FILE_PROFILE
from .models import StrictModel
from .moi_identity import seal

PROFILE = "caf-source-reference/1"
LIST_PROFILE = "caf-source-references/1"
SAVE_PROFILE = "caf-source-reference-save/1"
REMOVE_PROFILE = "caf-source-reference-remove/1"
MAX_REFERENCES = 256
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_REPORT_BYTES = 1024 * 1024
SCOPE = (
    "User-selected historical CAF/source reference. Original identity comparison only; "
    "source availability and current controller application are not revalidated. "
    "No application association, full-program match, compiler compatibility or field authority."
)
UNAVAILABLE = (
    "Saved source reference evidence is unavailable or inconsistent; "
    "remove this reference if no longer needed."
)
FLAGS = {
    "read_only": True,
    "controller_queries": False,
    "controller_writes": False,
    "field_actions": False,
    "full_program_match_verified": False,
    "compiler_compatibility_verified": False,
    "application_association_granted": False,
    "can_apply": False,
    "source_availability_revalidated": False,
}
Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{32}$")]


class BackupReference(StrictModel):
    source_kind: Literal["backup"]
    source_sha256: Digest
    capture_id: Identifier
    snapshot_sha256: Digest


class FileReference(StrictModel):
    source_kind: Literal["file"]
    source_sha256: Digest
    capture_id: Identifier
    receipt_sha256: Digest
    file_sha256: Digest


SaveReference = Annotated[BackupReference | FileReference, Field(discriminator="source_kind")]
REQUEST = TypeAdapter(SaveReference)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identifier(value, size):
    if type(value) is not str or not re.fullmatch(r"[a-f0-9]{" + str(size) + "}", value):
        raise ValueError("Select a valid CAF hash and source reference identifier.")
    return value


def metadata(caf_hash, source_kind, report, reference_id, created):
    """Re-derive only recorded metadata; never reopen a CAF, source or controller."""
    identifier(caf_hash, 64)
    identifier(reference_id, 32)
    if type(created) is not str or datetime.fromisoformat(created).tzinfo is None:
        raise ValueError(UNAVAILABLE)
    expected_profile = BACKUP_PROFILE if source_kind == "backup" else FILE_PROFILE
    if (
        source_kind not in ("backup", "file")
        or type(report) is not dict
        or report.get("profile") != expected_profile
        or report.get("report_sha256")
        != seal({k: v for k, v in report.items() if k != "report_sha256"})
        or report.get("caf", {}).get("sha256") != caf_hash
        or report.get("caf", {}).get("source") != "original-opened-archive"
        or report.get("query") != ""
        or type(report.get("offset")) is not int
        or report["offset"] != 0
        or type(report.get("limit")) is not int
        or report["limit"] != 128
        or report.get("read_only") is not True
        or any(
            report.get(key) is not False
            for key in (
                "controller_queries",
                "field_actions",
                "full_program_match_verified",
                "compiler_compatibility_verified",
                "application_association_granted",
                "can_apply",
            )
        )
        or report.get("classification")
        not in (
            "recorded-identities-equal",
            "identity-incomplete",
            "recorded-differences",
        )
    ):
        raise ValueError(UNAVAILABLE)
    request = dict(report["request"])
    if any(
        request.pop(key, None) != value
        for key, value in (("query", ""), ("offset", 0), ("limit", 128))
    ):
        raise ValueError(UNAVAILABLE)
    selected = REQUEST.validate_python({**request, "source_kind": source_kind})
    if selected.source_sha256 != caf_hash:
        raise ValueError(UNAVAILABLE)
    source = report["native_backup" if source_kind == "backup" else "native_file"]
    if (
        source["capture_id"] != selected.capture_id
        or source.get("controller_queries") is not False
        or source.get("field_actions") is not False
        or type(source["target"]) is not dict
        or type(source["target"].get("address")) is not str
        or type(report["coverage"]) is not dict
        or type(report["total_matches"]) is not int
        or not 0 <= report["total_matches"] <= 40000
        or report["coverage"].get("union_references") != report["total_matches"]
        or type(report["records"]) is not list
        or len(report["records"]) != min(report["total_matches"], 128)
        or report["next_offset"] != (128 if report["total_matches"] > 128 else None)
    ):
        raise ValueError(UNAVAILABLE)
    identifier(source["sha256"], 64)
    if source_kind == "backup":
        if source["snapshot_sha256"] != selected.snapshot_sha256:
            raise ValueError(UNAVAILABLE)
        extra = {"snapshot_sha256": source["snapshot_sha256"]}
    else:
        if (
            source["receipt_sha256"] != selected.receipt_sha256
            or source["sha256"] != selected.file_sha256
        ):
            raise ValueError(UNAVAILABLE)
        extra = {"receipt_sha256": source["receipt_sha256"], "file_object": source["file_object"]}
    return {
        "profile": PROFILE,
        "id": reference_id,
        "state": "saved",
        "caf_sha256": caf_hash,
        "source_kind": source_kind,
        "source": {
            "capture_id": source["capture_id"],
            "sha256": source["sha256"],
            "target": source["target"],
            "captured_at": source["captured_at"],
            **extra,
        },
        "classification": report["classification"],
        "created_at": created,
        "report_sha256": digest(encoded(report)),
        "comparison_report_sha256": report["report_sha256"],
        "coverage": report["coverage"],
        "pagination": {
            "query": "",
            "offset": 0,
            "limit": 128,
            "total_matches": report["total_matches"],
            "next_offset": report["next_offset"],
            "records_retained": len(report["records"]),
        },
        "scope": SCOPE,
        **FLAGS,
    }


class CafSourceReferences:
    def __init__(self, store, backups, native_files):
        self.store, self.backups, self.native_files = store, backups, native_files
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS caf_source_references(
                id TEXT PRIMARY KEY, caf_sha256 TEXT NOT NULL, dedupe_sha256 TEXT NOT NULL,
                source_kind TEXT NOT NULL, created_at TEXT NOT NULL,
                report BLOB NOT NULL, report_sha256 TEXT NOT NULL,
                summary BLOB NOT NULL, summary_sha256 TEXT NOT NULL,
                UNIQUE(caf_sha256,dedupe_sha256)
            )""")

    @staticmethod
    def bounded_columns():
        # Corrupt oversized artifacts must not be loaded merely to report them unavailable.
        return (
            "id,caf_sha256,dedupe_sha256,source_kind,created_at,report_sha256,summary_sha256,"
            f"CASE WHEN LENGTH(report) BETWEEN 1 AND {MAX_REPORT_BYTES} THEN report END AS report,"
            f"CASE WHEN LENGTH(summary) BETWEEN 1 AND {MAX_REPORT_BYTES} THEN summary END AS summary"
        )

    @staticmethod
    def capacity(db):
        count, size = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(LENGTH(report)+LENGTH(summary)),0) FROM caf_source_references"
        ).fetchone()
        return {
            "count": count,
            "limit": MAX_REFERENCES,
            "bytes": size,
            "byte_limit": MAX_TOTAL_BYTES,
        }

    @staticmethod
    def checked(row):
        try:
            raw, summary = row["report"], row["summary"]
            if (
                type(raw) is not bytes
                or not 1 <= len(raw) <= MAX_REPORT_BYTES
                or type(summary) is not bytes
                or not 1 <= len(summary) <= MAX_REPORT_BYTES
                or digest(raw) != row["report_sha256"]
                or digest(summary) != row["summary_sha256"]
            ):
                raise ValueError(UNAVAILABLE)
            report, saved = json.loads(raw), json.loads(summary)
            expected = metadata(
                row["caf_sha256"], row["source_kind"], report, row["id"], row["created_at"]
            )
            if encoded(report) != raw or encoded(expected) != summary or saved != expected:
                raise ValueError(UNAVAILABLE)
            if row["dedupe_sha256"] != seal(
                {
                    "caf_sha256": row["caf_sha256"],
                    "source_kind": row["source_kind"],
                    "report_sha256": digest(raw),
                }
            ):
                raise ValueError(UNAVAILABLE)
            return expected, raw
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
            RecursionError,
        ) as exc:
            raise ValueError(UNAVAILABLE) from exc

    def save(self, caf, request):
        selected = REQUEST.validate_python(request)
        if caf.hash != selected.source_sha256:
            raise ValueError(
                "The opened CAF changed; reopen its original file before saving a reference."
            )
        arguments = selected.model_dump(exclude={"source_kind"}) | {
            "query": "",
            "offset": 0,
            "limit": 128,
        }
        report = (
            correlate(caf, self.backups, arguments)
            if selected.source_kind == "backup"
            else self.native_files.compare(caf, arguments)
        )
        raw = encoded(report)
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError("The comparison exceeds the saved-reference evidence size limit.")
        created = datetime.now(UTC).isoformat()
        item = metadata(caf.hash, selected.source_kind, report, secrets.token_hex(16), created)
        summary = encoded(item)
        if len(summary) > MAX_REPORT_BYTES:
            raise ValueError("The comparison exceeds the saved-reference metadata size limit.")
        key = seal(
            {
                "caf_sha256": caf.hash,
                "source_kind": selected.source_kind,
                "report_sha256": digest(raw),
            }
        )
        with self.store.connect() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                f"SELECT {self.bounded_columns()} FROM caf_source_references WHERE caf_sha256=? AND dedupe_sha256=?",
                (caf.hash, key),
            ).fetchone()
            if prior is not None:
                item, _ = self.checked(prior)
                added = False
            else:
                capacity = self.capacity(db)
                if (
                    capacity["count"] >= MAX_REFERENCES
                    or capacity["bytes"] + len(raw) + len(summary) > MAX_TOTAL_BYTES
                ):
                    raise ValueError(
                        "Saved source-reference capacity reached; explicitly remove an unneeded reference first."
                    )
                db.execute(
                    "INSERT INTO caf_source_references VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        item["id"],
                        caf.hash,
                        key,
                        selected.source_kind,
                        created,
                        raw,
                        digest(raw),
                        summary,
                        digest(summary),
                    ),
                )
                added = True
        return {
            "profile": SAVE_PROFILE,
            "reference": item,
            "created": added,
            "deduplicated": not added,
            "scope": SCOPE,
            **FLAGS,
        }

    def list(self, caf_hash):
        identifier(caf_hash, 64)
        with self.store.connect() as db:
            db.execute("BEGIN")
            rows = db.execute(
                f"SELECT {self.bounded_columns()} FROM caf_source_references WHERE caf_sha256=? ORDER BY created_at DESC,id LIMIT ?",
                (caf_hash, MAX_REFERENCES + 1),
            ).fetchall()
            capacity = self.capacity(db)
        if len(rows) > MAX_REFERENCES:
            raise ValueError("Saved source-reference count exceeds its storage limit.")
        items = []
        for row in rows:
            try:
                item, _ = self.checked(row)
                items.append(item)
            except ValueError:
                items.append(
                    {
                        "id": row["id"],
                        "caf_sha256": caf_hash,
                        "state": "unavailable",
                        "error": UNAVAILABLE,
                    }
                )
        return {
            "profile": LIST_PROFILE,
            "caf_sha256": caf_hash,
            "references": items,
            "capacity": capacity,
            "scope": SCOPE,
            **FLAGS,
        }

    def report(self, caf_hash, reference_id):
        identifier(caf_hash, 64)
        identifier(reference_id, 32)
        with self.store.connect() as db:
            row = db.execute(
                f"SELECT {self.bounded_columns()} FROM caf_source_references WHERE caf_sha256=? AND id=?",
                (caf_hash, reference_id),
            ).fetchone()
        if row is None:
            raise ValueError("This saved source reference is unavailable for the selected CAF.")
        return self.checked(row)[1]

    def remove(self, caf_hash, reference_id):
        identifier(caf_hash, 64)
        identifier(reference_id, 32)
        with self.store.connect() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            removed = (
                db.execute(
                    "DELETE FROM caf_source_references WHERE caf_sha256=? AND id=?",
                    (caf_hash, reference_id),
                ).rowcount
                == 1
            )
        return {
            "profile": REMOVE_PROFILE,
            "id": reference_id,
            "removed": removed,
            "scope": SCOPE,
            **FLAGS,
        }


def source_reference_router(service, get_caf):
    router = APIRouter(prefix="/api/caf/{caf_id}/source-references")

    @router.get("")
    def list_references(caf_id: str):
        return service.list(caf_id)

    @router.post("")
    def save_reference(caf_id: str, body: SaveReference):
        identifier(caf_id, 64)
        return service.save(get_caf(caf_id), body.model_dump())

    @router.get("/{reference_id}/report")
    def original_report(caf_id: str, reference_id: str):
        raw = service.report(caf_id, reference_id)
        return Response(
            raw,
            media_type="application/json",
            headers={
                "X-Studio-Artifact-Sha256": digest(raw),
                "Content-Disposition": 'attachment; filename="caf-source-reference.json"',
            },
        )

    @router.delete("/{reference_id}")
    def remove_reference(caf_id: str, reference_id: str):
        return service.remove(caf_id, reference_id)

    return router
