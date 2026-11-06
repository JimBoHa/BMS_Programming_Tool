"""Explicit original-source wiring checkpoints; no export or field authority."""

import json
import secrets
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import Field, field_validator, model_validator

from .caf_constant_copy import CafConstantCopies
from .caf_graph import CafGraph
from .caf_scalar_drafts import (
    MAX_CONTEXTS,
    MAX_RECORD_BYTES,
    MAX_REVISION,
    MAX_TOTAL_BYTES,
    Digest,
    ExpectedCheckpoint,
    Identifier,
    Revision,
    caf_hash,
    encoded,
)
from .models import StrictModel
from .moi_identity import seal, sha
from .storage import Conflict

PROFILE = "caf-wiring-draft/1"
SCOPE = "Unfinished original-source wiring selections only. Restore rechecks the original graph and grants no export success, compatibility, compilation or field authority."
FLAGS = {
    "controller_queries": False,
    "controller_writes": False,
    "can_apply": False,
    "graph_compatibility_validated": False,
    "export_success_restored": False,
}
UNAVAILABLE = "Saved wiring checkpoint is unavailable or inconsistent; explicitly remove it before saving new work."
Reference = Annotated[str, Field(strict=True, min_length=1, max_length=512)]
Choice = Annotated[str, Field(strict=True, max_length=512)]
UInt = Annotated[int, Field(strict=True, ge=0, le=65535)]


class WiringSelection(StrictModel):
    diagram_ref: Reference
    wire_index: int = Field(strict=True, ge=0, le=65534)
    connection_count: int = Field(strict=True, ge=1, le=65535)
    old: list[UInt] = Field(min_length=4, max_length=4)
    rewire_source_ref: Choice
    connection_source_ref: Choice
    connection_target_ref: Choice

    @model_validator(mode="after")
    def unfinished(self):
        if not any(
            (self.rewire_source_ref, self.connection_source_ref, self.connection_target_ref)
        ):
            raise ValueError("Choose at least one unfinished wiring source or destination.")
        return self


class WiringEvidence(StrictModel):
    diagram_sha256: Digest
    diagram_class_id: Literal["536", "575"]
    diagram_class_version: Literal["1.0"]
    blocks_sha256: Digest
    source_ref: Reference
    target_ref: Reference
    continuation_flag: bool = Field(strict=True)
    continuation_text: str = Field(strict=True, max_length=8192)


class SavedWiringDraft(StrictModel):
    profile: Literal[PROFILE]
    id: Identifier
    caf_sha256: Digest
    revision: Revision
    created_at: str = Field(strict=True, max_length=80)
    updated_at: str = Field(strict=True, max_length=80)
    selection: WiringSelection
    source_evidence: WiringEvidence
    checkpoint_sha256: Digest

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamp(cls, value):
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError(UNAVAILABLE)
        return value


class SaveWiringDraft(StrictModel):
    selection: WiringSelection
    expected: ExpectedCheckpoint | None


class MatchWiringDraft(StrictModel):
    diagram_ref: Reference
    expected: ExpectedCheckpoint


def context_key(source, diagram):
    caf_hash(source)
    if not isinstance(diagram, str) or not 1 <= len(diagram) <= 512:
        raise ValueError("Choose an exact original CAF diagram reference.")
    return seal({"caf_sha256": source, "diagram_ref": diagram})


def source_evidence(caf, selection):
    graph = CafGraph(caf).diagram(selection.diagram_ref)
    if not graph["observed_version"]:
        raise ValueError("Wiring checkpoints require observed diagram version 1.0.")
    if selection.connection_count != len(graph["connections"]) or selection.wire_index >= len(
        graph["connections"]
    ):
        raise ValueError("Wiring checkpoint count or original occurrence differs from this CAF.")
    wire = graph["connections"][selection.wire_index]
    if selection.old != wire["raw"]:
        raise ValueError("Wiring checkpoint original tuple differs from this CAF.")
    refs = {row["ref"] for row in graph["blocks"]}
    if any(
        ref and ref not in refs
        for ref in (
            selection.rewire_source_ref,
            selection.connection_source_ref,
            selection.connection_target_ref,
        )
    ):
        raise ValueError("An unfinished wiring choice is not an actual block in this diagram.")
    return WiringEvidence(
        diagram_sha256=sha(CafConstantCopies(caf)._raw(caf.objects[selection.diagram_ref])),
        diagram_class_id=graph["class_id"],
        diagram_class_version=graph["class_version"],
        blocks_sha256=seal(
            [
                {k: row[k] for k in ("index", "ref", "class_id", "class_version")}
                for row in graph["blocks"]
            ]
        ),
        source_ref=wire["source_ref"],
        target_ref=wire["target_ref"],
        continuation_flag=wire["continuation"]["flag"],
        continuation_text=wire["continuation"]["text"],
    ).model_dump()


def envelope(operation, source, diagram, *, revalidated=False, **values):
    return {
        "profile": "caf-wiring-draft-" + operation + "/1",
        "caf_sha256": source,
        "diagram_ref": diagram,
        "scope": SCOPE,
        **FLAGS,
        "source_revalidated": revalidated,
        **values,
    }


class CafWiringDrafts:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS caf_wiring_drafts(
                context_sha256 TEXT PRIMARY KEY,id TEXT NOT NULL UNIQUE,revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL,content BLOB NOT NULL,sha256 TEXT NOT NULL
            )""")

    @staticmethod
    def row(db, key):
        return db.execute(
            "SELECT context_sha256,id,revision,created_at,updated_at,sha256,LENGTH(content) AS content_bytes,"
            f"CASE WHEN LENGTH(content) BETWEEN 1 AND {MAX_RECORD_BYTES} THEN content END AS content "
            "FROM caf_wiring_drafts WHERE context_sha256=?",
            (key,),
        ).fetchone()

    @staticmethod
    def capacity(db):
        count, size = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(LENGTH(content)),0) FROM caf_wiring_drafts"
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
            saved = SavedWiringDraft.model_validate(json.loads(raw)).model_dump()
            if (
                encoded(saved) != raw
                or saved["checkpoint_sha256"]
                != seal({k: v for k, v in saved.items() if k != "checkpoint_sha256"})
                or context_key(saved["caf_sha256"], saved["selection"]["diagram_ref"])
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
                raise Conflict("A wiring checkpoint already exists; refresh before replacing it.")
        elif (
            row is None
            or row["id"] != expected.id
            or type(row["revision"]) is not int
            or row["revision"] != expected.revision
        ):
            raise Conflict("The wiring checkpoint changed or was removed; refresh before retrying.")

    def status(self, source, diagram):
        key = context_key(source, diagram)
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
        return envelope("status", source, diagram, checkpoint=saved, capacity=capacity)

    def save(self, caf, request):
        options = SaveWiringDraft.model_validate(request)
        source, diagram = caf_hash(caf.hash), options.selection.diagram_ref
        key = context_key(source, diagram)
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
                    "Wiring checkpoint revision limit reached; remove it before creating a new generation."
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
                    "Wiring checkpoint capacity reached; explicitly remove an unneeded draft first."
                )
            db.execute(
                "INSERT INTO caf_wiring_drafts VALUES(?,?,?,?,?,?,?) ON CONFLICT(context_sha256) DO UPDATE SET id=excluded.id,revision=excluded.revision,created_at=excluded.created_at,updated_at=excluded.updated_at,content=excluded.content,sha256=excluded.sha256",
                (key, saved["id"], revision, saved["created_at"], now, raw, sha(raw)),
            )
        return envelope("save", source, diagram, revalidated=True, checkpoint=saved)

    def restore(self, caf, request):
        options = MatchWiringDraft.model_validate(request)
        source, diagram = caf_hash(caf.hash), options.diagram_ref
        with self.store.connect() as db:
            db.execute("BEGIN")
            row = self.row(db, context_key(source, diagram))
            self.match(row, options.expected)
            saved = self.checked(row)
        if (
            source_evidence(caf, WiringSelection.model_validate(saved["selection"]))
            != saved["source_evidence"]
        ):
            raise ValueError("Saved wiring source evidence differs from the reopened original CAF.")
        return envelope("restore", source, diagram, revalidated=True, checkpoint=saved)

    def remove(self, source, request):
        options = MatchWiringDraft.model_validate(request)
        key = context_key(source, options.diagram_ref)
        with self.store.connect() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            row = self.row(db, key)
            self.match(row, options.expected)
            db.execute("DELETE FROM caf_wiring_drafts WHERE context_sha256=?", (key,))
        return envelope(
            "remove",
            source,
            options.diagram_ref,
            id=options.expected.id,
            revision=options.expected.revision,
            removed=True,
        )


def wiring_draft_router(service, get_caf):
    router = APIRouter(prefix="/api/caf/{source}/wiring-draft")

    def load(source):
        caf_hash(source)
        caf = get_caf(source)
        if caf.hash != source:
            raise ValueError("Select the exact original CAF source hash.")
        return caf

    @router.get("")
    def status(source: str, diagram_ref: Reference):
        return service.status(source, diagram_ref)

    @router.post("")
    def save(source: str, body: SaveWiringDraft):
        return service.save(load(source), body.model_dump())

    @router.post("/restore")
    def restore(source: str, body: MatchWiringDraft):
        return service.restore(load(source), body.model_dump())

    @router.delete("")
    def remove(source: str, body: MatchWiringDraft):
        return service.remove(source, body.model_dump())

    return router
