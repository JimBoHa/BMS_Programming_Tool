"""Native OS ownership/persistence plus authored Win32 failure evidence.

This module also runs unchanged on Windows; Win32 integration tests do not need
administrator privileges. Symlink-specific tests skip only where creation is
unavailable, while simulated handle-attribute failures always remain covered.
"""

import errno
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest
from bms_tool import file_access as access
from bms_tool.bacnet_history import BacnetHistory
from bms_tool.iec import profile

ROOT = Path(__file__).resolve().parents[1]
_NATIVE_WINDOWS_API = access._WindowsAPI


@pytest.fixture
def held_process(tmp_path):
    processes = []

    def start(path):
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "backend")}
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                (
                    "import sys; from bms_tool.file_access import file_lock; "
                    "lock=file_lock(sys.argv[1],timeout=0,busy='busy'); lock.__enter__(); "
                    "print('owned',flush=True); sys.stdin.readline(); lock.__exit__(None,None,None)"
                ),
                str(path),
            ],
            cwd=tmp_path,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append(process)
        ready = Queue()
        threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
        assert ready.get(timeout=10) == "owned\n"
        return process

    yield start
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def test_actual_process_ownership_is_bounded_and_crash_releases_lock(tmp_path, held_process):
    path = tmp_path / "owned.lock"
    child = held_process(path)
    started = time.monotonic()
    with pytest.raises(ValueError, match="busy"):
        with access.file_lock(path, timeout=0.08, busy="busy"):
            pytest.fail("A second process acquired active ownership")
    assert time.monotonic() - started < 1
    assert path.stat().st_size == 0  # no write before owning byte zero
    child.kill()
    child.communicate(timeout=10)
    with access.file_lock(path, timeout=1, busy="busy") as descriptor:
        assert not os.get_inheritable(descriptor)
        assert access.regular_file(os.fstat(descriptor))


def test_normal_process_exit_releases_os_ownership(tmp_path, held_process):
    path = tmp_path / "owned.lock"
    child = held_process(path)
    child.communicate("release\n", timeout=10)
    assert child.returncode == 0
    with access.file_lock(path, timeout=1, busy="busy"):
        assert path.stat().st_size == 0


def test_thread_enters_only_after_owner_releases(tmp_path):
    path = tmp_path / "thread.lock"
    entered, attempt = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with access.file_lock(path, timeout=1, busy="busy"):

            def waiting():
                attempt.set()
                with access.file_lock(path, timeout=2, busy="busy"):
                    entered.set()

            worker = executor.submit(waiting)
            assert attempt.wait(1) and not entered.wait(0.05)
        worker.result(timeout=2)
    assert entered.is_set()


def test_exclusive_file_creation_never_replaces_existing_bytes_and_is_not_inherited(tmp_path):
    path = tmp_path / "capture"
    descriptor = access.open_regular(path, writable=True, create=True, exclusive=True)
    assert not os.get_inheritable(descriptor)
    os.write(descriptor, b"source bytes\x00\xff")
    os.fsync(descriptor)
    os.close(descriptor)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        access.open_regular(path, writable=True, create=True, exclusive=True)
    with os.fdopen(access.open_regular(path), "rb") as stream:
        assert stream.read() == before == b"source bytes\x00\xff"
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(before).digest()


def test_native_opens_refuse_directories_and_final_symlinks_without_touching_target(tmp_path):
    with pytest.raises((ValueError, OSError)):
        access.open_regular(tmp_path, writable=True)
    target, link = tmp_path / "target", tmp_path / "link"
    target.write_bytes(b"unchanged")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("This OS/account cannot create a symlink; reparse API tests still run")
    with pytest.raises((ValueError, OSError)):
        access.open_regular(link, writable=True, create=True)
    assert target.read_bytes() == b"unchanged"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is a POSIX-specific file kind")
def test_fifo_open_never_waits_for_writer_or_mutates_fifo(tmp_path):
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    started = time.monotonic()
    with pytest.raises(ValueError, match="regular file"):
        access.open_regular(fifo)
    assert time.monotonic() - started < 0.5
    with pytest.raises(ValueError, match="regular file"):
        access.open_regular(fifo, writable=True, create=True)


def _history(directory):
    connector = SimpleNamespace(status=lambda: {"connected": False})
    return BacnetHistory(connector, directory)


def _report(identifier):
    return {
        "id": identifier,
        "profile": "bacnet-trend-log-history/1",
        "source_kind": "device-history",
        "target": {"device": "device,42"},
        "read_at": "2026-10-21T12:00:00+00:00",
        "received_at": "2026-10-21T12:00:01+00:00",
        "complete": True,
        "truncated": False,
        "records": [
            {"value": 21.5, "local_timestamp": "2026-10-21T05:00:00", "quality": "unknown"}
        ],
    }


def test_actual_capture_save_restart_seal_and_busy_owner_preserve_bytes(
    tmp_path, held_process, monkeypatch
):
    import bms_tool.bacnet_history as history

    service = _history(tmp_path)
    identifier = "a" * 32
    report = _report(identifier)
    service._reports[identifier] = report
    held = held_process(service.directory / ".capture.lock")
    monkeypatch.setattr(history, "CAPTURE_LOCK_SECONDS", 0.05)
    with pytest.raises(ValueError, match="storage is busy"):
        service.save(identifier)
    assert service.captures() == [] and not list(service.directory.glob("*.tmp"))
    held.communicate("release\n", timeout=10)
    saved = service.save(identifier)
    path = service.directory / ("capture-" + identifier + ".json")
    original = path.read_bytes()
    restarted = _history(tmp_path)
    assert restarted.capture(identifier) == report
    assert restarted.save(identifier) == saved
    assert path.read_bytes() == original
    wrapper = json.loads(original)
    wrapper["report"]["records"][0]["value"] = -100
    path.write_text(json.dumps(wrapper))
    with pytest.raises(ValueError, match="integrity"):
        restarted.capture(identifier)


def test_unsupported_hardlink_publication_fails_closed_without_replacing_capture(
    tmp_path, monkeypatch
):
    service = _history(tmp_path)
    identifier = "b" * 32
    service._reports[identifier] = _report(identifier)

    def unsupported(*args):
        raise OSError(errno.ENOTSUP, "Hardlinks unavailable")

    monkeypatch.setattr(os, "link", unsupported)
    with pytest.raises(OSError, match="Hardlinks unavailable"):
        service.save(identifier)
    assert service.captures() == [] and not list(service.directory.glob("*.tmp"))


def test_unsupported_platform_and_native_lock_errors_do_not_enter_critical_section(
    tmp_path, monkeypatch
):
    with os.fdopen(
        access.open_regular(tmp_path / "file", writable=True, create=True), "wb"
    ) as stream:
        descriptor = stream.fileno()
        monkeypatch.setattr(access, "_PLATFORM", "unsupported")
        with pytest.raises(OSError, match="unavailable"):
            access.try_lock(descriptor)
    with pytest.raises(OSError, match="unavailable"):
        access.open_regular(tmp_path / "file")


def test_windows_profile_never_claims_directory_or_powerloss_durability(monkeypatch):
    monkeypatch.setattr(access, "_PLATFORM", "nt")
    monkeypatch.setattr(os, "open", lambda *args: pytest.fail("Windows directory open attempted"))
    assert access.sync_directory("unused") is False
    status = access.storage_profile()
    assert status["directory_flush"] is False
    assert "unverified" in status["durability"]


def test_nonposix_iec_is_normal_unavailable_profile_without_toolchain_access(monkeypatch):
    import bms_tool.iec as iec

    monkeypatch.setattr(iec, "os", SimpleNamespace(name="nt"))
    result = profile()
    assert result["available"] is False and "POSIX process pipes" in result["error"]
    assert result["physical_io"] is result["controller_download"] is False


class AuthoredWindowsAPI:
    """Injected native boundary; test handle lifetime, never fake OS lock ownership."""

    def __init__(self, *, attributes=0, file_type=1, conversion_error=False):
        self.attributes, self.file_type = attributes, file_type
        self.conversion_error = conversion_error
        self.closed, self.converted = [], []

    def open(self, path, **options):
        self.path, self.options = path, options
        return 0x1234567812345678

    def validate(self, handle):
        # Exercise the actual Win32 validator with authored native responses.
        native = object.__new__(_NATIVE_WINDOWS_API)
        native.ctypes = SimpleNamespace(byref=lambda item: item)
        native.information_type = lambda: SimpleNamespace(attributes=self.attributes)
        native.information = lambda handle, information: True
        native.kind = lambda handle: self.file_type
        _NATIVE_WINDOWS_API.validate(native, handle)

    def descriptor(self, handle, *, writable):
        self.converted.append((handle, writable))
        if self.conversion_error:
            raise OSError(errno.EBADF, "CRT conversion rejected")
        return 51

    def close(self, handle):
        self.closed.append(handle)


@pytest.mark.parametrize("attributes,kind", [(0x400, 1), (0x10, 1), (0, 2), (0, 3)])
def test_authored_windows_native_handle_rejects_reparse_directory_pipe_device(
    monkeypatch,
    attributes,
    kind,
):
    api = AuthoredWindowsAPI(attributes=attributes, file_type=kind)
    monkeypatch.setattr(access, "_WindowsAPI", lambda: api)
    with pytest.raises(ValueError, match="regular file"):
        access._windows_open("capture.json", writable=True, create=True, exclusive=False)
    assert api.closed == [0x1234567812345678] and not api.converted


def test_authored_windows_handle_transfer_uses_same_validated_handle_and_closes_on_failure(
    monkeypatch,
):
    api = AuthoredWindowsAPI()
    monkeypatch.setattr(access, "_WindowsAPI", lambda: api)
    assert access._windows_open("capture.json", writable=False, create=False, exclusive=False) == 51
    assert api.options == {"writable": False, "create": False, "exclusive": False}
    assert api.converted == [(0x1234567812345678, False)] and not api.closed
    api.conversion_error = True
    with pytest.raises(OSError, match="CRT conversion"):
        access._windows_open("capture.json", writable=True, create=True, exclusive=True)
    assert api.closed == [0x1234567812345678]


@pytest.mark.parametrize(
    "native_errno,busy", [(errno.EACCES, True), (errno.EAGAIN, True), (errno.EBADF, False)]
)
def test_authored_windows_lock_uses_exact_byte_zero_and_native_failure_never_succeeds(
    tmp_path,
    monkeypatch,
    native_errno,
    busy,
):
    path = tmp_path / "lock"
    descriptor = access.open_regular(path, writable=True, create=True)
    calls = []

    def locking(fd, mode, count):
        calls.append((fd, mode, count, os.lseek(fd, 0, os.SEEK_CUR)))
        raise OSError(native_errno, "Native failure")

    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(LK_NBLCK=2, locking=locking))
    monkeypatch.setattr(access, "_PLATFORM", "nt")
    try:
        os.lseek(descriptor, 12, os.SEEK_SET)
        with pytest.raises(BlockingIOError if busy else OSError):
            access.try_lock(descriptor)
        assert calls == [(descriptor, 2, 1, 0)]
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)


def test_application_import_does_not_require_posix_lock_module(tmp_path):
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "backend")}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'fcntl' and args and (args[0] or {}).get('__name__', '').startswith('bms_tool'):
        raise ImportError('POSIX-only module unavailable')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from bms_tool.app import create_app
assert callable(create_app)
""",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")


@pytest.mark.parametrize(
    "exclusive,create,disposition", [(True, True, 1), (False, True, 4), (False, False, 3)]
)
def test_authored_windows_createfile_flags_never_follow_or_overwrite(
    exclusive, create, disposition
):
    api = object.__new__(_NATIVE_WINDOWS_API)
    calls = []
    api.ctypes = SimpleNamespace(c_void_p=lambda value: SimpleNamespace(value=value))

    def native_create(*args):
        calls.append(args)
        return 0x1234567812345678

    api.create = native_create
    assert (
        api.open("C:\\data\\capture", writable=True, create=create, exclusive=exclusive)
        == 0x1234567812345678
    )
    _, access_flags, share, security, actual, flags, template = calls[0]
    assert access_flags == 0xC0000000 and share == 3 and actual == disposition
    assert flags & 0x00200000 and flags & 0x02000000
    assert security is template is None


def test_authored_windows_native_attribute_failure_fails_closed():
    native = object.__new__(_NATIVE_WINDOWS_API)
    native.ctypes = SimpleNamespace(byref=lambda item: item)
    native.information_type = lambda: SimpleNamespace(attributes=0)
    native.information = lambda *args: False
    native.error = lambda: OSError(errno.EIO, "Native metadata unavailable")
    with pytest.raises(OSError, match="metadata unavailable"):
        native.validate(0x1234567812345678)


def test_native_lock_error_closes_descriptor_without_entering_or_unlocking(tmp_path, monkeypatch):
    descriptor = access.open_regular(tmp_path / "lock", writable=True, create=True)
    monkeypatch.setattr(access, "open_regular", lambda *args, **kwargs: descriptor)

    def broken(fd):
        raise OSError(errno.EBADF, "Native lock failed")

    monkeypatch.setattr(access, "try_lock", broken)
    monkeypatch.setattr(access, "unlock", lambda fd: pytest.fail("Unowned unlock attempted"))
    with pytest.raises(OSError, match="Native lock failed"):
        with access.file_lock(tmp_path / "lock", timeout=0.05, busy="busy"):
            pytest.fail("Entered critical section without native ownership")
    with pytest.raises(OSError):
        os.fstat(descriptor)
