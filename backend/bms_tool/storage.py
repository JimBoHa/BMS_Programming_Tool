"""Local revision store, optimistic saves, and append-only operation evidence."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import Program, canonical

LEGACY_HASH_FORMAT = "model-json/1"
CANONICAL_HASH_FORMAT = "canonical-json/1"


class Conflict(ValueError):
    pass


class RevisionIntegrityError(ValueError):
    """A stored revision cannot be verified using its recorded hash algorithm."""


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = self.directory / "studio.sqlite3"
        with self.connect() as db:
            # Serialize schema inspection and migration across concurrent app starts.
            # executescript() implicitly commits, so keep these as individual statements.
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                CREATE TABLE IF NOT EXISTS revisions(
                    id TEXT, revision INTEGER, name TEXT, content TEXT, sha256 TEXT,
                    created TEXT, hash_format TEXT NOT NULL DEFAULT 'model-json/1',
                    PRIMARY KEY(id,revision)
                )
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(revisions)")}
            if "hash_format" not in columns:
                # The default labels existing rows without rewriting their content or hash.
                db.execute(
                    "ALTER TABLE revisions ADD COLUMN hash_format TEXT NOT NULL "
                    "DEFAULT 'model-json/1'"
                )
            db.execute("""
                CREATE TABLE IF NOT EXISTS audit(
                    sequence INTEGER PRIMARY KEY, created TEXT, operation TEXT,
                    detail TEXT, previous_hash TEXT, entry_hash TEXT
                )
            """)

    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def save(self, program, expected_revision=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT MAX(revision) AS r FROM revisions WHERE id=?", (program.id,)
            ).fetchone()
            current = row["r"] or 0
            if expected_revision is not None and expected_revision != current:
                raise Conflict(
                    f"Expected revision {expected_revision}; current revision is {current}. Reload before saving."
                )
            p = program.model_copy(deep=True)
            p.revision = current + 1
            created = datetime.now(UTC).isoformat()
            content = p.model_dump_json()
            digest = hashlib.sha256(canonical(p)).hexdigest()
            db.execute(
                "INSERT INTO revisions(id,revision,name,content,sha256,created,hash_format) "
                "VALUES(?,?,?,?,?,?,?)",
                (p.id, p.revision, p.name, content, digest, created, CANONICAL_HASH_FORMAT),
            )
        self.record(
            "project.save",
            {
                "id": p.id,
                "revision": p.revision,
                "sha256": digest,
                "hash_format": CANONICAL_HASH_FORMAT,
            },
        )
        return p

    def load(self, id, revision=None):
        with self.connect() as db:
            row = db.execute(
                "SELECT id,revision,name,content,sha256,hash_format FROM revisions WHERE id=? "
                + ("AND revision=?" if revision is not None else "")
                + " ORDER BY revision DESC LIMIT 1",
                (id, revision) if revision is not None else (id,),
            ).fetchone()
        if row is None:
            raise ValueError("Project revision not found.")
        hash_format = row["hash_format"]
        if hash_format not in (LEGACY_HASH_FORMAT, CANONICAL_HASH_FORMAT):
            raise RevisionIntegrityError(
                f"Unsupported stored revision hash format: {hash_format!r}."
            )
        try:
            content = row["content"]
            if not isinstance(content, str):
                raise ValueError("Stored content is not text.")
            program = Program.model_validate_json(content)
            verified = (
                hashlib.sha256(content.encode()).hexdigest()
                if hash_format == LEGACY_HASH_FORMAT
                else hashlib.sha256(canonical(program)).hexdigest()
            )
        except (ValueError, UnicodeError) as exc:
            raise RevisionIntegrityError("Stored project revision content is invalid.") from exc
        if verified != row["sha256"]:
            raise RevisionIntegrityError(
                "Stored project revision failed integrity verification: hash mismatch."
            )
        if (program.id, program.revision, program.name) != (
            row["id"],
            row["revision"],
            row["name"],
        ):
            raise RevisionIntegrityError(
                "Stored project revision identity does not match its content."
            )
        return program

    def projects(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,MAX(revision) AS revision,name,created FROM revisions GROUP BY id ORDER BY created DESC"
                )
            ]

    def versions(self, id):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT revision,name,sha256,created,hash_format FROM revisions "
                    "WHERE id=? ORDER BY revision DESC",
                    (id,),
                )
            ]

    def record(self, operation, detail):
        content = json.dumps(detail, sort_keys=True, allow_nan=False)
        created = datetime.now(UTC).isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT entry_hash FROM audit ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous = row[0] if row else "0" * 64
            digest = hashlib.sha256((previous + created + operation + content).encode()).hexdigest()
            db.execute(
                "INSERT INTO audit(created,operation,detail,previous_hash,entry_hash) VALUES(?,?,?,?,?)",
                (created, operation, content, previous, digest),
            )
        return digest

    def audit(self):
        with self.connect() as db:
            return [
                dict(r) for r in db.execute("SELECT * FROM audit ORDER BY sequence DESC LIMIT 500")
            ]
