"""Independent UDP NAE backup peer, including Files absent outside backup mode."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from bacpypes3.apdu import AtomicReadFileACK, ReadPropertyACK, SimpleAckPDU
from bacpypes3.app import Application
from bacpypes3.basetypes import (
    AtomicReadFileACKAccessMethodChoice,
    AtomicReadFileACKAccessMethodStreamAccess,
    BackupState,
    ServicesSupported,
)
from bacpypes3.constructeddata import Any
from bacpypes3.errors import ExecutionError
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.object import DeviceObject as DeviceSchema
from bacpypes3.object import FileObject as FileSchema
from bacpypes3.primitivedata import ObjectIdentifier, Unsigned
from bms_tool.connections import Bacnet
from bms_tool.nae_configuration import NaeConfigurationCapture
from bms_tool.storage import Store

from .test_native_applications import port


class NaePeer(Application):
    def setup(self):
        self.state, self.revision = 0, 42
        self.mode, self.events = "normal", []
        self.files = {0: b"", 7: b"authored opaque configuration" * 40, 42: b"other retained bytes"}
        services = [0] * 41
        for index in (6, 7, 12, 20):
            services[index] = 1
        self.properties = {
            "object-identifier": ObjectIdentifier("device,321"),
            "object-name": "Authored NAE",
            "model-name": "MS-NAE-AUTHORED",
            "vendor-identifier": 5,
            "firmware-revision": "authored-1",
            "database-revision": 42,
            "max-apdu-length-accepted": 480,
            "protocol-services-supported": ServicesSupported(services),
            "backup-preparation-time": 0,
            "backup-failure-timeout": 120,
            "system-status": 0,
        }

    async def do_ReadPropertyRequest(self, request):
        prop, obj = str(request.propertyIdentifier), request.objectIdentifier
        self.events.append(("property", str(obj), prop))
        if int(obj[0]) == 8:
            schema = DeviceSchema
            if prop == "backup-and-restore-state":
                value = BackupState(self.state)
            elif prop == "configuration-files":
                values = (
                    [ObjectIdentifier((10, key)) for key in self.files] if self.state == 2 else []
                )
                if self.mode == "duplicate-array":
                    values = [ObjectIdentifier((10, 7))] * 2
                index = request.propertyArrayIndex
                value = Unsigned(len(values)) if index == 0 else values[int(index) - 1]
            elif prop == "database-revision":
                value = Unsigned(self.revision)
            else:
                if prop not in self.properties:
                    raise ExecutionError(errorClass="property", errorCode="unknown-property")
                value = schema.get_property_type(prop)(self.properties[prop])
        else:
            assert int(obj[0]) == 10 and self.state == 2
            schema = FileSchema
            values = {
                "object-identifier": obj,
                "object-name": "untrusted/../name",
                "file-type": "CONFIGURATION",
                "file-size": len(self.files[obj[1]]),
                "file-access-method": "stream-access",
            }
            if prop == "file-size" and self.mode == "unknown-size":
                raise ExecutionError(errorClass="services", errorCode="unknown-file-size")
            value = schema.get_property_type(prop)(values[prop])
        await self.response(
            ReadPropertyACK(
                context=request,
                objectIdentifier=obj,
                propertyIdentifier=request.propertyIdentifier,
                propertyArrayIndex=request.propertyArrayIndex,
                propertyValue=Any(value),
            )
        )

    async def do_ReinitializeDeviceRequest(self, request):
        state = str(request.reinitializedStateOfDevice)
        assert state in ("start-backup", "end-backup"), "No restore/restart command admitted"
        self.events.append(("state", state))
        if state == "start-backup":
            if self.mode == "reject-start":
                raise ExecutionError(errorClass="security", errorCode="password-failure")
            self.state = 2
            if self.mode == "drop-start":
                return
        else:
            self.state = 0
            if self.mode == "drop-end":
                return
        await self.response(SimpleAckPDU(context=request))

    async def do_AtomicReadFileRequest(self, request):
        assert self.state == 2
        obj = request.fileIdentifier
        assert int(obj[0]) == 10 and obj[1] in self.files
        access = request.accessMethod.streamAccess
        start, size = int(access.fileStartPosition), int(access.requestedOctetCount)
        self.events.append(("file", obj[1], start))
        if self.mode == "drop-file":
            return
        data = self.files[obj[1]][start : start + size]
        await self.response(
            AtomicReadFileACK(
                context=request,
                endOfFile=start + len(data) == len(self.files[obj[1]]),
                accessMethod=AtomicReadFileACKAccessMethodChoice(
                    streamAccess=AtomicReadFileACKAccessMethodStreamAccess(
                        fileStartPosition=start + (1 if self.mode == "wrong-offset" else 0),
                        fileData=data,
                    )
                ),
            )
        )

    async def do_AtomicWriteFileRequest(self, request):
        raise AssertionError("Configuration capture must not write File contents")


@pytest.fixture
async def link(tmp_path):
    remote = port()
    peer = NaePeer.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", 321), objectName="Authored NAE", vendorIdentifier=5
            ),
            NetworkPortObject(
                f"127.0.0.1:{remote}",
                objectIdentifier=("network-port", 1),
                objectName="Isolated UDP",
            ),
        ]
    )
    peer.setup()
    store = Store(tmp_path)
    bacnet = Bacnet(store)
    await bacnet.connect(f"127.0.0.1:{port(exclude={remote})}")
    service = NaeConfigurationCapture(
        bacnet, store, tmp_path / "nae", timeout=0.2, poll_seconds=0.01, operation_seconds=5
    )
    service.path.request_gap = 0
    service.wire.gap = 0
    target = {"address": f"127.0.0.1:{remote}", "device": "device,321"}
    try:
        yield peer, bacnet, service, target
    finally:
        bacnet.close()
        peer.close()
        await asyncio.sleep(0.02)


async def apply(service, review):
    return await service.capture(
        token=review["token"], review_sha256=review["review_sha256"], allow_backup_mode=True
    )


async def test_native_backup_acquires_only_session_advertised_files_and_closes(link):
    peer, bacnet, service, target = link
    review = await service.prepare(**target)
    assert not any(e[0] == "state" for e in peer.events)
    assert review["effects"]["engine_control_may_pause"] is True
    result = await apply(service, review)
    assert result["status"] == "capture_verified" and peer.state == 0
    assert [e for e in peer.events if e[0] == "state"] == [
        ("state", "start-backup"),
        ("state", "end-backup"),
    ]
    assert {row["object-identifier"] for row in result["files"]} == {"file,0", "file,7", "file,42"}
    for key, data in peer.files.items():
        assert (service.directory / result["operation_id"] / f"{key}.bin").read_bytes() == data
    assert not list(service.directory.rglob("name"))
    assert not bacnet.app.asap.clientTransactions and not bacnet.lock.locked()
    with pytest.raises(ValueError, match="consumed"):
        await apply(service, review)


async def test_stale_native_database_and_busy_state_stop_before_backup(link):
    peer, _, service, target = link
    review = await service.prepare(**target)
    peer.revision += 1
    with pytest.raises(ValueError, match="changed after review"):
        await apply(service, review)
    assert not any(e[0] == "state" for e in peer.events)
    peer.state = 2
    with pytest.raises(ValueError, match="already"):
        await service.prepare(**target)


async def test_timing_change_without_database_revision_change_invalidates_review(link):
    peer, _, service, target = link
    review = await service.prepare(**target)
    peer.properties["backup-failure-timeout"] = 90
    with pytest.raises(ValueError, match="timing.*changed after review"):
        await apply(service, review)
    assert not any(e[0] == "state" for e in peer.events)


async def test_capture_transport_refuses_restore_or_restart_before_dispatch(link):
    peer, _, service, _ = link
    for state in ("start-restore", "end-restore", "warm-start", "cold-start"):
        with pytest.raises(ValueError, match="does not admit"):
            await service.wire.state({}, state)
    assert not peer.events


async def test_insufficient_storage_refuses_backup_before_any_field_request(link, monkeypatch):
    peer, _, service, target = link
    monkeypatch.setattr(
        "bms_tool.nae_configuration.shutil.disk_usage", lambda _: SimpleNamespace(free=0)
    )
    with pytest.raises(ValueError, match="Insufficient private storage"):
        await service.prepare(**target)
    assert not peer.events


@pytest.mark.parametrize("mode", ["duplicate-array", "wrong-offset", "drop-file"])
async def test_failed_capture_ends_only_its_acknowledged_backup(link, mode):
    peer, _, service, target = link
    review = await service.prepare(**target)
    peer.mode = mode
    with pytest.raises((ValueError, TimeoutError)):
        await apply(service, review)
    assert peer.state == 0
    row = json.loads((service.directory / (review["operation_id"] + ".json")).read_text())
    assert row["status"] == "capture_failed_closed"
    assert [e for e in peer.events if e[0] == "state"] == [
        ("state", "start-backup"),
        ("state", "end-backup"),
    ]


@pytest.mark.parametrize("mode", ["drop-start", "drop-end"])
async def test_lost_lifecycle_reply_blocks_repetition_and_reconciles_without_sending(link, mode):
    peer, _, service, target = link
    review = await service.prepare(**target)
    peer.mode = mode
    with pytest.raises((ValueError, TimeoutError)):
        await apply(service, review)
    before = [e for e in peer.events if e[0] == "state"]
    assert before.count(("state", "start-backup")) == 1
    assert before.count(("state", "end-backup")) == (mode == "drop-end")
    with pytest.raises(ValueError, match="unresolved"):
        await service.prepare(**target)
    peer.state = 0  # independently model device timeout/recovery
    result = await service.reconcile(review["operation_id"])
    assert not result["capture_verified"] and result["read_only"]
    assert [e for e in peer.events if e[0] == "state"] == before
    await service.prepare(**target)


async def test_native_password_refusal_is_not_retried_or_guessed(link):
    peer, _, service, target = link
    review = await service.prepare(**target)
    peer.mode = "reject-start"
    with pytest.raises(ValueError, match="rejected"):
        await service.capture(
            token=review["token"],
            review_sha256=review["review_sha256"],
            allow_backup_mode=True,
            password="authored-secret",
        )
    assert [e for e in peer.events if e[0] == "state"] == [("state", "start-backup")]
    text = (service.directory / (review["operation_id"] + ".json")).read_text()
    assert "authored-secret" not in text and json.loads(text)["status"] == "start_rejected"


async def test_native_unknown_size_is_bounded_by_eof_and_retains_original_bytes(link):
    peer, _, service, target = link
    peer.mode = "unknown-size"
    result = await apply(service, await service.prepare(**target))
    assert result["status"] == "capture_verified"
    assert all(row["file-size"] is None for row in result["files"])
    assert sum(row["bytes"] for row in result["files"]) == sum(map(len, peer.files.values()))


async def test_local_journal_failure_does_not_prevent_owned_backup_closure(link, monkeypatch):
    peer, _, service, target = link
    original = service._write

    def write(record):
        if record["status"] in ("end_intent", "end_sent"):
            raise OSError("Authored full-disk condition")
        original(record)

    monkeypatch.setattr(service, "_write", write)
    result = await apply(service, await service.prepare(**target))
    assert peer.state == 0 and result["status"] == "capture_verified"
    assert result["journal_error_type"] == "OSError"
    assert [e for e in peer.events if e[0] == "state"] == [
        ("state", "start-backup"),
        ("state", "end-backup"),
    ]


async def test_cancellation_retires_native_transaction_and_closes_acknowledged_backup(link):
    peer, bacnet, service, target = link
    review = await service.prepare(**target)
    peer.mode = "drop-file"
    task = asyncio.create_task(apply(service, review))
    async with asyncio.timeout(2):
        while not any(e[0] == "file" for e in peer.events):
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert peer.state == 0 and not bacnet.app.asap.clientTransactions
    row = json.loads((service.directory / (review["operation_id"] + ".json")).read_text())
    assert row["status"] == "capture_failed_closed"
