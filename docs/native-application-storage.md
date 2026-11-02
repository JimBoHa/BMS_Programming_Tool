# Native application storage on Mac and Windows

Native application backups, reviewed payloads and local controller-family
credential files now use the existing [native safe-file layer](portable-storage.md).
They retain their original serialized formats, IDs, seals, paths and read limits.
Existing originals reopen without migration or resealing. The change does not
alter BACnet requests, compiler output, reviews, transfers or controller settings.

## Complete files and original evidence

Writes create an exclusive private temporary file through `open_regular`, write
and flush all bytes with `os.fsync`, then publish the complete file with
`os.replace`. The temporary file is cleaned up after an acquired write, including
failure. There is no partial-copy or overwrite fallback when exclusive creation,
flush or publication fails. A directory-flush error after publication remains an
error; complete published bytes do not establish namespace durability.

Reads obtain the checked native regular-file descriptor before reading at most
the existing limit plus one byte. POSIX uses nonblocking, no-follow opens and
descriptor checks. Windows uses `CreateFileW` with `FILE_FLAG_OPEN_REPARSE_POINT`,
validates the actual handle's attributes and type, then transfers that same
handle to the CRT. Reparse points, directories, pipes and devices are refused;
failed handle validation closes the handle. The shared layer also refuses
Windows device namespaces and alternate data streams.

The native capture directory and each retained capture folder must be real
directories. `lstat` refuses symlinks and Windows reparse attributes, including
NTFS junctions, before reading retained sources or catalog manifests. The data
directory and its ancestors remain under the user's control; this is not a
sandbox against an administrator replacing parent paths concurrently.

POSIX file permissions remain private. Windows file ACLs inherit from the
controlled directory; mode `0600` alone is not an equivalent Windows ACL claim.
Original manifests and original Files 3/11/12 are not updated with the new
computer's storage policy. That policy must not be mistaken for how an older or
copied capture was originally acquired or persisted.

## Current storage policy

In **History → Native backups → Storage on this computer**, the current policy
appears separately from the selected source's original evidence. Native status
and backup catalog responses expose `storage` with profile
`native-application-storage/1`. It records the current platform, availability,
regular-file guard, complete-file flush/replace policy and directory-flush policy.
It does not claim a separate native process lock: catalog capacity and transfer
evidence retain their existing SQLite transactions. Lifecycle and transfer
updates retain `synchronous=FULL`.

On POSIX, publication flushes the directory; errors remain visible. On Windows,
the existing native policy skips the unsupported ordinary directory open and
reports **file data flushed; namespace/power-loss durability unverified**. It
never silently claims POSIX directory-flush behavior. Unsupported platforms
report unavailable safe native storage and fail closed at the safe-file opener.
Unknown browser metadata appears unavailable instead of supplying another
platform's guarantees.

## Acceptance

`tests/test_native_application_storage.py` exercises native file replacement and
bounded reads, exact credentials round trips, flush/publication order, failure
visibility, descriptor cleanup, directory reparse refusal and local HTTP source
preservation. Its authored Win32 boundary explicitly lacks POSIX-only constants
and refuses ordinary directory opens. These tests are separate from native
Windows execution. The unchanged shared safe-file tests cover real process
ownership and native handle contracts.

The native NTFS-junction case runs only on Windows and restores its authored
original folder after checking refusal. Browser tests cover both local entry
paths, current source evidence and an explicitly authored Windows policy, plus
unknown metadata without field requests. Existing native compilation, capture,
typed transfers, archiving and restart recovery retain separate regression tests.
Package acceptance uses an isolated installed wheel. Software peer tests do not
establish physical controller, BTCVT, driver or whole-state migration acceptance.

FIFO construction uses Python's [Unix-only `os.mkfifo`](https://docs.python.org/3.13/library/os.html#os.mkfifo)
where available. Windows has a separate native case: create a real
[named-pipe handle](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-createnamedpipew),
confirm its [`FILE_TYPE_PIPE`](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfiletype)
classification and require refusal and handle closure before CRT conversion or
reading. The original failing Windows FIFO-setup run remains retained; its
fixture correction changes no product guard or original assertion body.

An isolated Windows 10 x64 / CPython 3.13.16 run passed 64 storage tests, including
native named-pipe and NTFS-junction cases, archive/restart retention, competing
capacity claims and all six typed recovery families. Only the two Unix FIFO
constructors were skipped. An independent native before/after probe reproduced
the original directory-open and missing-flag failures before exercising the new
safe file path. This qualifies local storage on that host; controller transports
and physical acceptance remain separate.
