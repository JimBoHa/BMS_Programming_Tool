"""Independent wire-encoded Calendar/Schedule peer; no native response encoder."""

import asyncio
import hashlib
import math
import socket
import struct

import pytest
from bacpypes3.apdu import APDU, APCISequence, ReadPropertyRequest
from bacpypes3.pdu import PDU
from bms_tool.connections import Bacnet
from bms_tool.schedule_inventory import ScheduleInventory, ScheduleReadRequest, _encoded
from bms_tool.storage import Store

from .test_connections import free_udp


def oid(kind, instance):
    return struct.pack(">I", (kind << 22) | instance)


def unsigned(number, context=None):
    raw = number.to_bytes(max(1, (number.bit_length() + 7) // 8), "big")
    return (
        bytes(
            [((2 if context is None else context) << 4) | (0 if context is None else 8) | len(raw)]
        )
        + raw
    )


def text(value):
    data = b"\x00" + value.encode()
    return bytes([0x75, len(data)]) + data if len(data) >= 5 else bytes([0x70 | len(data)]) + data


class SchedulePeer(asyncio.DatagramProtocol):
    """Literal standard BVLC/NPDU/APDU reply fields, independently authored values."""

    def __init__(self, *, routed=False, behavior="normal"):
        self.routed, self.behavior = routed, behavior
        self.requests, self.errors, self.tasks = [], [], set()
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.hold_property = None
        self.corrupt_property = None
        self.rogue = None
        self.rogue_kind = None
        self.object_list = [(8, 42), (0, 5), (6, 1), (17, 1), (6, 2)]
        self.exception_count = 2

    def connection_made(self, transport):
        self.transport = transport
        host, port = transport.get_extra_info("sockname")
        self.endpoint = f"{host}:{port}"

    def datagram_received(self, data, source):
        task = asyncio.create_task(self.reply(data, source))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def value(self, obj, prop, index):
        kind, instance = int(obj[0]), obj[1]
        if prop == "object-identifier":
            return b"\xc4" + oid(kind, 99 if self.behavior == "wrong_identity" else instance)
        if prop == "object-name":
            return text(f"Native {obj}")
        if prop == "description":
            return text("Evidence fixture")
        if prop == "object-list":
            return (
                unsigned(len(self.object_list))
                if index == 0
                else b"\xc4" + oid(*self.object_list[index - 1])
            )
        if prop == "local-date":
            return b"\xa4\x7e\x0a\x15\x03"
        if prop == "local-time":
            return b"\xb4\x0d\x18\x06\x63"
        if prop == "utc-offset":
            return b"\x32\x01\xe0"  # signed 480, not a timezone identifier
        if prop == "daylight-savings-status":
            return b"\x11"
        if prop == "present-value":
            return b"\x10" if kind == 6 else b"\x44" + struct.pack(">f", -0.0)
        if prop == "date-list":
            # wildcard/special month/day fields, range, and weekNDay native Choice
            return b"\x0c\xff\x0d\x20\xff\x1e\xa4\xff\x01\x01\xff\xa4\xff\x0c\x1f\xff\x1f\x2b\xff\x06\x07"
        if prop == "effective-period":
            return b"\xa4\xff\xff\xff\xff\xa4\xff\xff\xff\xff"
        if prop == "schedule-default":
            return b"\x44" + struct.pack(">f", 2.0)
        if prop == "priority-for-writing":
            return unsigned(8)
        if prop == "list-of-object-property-references":
            return b"\x0c" + oid(2, 10) + b"\x19\x55\x29\x02\x3c" + oid(8, 77)
        if prop == "status-flags":
            return b"\x82\x04\x00"
        if prop == "reliability":
            return b"\x92\x03\xe7" if self.behavior == "unknown_enum" else b"\x91\x00"
        if prop == "out-of-service":
            return b"\x10"
        if prop == "weekly-schedule":
            if index == 0:
                return unsigned(7)
            primitive = (
                b"\xd1\x01"
                if self.behavior == "unknown_any" and index == 1
                else b"\x44" + struct.pack(">f", -0.0)
            )
            return b"\x0e\xb4\x08\x00\x00\x00" + primitive + b"\x0f"
        if prop == "exception-schedule":
            if index == 0:
                return unsigned(self.exception_count)
            period = b"\x0e\x0c\xff\x02\x1d\xff\x0f" if index == 1 else b"\x1c" + oid(6, 2)
            return (
                period + b"\x2e\xb4\x09\x1e\x00\x00\x44" + struct.pack(">f", 2.0) + b"\x2f\x39\x08"
            )
        raise ValueError(prop)

    async def reply(self, data, source):
        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            packet = data[4:]
            if self.routed:
                assert (
                    packet[:2] == b"\x01\x24"
                    and packet[2:6] == b"\x0b\xb9\x01\x07"
                    and packet[6] == 255
                )
                payload = packet[7:]
                response_npdu = b"\x01\x08\x0b\xb9\x01\x07"
            else:
                assert packet[:2] == b"\x01\x04"
                payload, response_npdu = packet[2:], b"\x01\x00"
            request = APCISequence.decode(APDU.decode(PDU(payload)))
            assert isinstance(request, ReadPropertyRequest), (
                "Only explicit ReadProperty is allowed."
            )
            obj, prop, index = (
                request.objectIdentifier,
                str(request.propertyIdentifier),
                request.propertyArrayIndex,
            )
            self.requests.append((str(obj), prop, index))
            if self.behavior == "hold" or prop == self.hold_property:
                self.entered.set()
                await self.release.wait()
            if prop == self.corrupt_property and self.behavior == "timeout":
                return
            reference = (
                b"\x0c" + oid(int(obj[0]), obj[1]) + unsigned(int(request.propertyIdentifier), 1)
            )
            if index is not None:
                reference += unsigned(index, 2)
            value = self.value(obj, prop, index)
            if prop == self.corrupt_property:
                if self.behavior == "native_error":
                    apdu = bytes([0x50, request.apduInvokeID, 12]) + b"\x91\x02\x91\x20"
                elif self.behavior == "wrong_property":
                    apdu = (
                        bytes([0x30, request.apduInvokeID, 12])
                        + b"\x0c"
                        + oid(int(obj[0]), obj[1])
                        + b"\x19\x55\x3e"
                        + value
                        + b"\x3f"
                    )
                else:
                    if self.behavior == "trailing":
                        value += b"\x21\x01"
                    elif self.behavior == "unclosed":
                        value = b"\x0e\xb4\x08\x00\x00\x00\x44\x00\x00\x00\x00"
                    elif self.behavior == "oversize":
                        value = text("x" * 10) * 2000
                    apdu = (
                        bytes([0x30, request.apduInvokeID, 12])
                        + reference
                        + b"\x3e"
                        + value
                        + b"\x3f"
                    )
            else:
                apdu = (
                    bytes([0x30, request.apduInvokeID, 12]) + reference + b"\x3e" + value + b"\x3f"
                )
            body = response_npdu + apdu
            frame = b"\x81\x0a" + struct.pack(">H", len(body) + 4) + body
            if self.rogue:
                spoof = frame
                if self.rogue_kind == "forwarded":
                    host, port = self.transport.get_extra_info("sockname")
                    body = socket.inet_aton(host) + struct.pack(">H", port) + frame[4:]
                    spoof = b"\x81\x04" + struct.pack(">H", len(body) + 4) + body
                elif self.rogue_kind == "wrong_invoke":
                    body = (
                        response_npdu
                        + bytes([0x30, (request.apduInvokeID + 77) % 256, 12])
                        + apdu[3:]
                    )
                    spoof = b"\x81\x0a" + struct.pack(">H", len(body) + 4) + body
                self.rogue.sendto(spoof, source)
                await asyncio.sleep(0.002)
            self.transport.sendto(frame, source)
        except Exception as exc:
            self.errors.append(exc)

    def close(self):
        self.release.set()
        for task in list(self.tasks):
            task.cancel()
        self.transport.close()


async def make_peer(**kwargs):
    peer = SchedulePeer(**kwargs)
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    return peer


def options(peer, **kwargs):
    return (
        dict(
            address="3001:7" if peer.routed else peer.endpoint,
            device="device,42",
            router=peer.endpoint if peer.routed else None,
            dnet=3001 if peer.routed else None,
            operation_id="schedule_test_operation",
            object_ids=["calendar,1", "schedule,1"],
        )
        | kwargs
    )


@pytest.fixture
async def link(tmp_path):
    peer = await make_peer()
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = ScheduleInventory(
        client, client.store, timeout=0.08, operation_timeout=3, request_gap=0
    )
    try:
        yield peer, client, service
    finally:
        await service.close()
        client.close()
        peer.close()
        await asyncio.sleep(0.03)


def verify_hash(report):
    body = {key: value for key, value in report.items() if key != "evidence_sha256"}
    assert hashlib.sha256(_encoded(body)).hexdigest() == report["evidence_sha256"]


def retired(client):
    app = client.app
    assert not app._requests
    assert not app.asap.clientTransactions
    assert not app.nsap.local_adapter.clientPeer.multiplexer.__dict__.get("confirmation")


@pytest.mark.asyncio
async def test_exact_values_wildcards_native_any_and_no_reference_crawling(link):
    peer, client, service = link
    report = await service.read(**options(peer, include_device_clock=True))
    assert report["status"] == "complete", report
    cal, schedule = report["objects"]
    dates = cal["properties"]["date-list"]["value"]
    assert dates[0] == {
        "type": "date",
        "value": {"native_datatype": "Date", "fields": [255, 13, 32, 255]},
    }
    assert dates[1]["type"] == "dateRange" and dates[2]["type"] == "weekNDay"
    p = schedule["properties"]
    assert p["effective-period"]["value"]["startDate"]["fields"] == [255] * 4
    assert (
        p["schedule-default"]["value"]["native_datatype"] == "Real"
        and p["schedule-default"]["value"]["value"] == 2.0
    )
    assert math.copysign(1, p["present-value"]["value"]["value"]) == -1
    assert (
        p["weekly-schedule"]["elements"][0]["value"]["daySchedule"][0]["value"]["native_datatype"]
        == "Real"
    )
    assert p["exception-schedule"]["elements"][1]["value"]["period"]["type"] == "calendarReference"
    reference = p["list-of-object-property-references"]["value"][0]
    assert (
        reference["deviceIdentifier"]["value"] == "device,77"
        and reference["propertyArrayIndex"] == 2
    )
    assert report["device_clock"]["utc-offset"]["value"] == 480
    assert report["source_clock_utc"] is None
    assert all(obj in ("device,42", "calendar,1", "schedule,1") for obj, _, _ in peer.requests)
    assert not peer.errors
    verify_hash(report)
    retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("routed", [False, True])
async def test_exact_source_and_rogue_peer_ignored_even_with_same_route_and_invoke(link, routed):
    old, client, service = link
    peer = await make_peer(routed=routed)
    rogue, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    peer.rogue = rogue
    try:
        report = await service.read(**options(peer))
        assert report["status"] == "complete", report
        if routed:
            assert report["ignored_transport_candidates"] == len(peer.requests)
        schedule = report["objects"][1]["properties"]
        wire = schedule["present-value"]["transport_evidence"]
        assert wire["next_hop"] == peer.endpoint
        assert wire["npdu_source"] == ("3001:7" if routed else None)
        assert (
            hashlib.sha256(bytes.fromhex(wire["udp_payload_hex"])).hexdigest()
            == wire["udp_payload_sha256"]
        )
        assert not peer.errors
        retired(client)
        assert "indication" not in client.app.nsap.__dict__
    finally:
        rogue.close()
        peer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "behavior,prop,status",
    [
        ("native_error", "description", "native_error"),
        ("timeout", "description", "timeout"),
        ("wrong_property", "object-name", "protocol_error"),
        ("trailing", "description", "decode_error"),
        ("unclosed", "weekly-schedule", "decode_error"),
        ("oversize", "description", "timeout"),
    ],
)
async def test_failures_never_fabricate_empty_or_valid_schedule(link, behavior, prop, status):
    peer, client, service = link
    peer.behavior, peer.corrupt_property = behavior, prop
    report = await service.read(**options(peer, object_ids=["schedule,1"]))
    assert report["status"] == "partial" and not report["complete"], report
    rows = report["objects"][0]["properties"]
    row = rows[prop]["count_read"] if prop == "weekly-schedule" else rows[prop]
    assert row["status"] == status, row
    if behavior in ("trailing", "unclosed"):
        assert row["encoded_value"]["hex"]
    if behavior == "native_error":
        assert row["native_error"]["errorCode"]["value"] == 32
    assert rows["out-of-service"]["status"] == "ok"
    retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior", ["unknown_any", "unknown_enum"])
async def test_unknown_values_stay_typed_or_opaque_evidence(link, behavior):
    peer, client, service = link
    peer.behavior = behavior
    report = await service.read(**options(peer, object_ids=["schedule,1"]))
    rows = report["objects"][0]["properties"]
    if behavior == "unknown_any":
        first = rows["weekly-schedule"]["elements"][0]
        assert first["status"] == "partial" and first["nested_decode_errors"]
        assert first["value"]["daySchedule"][0]["value"]["decode_status"] == "opaque"
        assert not report["complete"]
    else:
        enum = rows["reliability"]["value"]
        assert enum["value"] == 999 and not enum["known"]
    verify_hash(report)
    retired(client)


@pytest.mark.asyncio
async def test_discovery_pages_are_explicit_and_references_not_crawled(link):
    peer, client, service = link
    first = await service.read(**options(peer, object_ids=None, object_list_limit=3))
    assert first["inventory"]["next_offset"] == 3 and not first["complete"]
    assert [o["object"] for o in first["objects"]] == ["calendar,1"]
    requests = len(peer.requests)
    await asyncio.sleep(0.03)
    assert len(peer.requests) == requests
    second = await service.read(
        **options(
            peer,
            operation_id="schedule_second_page",
            object_ids=None,
            object_list_offset=3,
            object_list_limit=3,
            max_objects=1,
        )
    )
    assert second["inventory"]["next_offset"] == 4
    assert [o["object"] for o in second["objects"]] == ["schedule,1"]
    assert not any(obj == "device,77" for obj, _, _ in peer.requests)
    retired(client)


@pytest.mark.asyncio
async def test_wrong_device_or_object_identity_blocks_remaining_fields(link):
    peer, client, service = link
    peer.behavior = "wrong_identity"
    report = await service.read(**options(peer))
    assert not report["identity_verified"] and report["requests"] == 1 and not report["objects"]
    retired(client)


@pytest.mark.asyncio
async def test_array_bounds_and_missing_fields_are_incomplete(link):
    peer, client, service = link
    peer.exception_count = 33
    report = await service.read(**options(peer, object_ids=["schedule,1"]))
    array = report["objects"][0]["properties"]["exception-schedule"]
    assert array["status"] == "limited" and len(array["elements"]) == 32 and not array["complete"]
    assert not report["complete"]
    retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "close", "interface", "deadline"])
async def test_owned_teardown_retires_transactions_and_route_hooks(link, action):
    old, client, service = link
    peer = await make_peer(routed=True, behavior="hold")
    service.timeout = 0.1
    if action == "deadline":
        service.operation_timeout = 0.05
    app = client.app
    task = asyncio.create_task(service.read(**options(peer)))
    try:
        await asyncio.wait_for(peer.entered.wait(), 1)
        if action == "cancel":
            assert service.cancel("schedule_test_operation")["cancel_requested"]
        elif action == "close":
            await service.close()
        elif action == "interface":
            client.close()
        report = await task
        assert (
            report["status"]
            == {
                "cancel": "cancelled",
                "close": "cancelled",
                "interface": "interface_changed",
                "deadline": "timeout",
            }[action]
        )
        assert not app._requests and not app.asap.clientTransactions and not client.lock.locked()
        assert "process_npdu" not in app.nsap.__dict__ and "indication" not in app.nsap.__dict__
        assert "confirmation" not in app.nsap.local_adapter.clientPeer.multiplexer.__dict__
        peer.release.set()
        await asyncio.sleep(0.02)
        verify_hash(report)
    finally:
        peer.close()


@pytest.mark.asyncio
async def test_cancel_before_admission_and_concurrent_rejection(link):
    peer, client, service = link
    service.cancel("cancel_before_read")
    with pytest.raises(ValueError, match="before admission"):
        await service.read(**options(peer, operation_id="cancel_before_read"))
    peer.behavior = "hold"
    task = asyncio.create_task(service.read(**options(peer)))
    await peer.entered.wait()
    with pytest.raises(ValueError, match="another read"):
        await service.read(**options(peer, operation_id="other_operation"))
    service.cancel("schedule_test_operation")
    await task
    retired(client)


@pytest.mark.asyncio
async def test_immutable_bounded_reports_and_restart_disabled(link):
    peer, client, service = link
    report = await service.read(**options(peer, object_ids=["calendar,1"]))
    report["objects"].clear()
    assert service.detail(report["id"])["objects"]
    fresh = ScheduleInventory(client, client.store)
    assert not fresh.status()["reports"] and not fresh.status()["active_operation"]
    await fresh.close()
    assert not peer.errors


@pytest.mark.parametrize(
    "extra",
    [
        {"device": "device,4194303"},
        {"object_ids": ["analog-input,1"]},
        {"object_ids": ["schedule,1", "schedule,1"]},
        {"object_ids": ["calendar,4194303"]},
        {"object_list_limit": 257},
        {"object_list_offset": True},
        {"max_objects": 17},
        {"router": "127.0.0.1"},
        {"dnet": 3001},
        {"operation_id": "short"},
    ],
)
def test_strict_options(extra):
    with pytest.raises(ValueError):
        ScheduleReadRequest(
            **(
                {"address": "127.0.0.1", "device": "device,42", "operation_id": "valid_operation"}
                | extra
            )
        )


@pytest.mark.asyncio
async def test_unrelated_transport_observer_called_once_and_restored_when_it_raises(link):
    peer, client, service = link
    mux = client.app.nsap.local_adapter.clientPeer.multiplexer
    original = mux.confirmation
    calls = []

    async def unrelated(packet):
        calls.append(packet)
        raise RuntimeError("independent observer")

    mux.confirmation = unrelated
    request = ReadPropertyRequest(objectIdentifier=("device", 42), propertyIdentifier="object-name")
    request.apduInvokeID = 13
    session = {
        "app": client.app,
        "config": client.config,
        "target": __import__("bacpypes3.pdu", fromlist=["Address"]).Address(peer.endpoint),
    }
    try:
        async with service._wire(session, {"ignored_transport_candidates": 0}, request):
            with pytest.raises(RuntimeError, match="independent observer"):
                await mux.confirmation(PDU(b"irrelevant"))
        assert len(calls) == 1 and mux.confirmation is unrelated
    finally:
        mux.confirmation = original


@pytest.mark.asyncio
async def test_report_retention_budget_and_socket_identity_change(link, monkeypatch):
    import bms_tool.schedule_inventory as inventory

    peer, client, service = link
    monkeypatch.setattr(inventory, "MAX_REPORTS", 2)
    identifiers = []
    for n in range(3):
        report = await service.read(
            **options(peer, operation_id=f"operation_number_{n}", object_ids=["calendar,1"])
        )
        identifiers.append(report["id"])
    assert len(service.reports) == 2
    with pytest.raises(ValueError, match="not retained"):
        service.detail(identifiers[0])
    layer = client.app.nsap.local_adapter.clientPeer
    session = {
        "app": client.app,
        "config": client.config,
        "evidence_adapter": client.app.nsap.local_adapter,
        "evidence_layer": layer,
        "evidence_socket": object(),
    }
    with pytest.raises(ValueError, match="socket identity"):
        service._guard(session)
    monkeypatch.setattr(inventory, "MAX_REPORT_BYTES", 128 * 1024 + 10)
    limited = await service.read(**options(peer, object_ids=["calendar,1"]))
    assert limited["status"] == "failed" and limited["last_omitted_property"]
    assert not limited["complete"]


@pytest.mark.asyncio
async def test_cancel_retains_completed_array_indexes_and_unrelated_mux_observer(link):
    peer, client, service = link
    original = peer.value

    def stop_after_first(obj, prop, index):
        value = original(obj, prop, index)
        if prop == "weekly-schedule" and index == 1:
            peer.hold_property = "weekly-schedule"
        return value

    peer.value = stop_after_first
    mux = client.app.nsap.local_adapter.clientPeer.multiplexer
    prior = mux.confirmation
    observed = []

    async def observer(packet):
        observed.append(bytes(packet.pduData))
        await prior(packet)

    mux.confirmation = observer
    task = asyncio.create_task(service.read(**options(peer, object_ids=["schedule,1"])))
    try:
        await asyncio.wait_for(peer.entered.wait(), 1)
        service.cancel("schedule_test_operation")
        report = await task
        array = report["objects"][0]["properties"]["weekly-schedule"]
        assert array["status"] == "cancelled" and not array["complete"]
        assert array["count_read"]["value"] == 7
        assert len(array["elements"]) == 1 and array["elements"][0]["status"] == "ok"
        assert len(observed) == len(peer.requests) - 1
        assert mux.confirmation is observer
        verify_hash(report)
    finally:
        mux.confirmation = prior


@pytest.mark.asyncio
async def test_forwarded_reply_cannot_claim_direct_selected_endpoint(link):
    peer, client, service = link
    rogue, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    peer.rogue, peer.rogue_kind = rogue, "forwarded"
    try:
        report = await service.read(**options(peer))
        assert report["complete"] and report["ignored_transport_candidates"] == len(peer.requests)
        assert all(
            row["transport_evidence"]["next_hop"] == peer.endpoint
            for item in report["objects"]
            for row in item["properties"].values()
            if "transport_evidence" in row
        )
        retired(client)
    finally:
        rogue.close()


@pytest.mark.asyncio
async def test_mutable_route_cache_and_unrelated_direct_requests_preserved(link):
    from bacpypes3.pdu import Address
    from bms_tool.bacnet_read import read_property

    direct, client, service = link
    router = await make_peer(routed=True)
    router.hold_property = "description"
    wrong = Address(f"127.0.0.1:{free_udp()}")
    await client.app.nsap.router_info_cache.update_path_info(None, wrong, {3001})
    task = asyncio.create_task(service.read(**options(router, object_ids=["schedule,1"])))
    try:
        await asyncio.wait_for(router.entered.wait(), 1)
        # Another native service on a different endpoint is not hijacked by the
        # selected route's temporary outbound or response-source hooks.
        unrelated = await read_property(
            client.app, Address(direct.endpoint), "device,42", "object-name"
        )
        assert str(unrelated) == "Native device,42"
        await client.app.nsap.router_info_cache.update_path_info(None, wrong, {3001})
        router.release.set()
        report = await task
        assert report["complete"] and not router.errors
        assert (
            report["objects"][0]["properties"]["weekly-schedule"]["elements"][-1][
                "transport_evidence"
            ]["next_hop"]
            == router.endpoint
        )
        retired(client)
    finally:
        router.close()


@pytest.mark.asyncio
async def test_operation_lock_wait_is_bounded_and_no_dispatch(link):
    peer, client, service = link
    service.operation_timeout = 0.05
    await client.lock.acquire()
    try:
        report = await service.read(**options(peer))
        assert report["status"] == "timeout" and report["requests"] == 0
        assert not peer.requests
    finally:
        client.lock.release()
    retired(client)


@pytest.mark.asyncio
async def test_late_cancelled_response_cannot_replace_report_or_next_transaction(link):
    peer, client, service = link
    peer.behavior = "hold"
    task = asyncio.create_task(service.read(**options(peer)))
    await peer.entered.wait()
    service.cancel("schedule_test_operation")
    old = await task
    before = service.detail(old["id"])
    peer.behavior = "normal"
    peer.release.set()
    fresh = await service.read(**options(peer, operation_id="fresh_after_cancel"))
    assert fresh["complete"] and fresh["identity_verified"]
    assert service.detail(old["id"]) == before
    assert len(service.reports) == 2
    verify_hash(old)
    verify_hash(fresh)
    retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configuration", [{"bbmd_address": "127.0.0.1:47808"}, {"transport": "mstp"}]
)
async def test_unsupported_transports_rejected_before_network_dispatch(link, configuration):
    peer, client, service = link
    client.config.update(configuration)
    with pytest.raises(ValueError, match="plain IPv4"):
        await service.read(**options(peer))
    assert not peer.requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,datatype,value",
    [
        (b"\x00", "Null", None),
        (b"\x11", "Boolean", True),
        (b"\x21\x07", "Unsigned", 7),
        (b"\x31\xff", "Integer", -1),
        (b"\x55\x08" + struct.pack(">d", -0.0), "Double", -0.0),
        (b"\x91\x63", "Enumerated", 99),
    ],
)
async def test_native_schedule_any_atomic_choices_not_coerced_to_real(link, raw, datatype, value):
    peer, client, service = link
    original = peer.value

    def replacement(obj, prop, index):
        return raw if prop == "schedule-default" else original(obj, prop, index)

    peer.value = replacement
    report = await service.read(**options(peer, object_ids=["schedule,1"]))
    row = report["objects"][0]["properties"]["schedule-default"]
    assert row["status"] == "ok" and row["value"]["native_datatype"] == datatype
    assert row["value"]["value"] == value
    assert row["encoded_value"]["hex"] == (b"\x3e" + raw + b"\x3f").hex()
    if datatype == "Double":
        assert math.copysign(1, row["value"]["value"]) == -1
    verify_hash(report)
    retired(client)
