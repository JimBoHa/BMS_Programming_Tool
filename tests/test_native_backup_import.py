"""Portable native originals stay immutable, bounded and separate from field authority."""

import io
import json
import stat
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from bms_tool import native_backup_import as module
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore, encoded, evidence
from bms_tool.native_backup_import import MAX_ARCHIVE, PROFILE, SIDECAR, NativeBackupImports
from bms_tool.native_backup_lifecycle import NativeBackupLifecycle
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_signal_compiler import SignalCompilerService
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_signal_compiler import retained


@pytest.fixture(scope="module")
def original(tmp_path_factory):
    store = ApplicationStore(Store(tmp_path_factory.mktemp("exported-native-original")))
    manifest = retained(store)
    return manifest, store.load(manifest["id"])[1], store.export(manifest["id"])


def contents(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def repack(raw, change):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        rows = [(x.filename, archive.read(x)) for x in archive.infolist()]
    rows = change(rows)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in rows:
            archive.writestr(name, body)
    return out.getvalue()


def test_roundtrip_original_ids_files_restart_and_idempotence(tmp_path, original):
    manifest, files, raw = original
    store = ApplicationStore(Store(tmp_path))
    service = NativeBackupImports(store)
    result = service.import_archive(raw, "original.zip")
    assert result["profile"] == PROFILE and result["created"] and not result["resumed"]
    assert result["manifest"] == manifest and result["capture_id"] == manifest["id"]
    assert (
        not result["controller_queries"]
        and not result["field_actions"]
        and not result["authority_restored"]
    )
    assert store.load(manifest["id"]) == (manifest, files)
    before = contents(store.directory)
    repeated = NativeBackupImports(ApplicationStore(Store(tmp_path))).import_archive(
        raw, "again.zip"
    )
    assert repeated["already_present"] and repeated["local_import"] == result["local_import"]
    assert contents(store.directory) == before
    with zipfile.ZipFile(io.BytesIO(store.export(manifest["id"]))) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "file-3.bin",
            "file-11.bin",
            "file-12.bin",
        }
        assert json.loads(archive.read("manifest.json")) == manifest
        for key, value in files.items():
            assert archive.read(f"file-{key}.bin") == value
    entry = NativeBackupLifecycle(store).list({})["backups"][0]
    assert entry["local_import"] == result["local_import"]
    assert stat.S_IMODE((store.directory / manifest["id"]).stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(p.stat().st_mode) == 0o600
        for p in (store.directory / manifest["id"]).iterdir()
    )


@pytest.mark.parametrize(
    "case",
    [
        "extra",
        "missing",
        "duplicate",
        "path",
        "absolute",
        "file_hash",
        "manifest_hash",
        "duplicate_json",
        "nan",
        "unpaired",
        "bad_id",
        "bad_size",
        "oversize_manifest",
        "oversize_member",
        "symlink",
        "compression",
        "truncated",
        "archive_limit",
    ],
)
def test_bad_archives_are_refused_before_any_publication(tmp_path, original, case):
    _, _, raw = original
    store = ApplicationStore(Store(tmp_path))
    if case == "extra":
        raw = repack(raw, lambda r: r + [("extra.bin", b"x")])
    elif case == "missing":
        raw = repack(raw, lambda r: r[:-1])
    elif case == "duplicate":
        raw = repack(raw, lambda r: r + [r[0]])
    elif case == "path":
        raw = repack(
            raw, lambda r: [("../manifest.json" if n == "manifest.json" else n, b) for n, b in r]
        )
    elif case == "absolute":
        raw = repack(
            raw, lambda r: [("/manifest.json" if n == "manifest.json" else n, b) for n, b in r]
        )
    elif case == "file_hash":
        raw = repack(raw, lambda r: [(n, b + b"changed" if n == "file-3.bin" else b) for n, b in r])
    elif case in ("manifest_hash", "bad_id", "bad_size"):

        def changed(rows):
            result = []
            for name, body in rows:
                if name == "manifest.json":
                    m = json.loads(body)
                    if case == "manifest_hash":
                        m["device"] = "device,99"
                    elif case == "bad_id":
                        m["id"] = "../outside"
                        m = evidence({k: v for k, v in m.items() if k != "evidence_sha256"})
                    else:
                        m["files"]["3"]["bytes"] = True
                        m = evidence({k: v for k, v in m.items() if k != "evidence_sha256"})
                    body = encoded(m)
                result.append((name, body))
            return result

        raw = repack(raw, changed)
    elif case in ("duplicate_json", "nan", "unpaired", "oversize_manifest"):
        body = {
            "duplicate_json": b'{"profile":1,"profile":2}',
            "nan": b'{"x":NaN}',
            "unpaired": b'{"x":"\\ud800"}',
            "oversize_manifest": b" " * (128 * 1024 + 1),
        }[case]
        raw = repack(raw, lambda r: [(n, body if n == "manifest.json" else b) for n, b in r])
    elif case == "oversize_member":
        raw = repack(
            raw,
            lambda r: [(n, b"x" * (2 * 1024 * 1024 + 1) if n == "file-3.bin" else b) for n, b in r],
        )
    elif case in ("symlink", "compression"):
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as old, zipfile.ZipFile(out, "w") as new:
            for n in old.namelist():
                info = zipfile.ZipInfo(n)
                if n == "file-3.bin":
                    if case == "symlink":
                        info.create_system = 3
                        info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    else:
                        info.compress_type = zipfile.ZIP_BZIP2
                new.writestr(info, old.read(n))
        raw = out.getvalue()
    elif case == "truncated":
        raw = raw[:-20]
    elif case == "archive_limit":
        raw = b"x" * (MAX_ARCHIVE + 1)
    with pytest.raises(ValueError):
        NativeBackupImports(store).import_archive(raw, "bad.zip")
    assert contents(store.directory) == {}


def test_conflicts_symlinks_and_incomplete_non_imports_are_never_replaced(tmp_path, original):
    manifest, _, raw = original
    store = ApplicationStore(Store(tmp_path))
    service = NativeBackupImports(store)
    folder = store.directory / manifest["id"]
    folder.mkdir(mode=0o700)
    (folder / "file-3.bin").write_bytes(b"keep")
    before = contents(store.directory)
    with pytest.raises(ValueError, match="incomplete"):
        service.import_archive(raw, "original.zip")
    assert contents(store.directory) == before
    (folder / "file-3.bin").unlink()
    folder.rmdir()
    external = tmp_path / "external"
    external.mkdir()
    folder.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError):
        service.import_archive(raw, "original.zip")
    assert folder.is_symlink() and list(external.iterdir()) == []


def test_owned_interrupted_import_can_resume_only_exact_existing_bytes(
    tmp_path, original, monkeypatch
):
    manifest, files, raw = original
    store = ApplicationStore(Store(tmp_path))
    service = NativeBackupImports(store)
    write = module.private_write

    def fail(path, body):
        if path.name == "file-11.bin":
            raise OSError("authored interrupted write")
        write(path, body)

    monkeypatch.setattr(module, "private_write", fail)
    with pytest.raises(ValueError, match="interrupted"):
        service.import_archive(raw, "original.zip")
    folder = store.directory / manifest["id"]
    assert (folder / SIDECAR).is_file() and not (folder / "manifest.json").exists()
    assert store.captures() == [] and (folder / "file-3.bin").read_bytes() == files[3]
    monkeypatch.setattr(module, "private_write", write)
    done = service.import_archive(raw, "retry.zip")
    assert done["resumed"] and not done["created"]
    assert done["local_import"]["filename"] == "original.zip" and store.load(manifest["id"]) == (
        manifest,
        files,
    )


def test_active_limit_is_unchanged_and_identical_existing_copy_needs_no_slot(tmp_path, original):
    manifest, files, raw = original
    store = ApplicationStore(Store(tmp_path))
    service = NativeBackupImports(store)
    service.import_archive(raw, "first.zip")
    for _ in range(127):
        retained(store, files)
    before = contents(store.directory)
    assert service.import_archive(raw, "same.zip")["already_present"]
    other = ApplicationStore(Store(tmp_path / "other"))
    m = retained(other, files)
    new = other.export(m["id"])
    with pytest.raises(ValueError, match="storage is full"):
        service.import_archive(new, "new.zip")
    assert contents(store.directory) == before


def test_concurrent_same_archive_publishes_once(tmp_path, original):
    manifest, files, raw = original
    store = ApplicationStore(Store(tmp_path))
    service = NativeBackupImports(store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.import_archive(raw, "copy.zip"), range(2)))
    assert (
        sum(r["created"] for r in results) == 1 and sum(r["already_present"] for r in results) == 1
    )
    assert store.load(manifest["id"]) == (manifest, files)


def test_conflicting_complete_original_and_damaged_import_provenance_are_retained(
    tmp_path, original
):
    manifest, _, raw = original
    store = ApplicationStore(Store(tmp_path))
    service = NativeBackupImports(store)
    service.import_archive(raw, "original.zip")
    before = contents(store.directory)

    def different(rows):
        result = []
        for name, body in rows:
            if name == "manifest.json":
                value = json.loads(body)
                value["identity"]["object-name"] = "different historical identity"
                body = encoded(evidence({k: v for k, v in value.items() if k != "evidence_sha256"}))
            result.append((name, body))
        return result

    with pytest.raises(ValueError, match="different local evidence"):
        service.import_archive(repack(raw, different), "conflict.zip")
    assert contents(store.directory) == before
    sidecar = store.directory / manifest["id"] / SIDECAR
    sidecar.write_bytes(b"damaged")
    damaged = contents(store.directory)
    row = NativeBackupLifecycle(store).list({})["backups"][0]
    assert row["local_import_unavailable"] and "local_import" not in row
    assert store.load(manifest["id"])[0] == manifest
    with pytest.raises(ValueError):
        service.import_archive(raw, "same.zip")
    assert contents(store.directory) == damaged


def test_preexisting_local_source_is_not_relabeled_as_imported(tmp_path, original):
    manifest, files, raw = original
    store = ApplicationStore(Store(tmp_path))
    folder = store.directory / manifest["id"]
    folder.mkdir(mode=0o700)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for member in archive.namelist():
            module.private_write(folder / member, archive.read(member))
    before = contents(store.directory)
    result = NativeBackupImports(store).import_archive(raw, "same.zip")
    assert result["already_present"] and result["local_import"] is None
    assert "local_import" not in NativeBackupLifecycle(store).list({})["backups"][0]
    assert contents(store.directory) == before and store.load(manifest["id"])[1] == files


@pytest.mark.parametrize(
    "field,value",
    [
        ("target", {"address": "x", "router": {}}),
        ("target", {"address": "x", "dnet": True}),
        ("target", {"address": "x", "dnet": 65535}),
        ("target", {"address": "x" * 513}),
        ("device", "device,4194303"),
        ("device", "device,01"),
        ("identity", {"object-name": {"not": "text"}}),
        ("source_identity_matches", "true"),
    ],
)
def test_sealed_but_malformed_display_metadata_cannot_enter_catalog(
    tmp_path, original, field, value
):
    _, _, raw = original

    def changed(rows):
        result = []
        for name, body in rows:
            if name == "manifest.json":
                value_row = json.loads(body)
                value_row[field] = value
                body = encoded(
                    evidence({k: v for k, v in value_row.items() if k != "evidence_sha256"})
                )
            result.append((name, body))
        return result

    storage = ApplicationStore(Store(tmp_path))
    with pytest.raises(ValueError, match="malformed"):
        NativeBackupImports(storage).import_archive(repack(raw, changed), "bad.zip")
    assert contents(storage.directory) == {}


def test_reimport_never_restores_archived_capture_or_retained_authority(tmp_path, original):
    manifest, _, raw = original
    storage = ApplicationStore(Store(tmp_path))
    service = NativeBackupImports(storage)
    service.import_archive(raw, "first.zip")
    lifecycle = NativeBackupLifecycle(storage)
    lifecycle.change(
        {
            "capture_id": manifest["id"],
            "snapshot_sha256": manifest["evidence_sha256"],
            "expected_revision": 0,
            "action": "archive",
        }
    )
    before = contents(storage.directory)
    result = service.import_archive(raw, "again.zip")
    assert result["already_present"]
    assert contents(storage.directory) == before and storage.receipts() == []
    row = lifecycle.list({"state": "archived"})["backups"][0]
    assert row["revision"] == 1 and row["archived"]


def test_corrupt_partial_original_and_unknown_partial_entries_require_inspection(
    tmp_path, original, monkeypatch
):
    manifest, _, raw = original
    storage = ApplicationStore(Store(tmp_path))
    service = NativeBackupImports(storage)
    write = module.private_write

    def fail(path, body):
        if path.name == "file-11.bin":
            raise OSError("interrupted")
        write(path, body)

    monkeypatch.setattr(module, "private_write", fail)
    with pytest.raises(ValueError):
        service.import_archive(raw, "first.zip")
    monkeypatch.setattr(module, "private_write", write)
    folder = storage.directory / manifest["id"]
    (folder / "file-3.bin").write_bytes(b"changed")
    before = contents(storage.directory)
    with pytest.raises(ValueError, match="different original bytes"):
        service.import_archive(raw, "same.zip")
    assert contents(storage.directory) == before
    (folder / "unexpected.part").write_bytes(b"retained evidence")
    before = contents(storage.directory)
    with pytest.raises(ValueError, match="unrecognized entries"):
        service.import_archive(raw, "same.zip")
    assert contents(storage.directory) == before


def test_actual_local_http_needs_token_and_reopens_without_field_interface(tmp_path, original):
    manifest, files, raw = original
    with TestClient(create_app(tmp_path)) as client:
        base = "/api/bacnet/controller/native-application/backup-library"
        assert client.post(base + "/import", files={"file": ("source.zip", raw)}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            base + "/import", headers=headers, files={"file": ("source.zip", raw)}
        )
        assert response.status_code == 200, response.text
        assert response.json()["capture_id"] == manifest["id"]
        assert client.app.state.native_applications.storage.load(manifest["id"]) == (
            manifest,
            files,
        )
        assert not client.get("/api/session").json()["field_network_open"]
        assert (
            client.post(base + "/list", headers=headers, json={}).json()["backups"][0][
                "local_import"
            ]["profile"]
            == PROFILE
        )


def test_imported_originals_feed_existing_offline_readers_without_mutating_source(
    tmp_path, original
):
    manifest, _, raw = original
    storage = ApplicationStore(Store(tmp_path))
    NativeBackupImports(storage).import_archive(raw, "moved-original.zip")
    before = contents(storage.directory)
    request = {"capture_id": manifest["id"], "snapshot_sha256": manifest["evidence_sha256"]}
    inspected = NativeBackupRecords(storage).source(request)
    assert inspected["capture_id"] == manifest["id"] and not inspected["controller_queries"]
    compiled_source = SignalCompilerService(storage).source(manifest["id"])
    assert compiled_source["capture_id"] == manifest["id"]
    assert contents(storage.directory) == before and storage.receipts() == []


def test_opaque_native_files_are_retained_without_fabricated_format_compatibility(tmp_path):
    source = ApplicationStore(Store(tmp_path / "source"))
    files = {k: b"Opaque original native bytes " + bytes([k]) for k in (3, 11, 12)}
    manifest = retained(source, files, source_identity_matches=False)
    destination = ApplicationStore(Store(tmp_path / "destination"))
    result = NativeBackupImports(destination).import_archive(
        source.export(manifest["id"]), "opaque.zip"
    )
    assert result["created"] and not result["authority_restored"]
    assert destination.load(manifest["id"]) == (manifest, files)
    with pytest.raises(ValueError):
        SignalCompilerService(destination).source(manifest["id"])
