"""Real UDP File peers with independently authored stream/record selection."""

import asyncio
import hashlib
import io
import json
import os
import socket
import zipfile

import pytest
from bacpypes3.apdu import AtomicReadFileACK, AtomicReadFileRequest
from bacpypes3.app import Application
from bacpypes3.basetypes import (
    AtomicReadFileACKAccessMethodChoice,
    AtomicReadFileACKAccessMethodRecordAccess,
    AtomicReadFileACKAccessMethodStreamAccess,
    DateTime,
)
from bacpypes3.errors import ExecutionError
from bacpypes3.local.device import ArrayOfObjectIdentifier, DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.object import FileObject
from bms_tool.bacnet_files import BacnetFiles
from bms_tool.connections import Bacnet
from bms_tool.storage import Store


def port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FilePeer(Application):
    def setup(self):
        self.payload = b"Independent UDP file bytes\x00\xff" * 12
        self.records = [b"first\x00record", b"", b"\xfflast-record"]
        self.stream = FileObject(
            objectIdentifier=("file", 31),
            objectName="Authored stream",
            description="Opaque synthetic bytes",
            fileType="application/octet-stream",
            fileSize=len(self.payload),
            modificationDate=DateTime("2026-01-05 12:00:00"),
            archive=False,
            readOnly=True,
            fileAccessMethod="stream-access",
        )
        self.record = FileObject(
            objectIdentifier=("file", 32),
            objectName="Authored records",
            description="Record boundaries matter",
            fileType="application/octet-stream",
            fileSize=sum(map(len, self.records)),
            modificationDate=DateTime("2026-01-05 12:00:00"),
            archive=False,
            readOnly=True,
            fileAccessMethod="record-access",
            recordCount=len(self.records),
        )
        self.add_object(self.stream)
        self.add_object(self.record)
        self.atomic_requests, self.all_requests = [], []
        self.property_requests = []
        self.mutation = None
        self.callback = None
        self.drop = False

    async def do_ReadPropertyRequest(self, request):
        self.all_requests.append(type(request).__name__)
        self.property_requests.append((str(request.propertyIdentifier), request.propertyArrayIndex))
        await super().do_ReadPropertyRequest(request)

    async def do_AtomicReadFileRequest(self, request):
        self.all_requests.append(type(request).__name__)
        self.atomic_requests.append(request)
        if self.drop:
            return
        if request.fileIdentifier == self.stream.objectIdentifier:
            selection = request.accessMethod.streamAccess
            if selection is None:
                raise ExecutionError(errorClass="services", errorCode="invalid-file-access-method")
            start, count = int(selection.fileStartPosition), int(selection.requestedOctetCount)
            block = self.payload[start : start + count]
            response = AtomicReadFileACK(
                context=request,
                endOfFile=start + len(block) >= len(self.payload),
                accessMethod=AtomicReadFileACKAccessMethodChoice(
                    streamAccess=AtomicReadFileACKAccessMethodStreamAccess(
                        fileStartPosition=start, fileData=block
                    )
                ),
            )
        elif request.fileIdentifier == self.record.objectIdentifier:
            selection = request.accessMethod.recordAccess
            if selection is None:
                raise ExecutionError(errorClass="services", errorCode="invalid-file-access-method")
            start, count = int(selection.fileStartRecord), int(selection.requestedRecordCount)
            chosen = self.records[start : start + count]
            response = AtomicReadFileACK(
                context=request,
                endOfFile=start + len(chosen) >= len(self.records),
                accessMethod=AtomicReadFileACKAccessMethodChoice(
                    recordAccess=AtomicReadFileACKAccessMethodRecordAccess(
                        fileStartRecord=start,
                        returnedRecordCount=len(chosen),
                        fileRecordData=chosen,
                    )
                ),
            )
        else:
            raise ExecutionError(errorClass="object", errorCode="unknown-object")
        if self.mutation:
            self.mutation(response)
        await self.response(response)
        if self.callback:
            self.callback()

    async def do_WritePropertyRequest(self, request):
        raise AssertionError("File reader must never issue WriteProperty")

    async def do_AtomicWriteFileRequest(self, request):
        raise AssertionError("File reader must never issue AtomicWriteFile")

    async def do_ReinitializeDeviceRequest(self, request):
        raise AssertionError("File reader must never start a backup/reinitialize session")


@pytest.fixture
async def link(tmp_path):
    remote = port()
    server = FilePeer.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", 4190150),
                objectName="Independent file peer",
                vendorIdentifier=999,
                modelName="Authored File Peer",
                firmwareRevision="test-1.0",
                maxApduLengthAccepted=128,
                configurationFiles=[("file", 31), ("file", 32)],
            ),
            NetworkPortObject(
                f"127.0.0.1:{remote}",
                objectIdentifier=("network-port", 1),
                objectName="Loopback UDP",
            ),
        ]
    )
    server.setup()
    store = Store(tmp_path)
    connector = Bacnet(store)
    await connector.connect(f"127.0.0.1:{port()}")
    service = BacnetFiles(connector, store, timeout=0.1, operation_timeout=3, request_gap=0.01)
    try:
        yield (
            server,
            connector,
            service,
            {"address": f"127.0.0.1:{remote}", "device": "device,4190150"},
        )
    finally:
        connector.close()
        server.close()
        await asyncio.sleep(0.02)


async def inspect(link, index=0):
    server, connector, service, target = link
    report = await service.inspect_config(**target)
    metadata = report["files"][index]
    return (
        server,
        connector,
        service,
        report,
        {
            "inspection_id": report["id"],
            "object_id": metadata["object_id"],
            "metadata_sha256": metadata["metadata_sha256"],
        },
    )


async def test_actual_udp_metadata_and_stream_bytes_are_preserved_as_opaque_capture(link):
    server, connector, service, inspection, request = await inspect(link)
    assert inspection["configuration_files"] == ["file,31", "file,32"]
    assert not server.atomic_requests and inspection["files"][0]["read_only"]
    assert inspection["device_identity"]["firmware-revision"] == "test-1.0"
    result = await service.read_raw_file(**request)
    assert result["complete"] and not result["native_caf"]
    assert result["bytes"] == len(server.payload)
    raw, filename, media = service.export(result["id"])
    assert (
        raw == server.payload and filename.endswith(".bin") and media == "application/octet-stream"
    )
    assert service.capture(result["id"]) == result
    assert len(service.captures()) == 1
    assert all(
        int(page.accessMethod.streamAccess.requestedOctetCount) == 96
        for page in server.atomic_requests
    )
    assert [
        int(page.accessMethod.streamAccess.fileStartPosition) for page in server.atomic_requests
    ] == list(range(0, len(server.payload), 96))
    assert set(server.all_requests) == {"ReadPropertyRequest", "AtomicReadFileRequest"}
    assert (
        not connector.commands
        and not connector.lock.locked()
        and not connector.app.asap.clientTransactions
    )


async def test_record_access_exports_all_boundaries_including_empty_records(link):
    server, _, service, _, request = await inspect(link, 1)
    result = await service.read_raw_file(**request)
    assert result["access_method"] == "record-access" and len(result["record_boundaries"]) == 3
    raw, name, media = service.export(result["id"])
    assert name.endswith("-records.zip") and media == "application/zip"
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert [archive.read(f"records/{index:08d}.bin") for index in range(3)] == server.records
        assert json.loads(archive.read("receipt.json"))["sha256"] == result["sha256"]


async def test_stale_inspection_metadata_and_connection_guards_prevent_file_requests(link):
    server, connector, service, _, request = await inspect(link)
    with pytest.raises(ValueError, match="metadata guard"):
        await service.read_raw_file(**(request | {"metadata_sha256": "0" * 64}))
    connector.config = {"changed": True}
    with pytest.raises(ValueError, match="interface changed"):
        await service.read_raw_file(**request)
    assert not server.atomic_requests and not service.captures()


async def test_file_size_mutation_before_or_after_transfer_refuses_complete_capture(link):
    server, _, service, _, request = await inspect(link)
    server.stream.fileSize += 1
    with pytest.raises(ValueError, match="metadata or original size changed"):
        await service.read_raw_file(**request)
    assert not server.atomic_requests
    server.stream.fileSize -= 1
    server.callback = lambda: setattr(server.stream, "fileSize", len(server.payload) + 1)
    with pytest.raises(ValueError, match="metadata or original size changed"):
        await service.read_raw_file(**request)
    assert server.atomic_requests and not service.captures()


@pytest.mark.parametrize("mode", ["wrong-start", "no-progress", "too-large", "early-eof"])
async def test_malformed_stream_ack_is_rejected_without_saving_partial_bytes(link, mode):
    server, connector, service, _, request = await inspect(link)

    def mutate(reply):
        value = reply.accessMethod.streamAccess
        if mode == "wrong-start":
            value.fileStartPosition += 1
        elif mode == "no-progress":
            value.fileData, reply.endOfFile = b"", False
        elif mode == "too-large":
            value.fileData = b"x" * 97
        else:
            reply.endOfFile = True

    server.mutation = mutate
    with pytest.raises(ValueError, match="AtomicReadFile"):
        await service.read_raw_file(**request)
    assert not service.captures() and not connector.app.asap.clientTransactions


async def test_timeout_and_cancellation_remove_transaction_and_release_connector_lock(link):
    server, connector, service, _, request = await inspect(link)
    server.drop = True
    with pytest.raises(ValueError, match="timed out"):
        await service.read_raw_file(**request)
    assert not connector.lock.locked() and not connector.app.asap.clientTransactions
    pending = asyncio.create_task(service.read_raw_file(**request))
    while len(server.atomic_requests) < 2:
        await asyncio.sleep(0.01)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert (
        not connector.lock.locked()
        and not connector.app.asap.clientTransactions
        and not service.captures()
    )


async def test_waiting_for_connector_lock_has_bounded_operation_deadline(link):
    server, connector, service, target = link
    service.operation_timeout = 0.05
    async with connector.lock:
        with pytest.raises(ValueError, match="timed out"):
            await service.inspect_config(**target)
        assert connector.lock.locked()
    assert not server.all_requests


async def test_configuration_files_membership_and_device_firmware_are_guarded(link):
    server, _, service, _, request = await inspect(link)
    server.device_object.firmwareRevision = "changed"
    with pytest.raises(ValueError, match="identity"):
        await service.read_raw_file(**request)
    assert not server.atomic_requests


async def test_no_configuration_files_is_a_valid_inspection_not_an_invented_program(link):
    server, _, service, target = link
    server.device_object.configurationFiles = []
    server.delete_object(server.stream)
    server.delete_object(server.record)
    result = await service.inspect_config(**target)
    assert result["files"] == [] and result["configuration_files"] == []
    assert result["advertised_files"] == [] and result["discovery_source"] == "object-list"
    assert not server.atomic_requests and not result["native_caf"]


async def test_empty_configuration_files_falls_back_to_actual_advertised_file_objects(link):
    server, _, service, target = link
    server.device_object.configurationFiles = []
    inspection = await service.inspect_config(**target)
    assert inspection["configuration_files"] == []
    assert inspection["discovery_source"] == "object-list"
    assert inspection["advertised_files"] == ["file,31", "file,32"]
    assert inspection["object_list_count"] == 4
    assert len(inspection["object_list_sha256"]) == 64
    assert [index for name, index in server.property_requests if name == "object-list"] == [
        0,
        None,
        0,
        0,
        None,
        0,
    ]
    assert not server.atomic_requests
    row = inspection["files"][0]
    receipt = await service.read_raw_file(
        inspection["id"], row["object_id"], row["metadata_sha256"]
    )
    assert receipt["configuration_files"] == []
    assert receipt["advertised_files"] == ["file,31", "file,32"]
    assert receipt["discovery_source"] == "object-list"
    assert service.export(receipt["id"])[0] == server.payload
    assert set(server.all_requests) == {"ReadPropertyRequest", "AtomicReadFileRequest"}


@pytest.mark.parametrize("stage", ["inspection", "file"])
@pytest.mark.parametrize("method", ["caller", "disconnect"])
async def test_preinvoke_file_request_cancel_or_disconnect_cannot_transmit_later(
    link, monkeypatch, stage, method
):
    server, connector, service, target = link
    service.timeout = 1
    app = connector.app
    request = None
    if stage == "file":
        _, _, _, _, request = await inspect(link)
    original = app.device_info_cache.get_device_info
    entered, release = asyncio.Event(), asyncio.Event()

    async def held(address):
        matching = [
            transaction
            for transaction in app.asap.clientTransactions
            if (
                getattr(getattr(transaction, "segmentAPDU", None), "apduService", None)
                == AtomicReadFileRequest.service_choice
            )
            == (stage == "file")
        ]
        if matching and not entered.is_set():
            entered.set()
            await release.wait()
        return await original(address)

    monkeypatch.setattr(app.device_info_cache, "get_device_info", held)
    operation = asyncio.create_task(
        service.inspect_config(**target)
        if stage == "inspection"
        else service.read_raw_file(**request)
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        [transaction] = app.asap.clientTransactions
        assert transaction.invokeID is None and transaction.segmentAPDU.apduInvokeID is not None
        sent = list(server.all_requests)
        if method == "caller":
            operation.cancel()
        else:
            # Public disconnect serializes behind the held operation lock;
            # lifecycle/physical-interface close must also stop native dispatch.
            connector.close()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert not app.asap.clientTransactions and not app._requests
        assert not connector.lock.locked() and not service.captures()
        release.set()
        await asyncio.sleep(0.1)
        assert server.all_requests == sent and not server.atomic_requests
    finally:
        release.set()
        if not operation.done():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)


@pytest.mark.parametrize("when", ["before", "during"])
async def test_object_list_file_membership_is_guarded_before_and_after_read(link, when):
    server, _, service, target = link
    server.device_object.configurationFiles = []
    inspection = await service.inspect_config(**target)
    row = inspection["files"][0]
    if when == "before":
        server.delete_object(server.record)
    else:

        def remove_other_file():
            if server.record.objectIdentifier in server.objectIdentifier:
                server.delete_object(server.record)

        server.callback = remove_other_file
    with pytest.raises(ValueError, match="advertised File"):
        await service.read_raw_file(inspection["id"], row["object_id"], row["metadata_sha256"])
    assert bool(server.atomic_requests) is (when == "during")
    assert not service.captures()


@pytest.mark.parametrize("mode", ["large", "duplicates", "many-files"])
async def test_object_list_fallback_rejects_unbounded_or_ambiguous_native_inventory(
    link, monkeypatch, mode
):
    server, _, service, target = link
    server.device_object.configurationFiles = []
    identifiers = (
        [("analog-input", index) for index in range(513)]
        if mode == "large"
        else [("file", 31), ("file", 31)]
        if mode == "duplicates"
        else [("file", index) for index in range(17)]
    )
    monkeypatch.setattr(
        type(server.device_object),
        "objectList",
        property(lambda _: ArrayOfObjectIdentifier(identifiers)),
    )
    with pytest.raises(
        ValueError,
        match={"large": "512-object", "duplicates": "duplicate object", "many-files": "16-File"}[
            mode
        ],
    ):
        await service.inspect_config(**target)
    assert not server.atomic_requests and not service.captures()


async def test_object_list_fallback_uses_indexed_reads_when_array_exceeds_apdu_profile(
    link, monkeypatch
):
    server, _, service, target = link
    server.device_object.configurationFiles = []
    identifiers = list(server.objectIdentifier) + [("analog-input", index) for index in range(16)]
    monkeypatch.setattr(
        type(server.device_object),
        "objectList",
        property(lambda _: ArrayOfObjectIdentifier(identifiers)),
    )
    result = await service.inspect_config(**target)
    assert result["advertised_files"] == ["file,31", "file,32"]
    assert result["object_list_count"] == 20
    indices = [index for name, index in server.property_requests if name == "object-list"]
    assert indices == ([0] + list(range(1, 21)) + [0]) * 2
    assert not server.atomic_requests


async def test_object_list_fallback_refuses_native_array_length_different_from_count(
    link, monkeypatch
):
    server, _, service, target = link
    server.device_object.configurationFiles = []
    values = list(server.objectIdentifier)
    calls = 0

    def changed(_):
        nonlocal calls
        calls += 1
        return ArrayOfObjectIdentifier(values[:-1] if calls == 1 else values)

    monkeypatch.setattr(type(server.device_object), "objectList", property(changed))
    with pytest.raises(ValueError, match="array length"):
        await service.inspect_config(**target)
    assert not server.atomic_requests and not service.captures()


@pytest.mark.parametrize("mode", ["wrong-record", "count", "no-progress", "too-large"])
async def test_malformed_record_responses_fail_with_no_capture(link, mode):
    server, connector, service, _, request = await inspect(link, 1)

    def mutate(reply):
        value = reply.accessMethod.recordAccess
        if mode == "wrong-record":
            value.fileStartRecord += 1
        elif mode == "count":
            value.returnedRecordCount += 1
        elif mode == "no-progress":
            value.fileRecordData, value.returnedRecordCount, reply.endOfFile = [], 0, False
        else:
            value.fileRecordData = [b"x" * 97]

    server.mutation = mutate
    with pytest.raises(ValueError, match="AtomicReadFile|File record|timed out"):
        await service.read_raw_file(**request)
    assert not service.captures() and not connector.app.asap.clientTransactions


async def test_configuration_file_membership_is_not_guessed_or_replaced(link):
    server, _, service, _, request = await inspect(link)
    server.device_object.configurationFiles = [("file", 32)]
    with pytest.raises(ValueError, match="identity, File metadata"):
        await service.read_raw_file(**request)
    assert not server.atomic_requests


async def test_oversized_and_duplicate_config_lists_refuse_before_atomic_reads(link):
    server, _, service, target = link
    server.device_object.configurationFiles = [("file", 31)] * 17
    with pytest.raises(ValueError, match="16-file"):
        await service.inspect_config(**target)
    server.device_object.configurationFiles = [("file", 31)] * 2
    with pytest.raises(ValueError, match="duplicate"):
        await service.inspect_config(**target)
    assert not server.atomic_requests


async def test_saved_capture_preserves_source_bytes_and_refuses_overwrite_corruption_and_symlinks(
    link,
):
    _, _, service, _, request = await inspect(link)
    report = await service.read_raw_file(**request)
    path = service.directory / (report["id"] + ".capture")
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        service._save(report, b"same id cannot overwrite")
    assert path.read_bytes() == original
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        receipt, data, checksum = (
            archive.read("receipt.json"),
            archive.read("data.bin"),
            archive.comment,
        )
    changed = io.BytesIO()
    with zipfile.ZipFile(changed, "w") as archive:
        archive.comment = checksum
        archive.writestr("receipt.json", receipt.replace(b'"complete":true', b'"complete":false'))
        archive.writestr("data.bin", data)
    path.write_bytes(changed.getvalue())
    with pytest.raises(ValueError, match="Invalid saved"):
        service.capture(report["id"])
    path.unlink()
    target = service.directory / "retained-original"
    target.write_bytes(original)
    path.symlink_to(target)
    with pytest.raises(ValueError, match="regular file"):
        service.capture(report["id"])
    assert target.read_bytes() == original


async def test_record_boundary_tampering_is_rejected_even_with_recomputed_container_checksum(link):
    _, _, service, _, request = await inspect(link, 1)
    report = await service.read_raw_file(**request)
    path = service.directory / (report["id"] + ".capture")
    with zipfile.ZipFile(path) as archive:
        receipt, data = json.loads(archive.read("receipt.json")), archive.read("data.bin")
    receipt["record_boundaries"][0]["offset"] = -1
    raw = json.dumps(receipt).encode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.comment = hashlib.sha256(raw).hexdigest().encode()
        archive.writestr("receipt.json", raw)
        archive.writestr("data.bin", data)
    with pytest.raises(ValueError, match="record boundaries"):
        service.export(report["id"])


async def test_capture_capacity_never_removes_existing_evidence(link, monkeypatch):
    _, _, service, _, request = await inspect(link)
    result = await service.read_raw_file(**request)
    original, _, _ = service.export(result["id"])
    monkeypatch.setattr("bms_tool.bacnet_files.MAX_CAPTURES", 1)
    with pytest.raises(ValueError, match="capacity"):
        await service.read_raw_file(**request)
    assert service.export(result["id"])[0] == original


async def test_nonregular_capture_lock_refuses_storage_without_touching_target(link):
    server, _, service, _, request = await inspect(link)
    lock = service.directory / ".capture.lock"
    os.mkfifo(lock)
    with pytest.raises(ValueError, match="regular file"):
        await service.read_raw_file(**request)
    assert not service.captures() and server.atomic_requests
