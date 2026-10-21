"""Authored native multi-channel records, real UDP and literal routed peers."""

import asyncio
import copy
import json
import time
from datetime import datetime

import pytest
from bacpypes3.apdu import ReadRangeACK
from bacpypes3.app import Application
from bacpypes3.basetypes import (
    DateTime,
    DeviceObjectPropertyReference,
    ErrorType,
    LogData,
    LogDataLogData,
    LogMultipleRecord,
)
from bacpypes3.constructeddata import Any, ListOf
from bacpypes3.errors import ExecutionError
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.object import TrendLogMultipleObject
from bms_tool.bacnet_history_multiple import MultipleHistory
from bms_tool.bacnet_read import close_application
from bms_tool.connections import Bacnet
from bms_tool.storage import Store

from .test_connections import free_udp


def record(number=1, *, kind="logData", stamp=None, values=None):
    datum = (
        [LogDataLogData(realValue=number + 0.25), LogDataLogData(booleanValue=number % 2)]
        if kind == "logData" and values is None
        else values
    )
    return LogMultipleRecord(
        timestamp=stamp or DateTime(datetime(2026, 10, 21, 12, 0)), logData=LogData(**{kind: datum})
    )


class MultipleDevice(Application):
    def setup(self):
        self.history = TrendLogMultipleObject(
            objectIdentifier=("trend-log-multiple", 1),
            objectName="Authored multi-channel log",
            statusFlags=[0, 0, 0, 0],
            eventState="normal",
            enable=True,
            logInterval=100,
            logDeviceObjectProperty=[
                DeviceObjectPropertyReference(
                    objectIdentifier=("analog-input", 1), propertyIdentifier="present-value"
                ),
                DeviceObjectPropertyReference(
                    objectIdentifier=("binary-input", 2),
                    propertyIdentifier="present-value",
                    deviceIdentifier=("device", 42),
                ),
            ],
            loggingType="polled",
            stopWhenFull=False,
            bufferSize=1000,
            logBuffer=[record(index) for index in range(1, 6)],
            recordCount=5,
            totalRecordCount=104,
        )
        self.add_object(self.history)
        self.sequences = [100, 101, 102, 103, 104]
        self.requests = []
        self.page_limit = 2
        self.mutation = None
        self.behavior = "normal"
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def do_ReadRangeRequest(self, request):
        self.requests.append(request)
        self.entered.set()
        if self.behavior == "hold" or (self.behavior == "hold-second" and len(self.requests) > 1):
            await self.release.wait()
            return
        if self.behavior == "reject":
            raise ExecutionError(
                errorClass="services", errorCode="optionalFunctionalityNotSupported"
            )
        if request.objectIdentifier != self.history.objectIdentifier:
            raise ExecutionError(errorClass="object", errorCode="unknownObject")
        selection = request.range
        records = list(self.history.logBuffer)
        if selection.byPosition is not None:
            start = int(selection.byPosition.referenceIndex) - 1
            count = int(selection.byPosition.count)
        elif selection.bySequenceNumber is not None:
            anchor = int(selection.bySequenceNumber.referenceSequenceNumber)
            count = int(selection.bySequenceNumber.count)
            window = [(anchor - 1 + offset) % 0xFFFFFFFF + 1 for offset in range(count)]
            matches = [
                (window.index(sequence), index)
                for index, sequence in enumerate(self.sequences)
                if sequence in window
            ]
            if matches:
                consumed, start = min(matches)
                count -= consumed
            else:
                start = len(records)
        else:
            anchor = selection.byTime.referenceTime.datetime
            count = int(selection.byTime.count)
            start = next(
                (index for index, item in enumerate(records) if item.timestamp.datetime >= anchor),
                len(records),
            )
        chosen = records[start : start + min(count, self.page_limit)]
        reply = ReadRangeACK(
            context=request,
            objectIdentifier=self.history.objectIdentifier,
            propertyIdentifier="log-buffer",
            resultFlags=[
                int(start == 0),
                int(start + len(chosen) >= len(records)),
                int(len(chosen) < min(count, max(0, len(records) - start))),
            ],
            itemCount=len(chosen),
            itemData=Any(ListOf(LogMultipleRecord)(chosen)),
            **({"firstSequenceNumber": self.sequences[start]} if chosen else {}),
        )
        if self.mutation:
            self.mutation(reply)
        await self.response(reply)


def device(port):
    server = MultipleDevice.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", 4190102), objectName="Authored multiple log peer"
            ),
            NetworkPortObject(
                f"127.0.0.1:{port}",
                objectIdentifier=("network-port", 1),
                objectName="Multiple loopback",
            ),
        ]
    )
    server.setup()
    return server


def options(address, **updates):
    return {
        "address": address,
        "device": "device,4190102",
        "object_id": "trend-log-multiple,1",
        "operation_id": "multi-" + str(time.monotonic_ns()),
        **updates,
    }


def retired(client, app=None):
    app = app or client.app
    assert not app._requests and not app.asap.clientTransactions and not client.lock.locked()
    assert "process_npdu" not in app.nsap.__dict__ and "indication" not in app.nsap.__dict__


@pytest.fixture
async def link(tmp_path):
    port = free_udp()
    server = device(port)
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = MultipleHistory(client, client.store, timeout=0.1, operation_timeout=2, request_gap=0)
    try:
        yield server, client, service, f"127.0.0.1:{port}"
    finally:
        await service.close()
        client.close()
        server.release.set()
        close_application(server)
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_real_native_multiple_records_channel_refs_unknown_quality_and_clock(link):
    server, client, service, address = link
    config, commands = copy.deepcopy(client.config), copy.deepcopy(client.commands)
    report = await service.read(**options(address))
    assert report["complete"] and report["identity_verified"] and not report["errors"], report
    assert [row["sequence"] for row in report["records"]] == [100, 101, 102, 103, 104]
    first = report["records"][0]
    assert first["raw"]["logData"]["type"] == "logData" and len(first["channels"]) == 2
    assert first["channels"][0]["raw"] == {"type": "realValue", "value": 1.25}
    assert first["channels"][1]["raw"] == {"type": "booleanValue", "value": True}
    assert first["channels"][1]["reference"]["raw"]["deviceIdentifier"] == [8, 42]
    assert all(
        row["quality"] == "unknown" and row["source_clock"] is None for row in report["records"]
    )
    assert report["timezone"] is None and report["channel_reference_count"] == 2
    assert len(server.requests) == 3 and service.captures() == []
    assert client.config == config and client.commands == commands
    retired(client)


@pytest.mark.asyncio
async def test_explicit_clock_native_status_failure_null_and_opaque_choices(link):
    server, client, service, address = link
    server.history.logBuffer = [
        record(kind="logStatus", values=[0, 1, 1]),
        record(kind="timeChange", values=-60),
        record(
            values=[
                LogDataLogData(nullValue=()),
                LogDataLogData(
                    failure=ErrorType(errorClass="property", errorCode="unknownProperty")
                ),
            ]
        ),
    ]
    server.sequences = [100, 101, 102]
    result = await service.read(**options(address, device_timezone="America/Los_Angeles"))
    assert result["complete"], result
    assert result["records"][0]["log_status"] == {
        "log_disabled": False,
        "buffer_purged": True,
        "log_interrupted": True,
    }
    assert result["records"][1]["time_change"] == -60
    assert result["records"][2]["channels"][1]["quality"] == "fault"
    assert result["records"][0]["source_clock"] == "2026-10-21T19:00:00.000000+00:00"
    retired(client)


@pytest.mark.asyncio
async def test_capture_roundtrip_restart_and_hash_tampering(link):
    _, client, service, address = link
    report = await service.read(**options(address))
    saved = service.save(report["id"])
    assert saved["records"] == 5
    restored = MultipleHistory(
        client, client.store, timeout=0.1, operation_timeout=2, request_gap=0
    )
    assert restored.capture(report["id"]) == report and restored.captures() == [saved]
    assert service.save(report["id"]) == saved
    path = service.directory / ("capture-" + report["id"] + ".json")
    data = json.loads(path.read_bytes())
    data["report"]["records"][0]["quality"] = "good"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="integrity"):
        restored.capture(report["id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["position", "sequence", "time"])
async def test_actual_native_range_choices(link, mode):
    _, client, service, address = link
    result = await service.read(
        **options(
            address,
            mode=mode,
            **(
                {"reference": 100}
                if mode == "sequence"
                else {
                    "reference_time": "2026-10-21T19:00:00Z",
                    "device_timezone": "America/Los_Angeles",
                }
                if mode == "time"
                else {"reference": 1}
            ),
        )
    )
    assert result["complete"] and len(result["records"]) == 5, result
    retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    ["object", "property", "array", "count", "flags", "invoke", "zero-sequence", "repeat"],
)
async def test_invalid_native_pages_are_not_imported_or_duplicated(link, mutation):
    server, client, service, address = link

    def damage(reply):
        if mutation == "repeat":
            if len(server.requests) > 1:
                reply.firstSequenceNumber = 100
        elif mutation == "object":
            reply.objectIdentifier = ("trend-log", 1)
        elif mutation == "property":
            reply.propertyIdentifier = "present-value"
        elif mutation == "array":
            reply.propertyArrayIndex = 1
        elif mutation == "count":
            reply.itemCount = int(reply.itemCount) + 1
        elif mutation == "flags":
            reply.resultFlags = [1, 1, 1]
        elif mutation == "invoke":
            reply.apduInvokeID = (reply.apduInvokeID + 1) % 256
        else:
            reply.firstSequenceNumber = 0

    server.mutation = damage
    result = await service.read(**options(address))
    assert (
        result["status"] == ("partial" if mutation == "repeat" else "failed")
        and not result["complete"]
    ), result
    assert len(result["records"]) == (2 if mutation == "repeat" else 0)
    assert result["errors"]
    retired(client)


@pytest.mark.asyncio
async def test_uint32_sequence_wrap_and_bounded_continuation(link):
    server, client, service, address = link
    server.sequences = [4294967294, 4294967295, 1, 2, 3]
    result = await service.read(
        **options(address, mode="sequence", reference=4294967294, count=3, page_size=2)
    )
    assert result["status"] == "bounded" and result["truncated"] and not result["complete"], result
    assert [item["sequence"] for item in result["records"]] == [4294967294, 4294967295, 1]
    assert result["next_cursor"] == {"mode": "sequence", "reference": 2}
    resumed = await service.read(**options(address, **result["next_cursor"]))
    assert resumed["complete"] and [item["sequence"] for item in resumed["records"]] == [2, 3]
    retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["explicit", "caller", "interface", "deadline"])
async def test_multiple_cancel_deadline_and_interface_cleanup_preserve_completed_pages(link, kind):
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
        assert result["truncated"] and len(result["records"]) == 2 and not result["complete"], (
            result
        )
        assert (
            result["status"]
            == {"explicit": "cancelled", "interface": "interface_changed", "deadline": "partial"}[
                kind
            ]
        )
        saved = service.save(result["id"])
        assert saved["records"] == 2
    retired(client, app)


@pytest.mark.asyncio
async def test_unresolved_wildcard_clock_and_native_nonfinite_remain_loss_explicit(link):
    server, client, service, address = link
    server.history.logBuffer = [
        record(
            stamp=DateTime(date=(255, 255, 255, 255), time=(255, 255, 255, 255)),
            values=[
                LogDataLogData(realValue=float("nan")),
                LogDataLogData(unsignedValue=4294967295),
            ],
        )
    ]
    server.sequences = [100]
    result = await service.read(**options(address, device_timezone="UTC"))
    assert result["complete"], result
    row = result["records"][0]
    assert row["source_clock"] is None and "wildcard" in row["timestamp_error"]
    assert row["channels"][0]["raw"]["value"] == {"type": "nonfinite-number", "value": "NaN"}
    assert row["channels"][1]["raw"]["value"] == 4294967295
    assert all(item["quality"] == "unknown" for item in row["channels"])
    retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", ["channels", "page-bytes", "report-bytes", "pages"])
async def test_native_multiple_result_bounds(link, bound, monkeypatch):
    import bms_tool.bacnet_history_multiple as module

    server, client, service, address = link
    if bound == "channels":
        server.history.logBuffer = [record(values=[LogDataLogData(realValue=1)] * 33)]
    elif bound == "page-bytes":
        monkeypatch.setattr(module, "MAX_PAGE_BYTES", 1)
    elif bound == "report-bytes":
        monkeypatch.setattr(module, "MAX_BYTES", 65537)
    else:
        monkeypatch.setattr(module, "MAX_PAGES", 1)
    result = await service.read(**options(address))
    assert result["truncated"] and result["errors"], result
    assert len(result["records"]) == (2 if bound == "pages" else 0)
    retired(client)


class MultipleRouter(asyncio.DatagramProtocol):
    """Independent IPv4/NPDU routing peer with an untrusted alternate next hop."""

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
            ReadRangeRequest,
        )
        from bacpypes3.pdu import PDU
        from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned

        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            packet = data[4:]
            assert packet[:7] == b"\x01\x24\x0b\xb9\x01\x07\xff"
            request = APCISequence.decode(APDU.decode(PDU(packet[7:])))
            self.requests.append(type(request).__name__)
            if isinstance(request, ReadPropertyRequest):
                obj, prop = str(request.objectIdentifier), str(request.propertyIdentifier)
                if prop == "object-identifier":
                    value = ObjectIdentifier(
                        ("device", 4190102)
                        if obj == "device,4190102"
                        else ("trend-log-multiple", 1)
                    )
                elif prop == "object-name":
                    value = CharacterString("Authored routed multiple log")
                elif prop == "log-device-object-property":
                    value = (
                        Unsigned(1)
                        if request.propertyArrayIndex == 0
                        else DeviceObjectPropertyReference(
                            objectIdentifier=("analog-input", 1), propertyIdentifier="present-value"
                        )
                    )
                else:
                    from bacpypes3.basetypes import LoggingType

                    value = (
                        LoggingType("polled")
                        if prop == "logging-type"
                        else Unsigned(
                            {
                                "record-count": 1,
                                "total-record-count": 100,
                                "buffer-size": 1000,
                                "log-interval": 100,
                            }[prop]
                        )
                    )
                reply = ReadPropertyACK(
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=request.propertyIdentifier,
                    propertyValue=Any(value),
                    **(
                        {"propertyArrayIndex": request.propertyArrayIndex}
                        if request.propertyArrayIndex is not None
                        else {}
                    ),
                )
                reply.apduService = 12
            else:
                assert isinstance(request, ReadRangeRequest)
                reply = ReadRangeACK(
                    objectIdentifier=("trend-log-multiple", 1),
                    propertyIdentifier="log-buffer",
                    resultFlags=[1, 1, 0],
                    itemCount=1,
                    itemData=Any(
                        ListOf(LogMultipleRecord)(
                            [record(values=[LogDataLogData(realValue=42.25)])]
                        )
                    ),
                    firstSequenceNumber=100,
                )
                reply.apduService = 26
            reply.apduInvokeID, reply.apduSeg, reply.apduMor = request.apduInvokeID, False, False
            payload = b"\x01\x08\x0b\xb9\x01\x07" + bytes(reply.encode().encode().pduData)
            frame = b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload
            self.rogue.sendto(frame, source)
            await asyncio.sleep(0.002)
            if not isinstance(request, ReadRangeRequest) or self.mode == "normal":
                self.transport.sendto(frame, source)
        except Exception as exc:
            self.errors.append(exc)

    def close(self):
        for task in list(self.tasks):
            task.cancel()
        self.transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "rogue-only"])
async def test_real_routed_multiple_log_pins_next_hop_and_rejects_rogue_native_pages(
    tmp_path, mode
):
    from bacpypes3.pdu import Address

    loop = asyncio.get_running_loop()
    rogue, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    _, router = await loop.create_datagram_endpoint(
        lambda: MultipleRouter(rogue, mode), local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = MultipleHistory(client, client.store, timeout=0.1, operation_timeout=2, request_gap=0)
    config = copy.deepcopy(client.config)
    await client.app.nsap.update_router_references(
        None, Address(rogue.get_extra_info("sockname")), [3001]
    )
    try:
        result = await service.read(**options("3001:7", router=router.endpoint, dnet=3001))
        if mode == "normal":
            assert (
                result["complete"] and result["records"][0]["channels"][0]["raw"]["value"] == 42.25
            ), result
            assert result["ignored_router_packets"] >= 10
        else:
            assert (
                result["status"] == "failed"
                and result["identity_verified"]
                and not result["records"]
            ), result
        assert client.config == config
        retired(client)
    finally:
        await service.close()
        client.close()
        router.close()
        rogue.close()
        await asyncio.sleep(0.02)
        assert not router.errors


@pytest.mark.asyncio
async def test_current_reference_count_mismatch_never_assigns_current_refs_to_historical_channels(
    link,
):
    server, client, service, address = link
    server.history.logBuffer = [record(values=[LogDataLogData(realValue=1)])]
    server.sequences = [100]
    result = await service.read(**options(address))
    assert result["complete"], result
    row = result["records"][0]
    assert row["current_reference_count"] == 2 and row["channel_count"] == 1
    assert "current-count-mismatch" in row["reference_alignment"]
    assert row["channels"][0]["reference"] is None
    assert len(result["channel_references"]) == 2
    retired(client)


@pytest.mark.asyncio
async def test_preinvoke_cancellation_never_dispatches_late_native_range(link, monkeypatch):
    server, client, service, address = link
    entered, release = asyncio.Event(), asyncio.Event()
    original = client.app.device_info_cache.get_device_info

    async def held(target):
        if any(
            request.apduService == 26
            for entries in client.app._requests.values()
            for request, _ in entries
        ):
            entered.set()
            await release.wait()
        return await original(target)

    monkeypatch.setattr(client.app.device_info_cache, "get_device_info", held)
    pending = asyncio.create_task(service.read(**options(address)))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        retired(client)
        release.set()
        await asyncio.sleep(0.05)
        assert not server.requests
    finally:
        release.set()
        if not pending.done():
            pending.cancel()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["same-count", "count", "unavailable"])
async def test_reference_recheck_preserves_native_indices_without_assigning_changed_current_points(
    link, change
):
    server, client, service, address = link
    if change == "unavailable":
        original = server.do_ReadPropertyRequest
        checks = 0

        async def read(request):
            nonlocal checks
            if (
                str(request.propertyIdentifier) == "log-device-object-property"
                and request.propertyArrayIndex == 0
            ):
                checks += 1
                if checks > 1:
                    raise ExecutionError(errorClass="property", errorCode="readAccessDenied")
            await original(request)

        server.do_ReadPropertyRequest = read
    else:

        def mutate(_):
            refs = [
                DeviceObjectPropertyReference(
                    objectIdentifier=("analog-input", 99), propertyIdentifier="present-value"
                )
            ]
            if change == "same-count":
                refs.append(
                    DeviceObjectPropertyReference(
                        objectIdentifier=("binary-input", 2), propertyIdentifier="present-value"
                    )
                )
            server.history.logDeviceObjectProperty = refs

        server.mutation = mutate
    result = await service.read(**options(address))
    assert result["complete"] and result["records_complete"], result
    assert result["channel_reference_consistency"] != "unchanged-current-snapshots"
    assert result["warnings"] and len(result["channel_references"]) == 2
    assert all(
        channel["reference"] is None for row in result["records"] for channel in row["channels"]
    )
    assert result["records"][0]["channels"][0]["raw"]["value"] == 1.25
    assert [channel["index"] for channel in result["records"][0]["channels"]] == [1, 2]
    retired(client)


@pytest.mark.asyncio
async def test_unavailable_optional_metadata_does_not_hide_acquired_native_log_values(link):
    server, client, service, address = link
    original = server.do_ReadPropertyRequest

    async def read(request):
        if str(request.propertyIdentifier) in ("object-name", "log-device-object-property"):
            raise ExecutionError(errorClass="property", errorCode="readAccessDenied")
        await original(request)

    server.do_ReadPropertyRequest = read
    result = await service.read(**options(address))
    assert result["complete"] and len(result["records"]) == 5, result
    assert result["metadata"]["object-name"]["status"] == "unavailable"
    assert result["channel_reference_consistency"] == "unavailable"
    assert result["channel_reference_count"] is None
    assert all(
        channel["reference"] is None for row in result["records"] for channel in row["channels"]
    )
    retired(client)


@pytest.mark.parametrize(
    "change",
    [
        {"device": "analog-input,1"},
        {"device": "device,4194303"},
        {"object_id": "trend-log,1"},
        {"reference": 0, "mode": "sequence"},
        {"mode": "time", "reference_time": "2026-10-21T12:00:00Z"},
        {"page_size": 101},
        {"page_size": True},
        {"count": 1001},
        {"device_timezone": "guessed"},
        {"router": "127.0.0.1"},
        {"address": "3001:*", "router": "127.0.0.1", "dnet": 3001},
    ],
)
def test_multiple_requests_require_exact_identity_and_bounded_explicit_clock_choices(change):
    from bms_tool.bacnet_history_multiple import MultipleHistoryRequest

    with pytest.raises(ValueError):
        MultipleHistoryRequest(**(options("127.0.0.1") | change))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["native-reject", "corrupt-datatype"])
async def test_native_multiple_rejection_and_corrupt_log_record_are_visible_failures(link, failure):
    from bacpypes3.primitivedata import Unsigned

    server, client, service, address = link
    if failure == "native-reject":
        server.behavior = "reject"
    else:
        server.mutation = lambda reply: setattr(reply, "itemData", Any(Unsigned(9)))
    result = await service.read(**options(address))
    assert result["status"] == "failed" and result["errors"] and not result["records"], result
    retired(client)


@pytest.mark.asyncio
async def test_native_opaque_channel_value_is_preserved_as_bounded_tags_without_interpretation(
    link,
):
    from bacpypes3.primitivedata import CharacterString

    server, client, service, address = link
    server.history.logBuffer = [
        record(
            values=[
                LogDataLogData(anyValue=Any(CharacterString("Authored opaque value"))),
                LogDataLogData(bitstringValue=[1, 0, 1]),
            ]
        )
    ]
    server.sequences = [100]
    result = await service.read(**options(address))
    assert result["complete"], result
    channels = result["records"][0]["channels"]
    assert channels[0]["raw"]["value"]["type"] == "bacnet-opaque"
    assert channels[0]["raw"]["value"]["sha256"]
    assert channels[1]["raw"] == {"type": "bitstringValue", "value": [1, 0, 1]}
    retired(client)


@pytest.mark.asyncio
async def test_oversized_current_reference_array_preserves_length_without_unbounded_reads(link):
    server, client, service, address = link
    server.history.logDeviceObjectProperty = [server.history.logDeviceObjectProperty[0]] * 33
    result = await service.read(**options(address))
    assert result["complete"] and len(result["records"]) == 5, result
    assert result["channel_reference_length_evidence"]["raw"] == 33
    assert result["channel_reference_count"] is None and not result["channel_references"]
    assert result["warnings"] and result["channel_reference_consistency"] == "unavailable"
    retired(client)


@pytest.mark.asyncio
async def test_uninitialized_current_reference_is_explicit_native_evidence_not_a_valid_point(link):
    server, client, service, address = link
    server.history.logDeviceObjectProperty = [
        DeviceObjectPropertyReference(
            objectIdentifier=("analog-input", 4194303), propertyIdentifier="present-value"
        ),
        server.history.logDeviceObjectProperty[1],
    ]
    result = await service.read(**options(address))
    assert result["complete"], result
    assert result["channel_references"][0]["status"] == "uninitialized"
    assert result["records"][0]["channels"][0]["reference"]["status"] == "uninitialized"
    retired(client)
