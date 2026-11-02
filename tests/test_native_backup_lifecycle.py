"""Archiving frees catalog slots while immutable originals and all consumers survive."""

import io
import json
import os
import secrets
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore, encoded, evidence
from bms_tool.moi_identity import seal
from bms_tool.native_backup_lifecycle import NativeBackupLifecycle
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_signal_compiler import SignalCompilerService
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_signal_compiler import retained

BASE = "/api/bacnet/controller/native-application/backup-library"


def transition(library, capture, action="archive", revision=0):
    return library.change(
        {
            "capture_id": capture["id"],
            "snapshot_sha256": capture["evidence_sha256"],
            "expected_revision": revision,
            "action": action,
        }
    )


def original_bytes(storage):
    return {
        str(p.relative_to(storage.directory)): (p.read_bytes(), p.stat().st_mode & 0o777)
        for p in storage.directory.rglob("*")
        if p.is_file()
    }


def test_archive_restart_restore_preserves_every_original_path_byte_mode_and_reader(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    capture = retained(storage)
    folder = storage.directory / capture["id"]
    payload = folder / "reviewed-application.bin"
    payload.write_bytes(b"Authored reviewed payload, retained but never replayed")
    payload.chmod(0o600)
    before = original_bytes(storage)
    files = storage.load(capture["id"])[1]
    request = {"capture_id": capture["id"], "snapshot_sha256": capture["evidence_sha256"]}
    source = NativeBackupRecords(storage).source(request)
    compiler = SignalCompilerService(storage).source(capture["id"])
    archive_zip = storage.export(capture["id"])
    library = NativeBackupLifecycle(storage)
    changed = transition(library, capture)
    assert changed["transition"]["archived"] and changed["transition"]["revision"] == 1
    assert not changed["field_actions"] and not changed["controller_queries"]
    restarted = ApplicationStore(Store(tmp_path))
    assert (
        restarted.captures() == [] and SignalCompilerService(restarted).sources()["sources"] == []
    )
    assert restarted.load(capture["id"])[1] == files
    assert NativeBackupRecords(restarted).source(request) == source
    assert SignalCompilerService(restarted).source(capture["id"]) == compiler
    assert original_bytes(restarted) == before
    with zipfile.ZipFile(io.BytesIO(restarted.export(capture["id"]))) as archive:
        assert archive.read("manifest.json") == encoded(capture)
        assert all(archive.read(f"file-{key}.bin") == value for key, value in files.items())
    with (
        zipfile.ZipFile(io.BytesIO(archive_zip)) as old,
        zipfile.ZipFile(io.BytesIO(restarted.export(capture["id"]))) as new,
    ):
        assert {name: old.read(name) for name in old.namelist()} == {
            name: new.read(name) for name in new.namelist()
        }
    restored = transition(NativeBackupLifecycle(restarted), capture, "restore", 1)
    assert not restored["backup"]["archived"] and restored["backup"]["revision"] == 2
    assert restarted.captures() == [capture] and original_bytes(restarted) == before
    with restarted.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM application_capture_lifecycle").fetchone()[0] == 2


def test_active_128_limit_remains_and_archive_frees_exactly_one_slot(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    files = {3: b"original application", 11: b"static", 12: b"dynamic"}
    captures = [storage.save({}, files) for _ in range(128)]
    with pytest.raises(ValueError, match="storage is full"):
        storage.save({}, files)
    library = NativeBackupLifecycle(storage)
    transition(library, captures[0])
    newest = storage.save({}, files)
    assert len(storage.captures()) == 128 and storage.load(captures[0]["id"])[1] == files
    with pytest.raises(ValueError, match="storage is full"):
        transition(library, captures[0], "restore", 1)
    with pytest.raises(ValueError, match="storage is full"):
        storage.save({}, files)
    transition(library, newest)
    transition(library, captures[0], "restore", 1)
    assert len(storage.captures()) == 128


@pytest.mark.parametrize("operation", ["save", "restore"])
def test_separate_process_style_stores_serialize_last_active_slot(tmp_path, operation):
    storage = ApplicationStore(Store(tmp_path))
    files = {3: b"app", 11: b"static", 12: b"dynamic"}
    for _ in range(127):
        storage.save({}, files)
    archived = storage.save({}, files)
    transition(NativeBackupLifecycle(storage), archived)
    barrier = threading.Barrier(2)

    def attempt(number):
        separate = ApplicationStore(Store(tmp_path))
        barrier.wait(timeout=5)
        try:
            if operation == "restore" and number == 0:
                transition(NativeBackupLifecycle(separate), archived, "restore", 1)
            else:
                separate.save({}, files)
            return "saved"
        except ValueError as exc:
            assert "storage is full" in str(exc)
            return "full"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [0, 1])) == ["full", "saved"]
    assert len(storage.captures()) == 128


def test_revision_blocks_repeated_actions_and_archive_restore_archive_aba(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    capture = retained(storage)
    library = NativeBackupLifecycle(storage)
    transition(library, capture)
    for action, revision in [("archive", 0), ("archive", 1), ("restore", 0)]:
        with pytest.raises(ValueError, match="catalog changed"):
            transition(library, capture, action, revision)
    transition(library, capture, "restore", 1)
    with pytest.raises(ValueError, match="catalog changed"):
        transition(library, capture)
    transition(library, capture, revision=2)
    assert library.list({"state": "archived"})["backups"][0]["revision"] == 3


def test_bounded_search_lists_exact_routes_times_sizes_and_digests(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    captures = [
        retained(
            storage, target={"address": f"3001:{i}", "router": "127.0.0.1:49000", "dnet": 3001}
        )
        for i in range(35)
    ]
    library = NativeBackupLifecycle(storage)
    for capture in captures[:3]:
        transition(library, capture)
    report = library.list({"limit": 2})
    assert report["active_count"] == 32 and report["archived_count"] == 3
    assert report["total"] == 32 and report["has_more"] and len(report["backups"]) == 2
    specific = library.list({"state": "archived", "query": captures[1]["id"]})
    (row,) = specific["backups"]
    assert (
        row["target"] == captures[1]["target"] and row["captured_at"] == captures[1]["captured_at"]
    )
    assert row["files"] == captures[1]["files"] and row["file_bytes"] == sum(
        v["bytes"] for v in row["files"].values()
    )
    assert row["evidence_sha256"] == captures[1]["evidence_sha256"]
    assert library.list({"query": "not present"})["backups"] == []


@pytest.mark.parametrize("kind", ["real", "boolean", "wire", "historical-wire", "name", "instance"])
def test_all_recovery_families_keep_exact_proposals_after_all_sources_are_archived(tmp_path, kind):
    from bms_tool.native_historical_wire_recovery import NativeHistoricalWireRecovery

    from . import test_native_boolean_recovery as boolean
    from . import test_native_default_recovery as real
    from . import test_native_instance_recovery as instance
    from . import test_native_name_recovery as name
    from . import test_native_wire_recovery as wire

    module = {
        "real": real,
        "boolean": boolean,
        "wire": wire,
        "historical-wire": wire,
        "name": name,
        "instance": instance,
    }[kind]
    arguments = {"wires": wire.FANOUT[:2]} if kind == "historical-wire" else {}
    storage, service, request, *_ = module.setup(tmp_path, **arguments)
    if kind == "historical-wire":
        service = NativeHistoricalWireRecovery(service.records)
    before = service.prepare(request)
    receipts = storage.receipts()
    files = original_bytes(storage)
    for capture in storage.captures():
        transition(NativeBackupLifecycle(storage), capture)
    restarted = ApplicationStore(Store(tmp_path))
    service.storage = restarted
    service.records.storage = restarted
    assert service.prepare(request) == before
    assert restarted.receipts() == receipts and original_bytes(restarted) == files
    assert restarted.captures() == []


def test_pending_receipt_and_reviewed_payload_are_retained_without_replay(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    capture = retained(storage)
    receipt_id = secrets.token_hex(16)
    storage.intent({"id": receipt_id, "target": capture["target"], "backup_id": capture["id"]})
    storage.event(receipt_id, "dispatch", {"capture_id": capture["id"]})
    before = storage.receipt(receipt_id)
    transition(NativeBackupLifecycle(storage), capture)
    assert ApplicationStore(Store(tmp_path)).receipt(receipt_id) == before
    assert before["pending"] and before["result"] is None


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "file",
        "folder-link",
        "manifest-link",
        pytest.param(
            "fifo",
            marks=pytest.mark.skipif(
                not hasattr(os, "mkfifo"),
                reason="POSIX FIFO creation requires os.mkfifo; native Windows pipes have separate coverage.",
            ),
        ),
        "catalog",
    ],
)
def test_substituted_evidence_or_redirected_files_never_changes_catalog(tmp_path, fault):
    storage = ApplicationStore(Store(tmp_path))
    capture = retained(storage)
    folder = storage.directory / capture["id"]
    library = NativeBackupLifecycle(storage)
    if fault == "hash":
        capture = capture | {"evidence_sha256": "0" * 64}
    elif fault == "file":
        (folder / "file-12.bin").write_bytes(b"substitution")
    elif fault == "folder-link":
        folder.rename(folder.with_name("redirected"))
        folder.symlink_to(folder.with_name("redirected"), target_is_directory=True)
    elif fault == "manifest-link":
        (folder / "manifest.json").rename(folder / "redirected.json")
        (folder / "manifest.json").symlink_to(folder / "redirected.json")
    elif fault == "fifo":
        (folder / "file-11.bin").unlink()
        os.mkfifo(folder / "file-11.bin")
    else:
        transition(library, capture)
        with storage.store.connect() as db:
            row = json.loads(
                db.execute("SELECT body FROM application_capture_lifecycle").fetchone()[0]
            )
            row["archived"] = False
            db.execute("UPDATE application_capture_lifecycle SET body=?", (encoded(row),))
    with pytest.raises((ValueError, OSError)):
        transition(
            library,
            capture,
            "restore" if fault == "catalog" else "archive",
            1 if fault == "catalog" else 0,
        )
    with storage.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM application_capture_lifecycle").fetchone()[
            0
        ] == int(fault == "catalog")


def test_archived_1024_limit_is_separate_and_never_silently_prunes_sources(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    capture = retained(storage)
    files = storage.load(capture["id"])[1]
    with storage.store.connect() as db:
        for i in range(1024):
            capture_id = f"{i:032x}"
            manifest = evidence(
                {k: v for k, v in capture.items() if k != "evidence_sha256"} | {"id": capture_id}
            )
            folder = storage.directory / capture_id
            folder.mkdir()
            (folder / "manifest.json").write_bytes(encoded(manifest))
            for file_id, data in files.items():
                (folder / f"file-{file_id}.bin").write_bytes(data)
            body = {
                "profile": "native-backup-lifecycle/1",
                "capture_id": capture_id,
                "snapshot_sha256": manifest["evidence_sha256"],
                "revision": 1,
                "archived": True,
                "changed_at": capture["captured_at"],
            }
            db.execute(
                "INSERT INTO application_capture_lifecycle VALUES(?,?,?)",
                (capture_id, 1, encoded(body | {"evidence_sha256": seal(body)})),
            )
    library = NativeBackupLifecycle(storage)
    assert library.list({"state": "archived", "offset": 1020})["total"] == 1024
    with pytest.raises(ValueError, match="archive is full"):
        transition(library, capture)
    assert storage.load("0" * 32)[1] == files and storage.load(capture["id"])[1] == files


@pytest.mark.parametrize(
    "changes",
    [
        {"limit": 65},
        {"offset": -1},
        {"offset": True},
        {"state": "all"},
        {"query": "x" * 257},
        {"address": "127.0.0.1"},
    ],
)
def test_http_list_validation_and_token_guard_never_opens_field_interface(tmp_path, changes):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE + "/list", json={}).status_code == 403
        assert client.post(BASE + "/list", headers=headers, json=changes).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]


def test_http_catalog_changes_are_bound_local_and_busy_native_operation_is_preserved(tmp_path):
    app = create_app(tmp_path)
    native = app.state.native_applications
    capture = retained(native.storage)
    body = {
        "capture_id": capture["id"],
        "snapshot_sha256": capture["evidence_sha256"],
        "expected_revision": 0,
        "action": "archive",
    }
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE + "/change", json=body).status_code == 403
        for change in [
            {"expected_revision": True},
            {"action": "delete"},
            {"confirmed": True},
            {"capture_id": "../escape"},
        ]:
            assert (
                client.post(BASE + "/change", headers=headers, json=body | change).status_code
                == 422
            )
        native.active = {"operation_id": "authored-busy"}
        try:
            blocked = client.post(BASE + "/change", headers=headers, json=body)
            assert blocked.status_code == 422 and "active native operation" in blocked.text
        finally:
            native.active = None
        changed = client.post(BASE + "/change", headers=headers, json=body)
        assert changed.status_code == 200, changed.text
        assert client.post(BASE + "/change", headers=headers, json=body).status_code == 422
        report = client.post(BASE + "/list", headers=headers, json={"state": "archived"}).json()
        assert report["backups"][0]["id"] == capture["id"]
        assert (
            client.get(
                f"/api/bacnet/controller/native-application/backups/{capture['id']}"
            ).status_code
            == 200
        )
        assert not client.get("/api/session").json()["field_network_open"]
