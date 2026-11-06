"""Explicit source-bound unfinished scalar checkpoints; no CAF export or field authority."""

import copy
import json
import re
import secrets
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import Field, field_validator, model_validator

from .caf import Q
from .models import StrictModel
from .moi_identity import seal, sha
from .storage import Conflict

PROFILE = "caf-scalar-draft/1"
MAX_CONTEXTS = 32
MAX_RECORD_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_PROPOSALS = 1000
MAX_TEXT = 8192
MAX_REVISION = 2147483647
SCOPE = (
    "Source-bound unfinished scalar text only. Saving does not validate proposed values or "
    "export a CAF. Restoration rechecks original field eligibility, but restores no successful "
    "export, review, connection or controller write authority."
)
UNAVAILABLE = (
    "Saved scalar draft evidence is unavailable or inconsistent; "
    "remove the checkpoint before saving new work."
)
FLAGS = {
    "read_only": True,
    "controller_queries": False,
    "controller_writes": False,
    "field_actions": False,
    "can_apply": False,
    "proposal_values_validated": False,
    "export_success_restored": False,
}
Identifier = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{32}$")]
Digest = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
Revision = Annotated[int, Field(strict=True, ge=1, le=MAX_REVISION)]


class ScalarProposal(StrictModel):
    ref: str = Field(strict=True, min_length=1, max_length=512)
    property: str = Field(strict=True, pattern=r"^(0|[1-9][0-9]{0,4})$")
    old: str = Field(strict=True, max_length=MAX_TEXT)
    value: str = Field(strict=True, max_length=MAX_TEXT)

    @field_validator("property")
    @classmethod
    def property_range(cls, value):
        if int(value) > 65535:
            raise ValueError("CAF property identifier exceeds its range.")
        return value


class ProposalSet(StrictModel):
    changes: list[ScalarProposal] = Field(min_length=1, max_length=MAX_PROPOSALS)

    @model_validator(mode="after")
    def unique_proposals(self):
        if len({(row.ref, row.property) for row in self.changes}) != len(self.changes):
            raise ValueError("A scalar checkpoint cannot repeat an object/property proposal.")
        return self


class ExpectedCheckpoint(StrictModel):
    id: Identifier
    revision: Revision


class SaveScalarDraft(ProposalSet):
    expected: ExpectedCheckpoint | None


class MatchScalarDraft(StrictModel):
    expected: ExpectedCheckpoint


class SavedScalarDraft(ProposalSet):
    profile: Literal[PROFILE]
    id: Identifier
    caf_sha256: Digest
    revision: Revision
    created_at: str = Field(strict=True, max_length=80)
    updated_at: str = Field(strict=True, max_length=80)
    checkpoint_sha256: Digest

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamp(cls, value):
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError(UNAVAILABLE)
        return value


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def caf_hash(value):
    if type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Select an exact original CAF hash.")
    return value


def source_fields(caf, changes):
    """Reuse actual scalar admission while retaining every proposed character unparsed."""
    rows = ProposalSet.model_validate({"changes": changes}).changes
    fields = []
    for row in rows:
        obj = caf.objects.get(row.ref)
        if obj is None:
            raise ValueError("The scalar draft object is absent from the original CAF.")
        props = [p for p in obj if p.tag == Q + "property" and p.get("id") == row.property]
        if len(props) != 1 or not caf._editable(props[0], class_id=obj.get("classid")):
            raise ValueError(
                "The scalar draft property is not uniquely editable in the original CAF."
            )
        prop = props[0]
        scalar = caf.scalar(prop)
        if scalar["text"] != row.old:
            raise ValueError("The scalar draft original text differs from the reopened CAF.")
        metadata = {
            "id": row.property,
            "kind": "property",
            "editable": True,
            "scalar": copy.deepcopy(scalar),
        }
        enum = caf._enum_copy(prop, obj.get("classid"))
        if enum is not None:
            metadata["enum_code_copy"] = {**enum, "record_ref": row.ref}
        fields.append({"ref": row.ref, "class_id": obj.get("classid"), "property": metadata})
    return fields


def envelope(kind, source, *, revalidated=False, **values):
    return {
        "profile": f"caf-scalar-draft-{kind}/1",
        "caf_sha256": source,
        **values,
        "scope": SCOPE,
        **FLAGS,
        "source_revalidated": revalidated,
    }


class CafScalarDrafts:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS caf_scalar_drafts(
                caf_sha256 TEXT PRIMARY KEY, id TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                content BLOB NOT NULL, sha256 TEXT NOT NULL
            )""")

    @staticmethod
    def capacity(db):
        count, size = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(LENGTH(content)),0) FROM caf_scalar_drafts"
        ).fetchone()
        return {"count": count, "limit": MAX_CONTEXTS, "bytes": size, "byte_limit": MAX_TOTAL_BYTES}

    @staticmethod
    def row(db, source):
        return db.execute(
            "SELECT caf_sha256,id,revision,created_at,updated_at,sha256,LENGTH(content) AS content_bytes,"
            f"CASE WHEN LENGTH(content) BETWEEN 1 AND {MAX_RECORD_BYTES} THEN content END AS content "
            "FROM caf_scalar_drafts WHERE caf_sha256=?",
            (source,),
        ).fetchone()

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
            data = SavedScalarDraft.model_validate(json.loads(raw)).model_dump()
            if (
                encoded(data) != raw
                or data["checkpoint_sha256"]
                != seal({k: v for k, v in data.items() if k != "checkpoint_sha256"})
                or any(
                    data[key] != row[key] or type(data[key]) is not type(row[key])
                    for key in ("caf_sha256", "id", "revision", "created_at", "updated_at")
                )
            ):
                raise ValueError(UNAVAILABLE)
            return data
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
                raise Conflict(
                    "A checkpoint already exists. Refresh its current generation and revision before replacing it."
                )
        elif (
            row is None
            or row["id"] != expected.id
            or type(row["revision"]) is not int
            or row["revision"] != expected.revision
        ):
            raise Conflict(
                "The saved scalar checkpoint changed or was removed. Refresh before retrying."
            )

    def status(self, source):
        caf_hash(source)
        with self.store.connect() as db:
            db.execute("BEGIN")
            row, capacity = self.row(db, source), self.capacity(db)
        saved = None
        if row is not None:
            try:
                saved = self.checked(row)
            except ValueError:
                saved = {
                    "state": "unavailable",
                    "id": row["id"]
                    if type(row["id"]) is str and re.fullmatch(r"[a-f0-9]{32}", row["id"])
                    else None,
                    "revision": row["revision"]
                    if type(row["revision"]) is int and 1 <= row["revision"] <= MAX_REVISION
                    else None,
                    "error": UNAVAILABLE,
                }
        return envelope("status", source, checkpoint=saved, capacity=capacity)

    def save(self, caf, request):
        options = SaveScalarDraft.model_validate(request)
        changes = [row.model_dump() for row in options.changes]
        source = caf_hash(caf.hash)
        source_fields(caf, changes)
        with self.store.connect() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            prior = self.row(db, source)
            self.match(prior, options.expected)
            previous = self.checked(prior) if prior is not None else None
            revision = previous["revision"] + 1 if previous is not None else 1
            if revision > MAX_REVISION:
                raise ValueError(
                    "The checkpoint revision limit was reached; explicitly remove it before creating a new generation."
                )
            now = datetime.now(UTC).isoformat()
            body = {
                "profile": PROFILE,
                "id": previous["id"] if previous else secrets.token_hex(16),
                "caf_sha256": source,
                "revision": revision,
                "created_at": previous["created_at"] if previous else now,
                "updated_at": now,
                "changes": changes,
            }
            saved = {**body, "checkpoint_sha256": seal(body)}
            raw = encoded(saved)
            if len(raw) > MAX_RECORD_BYTES:
                raise ValueError("The unfinished scalar checkpoint exceeds its content size limit.")
            capacity = self.capacity(db)
            if (prior is None and capacity["count"] >= MAX_CONTEXTS) or capacity["bytes"] - (
                prior["content_bytes"] if prior else 0
            ) + len(raw) > MAX_TOTAL_BYTES:
                raise ValueError(
                    "Scalar checkpoint capacity reached. Explicitly remove an unneeded saved draft first."
                )
            db.execute(
                "INSERT INTO caf_scalar_drafts VALUES(?,?,?,?,?,?,?) ON CONFLICT(caf_sha256) DO UPDATE SET id=excluded.id,revision=excluded.revision,created_at=excluded.created_at,updated_at=excluded.updated_at,content=excluded.content,sha256=excluded.sha256",
                (source, saved["id"], revision, saved["created_at"], now, raw, sha(raw)),
            )
        return envelope("save", source, revalidated=True, checkpoint=saved)

    def restore(self, caf, request):
        options = MatchScalarDraft.model_validate(request)
        source = caf_hash(caf.hash)
        with self.store.connect() as db:
            db.execute("BEGIN")
            row = self.row(db, source)
            self.match(row, options.expected)
            saved = self.checked(row)
        fields = source_fields(caf, saved["changes"])
        return envelope("restore", source, revalidated=True, checkpoint=saved, fields=fields)

    def remove(self, source, request):
        caf_hash(source)
        options = MatchScalarDraft.model_validate(request)
        with self.store.connect() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            row = self.row(db, source)
            self.match(row, options.expected)
            db.execute("DELETE FROM caf_scalar_drafts WHERE caf_sha256=?", (source,))
        return envelope(
            "remove",
            source,
            id=options.expected.id,
            revision=options.expected.revision,
            removed=True,
        )


def scalar_draft_router(service, get_caf):
    router = APIRouter(prefix="/api/caf/{source}/scalar-draft")

    @router.get("")
    def status(source: str):
        return service.status(source)

    @router.post("")
    def save(source: str, body: SaveScalarDraft):
        caf_hash(source)
        return service.save(get_caf(source), body.model_dump())

    @router.post("/restore")
    def restore(source: str, body: MatchScalarDraft):
        caf_hash(source)
        return service.restore(get_caf(source), body.model_dump())

    @router.delete("")
    def remove(source: str, body: MatchScalarDraft):
        return service.remove(source, body.model_dump())

    return router
