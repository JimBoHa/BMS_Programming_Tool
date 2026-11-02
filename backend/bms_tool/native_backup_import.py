"""Bounded local native archive copies with original IDs and no field authority."""

import asyncio
import io
import json
import re
import sqlite3
import stat
import zipfile
import zlib

from fastapi import APIRouter, Response, UploadFile

from .application_store import checked, encoded, identifier, private_write, read_private, utc
from .file_access import sync_directory
from .moi_identity import seal, sha
from .native_backup_lifecycle import ACTIVE_LIMIT
from .native_schedule_library import strict_json

PROFILE = "native-backup-import/1"
MAX_ARCHIVE = 8 * 1024 * 1024
MAX_MANIFEST = 128 * 1024
MAX_FILE = 2 * 1024 * 1024
SIDECAR = "local-import.json"
MEMBERS = {"manifest.json", "file-3.bin", "file-11.bin", "file-12.bin"}
SCOPE = (
    "Local original-file import only. Imported metadata describes historical evidence, "
    "not a responding controller, current settings, compatible compilation or transfer authority. "
    "No receipt, review, confirmation, credential or prepared recovery is restored."
)


def origin_at(folder, capture_id, snapshot_sha256):
    path = folder / SIDECAR
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    body = strict_json(read_private(path, 8192), 8192)
    if type(body) is not dict:
        raise ValueError("Local import provenance must be an object.")
    digest = body.pop("evidence_sha256", None)
    if (
        set(body)
        != {
            "profile",
            "capture_id",
            "snapshot_sha256",
            "incoming_archive_sha256",
            "manifest_file_sha256",
            "filename",
            "imported_at",
            "scope",
        }
        or body["profile"] != PROFILE
        or body["scope"] != SCOPE
        or body["capture_id"] != capture_id
        or body["snapshot_sha256"] != snapshot_sha256
        or type(body["filename"]) is not str
        or not 1 <= len(body["filename"].encode("utf-16-le")) // 2 <= 1024
        or type(body["imported_at"]) is not str
        or not 1 <= len(body["imported_at"]) <= 64
        or any(
            type(body[k]) is not str or not re.fullmatch(r"[a-f0-9]{64}", body[k])
            for k in ("incoming_archive_sha256", "manifest_file_sha256")
        )
        or seal(body) != digest
    ):
        raise ValueError("Local native import provenance differs from its source.")
    return {**body, "evidence_sha256": digest}


def import_origin(storage, manifest):
    folder = storage.capture_folder(manifest["id"])
    origin = origin_at(folder, manifest["id"], manifest["evidence_sha256"])
    if (
        origin
        and sha(read_private(folder / "manifest.json", MAX_MANIFEST))
        != origin["manifest_file_sha256"]
    ):
        raise ValueError("Imported native manifest bytes differ from their recorded provenance.")
    return origin


def read_archive(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_ARCHIVE:
        raise ValueError("Native backup ZIP exceeds its 8 MiB limit.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != 4 or {m.filename for m in members} != MEMBERS:
                raise ValueError(
                    "Native ZIP requires exactly its manifest and original Files 3, 11 and 12."
                )
            content = {}
            for member in members:
                limit = MAX_MANIFEST if member.filename == "manifest.json" else MAX_FILE
                if (
                    member.is_dir()
                    or member.flag_bits & 1
                    or stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG)
                    or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or not 1 <= member.file_size <= limit
                ):
                    raise ValueError("Native ZIP member type, compression or size is unsupported.")
                with archive.open(member) as stream:
                    value = stream.read(limit + 1)
                if len(value) != member.file_size or len(value) > limit:
                    raise ValueError("Native ZIP member exceeds its declared size.")
                content[member.filename] = value
        if type(strict_json(content["manifest.json"], MAX_MANIFEST)) is not dict:
            raise ValueError("Native manifest must be an object.")
        manifest = checked(content["manifest.json"])
        identifier(manifest.get("id"))
        if (
            type(manifest.get("files")) is not dict
            or set(manifest["files"]) != {"3", "11", "12"}
            or type(manifest.get("target")) is not dict
            or type(manifest["target"].get("address")) is not str
            or not manifest["target"]["address"]
            or len(manifest["target"]["address"]) > 512
            or (
                manifest["target"].get("router") is not None
                and (
                    type(manifest["target"]["router"]) is not str
                    or not 1 <= len(manifest["target"]["router"]) <= 512
                )
            )
            or (
                manifest["target"].get("dnet") is not None
                and (
                    type(manifest["target"]["dnet"]) is not int
                    or not 0 <= manifest["target"]["dnet"] <= 65534
                )
            )
            or type(manifest.get("device")) is not str
            or not re.fullmatch(r"device,(0|[1-9][0-9]*)", manifest["device"])
            or int(manifest["device"].split(",")[1]) > 4194302
            or type(manifest.get("identity")) is not dict
            or (
                "object-name" in manifest["identity"]
                and type(manifest["identity"]["object-name"]) is not str
            )
            or (
                "source_identity_matches" in manifest
                and type(manifest["source_identity_matches"]) is not bool
            )
            or type(manifest.get("captured_at")) is not str
            or not 1 <= len(manifest["captured_at"]) <= 64
        ):
            raise ValueError("Original native manifest identity or file list is malformed.")
        files = {}
        for key, expected in manifest["files"].items():
            value = content[f"file-{key}.bin"]
            if (
                type(expected) is not dict
                or set(expected) != {"bytes", "sha256"}
                or type(expected["bytes"]) is not int
                or expected["bytes"] != len(value)
                or type(expected["sha256"]) is not str
                or expected["sha256"] != sha(value)
            ):
                raise ValueError("Original native file hash or size differs from its manifest.")
            files[int(key)] = value
        return manifest, files, content["manifest.json"]
    except (
        zipfile.BadZipFile,
        zlib.error,
        RuntimeError,
        NotImplementedError,
        OSError,
        KeyError,
        TypeError,
        UnicodeError,
    ) as error:
        raise ValueError(
            "Native backup ZIP cannot be safely interpreted; no original was replaced."
        ) from error


class NativeBackupImports:
    def __init__(self, storage):
        self.storage = storage

    def import_archive(self, raw, filename):
        if type(filename) is not str or not 1 <= len(filename.encode("utf-16-le")) // 2 <= 1024:
            raise ValueError("Native import filename exceeds its text limit.")
        manifest, files, original_manifest = read_archive(raw)
        incoming = sha(raw)
        folder = self.storage.directory / manifest["id"]
        created = False
        resumed = False
        publishing = False
        try:
            with self.storage.store.connect(timeout=0.25) as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    folder.lstat()
                    exists = True
                except FileNotFoundError:
                    exists = False
                if exists:
                    self.storage.capture_folder(manifest["id"])
                    try:
                        (folder / "manifest.json").lstat()
                        complete = True
                    except FileNotFoundError:
                        complete = False
                    if complete:
                        retained, old_files = self.storage.load(manifest["id"])
                        if retained != manifest or old_files != files:
                            raise ValueError(
                                "This capture ID contains different local evidence. Existing originals were kept."
                            )
                        origin = import_origin(self.storage, retained)
                    else:
                        origin = origin_at(folder, manifest["id"], manifest["evidence_sha256"])
                        if (
                            not origin
                            or origin["incoming_archive_sha256"] != incoming
                            or origin["manifest_file_sha256"] != sha(original_manifest)
                        ):
                            raise ValueError(
                                "An incomplete source with this ID needs separate storage inspection. Existing data was kept."
                            )
                        if {p.name for p in folder.iterdir()} - (
                            {SIDECAR} | {f"file-{k}.bin" for k in files}
                        ):
                            raise ValueError(
                                "Incomplete native source has unrecognized entries; inspect it before retrying."
                            )
                        for key, value in files.items():
                            path = folder / f"file-{key}.bin"
                            try:
                                path.lstat()
                            except FileNotFoundError:
                                continue
                            if read_private(path, MAX_FILE) != value:
                                raise ValueError(
                                    "Incomplete native source contains different original bytes. Existing data was kept."
                                )
                        resumed = True
                else:
                    complete = False
                    origin = {
                        "profile": PROFILE,
                        "capture_id": manifest["id"],
                        "snapshot_sha256": manifest["evidence_sha256"],
                        "incoming_archive_sha256": incoming,
                        "manifest_file_sha256": sha(original_manifest),
                        "filename": filename,
                        "imported_at": utc(),
                        "scope": SCOPE,
                    }
                    origin["evidence_sha256"] = seal(origin)
                if not complete:
                    if len(self.storage.active_folders(db)) >= ACTIVE_LIMIT:
                        raise ValueError(
                            "Native backup storage is full; archive retained backups before importing another."
                        )
                    if not exists:
                        folder.mkdir(mode=0o700)
                        created = True
                    publishing = True
                    if created:
                        private_write(folder / SIDECAR, encoded(origin))
                    for key in sorted(files):
                        value = files[key]
                        path = folder / f"file-{key}.bin"
                        if not path.exists():
                            private_write(path, value)
                    private_write(folder / "manifest.json", original_manifest)
                    sync_directory(self.storage.directory)
        except (OSError, ValueError, sqlite3.Error) as error:
            if publishing:
                if created:
                    try:
                        folder.rmdir()
                    except OSError:
                        pass
                raise ValueError(
                    "Native import interrupted; retained private data needs storage inspection. Retry the same ZIP only after checking its status. No original was replaced."
                ) from error
            if isinstance(error, sqlite3.Error):
                raise ValueError(
                    "Native backup catalog is busy or unavailable; retry after checking local storage."
                ) from error
            raise
        return {
            "profile": PROFILE,
            "controller_queries": False,
            "field_actions": False,
            "authority_restored": False,
            "scope": SCOPE,
            "created": created,
            "resumed": resumed,
            "already_present": not created and not resumed,
            "incoming_archive_sha256": incoming,
            "manifest_file_sha256": sha(original_manifest),
            "capture_id": manifest["id"],
            "snapshot_sha256": manifest["evidence_sha256"],
            "manifest": manifest,
            "local_import": origin,
        }


def backup_import_router(storage):
    service = NativeBackupImports(storage)
    router = APIRouter(prefix="/api/bacnet/controller/native-application/backup-library")

    @router.post("/import")
    async def import_backup(file: UploadFile):
        result = await asyncio.to_thread(
            service.import_archive, await file.read(MAX_ARCHIVE + 1), file.filename
        )
        return Response(
            json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(),
            media_type="application/json",
        )

    return router
