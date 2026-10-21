"""Native EventLogRecord peers; test devices/operators are independently authored."""

import asyncio
import base64
import copy
import hashlib
import json
import time

import pytest
from bacpypes3.basetypes import (
    DateTime,
    EventLogRecord,
    EventLogRecordLogDatum,
    EventNotificationParameters,
    NotificationParameters,
    NotificationParametersOutOfRange,
    TimeStamp,
)
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.object import EventLogObject
from bacpypes3.primitivedata import ClosingTag, OpeningTag
from bms_tool.bacnet_event_log import EventLogHistory
from bms_tool.bacnet_read import close_application
from bms_tool.connections import Bacnet
from bms_tool.storage import Store

from .test_bacnet_history_multiple import MultipleDevice, retired
from .test_connections import free_udp


def notification(**updates):
    data = dict(
        processIdentifier=7,
        initiatingDeviceIdentifier=("device", 42),
        eventObjectIdentifier=("analog-input", 1),
        timeStamp=TimeStamp(sequenceNumber=40),
        notificationClass=3,
        priority=80,
        eventType="outOfRange",
        messageText="Authored native notification",
        notifyType="alarm",
        ackRequired=True,
        fromState="normal",
        toState="highLimit",
        eventValues=NotificationParameters(
            outOfRange=NotificationParametersOutOfRange(
                exceedingValue=81.5, statusFlags=[1, 0, 0, 0], deadband=2, exceededLimit=80
            )
        ),
    )
    data.update(updates)
    return EventNotificationParameters(**data)


def record(kind="notification", value=None, stamp=None):
    return EventLogRecord(
        timestamp=stamp or DateTime(date=(126, 10, 21, 3), time=(12, 0, 0, 0)),
        logDatum=EventLogRecordLogDatum(**{kind: value if value is not None else notification()}),
    )


class EventLogDevice(MultipleDevice):
    record_type = EventLogRecord

    def setup(self):
        self.history = EventLogObject(
            objectIdentifier=("event-log", 1),
            objectName="Authored native Event Log",
            statusFlags=[0, 0, 0, 0],
            eventState="normal",
            reliability="no-fault-detected",
            enable=True,
            stopWhenFull=False,
            bufferSize=1000,
            logBuffer=[
                record(),
                record("logStatus", [0, 1, 1]),
                record("timeChange", -60),
                record(value=notification(timeStamp=TimeStamp(time=(8, 9, 10, 11)))),
                record(
                    value=notification(
                        notifyType="ackNotification",
                        ackRequired=None,
                        fromState=None,
                        eventValues=None,
                    )
                ),
            ],
            recordCount=5,
            totalRecordCount=104,
            notificationClass=3,
        )
        self.add_object(self.history)
        self.sequences = [100, 101, 102, 103, 104]
        self.requests = []
        self.page_limit = 2
        self.mutation = None
        self.behavior = "normal"
        self.entered, self.release = asyncio.Event(), asyncio.Event()


def device(port):
    server = EventLogDevice.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", 4190103), objectName="Authored event history peer"
            ),
            NetworkPortObject(
                f"127.0.0.1:{port}",
                objectIdentifier=("network-port", 1),
                objectName="Event history loopback",
            ),
        ]
    )
    server.setup()
    return server


def options(address, **updates):
    return {
        "address": address,
        "device": "device,4190103",
        "object_id": "event-log,1",
        "operation_id": "event-log-" + str(time.monotonic_ns()),
        **updates,
    }


@pytest.fixture
async def link(tmp_path):
    port = free_udp()
    server = device(port)
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = EventLogHistory(client, client.store, timeout=0.1, operation_timeout=2, request_gap=0)
    try:
        yield server, client, service, f"127.0.0.1:{port}"
    finally:
        await service.close()
        client.close()
        server.release.set()
        close_application(server)
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_real_udp_event_notifications_log_status_clock_and_ack_notification_are_native_history(
    link,
):
    server, client, service, address = link
    config, commands = copy.deepcopy(client.config), copy.deepcopy(client.commands)
    report = await service.read(**options(address))
    assert report["complete"] and report["identity_verified"], report
    assert [row["sequence"] for row in report["records"]] == [100, 101, 102, 103, 104]
    first = report["records"][0]
    assert first["source_clock"] is None and first["recorded_at"] == first["read_received_at"]
    note = first["notification"]
    assert note["event_timestamp"]["raw"] == {"type": "sequenceNumber", "value": 40}
    assert note["initiating_device"] == "device,42" and note["event_object"] == "analog-input,1"
    assert (
        note["event_values"]["type"] == "outOfRange"
        and note["event_values"]["value"]["exceedingValue"] == 81.5
    )
    assert note["ack_required"] is True and note["to_state"]["value"] == 3
    assert report["records"][1]["log_status"] == {
        "log_disabled": False,
        "buffer_purged": True,
        "log_interrupted": True,
    }
    assert report["records"][2]["time_change"] == -60
    ack = report["records"][4]["notification"]
    assert (
        ack["notify_type"]["name"] == "ack-notification"
        and ack["ack_required"] is None
        and ack["from_state"] is None
    )
    assert all(row["quality"] == "unknown" for row in report["records"])
    assert report["metadata"]["enable"]["raw"] is True
    assert client.config == config and client.commands == commands and not service.captures()
    assert len(server.requests) == 3
    retired(client)


@pytest.mark.asyncio
async def test_logger_timezone_never_reinterprets_embedded_event_source_timestamp(link):
    server, client, service, address = link
    source = TimeStamp(dateTime=DateTime(date=(125, 1, 6, 1), time=(7, 8, 9, 10)))
    server.history.logBuffer = [record(value=notification(timeStamp=source))]
    server.sequences = [100]
    result = await service.read(**options(address, device_timezone="America/Los_Angeles"))
    assert result["complete"], result
    row = result["records"][0]
    assert row["source_clock"] == "2026-10-21T19:00:00.000000+00:00"
    assert row["notification"]["event_timestamp"]["source_clock_utc"] is None
    assert row["notification"]["event_timestamp"]["raw"]["value"]["date"] == [125, 1, 6, 1]
    retired(client)


@pytest.mark.asyncio
async def test_unknown_numeric_enums_remain_numeric_and_uninterpreted(link):
    server, client, service, address = link
    server.history.logBuffer = [
        record(
            value=notification(
                eventType=64, notifyType=64, fromState=64, toState=65, eventValues=None
            )
        )
    ]
    server.sequences = [100]
    result = await service.read(**options(address))
    assert result["complete"], result
    note = result["records"][0]["notification"]
    assert note["event_type"] == {"value": 64, "name": "64", "known": False}
    assert note["to_state"]["value"] == 65 and not note["notify_type"]["known"]
    assert note["raw"]["fromState"] == 64
    retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [False, True])
async def test_unknown_notification_parameter_choice_is_deferred_with_full_native_tags(
    link, partial
):
    server, client, service, address = link
    captured = []

    def change(reply):
        if partial and len(server.requests) == 1:
            return
        tags = reply.itemData.tagList
        # Keep ReadRangeACK's outer itemData context 5 intact; change only
        # the nested NotificationParameters outOfRange choice.
        for tag in tags[1:-1]:
            if isinstance(tag, (OpeningTag, ClosingTag)) and tag.tag_number == 5:
                tag.tag_number = 99
        captured.append(bytes(tags.encode().pduData))

    server.mutation = change
    result = await service.read(**options(address))
    assert result["status"] == ("partial" if partial else "unsupported_native_records"), result
    assert len(result["records"]) == (2 if partial else 0)
    evidence = result["undecoded_pages"][0]
    assert base64.b64decode(evidence["item_data_tags"]["base64"]) == captured[0]
    assert evidence["item_data_tags"]["sha256"] == hashlib.sha256(captured[0]).hexdigest()
    assert not evidence["item_data_tags"]["truncated"] and not result["complete"]
    assert "Pinned BACpypes3" in result["errors"][0]
    service.save(result["id"])
    assert service.capture(result["id"]) == result
    retired(client)


@pytest.mark.asyncio
async def test_event_log_sealed_capture_restart_and_tamper_checks(link):
    _, client, service, address = link
    result = await service.read(**options(address))
    saved = service.save(result["id"])
    restarted = EventLogHistory(
        client, client.store, timeout=0.1, operation_timeout=2, request_gap=0
    )
    assert restarted.capture(result["id"]) == result and restarted.captures() == [saved]
    path = service.directory / ("capture-" + result["id"] + ".json")
    data = json.loads(path.read_bytes())
    data["report"]["records"][0]["notification"]["priority"] = 0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="integrity"):
        restarted.capture(result["id"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "damage", ["object", "property", "array", "count", "flags", "invoke", "repeat", "reject"]
)
async def test_native_event_log_corruption_rejection_and_stale_pages_do_not_become_records(
    link, damage
):
    server, client, service, address = link

    def mutate(reply):
        if damage == "object":
            reply.objectIdentifier = ("trend-log", 1)
        elif damage == "property":
            reply.propertyIdentifier = "present-value"
        elif damage == "array":
            reply.propertyArrayIndex = 1
        elif damage == "count":
            reply.itemCount = int(reply.itemCount) + 1
        elif damage == "flags":
            reply.resultFlags = [1, 1, 1]
        elif damage == "invoke":
            reply.apduInvokeID = (reply.apduInvokeID + 1) % 256
        elif damage == "repeat" and len(server.requests) > 1:
            reply.firstSequenceNumber = 100

    server.mutation = mutate
    if damage == "reject":
        server.behavior = "reject"
    result = await service.read(**options(address))
    assert result["status"] == ("partial" if damage == "repeat" else "failed"), result
    assert len(result["records"]) == (2 if damage == "repeat" else 0) and result["errors"]
    retired(client)


@pytest.mark.asyncio
async def test_native_event_sequence_wrap_and_explicit_new_range(link):
    server, client, service, address = link
    server.sequences = [4294967294, 4294967295, 1, 2, 3]
    first = await service.read(
        **options(address, mode="sequence", reference=4294967294, count=3, page_size=2)
    )
    assert [row["sequence"] for row in first["records"]] == [4294967294, 4294967295, 1] and first[
        "status"
    ] == "bounded", first
    second = await service.read(**options(address, **first["next_cursor"]))
    assert second["complete"] and [row["sequence"] for row in second["records"]] == [2, 3], second
    retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["explicit", "caller", "interface", "timeout"])
async def test_event_read_cancellation_and_deadline_retire_owned_exchange(link, kind):
    server, client, service, address = link
    server.behavior = "hold-second"
    request = options(address)
    task = asyncio.create_task(service.read(**request))
    while len(server.requests) < 2:
        await asyncio.sleep(0.005)
    app = client.app
    if kind == "caller":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        if kind == "explicit":
            service.cancel(request["operation_id"])
        elif kind == "interface":
            await service.close()
            await client.disconnect()
        result = await task
        assert len(result["records"]) == 2 and not result["complete"], result
        assert (
            result["status"]
            == {"explicit": "cancelled", "interface": "interface_changed", "timeout": "partial"}[
                kind
            ]
        )
        service.save(result["id"])
    retired(client, app)


@pytest.mark.asyncio
async def test_current_logger_configuration_change_does_not_rewrite_historical_notification(link):
    server, client, service, address = link
    server.mutation = lambda _: setattr(server.history, "notificationClass", 77)
    result = await service.read(**options(address))
    assert result["complete"] and result["warnings"], result
    assert (
        result["metadata"]["notification-class"]["raw"] == 3
        and result["current_configuration_recheck"]["notification-class"]["raw"] == 77
    )
    assert result["records"][0]["notification"]["notification_class"] == 3
    assert (
        result["current_configuration_consistency"] == "changed-or-unverifiable-current-snapshots"
    )
    retired(client)


class EventLogRouter(asyncio.DatagramProtocol):
    """Literal NPDU replies independent of the production route helper."""

    def __init__(self, rogue, mode):
        self.rogue, self.mode = rogue, mode
        self.requests, self.errors, self.tasks = [], [], set()

    def connection_made(self, transport):
        self.transport = transport
        host, port = transport.get_extra_info("sockname")
        self.endpoint = f"{host}:{port}"

    def datagram_received(self, data, source):
        task = asyncio.create_task(self.reply(data, source))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def reply(self, data, source):
        import struct

        from bacpypes3.apdu import (
            APDU,
            APCISequence,
            ReadPropertyACK,
            ReadPropertyRequest,
            ReadRangeACK,
            ReadRangeRequest,
        )
        from bacpypes3.basetypes import Reliability, StatusFlags
        from bacpypes3.constructeddata import Any, ListOf
        from bacpypes3.pdu import PDU
        from bacpypes3.primitivedata import Boolean, CharacterString, ObjectIdentifier, Unsigned

        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            payload = data[4:]
            assert payload[:7] == b"\x01\x24\x0b\xb9\x01\x07\xff"
            request = APCISequence.decode(APDU.decode(PDU(payload[7:])))
            self.requests.append(type(request).__name__)
            if isinstance(request, ReadPropertyRequest):
                prop, obj = str(request.propertyIdentifier), str(request.objectIdentifier)
                if prop == "object-identifier":
                    value = ObjectIdentifier(
                        ("device", 42 if self.mode == "wrong-device" else 4190103)
                        if obj == "device,4190103"
                        else ("event-log", 1)
                    )
                elif prop == "object-name":
                    value = CharacterString("Authored routed Event Log")
                elif prop in ("enable", "stop-when-full"):
                    value = Boolean(prop == "enable")
                elif prop == "status-flags":
                    value = StatusFlags([0, 0, 0, 0])
                elif prop == "reliability":
                    value = Reliability("no-fault-detected")
                else:
                    value = Unsigned(
                        {
                            "record-count": 1,
                            "total-record-count": 100,
                            "buffer-size": 1000,
                            "notification-class": 3,
                        }[prop]
                    )
                response = ReadPropertyACK(
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=request.propertyIdentifier,
                    propertyValue=Any(value),
                )
                response.apduService = 12
            else:
                assert isinstance(request, ReadRangeRequest)
                response = ReadRangeACK(
                    objectIdentifier=("event-log", 1),
                    propertyIdentifier="log-buffer",
                    resultFlags=[1, 1, 0],
                    itemCount=1,
                    itemData=Any(ListOf(EventLogRecord)([record()])),
                    firstSequenceNumber=100,
                )
                response.apduService = 26
            response.apduInvokeID, response.apduSeg, response.apduMor = (
                request.apduInvokeID,
                False,
                False,
            )
            npdu = b"\x01\x08\x0b\xb9\x01\x07" + bytes(response.encode().encode().pduData)
            frame = b"\x81\x0a" + struct.pack(">H", len(npdu) + 4) + npdu
            self.rogue.sendto(frame, source)
            await asyncio.sleep(0.002)
            if not isinstance(request, ReadRangeRequest) or self.mode != "rogue-only":
                self.transport.sendto(frame, source)
        except Exception as exc:
            self.errors.append(exc)

    def close(self):
        for task in list(self.tasks):
            task.cancel()
        self.transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "rogue-only", "wrong-device"])
async def test_event_log_literal_routed_peer_source_identity_and_rogue_filter(tmp_path, mode):
    from bacpypes3.pdu import Address

    loop = asyncio.get_running_loop()
    rogue, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    _, router = await loop.create_datagram_endpoint(
        lambda: EventLogRouter(rogue, mode), local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = EventLogHistory(client, client.store, timeout=0.1, operation_timeout=2, request_gap=0)
    original = copy.deepcopy(client.config)
    await client.app.nsap.update_router_references(
        None, Address(rogue.get_extra_info("sockname")), [3001]
    )
    try:
        result = await service.read(**options("3001:7", router=router.endpoint, dnet=3001))
        if mode == "normal":
            assert (
                result["complete"]
                and result["records"][0]["notification"]["event_object"] == "analog-input,1"
            ), result
            assert result["ignored_router_packets"] >= 20
        else:
            assert result["status"] == "failed" and not result["records"], result
            assert result["identity_verified"] == (mode != "wrong-device")
        assert client.config == original
        retired(client)
    finally:
        await service.close()
        client.close()
        router.close()
        rogue.close()
        await asyncio.sleep(0.02)
        assert not router.errors


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["position", "sequence", "time"])
async def test_event_log_native_forward_range_choices_use_logger_clock(link, mode):
    _, client, service, address = link
    parameters = {"mode": mode}
    if mode == "sequence":
        parameters["reference"] = 100
    elif mode == "time":
        parameters.update(reference_time="2026-10-21T12:00:00Z", device_timezone="UTC")
    result = await service.read(**options(address, **parameters))
    assert result["complete"] and len(result["records"]) == 5, result
    retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", ["page-bytes", "report-bytes", "pages"])
async def test_event_log_native_acquisition_bounds_are_visible(link, bound, monkeypatch):
    import bms_tool.bacnet_history_multiple as module

    _, client, service, address = link
    if bound == "page-bytes":
        monkeypatch.setattr(module, "MAX_PAGE_BYTES", 1)
    elif bound == "report-bytes":
        monkeypatch.setattr(module, "MAX_BYTES", 65537)
    else:
        monkeypatch.setattr(module, "MAX_PAGES", 1)
    result = await service.read(**options(address))
    assert result["truncated"] and result["errors"], result
    assert len(result["records"]) == (2 if bound == "pages" else 0)
    retired(client)


@pytest.mark.asyncio
async def test_event_log_wildcard_logger_time_and_nonfinite_clock_change_stay_native(link):
    server, client, service, address = link
    server.history.logBuffer = [
        record(
            "timeChange",
            float("nan"),
            stamp=DateTime(date=(255, 255, 255, 255), time=(255, 255, 255, 255)),
        )
    ]
    server.sequences = [100]
    result = await service.read(**options(address, device_timezone="UTC"))
    assert result["complete"], result
    row = result["records"][0]
    assert row["source_clock"] is None and "wildcard" in row["timestamp_error"]
    assert (
        row["time_change"] == {"type": "nonfinite-number", "value": "NaN"}
        and row["quality"] == "unknown"
    )
    retired(client)


@pytest.mark.asyncio
async def test_decoder_diagnostic_is_bounded_without_losing_native_opaque_evidence(
    link, monkeypatch
):
    import bms_tool.bacnet_event_log as module

    _, client, service, address = link
    original = module.json_value

    def failed(value):
        if isinstance(value, EventLogRecord):
            raise ValueError("Authored decoder failure: " + "x" * 100000)
        return original(value)

    monkeypatch.setattr(module, "json_value", failed)
    result = await service.read(**options(address))
    assert result["status"] == "unsupported_native_records", result
    assert len(result["errors"][0]) < 2400 and "truncated" in result["errors"][0]
    evidence = result["undecoded_pages"][0]
    assert len(evidence["error"]) < 2400 and "SHA-256" in evidence["error"]
    tags = base64.b64decode(evidence["item_data_tags"]["base64"])
    assert hashlib.sha256(tags).hexdigest() == evidence["item_data_tags"]["sha256"]
    assert len(json.dumps(result).encode()) < 2 * 1024 * 1024
    retired(client)


@pytest.mark.asyncio
async def test_oversized_current_logger_metadata_never_becomes_historical_event_configuration(link):
    server, client, service, address = link
    server.history.objectName = "Authored " + ("X" * 5000)
    server.device_object.segmentationSupported = "segmented-both"
    client.app.device_object.segmentationSupported = "segmented-both"
    result = await service.read(**options(address))
    assert result["complete"] and len(result["records"]) == 5, result
    assert result["metadata"]["object-name"]["status"] in ("over_metadata_profile", "unavailable")
    assert (
        result["current_configuration_consistency"] == "changed-or-unverifiable-current-snapshots"
    )
    assert len(json.dumps(result).encode()) < 2 * 1024 * 1024
    retired(client)


@pytest.mark.asyncio
async def test_large_native_opaque_page_is_budgeted_before_base64_expansion(link, monkeypatch):
    import bms_tool.bacnet_history_multiple as module

    server, client, service, address = link
    server.history.logBuffer = [
        record(value=notification(messageText="Authored " + ("N" * 30000))) for _ in range(2)
    ]
    server.sequences = [100, 101]
    server.device_object.segmentationSupported = "segmented-both"
    client.app.device_object.segmentationSupported = "segmented-both"
    client.app.device_object.maxSegmentsAccepted = 64
    client.app.device_object.maxApduLengthAccepted = 1476
    service.timeout = 1.5

    def unknown(reply):
        for tag in reply.itemData.tagList[1:-1]:
            if isinstance(tag, (OpeningTag, ClosingTag)) and tag.tag_number == 5:
                tag.tag_number = 99

    server.mutation = unknown
    monkeypatch.setattr(module, "MAX_BYTES", 65537)
    result = await service.read(**options(address))
    assert result["status"] == "unsupported_native_records", result
    tags = result["undecoded_pages"][0]["item_data_tags"]
    assert tags["bytes"] > 60000 and tags["truncated"]
    assert len(base64.b64decode(tags["base64"])) == 3072
    assert len(json.dumps(result).encode()) < 65537
    service.save(result["id"])
    retired(client)
