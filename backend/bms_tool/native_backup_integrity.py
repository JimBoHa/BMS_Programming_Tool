"""Bounded, read-only observations of original native backup storage.

Diagnostics do not repair evidence, change catalog state or qualify a controller
restore. Damaged or unpublished sources remain separate from usable captures.
"""

import errno
import os
import re

from pydantic import Field

from .application_store import checked, read_private, retained_directory, utc
from .models import StrictModel
from .moi_identity import seal, sha
from .native_backup_lifecycle import ACTIVE_LIMIT, ARCHIVE_LIMIT

PROFILE = "native-backup-integrity/1"
ENTRY_LIMIT = ACTIVE_LIMIT + ARCHIVE_LIMIT
CAPTURE = re.compile(r"^[a-f0-9]{32}$")
HASH = re.compile(r"^[a-f0-9]{64}$")
READ_ERRORS = (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError)
SCOPE = (
    "Read-only local storage observations. A manifest match is not proof of a complete "
    "controller backup, program compatibility or restore acceptance. No files, catalog "
    "state, receipts or controller settings are changed. Retain damaged originals."
)


class BackupStorageQuery(StrictModel):
    query: str = Field(default="", max_length=256, strict=True)
    offset: int = Field(default=0, ge=0, le=ENTRY_LIMIT, strict=True)
    limit: int = Field(default=16, ge=1, le=32, strict=True)


class BackupIntegrityCheck(StrictModel):
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$", strict=True)
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)


def problem(error):
    if isinstance(error, OSError):
        if error.errno == errno.ENOENT:
            return "An original file or folder is missing or unpublished."
        if error.errno in (errno.EACCES, errno.EPERM):
            return "An original file or folder cannot be read with current permissions."
        return "The original file or folder could not be read safely."
    if isinstance(error, ValueError) and not isinstance(error, UnicodeError):
        return str(error)[:256]
    return "The original manifest has an unsupported or malformed structure."


def manifest_at(storage, capture_id):
    folder = storage.capture_folder(capture_id)
    raw = read_private(folder / "manifest.json", 128 * 1024)
    manifest = checked(raw)
    if manifest.get("id") != capture_id or set(manifest.get("files", {})) != {"3", "11", "12"}:
        raise ValueError("Native backup manifest does not match its retained source.")
    for value in manifest["files"].values():
        if (
            not isinstance(value, dict)
            or type(value.get("bytes")) is not int
            or not 1 <= value["bytes"] <= 2 * 1024 * 1024
            or not isinstance(value.get("sha256"), str)
            or not HASH.fullmatch(value["sha256"])
        ):
            raise ValueError("Original manifest file sizes or hashes are invalid.")
    return folder, raw, manifest


def source(manifest):
    return {
        key: manifest.get(key)
        for key in ("captured_at", "device", "target", "identity", "source_identity_matches")
    }


class NativeBackupIntegrity:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def envelope():
        return {
            "profile": PROFILE,
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "storage_mutations": False,
            "scope": SCOPE,
        }

    def entry(self, name):
        row = {
            "entry_name": name,
            "capture_id": name if CAPTURE.fullmatch(name) else None,
            "status": "unrecognized_entry",
            "problem": "This entry is not a native capture identifier; its contents were not read.",
            "manifest_sha256": None,
            "snapshot_sha256": None,
            "source": None,
            "original_files_checked": False,
        }
        if row["capture_id"] is None:
            return row
        try:
            _, raw, manifest = manifest_at(self.storage, name)
        except READ_ERRORS as error:
            return {**row, "status": "manifest_unavailable", "problem": problem(error)}
        return {
            **row,
            "status": "manifest_available",
            "problem": None,
            "manifest_sha256": sha(raw),
            "snapshot_sha256": manifest["evidence_sha256"],
            "source": source(manifest),
        }

    def inventory(self, request):
        options = BackupStorageQuery.model_validate(request)
        retained_directory(self.storage.directory)
        names = []
        complete = True
        # Include unpublished and unrecognized entries, not just manifest globs.
        # Stop before reading an unbounded directory; truncation is explicit.
        with os.scandir(self.storage.directory) as entries:
            for entry in entries:
                if len(names) == ENTRY_LIMIT:
                    complete = False
                    break
                names.append(entry.name)
        selected = sorted(name for name in names if options.query.casefold() in name.casefold())
        body = {
            **self.envelope(),
            "kind": "storage_inventory",
            "observed_at": utc(),
            "entry_limit": ENTRY_LIMIT,
            "scan_complete": complete,
            "observed_entries": len(names),
            "query": options.query,
            "offset": options.offset,
            "limit": options.limit,
            "matching_observed_entries": len(selected),
            "has_more": options.offset + options.limit < len(selected),
            "entries": [
                self.entry(name)
                for name in selected[options.offset : options.offset + options.limit]
            ],
        }
        return {**body, "report_sha256": seal(body)}

    def check(self, request):
        options = BackupIntegrityCheck.model_validate(request)
        try:
            folder, raw, manifest = manifest_at(self.storage, options.capture_id)
        except READ_ERRORS as error:
            raise ValueError("Original manifest unavailable. " + problem(error)) from None
        if sha(raw) != options.manifest_sha256:
            raise ValueError(
                "Original manifest changed; inspect storage and select the source again."
            )
        files = []
        for key in ("3", "11", "12"):
            expected = manifest["files"][key]
            row = {
                "file_id": int(key),
                "expected_bytes": expected["bytes"],
                "expected_sha256": expected["sha256"],
                "observed_bytes": None,
                "observed_sha256": None,
                "status": "unavailable",
                "problem": None,
            }
            try:
                raw_file = read_private(folder / f"file-{key}.bin", 2 * 1024 * 1024)
                digest = sha(raw_file)
                row.update(
                    observed_bytes=len(raw_file),
                    observed_sha256=digest,
                    status="matches"
                    if len(raw_file) == expected["bytes"] and digest == expected["sha256"]
                    else "mismatch",
                )
            except READ_ERRORS as error:
                row["problem"] = problem(error)
            files.append(row)
        # A replaced manifest cannot lend its old expectations to a new result.
        try:
            current = read_private(
                self.storage.capture_folder(options.capture_id) / "manifest.json", 128 * 1024
            )
        except READ_ERRORS as error:
            raise ValueError("Original manifest became unavailable. " + problem(error)) from None
        if current != raw:
            raise ValueError("Original manifest changed during inspection; inspect storage again.")
        integrity = (
            "incomplete"
            if any(row["status"] == "unavailable" for row in files)
            else "mismatch"
            if any(row["status"] == "mismatch" for row in files)
            else "matches_manifest"
        )
        body = {
            **self.envelope(),
            "kind": "original_file_check",
            "checked_at": utc(),
            **options.model_dump(),
            "snapshot_sha256": manifest["evidence_sha256"],
            "source": source(manifest),
            "integrity": integrity,
            "files": files,
            "observation_is_atomic": False,
        }
        return {**body, "report_sha256": seal(body)}
