"""Durable BBMD before-state, dispatch intent and observation receipts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path

from .notification_outbox import _OwnerLock

MAX_RECORDS = 512
MAX_RECEIPT_BYTES = 512 * 1024


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    )


class BbmdAdminStore:
    def __init__(self, directory):
        self.directory = Path(directory) / "bbmd-administration"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.db = self.directory / "receipts.sqlite3"
        try:
            if not stat.S_ISREG(self.db.lstat().st_mode):
                raise ValueError("BBMD receipts require a regular SQLite file.")
        except FileNotFoundError:
            pass
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,body TEXT NOT NULL,sha256 TEXT NOT NULL,created TEXT NOT NULL)"
            )
        self.db.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=0.2)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def claim(self):
        try:
            return _OwnerLock(self.directory / "writer.lock")
        except ValueError as exc:
            raise ValueError(
                "BBMD administration writer unavailable; another process or invalid lock file."
            ) from exc

    def save(self, receipt):
        body = encoded(receipt)
        if len(body.encode()) > MAX_RECEIPT_BYTES:
            raise ValueError("BBMD receipt exceeds its bounded storage profile.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM receipts WHERE id=?", (receipt["id"],)).fetchone() is None:
                if db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] >= MAX_RECORDS:
                    raise ValueError(
                        "BBMD receipt capacity reached; no new changes accepted. Export history for review."
                    )
            db.execute(
                "INSERT INTO receipts(id,body,sha256,created) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,sha256=excluded.sha256",
                (
                    receipt["id"],
                    body,
                    hashlib.sha256(body.encode()).hexdigest(),
                    receipt["created_at"],
                ),
            )

    def get(self, identifier):
        if (
            not isinstance(identifier, str)
            or len(identifier) != 29
            or not identifier.startswith("bbma-")
            or any(c not in "0123456789abcdef" for c in identifier[5:])
        ):
            raise ValueError("Invalid BBMD administration receipt identifier.")
        with self.connect() as db:
            row = db.execute(
                "SELECT id,sha256,CASE WHEN length(CAST(body AS BLOB))<=? THEN body ELSE NULL END AS body FROM receipts WHERE id=?",
                (MAX_RECEIPT_BYTES, identifier),
            ).fetchone()
        if row is None:
            raise ValueError("BBMD administration receipt not found.")
        if row["body"] is None:
            raise ValueError("BBMD receipt exceeds its bounded storage profile.")
        if hashlib.sha256(row["body"].encode()).hexdigest() != row["sha256"]:
            raise ValueError("BBMD receipt integrity check failed.")
        result = json.loads(row["body"])
        if result.get("id") != identifier:
            raise ValueError("BBMD receipt identity differs from its storage key.")
        return result

    def ids(self):
        with self.connect() as db:
            return [
                row[0]
                for row in db.execute(
                    "SELECT id FROM receipts ORDER BY created DESC,id DESC LIMIT ?", (MAX_RECORDS,)
                )
            ]
