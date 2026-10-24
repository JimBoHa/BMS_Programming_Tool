# Native file ownership and capture storage

The browser application imports on Windows without importing POSIX-only
`fcntl`. Standard BACnet history and opaque File captures use the same sealed
formats as before. Existing captures reopen without migration or resealing.
This changes local file handling, not controller communication or native program
compatibility. Native IEC host execution still requires POSIX process pipes;
Windows receives an explicit unavailable profile rather than an import error.

## Ownership and safe files

`bms_tool.file_access` preserves POSIX `flock(LOCK_EX | LOCK_NB)` ownership and
uses Windows `msvcrt.locking(LK_NBLCK)` for byte zero. The Windows region may
extend past EOF; opening an empty lock does not write before acquiring ownership.
Unlocking selects the same byte. Closing the native descriptor, including after a
process crash, releases its ownership. Native locking failures never substitute
a thread-only lock. Capture saves keep their two-second maximum contention wait;
compiler process queues allow at most 45 seconds. The outbox fails immediately
if another owner is active. Independent processes and threads are tested.

POSIX regular-file opens require `O_NOFOLLOW`, use `O_NONBLOCK`, and check the
opened descriptor. Windows uses `CreateFileW(FILE_FLAG_OPEN_REPARSE_POINT)` and
validates `GetFileInformationByHandle` attributes plus `GetFileType` on that exact
handle before transferring ownership to `msvcrt.open_osfhandle`. Directories,
final-component symlinks/reparse points, pipes and devices are refused. A failed
inspection or CRT conversion closes the original handle. Handles and descriptors
are non-inheritable. Active Windows handles do not share delete access, so a lock
cannot be detached through ordinary rename/delete while owned.

These checks protect the final file component. The application's data directory
and its ancestors must remain under the user's control; this is not a sandbox
against an administrator or an attacker replacing ancestor directories. Windows
alternate data streams and explicit device/extended-path namespaces are refused.
Unsupported filesystem locking or hard-link operations fail closed. No copy or
replace fallback overwrites an immutable capture.

## Flushes and durability limits

Capture data is flushed with `os.fsync` before exclusive hard-link publication.
POSIX then flushes the containing directory with `fsync`; native errors remain
visible. Windows does not attempt the unsupported ordinary directory open and
makes **no namespace or power-loss durability guarantee**. History/File status
responses expose the active storage profile; the browser displays its durability
statement. File-data flush and successful publication do not prove preservation
through sudden power loss, remote-server failure or storage-device cache loss.

Temco's existing replaceable local journal also uses safe exclusive temporary
files and the same platform-specific directory-flush policy. Its transfer and
recovery protocol has not changed. SQLite outbox ownership shares the safe lock
opener; SQLite retains its own transaction/flush policy. Windows filesystem ACLs
are inherited from the controlled data directory; POSIX mode 0600 is not claimed
to establish an equivalent Windows ACL.

## Acceptance

On a source checkout with installed dependencies, run on both POSIX and Windows:

```text
python -m pytest -q tests/test_file_access.py
python -m pytest -q tests/test_bacnet_history_api.py tests/test_bacnet_files_api.py
```

The first command exercises native independent-process ownership, bounded waits,
normal/crash release, competing threads, exclusive creation, safe native reads,
sealed capture restart/tamper detection and refusal of unavailable hard links.
Only POSIX FIFO and unavailable account-level symlink creation may skip.
Authored Win32 boundary tests additionally cover reparse/directory/device
attributes, exact handle transfer and failures; those are not a substitute for
running the unchanged native tests on Windows. No field networking is used.
Windows 10 x64 with the official Python 3.13.16 embeddable runtime was also
checked in a disposable VM: **24 storage tests passed**, with only the
POSIX FIFO test skipped, and **all five loopback capture API tests passed**.
The nonregular API case uses a real directory on Windows and retains a FIFO on
POSIX. Native Windows symlink refusal, cross-process/thread ownership, crash
release, hard-link publication and capture seal/restart checks executed.

The application wheel from source commit
`57c511ca214f278cabc7ca37751fd1c7d1388179` had SHA-256
`452e5349cc4a5cdf7162c3c67407e644d91b6c1b4b04e9cde595bbf602c6be2c`.
Exact wheel contents and dependency wheels were unpacked into the isolated
runtime; no system installation was performed. App imports, built assets and
local profiles, Structured Text export, simulation, project save and packaged
timezone fallback passed. Field interfaces remained closed during application
acceptance; capture API peers used loopback only. The VM returned stopped.
These results do not establish Windows namespace/power-loss durability, native
IEC execution, external compiler availability or physical controller support.

Primary API references:

- [Python `msvcrt` locking and handle ownership](https://docs.python.org/3.13/library/msvcrt.html)
- [Microsoft `CreateFileW` flags and sharing](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [Microsoft `GetFileInformationByHandle`](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle)
- [Microsoft `_open_osfhandle` ownership](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/open-osfhandle?view=msvc-170)

The Win32 calls use pointer-sized handle signatures. No third-party Windows
package, privileged installer or external lock service is required.
