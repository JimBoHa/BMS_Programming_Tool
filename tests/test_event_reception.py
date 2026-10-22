"""Independent raw UDP event peers; no native event encoder or site traffic."""

import asyncio
import struct
import threading

import pytest
from bacpypes3.pdu import Address
from bms_tool.connections import Bacnet
from bms_tool.device_details import DeviceDetails, DeviceDetailsRequest
from bms_tool.event_reception import EventReception
from bms_tool.scoped_hooks import ScopedAttribute
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_foreign_bacnet import bvlc, wait_until


def notification(
    *,
    confirmed=True,
    process=7,
    device=4190010,
    obj=(2 << 22) | 1,
    invoke=42,
    values=True,
    unknown=False,
    timestamp=None,
    exceeding=81.5,
):
    # ASHRAE event service 2/3; context fields authored without BACpypes codecs.
    prefix = bytes((0, 5, invoke, 2)) if confirmed else b"\x10\x03"
    fields = b"\x0c" + struct.pack(">I", process)
    fields += b"\x1c" + struct.pack(">I", (8 << 22) | device)
    fields += b"\x2c" + struct.pack(">I", obj)
    fields += timestamp or bytes.fromhex("3e19283f")
    fields += bytes.fromhex("49035950")
    fields += bytes.fromhex("6a0201") if unknown else bytes.fromhex("6905")
    fields += bytes.fromhex("89009901a900b903")
    if values:
        fields += (
            bytes.fromhex("cefe1a0901ff1acf")
            if unknown
            else bytes.fromhex("ce5e0c")
            + struct.pack(">f", exceeding)
            + bytes.fromhex("1a04802c")
            + struct.pack(">f", 2)
            + b"\x3c"
            + struct.pack(">f", 80)
            + bytes.fromhex("5fcf")
        )
    return prefix + fields


def npdu(payload, *, source=None, destination=None):
    control = (8 if source else 0) | (32 if destination else 0)
    raw = bytes((1, control))
    if destination:
        raw += struct.pack(">HB", destination[0], 1) + bytes((destination[1],))
    if source:
        raw += struct.pack(">HB", source[0], 1) + bytes((source[1],))
    if destination:
        raw += b"\xff"
    return raw + payload


def split_npdu(raw):
    assert raw[0] == 1
    control, offset, destination = raw[1], 2, None
    if control & 32:
        dnet, size = struct.unpack(">HB", raw[offset : offset + 3])
        destination = (dnet, raw[offset + 3 : offset + 3 + size])
        offset += 3 + size
    if control & 8:
        size = raw[offset + 2]
        offset += 3 + size
    if control & 32:
        offset += 1
    return raw[offset:], destination


class RawEvents(asyncio.DatagramProtocol):
    def __init__(self, routed=False):
        self.routed = routed
        self.frames, self.acks, self.errors = [], [], []
        self.other_responses = []
        self.wrong_identity = False
        self.drop_reads = False

    def connection_made(self, transport):
        self.transport = transport
        self.endpoint = transport.get_extra_info("sockname")

    def datagram_received(self, raw, source):
        try:
            assert raw[:2] == b"\x81\x0a" and int.from_bytes(raw[2:4], "big") == len(raw)
            apdu, destination = split_npdu(raw[4:])
            self.frames.append((raw, source))
            self.client = source
            if apdu[:1] == b"\x20":
                assert apdu[2] == 2
                self.acks.append((apdu[1], destination, source))
                return
            if apdu[0] & 0xF0 in (0x50, 0x60, 0x70):
                self.other_responses.append(apdu)
                return
            assert apdu[0] & 0xF0 == 0 and apdu[3] == 12
            assert apdu[4:5] == b"\x0c" and apdu[9:] == bytes.fromhex("194b")
            if self.routed:
                assert destination == (2001, b"\x04")
            if self.drop_reads:
                return
            obj = apdu[5:9]
            value = struct.pack(">I", (8 << 22) | 42) if self.wrong_identity else obj
            reply = (
                b"\x30"
                + apdu[2:3]
                + b"\x0c\x0c"
                + obj
                + bytes.fromhex("194b3ec4")
                + value
                + b"\x3f"
            )
            self.transport.sendto(
                bvlc(10, npdu(reply, source=(2001, 4) if self.routed else None)), source
            )
        except Exception as exc:
            self.errors.append(exc)

    def send(self, raw=None, *, sender=None, source=None, destination=None):
        payload = notification() if raw is None else raw
        if self.routed and source is None:
            source = (2001, 4)
        (sender or self.transport).sendto(
            bvlc(10, npdu(payload, source=source, destination=destination)), self.client
        )


@pytest.fixture(params=[False, True], ids=["direct", "routed"])
async def wire(tmp_path, request):
    loop = asyncio.get_running_loop()
    transport, peer = await loop.create_datagram_endpoint(
        lambda: RawEvents(request.param), local_addr=("127.0.0.1", 0)
    )
    rogue, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    store = Store(tmp_path)
    client = Bacnet(store)
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = EventReception(client, store, timeout=0.2)
    endpoint = f"127.0.0.1:{peer.endpoint[1]}"
    options = dict(
        address="2001:4" if request.param else endpoint,
        device="device,4190010",
        object_id="analog-value,1",
        process_identifier=7,
        mode="both",
        duration_seconds=5,
    )
    if request.param:
        options.update(router=endpoint, dnet=2001)
    try:
        yield peer, rogue, client, service, options
    finally:
        await service.close()
        client.close()
        transport.close()
        rogue.close()
        await asyncio.sleep(0.02)
        assert not peer.errors


async def test_wire_confirmed_unconfirmed_timestamp_native_values_and_pinned_ack(wire):
    peer, rogue, client, service, options = wire
    assert not peer.frames
    started = await service.start(**options)
    assert len(peer.frames) == 2 and not peer.acks
    if peer.routed:
        await client.app.nsap.update_router_references(
            None, Address(f"127.0.0.1:{rogue.get_extra_info('sockname')[1]}"), [2001]
        )
    peer.send()
    peer.send(notification(confirmed=False, timestamp=bytes.fromhex("3e0c08090a0b3f")))
    await wait_until(lambda: service.detail(started["id"])["received"] == 2 and len(peer.acks) == 1)
    data = service.detail(started["id"])
    assert peer.acks[0][0] == 42
    assert peer.acks[0][1] == ((2001, b"\x04") if peer.routed else None)
    first, second = data["events"]
    assert first["event_values"]["type"] == "outOfRange"
    assert first["event_values"]["value"]["exceedingValue"] == 81.5
    assert first["timestamp"] == {"type": "sequenceNumber", "value": 40}
    assert second["timestamp"] == {"type": "time", "value": [8, 9, 10, 11]}
    assert first["source_clock_utc"] is None and first["quality"] == "unknown"
    assert first["protocol_ack"] == "dispatch-returned-reception-only"
    assert first["operator_acknowledged"] is None
    assert second["protocol_ack"] == "not-applicable"
    assert not client.commands and not client.app._requests
    assert all(raw[1] == 10 for raw, _ in peer.frames)


async def test_opaque_unknown_nested_choice_and_native_enum_evidence(wire):
    peer, _, _, service, options = wire
    started = await service.start(**options)
    peer.send(notification(unknown=True))
    await wait_until(lambda: service.detail(started["id"])["received"] == 1)
    event = service.detail(started["id"])["events"][0]
    assert event["event_type"]["value"] == 513 and not event["event_type"]["known"]
    assert event["event_values_decode_status"] == "opaque"
    assert event["event_values"]["type"] == "bacnet-opaque"
    assert event["apdu_hex"] == notification(unknown=True).hex()
    assert event["raw_complete"]
    await wait_until(lambda: len(peer.acks) == 1)


async def test_rogue_peer_route_mode_object_malformed_and_bounds_never_get_owned_ack(wire):
    peer, rogue, _, service, options = wire
    started = await service.start(**(options | {"mode": "confirmed"}))
    peer.send(sender=rogue)
    peer.send(notification(confirmed=False))
    peer.send(notification(obj=(2 << 22) | 2))
    peer.send(notification()[:-1])
    peer.send(notification() + b"\x09\x01")
    peer.send(notification() + b"x" * 4096)
    peer.send(destination=(2002, 4))
    if peer.routed:
        peer.send(source=(2001, 5))
        peer.send(source=(2002, 4))
    await wait_until(lambda: service.detail(started["id"])["ignored"] >= (9 if peer.routed else 7))
    assert service.detail(started["id"])["received"] == 0 and not peer.acks
    assert service.detail(started["id"])["last_rejected"]["reason"]
    peer.send(notification(invoke=88))
    await wait_until(lambda: len(peer.acks) == 1)
    assert peer.acks[0][0] == 88


async def test_flood_retention_duplicates_finite_expiry_and_interface_shutdown(wire):
    peer, _, client, service, options = wire
    now = [0.0]
    service.clock = lambda: now[0]
    started = await service.start(**options)
    for _ in range(125):
        peer.send(notification(confirmed=False))
        await asyncio.sleep(0.001)
    await wait_until(lambda: service.detail(started["id"])["received"] == 125)
    report = service.detail(started["id"])
    assert report["events_retained"] == 100 and report["evicted"] == 25
    assert report["events"][-1]["possible_duplicate"]
    now[0] = 6
    await wait_until(lambda: not service.detail(started["id"])["active"])
    assert service.detail(started["id"])["state"] == "expired" and not service.hooks
    next_session = await service.start(**options)
    await client.disconnect()
    await wait_until(lambda: not service.detail(next_session["id"])["active"])
    assert service.detail(next_session["id"])["state"] == "interface_changed"
    assert not service.hooks and not service.operations


async def test_unrelated_native_observer_preserved_and_scoped_retirement(wire):
    peer, _, client, service, options = wire
    app = client.app
    original = app.nsap.process_npdu
    seen = []

    async def native(adapter, packet):
        seen.append(bytes(packet.pduData))
        return await original(adapter, packet)

    hook = ScopedAttribute(app.nsap, "process_npdu", native)
    started = await service.start(**options)
    seen.clear()
    peer.send(notification(confirmed=False, process=8))
    peer.send(notification(confirmed=False, device=4190099))
    await wait_until(lambda: len(seen) == 2)
    assert not service.detail(started["id"])["received"]
    outer_seen = []
    inner = app.nsap.process_npdu

    async def outer(adapter, packet):
        outer_seen.append(bytes(packet.pduData))
        return await inner(adapter, packet)

    outer_hook = ScopedAttribute(app.nsap, "process_npdu", outer)
    await service.stop(started["id"])
    assert app.nsap.process_npdu is outer
    peer.send(notification(confirmed=False))
    await wait_until(lambda: len(outer_seen) == 1)
    assert len(seen) == 3 and not service.detail(started["id"])["received"]
    outer_hook.close()
    assert app.nsap.process_npdu is native
    hook.close()
    assert app.nsap.process_npdu == original


async def test_routed_receive_and_ack_survive_other_pinned_path(wire):
    peer, _, client, service, options = wire
    if not peer.routed:
        pytest.skip("Routed source filter composition only.")
    started = await service.start(**options)
    other = DeviceDetailsRequest(
        **{key: value for key, value in options.items() if key in {"address", "device", "dnet"}},
        router="127.0.0.1:49997",
    )
    async with DeviceDetails(client, None)._path(other):
        peer.send()
        await wait_until(lambda: len(peer.acks) == 1)
    assert service.detail(started["id"])["received"] == 1
    assert peer.acks[0][1] == (2001, b"\x04")


async def test_failed_identity_and_shutdown_of_held_start_leave_no_listener(wire):
    peer, _, client, service, options = wire
    peer.wrong_identity = True
    with pytest.raises(ValueError, match="identifier value differs|identity differs"):
        await service.start(**options)
    assert not service.hooks and not service.jobs
    peer.wrong_identity, peer.drop_reads = False, True
    operation = asyncio.create_task(service.start(**options))
    await wait_until(lambda: client.lock.locked())
    await service.close()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert not client.lock.locked() and not service.hooks and not service.operations


async def test_native_event_owner_is_refused_before_reads_and_respected_if_added_later(wire):
    peer, _, client, service, options = wire
    seen = []

    async def native(apdu):
        seen.append(apdu)

    client.app.do_UnconfirmedEventNotificationRequest = native
    with pytest.raises(ValueError, match="native event-recipient handler"):
        await service.start(**options)
    assert not peer.frames and not service.hooks
    del client.app.do_UnconfirmedEventNotificationRequest
    started = await service.start(**options)
    client.app.do_UnconfirmedEventNotificationRequest = native
    await wait_until(lambda: not service.detail(started["id"])["active"])
    assert not service.hooks and client.app.do_UnconfirmedEventNotificationRequest is native
    peer.send(notification(confirmed=False))
    await wait_until(lambda: len(seen) == 1)
    assert not service.detail(started["id"])["received"] and not peer.acks
    del client.app.do_UnconfirmedEventNotificationRequest


async def test_noncanonical_process_tags_remain_owned_and_oversize_prefix_has_no_owned_ack(wire):
    peer, _, _, service, options = wire
    started = await service.start(**(options | {"mode": "confirmed"}))
    raw = notification()
    extended = raw[:4] + b"\x0d\x04\0\0\0\x07" + raw[9:]
    peer.send(extended)
    await wait_until(lambda: len(peer.acks) == 1)
    assert service.detail(started["id"])["received"] == 1
    peer.send(b"\x10\x03" + extended[4:])
    await wait_until(lambda: service.detail(started["id"])["ignored"] == 1)
    oversize = raw[:4] + b"\x0d\x05\0\0\0\0\x07" + raw[9:]
    peer.send(oversize)
    await wait_until(lambda: bool(peer.other_responses))
    assert len(peer.acks) == 1 and service.detail(started["id"])["received"] == 1


async def test_callback_capacity_and_stop_cancel_and_join_owned_ack_dispatches(wire):
    peer, _, client, service, options = wire
    started = await service.start(**options)
    adapter = client.app.nsap.local_adapter
    original = adapter.process_npdu
    pending = set()

    async def held(packet):
        if bytes(packet.pduData)[:1] == b"\x20":
            task = asyncio.current_task()
            pending.add(task)
            try:
                await asyncio.Event().wait()
            finally:
                pending.discard(task)
        else:
            await original(packet)

    hook = ScopedAttribute(adapter, "process_npdu", held)
    try:
        for invoke in range(24):
            peer.send(notification(invoke=invoke))
        await wait_until(lambda: service.detail(started["id"])["ignored"] >= 8)
        assert len(pending) <= 16 and service.detail(started["id"])["pending_callbacks"] <= 16
        stopped = await service.stop(started["id"])
        assert stopped["pending_callbacks"] == 0 and not pending and not peer.acks
        assert all(row["protocol_ack"] == "unknown" for row in stopped["events"])
        assert stopped["ack_failures"] == stopped["received"]
    finally:
        hook.close()


async def test_device_process_ownership_is_exclusive_and_distinct_processes_keep_own_modes(wire):
    peer, _, _, service, options = wire
    first = await service.start(**(options | {"mode": "confirmed"}))
    count = len(peer.frames)
    with pytest.raises(ValueError, match="already has an active receiver"):
        await service.start(**(options | {"mode": "unconfirmed"}))
    assert len(peer.frames) == count
    second = await service.start(**(options | {"process_identifier": 8, "mode": "unconfirmed"}))
    peer.send(notification())
    peer.send(notification(confirmed=False, process=8))
    await wait_until(
        lambda: (
            service.detail(first["id"])["received"] == 1
            and service.detail(second["id"])["received"] == 1
            and len(peer.acks) == 1
        )
    )
    assert len(peer.acks) == 1
    await service.stop(first["id"])
    assert service.hooks and service.detail(second["id"])["active"]
    peer.send(notification(confirmed=False, process=8))
    await wait_until(lambda: service.detail(second["id"])["received"] == 2)


async def test_final_snapshot_storage_failure_restart_integrity_and_no_auto_listen(
    wire, monkeypatch
):
    peer, _, client, service, options = wire
    started = await service.start(**options)
    with pytest.raises(ValueError, match="Stop the listener"):
        await service.save(started["id"])
    peer.send(notification(confirmed=False))
    await wait_until(lambda: service.detail(started["id"])["received"] == 1)
    await service.stop(started["id"])
    original = service._save
    monkeypatch.setattr(
        service, "_save", lambda report: (_ for _ in ()).throw(OSError("authored storage failure"))
    )
    with pytest.raises(OSError, match="authored storage"):
        await service.save(started["id"])
    assert service.snapshots() == []
    monkeypatch.setattr(service, "_save", original)
    saved = await service.save(started["id"])
    assert saved["events"][0]["source_clock_utc"] is None and not saved["auto_resume"]
    count = len(peer.frames)
    reopened = EventReception(client, service.store)
    try:
        assert reopened.status()["sessions"] == [] and len(peer.frames) == count
        assert reopened.saved(started["id"])["events"] == saved["events"]
        with service.store.connect() as db:
            db.execute("UPDATE event_reception_snapshots SET body=body||' '")
        with pytest.raises(ValueError, match="integrity"):
            reopened.saved(started["id"])
    finally:
        await reopened.close()


async def test_shutdown_repeated_cancellation_joins_explicit_snapshot_writer(wire, monkeypatch):
    peer, _, _, service, options = wire
    started = await service.start(**options)
    await service.stop(started["id"])
    entered, release = threading.Event(), threading.Event()
    original = service._save

    def held(report):
        entered.set()
        assert release.wait(2)
        return original(report)

    monkeypatch.setattr(service, "_save", held)
    saving = asyncio.create_task(service.save(started["id"]))
    assert await asyncio.to_thread(entered.wait, 1)
    saving.cancel()
    stopping = asyncio.create_task(service.close())
    await asyncio.sleep(0.02)
    saving.cancel()
    assert not saving.done() and not stopping.done()
    release.set()
    await stopping
    with pytest.raises(asyncio.CancelledError):
        await saving
    assert service.snapshots() and not service.operations and not peer.acks


@pytest.mark.parametrize(
    "changes",
    [
        {"device": "analog-value,1"},
        {"device": "device,4194303"},
        {"process_identifier": True},
        {"process_identifier": -1},
        {"process_identifier": 2**32},
        {"mode": "automatic"},
        {"duration_seconds": True},
        {"duration_seconds": 4},
        {"duration_seconds": 3601},
        {"object_id": "analog-input,4194303"},
        {"router": "127.0.0.1:47808"},
        {"address": "2001:4"},
        {"address": "255.255.255.255"},
    ],
)
def test_explicit_bounded_request_models(changes):
    from bms_tool.event_reception import EventListenStart
    from pydantic import ValidationError

    base = dict(address="127.0.0.1:47809", device="device,42", process_identifier=7, mode="both")
    with pytest.raises(ValidationError):
        EventListenStart(**(base | changes))
