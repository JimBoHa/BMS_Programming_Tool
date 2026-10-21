"""Real loopback UDP EventSummary services and independently framed routed replies."""

import asyncio
import copy
import hashlib
import json
import struct
import time

import pytest
from bacpypes3.apdu import (
    APDU,
    APCISequence,
    Error,
    GetEventInformationACK,
    GetEventInformationRequest,
    ReadPropertyACK,
    ReadPropertyRequest,
    RejectPDU,
    SimpleAckPDU,
)
from bacpypes3.app import Application
from bacpypes3.basetypes import DateTime, GetEventInformationEventSummary, TimeStamp
from bacpypes3.constructeddata import Any
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import PDU, Address
from bacpypes3.primitivedata import ObjectIdentifier
from bms_tool.bacnet_events import EventInventory, EventInventoryRequest
from bms_tool.bacnet_read import close_application
from bms_tool.connections import Bacnet
from bms_tool.storage import Store

from .test_connections import free_udp


def event(number=1, *, state="offnormal", priorities=(80, 90, 100), timestamps=None):
    return GetEventInformationEventSummary(
        objectIdentifier=("analog-value", number),
        eventState=state,
        acknowledgedTransitions=[0, 1, 1],
        eventTimeStamps=timestamps
        or [
            TimeStamp(dateTime=DateTime(date=(126, 10, 21, 3), time=(12, 34, 56, 78))),
            TimeStamp(time=(255, 255, 255, 255)),
            TimeStamp(sequenceNumber=42),
        ],
        notifyType="alarm",
        eventEnable=[1, 1, 1],
        eventPriorities=list(priorities),
    )


class EventsDevice(Application):
    def setup(self, pages=None, behavior="normal"):
        self.pages = (
            pages
            if pages is not None
            else {None: ([event(2)], True), "analog-value,2": ([event(1)], False)}
        )
        self.behavior = behavior
        self.event_requests = []
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def do_GetEventInformationRequest(self, request):
        anchor = (
            None
            if request.lastReceivedObjectIdentifier is None
            else str(request.lastReceivedObjectIdentifier)
        )
        self.event_requests.append(anchor)
        self.entered.set()
        if self.behavior == "hold" or (self.behavior == "hold-second" and anchor is not None):
            await self.release.wait()
            return
        if self.behavior == "unsupported":
            await self.response(RejectPDU(reason="unrecognizedService", context=request))
            return
        if self.behavior == "unsupported-error":
            await self.response(
                Error(
                    service_choice=29,
                    errorClass="services",
                    errorCode="optionalFunctionalityNotSupported",
                    context=request,
                )
            )
            return
        if self.behavior == "wrong-ack":
            await self.response(SimpleAckPDU(context=request))
            return
        if self.behavior == "wrong-error-service":
            response = Error(
                service_choice=29,
                errorClass="services",
                errorCode="optionalFunctionalityNotSupported",
                context=request,
            )
            response.apduService = 12
            await self.response(response)
            return
        values, more = self.pages.get(anchor, ([], False))
        response = GetEventInformationACK(
            listOfEventSummaries=values, moreEvents=more, context=request
        )
        if self.behavior == "wrong-invoke":
            response.apduInvokeID = (request.apduInvokeID + 1) % 256
        await self.response(response)


def events_device(port, **kwargs):
    server = EventsDevice.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", 4190096),
                objectName="Authored event peer",
                vendorIdentifier=5,
                maxApduLengthAccepted=1476,
                segmentationSupported="segmented-both",
            ),
            NetworkPortObject(
                f"127.0.0.1:{port}",
                objectIdentifier=("network-port", 1),
                objectName="Events loopback",
            ),
        ]
    )
    server.setup(**kwargs)
    return server


def options(address, **updates):
    return {
        "address": address,
        "device": "device,4190096",
        "operation_id": "operation-" + str(time.monotonic_ns()),
        **updates,
    }


def continuation(report):
    return {"report_id": report["id"], "cursor": report["next_cursor"]["token"]}


def assert_retired(client, app=None):
    app = app or client.app
    assert not app._requests and not app.asap.clientTransactions
    assert not client.lock.locked()
    assert "process_npdu" not in app.nsap.__dict__ and "indication" not in app.nsap.__dict__


@pytest.fixture
async def events_link(tmp_path):
    port = free_udp()
    server = events_device(port)
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = EventInventory(client, client.store, timeout=0.1, operation_timeout=2, request_gap=0)
    try:
        yield server, client, service, f"127.0.0.1:{port}"
    finally:
        await service.close()
        client.close()
        server.release.set()
        close_application(server)
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_actual_event_pages_preserve_native_states_timestamps_and_cursor_evidence(
    events_link,
):
    server, client, service, address = events_link
    config, commands = copy.deepcopy(client.config), copy.deepcopy(client.commands)
    first = await service.read(**options(address))
    assert first["identity_verified"] and not first["complete"] and first["status"] == "partial"
    assert first["outcome"] == "page_boundary" and len(first["events"]) == 1
    value = first["events"][0]
    assert value["object_id"] == "analog-value,2" and value["event_state"] == {
        "value": 2,
        "name": "offnormal",
    }
    assert value["raw"]["eventState"] == 2 and value["raw"]["acknowledgedTransitions"] == [0, 1, 1]
    assert value["event_timestamps"][0]["raw"] == {
        "type": "dateTime",
        "value": {"date": [126, 10, 21, 3], "time": [12, 34, 56, 78]},
    }
    assert value["event_timestamps"][1]["raw"] == {"type": "time", "value": [255] * 4}
    assert value["event_timestamps"][2]["raw"] == {"type": "sequenceNumber", "value": 42}
    assert all(stamp["source_clock_utc"] is None for stamp in value["event_timestamps"])
    assert value["quality"] == "not-supplied-by-EventSummary" and value["received_at"].endswith(
        "+00:00"
    )
    second = await service.read(**options(address, **continuation(first)))
    assert second["complete"] and second["status"] == "complete" and second["next_cursor"] is None
    assert [row["object_id"] for row in second["events"]] == ["analog-value,2", "analog-value,1"]
    assert server.event_requests == [None, "analog-value,2"]
    assert len(second["device_identity_reads"]) == 2
    assert second["pages"][1]["request_anchor"] == "analog-value,2"
    digest_input = {key: value for key, value in second.items() if key != "evidence_sha256"}
    assert (
        second["evidence_sha256"]
        == hashlib.sha256(
            json.dumps(
                digest_input, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
    )
    assert first["events"] != second["events"]  # Returned pages are independent snapshots.
    assert client.config == config and client.commands == commands
    assert_retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["replay", "target", "device", "route", "expired", "reconnected", "superseded"]
)
async def test_stale_or_changed_continuation_is_refused_before_event_traffic(events_link, bad):
    server, client, service, address = events_link
    first = await service.read(**options(address))
    request = options(address, **continuation(first))
    if bad == "replay":
        await service.read(**request)
    elif bad == "target":
        request["address"] = f"127.0.0.1:{free_udp()}"
    elif bad == "device":
        request["device"] = "device,4190095"
    elif bad == "route":
        request.update(address="3001:7", router=address, dnet=3001)
    elif bad == "expired":
        service._reports[first["id"]]["updated"] -= 301
    elif bad == "reconnected":
        await client.connect(f"127.0.0.1:{free_udp()}")
    elif bad == "superseded":
        await service.read(**options(address))
    count = len(server.event_requests)
    with pytest.raises(ValueError, match="stale|differs|expired|changed|superseded"):
        await service.read(**request)
    assert len(server.event_requests) == count
    assert_retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "behavior,outcome",
    [
        ("unsupported", "unsupported"),
        ("unsupported-error", "unsupported"),
        ("wrong-ack", "protocol_error"),
        ("wrong-error-service", "protocol_error"),
        ("wrong-invoke", "timeout"),
    ],
)
async def test_real_service_rejection_and_acknowledgement_errors_are_visible(
    events_link, behavior, outcome
):
    server, client, service, address = events_link
    server.behavior = behavior
    result = await service.read(**options(address))
    assert result["status"] == outcome and result["outcome"] == outcome and not result["complete"]
    assert not result["events"] and result["errors"] and result["next_cursor"] is None
    assert_retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["repeated", "empty-more", "duplicate-in-page", "priorities", "timestamp-count"]
)
async def test_invalid_or_repeated_event_pages_never_append_stale_summaries(events_link, bad):
    server, client, service, address = events_link
    first = await service.read(**options(address))
    next_event = event(1)
    values, more = [next_event], False
    if bad == "repeated":
        values = [event(2)]
    elif bad == "empty-more":
        values, more = [], True
    elif bad == "duplicate-in-page":
        values = [event(1), event(1)]
    elif bad == "priorities":
        values = [event(1, priorities=(1, 2, 256))]
    elif bad == "timestamp-count":
        values = [event(1, timestamps=[TimeStamp(sequenceNumber=1)])]
    server.pages["analog-value,2"] = values, more
    result = await service.read(**options(address, **continuation(first)))
    assert result["status"] == "partial" and result["outcome"] == "protocol_error"
    assert result["events"] == first["events"] and len(result["pages"]) == 1
    assert result["next_cursor"] is None and not result["complete"]
    assert_retired(client)


@pytest.mark.asyncio
async def test_identity_failure_prevents_event_query_and_no_empty_alarm_claim(events_link):
    server, client, service, address = events_link
    original = server.do_ReadPropertyRequest

    async def changed(request):
        if str(request.propertyIdentifier) == "object-identifier":
            await server.response(
                ReadPropertyACK(
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=request.propertyIdentifier,
                    propertyValue=Any(ObjectIdentifier(("device", 4190095))),
                    context=request,
                )
            )
        else:
            await original(request)

    server.do_ReadPropertyRequest = changed
    result = await service.read(**options(address))
    assert not result["identity_verified"] and not result["complete"]
    assert not server.event_requests and result["errors"]
    assert_retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_kind", ["caller", "explicit", "disconnect", "close"])
async def test_cancellation_and_interface_teardown_retire_held_native_event_exchange(
    events_link, cancel_kind
):
    server, client, service, address = events_link
    server.behavior = "hold"
    request = options(address)
    task = asyncio.create_task(service.read(**request))
    await asyncio.wait_for(server.entered.wait(), 2)
    app = client.app
    if cancel_kind == "caller":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif cancel_kind == "explicit":
        assert service.cancel(request["operation_id"])["cancel_requested"]
        assert (await task)["status"] == "cancelled"
    elif cancel_kind == "disconnect":
        await service.close()
        await client.disconnect()
        assert (await task)["outcome"] == "interface_changed"
    else:
        client.close()
        assert (await task)["outcome"] == "interface_changed"
    assert_retired(client, app)
    assert service.status()["active_operation"] is None


@pytest.mark.asyncio
async def test_completed_pages_survive_timeout_with_a_fresh_one_use_resume_token(events_link):
    server, client, service, address = events_link
    server.behavior = "hold-second"
    result = await service.read(**options(address, pages_per_request=2))
    assert result["status"] == "partial" and result["outcome"] == "timeout"
    assert len(result["events"]) == 1 and result["next_cursor"] is not None
    server.behavior = "normal"
    completed = await service.read(**options(address, **continuation(result)))
    assert completed["complete"] and len(completed["events"]) == 2
    assert completed["errors"][0]["status"] == "timeout"
    assert_retired(client)


@pytest.mark.asyncio
async def test_cancel_before_admission_prevents_later_traffic_and_only_one_acquisition_runs(
    events_link,
):
    server, client, service, address = events_link
    request = options(address)
    assert not service.cancel(request["operation_id"])["cancel_requested"]
    with pytest.raises(ValueError, match="cancelled before admission"):
        await service.read(**request)
    assert not server.event_requests
    server.behavior = "hold"
    task = asyncio.create_task(service.read(**options(address)))
    await asyncio.wait_for(server.entered.wait(), 2)
    with pytest.raises(ValueError, match="already running"):
        await service.read(**options(address))
    await service.close()
    await task
    assert_retired(client)


@pytest.mark.asyncio
async def test_empty_complete_response_and_unrecognized_native_state_are_preserved(events_link):
    server, client, service, address = events_link
    server.pages = {None: ([], False)}
    empty = await service.read(**options(address))
    assert empty["complete"] and empty["events"] == [] and empty["more_events"] is False
    server.pages = {None: ([event(1, state=64)], False)}
    vendor = await service.read(**options(address))
    assert vendor["events"][0]["event_state"]["value"] == 64
    assert vendor["events"][0]["raw"]["eventState"] == 64
    assert_retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", ["page_bytes", "report_bytes", "pages", "attempts", "events"])
async def test_result_resource_limits_keep_completed_pages_explicit_and_bounded(
    events_link, monkeypatch, bound
):
    import bms_tool.bacnet_events as module

    server, client, service, address = events_link
    if bound == "page_bytes":
        monkeypatch.setattr(module, "MAX_PAGE_BYTES", 1)
    elif bound == "report_bytes":
        monkeypatch.setattr(module, "MAX_REPORT_BYTES", 128 * 1024 + 100)
    elif bound == "pages":
        monkeypatch.setattr(module, "MAX_PAGES", 1)
    elif bound == "attempts":
        monkeypatch.setattr(module, "MAX_ATTEMPTS", 1)
    else:
        monkeypatch.setattr(module, "MAX_EVENTS", 2)
        server.pages["analog-value,2"] = [event(1), event(3)], False
    result = await service.read(**options(address, pages_per_request=2 if bound == "events" else 1))
    assert result["outcome"] == "limit_exceeded" and not result["complete"]
    assert result["next_cursor"] is None
    assert len(result["events"]) <= (1 if bound in ("pages", "attempts", "events") else 0)
    assert result["errors"][-1]["status"] == "limit_exceeded"
    assert_retired(client)


@pytest.mark.asyncio
async def test_audit_failure_is_visible_and_preserves_a_valid_report_hash(events_link, monkeypatch):
    _, client, service, address = events_link

    def unavailable(*args):
        raise OSError("Authored audit failure")

    monkeypatch.setattr(service.store, "record", unavailable)
    result = await service.read(**options(address))
    assert result["audit_error"] and result["events"]
    digest_input = {key: value for key, value in result.items() if key != "evidence_sha256"}
    assert (
        result["evidence_sha256"]
        == hashlib.sha256(
            json.dumps(
                digest_input, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
    )
    assert_retired(client)


@pytest.mark.asyncio
async def test_cancelled_preinvoke_event_dispatch_cannot_transmit_after_release(
    events_link, monkeypatch
):
    server, client, service, address = events_link
    entered, release = asyncio.Event(), asyncio.Event()
    original = client.app.device_info_cache.get_device_info

    async def held(target):
        if any(
            request.apduService == 29
            for requests in client.app._requests.values()
            for request, _ in requests
        ):
            entered.set()
            await release.wait()
        return await original(target)

    monkeypatch.setattr(client.app.device_info_cache, "get_device_info", held)
    task = asyncio.create_task(service.read(**options(address)))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert_retired(client)
        release.set()
        await asyncio.sleep(0.05)
        assert not server.event_requests
    finally:
        release.set()
        if not task.done():
            task.cancel()


class EventsRouter(asyncio.DatagramProtocol):
    """Literal IPv4/NPDU router independent of the client service's path helper."""

    def __init__(self, rogue):
        self.rogue, self.errors, self.requests, self.tasks = rogue, [], [], set()

    def connection_made(self, transport):
        self.transport = transport
        host, port = transport.get_extra_info("sockname")
        self.endpoint = f"{host}:{port}"

    def datagram_received(self, data, source):
        task = asyncio.create_task(self.reply(data, source))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def reply(self, data, source):
        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            packet = data[4:]
            assert packet[:2] == b"\x01\x24"
            assert packet[2:6] == b"\x0b\xb9\x01\x07" and packet[6] == 255
            request = APCISequence.decode(APDU.decode(PDU(packet[7:])))
            self.requests.append(type(request).__name__)
            if isinstance(request, ReadPropertyRequest):
                assert str(request.objectIdentifier) == "device,4190096"
                assert str(request.propertyIdentifier) == "object-identifier"
                reply = ReadPropertyACK(
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=request.propertyIdentifier,
                    propertyValue=Any(ObjectIdentifier(("device", 4190096))),
                )
                reply.apduService = 12
            else:
                assert isinstance(request, GetEventInformationRequest)
                reply = GetEventInformationACK(listOfEventSummaries=[event()], moreEvents=False)
                assert request.apduService == 29  # APDU choice; ServicesSupported bit is 39.
                reply.apduService = 29
            reply.apduInvokeID, reply.apduSeg, reply.apduMor = request.apduInvokeID, False, False
            payload = b"\x01\x08\x0b\xb9\x01\x07" + bytes(reply.encode().encode().pduData)
            frame = b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload
            self.rogue.sendto(frame, source)
            await asyncio.sleep(0.005)
            self.transport.sendto(frame, source)
        except Exception as exc:
            self.errors.append(exc)

    def close(self):
        for task in list(self.tasks):
            task.cancel()
        self.transport.close()


@pytest.mark.asyncio
async def test_routed_event_query_pins_next_hop_and_restores_source_hooks_without_config_change(
    tmp_path,
):
    loop = asyncio.get_running_loop()
    rogue, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    _, router = await loop.create_datagram_endpoint(
        lambda: EventsRouter(rogue), local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        saved_config = copy.deepcopy(client.config)
        await client.app.nsap.update_router_references(
            None, Address(rogue.get_extra_info("sockname")), [3001]
        )
        service = EventInventory(
            client, client.store, timeout=0.2, operation_timeout=2, request_gap=0
        )
        result = await service.read(**options("3001:7", router=router.endpoint, dnet=3001))
        assert result["identity_verified"] and result["complete"], result
        assert result["ignored_router_packets"] == 2
        assert result["events"][0]["object_id"] == "analog-value,1"
        assert result["target"]["router"] == router.endpoint and result["target"]["dnet"] == 3001
        assert client.config == saved_config
        assert router.requests == ["ReadPropertyRequest", "GetEventInformationRequest"]
        assert_retired(client)
    finally:
        client.close()
        router.close()
        rogue.close()
        await asyncio.sleep(0.02)
        assert not router.errors


@pytest.mark.parametrize(
    "change",
    [
        {"address": "localhost"},
        {"device": "device,4194303"},
        {"device": "analog-value,1"},
        {"address": "3001:*", "router": "127.0.0.1", "dnet": 3001},
        {"router": "127.0.0.1"},
        {"pages_per_request": 6},
        {"pages_per_request": True},
        {"cursor": "a" * 32},
        {"report_id": "0" * 32},
        {"operation_id": "bad id"},
    ],
)
def test_event_request_requires_exact_targets_and_bounded_continuation(change):
    with pytest.raises(ValueError):
        EventInventoryRequest(**(options("127.0.0.1") | change))
