"""Retain capture space before native state commands without reserving catalog slots."""

import asyncio
import copy
from contextlib import asynccontextmanager

import pytest
from bms_tool.application_store import ApplicationStore
from bms_tool.native_backup_import import NativeBackupImports
from bms_tool.native_backup_lifecycle import NativeBackupLifecycle
from bms_tool.storage import Store

from .test_native_applications import apply_request, review
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_backup_lifecycle import transition
from .test_native_connection_transfer import applying, connection_review
from .test_native_default_transfer import NativeRouter


@pytest.fixture(params=[False, True], ids=["direct", "routed"])
async def connection_case(native_link, request):
    transport = None
    try:
        target = None
        if request.param:
            host, port = native_link[-1]["address"].split(":")
            transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
            )
            target = {
                **native_link[-1],
                "address": "3001:7",
                "router": proxy.endpoint,
                "dnet": 3001,
            }
        _, plan = await connection_review(native_link, target=target)
        yield native_link, plan
    finally:
        if transport:
            transport.close()
            await asyncio.sleep(0.02)


def count(storage):
    with storage.store.connect() as db:
        return len(storage.active_folders(db))


def fill(storage, total, files):
    added = []
    while count(storage) < total:
        added.append(storage.save({}, files))
    assert count(storage) == total
    return added


def incoming(storage, capture_id, directory):
    manifest, files = storage.load(capture_id)
    other = ApplicationStore(Store(directory))
    metadata = {
        k: v
        for k, v in manifest.items()
        if k not in {"id", "files", "evidence_sha256", "captured_at", "profile"}
    }
    capture = other.save(metadata, files)
    return other.export(capture["id"]), capture


def test_capacity_observation_keeps_128_limit_and_does_not_reserve_or_delete(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    files = {3: b"Authored original", 11: b"Authored directory", 12: b"Authored values"}
    captures = fill(storage, 126, files)
    before = {p: p.read_bytes() for p in storage.directory.glob("*/*") if p.is_file()}
    storage.require_capture_capacity(2)
    # A different writer can still use space after this point-in-time observation.
    other = ApplicationStore(Store(tmp_path))
    other.save({}, files)
    assert count(storage) == 127
    storage.require_capture_capacity()
    with pytest.raises(ValueError, match="2 required snapshot"):
        storage.require_capture_capacity(2)
    other.save({}, files)
    with pytest.raises(ValueError, match="1 required snapshot"):
        storage.require_capture_capacity()
    with pytest.raises(ValueError, match="storage is full"):
        storage.save({}, files)
    assert count(storage) == 128
    assert all(p.read_bytes() == raw for p, raw in before.items())
    library = NativeBackupLifecycle(storage)
    transition(library, captures[0])
    assert storage.load(captures[0]["id"])[1] == files
    restarted = ApplicationStore(Store(tmp_path))
    restarted.require_capture_capacity()
    with pytest.raises(ValueError, match="2 required snapshot"):
        restarted.require_capture_capacity(2)
    transition(library, captures[0], "restore", 1)
    assert count(storage) == 128
    with pytest.raises(ValueError, match="1 required snapshot"):
        restarted.require_capture_capacity()


@pytest.mark.parametrize("needed", [True, False, 0, -1, 129, 1.0, "1", None])
def test_invalid_capacity_request_does_not_read_catalog(tmp_path, monkeypatch, needed):
    storage = ApplicationStore(Store(tmp_path))
    monkeypatch.setattr(
        storage, "active_folders", lambda _: pytest.fail("Invalid count reached the catalog")
    )
    with pytest.raises(ValueError, match="bounded positive"):
        storage.require_capture_capacity(needed)


async def test_full_capture_refuses_before_entering_a_network_path(native_link, monkeypatch):
    peer, _, _, native, target = native_link
    fill(native.storage, 128, peer.files)
    monkeypatch.setattr(
        native.path, "_path", lambda _: pytest.fail("Full catalog opened a field path")
    )
    with pytest.raises(ValueError, match="1 required snapshot"):
        await native.capture(**target, operation_id="full-capacity-capture")
    assert not peer.events and not native.storage.receipts() and native.active is None
    assert count(native.storage) == 128


async def test_apply_needs_two_slots_before_collision_or_backup(connection_case, monkeypatch):
    native_link, plan = connection_case
    peer, _, _, native, _ = native_link
    fill(native.storage, 127, peer.files)
    before, files = copy.deepcopy(peer.events), copy.deepcopy(peer.files)
    monkeypatch.setattr(
        native.path, "_path", lambda _: pytest.fail("Insufficient capacity opened a field path")
    )
    result = await native.apply_connection(**applying(plan))
    assert result["intent"] is None and result["result"]["status"] == "not_sent"
    assert not result["result"]["may_have_applied"]
    assert not result["result"]["protocol_accepted"]
    assert any("2 required snapshot" in error for error in result["result"]["errors"])
    assert peer.events == before and peer.files == files
    assert not native.storage.receipts() and count(native.storage) == 127
    assert native.active is None
    with pytest.raises(ValueError, match="consumed"):
        await native.apply_connection(**applying(plan, operation_id="fresh-capacity-apply"))


async def test_two_remaining_slots_retain_original_and_complete_verified_readback(connection_case):
    native_link, plan = connection_case
    peer, _, _, native, _ = native_link
    added = fill(native.storage, 126, peer.files)
    original = native.storage.load(added[0]["id"])
    result = await native.apply_connection(**applying(plan))
    assert result["result"]["status"] == "verified", result
    assert result["pending"] is False and count(native.storage) == 128
    assert native.storage.load(added[0]["id"]) == original
    assert native.storage.load(result["intent"]["backup_id"])
    assert native.storage.load(result["result"]["verification_capture_id"])
    assert [e for e in peer.events if e == ("state", "start-restore")] == [
        ("state", "start-restore")
    ]


async def test_import_using_last_slot_during_preflight_refuses_restore(
    native_link, monkeypatch, tmp_path
):
    peer, _, _, native, _ = native_link
    _, plan = await connection_review(native_link)
    raw, imported = incoming(native.storage, plan["capture_id"], tmp_path / "incoming")
    fill(native.storage, 126, peer.files)
    save = native.storage.save
    seen = []

    def competing_import(metadata, files):
        capture = save(metadata, files)
        assert count(native.storage) == 127
        seen.append(
            NativeBackupImports(native.storage).import_archive(raw, "authored-original.zip")
        )
        return capture

    monkeypatch.setattr(native.storage, "save", competing_import)
    result = await native.apply_connection(**applying(plan))
    assert len(seen) == 1 and count(native.storage) == 128
    assert native.storage.load(imported["id"])[1]
    assert result["intent"] is None and result["result"]["status"] == "not_sent"
    assert any("1 required snapshot" in error for error in result["result"]["errors"])
    assert not native.storage.receipts()
    assert [e[1] for e in peer.events if e[0] == "state"][-2:] == [
        "start-backup",
        "end-backup",
    ]
    assert not any(e == ("state", "start-restore") for e in peer.events)


async def test_post_dispatch_import_keeps_uncertainty_until_explicit_readback(
    native_link, tmp_path
):
    peer, _, _, native, _ = native_link
    _, plan = await connection_review(native_link)
    raw, imported = incoming(native.storage, plan["capture_id"], tmp_path / "incoming")
    fill(native.storage, 126, peer.files)
    seen = []

    def import_after_dispatch():
        if not seen:
            assert count(native.storage) == 127
            seen.append(
                NativeBackupImports(native.storage).import_archive(raw, "authored-later.zip")
            )

    peer.dispatch = import_after_dispatch
    result = await native.apply_connection(**applying(plan))
    assert len(seen) == 1 and count(native.storage) == 128
    assert result["intent"] and result["pending"] and result["result"]["status"] == "unknown"
    assert "1 required snapshot" in result["result"]["error"]
    assert result["result"]["may_have_applied"]
    NativeBackupLifecycle(native.storage).change(
        {
            "capture_id": imported["id"],
            "snapshot_sha256": imported["evidence_sha256"],
            "expected_revision": 0,
            "action": "archive",
        }
    )
    assert count(native.storage) == 127
    observed = await native.reconcile(
        operation_id="capacity-explicit-readback", receipt_id=result["intent"]["id"]
    )
    assert observed["result"] == result["result"]
    assert observed["latest_readback"]["status"] == "verified" and not observed["pending"]
    assert count(native.storage) == 128
    assert sum(e == ("state", "start-restore") for e in peer.events) == 1


async def test_full_readback_keeps_original_receipt_without_a_network_observation(
    native_link, monkeypatch
):
    peer, _, _, native, _ = native_link
    _, plan = await connection_review(native_link)
    peer.mode = "drop-end"
    result = await native.apply_connection(**applying(plan))
    assert result["pending"] and result["result"]["status"] == "unknown"
    fill(native.storage, 128, peer.files)
    before = native.storage.receipt(result["intent"]["id"])
    events = copy.deepcopy(peer.events)
    monkeypatch.setattr(
        native.path, "_path", lambda _: pytest.fail("Full readback opened a field path")
    )
    with pytest.raises(ValueError, match="1 required snapshot"):
        await native.reconcile(
            operation_id="full-capacity-readback", receipt_id=result["intent"]["id"]
        )
    assert native.storage.receipt(result["intent"]["id"]) == before
    assert peer.events == events and native.active is None


async def test_identity_apply_checks_local_capacity_before_a_collision_query(
    native_link, monkeypatch
):
    peer, _, _, native, _ = native_link
    _, plan = await review(native_link)
    fill(native.storage, 127, peer.files)
    monkeypatch.setattr(
        native.instances, "_collision", lambda _: pytest.fail("Capacity refusal scanned identities")
    )
    events = copy.deepcopy(peer.events)
    result = await native.apply(**apply_request(plan))
    assert result["intent"] is None and result["result"]["status"] == "not_sent"
    assert any("2 required snapshot" in error for error in result["result"]["errors"])
    assert peer.events == events and not native.storage.receipts()


async def test_capture_rechecks_space_before_backup_if_another_writer_fills_it(
    native_link, monkeypatch
):
    peer, _, _, native, target = native_link
    fill(native.storage, 127, peer.files)
    original_path = native.path._path

    @asynccontextmanager
    async def later_full(options):
        async with original_path(options) as session:
            native.storage.save({}, peer.files)
            yield session

    monkeypatch.setattr(native.path, "_path", later_full)
    with pytest.raises(ValueError, match="1 required snapshot"):
        await native.capture(**target, operation_id="capacity-raced-capture")
    assert not peer.events and count(native.storage) == 128 and native.active is None
