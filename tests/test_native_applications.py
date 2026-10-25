"""Connected commissioning against an authored UDP controller; no field network."""

import asyncio
import copy
import socket

import pytest
from bacpypes3.apdu import (
    AtomicReadFileACK,
    AtomicWriteFileACK,
    ConfirmedPrivateTransferACK,
    SimpleAckPDU,
)
from bacpypes3.app import Application
from bacpypes3.basetypes import (
    AtomicReadFileACKAccessMethodChoice,
    AtomicReadFileACKAccessMethodStreamAccess,
)
from bacpypes3.constructeddata import Any
from bacpypes3.errors import ExecutionError
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    ClosingTag,
    ContextTag,
    Enumerated,
    ObjectIdentifier,
    OctetString,
    OpeningTag,
    Real,
    TagList,
    Unsigned,
)
from bms_tool.application_store import ApplicationStore
from bms_tool.connections import Bacnet
from bms_tool.device_instance import DeviceInstances
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_applications import NativeApplications
from bms_tool.storage import Store

from .test_device_instance import read_reply
from .test_moi_parameters import parameters_source


def port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class NativePeer(Application):
    def setup(self):
        self.instance = 5136
        a, s, d = parameters_source()
        self.files = {3: a, 11: s, 12: d}
        self.metadata = {
            "object-name": "Authored controller",
            "vendor-identifier": 5,
            "model-name": "UNLISTED-MODEL",
            "firmware-revision": "authored-1",
            "application-software-version": "authored-application",
        }
        self.events = []
        self.mode = "normal"
        self.restore = False
        self.stage = bytearray()
        self.dispatch = None

    async def do_ReadPropertyRequest(self, request):
        prop = str(request.propertyIdentifier)
        if prop == "max-apdu-length-accepted":
            values = {prop: 480}
        elif request.objectIdentifier == ObjectIdentifier(("file", 3)):
            from bacpypes3.apdu import ReadPropertyACK

            await self.response(
                ReadPropertyACK(
                    context=request,
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=request.propertyIdentifier,
                    propertyValue=Any(CharacterString(".moi")),
                )
            )
            return
        else:
            if prop not in self.metadata and prop != "object-identifier":
                raise ExecutionError(errorClass="property", errorCode="unknown-property")
            values = self.metadata
        await self.response(read_reply(request, self.instance, values))

    async def do_ConfirmedPrivateTransferRequest(self, request):
        assert request.vendorID == 5 and request.serviceNumber == 54
        tags = list(request.serviceParameters.tagList)
        assert bytes(tags[1].tag_data) == bytes.fromhex("023fffff")
        assert bytes(tags[2].tag_data) == bytes.fromhex("02a6")
        args = [
            CharacterString(self.metadata["object-name"]),
            CharacterString("Authored variable-model peer"),
            Enumerated(1),
            CharacterString("1.0"),
            CharacterString("1.0"),
            CharacterString("1.0"),
            CharacterString("Authored application"),
            Enumerated(1),
            Enumerated(1),
            CharacterString(""),
            ObjectIdentifier((8, self.instance)),
            Real(0),
            Unsigned(0),
            Unsigned(0),
            Real(0),
            Enumerated(0),
            CharacterString(""),
            OctetString(b""),
            Boolean(False),
            Unsigned(0),
            Unsigned(0),
        ]
        reply_tags = [
            ContextTag(0, bytes.fromhex("023fffff")),
            ContextTag(1, bytes.fromhex("02a6")),
            OpeningTag(2),
        ]
        for value in args:
            reply_tags.extend(value.encode())
        reply_tags.append(ClosingTag(2))
        await self.response(
            ConfirmedPrivateTransferACK(
                context=request, vendorID=5, serviceNumber=54, resultBlock=Any(TagList(reply_tags))
            )
        )

    async def do_ReinitializeDeviceRequest(self, request):
        state = str(request.reinitializedStateOfDevice)
        self.events.append(("state", state))
        if state == "start-backup":
            assert str(request.password) == "authored-backup"
        elif state == "start-restore":
            assert str(request.password) == "authored-restore"
            self.restore = True
            self.stage = bytearray()
            if self.mode == "drop-start":
                return
        elif state == "end-restore":
            assert self.restore
            self.files[3] = bytes(self.stage)
            self.instance = MoiIdentity(self.files[3]).instance
            self.restore = False
            if self.mode == "mismatch":
                self.files[3] = parameters_source(model="OTHER")[0]
            if self.mode == "drop-end":
                return
        else:
            assert state == "end-backup"
        await self.response(SimpleAckPDU(context=request))

    async def do_AtomicReadFileRequest(self, request):
        assert request.fileIdentifier[0] == 10
        file_id = int(request.fileIdentifier[1])
        assert file_id in (3, 11, 12)
        access = request.accessMethod.streamAccess
        start, count = int(access.fileStartPosition), int(access.requestedOctetCount)
        self.events.append(("read", file_id, start))
        data = self.files[file_id][start : start + count]
        await self.response(
            AtomicReadFileACK(
                context=request,
                endOfFile=start + len(data) >= len(self.files[file_id]),
                accessMethod=AtomicReadFileACKAccessMethodChoice(
                    streamAccess=AtomicReadFileACKAccessMethodStreamAccess(
                        fileStartPosition=start, fileData=data
                    )
                ),
            )
        )

    async def do_AtomicWriteFileRequest(self, request):
        assert self.restore and request.fileIdentifier == ObjectIdentifier(("file", 3))
        a = request.accessMethod.streamAccess
        pos = int(a.fileStartPosition)
        assert pos == len(self.stage)
        if self.dispatch:
            self.dispatch()
        self.stage.extend(bytes(a.fileData))
        self.events.append(("write", 3, pos, len(a.fileData)))
        if self.mode == "drop-block":
            return
        await self.response(AtomicWriteFileACK(context=request, fileStartPosition=pos))

    async def do_WritePropertyRequest(self, request):
        raise AssertionError(
            "Native application adapter must not fall back to standard property writes."
        )


@pytest.fixture
async def native_link(tmp_path):
    remote = port()
    peer = NativePeer.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", 5136),
                objectName="Authored controller",
                vendorIdentifier=5,
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
    await bacnet.connect(f"127.0.0.1:{port()}")
    instances = DeviceInstances(bacnet, store)
    instances.path.request_gap = 0
    instances.path.timeout = 0.1

    async def collision(options):
        return {
            "devices": [],
            "scope": "Authored isolated scope",
            "limitation": "Test allocation",
            "checked_at": "test",
        }

    instances._collision = collision
    service = NativeApplications(bacnet, store, instances, request_timeout=0.1, gap=0)
    service.credentials.set("authored-backup", "authored-restore")
    target = {"address": f"127.0.0.1:{remote}", "device": "device,5136"}
    try:
        yield peer, bacnet, store, service, target
    finally:
        await service.close()
        await instances.close()
        bacnet.close()
        peer.close()
        await asyncio.sleep(0.02)


async def review(link):
    peer, bacnet, store, service, target = link
    capture = await service.capture(**target, operation_id="authored-capture")
    plan = await service.preview(
        **target, operation_id="authored-preview", capture_id=capture["id"], new_instance=5336
    )
    return capture, plan


def apply_request(plan):
    return {
        "operation_id": "authored-apply",
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        "allocation_confirmed": True,
        "application_transfer_confirmed": True,
    }


async def test_capture_review_compile_transfer_and_verify_all_use_owned_udp(native_link):
    peer, bacnet, store, service, target = native_link
    original = copy.deepcopy(peer.files)
    capture, plan = await review(native_link)
    assert capture["instance_edit_supported"] and not any(e[0] == "write" for e in peer.events)
    assert plan["can_apply"] and not plan["vendor_runtime_required"]
    dispatched = []

    def before_actual_write():
        rows = service.storage.receipts()
        assert len(rows) == 1 and rows[0]["pending"]
        assert any(e["stage"] == "dispatch-application-block" for e in rows[0]["events"])
        dispatched.append(True)

    peer.dispatch = before_actual_write
    result = await service.apply(**apply_request(plan))
    assert result["result"]["status"] == "verified", result
    assert not result["pending"] and result["result"]["protocol_accepted"] and dispatched
    assert peer.instance == 5336 and MoiIdentity(peer.files[3]).instance == 5336
    e = MoiIdentity(peer.files[3])
    assert e.reader.scalar(e.root, 901) == 70000 and e.reader.scalar(e.root, 900) == 3.5
    assert peer.files[11] == original[11] and peer.files[12] == original[12]
    kept, raw = service.storage.load(result["intent"]["backup_id"])
    assert raw == original and kept["device"] == "device,5136"
    assert not bacnet.app.asap.clientTransactions and not bacnet.lock.locked()
    with pytest.raises(ValueError, match="consumed"):
        await service.apply(**apply_request(plan))


@pytest.mark.parametrize("mode", ["drop-start", "drop-block", "drop-end"])
async def test_any_lost_mutation_ack_stops_once_and_survives_restart(native_link, mode):
    peer, bacnet, store, service, target = native_link
    _, plan = await review(native_link)
    peer.mode = mode
    result = await service.apply(**apply_request(plan))
    assert result["pending"] and result["result"]["status"] == "unknown"
    assert result["result"]["may_have_applied"]
    assert len([e for e in peer.events if e == ("state", "start-restore")]) == 1
    writes = [e for e in peer.events if e[0] == "write"]
    if mode == "drop-start":
        assert not writes
    if mode == "drop-block":
        assert len(writes) == 1 and ("state", "end-restore") not in peer.events
    restarted = ApplicationStore(store)
    assert restarted.receipt(result["intent"]["id"])["pending"]
    with pytest.raises(ValueError, match="unresolved"):
        restarted.available(result["intent"]["target"])
    assert not bacnet.app.asap.clientTransactions and not bacnet.lock.locked()


async def test_source_change_after_review_never_starts_a_restore(native_link):
    peer, _, _, service, _ = native_link
    _, plan = await review(native_link)
    peer.files[3] = parameters_source(model="Changed after review")[0]
    result = await service.apply(**apply_request(plan))
    assert result["intent"] is None and result["result"]["status"] == "not_sent"
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


async def test_cancelled_or_changed_interface_plan_cannot_dispatch(native_link):
    peer, bacnet, _, service, _ = native_link
    _, plan = await review(native_link)
    service.cancel("authored-preview")
    with pytest.raises(ValueError, match="consumed"):
        await service.apply(**apply_request(plan))
    assert not any(e[0] == "write" for e in peer.events)


async def test_backup_checksums_and_export_are_retained_privately(native_link):
    _, _, store, service, _ = native_link
    capture, _ = await review(native_link)
    path = service.storage.directory / capture["id"] / "file-3.bin"
    assert path.stat().st_mode & 0o777 == 0o600
    assert (store.directory / "native-application-credentials.json").stat().st_mode & 0o777 == 0o600
    assert service.storage.export(capture["id"]).startswith(b"PK")
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        service.storage.load(capture["id"])


async def test_readback_resolves_lost_commit_ack_without_another_restore(native_link):
    peer, _, _, service, _ = native_link
    _, plan = await review(native_link)
    peer.mode = "drop-end"
    result = await service.apply(**apply_request(plan))
    assert result["pending"] and peer.instance == 5336
    mutations = [
        e for e in peer.events if e[0] == "write" or (e[0] == "state" and "restore" in e[1])
    ]
    peer.mode = "normal"
    observed = await service.reconcile(
        operation_id="receipt-readback", receipt_id=result["intent"]["id"]
    )
    assert not observed["pending"]
    assert observed["events"][-1]["stage"] == "readback"
    assert observed["events"][-1]["detail"]["status"] == "verified"
    assert mutations == [
        e for e in peer.events if e[0] == "write" or (e[0] == "state" and "restore" in e[1])
    ]


async def test_journal_failure_before_dispatch_never_enters_restore(native_link, monkeypatch):
    peer, _, _, service, _ = native_link
    _, plan = await review(native_link)

    def unavailable(*args, **kwargs):
        raise OSError("Authored disk failure")

    monkeypatch.setattr(service.storage, "event", unavailable)
    result = await service.apply(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"]
    assert not any(e == ("state", "start-restore") or e[0] == "write" for e in peer.events)


async def test_new_collision_during_apply_cannot_dispatch(native_link):
    peer, _, _, service, _ = native_link
    _, plan = await review(native_link)

    async def occupied(options):
        return {"devices": [{"device": "device,5336"}]}

    service.instances._collision = occupied
    result = await service.apply(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"]
    assert not any(e == ("state", "start-restore") or e[0] == "write" for e in peer.events)


async def test_review_expiry_after_backup_prevents_dispatch(native_link, monkeypatch):
    peer, _, _, service, _ = native_link
    _, plan = await review(native_link)
    retained = service.plans[plan["token"]]
    original = service.capture_session

    async def expires(*args, **kwargs):
        result = await original(*args, **kwargs)
        retained["expires"] = 0
        return result

    monkeypatch.setattr(service, "capture_session", expires)
    result = await service.apply(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"]
    assert not any(e == ("state", "start-restore") or e[0] == "write" for e in peer.events)


async def test_another_instance_session_cannot_use_native_pending_receipt(native_link):
    peer, _, _, service, _ = native_link
    _, plan = await review(native_link)
    peer.mode = "drop-block"
    result = await service.apply(**apply_request(plan))
    assert result["pending"]
    with pytest.raises(ValueError, match="unresolved"):
        service.storage.available(result["intent"]["target"])


@pytest.mark.parametrize("kind", ["unknown-format", "other-model"])
async def test_unsupported_application_retains_original_backup_without_admitting_a_transfer(
    native_link, kind
):
    peer, _, _, service, target = native_link
    peer.files[3] = (
        b"An unrecognized application"
        if kind == "unknown-format"
        else parameters_source(model="DIFFERENT")[0]
    )
    capture = await service.capture(**target, operation_id="unsupported-capture")
    assert not capture["instance_edit_supported"] and capture["compiler_error"]
    assert service.storage.load(capture["id"])[1] == peer.files
    with pytest.raises(ValueError):
        await service.preview(
            **target,
            operation_id="unsupported-preview",
            capture_id=capture["id"],
            new_instance=5336,
        )
    assert not any(e == ("state", "start-restore") or e[0] == "write" for e in peer.events)
