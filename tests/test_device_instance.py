"""Actual loopback UDP commissioning, including independent NPDU router peers."""

import asyncio
import copy
import sqlite3
import struct
import time

import pytest
from bacpypes3.apdu import (
    APDU,
    APCISequence,
    ConfirmedRequestPDU,
    Error,
    IAmRequest,
    ReadPropertyACK,
    ReadPropertyRequest,
    SimpleAckPDU,
    WhoIsRequest,
    WritePropertyRequest,
)
from bacpypes3.app import Application
from bacpypes3.constructeddata import Any
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import PDU, Address
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned
from bms_tool.bacnet_read import close_application
from bms_tool.connections import Bacnet
from bms_tool.device_instance import DeviceInstances, InstanceApply, InstancePreview, sha
from bms_tool.storage import Store

from .test_bacnet_events import assert_retired
from .test_connections import free_udp

OLD, NEW = 5136, 15136
METADATA = {
    "object-name": "Authored controller",
    "vendor-identifier": 5,
    "model-name": "Authored model",
    "firmware-revision": "1.0",
    "application-software-version": "1.1",
}


def options(address, **updates):
    return {
        "operation_id": "instance-" + str(time.monotonic_ns()),
        "address": address,
        "device": f"device,{OLD}",
        "new_instance": NEW,
        **updates,
    }


def apply_request(plan, **updates):
    return {
        "operation_id": "apply-" + str(time.monotonic_ns()),
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        "allocation_confirmed": True,
        **updates,
    }


def read_reply(request, instance, metadata):
    device = ObjectIdentifier(("device", instance))
    if request.objectIdentifier not in (device, ObjectIdentifier(("device", 4194303))):
        return Error(
            service_choice=12, errorClass="object", errorCode="unknownObject", context=request
        )
    prop = str(request.propertyIdentifier)
    value = device if prop == "object-identifier" else metadata[prop]
    value = (
        value
        if isinstance(value, ObjectIdentifier)
        else Unsigned(value)
        if isinstance(value, int)
        else CharacterString(value)
    )
    return ReadPropertyACK(
        objectIdentifier=device,
        propertyIdentifier=request.propertyIdentifier,
        propertyValue=Any(value),
        context=request,
    )


class InstancePeer(Application):
    def setup(self, mode="accept"):
        self.instance, self.mode, self.metadata = OLD, mode, copy.deepcopy(METADATA)
        self.writes, self.wire_writes, self.reads = [], [], []
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        original = self.asap.confirmation

        async def wire(pdu):
            packet = APDU.decode(PDU(bytes(pdu.pduData)))
            if isinstance(packet, ConfirmedRequestPDU) and packet.apduService == 15:
                self.wire_writes.append(bytes(pdu.pduData))
            await original(pdu)

        self.asap.confirmation = wire

    async def do_ReadPropertyRequest(self, request):
        self.reads.append((str(request.objectIdentifier), str(request.propertyIdentifier)))
        await self.response(read_reply(request, self.instance, self.metadata))

    async def do_WritePropertyRequest(self, request):
        self.writes.append(request)
        self.entered.set()
        assert request.objectIdentifier == ObjectIdentifier(("device", OLD))
        assert str(request.propertyIdentifier) == "object-identifier"
        assert request.propertyArrayIndex is None and request.priority is None
        new = request.propertyValue.cast_out(ObjectIdentifier)
        assert new == ObjectIdentifier(("device", NEW))
        if self.mode == "hold":
            await self.release.wait()
            return
        if self.mode == "reject":
            await self.response(
                Error(
                    service_choice=15,
                    errorClass="property",
                    errorCode="writeAccessDenied",
                    context=request,
                )
            )
            return
        if self.mode not in ("unchanged", "wrong-service"):
            self.instance = new[1]
        if self.mode == "lost-ack":
            return
        reply = SimpleAckPDU(context=request)
        if self.mode == "wrong-service":
            reply.apduService = 12
        await self.response(reply)


def instance_peer(port, mode="accept"):
    peer = InstancePeer.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", OLD),
                objectName="Authored peer",
                vendorIdentifier=5,
                maxApduLengthAccepted=1476,
                segmentationSupported="no-segmentation",
            ),
            NetworkPortObject(
                f"127.0.0.1:{port}", objectIdentifier=("network-port", 1), objectName="Loopback"
            ),
        ]
    )
    peer.setup(mode)
    return peer


@pytest.fixture
async def link(tmp_path):
    port = free_udp()
    peer = instance_peer(port)
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = DeviceInstances(client, client.store, timeout=0.1, operation_timeout=5, request_gap=0)
    try:
        yield peer, client, service, f"127.0.0.1:{port}"
    finally:
        await service.close()
        client.close()
        peer.release.set()
        close_application(peer)
        await asyncio.sleep(0)


async def clear_collision(_options):
    return {
        "scope": "Authored empty collision window",
        "devices": [],
        "checked_at": "authored",
        "evidence_sha256": "a" * 64,
        "limitation": "Offline devices remain unknown.",
    }


@pytest.mark.asyncio
async def test_direct_udp_review_write_once_readback_and_durable_receipt(link):
    peer, client, service, address = link
    # Exercise the actual bounded local-subnet Who-Is implementation too.
    plan = await service.preview(**options(address))
    assert plan["can_apply"] and plan["identity"]["device"] == f"device,{OLD}"
    assert not peer.wire_writes and not peer.writes
    assert plan["review_sha256"] == sha(
        {k: v for k, v in plan.items() if k not in ("token", "review_sha256")}
    )
    result = await service.apply(**apply_request(plan))
    assert result["status"] == "verified", result
    assert result["protocol_accepted"] and result["readback"]["status"] == "verified_new"
    assert peer.instance == NEW and len(peer.wire_writes) == len(peer.writes) == 1
    assert client.config["instance"] == 4190001
    loaded = DeviceInstances(client, client.store).journal.receipt(result["id"])
    assert loaded["attempt"] == result and loaded["intent"]["may_have_applied"]
    assert not service.status()["receipts"][0]["pending"]
    with pytest.raises(ValueError, match="consumed"):
        await service.apply(**apply_request(plan))
    assert len(peer.wire_writes) == 1
    assert_retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode, expected, accepted, pending",
    [
        ("reject", "rejected", False, False),
        ("lost-ack", "verified", False, False),
        ("wrong-service", "unknown", False, True),
        ("unchanged", "unknown", True, True),
    ],
)
async def test_protocol_rejection_lost_ack_wrong_ack_and_unchanged_readback(
    link, monkeypatch, mode, expected, accepted, pending
):
    peer, client, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    peer.mode = mode
    result = await service.apply(**apply_request(await service.preview(**options(address))))
    assert result["status"] == expected, result
    assert result["protocol_accepted"] is accepted
    assert service.status()["receipts"][0]["pending"] is pending
    assert len(peer.wire_writes) == 1
    assert_retired(client)
    if pending:
        # A restart does not erase uncertainty or automatically retry a write.
        restarted = DeviceInstances(client, client.store, timeout=0.1, request_gap=0)
        with pytest.raises(ValueError, match="unresolved"):
            await restarted.preview(**options(address))
        peer.instance = NEW
        observed = await restarted.reconcile(
            operation_id="readback-after-restart", receipt_id=result["id"]
        )
        assert observed["read_only"] and observed["readback"]["status"] == "verified_new"
        assert not restarted.status()["receipts"][0]["pending"]
        assert len(peer.wire_writes) == 1
        # A later separate renumber/offline observation cannot reopen a resolved attempt.
        peer.instance = OLD
        await restarted.reconcile(operation_id="later-readback", receipt_id=result["id"])
        assert not restarted.status()["receipts"][0]["pending"]


@pytest.mark.asyncio
async def test_stale_identity_expiry_hash_and_target_guards_send_no_writes(link, monkeypatch):
    peer, client, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    plan = await service.preview(**options(address))
    peer.metadata["model-name"] = "Different controller"
    result = await service.apply(**apply_request(plan))
    assert result["status"] == "not_sent" and "identity changed" in result["errors"][0]
    plan = await service.preview(**options(address))
    service._plans[plan["token"]]["expires"] = time.monotonic() - 1
    result = await service.apply(**apply_request(plan))
    assert result["status"] == "not_sent" and "expired" in result["errors"][0]
    plan = await service.preview(**options(address))
    with pytest.raises(ValueError, match="changed"):
        await service.apply(**apply_request(plan, review_sha256="0" * 64))
    with pytest.raises(ValueError, match="client"):
        await service.preview(**options(address, new_instance=4190001))
    with pytest.raises(ValueError, match="itself"):
        await service.preview(**options(client.config["local_address"]))
    with pytest.raises(ValueError, match="differ"):
        await service.preview(**options(address, new_instance=OLD))
    assert not peer.wire_writes
    assert_retired(client)


@pytest.mark.asyncio
async def test_collision_before_preview_or_between_review_and_apply_blocks_write(link, monkeypatch):
    peer, client, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    plan = await service.preview(**options(address))

    async def occupied(request):
        return {
            **await clear_collision(request),
            "devices": [{"address": "3001:8", "device_instance": NEW}],
        }

    monkeypatch.setattr(service, "_collision", occupied)
    result = await service.apply(**apply_request(plan))
    assert result["status"] == "not_sent" and "collision" in result["errors"][0]
    blocked = await service.preview(**options(address))
    assert not blocked["can_apply"]
    with pytest.raises(ValueError, match="blocked"):
        await service.apply(**apply_request(blocked))
    assert not peer.wire_writes


@pytest.mark.asyncio
async def test_durable_intent_failure_and_interface_change_prevent_dispatch(link, monkeypatch):
    peer, client, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    plan = await service.preview(**options(address))

    def unavailable(_receipt):
        raise OSError("Authored full disk")

    monkeypatch.setattr(service.journal, "intent", unavailable)
    result = await service.apply(**apply_request(plan))
    assert result["status"] == "not_sent" and not result["may_have_applied"]
    assert "full disk" in result["errors"][0]
    plan = await service.preview(**options(address))
    client.config = {**client.config, "instance": 4190002}
    result = await service.apply(**apply_request(plan))
    assert result["status"] == "not_sent" and not peer.wire_writes
    assert_retired(client)


@pytest.mark.asyncio
async def test_disconnect_after_dispatch_preserves_unknown_and_retires_all_work(link, monkeypatch):
    peer, client, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    peer.mode = "hold"
    plan = await service.preview(**options(address))
    old_app = client.app
    task = asyncio.create_task(service.apply(**apply_request(plan)))
    await asyncio.wait_for(peer.entered.wait(), 2)
    await service.close()
    result = await task
    assert result["status"] == "unknown" and result["may_have_applied"]
    assert service.journal.receipt(result["id"])["attempt"] == result
    assert service.status()["receipts"][0]["pending"]
    await asyncio.sleep(0.2)
    assert len(peer.wire_writes) == 1
    assert_retired(client, old_app)


@pytest.mark.asyncio
async def test_cancel_before_native_dispatch_cannot_send_when_a_cache_lookup_resumes(
    link, monkeypatch
):
    peer, client, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    plan = await service.preview(**options(address))
    entered, release = asyncio.Event(), asyncio.Event()
    original = client.app.device_info_cache.get_device_info

    async def held(target):
        if any(
            packet.apduService == 15
            for requests in client.app._requests.values()
            for packet, _ in requests
        ):
            entered.set()
            await release.wait()
        return await original(target)

    monkeypatch.setattr(client.app.device_info_cache, "get_device_info", held)
    request = apply_request(plan)
    task = asyncio.create_task(service.apply(**request))
    await asyncio.wait_for(entered.wait(), 2)
    service.cancel(request["operation_id"])
    result = await task
    release.set()
    await asyncio.sleep(0.15)
    assert result["status"] == "not_sent" and not result["may_have_applied"]
    assert not peer.wire_writes and service.journal.receipt(result["id"])["intent"] is None
    assert_retired(client)


@pytest.mark.asyncio
async def test_separate_applications_cannot_commit_two_pending_station_intents(link, monkeypatch):
    peer, client, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    peer.mode = "hold"
    task = asyncio.create_task(
        service.apply(**apply_request(await service.preview(**options(address))))
    )
    await asyncio.wait_for(peer.entered.wait(), 2)
    other = DeviceInstances(client, client.store)
    first = other.journal.entries()[0]["attempt"]
    with pytest.raises(sqlite3.IntegrityError):
        other.journal.intent({**first, "id": "f" * 32})
    await service.close()
    result = await task
    assert result["status"] == "unknown" and len(peer.wire_writes) == 1


@pytest.mark.asyncio
async def test_intent_only_restart_and_corrupt_evidence_fail_closed(link, monkeypatch):
    _, client, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    plan = await service.preview(**options(address))

    def no_result(_receipt):
        raise OSError("Authored lost result journal")

    monkeypatch.setattr(service.journal, "result", no_result)
    result = await service.apply(**apply_request(plan))
    restarted = DeviceInstances(client, client.store, timeout=0.1, request_gap=0)
    entry = restarted.journal.receipt(result["id"])
    assert entry["attempt"]["journal_state"] == "intent_only" and restarted.pending(entry)
    await restarted.reconcile(operation_id="restart-readback", receipt_id=result["id"])
    assert not restarted.status()["receipts"][0]["pending"]
    with client.store.connect() as db:
        db.execute("UPDATE device_instance_changes SET intent=? WHERE id=?", (b"{}", result["id"]))
    with pytest.raises(ValueError, match="integrity"):
        restarted.status()


@pytest.mark.asyncio
async def test_owned_commands_activity_and_superseded_review_block_commissioning(link, monkeypatch):
    _, client, service, address = link
    monkeypatch.setattr(service, "_collision", clear_collision)
    client.commands["authored"] = {}
    with pytest.raises(ValueError, match="Release"):
        await service.preview(**options(address))
    client.commands.clear()

    def active():
        raise ValueError("Authored active monitor")

    service.activity_guard = active
    with pytest.raises(ValueError, match="active monitor"):
        await service.preview(**options(address))
    service.activity_guard = lambda: None
    first = await service.preview(**options(address))
    await service.preview(**options(address))
    with pytest.raises(ValueError, match="unavailable"):
        await service.apply(**apply_request(first))


@pytest.mark.parametrize(
    "updates",
    [
        {"new_instance": True},
        {"new_instance": "15136"},
        {"new_instance": 1.5},
        {"new_instance": -1},
        {"new_instance": 4194303},
        {"device": "device,4194303"},
        {"address": "localhost"},
        {"address": "3001:*", "router": "127.0.0.1", "dnet": 3001},
        {"address": "3001:7", "router": "127.0.0.1", "dnet": 3002},
    ],
)
def test_exact_target_and_integer_validation(updates):
    with pytest.raises(ValueError):
        InstancePreview(**(options("127.0.0.1") | updates))
    with pytest.raises(ValueError):
        InstanceApply(
            **apply_request({"token": "a" * 32, "review_sha256": "a" * 64}, allocation_confirmed=1)
        )


class InstanceRouter(asyncio.DatagramProtocol):
    """Literal BVLC/NPDU framing; two duplicate-ID stations behind one router."""

    def __init__(self, rogue=None):
        self.rogue = rogue
        self.instances, self.metadata = {7: OLD, 8: OLD}, copy.deepcopy(METADATA)
        self.errors, self.tasks, self.writes, self.queries = [], set(), [], []
        self.collision = False

    def connection_made(self, transport):
        self.transport = transport
        host, port = transport.get_extra_info("sockname")
        self.endpoint = f"{host}:{port}"

    def datagram_received(self, data, source):
        task = asyncio.create_task(self.respond(data, source))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def frame(self, reply, mac):
        packet = reply.encode()
        if isinstance(packet, APDU):
            packet = packet.encode()
        payload = b"\x01\x08\x0b\xb9\x01" + bytes([mac]) + bytes(packet.pduData)
        return b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload

    async def respond(self, data, source):
        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            packet = data[4:]
            assert packet[0] == 1 and packet[2:4] == b"\x0b\xb9"
            length = packet[4]
            assert packet[5 + length] == 255
            request = APCISequence.decode(APDU.decode(PDU(packet[6 + length :])))
            if isinstance(request, WhoIsRequest):
                assert length == 0 and packet[1] == 0x20
                assert (
                    request.deviceInstanceRangeLowLimit
                    == request.deviceInstanceRangeHighLimit
                    == NEW
                )
                self.queries.append(NEW)
                if self.collision:
                    reply = IAmRequest(
                        iAmDeviceIdentifier=("device", NEW),
                        maxAPDULengthAccepted=1476,
                        segmentationSupported="no-segmentation",
                        vendorID=5,
                    )
                    self.transport.sendto(self.frame(reply, 8), source)
                return
            assert length == 1 and packet[5] == 7 and packet[1] == 0x24
            if isinstance(request, ReadPropertyRequest):
                reply = read_reply(request, self.instances[7], self.metadata)
            else:
                assert isinstance(request, WritePropertyRequest) and request.apduService == 15
                assert str(request.objectIdentifier) == f"device,{OLD}"
                assert str(request.propertyIdentifier) == "object-identifier"
                assert request.priority is None and request.propertyArrayIndex is None
                assert request.propertyValue.cast_out(ObjectIdentifier) == ObjectIdentifier(
                    ("device", NEW)
                )
                self.writes.append(bytes(packet[6 + length :]))
                self.instances[7] = NEW
                reply = SimpleAckPDU(context=request)
            reply.apduInvokeID, reply.apduSeg, reply.apduMor = request.apduInvokeID, False, False
            frame = self.frame(reply, 7)
            if self.rogue:
                self.rogue.sendto(frame, source)
                await asyncio.sleep(0.002)
            self.transport.sendto(frame, source)
        except Exception as exc:
            self.errors.append(exc)

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("collision", [False, True])
async def test_routed_udp_exact_station_duplicate_id_wrong_cached_router_and_collision(
    tmp_path, collision
):
    loop = asyncio.get_running_loop()
    rogue, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    _, router = await loop.create_datagram_endpoint(
        lambda: InstanceRouter(rogue), local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        saved = copy.deepcopy(client.config)
        await client.app.nsap.update_router_references(
            None, Address(rogue.get_extra_info("sockname")), [3001]
        )
        service = DeviceInstances(
            client, client.store, timeout=0.2, operation_timeout=6, request_gap=0
        )
        router.collision = collision
        plan = await service.preview(**options("3001:7", router=router.endpoint, dnet=3001))
        assert plan["can_apply"] is not collision
        if collision:
            assert plan["collision_check"]["devices"][0]["address"] == "3001:8"
            with pytest.raises(ValueError, match="blocked"):
                await service.apply(**apply_request(plan))
            assert not router.writes
        else:
            result = await service.apply(**apply_request(plan))
            assert result["status"] == "verified" and result["protocol_accepted"], result
            assert router.instances == {7: NEW, 8: OLD}
            assert len(router.writes) == 1 and router.queries == [NEW, NEW]
        assert client.config == saved
        assert_retired(client)
    finally:
        client.close()
        await router.close()
        rogue.close()
        assert not router.errors
