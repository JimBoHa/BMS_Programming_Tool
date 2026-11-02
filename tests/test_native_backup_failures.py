"""A failed read must not hide uncertainty about ending its backup session."""

import asyncio

import pytest

from .test_native_applications import native_link as native_link  # noqa: F401


@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_failed_file_read_reports_its_position_and_cleanup_outcome(native_link, cleanup_fails):
    peer, bacnet, _, service, target = native_link
    peer.mode = "drop-file-read-and-end-backup" if cleanup_fails else "drop-file-read"
    with pytest.raises(ValueError) as error:
        await service.capture(**target, operation_id="interrupted-file-backup")
    message = str(error.value)
    assert "File 11 read failed at byte offset 0" in message
    assert ("Ending the backup session was also not confirmed" in message) is cleanup_fails
    assert peer.events == [("state", "start-backup"), ("read", 11, 0), ("state", "end-backup")]
    assert not service.storage.receipts() and not service.storage.captures()
    assert not bacnet.app.asap.clientTransactions and not bacnet.lock.locked()


async def test_complete_files_are_not_published_when_backup_completion_is_unconfirmed(native_link):
    peer, _, _, service, target = native_link
    peer.mode = "drop-end-backup"
    with pytest.raises(ValueError, match="Original files read, but ending the backup session"):
        await service.capture(**target, operation_id="unconfirmed-backup-completion")
    assert [e for e in peer.events if e[0] == "state"] == [
        ("state", "start-backup"),
        ("state", "end-backup"),
    ]
    assert not any(e[0] == "write" for e in peer.events)
    assert not service.storage.captures()


async def test_cancelled_capture_keeps_cancellation_notice_and_cleanup_detail(native_link, monkeypatch):
    peer, bacnet, _, service, target = native_link
    peer.mode = "drop-end-backup"

    async def cancel_read(*args, **kwargs):
        raise asyncio.CancelledError("Operator cancelled the capture")

    monkeypatch.setattr(service.files, "read", cancel_read)
    with pytest.raises(ValueError) as error:
        await service.capture(**target, operation_id="cancelled-backup-cleanup")
    assert "Native operation cancelled" in str(error.value)
    assert "Ending the backup session was also not confirmed" in str(error.value)
    assert peer.events == [("state", "start-backup"), ("state", "end-backup")]
    assert not service.storage.captures() and not service.storage.receipts()
    assert not bacnet.app.asap.clientTransactions and not bacnet.lock.locked()


async def test_operation_timeout_preserves_unconfirmed_cleanup_detail(native_link, monkeypatch):
    peer, _, _, service, target = native_link
    peer.mode = "drop-end-backup"
    service.operation_timeout = 0.3

    async def wait_for_timeout(*args, **kwargs):
        await asyncio.sleep(10)

    monkeypatch.setattr(service.files, "read", wait_for_timeout)
    with pytest.raises(ValueError) as error:
        await service.capture(**target, operation_id="timed-out-backup-cleanup")
    assert "Native operation timed out" in str(error.value)
    assert "Ending the backup session was also not confirmed" in str(error.value)
    assert peer.events == [("state", "start-backup"), ("state", "end-backup")]
    assert not service.storage.captures() and not service.storage.receipts()
