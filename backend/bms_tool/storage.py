"""Local revision store, optimistic saves, and append-only operation evidence."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import Program


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = self.directory / "studio.sqlite3"
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS revisions(id TEXT, revision INTEGER, name TEXT, content TEXT, sha256 TEXT, created TEXT, PRIMARY KEY(id,revision));
            CREATE TABLE IF NOT EXISTS audit(sequence INTEGER PRIMARY KEY, created TEXT, operation TEXT, detail TEXT, previous_hash TEXT, entry_hash TEXT);
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
            db.execute(
                "INSERT INTO revisions VALUES(?,?,?,?,?,?)",
                (p.id, p.revision, p.name, p.model_dump_json(), p.digest(), created),
            )
        self.record("project.save", {"id": p.id, "revision": p.revision, "sha256": p.digest()})
        return p

    def load(self, id, revision=None):
        with self.connect() as db:
            row = db.execute(
                "SELECT content FROM revisions WHERE id=? "
                + ("AND revision=?" if revision is not None else "")
                + " ORDER BY revision DESC LIMIT 1",
                (id, revision) if revision is not None else (id,),
            ).fetchone()
        if row is None:
            raise ValueError("Project revision not found.")
        return Program.model_validate_json(row["content"])

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
                    "SELECT revision,name,sha256,created FROM revisions WHERE id=? ORDER BY revision DESC",
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
