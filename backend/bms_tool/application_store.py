"""Private, immutable native backups and durable single-attempt transfer evidence."""

import io
import json
import os
import secrets
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from .device_instance import station_key
from .file_access import open_regular, storage_profile, sync_directory
from .moi_identity import seal, sha

PROFILE = "native-application-transfer/1"


def utc():
    return datetime.now(UTC).isoformat()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def checked(raw):
    if not raw or len(raw) > 128 * 1024:
        raise ValueError("Invalid native application evidence size.")
    row = json.loads(raw)
    digest = row.pop("evidence_sha256", None)
    if digest != seal(row) or row.get("profile") != PROFILE:
        raise ValueError("Native application evidence integrity check failed.")
    return {**row, "evidence_sha256": digest}


def evidence(row):
    return {**row, "evidence_sha256": seal(row)}


def native_storage_profile():
    current = storage_profile()
    available = current["platform"] in ("posix", "nt")
    return {
        "profile": "native-application-storage/1",
        "platform": current["platform"],
        "available": available,
        "regular_file_guard": current["regular_file_guard"] if available else "Unavailable",
        "file_data_flush": "os.fsync before complete-file replace" if available else "Unavailable",
        "directory_flush": available and current["directory_flush"],
        "durability": current["durability"] if available else "Safe native storage unavailable.",
        "catalog_and_journal": "SQLite transactions; lifecycle and transfer updates use synchronous=FULL.",
        "scope": "Current computer storage policy; not original capture durability or controller acceptance.",
    }


def retained_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("Native backups must remain in their original storage folder.")
    return path


def private_write(path, data):
    """Publish a complete file only after its private contents reach storage."""
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".part")
    fd = open_regular(temporary, writable=True, create=True, exclusive=True)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def read_private(path, maximum):
    fd = open_regular(path)
    with os.fdopen(fd, "rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("Private application file exceeds its size limit.")
    return raw


def identifier(value):
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("Invalid native application record identifier.")
    return value


class ApplicationStore:
    def __init__(self, store):
        self.store = store
        self.directory = store.directory / "native-applications"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        retained_directory(self.directory)
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS application_transfers("
                "id TEXT PRIMARY KEY,station TEXT NOT NULL,intent BLOB NOT NULL,"
                "result BLOB,pending INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS application_pending_station "
                "ON application_transfers(station) WHERE pending=1"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS application_transfer_events("
                "sequence INTEGER PRIMARY KEY,receipt_id TEXT NOT NULL,body BLOB NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS application_capture_lifecycle("
                "capture_id TEXT NOT NULL,revision INTEGER NOT NULL,body BLOB NOT NULL,"
                "PRIMARY KEY(capture_id,revision))"
            )

    def active_folders(self, db):
        from .native_backup_lifecycle import lifecycle_states

        retained_directory(self.directory)
        states = lifecycle_states(db)
        return [
            path.parent
            for path in self.directory.glob("*/manifest.json")
            if not states.get(path.parent.name, {}).get("archived", False)
        ]

    def require_capture_capacity(self, needed=1):
        """Check current retention space; this does not reserve slots for the caller."""
        from .native_backup_lifecycle import ACTIVE_LIMIT

        if type(needed) is not int or not 1 <= needed <= ACTIVE_LIMIT:
            raise ValueError("Native capture capacity requires a bounded positive snapshot count.")
        with self.store.connect(timeout=0.25) as db:
            active = len(self.active_folders(db))
        if active + needed > ACTIVE_LIMIT:
            raise ValueError(
                f"Native backup storage cannot retain the {needed} required snapshot(s); "
                "archive retained backups before this operation."
            )

    def save(self, metadata, files):
        if set(files) != {3, 11, 12} or any(
            not isinstance(data, bytes) or not 1 <= len(data) <= 2 * 1024 * 1024
            for data in files.values()
        ):
            raise ValueError("A native snapshot requires its three bounded original backup files.")
        with self.store.connect(timeout=0.25) as db:
            db.execute("BEGIN IMMEDIATE")
            if len(self.active_folders(db)) >= 128:
                raise ValueError(
                    "Native backup storage is full; archive retained backups before capturing again."
                )
            capture_id = secrets.token_hex(16)
            folder = self.directory / capture_id
            folder.mkdir(mode=0o700)
            for file_id, data in files.items():
                private_write(folder / f"file-{file_id}.bin", data)
            manifest = evidence(
                {
                    **metadata,
                    "profile": PROFILE,
                    "id": capture_id,
                    "captured_at": utc(),
                    "files": {
                        str(i): {"bytes": len(v), "sha256": sha(v)} for i, v in files.items()
                    },
                }
            )
            private_write(folder / "manifest.json", encoded(manifest))
        return manifest

    def capture_folder(self, capture_id):
        retained_directory(self.directory)
        folder = self.directory / identifier(capture_id)
        return retained_directory(folder)

    def load(self, capture_id):
        folder = self.capture_folder(capture_id)
        manifest = checked(read_private(folder / "manifest.json", 128 * 1024))
        if manifest["id"] != capture_id or set(manifest["files"]) != {"3", "11", "12"}:
            raise ValueError("Native backup manifest does not match its retained source.")
        files = {}
        for key, expected in manifest["files"].items():
            data = read_private(folder / f"file-{key}.bin", 2 * 1024 * 1024)
            if sha(data) != expected["sha256"] or len(data) != expected["bytes"]:
                raise ValueError("Native backup file integrity check failed.")
            files[int(key)] = data
        return manifest, files

    def captures(self):
        with self.store.connect() as db:
            folders = self.active_folders(db)
        return sorted(
            (self.load(folder.name)[0] for folder in folders),
            key=lambda row: row["captured_at"],
            reverse=True,
        )

    def export(self, capture_id):
        manifest, files = self.load(capture_id)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", encoded(manifest))
            for key, value in files.items():
                archive.writestr(f"file-{key}.bin", value)
        return output.getvalue()

    def intent(self, body):
        identifier(body["id"])
        row = evidence(
            {
                **body,
                "profile": PROFILE,
                "status": "unknown",
                "may_have_applied": True,
                "created_at": utc(),
            }
        )
        if len(encoded(row)) > 128 * 1024:
            raise ValueError("Native transfer intent exceeds its readable evidence limit.")
        with self.store.connect(timeout=0.25) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM application_transfers").fetchone()[0] >= 1024:
                raise ValueError("Native transfer journal is full.")
            db.execute(
                "INSERT INTO application_transfers VALUES(?,?,?,NULL,1)",
                (body["id"], encoded(station_key(body["target"])).decode(), encoded(row)),
            )
        return row

    def event(self, receipt_id, stage, detail):
        row = evidence(
            {
                "profile": PROFILE,
                "receipt_id": identifier(receipt_id),
                "stage": stage,
                "detail": detail,
                "created_at": utc(),
            }
        )
        raw = encoded(row)
        if len(raw) > 128 * 1024:
            raise ValueError("Native transfer event exceeds its evidence limit.")
        with self.store.connect(timeout=0.25) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT COUNT(*) FROM application_transfer_events WHERE receipt_id=?",
                    (receipt_id,),
                ).fetchone()[0]
                >= 8192
            ):
                raise ValueError("Native transfer exceeded its durable dispatch budget.")
            if not db.execute(
                "SELECT pending FROM application_transfers WHERE id=?", (receipt_id,)
            ).fetchone():
                raise ValueError("Native transfer has no durable intent.")
            db.execute(
                "INSERT INTO application_transfer_events(receipt_id,body) VALUES(?,?)",
                (receipt_id, raw),
            )
        return row

    def finish(self, receipt_id, result):
        row = evidence(
            {
                "profile": PROFILE,
                "receipt_id": identifier(receipt_id),
                **result,
                "finished_at": utc(),
            }
        )
        pending = int(
            row.get("may_have_applied", True)
            and row.get("status") not in ("verified", "recovered_original")
        )
        with self.store.connect(timeout=0.25) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT intent,result FROM application_transfers WHERE id=?", (receipt_id,)
            ).fetchone()
            if not previous or previous[1] is not None:
                raise ValueError("Native transfer result is absent or already retained.")
            intent = checked(previous[0])
            if row.get("intent_sha256") != intent["evidence_sha256"]:
                raise ValueError("Native transfer result differs from its durable intent.")
            db.execute(
                "UPDATE application_transfers SET result=?,pending=? WHERE id=?",
                (encoded(row), pending, receipt_id),
            )
        return self.receipt(receipt_id)

    def receipt(self, receipt_id, *, include_events=True):
        identifier(receipt_id)
        with self.store.connect() as db:
            row = db.execute(
                "SELECT intent,result,pending FROM application_transfers WHERE id=?", (receipt_id,)
            ).fetchone()
            events = (
                db.execute(
                    "SELECT body FROM application_transfer_events WHERE receipt_id=? ORDER BY sequence",
                    (receipt_id,),
                ).fetchall()
                if include_events
                else []
            )
            last_event = db.execute(
                "SELECT body FROM application_transfer_events WHERE receipt_id=? ORDER BY sequence DESC LIMIT 1",
                (receipt_id,),
            ).fetchone()
        if not row:
            raise ValueError("Native transfer receipt is unavailable.")
        latest = checked(last_event[0]) if last_event else None
        latest_readback = latest["detail"] if latest and latest["stage"] == "readback" else None
        return {
            "intent": checked(row[0]),
            "result": checked(row[1]) if row[1] else None,
            "pending": bool(row[2]),
            "latest_readback": latest_readback,
            "events": [checked(e[0]) for e in events],
        }

    def receipts(self, *, include_events=True):
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT id FROM application_transfers ORDER BY rowid DESC LIMIT 1024"
            ).fetchall()
        return [self.receipt(r[0], include_events=include_events) for r in rows]

    def verified_readback(self, receipt_id):
        """Find the first immutable verified readback without materializing all events."""
        identifier(receipt_id)
        with self.store.connect() as db:
            for (body,) in db.execute(
                "SELECT body FROM application_transfer_events WHERE receipt_id=? ORDER BY sequence",
                (receipt_id,),
            ):
                event = checked(body)
                detail = event.get("detail")
                if (
                    event.get("stage") == "readback"
                    and isinstance(detail, dict)
                    and detail.get("status") == "verified"
                ):
                    return event
        return None

    def resolve(self, receipt_id, readback):
        self.event(receipt_id, "readback", readback)
        if readback["status"] in ("verified", "recovered_original"):
            with self.store.connect() as db:
                db.execute("UPDATE application_transfers SET pending=0 WHERE id=?", (receipt_id,))
        return self.receipt(receipt_id)

    def available(self, target):
        key = station_key(target)
        for receipt in self.receipts(include_events=False):
            if receipt["pending"] and station_key(receipt["intent"]["target"]) == key:
                raise ValueError(
                    "This station has an unresolved native application transfer. Read back its receipt before another write."
                )


class ApplicationCredentials:
    def __init__(self, directory):
        self.path = Path(directory) / "native-application-credentials.json"

    def get(self):
        try:
            row = json.loads(read_private(self.path, 4096))
        except FileNotFoundError:
            raise ValueError(
                "Configure the controller family backup and application-transfer credentials first."
            ) from None
        if set(row) != {"backup", "restore"} or any(
            not isinstance(s, str) or not 1 <= len(s.encode()) <= 128 for s in row.values()
        ):
            raise ValueError("Invalid local native application credential configuration.")
        return row

    def configured(self):
        try:
            self.get()
            return True
        except (ValueError, OSError):
            return False

    def set(self, backup, restore):
        if any(
            not isinstance(s, str) or not 1 <= len(s.encode()) <= 128 for s in (backup, restore)
        ):
            raise ValueError("Use bounded controller-family credentials.")
        private_write(self.path, encoded({"backup": backup, "restore": restore}))
        return {"configured": True}
