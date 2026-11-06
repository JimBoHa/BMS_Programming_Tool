"""Explicit original-source recorded-copy drafts; no compilation or field authority."""

import json
import secrets
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field, field_validator

from .caf_boolean_copy import CafBooleanCopies
from .caf_boolean_logic_copy import CafBooleanLogicCopies
from .caf_comparison_service import CafComparisonService
from .caf_constant_api import Reference
from .caf_constant_copy import CafConstantCopies
from .caf_enum_copy import CafEnumCopies
from .caf_float_multiplexer_service import CafFloatMultiplexerService
from .caf_math_copy import CafMathCopies
from .caf_reliability_copy import CafReliabilityCopies
from .caf_scalar_drafts import (
    MAX_CONTEXTS,
    MAX_RECORD_BYTES,
    MAX_REVISION,
    MAX_TEXT,
    MAX_TOTAL_BYTES,
    Digest,
    ExpectedCheckpoint,
    Identifier,
    Revision,
    caf_hash,
    encoded,
)
from .caf_timer_copy import CafTimerCopies
from .models import StrictModel
from .moi_identity import seal, sha
from .storage import Conflict

PROFILE = "caf-creation-draft/1"
SCOPE = (
    "Unfinished coordinates for one original recorded CAF copy prototype only. Restoration "
    "rechecks its source inspector, but grants no coordinate validation, export success, "
    "compilation, application association or controller authority."
)
FLAGS = {
    "controller_queries": False,
    "controller_writes": False,
    "can_apply": False,
    "coordinates_validated": False,
    "export_success_restored": False,
}
UNAVAILABLE = "Saved copy checkpoint is unavailable or inconsistent; explicitly remove it before saving new work."
Kind = Literal[
    "float",
    "boolean",
    "enumeration",
    "comparison",
    "math",
    "timer",
    "booleanLogic",
    "reliability",
    "multiplexer",
]
INSPECTORS = {
    "float": CafConstantCopies,
    "boolean": CafBooleanCopies,
    "enumeration": CafEnumCopies,
    "comparison": CafComparisonService,
    "math": CafMathCopies,
    "timer": CafTimerCopies,
    "booleanLogic": CafBooleanLogicCopies,
    "reliability": CafReliabilityCopies,
    "multiplexer": CafFloatMultiplexerService,
}


class CreationContext(StrictModel):
    kind: Kind
    diagram_ref: Reference
    prototype_ref: Reference


class CreationSelection(CreationContext):
    selection_sha256: Digest
    x: str = Field(strict=True, max_length=MAX_TEXT)
    y: str = Field(strict=True, max_length=MAX_TEXT)


class CreationEvidence(StrictModel):
    source_profile: str = Field(strict=True, min_length=1, max_length=256)
    selection_sha256: Digest
    diagram_sha256: Digest
    prototype_sha256: Digest


class SavedCreationDraft(StrictModel):
    profile: Literal[PROFILE]
    id: Identifier
    caf_sha256: Digest
    revision: Revision
    created_at: str = Field(strict=True, max_length=80)
    updated_at: str = Field(strict=True, max_length=80)
    selection: CreationSelection
    source_evidence: CreationEvidence
    checkpoint_sha256: Digest

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamp(cls, value):
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError(UNAVAILABLE)
        return value


class SaveCreationDraft(StrictModel):
    selection: CreationSelection
    expected: ExpectedCheckpoint | None


class MatchCreationDraft(CreationContext):
    expected: ExpectedCheckpoint


def context_key(source, context):
    source = caf_hash(source)
    context = CreationContext.model_validate(context).model_dump()
    return seal({"caf_sha256": source, **context})


def selection_context(selection):
    return {k: selection[k] for k in CreationContext.model_fields}


def source_evidence(caf, selection):
    """Use the installed source-family dispatcher, never its compile/export method."""
    source = INSPECTORS[selection.kind](caf).inspect(selection.diagram_ref, selection.prototype_ref)
    if (
        source["source_sha256"] != caf.hash
        or source["selection_sha256"] != selection.selection_sha256
    ):
        raise ValueError(
            "The copy draft inspector evidence changed; inspect the original prototype again."
        )
    return CreationEvidence(
        source_profile=source["profile"],
        selection_sha256=source["selection_sha256"],
        diagram_sha256=source["diagram_sha256"],
        prototype_sha256=source["prototype_sha256"],
    ).model_dump()


def envelope(operation, source, context, *, revalidated=False, **values):
    return {
        "profile": "caf-creation-draft-" + operation + "/1",
        "caf_sha256": caf_hash(source),
        "context": CreationContext.model_validate(context).model_dump(),
        "scope": SCOPE,
        **FLAGS,
        "source_revalidated": revalidated,
        **values,
    }


class CafCreationDrafts:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS caf_creation_drafts(
                context_sha256 TEXT PRIMARY KEY,id TEXT NOT NULL UNIQUE,revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL,content BLOB NOT NULL,sha256 TEXT NOT NULL
            )""")

    @staticmethod
    def row(db, key):
        return db.execute(
            "SELECT context_sha256,id,revision,created_at,updated_at,sha256,LENGTH(content) AS content_bytes,"
            f"CASE WHEN LENGTH(content) BETWEEN 1 AND {MAX_RECORD_BYTES} THEN content END AS content "
            "FROM caf_creation_drafts WHERE context_sha256=?",
            (key,),
        ).fetchone()

    @staticmethod
    def capacity(db):
        count, size = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(LENGTH(content)),0) FROM caf_creation_drafts"
        ).fetchone()
        return {"count": count, "limit": MAX_CONTEXTS, "bytes": size, "byte_limit": MAX_TOTAL_BYTES}

    @staticmethod
    def checked(row):
        try:
            raw = row["content"]
            if (
                type(raw) is not bytes
                or not 1 <= len(raw) <= MAX_RECORD_BYTES
                or sha(raw) != row["sha256"]
            ):
                raise ValueError(UNAVAILABLE)
            saved = SavedCreationDraft.model_validate(json.loads(raw)).model_dump()
            if (
                encoded(saved) != raw
                or saved["checkpoint_sha256"]
                != seal({k: v for k, v in saved.items() if k != "checkpoint_sha256"})
                or saved["selection"]["selection_sha256"]
                != saved["source_evidence"]["selection_sha256"]
                or context_key(saved["caf_sha256"], selection_context(saved["selection"]))
                != row["context_sha256"]
                or any(
                    saved[k] != row[k] or type(saved[k]) is not type(row[k])
                    for k in ("id", "revision", "created_at", "updated_at")
                )
            ):
                raise ValueError(UNAVAILABLE)
            return saved
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RecursionError,
            OverflowError,
        ) as exc:
            raise ValueError(UNAVAILABLE) from exc

    @staticmethod
    def match(row, expected):
        if expected is None:
            if row is not None:
                raise Conflict("A copy checkpoint already exists; refresh before replacing it.")
        elif (
            row is None
            or row["id"] != expected.id
            or type(row["revision"]) is not int
            or row["revision"] != expected.revision
        ):
            raise Conflict("The copy checkpoint changed or was removed; refresh before retrying.")

    def status(self, source, context):
        key = context_key(source, context)
        with self.store.connect() as db:
            db.execute("BEGIN")
            row, capacity = self.row(db, key), self.capacity(db)
        saved = None
        if row is not None:
            try:
                saved = self.checked(row)
            except ValueError:
                saved = {
                    "state": "unavailable",
                    "id": row["id"]
                    if isinstance(row["id"], str)
                    and len(row["id"]) == 32
                    and all(c in "0123456789abcdef" for c in row["id"])
                    else None,
                    "revision": row["revision"]
                    if type(row["revision"]) is int and 1 <= row["revision"] <= MAX_REVISION
                    else None,
                    "error": UNAVAILABLE,
                }
        return envelope("status", source, context, checkpoint=saved, capacity=capacity)

    def save(self, caf, request):
        options = SaveCreationDraft.model_validate(request)
        source = caf_hash(caf.hash)
        context = selection_context(options.selection.model_dump())
        key = context_key(source, context)
        evidence = source_evidence(caf, options.selection)
        with self.store.connect() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            prior = self.row(db, key)
            self.match(prior, options.expected)
            previous = self.checked(prior) if prior is not None else None
            revision = previous["revision"] + 1 if previous else 1
            if revision > MAX_REVISION:
                raise ValueError(
                    "Copy checkpoint revision limit reached; remove it before creating a new generation."
                )
            now = datetime.now(UTC).isoformat()
            body = {
                "profile": PROFILE,
                "id": previous["id"] if previous else secrets.token_hex(16),
                "caf_sha256": source,
                "revision": revision,
                "created_at": previous["created_at"] if previous else now,
                "updated_at": now,
                "selection": options.selection.model_dump(),
                "source_evidence": evidence,
            }
            saved = {**body, "checkpoint_sha256": seal(body)}
            raw = encoded(saved)
            capacity = self.capacity(db)
            if (
                len(raw) > MAX_RECORD_BYTES
                or (prior is None and capacity["count"] >= MAX_CONTEXTS)
                or capacity["bytes"] - (prior["content_bytes"] if prior else 0) + len(raw)
                > MAX_TOTAL_BYTES
            ):
                raise ValueError(
                    "Copy checkpoint capacity reached; explicitly remove an unneeded draft first."
                )
            db.execute(
                "INSERT INTO caf_creation_drafts VALUES(?,?,?,?,?,?,?) ON CONFLICT(context_sha256) DO UPDATE SET id=excluded.id,revision=excluded.revision,created_at=excluded.created_at,updated_at=excluded.updated_at,content=excluded.content,sha256=excluded.sha256",
                (key, saved["id"], revision, saved["created_at"], now, raw, sha(raw)),
            )
        return envelope("save", source, context, revalidated=True, checkpoint=saved)

    def _load(self, source, request):
        options = MatchCreationDraft.model_validate(request)
        context = options.model_dump(exclude={"expected"})
        with self.store.connect() as db:
            db.execute("BEGIN")
            row = self.row(db, context_key(source, context))
            self.match(row, options.expected)
            saved = self.checked(row)
            raw = row["content"]
        return context, saved, raw

    def restore(self, caf, request):
        context, saved, _ = self._load(caf.hash, request)
        if (
            source_evidence(caf, CreationSelection.model_validate(saved["selection"]))
            != saved["source_evidence"]
        ):
            raise ValueError("Saved copy source evidence differs from the reopened original CAF.")
        return envelope("restore", caf.hash, context, revalidated=True, checkpoint=saved)

    def report(self, source, request):
        return self._load(source, request)[2]

    def remove(self, source, request):
        options = MatchCreationDraft.model_validate(request)
        context = options.model_dump(exclude={"expected"})
        key = context_key(source, context)
        with self.store.connect() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            row = self.row(db, key)
            self.match(row, options.expected)
            db.execute("DELETE FROM caf_creation_drafts WHERE context_sha256=?", (key,))
        return envelope(
            "remove",
            source,
            context,
            id=options.expected.id,
            revision=options.expected.revision,
            removed=True,
        )


def creation_draft_router(service, get_caf):
    router = APIRouter(prefix="/api/caf/{source}/creation-draft")

    def load(source):
        caf_hash(source)
        caf = get_caf(source)
        if caf.hash != source:
            raise ValueError("Select the exact original CAF source hash.")
        return caf

    @router.get("")
    def status(source: str, kind: Kind, diagram_ref: Reference, prototype_ref: Reference):
        return service.status(
            source, {"kind": kind, "diagram_ref": diagram_ref, "prototype_ref": prototype_ref}
        )

    @router.post("")
    def save(source: str, body: SaveCreationDraft):
        return service.save(load(source), body.model_dump())

    @router.post("/restore")
    def restore(source: str, body: MatchCreationDraft):
        return service.restore(load(source), body.model_dump())

    @router.post("/report")
    def report(source: str, body: MatchCreationDraft):
        raw = service.report(source, body.model_dump())
        return Response(
            raw,
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="caf-copy-checkpoint.json"',
                "X-Studio-Artifact-Sha256": sha(raw),
            },
        )

    @router.delete("")
    def remove(source: str, body: MatchCreationDraft):
        return service.remove(source, body.model_dump())

    return router
