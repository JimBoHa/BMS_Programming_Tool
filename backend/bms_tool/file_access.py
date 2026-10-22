"""Native regular-file handles and process ownership, with no unsafe fallback.

Windows rejects final-component reparse points using an opened Win32 handle,
not a path check followed by a potentially following CRT open. POSIX keeps
O_NOFOLLOW and nonblocking opens so a substituted FIFO cannot stall a caller.
"""

from __future__ import annotations

import errno
import os
import stat
import time
from contextlib import contextmanager

_PLATFORM = os.name
_REPARSE_POINT = 0x400
_DIRECTORY = 0x10


def regular_file(information):
    return stat.S_ISREG(information.st_mode) and not (
        getattr(information, "st_file_attributes", 0) & _REPARSE_POINT
    )


class _WindowsAPI:
    """Bind handle-sized Win32 types lazily; importing on POSIX remains safe."""

    def __init__(self):
        import ctypes
        import msvcrt
        from ctypes import wintypes

        self.ctypes, self.msvcrt = ctypes, msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.create = kernel.CreateFileW
        self.create.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.create.restype = wintypes.HANDLE
        self.close = kernel.CloseHandle
        self.close.argtypes, self.close.restype = [wintypes.HANDLE], wintypes.BOOL
        self.kind = kernel.GetFileType
        self.kind.argtypes, self.kind.restype = [wintypes.HANDLE], wintypes.DWORD

        class FileInformation(ctypes.Structure):
            _fields_ = [
                ("attributes", wintypes.DWORD),
                ("creation", wintypes.FILETIME),
                ("access", wintypes.FILETIME),
                ("write", wintypes.FILETIME),
                ("volume", wintypes.DWORD),
                ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD),
                ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD),
                ("index_low", wintypes.DWORD),
            ]

        self.information_type = FileInformation
        self.information = kernel.GetFileInformationByHandle
        self.information.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInformation)]
        self.information.restype = wintypes.BOOL

    def error(self):
        return self.ctypes.WinError(self.ctypes.get_last_error())

    def open(self, path, *, writable, create, exclusive):
        # No FILE_SHARE_DELETE: replacement cannot detach an active lock handle.
        handle = self.create(
            path,
            0x80000000 | (0x40000000 if writable else 0),
            0x1 | 0x2,
            None,
            1 if exclusive else (4 if create else 3),
            0x00200000 | 0x02000000,
            None,
        )
        if handle == self.ctypes.c_void_p(-1).value:
            raise self.error()
        return handle

    def validate(self, handle):
        information = self.information_type()
        if not self.information(handle, self.ctypes.byref(information)):
            raise self.error()
        if information.attributes & (_REPARSE_POINT | _DIRECTORY) or self.kind(handle) != 1:
            raise ValueError(
                "A regular file is required; symlinks, reparse points and devices are refused."
            )

    def descriptor(self, handle, *, writable):
        # CRT owns the handle after successful conversion, including on close.
        return self.msvcrt.open_osfhandle(
            handle, (0 if writable else os.O_RDONLY) | os.O_BINARY | os.O_NOINHERIT
        )


def _windows_open(path, *, writable, create, exclusive):
    # Alternate data streams and device namespaces are not capture files.
    path = os.path.abspath(os.fspath(path))
    if ":" in os.path.splitdrive(path)[1] or path.startswith(("\\\\.\\", "\\\\?\\")):
        raise ValueError("Windows device namespaces and alternate data streams are refused.")
    api = _WindowsAPI()
    handle = api.open(path, writable=writable, create=create, exclusive=exclusive)
    try:
        api.validate(handle)
        descriptor = api.descriptor(handle, writable=writable)
    except BaseException:
        api.close(handle)
        raise
    return descriptor


def open_regular(path, *, writable=False, create=False, exclusive=False, mode=0o600):
    """Return a non-inheritable descriptor, without following the final link."""
    if exclusive and not create:
        raise ValueError("Exclusive file creation requires create=True.")
    if _PLATFORM == "nt":
        descriptor = _windows_open(path, writable=writable, create=create, exclusive=exclusive)
    elif _PLATFORM == "posix":
        if not hasattr(os, "O_NOFOLLOW"):
            raise OSError(errno.ENOTSUP, "Safe regular-file opens require O_NOFOLLOW.")
        flags = (
            (os.O_RDWR if writable else os.O_RDONLY)
            | os.O_NOFOLLOW
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | (os.O_CREAT if create else 0)
            | (os.O_EXCL if exclusive else 0)
        )
        descriptor = os.open(path, flags, mode)
    else:
        raise OSError(errno.ENOTSUP, "Native safe-file profile is unavailable on this platform.")
    try:
        if not regular_file(os.fstat(descriptor)):
            raise ValueError("A regular file is required; symlinks and devices are refused.")
        os.set_inheritable(descriptor, False)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def try_lock(descriptor):
    """Own byte zero on Windows, or the file via POSIX flock; never wait here."""
    if _PLATFORM == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            # Locking past EOF is supported; writing before ownership is unsafe.
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise BlockingIOError(exc.errno, "File ownership is busy.") from exc
            raise
    elif _PLATFORM == "posix":
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        raise OSError(errno.ENOTSUP, "Native file locking is unavailable on this platform.")


def unlock(descriptor):
    if _PLATFORM == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    elif _PLATFORM == "posix":
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)
    else:
        raise OSError(errno.ENOTSUP, "Native file locking is unavailable on this platform.")


@contextmanager
def file_lock(path, *, timeout, busy, unavailable=None):
    try:
        descriptor = open_regular(path, writable=True, create=True)
    except OSError as exc:
        if unavailable:
            raise ValueError(unavailable) from exc
        raise
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                try_lock(descriptor)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError(busy) from None
                time.sleep(0.01)
            except OSError as exc:
                if unavailable:
                    raise ValueError(unavailable) from exc
                raise
        try:
            yield descriptor
        finally:
            unlock(descriptor)
    finally:
        os.close(descriptor)


def sync_directory(path):
    """Flush POSIX namespace changes; Windows has no claimed directory flush."""
    if _PLATFORM == "nt":
        return False
    if _PLATFORM != "posix":
        raise OSError(errno.ENOTSUP, "Directory durability profile is unavailable.")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


def storage_profile():
    return {
        "platform": _PLATFORM,
        "process_lock": "msvcrt byte zero" if _PLATFORM == "nt" else "POSIX flock",
        "regular_file_guard": (
            "Win32 handle attributes; final reparse points refused"
            if _PLATFORM == "nt"
            else "O_NOFOLLOW and regular-file descriptor"
        ),
        "file_data_flush": "os.fsync before exclusive hard-link publication",
        "directory_flush": _PLATFORM == "posix",
        "durability": (
            "File data flushed; namespace/power-loss durability unverified on Windows."
            if _PLATFORM == "nt"
            else "File and directory fsync; filesystem/hardware guarantees apply."
        ),
    }
