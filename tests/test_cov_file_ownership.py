"""Real COV writer admission through native cross-platform safe-file ownership."""

import os
from pathlib import Path

import pytest
from bms_tool.cov_observations import _WriterLock

from .test_file_access import held_process as held_process


def test_competing_cov_writer_cannot_change_empty_lock_before_ownership(tmp_path):
    path = tmp_path / "writer.lock"
    owner = _WriterLock(path)
    descriptor = owner.fd
    try:
        assert path.stat().st_size == 0
        assert not os.get_inheritable(descriptor)
        with pytest.raises(ValueError, match="ownership unavailable"):
            _WriterLock(path)
        assert path.stat().st_size == 0
        os.fstat(descriptor)  # A refused competitor did not close the owner.
    finally:
        owner.close()
        owner.close()
    with pytest.raises(OSError):
        os.fstat(descriptor)
    replacement = _WriterLock(path)
    replacement.close()


def test_cov_writer_obeys_other_native_process_and_reclaims_after_crash(tmp_path, held_process):
    path = tmp_path / "writer.lock"
    child = held_process(path)
    with pytest.raises(ValueError, match="ownership unavailable"):
        _WriterLock(path)
    assert path.stat().st_size == 0
    child.kill()
    child.communicate(timeout=10)
    replacement = _WriterLock(path)
    try:
        assert not os.get_inheritable(replacement.fd)
        assert path.stat().st_size == 0
    finally:
        replacement.close()


def test_cov_writer_refuses_final_symlink_without_touching_unrelated_file(tmp_path):
    target = tmp_path / "unrelated.txt"
    target.write_bytes(b"unchanged contents")
    link = tmp_path / "writer.lock"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("This account cannot create a native symlink")
    with pytest.raises(ValueError, match="ownership unavailable"):
        _WriterLock(link)
    assert target.read_bytes() == b"unchanged contents"
    assert link.is_symlink()


def test_cov_writer_refuses_directory_and_posix_fifo(tmp_path):
    with pytest.raises(ValueError, match="ownership unavailable"):
        _WriterLock(tmp_path)
    if hasattr(os, "mkfifo"):
        fifo = Path(tmp_path) / "writer.fifo"
        os.mkfifo(fifo)
        with pytest.raises(ValueError, match="ownership unavailable"):
            _WriterLock(fifo)
