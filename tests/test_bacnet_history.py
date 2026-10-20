"""Actual UDP ReadRange exchanges against an independently authored Trend Log device."""

import asyncio
import fcntl
import json
import os
import socket
import threading
import time
from datetime import UTC, datetime

import pytest
from bacpypes3.apdu import APDU, ConfirmedRequestPDU, ReadRangeACK
from bacpypes3.app import Application
from bacpypes3.basetypes import DateTime, ErrorType, LogRecord, LogRecordLogDatum
from bacpypes3.constructeddata import Any, ListOf
from bacpypes3.errors import ExecutionError
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.object import TrendLogObject
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import CharacterString, TagClass
from bacpypes3.vlan import VirtualNetwork
from bms_tool.bacnet_history import BacnetHistory, BacnetHistoryRequest
from bms_tool.bacnet_read import close_application
from bms_tool.connections import Bacnet
from bms_tool.storage import Store


def port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def log(value=12.5, *, kind="realValue", timestamp=None, flags=(0, 0, 0, 0)):
    return LogRecord(
        timestamp=DateTime(timestamp or datetime(2026, 1, 5, 12, 0)),
        logDatum=LogRecordLogDatum(**{kind: value}),
        **({"statusFlags": list(flags)} if flags is not None else {}),
    )


class HistoryDevice(Application):
    """Uses real TrendLogObject and BACpypes codec; owns independent range selection."""

    def setup(self, records):
        self.history = TrendLogObject(
            objectIdentifier=("trend-log", 1),
            objectName="Isolated history",
            enable=True,
            stopWhenFull=False,
            bufferSize=1000,
            logBuffer=records,
            recordCount=len(records),
            totalRecordCount=100 + len(records) - 1,
            loggingType="polled",
            statusFlags=[0, 0, 0, 0],
            reliability="no-fault-detected",
        )
        self.add_object(self.history)
        self.sequences = [100 + index for index in range(len(records))]
        self.requests = []
        self.page_limit = 2
        self.omit_sequence = False
        self.mutation = None
        self.drop_after = None
        self.callback = None

    async def do_ReadRangeRequest(self, request):
        self.requests.append(request)
        if self.drop_after is not None and len(self.requests) > self.drop_after:
            return
        if request.objectIdentifier != self.history.objectIdentifier:
            raise ExecutionError(errorClass="object", errorCode="unknownObject")
        if str(request.propertyIdentifier) != "log-buffer":
            raise ExecutionError(errorClass="property", errorCode="unknownProperty")
        selection = request.range
        records = list(self.history.logBuffer)
        if selection.byPosition is not None:
            start = int(selection.byPosition.referenceIndex) - 1
            count = int(selection.byPosition.count)
        elif selection.bySequenceNumber is not None:
            anchor = int(selection.bySequenceNumber.referenceSequenceNumber)
            count = int(selection.bySequenceNumber.count)
            window = [anchor]
            for _ in range(count - 1):
                previous = window[-1]
                window.append(1 if previous == 0xFFFFFFFF else previous + 1)
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
                (i for i, record in enumerate(records) if record.timestamp.datetime >= anchor),
                len(records),
            )
        chosen = records[start : start + min(count, self.page_limit)]
        available_requested = min(count, max(0, len(records) - start))
        first = self.sequences[start] if chosen else None
        response = ReadRangeACK(
            context=request,
            objectIdentifier=self.history.objectIdentifier,
            propertyIdentifier="log-buffer",
            resultFlags=[
                int(start == 0),
                int(start + len(chosen) >= len(records)),
                int(len(chosen) < available_requested),
            ],
            itemCount=len(chosen),
            itemData=Any(ListOf(LogRecord)(chosen)),
            **(
                {"firstSequenceNumber": first}
                if first is not None and not self.omit_sequence
                else {}
            ),
        )
        if self.mutation:
            self.mutation(response)
        await self.response(response)
        if self.callback:
            self.callback()


@pytest.fixture
async def link(tmp_path):
    remote = port()
    server = HistoryDevice.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", 4190101), objectName="Isolated history device"
            ),
            NetworkPortObject(
                f"127.0.0.1:{remote}",
                objectIdentifier=("network-port", 1),
                objectName="UDP loopback",
            ),
        ]
    )
    server.setup([log(index + 0.25) for index in range(7)])
    connector = Bacnet(Store(tmp_path))
    await connector.connect(f"127.0.0.1:{port()}")
    service = BacnetHistory(connector, tmp_path, timeout=0.1, operation_timeout=2)
    try:
        yield (
            server,
            connector,
            service,
            {
                "address": f"127.0.0.1:{remote}",
                "object_id": "trend-log,1",
                "device_timezone": "America/Los_Angeles",
            },
        )
    finally:
        connector.close()
        server.close()
        await asyncio.sleep(0.02)


async def test_actual_udp_history_pages_flags_sequence_and_distinct_source_receipt_clocks(link):
    server, connector, service, target = link
    report = await service.read(**target, count=100, page_size=3)
    assert report["complete"] and not report["truncated"] and not report["errors"]
    assert [row["sequence"] for row in report["records"]] == list(range(100, 107))
    assert [row["value"] for row in report["records"]] == [i + 0.25 for i in range(7)]
    assert all(row["quality"] == "good" for row in report["records"])
    assert report["records"][0]["source_clock"] == "2026-01-05T20:00:00.000000+00:00"
    assert report["records"][0]["recorded_at"] != report["records"][0]["source_clock"]
    assert report["timezone"]["name"] == "America/Los_Angeles"
    assert report["timezone"].get("zone_file_sha256")
    assert len(server.requests) == 4 and not connector.app.asap.clientTransactions
    assert str(server.requests[0].propertyIdentifier) == "log-buffer"
    assert server.requests[1].range.bySequenceNumber.referenceSequenceNumber == 102
    assert not connector.commands and service.captures() == []


async def test_more_items_false_is_not_end_of_log_when_full_requested_page_returned(link):
    server, _, service, target = link
    server.page_limit = 100
    report = await service.read(**target, mode="sequence", reference=100, page_size=2, count=7)
    assert len(server.requests) == 4
    assert report["pages"][0]["result_flags"] == {
        "first_item": True,
        "last_item": False,
        "more_items": False,
    }
    assert report["complete"] and len(report["records"]) == 7


async def test_empty_range_remains_empty_without_manufacturing_samples(link):
    _, _, service, target = link
    report = await service.read(**target, reference=999)
    assert report["complete"] and not report["records"]
    assert not report["errors"] and report["next_cursor"] is None


async def test_empty_sequence_response_may_carry_zero_metadata_without_inventing_a_record(link):
    server, _, service, target = link
    server.mutation = lambda ack: setattr(ack, "firstSequenceNumber", 0)
    report = await service.read(**target, mode="sequence", reference=999)
    assert report["complete"] and not report["records"] and not report["errors"]


async def test_response_cannot_place_records_outside_the_actual_requested_sequence_window(link):
    server, _, service, target = link
    server.mutation = lambda ack: setattr(ack, "firstSequenceNumber", 101)
    with pytest.raises(ValueError, match="sequence window"):
        await service.read(**target, mode="sequence", reference=100, count=2, page_size=2)


async def test_query_entirely_before_retained_sequence_window_returns_no_unrelated_records(link):
    _, _, service, target = link
    report = await service.read(**target, mode="sequence", reference=1, count=10, page_size=10)
    assert report["complete"] and not report["records"]


async def test_changed_sequence_anchor_preserves_received_page_and_reports_gap(link):
    server, _, service, target = link

    def changed(ack):
        if len(server.requests) == 2:
            ack.firstSequenceNumber = int(ack.firstSequenceNumber) + 1

    server.mutation = changed
    report = await service.read(**target)
    assert report["truncated"] and "sequence gap" in report["errors"][0]
    assert len(server.requests) == 2 and len(report["records"]) == 4
    assert report["next_cursor"] == {"mode": "sequence", "reference": 102}


async def test_requested_sequence_before_retained_buffer_is_disclosed(link):
    _, _, service, target = link
    report = await service.read(**target, mode="sequence", reference=1, page_size=100)
    assert report["warnings"] and report["records"][0]["sequence"] == 100
    assert report["complete"]


async def test_count_bound_and_explicit_sequence_cursor_do_not_claim_full_history(link):
    _, _, service, target = link
    report = await service.read(**target, count=3, page_size=2)
    assert report["truncated"] and not report["complete"]
    assert len(report["records"]) == 3 and report["next_cursor"] == {
        "mode": "sequence",
        "reference": 103,
    }
    continuation = await service.read(**target, **report["next_cursor"], count=4)
    assert [row["sequence"] for row in continuation["records"]] == [103, 104, 105, 106]
    assert continuation["complete"]


async def test_by_position_without_sequence_metadata_stays_explicit_instead_of_guessing(link):
    server, _, service, target = link
    server.omit_sequence = True
    report = await service.read(**target, count=7)
    assert len(report["records"]) == 2 and all(row["sequence"] is None for row in report["records"])
    assert report["truncated"] and "omitted sequence metadata" in report["errors"][0]
    assert report["next_cursor"] == {"mode": "position", "reference": 3}
    assert len(server.requests) == 1


async def test_time_query_converts_operator_utc_reference_into_device_local_wire_time(link):
    server, _, service, target = link
    server.history.logBuffer = [
        log(index, timestamp=datetime(2026, 1, 5, 12, index)) for index in range(7)
    ]
    report = await service.read(
        **target, mode="time", reference_time=datetime(2026, 1, 5, 20, 3, tzinfo=UTC), count=10
    )
    assert [row["value"] for row in report["records"]] == [3, 4, 5, 6]
    assert server.requests[0].range.byTime.referenceTime.datetime == datetime(2026, 1, 5, 12, 3)
    assert report["complete"]


async def test_sequence_wrap_skips_zero_and_record_clock_order_is_not_sorted(link):
    server, _, service, target = link
    server.history.logBuffer = [log(i, timestamp=datetime(2026, 1, 5, 12, 5 - i)) for i in range(4)]
    server.sequences = [0xFFFFFFFE, 0xFFFFFFFF, 1, 2]
    report = await service.read(**target, mode="sequence", reference=0xFFFFFFFE, count=4)
    assert [row["sequence"] for row in report["records"]] == [0xFFFFFFFE, 0xFFFFFFFF, 1, 2]
    assert server.requests[1].range.bySequenceNumber.referenceSequenceNumber == 1
    assert report["records"][0]["source_clock"] > report["records"][1]["source_clock"]


async def test_all_log_record_alternatives_and_quality_preserve_events_without_fake_samples(link):
    server, _, service, target = link
    records = [
        log(True, kind="booleanValue"),
        log(8, kind="enumValue"),
        log(9, kind="unsignedValue"),
        log(-2, kind="signedValue"),
        log([1, 0, 1], kind="bitstringValue"),
        log((), kind="nullValue"),
        log([0, 1, 0], kind="logStatus"),
        log(-3600, kind="timeChange"),
        log(ErrorType(errorClass="property", errorCode="unknownProperty"), kind="failure"),
        log(Any(CharacterString("opaque original")), kind="anyValue"),
        log(float("nan")),
        log(4, flags=None),
        log(5, flags=(0, 1, 0, 0)),
        log(6, flags=(1, 0, 0, 0)),
    ]
    server.history.logBuffer = records
    server.sequences = list(range(100, 100 + len(records)))
    report = await service.read(**target, count=100)
    assert report["complete"], report
    rows = report["records"]
    assert rows[0]["value"] is True and rows[3]["value"] == -2
    assert rows[4]["value"] == [True, False, True] and not rows[4]["sample"]
    assert rows[5]["value"] is None and not rows[5]["sample"]
    assert rows[6]["value"]["buffer_purged"] and not rows[6]["sample"]
    assert rows[7]["value"] == -3600 and not rows[7]["sample"]
    assert rows[8]["failure"]["error_code"] == "unknown-property" and rows[8]["quality"] == "fault"
    assert rows[9]["opaque_base64"] and rows[9]["value"] is None
    assert rows[10]["value"] is None and rows[10]["quality"] == "fault"
    assert rows[11]["quality"] == "unknown" and rows[12]["quality"] == "unreliable"
    assert rows[13]["quality"] == "good"  # alarm state is not a data acquisition fault
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize(
    "kind,value", [("unsignedValue", 2**80), ("signedValue", -(2**80)), ("enumValue", 2**80)]
)
async def test_wire_integer_outside_profile_retains_exact_evidence_without_lossy_json_number(
    link, kind, value
):
    server, _, service, target = link
    server.history.logBuffer = [log(1, kind=kind)]
    server.sequences = [100]

    # Upstream encoders correctly refuse >32-bit values, but decoders accept
    # longer context-tag payloads. Mutate actual encoded tags to test the wire.
    def oversized_integer(ack):
        number = {"unsignedValue": 4, "signedValue": 5, "enumValue": 3}[kind]
        for tag in ack.itemData.tagList:
            if tag.tag_class == TagClass.context and tag.tag_number == number:
                raw = value.to_bytes(11, "big", signed=kind == "signedValue")
                tag.tag_data = raw
                tag.tag_lvt = len(raw)

    server.mutation = oversized_integer
    report = await service.read(**target)
    row = report["records"][0]
    assert row["value"] is None and not row["sample"] and row["quality"] == "fault"
    assert row["exact_integer"] == str(value) and row["integer_value_sha256"]
    assert "32-bit" in row["value_error"]


@pytest.mark.parametrize(
    "stamp,error",
    [(datetime(2026, 11, 1, 1, 30), "Ambiguous"), (datetime(2026, 3, 8, 2, 30), "Nonexistent")],
)
async def test_unresolvable_dst_clock_is_preserved_with_no_invented_utc_timestamp(
    link, stamp, error
):
    server, _, service, target = link
    server.history.logBuffer = [log(timestamp=stamp)]
    server.sequences = [100]
    report = await service.read(**target)
    row = report["records"][0]
    assert row["source_clock"] is None and error in row["timestamp_error"]
    assert not row["sample"] and row["quality"] == "unknown"
    assert row["local_timestamp"]["time"][:2] == [stamp.hour, stamp.minute]
    if error == "Ambiguous":
        first = await service.read(**target, fold=0)
        second = await service.read(**target, fold=1)
        assert first["records"][0]["source_clock"] == "2026-11-01T08:30:00.000000+00:00"
        assert second["records"][0]["source_clock"] == "2026-11-01T09:30:00.000000+00:00"


async def test_wildcard_fields_are_retained_and_unspecified_weekday_alone_is_resolvable(link):
    server, _, service, target = link
    wildcard = log()
    wildcard.timestamp.date = (255, 1, 5, 255)
    weekday = log()
    weekday.timestamp.date = (126, 1, 5, 255)
    server.history.logBuffer = [wildcard, weekday]
    server.sequences = [100, 101]
    report = await service.read(**target)
    assert report["records"][0]["source_clock"] is None
    assert report["records"][0]["local_timestamp"]["date"][0] == 255
    assert report["records"][1]["source_clock"] == "2026-01-05T20:00:00.000000+00:00"


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda ack: setattr(ack, "itemCount", 99), "bounds"),
        (lambda ack: setattr(ack, "itemCount", 1), "record count"),
        (lambda ack: setattr(ack, "objectIdentifier", ("trend-log", 2)), "mismatch"),
        (lambda ack: setattr(ack, "propertyIdentifier", "record-count"), "mismatch"),
        (lambda ack: setattr(ack, "resultFlags", [0, 1, 1]), "both lastItem"),
    ],
)
async def test_malformed_ack_is_rejected_without_fabricating_a_history(link, mutation, expected):
    server, _, service, target = link
    server.mutation = mutation
    with pytest.raises(ValueError, match=expected):
        await service.read(**target, page_size=2)


async def test_missing_sequence_for_sequence_response_and_unknown_object_are_explicit(link):
    server, _, service, target = link
    server.omit_sequence = True
    with pytest.raises(ValueError, match="firstSequenceNumber"):
        await service.read(**target, mode="sequence", reference=100)
    with pytest.raises(ValueError, match="unknown-object"):
        await service.read(**{**target, "object_id": "trend-log,999"})


async def test_partial_timeout_and_config_fault_keep_only_received_records_and_release_lock(link):
    server, connector, service, target = link
    server.drop_after = 1
    report = await service.read(**target)
    assert len(report["records"]) == 2 and report["truncated"] and report["errors"]
    assert not connector.lock.locked() and not connector.app.asap.clientTransactions
    server.drop_after = None
    server.requests = []
    server.callback = lambda: setattr(connector, "config", {"injected": "changed"})
    report = await service.read(**target)
    assert len(report["records"]) == 2 and "interface changed" in report["errors"][0]
    assert not connector.lock.locked()


async def test_cancelling_read_retires_wire_transaction_and_never_starts_background_polling(link):
    server, connector, service, target = link
    server.drop_after = 0
    task = asyncio.create_task(service.read(**target))
    while not server.requests:
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not connector.lock.locked() and not connector.app.asap.clientTransactions
    before = len(server.requests)
    await asyncio.sleep(0.12)
    assert len(server.requests) == before


@pytest.mark.parametrize("exit_method", ["caller", "shutdown", "timeout"])
async def test_history_preinvoke_exit_cannot_dispatch_readrange_after_return(
    link, monkeypatch, exit_method
):
    server, connector, service, target = link
    service.timeout = 0.05 if exit_method == "timeout" else 1.0
    app = connector.app
    entered, release = asyncio.Event(), asyncio.Event()
    original_lookup = app.device_info_cache.get_device_info
    original_wire = server.asap.confirmation
    packets = []

    async def held(address):
        entered.set()
        await release.wait()
        return await original_lookup(address)

    async def observed(pdu):
        packet = APDU.decode(PDU(bytes(pdu.pduData)))
        if isinstance(packet, ConfirmedRequestPDU):
            packets.append(packet.apduService)
        await original_wire(pdu)

    monkeypatch.setattr(app.device_info_cache, "get_device_info", held)
    monkeypatch.setattr(server.asap, "confirmation", observed)
    pending = asyncio.create_task(service.read(**target))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        [transaction] = app.asap.clientTransactions
        assert transaction.invokeID is None
        assert transaction.segmentAPDU.apduInvokeID is not None
        if exit_method == "caller":
            pending.cancel()
        elif exit_method == "shutdown":
            close_application(app)
        if exit_method == "timeout":
            with pytest.raises(ValueError, match="TimeoutError"):
                await pending
        else:
            with pytest.raises(asyncio.CancelledError):
                await pending
        assert not app.asap.clientTransactions and not app._requests
        assert not connector.lock.locked() and not server.requests
        release.set()
        await asyncio.sleep(0.1)
        assert not packets and not server.requests
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass


async def test_connector_lock_wait_has_operation_deadline_without_releasing_another_owner(link):
    server, connector, _, target = link
    service = BacnetHistory(connector, timeout=0.05, operation_timeout=0.1)
    async with connector.lock:
        with pytest.raises(ValueError, match="TimeoutError"):
            await service.read(**target)
        assert connector.lock.locked()
    assert not connector.lock.locked() and not server.requests


async def test_explicit_immutable_capture_survives_restart_and_detects_tampering(link, tmp_path):
    _, connector, service, target = link
    report = await service.read(**target, count=3)
    assert service.captures() == []
    report["records"][0]["value"] = 999  # caller mutation cannot change captured evidence
    saved = service.save(report["id"])
    assert saved["records"] == 3
    assert service.capture(report["id"])["records"][0]["value"] == 0.25
    assert service.save(report["id"]) == saved
    restarted = BacnetHistory(connector, tmp_path)
    assert restarted.captures() == [saved]
    assert restarted.capture(report["id"])["source_kind"] == "device-history"
    path = service.directory / ("capture-" + report["id"] + ".json")
    broken = json.loads(path.read_text())
    broken["report"]["records"][0]["value"] = 88
    path.write_text(json.dumps(broken))
    with pytest.raises(ValueError, match="integrity"):
        restarted.capture(report["id"])
    for identifier in ("../secret", "nope", "A" * 32):
        with pytest.raises(ValueError):
            service.capture(identifier)


async def test_capture_capacity_refuses_without_deleting_existing_evidence(link, monkeypatch):
    import bms_tool.bacnet_history as history

    _, _, service, target = link
    monkeypatch.setattr(history, "MAX_CAPTURES", 1)
    first = await service.read(**target, count=1)
    service.save(first["id"])
    second = await service.read(**target, count=1)
    with pytest.raises(ValueError, match="capacity"):
        service.save(second["id"])
    assert len(service.captures()) == 1 and service.capture(first["id"])


async def test_busy_cross_process_capture_lock_is_bounded_and_does_not_hold_memory_lock(
    link, monkeypatch
):
    import bms_tool.bacnet_history as history

    _, _, service, target = link
    report = await service.read(**target, count=1)
    started_lock = threading.Event()
    real_flock = fcntl.flock

    def watched(fd, operation):
        if operation & fcntl.LOCK_EX:
            started_lock.set()
        return real_flock(fd, operation)

    monkeypatch.setattr(history, "CAPTURE_LOCK_SECONDS", 0.1)
    with (service.directory / ".capture.lock").open("a+b") as held:
        real_flock(held.fileno(), fcntl.LOCK_EX)
        monkeypatch.setattr(history.fcntl, "flock", watched)
        saving = asyncio.create_task(asyncio.to_thread(service.save, report["id"]))
        try:
            assert await asyncio.to_thread(started_lock.wait, 0.5)
            acquired = service._lock.acquire(blocking=False)
            assert acquired, (
                "Filesystem wait must not hold the report-cache lock used by the event loop"
            )
            service._lock.release()
            before = time.monotonic()
            with pytest.raises(ValueError, match="storage is busy"):
                await asyncio.wait_for(asyncio.shield(saving), 0.5)
            assert time.monotonic() - before < 0.5
        finally:
            real_flock(held.fileno(), fcntl.LOCK_UN)
            await asyncio.gather(saving, return_exceptions=True)


async def test_capture_stale_temporary_file_does_not_block_retry_or_get_overwritten(link):
    _, _, service, target = link
    report = await service.read(**target, count=1)
    stale = service.directory / ("." + report["id"] + ".tmp")
    stale.write_bytes(b"Retained crash evidence")
    assert service.save(report["id"])["id"] == report["id"]
    assert stale.read_bytes() == b"Retained crash evidence"


async def test_capture_fifo_symlink_and_deep_json_fail_promptly_instead_of_blocking(link, tmp_path):
    _, _, service, target = link
    report = await service.read(**target, count=1)
    service.save(report["id"])
    valid = service.directory / ("capture-" + report["id"] + ".json")
    external = tmp_path / "external-capture.json"
    external.write_bytes(valid.read_bytes())
    valid.unlink()
    valid.symlink_to(external)
    with pytest.raises(ValueError, match="symlink"):
        service.capture(report["id"])
    valid.unlink()
    os.mkfifo(valid)
    started = time.monotonic()
    with pytest.raises(ValueError, match="regular file"):
        service.capture(report["id"])
    assert time.monotonic() - started < 0.2
    valid.unlink()
    valid.write_text("[" * 10000 + "0" + "]" * 10000)
    with pytest.raises(ValueError, match="nesting profile"):
        service.capture(report["id"])


async def test_resealed_incomplete_capture_schema_is_rejected_without_keyerror(link):
    import hashlib

    _, _, service, target = link
    report = await service.read(**target, count=1)
    service.save(report["id"])
    path = service.directory / ("capture-" + report["id"] + ".json")
    wrapper = json.loads(path.read_text())
    del wrapper["report"]["received_at"]
    wrapper["sha256"] = hashlib.sha256(
        json.dumps(
            wrapper["report"], sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    path.write_text(json.dumps(wrapper))
    with pytest.raises(ValueError, match="integrity"):
        service.capture(report["id"])


@pytest.mark.parametrize(
    "extra",
    [
        {"object_id": "analog-input,1"},
        {"object_id": "trend-log-multiple,1"},
        {"device_timezone": "Unknown/Zone"},
        {"mode": "time"},
        {"mode": "time", "reference_time": "2026-01-01T00:00:00"},
        {"mode": "time", "reference_time": "2026-01-01T00:00:00.000001Z"},
        {"reference": 0},
        {"count": 0},
        {"count": 1001},
        {"count": True},
        {"page_size": 101},
        {"fold": True},
        {"count": "2"},
    ],
)
def test_strict_bounded_request_validation(extra):
    with pytest.raises(ValueError):
        BacnetHistoryRequest(
            **{
                "address": "127.0.0.1",
                "object_id": "trend-log,1",
                "device_timezone": "UTC",
                **extra,
            }
        )


async def test_read_never_opens_connection_or_accepts_broadcast(tmp_path):
    connector = Bacnet(Store(tmp_path))
    service = BacnetHistory(connector, tmp_path)
    target = {"address": "127.0.0.1", "object_id": "trend-log,1", "device_timezone": "UTC"}
    with pytest.raises(ValueError, match="Connect"):
        await service.read(**target)
    assert connector.app is None and not service.status()["auto_poll"]
    await connector.connect(f"127.0.0.1:{port()}")
    try:
        with pytest.raises(ValueError, match="unicast"):
            await service.read(**{**target, "address": "*"})
    finally:
        connector.close()


async def test_actual_udp_to_virtual_network_router_retrieves_trend_log_history(tmp_path):
    name = "history-route-" + str(port())
    VirtualNetwork(name)
    router_port = port()
    router = Application.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", 4190201), objectName="Isolated history router"
            ),
            NetworkPortObject(
                f"127.0.0.1:{router_port}",
                objectIdentifier=("network-port", 1),
                objectName="IP",
                networkNumber=100,
                networkNumberQuality="configured",
            ),
            NetworkPortObject(
                objectIdentifier=("network-port", 2),
                objectName="Virtual field",
                macAddress=b"\x02",
                networkType="virtual",
                networkInterfaceName=name,
                networkNumber=2201,
                networkNumberQuality="configured",
                protocolLevel="bacnet-application",
            ),
        ]
    )
    field = HistoryDevice.from_object_list(
        [
            DeviceObject(objectIdentifier=("device", 4190202), objectName="Isolated field log"),
            NetworkPortObject(
                objectIdentifier=("network-port", 1),
                objectName="Virtual field",
                macAddress=b"\x04",
                networkType="virtual",
                networkInterfaceName=name,
                protocolLevel="bacnet-application",
            ),
        ]
    )
    field.setup([log(18), log(19), log(20)])
    connector = Bacnet(Store(tmp_path))
    try:
        await connector.connect(f"127.0.0.1:{port()}", router=f"127.0.0.1:{router_port}", dnet=2201)
        report = await BacnetHistory(connector, timeout=0.2).read(
            address="2201:4",
            object_id="trend-log,1",
            device_timezone="UTC",
            mode="sequence",
            reference=100,
        )
        assert report["complete"] and [row["value"] for row in report["records"]] == [18, 19, 20]
        assert report["target"]["address"] == "2201:4" and len(field.requests) == 2
        assert not connector.commands
    finally:
        connector.close()
        field.close()
        router.close()
        await asyncio.sleep(0.02)
