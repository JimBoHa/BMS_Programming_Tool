"""Real UDP reviewed AcknowledgeAlarm; every peer and operator is test authored."""

import asyncio
import copy
import sqlite3
import struct
import time

import pytest
from bacpypes3.apdu import (
    APDU,
    AcknowledgeAlarmRequest,
    APCISequence,
    ConfirmedRequestPDU,
    Error,
    GetEventInformationACK,
    GetEventInformationRequest,
    ReadPropertyACK,
    ReadPropertyRequest,
    RejectPDU,
    SimpleAckPDU,
)
from bacpypes3.basetypes import DateTime, TimeStamp
from bacpypes3.constructeddata import Any
from bacpypes3.pdu import PDU, Address
from bacpypes3.primitivedata import ObjectIdentifier
from bms_tool.bacnet_event_ack import EventAcknowledgements, EventAckPreview
from bms_tool.bacnet_events import EventInventory
from bms_tool.bacnet_read import close_application
from bms_tool.bacnet_values import json_value
from bms_tool.connections import Bacnet
from bms_tool.storage import Store

from .test_bacnet_events import EventsRouter, assert_retired, event, events_device, options
from .test_connections import free_udp


def preview_request(report, **updates):
    return {
        "operation_id": "ack-preview-" + str(time.monotonic_ns()),
        "report_id": report["id"],
        "report_sha256": report["evidence_sha256"],
        "object_id": "analog-value,1",
        "transition": "to_offnormal",
        "operator_name": "Authored Operator",
        "process_id": 1,
        "acknowledgement_timezone": "America/Los_Angeles",
        **updates,
    }


def apply_request(plan, **updates):
    return {
        "operation_id": "ack-apply-" + str(time.monotonic_ns()),
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        **updates,
    }


async def configure_ack_peer(server):
    server.ack_mode, server.ack_requests, server.ack_packets = "accept", [], []
    server.ack_entered, server.ack_release = asyncio.Event(), asyncio.Event()
    original_wire = server.asap.confirmation

    async def wire(pdu):
        parsed = APDU.decode(PDU(bytes(pdu.pduData)))
        if isinstance(parsed, ConfirmedRequestPDU) and parsed.apduService == 0:
            server.ack_packets.append(parsed.apduInvokeID)
        await original_wire(pdu)

    async def acknowledge(request):
        assert isinstance(request, AcknowledgeAlarmRequest) and request.apduService == 0
        server.ack_requests.append(json_value(request))
        server.ack_entered.set()
        if server.ack_mode == "hold":
            await server.ack_release.wait()
            return
        if server.ack_mode == "unsupported":
            await server.response(RejectPDU(reason="unrecognizedService", context=request))
            return
        if server.ack_mode == "reject":
            await server.response(
                Error(
                    service_choice=0,
                    errorClass="services",
                    errorCode="invalidTimeStamp",
                    context=request,
                )
            )
            return
        row = server.pages[None][0][0]
        state = int(request.eventStateAcknowledged)
        index = 1 if state == 1 else 2 if state == 0 else 0
        assert str(request.eventObjectIdentifier) == str(row.objectIdentifier)
        assert json_value(request.timeStamp) == json_value(row.eventTimeStamps[index])
        assert int(request.acknowledgingProcessIdentifier) in (0, 1, 4294967295)
        assert str(request.acknowledgmentSource).startswith("BMS Studio / ")
        assert request.timeOfAcknowledgment._choice == "dateTime"
        if server.ack_mode == "wrong-service":
            response = SimpleAckPDU(context=request)
            response.apduService = 15
            await server.response(response)
            return
        row.acknowledgedTransitions[index] = 1
        await server.response(SimpleAckPDU(context=request))

    server.asap.confirmation = wire
    server.do_AcknowledgeAlarmRequest = acknowledge


@pytest.fixture
async def ack_link(tmp_path):
    port = free_udp()
    server = events_device(port, pages={None: ([event()], False)})
    await configure_ack_peer(server)
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    inventory = EventInventory(
        client, client.store, timeout=0.1, operation_timeout=2, request_gap=0
    )
    service = EventAcknowledgements(
        client, client.store, inventory, timeout=0.1, operation_timeout=2, request_gap=0
    )
    address = f"127.0.0.1:{port}"
    report = await inventory.read(**options(address))
    try:
        yield server, client, inventory, service, address, report
    finally:
        await service.close()
        await inventory.close()
        client.close()
        server.release.set()
        server.ack_release.set()
        close_application(server)
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dateTime", "time", "sequenceNumber"])
async def test_review_then_one_native_ack_preserves_each_timestamp_choice_and_source_policy(
    ack_link, kind
):
    server, client, inventory, service, address, old_report = ack_link
    row = server.pages[None][0][0]
    stamp = {
        "dateTime": TimeStamp(dateTime=DateTime(date=(126, 10, 21, 255), time=(8, 9, 10, 11))),
        "time": TimeStamp(time=(8, 9, 10, 11)),
        "sequenceNumber": TimeStamp(sequenceNumber=65535),
    }[kind]
    row.eventTimeStamps[0] = stamp
    report = await inventory.read(**options(address))
    config, commands = copy.deepcopy(client.config), copy.deepcopy(client.commands)
    plan = await service.preview(**preview_request(report, process_id=0))
    assert plan["can_apply"] and plan["status"] == "review_required"
    assert plan["event_timestamp"] == json_value(stamp)
    assert not server.ack_packets
    result = await service.apply(**apply_request(plan))
    assert result["status"] == "accepted" and result["protocol_accepted"]
    assert (
        result["dispatch_started"] and result["may_have_applied"] and result["requires_fresh_query"]
    )
    assert result["native_request"]["timeStamp"] == json_value(stamp)
    assert result["native_request"]["acknowledgingProcessIdentifier"] == 0
    assert result["native_request"]["acknowledgmentSource"] == "BMS Studio / Authored Operator"
    assert result["review"]["operator_identity_policy"].startswith(
        "Operator identity is explicitly user declared"
    )
    assert len(server.ack_packets) == len(server.ack_requests) == 1
    with pytest.raises(ValueError, match="already used"):
        await service.apply(**apply_request(plan))
    assert len(server.ack_packets) == 1
    assert service.receipt(result["id"]) == result
    assert client.config == config and client.commands == commands
    operations = [row["operation"] for row in client.store.audit()]
    assert (
        "bacnet.event_ack.dispatch_intent" in operations and "bacnet.event_ack.result" in operations
    )
    assert_retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("transition,state", [("to_fault", 1), ("to_normal", 0)])
async def test_unique_historical_fault_and_normal_transitions_use_their_own_native_timestamp(
    ack_link, transition, state
):
    server, client, inventory, service, address, _ = ack_link
    row = server.pages[None][0][0]
    row.eventState = "highLimit"
    row.acknowledgedTransitions = [0, 0, 0]
    row.eventTimeStamps = [
        TimeStamp(sequenceNumber=100),
        TimeStamp(sequenceNumber=101),
        TimeStamp(time=(8, 0, 0, 0)),
    ]
    report = await inventory.read(**options(address))
    plan = await service.preview(**preview_request(report, transition=transition))
    assert plan["can_apply"] and plan["event_state_acknowledged"] == state
    result = await service.apply(**apply_request(plan))
    assert (
        result["protocol_accepted"] and result["native_request"]["eventStateAcknowledged"] == state
    )
    assert_retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["state", "timestamp", "acked", "removed"])
async def test_preview_rejects_changed_source_without_native_ack(ack_link, change):
    server, client, _, service, _, report = ack_link
    row = server.pages[None][0][0]
    if change == "state":
        row.eventState = "highLimit"
    elif change == "timestamp":
        row.eventTimeStamps[0] = TimeStamp(sequenceNumber=1)
    elif change == "acked":
        row.acknowledgedTransitions = [1, 1, 1]
    else:
        server.pages = {None: ([], False)}
    plan = await service.preview(**preview_request(report))
    assert not plan["can_apply"] and plan["token"] is None and plan["reasons"]
    assert not server.ack_packets
    assert_retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe",
    ["historical-offnormal", "vendor-state", "wildcard-time", "wildcard-date", "sequence-range"],
)
async def test_unresolvable_state_or_timestamp_remains_visibly_deferred(ack_link, unsafe):
    server, client, inventory, service, address, _ = ack_link
    row = server.pages[None][0][0]
    if unsafe == "historical-offnormal":
        row.eventState = "normal"
    elif unsafe == "vendor-state":
        row.eventState = 64
    elif unsafe == "wildcard-time":
        row.eventTimeStamps[0] = TimeStamp(time=(255, 255, 255, 255))
    elif unsafe == "wildcard-date":
        row.eventTimeStamps[0] = TimeStamp(
            dateTime=DateTime(date=(255, 255, 255, 255), time=(8, 0, 0, 0))
        )
    else:
        row.eventTimeStamps[0] = TimeStamp(sequenceNumber=65536)
    report = await inventory.read(**options(address))
    plan = await service.preview(**preview_request(report))
    assert plan["status"] == "deferred" and not plan["can_apply"] and plan["reasons"]
    assert not server.ack_packets
    assert_retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stale", ["state", "stamp", "acked", "expired", "review-hash", "source-report", "interface"]
)
async def test_apply_token_staleness_never_sends_a_native_ack(ack_link, stale):
    server, client, inventory, service, address, report = ack_link
    plan = await service.preview(**preview_request(report))
    request = apply_request(plan)
    row = server.pages[None][0][0]
    admission_error = stale in ("expired", "review-hash", "source-report", "interface")
    if stale == "state":
        row.eventState = "highLimit"
    elif stale == "stamp":
        row.eventTimeStamps[0] = TimeStamp(sequenceNumber=222)
    elif stale == "acked":
        row.acknowledgedTransitions = [1, 1, 1]
    elif stale == "expired":
        service._plans[plan["token"]]["created"] -= 31
    elif stale == "review-hash":
        request["review_sha256"] = "0" * 64
    elif stale == "source-report":
        await inventory.read(**options(address))
    else:
        await client.connect(f"127.0.0.1:{free_udp()}")
    if admission_error:
        with pytest.raises(ValueError):
            await service.apply(**request)
    else:
        result = await service.apply(**request)
        assert result["status"] == "not_sent" and not result["may_have_applied"]
    assert not server.ack_packets
    assert_retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected",
    [
        ("reject", "rejected"),
        ("unsupported", "rejected"),
        ("hold", "unknown"),
        ("wrong-service", "unknown"),
    ],
)
async def test_native_reject_and_uncertain_post_dispatch_outcomes_are_not_automatic_retries(
    ack_link, mode, expected
):
    server, client, _, service, _, report = ack_link
    plan = await service.preview(**preview_request(report))
    server.ack_mode = mode
    client.app.device_object.apduTimeout = 20
    client.app.device_object.numberOfApduRetries = 4
    result = await service.apply(**apply_request(plan))
    assert result["status"] == expected and not result["protocol_accepted"]
    assert result["may_have_applied"] == (expected == "unknown")
    assert result["automatic_retries"] is False
    if mode in ("reject", "unsupported"):
        assert result["response"]["validated_rejection"]
        if mode == "reject":
            assert result["response"]["native_error"]["errorCode"] == 14
        else:
            assert result["response"]["reject_reason"] == 9
    await asyncio.sleep(0.15)
    assert len(server.ack_packets) == 1
    assert client.app.device_object.numberOfApduRetries == 4
    assert client.app.device_object.apduTimeout == 20
    assert_retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["freshness", "dispatched", "caller", "interface"])
async def test_cancellation_preserves_ambiguous_receipt_and_retires_only_owned_transaction(
    ack_link, phase
):
    server, client, _, service, _, report = ack_link
    plan = await service.preview(**preview_request(report))
    request = apply_request(plan)
    if phase == "freshness":
        server.behavior = "hold"
        server.entered.clear()
    else:
        server.ack_mode = "hold"
    pending = asyncio.create_task(service.apply(**request))
    await asyncio.wait_for(
        (server.entered if phase == "freshness" else server.ack_entered).wait(), 2
    )
    app = client.app
    if phase == "caller":
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        result = next(reversed(service._receipts.values()))
    elif phase == "interface":
        await service.close()
        await client.disconnect()
        result = await pending
    else:
        service.cancel(request["operation_id"])
        result = await pending
    assert result["may_have_applied"] == (phase != "freshness")
    assert result["status"] == ("cancelled" if phase == "freshness" else "unknown")
    assert len(server.ack_packets) == (0 if phase == "freshness" else 1)
    assert_retired(client, app)


@pytest.mark.asyncio
async def test_locked_audit_blocks_dispatch_with_a_short_bound_and_retains_not_sent_receipt(
    ack_link,
):
    server, client, _, service, _, report = ack_link
    plan = await service.preview(**preview_request(report))
    locked = sqlite3.connect(client.store.db)
    locked.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    try:
        result = await service.apply(**apply_request(plan))
        assert result["status"] == "not_sent" and not result["dispatch_started"]
        assert result["audit_error"] and not result["may_have_applied"]
        assert time.monotonic() - started < 2
        assert not server.ack_packets
        assert_retired(client)
    finally:
        locked.rollback()
        locked.close()


@pytest.mark.parametrize(
    "change",
    [
        {"operator_name": " "},
        {"operator_name": "Name\nInjected"},
        {"operator_name": "A\u202eB"},
        {"operator_name": "é" * 30},
        {"process_id": True},
        {"process_id": -1},
        {"acknowledgement_timezone": "guessed"},
        {"object_id": "device,4194303"},
    ],
)
def test_explicit_operator_clock_and_identity_policy_rejects_ambiguous_inputs(change):
    report = {"id": "0" * 32, "evidence_sha256": "0" * 64}
    with pytest.raises(ValueError):
        EventAckPreview(**preview_request(report, **change))


class AckRouter(EventsRouter):
    """Independent literal NPDU peer, including rogue next-hop ACK injection."""

    def __init__(self, rogue, mode):
        super().__init__(rogue)
        self.mode, self.row, self.ack_requests = mode, event(), []

    async def reply(self, data, source):
        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            packet = data[4:]
            assert packet[:7] == b"\x01\x24\x0b\xb9\x01\x07\xff"
            request = APCISequence.decode(APDU.decode(PDU(packet[7:])))
            self.requests.append(type(request).__name__)
            if isinstance(request, ReadPropertyRequest):
                reply = ReadPropertyACK(
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=request.propertyIdentifier,
                    propertyValue=Any(ObjectIdentifier(("device", 4190096))),
                )
                reply.apduService = 12
            elif isinstance(request, GetEventInformationRequest):
                reply = GetEventInformationACK(listOfEventSummaries=[self.row], moreEvents=False)
                reply.apduService = 29
            else:
                assert isinstance(request, AcknowledgeAlarmRequest)
                assert str(request.eventObjectIdentifier) == "analog-value,1"
                assert json_value(request.timeStamp) == json_value(self.row.eventTimeStamps[0])
                assert int(request.eventStateAcknowledged) == 2
                self.ack_requests.append(json_value(request))
                reply = SimpleAckPDU(service_choice=0)
            reply.apduInvokeID, reply.apduSeg, reply.apduMor = request.apduInvokeID, False, False
            encoded = reply.encode()
            if not isinstance(reply, SimpleAckPDU):
                encoded = encoded.encode()
            payload = b"\x01\x08\x0b\xb9\x01\x07" + bytes(encoded.pduData)
            frame = b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload
            self.rogue.sendto(frame, source)
            await asyncio.sleep(0.005)
            if not isinstance(request, AcknowledgeAlarmRequest) or self.mode == "accept":
                self.transport.sendto(frame, source)
        except Exception as exc:
            self.errors.append(exc)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["accept", "rogue-only"])
async def test_routed_acknowledgement_exact_peer_and_native_timestamp(tmp_path, mode):
    loop = asyncio.get_running_loop()
    rogue, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    _, router = await loop.create_datagram_endpoint(
        lambda: AckRouter(rogue, mode), local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path))
    inventory = EventInventory(
        client, client.store, timeout=0.1, operation_timeout=2, request_gap=0
    )
    service = EventAcknowledgements(
        client, client.store, inventory, timeout=0.1, operation_timeout=2, request_gap=0
    )
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        saved = copy.deepcopy(client.config)
        await client.app.nsap.update_router_references(
            None, Address(rogue.get_extra_info("sockname")), [3001]
        )
        report = await inventory.read(**options("3001:7", router=router.endpoint, dnet=3001))
        plan = await service.preview(**preview_request(report))
        assert plan["can_apply"], plan
        result = await service.apply(**apply_request(plan))
        assert result["status"] == ("accepted" if mode == "accept" else "unknown"), result
        assert result["may_have_applied"] and len(router.ack_requests) == 1
        assert result["target"]["router"] == router.endpoint
        assert client.config == saved
        assert_retired(client)
    finally:
        await service.close()
        await inventory.close()
        client.close()
        router.close()
        rogue.close()
        await asyncio.sleep(0.02)
        assert not router.errors


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "behavior", ["unsupported", "unsupported-error", "wrong-ack", "wrong-error-service", "hold"]
)
async def test_preview_native_service_failure_is_visible_and_never_acknowledges(ack_link, behavior):
    server, client, _, service, _, report = ack_link
    server.behavior = behavior
    plan = await service.preview(**preview_request(report))
    assert not plan["can_apply"] and plan["status"] == "deferred"
    assert plan["token"] is None and plan["reasons"]
    assert not server.ack_packets
    assert_retired(client)


@pytest.mark.asyncio
async def test_preinvoke_ack_cancellation_cannot_send_later(ack_link, monkeypatch):
    server, client, _, service, _, report = ack_link
    plan = await service.preview(**preview_request(report))
    original = client.app.device_info_cache.get_device_info
    entered, release = asyncio.Event(), asyncio.Event()

    async def held(target):
        if any(
            request.apduService == 0
            for requests in client.app._requests.values()
            for request, _ in requests
        ):
            entered.set()
            await release.wait()
        return await original(target)

    monkeypatch.setattr(client.app.device_info_cache, "get_device_info", held)
    task = asyncio.create_task(service.apply(**apply_request(plan)))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert_retired(client)
        release.set()
        await asyncio.sleep(0.05)
        assert not server.ack_packets
        assert list(service._receipts.values())[-1]["status"] == "cancelled"
    finally:
        release.set()
        if not task.done():
            task.cancel()
