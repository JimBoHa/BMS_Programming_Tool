"""Native backup/credential files use the existing native safe-file boundary."""

import errno
import io
import json
import os
import stat
import subprocess
import uuid
import zipfile
from types import SimpleNamespace

import pytest
from bms_tool import application_store as native
from bms_tool import file_access as access
from bms_tool.app import create_app
from bms_tool.native_backup_lifecycle import NativeBackupLifecycle
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_signal_compiler import retained


@pytest.mark.skipif(os.name != "nt", reason="Native Win32 named-pipe handle case runs on Windows.")
def test_actual_windows_pipe_handle_is_refused_and_closed_before_read_or_crt_conversion(
    tmp_path, monkeypatch
):
    import ctypes
    from ctypes import wintypes

    api = access._WindowsAPI()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateNamedPipeW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    create.restype = wintypes.HANDLE
    handle = create("\\\\.\\pipe\\bms-native-storage-" + uuid.uuid4().hex, 1, 0, 1, 64, 64, 0, None)
    assert handle not in (None, ctypes.c_void_p(-1).value)
    closed = []
    original_close = api.close

    def close(value):
        closed.append(value)
        return original_close(value)

    path = tmp_path / "original.bin"
    path.write_bytes(b"untouched authored original")
    monkeypatch.setattr(api, "open", lambda *args, **kwargs: handle)
    monkeypatch.setattr(api, "close", close)
    monkeypatch.setattr(
        api, "descriptor", lambda *args, **kwargs: pytest.fail("Pipe reached CRT conversion.")
    )
    monkeypatch.setattr(access, "_WindowsAPI", lambda: api)
    try:
        assert api.kind(handle) == 3  # FILE_TYPE_PIPE
        with pytest.raises((OSError, ValueError)):
            native.read_private(path, 128)
        assert closed == [handle]
        assert path.read_bytes() == b"untouched authored original"
    finally:
        if not closed:
            original_close(handle)


class WindowsCompatibleOS:
    """Keep real descriptors while refusing POSIX-only constants/directory opens."""

    def __getattr__(self, name):
        if name in ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY"):
            raise AttributeError(name)
        return getattr(os, name)

    def open(self, path, *args):
        if os.path.isdir(path):
            raise PermissionError(errno.EACCES, "Ordinary Windows directory open refused.")
        return os.open(path, *args)


class HandleBoundary:
    """Authored Win32 boundary, not a substitute for native Windows execution."""

    def __init__(self, *, rejected=False):
        self.calls, self.closed = [], []
        self.rejected = rejected

    def open(self, path, **options):
        self.calls.append((path, options))
        return (
            os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            if options["create"]
            else os.open(path, os.O_RDONLY)
        )

    def validate(self, handle):
        if self.rejected or not stat.S_ISREG(os.fstat(handle).st_mode):
            raise ValueError("Authored reparse or nonregular handle refused.")

    def descriptor(self, handle, *, writable):
        assert isinstance(writable, bool)
        return handle

    def close(self, handle):
        os.close(handle)
        self.closed.append(handle)


def test_authored_windows_boundary_writes_reads_and_replaces_credentials_without_posix_calls(
    tmp_path, monkeypatch
):
    boundary = HandleBoundary()
    monkeypatch.setattr(access, "_PLATFORM", "nt")
    monkeypatch.setattr(access, "_WindowsAPI", lambda: boundary)
    monkeypatch.setattr(native, "os", WindowsCompatibleOS())
    credentials = native.ApplicationCredentials(tmp_path)
    assert credentials.set("authored-backup", "authored-restore") == {"configured": True}
    original = credentials.path.read_bytes()
    assert credentials.get() == {"backup": "authored-backup", "restore": "authored-restore"}
    credentials.set("authored-replacement", "authored-new-restore")
    assert credentials.path.read_bytes() != original
    assert credentials.get()["backup"] == "authored-replacement"
    assert not list(tmp_path.glob("*.part"))
    assert len(boundary.calls) == 4
    assert all(
        options == {"writable": True, "create": True, "exclusive": True}
        for _, options in boundary.calls[::2]
    )
    assert all(
        options == {"writable": False, "create": False, "exclusive": False}
        for _, options in boundary.calls[1::2]
    )
    profile = native.native_storage_profile()
    assert profile["available"] and profile["platform"] == "nt" and not profile["directory_flush"]
    assert "unverified" in profile["durability"] and "hard-link" not in profile["file_data_flush"]
    assert "process_lock" not in profile


def test_rejected_windows_read_handle_is_closed_before_any_evidence_is_returned(
    tmp_path, monkeypatch
):
    path = tmp_path / "evidence.json"
    path.write_bytes(b"retained")
    boundary = HandleBoundary(rejected=True)
    monkeypatch.setattr(access, "_PLATFORM", "nt")
    monkeypatch.setattr(access, "_WindowsAPI", lambda: boundary)
    with pytest.raises(ValueError, match="reparse"):
        native.read_private(path, 128)
    (handle,) = boundary.closed
    with pytest.raises(OSError):
        os.fstat(handle)
    assert path.read_bytes() == b"retained"


def test_complete_file_flush_precedes_replace_and_directory_policy(tmp_path, monkeypatch):
    path = tmp_path / "snapshot.bin"
    path.write_bytes(b"original")
    events = []
    original_sync = native.sync_directory

    class OrderedOS(WindowsCompatibleOS):
        def fsync(self, descriptor):
            assert stat.S_ISREG(os.fstat(descriptor).st_mode)
            assert path.read_bytes() == b"original"
            events.append("file-flush")
            return os.fsync(descriptor)

        def replace(self, source, destination):
            assert (
                path.read_bytes() == b"original" and source.read_bytes() == b"complete replacement"
            )
            events.append("replace")
            return os.replace(source, destination)

    def directory_policy(directory):
        assert directory == tmp_path and path.read_bytes() == b"complete replacement"
        events.append("directory-policy")
        return original_sync(directory)

    monkeypatch.setattr(native, "os", OrderedOS())
    monkeypatch.setattr(native, "sync_directory", directory_policy)
    native.private_write(path, b"complete replacement")
    assert events == ["file-flush", "replace", "directory-policy"]
    assert native.read_private(path, 20) == b"complete replacement"
    with pytest.raises(ValueError, match="size limit"):
        native.read_private(path, 19)
    assert not list(tmp_path.glob("*.part"))
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("stage", ["flush", "replace", "directory"])
def test_storage_errors_remain_visible_without_partial_success_or_overwrite_fallback(
    tmp_path, monkeypatch, stage
):
    path = tmp_path / "original.bin"
    path.write_bytes(b"original")

    class FailedOS(WindowsCompatibleOS):
        def fsync(self, descriptor):
            if stage == "flush":
                raise OSError("Authored file flush failure")
            return os.fsync(descriptor)

        def replace(self, source, destination):
            if stage == "replace":
                raise OSError("Authored replace failure")
            return os.replace(source, destination)

    def failed_directory(_):
        raise OSError("Authored directory flush failure")

    monkeypatch.setattr(native, "os", FailedOS())
    if stage == "directory":
        monkeypatch.setattr(native, "sync_directory", failed_directory)
    with pytest.raises(OSError, match="Authored"):
        native.private_write(path, b"complete new file")
    assert path.read_bytes() == (b"complete new file" if stage == "directory" else b"original")
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("where", ["capture", "root"])
def test_authored_directory_reparse_attributes_refuse_native_and_catalog_reads(
    tmp_path, monkeypatch, where
):
    storage = native.ApplicationStore(Store(tmp_path))
    capture = retained(storage)
    selected = storage.directory if where == "root" else storage.directory / capture["id"]
    original_lstat = type(selected).lstat

    def information(path):
        if path == selected:
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_file_attributes=0x400)
        return original_lstat(path)

    monkeypatch.setattr(type(selected), "lstat", information)
    with pytest.raises(ValueError, match="original storage folder"):
        storage.load(capture["id"])
    with pytest.raises(ValueError, match="original storage folder"):
        NativeBackupLifecycle(storage).list({})
    if where == "root":
        with pytest.raises(ValueError, match="original storage folder"):
            storage.save({}, {3: b"app", 11: b"static", 12: b"dynamic"})


@pytest.mark.skipif(os.name != "nt", reason="Native NTFS junction case runs on Windows.")
def test_actual_windows_capture_directory_junction_is_refused_without_touching_originals(tmp_path):
    storage = native.ApplicationStore(Store(tmp_path))
    capture = retained(storage)
    folder = storage.directory / capture["id"]
    original = storage.load(capture["id"])
    kept = tmp_path / "kept-original"
    folder.rename(kept)
    result = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(folder), str(kept)], capture_output=True, text=True
    )
    if result.returncode:
        kept.rename(folder)
        pytest.skip("Native NTFS junction creation unavailable: " + result.stderr)
    try:
        assert folder.lstat().st_file_attributes & 0x400
        with pytest.raises(ValueError, match="original storage folder"):
            storage.load(capture["id"])
        with pytest.raises(ValueError, match="original storage folder"):
            NativeBackupLifecycle(storage).list({})
    finally:
        os.rmdir(folder)
        kept.rename(folder)
    assert storage.load(capture["id"]) == original


@pytest.mark.parametrize("platform", ["posix", "nt", "unsupported"])
def test_storage_profile_describes_actual_policy_without_claiming_another_capture_or_lock(
    monkeypatch, platform
):
    monkeypatch.setattr(access, "_PLATFORM", platform)
    profile = native.native_storage_profile()
    assert profile["profile"] == "native-application-storage/1" and profile["platform"] == platform
    assert profile["available"] is (platform != "unsupported")
    assert profile["directory_flush"] is (platform == "posix")
    assert "process_lock" not in profile and "not original capture durability" in profile["scope"]
    if platform == "unsupported":
        assert profile["regular_file_guard"] == profile["file_data_flush"] == "Unavailable"


def test_http_current_storage_policy_is_local_and_never_reseals_existing_capture(tmp_path):
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    capture = retained(storage)
    files = storage.load(capture["id"])[1]
    folder = storage.directory / capture["id"]
    manifest = (folder / "manifest.json").read_bytes()
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        status = client.get("/api/bacnet/controller/native-application/status").json()
        assert status["storage"] == native.native_storage_profile()
        listing = client.post(
            "/api/bacnet/controller/native-application/backup-library/list",
            headers=headers,
            json={},
        ).json()
        assert listing["storage"] == status["storage"]
        assert listing["backups"][0]["evidence_sha256"] == capture["evidence_sha256"]
        exported = client.get("/api/bacnet/controller/native-application/backups/" + capture["id"])
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            assert archive.read("manifest.json") == manifest
            assert all(archive.read(f"file-{key}.bin") == value for key, value in files.items())
        assert json.loads(manifest) == capture and "storage" not in capture
        assert not client.get("/api/session").json()["field_network_open"]
