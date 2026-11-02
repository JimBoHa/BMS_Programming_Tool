"""Reversible local catalog changes; immutable capture paths and receipts stay intact."""

import json
from typing import Literal

from pydantic import Field

from .application_store import checked, encoded, native_storage_profile, read_private, utc
from .models import StrictModel
from .moi_identity import seal

PROFILE = "native-backup-lifecycle/1"
ACTIVE_LIMIT = 128
ARCHIVE_LIMIT = 1024
TRANSITION_LIMIT = 1024
SCOPE = (
    "Local backup catalog only. Archiving retains the original files at their original paths "
    "and preserves transfer and recovery references. It frees an active slot, not disk space. "
    "Restoring makes a backup selectable again; it never restores a controller."
)


class BackupLibraryQuery(StrictModel):
    state: Literal["active", "archived"] = "active"
    query: str = Field(default="", max_length=256, strict=True)
    offset: int = Field(default=0, ge=0, le=ARCHIVE_LIMIT, strict=True)
    limit: int = Field(default=32, ge=1, le=64, strict=True)


class BackupLifecycleChange(StrictModel):
    capture_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_revision: int = Field(ge=0, le=TRANSITION_LIMIT, strict=True)
    action: Literal["archive", "restore"]


class LifecycleEvidence(StrictModel):
    profile: Literal["native-backup-lifecycle/1"]
    capture_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: int = Field(ge=1, le=TRANSITION_LIMIT, strict=True)
    archived: bool = Field(strict=True)
    changed_at: str = Field(min_length=1, max_length=64, strict=True)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def lifecycle_states(db):
    rows = db.execute(
        "SELECT l.capture_id,l.revision,l.body FROM application_capture_lifecycle l "
        "JOIN (SELECT capture_id,MAX(revision) revision FROM application_capture_lifecycle "
        "GROUP BY capture_id) latest USING(capture_id,revision)"
    )
    states = {}
    for capture_id, revision, raw in rows:
        if len(raw) > 2048:
            raise ValueError("Native backup catalog evidence exceeds its size limit.")
        row = LifecycleEvidence.model_validate_json(raw).model_dump()
        body = {k: v for k, v in row.items() if k != "evidence_sha256"}
        if (
            row["capture_id"] != capture_id
            or row["revision"] != revision
            or row["archived"] != bool(revision % 2)
            or seal(body) != row["evidence_sha256"]
        ):
            raise ValueError("Native backup catalog evidence integrity check failed.")
        states[capture_id] = row
    if sum(row["archived"] for row in states.values()) > ARCHIVE_LIMIT:
        raise ValueError("Native backup archive exceeds its retained source limit.")
    return states


class NativeBackupLifecycle:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def envelope():
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "controller_queries": False,
            "field_actions": False,
            "active_limit": ACTIVE_LIMIT,
            "archive_limit": ARCHIVE_LIMIT,
            "storage": native_storage_profile(),
        }

    def manifest(self, capture_id):
        folder = self.storage.capture_folder(capture_id)
        manifest = checked(read_private(folder / "manifest.json", 128 * 1024))
        if manifest["id"] != capture_id or set(manifest["files"]) != {"3", "11", "12"}:
            raise ValueError("Native backup manifest does not match its retained source.")
        return manifest

    @staticmethod
    def entry(manifest, state=None):
        if state and state["snapshot_sha256"] != manifest["evidence_sha256"]:
            raise ValueError("Native backup catalog source evidence changed.")
        return {
            **{
                key: manifest.get(key)
                for key in (
                    "id",
                    "captured_at",
                    "target",
                    "device",
                    "identity",
                    "source_identity_matches",
                    "evidence_sha256",
                    "files",
                )
            },
            "revision": state["revision"] if state else 0,
            "archived": state["archived"] if state else False,
            "changed_at": state["changed_at"] if state else None,
            "file_bytes": sum(row["bytes"] for row in manifest["files"].values()),
        }

    def list(self, request):
        options = BackupLibraryQuery.model_validate(request)
        with self.storage.store.connect(timeout=0.25) as db:
            # Serialize the bounded catalog snapshot with capture publication and transitions.
            db.execute("BEGIN IMMEDIATE")
            states = lifecycle_states(db)
            folders = list(self.storage.directory.glob("*/manifest.json"))
            if len(folders) > ACTIVE_LIMIT + ARCHIVE_LIMIT:
                raise ValueError("Native backup library exceeds its retained source limits.")
            rows = [
                self.entry(self.manifest(p.parent.name), states.get(p.parent.name)) for p in folders
            ]
        active = sum(not row["archived"] for row in rows)
        if active > ACTIVE_LIMIT:
            raise ValueError("Native backup library exceeds its active source limit.")
        query = options.query.casefold()
        selected = sorted(
            (
                row
                for row in rows
                if row["archived"] == (options.state == "archived")
                and query in json.dumps(row, ensure_ascii=False).casefold()
            ),
            key=lambda row: (row["captured_at"], row["id"]),
            reverse=True,
        )
        return {
            **self.envelope(),
            "read_only": True,
            "state": options.state,
            "query": options.query,
            "offset": options.offset,
            "limit": options.limit,
            "total": len(selected),
            "active_count": active,
            "archived_count": len(rows) - active,
            "has_more": options.offset + options.limit < len(selected),
            "backups": selected[options.offset : options.offset + options.limit],
        }

    def change(self, request):
        options = BackupLifecycleChange.model_validate(request)
        with self.storage.store.connect(timeout=0.25) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            states = lifecycle_states(db)
            previous = states.get(options.capture_id)
            revision = previous["revision"] if previous else 0
            archived = previous["archived"] if previous else False
            if revision != options.expected_revision or archived == (options.action == "archive"):
                raise ValueError(
                    "Native backup catalog changed; refresh and select the backup again."
                )
            if revision >= TRANSITION_LIMIT:
                raise ValueError("This backup reached its retained catalog transition limit.")
            manifest, _ = self.storage.load(options.capture_id)
            if manifest["evidence_sha256"] != options.snapshot_sha256:
                raise ValueError(
                    "Native backup source evidence changed; reopen its original snapshot."
                )
            self.entry(manifest, previous)
            if options.action == "archive":
                if sum(row["archived"] for row in states.values()) >= ARCHIVE_LIMIT:
                    raise ValueError(
                        "Native backup archive is full; retain existing sources and export copies."
                    )
            elif len(self.storage.active_folders(db)) >= ACTIVE_LIMIT:
                raise ValueError(
                    "Active native backup storage is full; archive another backup before restoring."
                )
            body = {
                "profile": PROFILE,
                "capture_id": options.capture_id,
                "snapshot_sha256": options.snapshot_sha256,
                "revision": revision + 1,
                "archived": options.action == "archive",
                "changed_at": utc(),
            }
            row = {**body, "evidence_sha256": seal(body)}
            db.execute(
                "INSERT INTO application_capture_lifecycle VALUES(?,?,?)",
                (options.capture_id, revision + 1, encoded(row)),
            )
        return {
            **self.envelope(),
            "local_state_changed": True,
            "transition": row,
            "backup": self.entry(manifest, row),
        }
