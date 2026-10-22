"""Literal UDP Schedule write peer: no client encoder is an expected-value oracle."""

import asyncio
import copy
import hashlib
import json
import sqlite3
import struct
import time

import pytest
from bacpypes3.errors import DecodingError, InvalidTag
from bms_tool.connections import Bacnet
from bms_tool.native_schedule_library import NativeScheduleLibrary, encoded
from bms_tool.native_schedule_wire import response_header
from bms_tool.native_schedule_write import NativeWeeklyDayWrites, WeeklyWriteJournal, seal
from bms_tool.schedule_inventory import ScheduleInventory
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_schedule_inventory import SchedulePeer, options, unsigned


class WeeklyPeer(SchedulePeer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.days = [b"\x0e\xb4\x08\x00\x00\x00\x44\x80\x00\x00\x00\x0f"] * 7
        self.maximum, self.mode = 480, "accept"
        self.writes, self.write_packets = [], []
        self.write_entered = asyncio.Event()
        self.overrides = {}
        self.rogue_transport = None
        self.hold_read = None

    def value(self, obj, prop, index):
        if (str(obj), prop, index) in self.overrides:
            return self.overrides[str(obj), prop, index]
        if prop == "max-apdu-length-accepted":
            return unsigned(self.maximum)
        if prop == "weekly-schedule" and index:
            return self.days[index - 1]
        return super().value(obj, prop, index)

    async def reply(self, data, source):
        offset = 11 if self.routed else 6
        payload = data[offset:]
        if len(payload) < 4 or payload[3] != 15:
            if self.hold_read and len(payload) >= 4 and payload[3] == 12:
                from bacpypes3.apdu import APDU, APCISequence
                from bacpypes3.pdu import PDU

                request = APCISequence.decode(APDU.decode(PDU(payload)))
                if (str(request.propertyIdentifier), request.propertyArrayIndex) == self.hold_read:
                    self.entered.set()
                    await self.release.wait()
            return await super().reply(data, source)
        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            assert payload[0] in (0, 2)  # unsegmented; no segmented request
            invoke, body = payload[2], payload[4:]
            # Independently authored object/property/index/context bytes. No
            # WritePropertyRequest decoder determines what the test expects.
            assert body[:8] == bytes.fromhex("0c04400001197b29")
            day = body[8]
            assert 1 <= day <= 7 and body[9] == 0x3E and body[-1] == 0x3F
            daily = body[10:-1]
            assert daily[:1] == b"\x0e" and daily[-1:] == b"\x0f"
            self.write_packets.append(bytes(data))
            self.writes.append((day, daily))
            self.write_entered.set()
            if self.mode in ("hold", "no_apply_drop"):
                return
            if self.mode not in (
                "reject",
                "server_abort",
                "client_abort",
                "wrong_service",
                "wrong_invoke",
                "trailing",
            ):
                self.days[day - 1] = daily
            if self.mode == "partial_error":
                self.days[day % 7] = b"\x0e\x0f"
            if self.mode == "normalize":
                self.days[day - 1] = b"\x0e\x0f"
            if self.mode == "unavailable":
                self.hold_property = "weekly-schedule"
            if self.mode == "partial_readback":
                self.hold_read = ("weekly-schedule", 4)
            if self.mode == "drop":
                return
            apdu = {
                "error": bytes([0x50, invoke, 15]) + b"\x91\x02\x91\x20",
                "unknown_error": bytes([0x50, invoke, 15]) + b"\x91\xff\x92\xff\xff",
                "partial_error": bytes([0x50, invoke, 15]) + b"\x91\x02\x91\x20",
                "reject": bytes([0x60, invoke, 9]),
                "server_abort": bytes([0x71, invoke, 1]),
                "client_abort": bytes([0x70, invoke, 1]),
                "wrong_service": bytes([0x20, invoke, 12]),
                "wrong_invoke": bytes([0x20, (invoke + 17) % 256, 15]),
                "trailing": bytes([0x20, invoke, 15, 0]),
            }.get(self.mode, bytes([0x20, invoke, 15]))
            npdu = b"\x01\x08\x0b\xb9\x01\x07" if self.routed else b"\x01\x00"
            if self.mode == "wrong_dnet":
                npdu = b"\x01\x08\x0b\xba\x01\x07"
            elif self.mode == "wrong_mac":
                npdu = b"\x01\x08\x0b\xb9\x01\x08"
            frame = b"\x81\x0a" + struct.pack(">H", 4 + len(npdu) + len(apdu)) + npdu + apdu
            if self.mode == "forwarded":
                import socket

                host, port = self.transport.get_extra_info("sockname")
                body = socket.inet_aton(host) + struct.pack(">H", port) + frame[4:]
                frame = b"\x81\x04" + struct.pack(">H", len(body) + 4) + body
            elif self.mode == "broadcast":
                frame = frame[:1] + b"\x0b" + frame[2:]
            elif self.mode == "reserved_npdu":
                frame = frame[:5] + bytes([frame[5] | 0x50]) + frame[6:]
            if self.mode == "rogue_hop":
                self.rogue_transport.sendto(frame, source)
            else:
                self.transport.sendto(frame, source)
        except Exception as exc:
            self.errors.append(exc)


async def link(tmp_path, *, routed=False, primitive=None):
    peer = WeeklyPeer(routed=routed)
    if primitive is not None:
        peer.exception_count = 0
        peer.days = [b"\x0e\xb4\x08\x00\x00\x00" + primitive + b"\x0f"] * 7
        peer.overrides["schedule,1", "present-value", None] = primitive
        peer.overrides["schedule,1", "schedule-default", None] = primitive
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    inventory = ScheduleInventory(
        client, client.store, timeout=0.1, operation_timeout=5, request_gap=0
    )
    report = await inventory.read(**options(peer, object_ids=["schedule,1"]))
    assert report["complete"] and not peer.errors
    library = NativeScheduleLibrary(tmp_path, inventory)
    capture = library.save(report["id"])
    service = NativeWeeklyDayWrites(
        client, client.store, library, timeout=0.1, operation_timeout=5, request_gap=0
    )
    return peer, client, inventory, library, service, capture


@pytest.fixture
async def connected(tmp_path):
    parts = await link(tmp_path)
    yield parts
    peer, client, inventory, _, service, _ = parts
    await service.close()
    await inventory.close()
    client.close()
    peer.close()
    await asyncio.sleep(0.01)


def draft(library, capture, **updates):
    return library.review(
        capture_id=capture["id"],
        object_id="schedule,1",
        day=updates.get("day", 1),
        transitions=updates.get(
            "transitions", [{"time": [8, 0, 0, 0], "native_type": "Real", "value_text": "2.5"}]
        ),
    )


async def preview(parts, **changes):
    _, _, _, library, service, capture = parts
    reviewed = draft(library, capture, **changes)
    return await service.preview(
        operation_id="preview_" + str(time.monotonic_ns()),
        draft_id=reviewed["id"],
        operator_name="Authored Operator",
        rationale="Authored weekly-day change",
    )


def apply_options(plan):
    return dict(
        operation_id="apply_" + str(time.monotonic_ns()),
        token=plan["token"],
        review_sha256=plan["review_sha256"],
    )


def assert_retired(client):
    assert not client.require().asap.clientTransactions
    assert not any(client.require()._requests.values())


@pytest.mark.parametrize("routed", [False, True])
async def test_literal_direct_and_routed_one_packet_exact_tags_and_durable_receipt(
    tmp_path, routed
):
    parts = await link(tmp_path, routed=routed)
    peer, client, inventory, library, service, _ = parts
    old = copy.deepcopy(peer.days)
    try:
        plan = await preview(parts)
        assert plan["can_apply"], plan
        assert plan["request_apdu_bytes"] == 27
        assert not peer.writes
        result_raw = await service.apply(**apply_options(plan))
        result = json.loads(result_raw)
        assert result["protocol_accepted"], result
        assert result["dispatch_started"] and result["may_have_applied"]
        assert result["protocol_status"] == "accepted" and result["readback"]["status"] == "match"
        assert result["response"]["raw_proof"]["receive_provenance"]
        assert len(peer.write_packets) == 1 and not peer.errors
        assert peer.writes == [(1, bytes.fromhex("0eb40800000044402000000f"))]
        assert peer.days[1:] == old[1:]
        assert result["native_request"]["request_priority"] is None
        assert len(bytes.fromhex(result["native_request"]["apdu_hex"])) == 27
        assert service.journal.receipt(result["id"]) == result_raw
        assert WeeklyWriteJournal(client.store).receipt(result["id"]) == result_raw
        assert (
            result["evidence_sha256"]
            == hashlib.sha256(
                encoded({k: v for k, v in result.items() if k != "evidence_sha256"})
            ).hexdigest()
        )
        with pytest.raises(ValueError, match="already used"):
            await service.apply(**apply_options(plan))
        assert_retired(client)
    finally:
        await service.close()
        await inventory.close()
        client.close()
        peer.close()


@pytest.mark.parametrize("day", range(1, 8))
async def test_each_fixed_weekly_index_preserves_other_six_days(connected, day):
    peer, client, _, _, service, _ = connected
    before = list(peer.days)
    plan = await preview(connected, day=day)
    assert plan["can_apply"], plan
    result = json.loads(await service.apply(**apply_options(plan)))
    assert result["readback"]["status"] == "match", result
    assert len(peer.writes) == 1 and peer.writes[0][0] == day
    assert all(before[i] == peer.days[i] for i in range(7) if i != day - 1)
    assert_retired(client)


@pytest.mark.parametrize(
    "mode,protocol,readback",
    [
        ("drop", "unknown", "match"),
        ("error", "rejected", "match"),
        ("unknown_error", "rejected", "match"),
        ("partial_error", "rejected", "mismatch"),
        ("reject", "rejected", "mismatch"),
        ("server_abort", "rejected", "mismatch"),
        ("client_abort", "unknown", "mismatch"),
        ("wrong_service", "unknown", "mismatch"),
        ("wrong_invoke", "unknown", "mismatch"),
        ("trailing", "unknown", "mismatch"),
        ("normalize", "accepted", "mismatch"),
        ("unavailable", "accepted", "unavailable"),
    ],
)
async def test_protocol_and_observed_state_are_independent_never_retry(
    connected, mode, protocol, readback
):
    peer, client, _, _, service, _ = connected
    plan = await preview(connected)
    assert plan["can_apply"], plan
    peer.mode = mode
    result = json.loads(await service.apply(**apply_options(plan)))
    assert result["dispatch_started"] and result["may_have_applied"], result
    assert result["protocol_status"] == protocol, result
    assert result["readback"]["status"] == readback, result
    if mode in ("error", "unknown_error", "partial_error"):
        assert result["response"]["error_class"]["native_datatype"] == "ErrorClass"
        assert result["response"]["error_code"]["native_datatype"] == "ErrorCode"
        if mode == "unknown_error":
            assert result["response"]["error_class"]["value"] == 255
            assert result["response"]["error_code"]["value"] == 65535
            assert result["response"]["error_class"]["known"] is False
    elif mode in ("reject", "server_abort"):
        assert result["response"]["reason"]["value"] in (9, 1)
    await asyncio.sleep(0.12)
    assert len(peer.write_packets) == 1 and not peer.errors
    assert_retired(client)


@pytest.mark.parametrize("raw", ["20010f", "50010f91029120", "600109", "710101"])
def test_exact_response_forms(raw):
    assert response_header(bytes.fromhex(raw), 1)


@pytest.mark.parametrize(
    "raw",
    [
        "20010c",
        "20010f00",
        "700101",
        "71010100",
        "50010f9102912000",
        "50010f21012101",
        "22010f",
        "20020f",
    ],
)
def test_wrong_service_invoke_reserved_bits_trailing_and_client_abort_refused(raw):
    with pytest.raises((ValueError, DecodingError, InvalidTag)):
        response_header(bytes.fromhex(raw), 1)


@pytest.mark.parametrize(
    "property,value",
    [
        ("schedule-default", b"\x44\x40\x40\x00\x00"),
        ("priority-for-writing", b"\x21\x09"),
        ("out-of-service", b"\x11"),
        ("effective-period", b"\xa4\x7e\x01\x01\xff\xa4\x7e\x0c\x1f\xff"),
        ("list-of-object-property-references", b""),
    ],
)
async def test_changed_static_context_prevents_preview_and_apply(connected, property, value):
    peer, client, _, _, service, _ = connected
    plan = await preview(connected)
    assert plan["can_apply"]
    peer.overrides["schedule,1", property, None] = value
    result = json.loads(await service.apply(**apply_options(plan)))
    assert not result["dispatch_started"] and not result["may_have_applied"]
    assert result["status"] == "not_sent" and not peer.writes
    refused = await preview(connected)
    assert not refused["can_apply"] and refused["token"] is None
    assert_retired(client)


@pytest.mark.parametrize("change", ["day", "neighbor", "device", "schedule", "count", "max_apdu"])
async def test_native_identity_array_and_size_changes_block_dispatch(connected, change):
    peer, client, _, _, service, _ = connected
    plan = await preview(connected)
    assert plan["can_apply"]
    if change in ("day", "neighbor"):
        peer.days[0 if change == "day" else 6] = b"\x0e\x0f"
    elif change in ("device", "schedule"):
        peer.overrides[
            "device,42" if change == "device" else "schedule,1", "object-identifier", None
        ] = b"\xc4\x02\x00\x00\x2b"
    elif change == "count":
        peer.overrides["schedule,1", "weekly-schedule", 0] = unsigned(6)
    else:
        peer.maximum = 50
    result = json.loads(await service.apply(**apply_options(plan)))
    assert not result["dispatch_started"] and not peer.writes, result
    assert_retired(client)


async def test_dynamic_present_value_and_advancing_clock_do_not_fake_stale_configuration(connected):
    peer, _, _, _, service, _ = connected
    peer.overrides["schedule,1", "present-value", None] = b"\x44\x40\x40\x00\x00"
    peer.overrides["device,42", "local-time", None] = b"\xb4\x0e\x00\x00\x00"
    plan = await preview(connected)
    assert plan["can_apply"], plan
    peer.overrides["schedule,1", "present-value", None] = b"\x44\x40\x80\x00\x00"
    peer.overrides["device,42", "local-time", None] = b"\xb4\x0e\x01\x00\x00"
    result = json.loads(await service.apply(**apply_options(plan)))
    assert result["protocol_accepted"] and result["readback"]["status"] == "match"
    assert len(peer.writes) == 1


async def test_no_change_never_allocates_write_token(connected):
    peer, _, _, _, _, _ = connected
    plan = await preview(
        connected, transitions=[{"time": [8, 0, 0, 0], "native_type": "Real", "value_text": "-0.0"}]
    )
    assert plan["status"] == "no_change" and not plan["can_apply"] and plan["token"] is None
    assert not peer.writes


@pytest.mark.parametrize("limit", ["remote", "profile"])
async def test_remote_and_local_unsegmented_apdu_limits_refuse_before_write(connected, limit):
    peer, _, _, _, _, _ = connected
    peer.maximum = 50 if limit == "remote" else 1476
    # Real32 32 transitions are below480; Double64 would require a new typed
    # source. A conservative profile reduction tests the actual encoded size.
    import bms_tool.native_schedule_write as module

    original = module.MAX_APDU
    if limit == "profile":
        module.MAX_APDU = 20
    try:
        plan = await preview(
            connected,
            transitions=[
                {"time": [hour, 0, 0, 0], "native_type": "Real", "value_text": "2.5"}
                for hour in range(8)
            ],
        )
    finally:
        module.MAX_APDU = original
    assert not plan["can_apply"] and not peer.writes


async def test_expired_superseded_changed_review_and_interface_tokens_never_write(connected):
    peer, client, _, _, service, _ = connected
    old = await preview(connected)
    newer = await preview(connected)
    with pytest.raises(ValueError, match="already used"):
        await service.apply(**apply_options(old))
    service.plans[newer["token"]]["created"] -= 31
    with pytest.raises(ValueError, match="expired"):
        await service.apply(**apply_options(newer))
    changed = await preview(connected)
    with pytest.raises(ValueError, match="invalid"):
        await service.apply(**(apply_options(changed) | {"review_sha256": "0" * 64}))
    replaced = await preview(connected)
    await client.connect(f"127.0.0.1:{free_udp()}")
    result = json.loads(await service.apply(**apply_options(replaced)))
    assert result["status"] == "not_sent" and not peer.writes


@pytest.mark.parametrize("failure", ["intent", "locked", "slow", "interface"])
async def test_failed_or_stale_journal_intent_prevents_dispatch(connected, failure, monkeypatch):
    peer, client, _, _, service, _ = connected
    plan = await preview(connected)
    original = service.journal.intent
    db = None
    if failure == "locked":
        db = client.store.connect(timeout=0.25)
        db.execute("BEGIN IMMEDIATE")
    elif failure == "intent":
        monkeypatch.setattr(
            service.journal,
            "intent",
            lambda _: (_ for _ in ()).throw(OSError("authored write failure")),
        )
    else:

        def altered(receipt):
            result = original(receipt)
            if failure == "slow":
                service.active["deadline"] = 0
            else:
                client.config = {**client.config, "instance": client.config["instance"] + 1}
            return result

        monkeypatch.setattr(service.journal, "intent", altered)
    try:
        result = json.loads(await service.apply(**apply_options(plan)))
    finally:
        if db:
            db.rollback()
            db.close()
    assert not result["dispatch_started"] and not result["may_have_applied"] and not peer.writes, (
        result
    )
    assert_retired(client)


@pytest.mark.parametrize("phase", ["before", "after"])
async def test_cancellation_retains_exact_dispatch_uncertainty_and_retires_owned_work(
    connected, phase
):
    peer, client, _, _, service, _ = connected
    plan = await preview(connected)
    if phase == "before":
        peer.hold_property = "schedule-default"
        peer.entered.clear()
    else:
        peer.mode = "hold"
    arguments = apply_options(plan)
    task = asyncio.create_task(service.apply(**arguments))
    await asyncio.wait_for(
        peer.entered.wait() if phase == "before" else peer.write_entered.wait(), 1
    )
    assert service.cancel(arguments["operation_id"])["cancel_requested"]
    result = json.loads(await task)
    assert result["dispatch_started"] is (phase == "after")
    assert result["may_have_applied"] is (phase == "after")
    assert len(peer.writes) == int(phase == "after")
    assert_retired(client)


async def test_postdispatch_result_journal_failure_leaves_durable_unresolved_intent(
    connected, monkeypatch
):
    peer, client, _, _, service, _ = connected
    plan = await preview(connected)
    monkeypatch.setattr(
        service.journal,
        "result",
        lambda _: (_ for _ in ()).throw(sqlite3.OperationalError("authored result failure")),
    )
    result = json.loads(await service.apply(**apply_options(plan)))
    assert result["protocol_accepted"] and result["may_have_applied"] and result["journal_error"]
    unresolved = json.loads(WeeklyWriteJournal(client.store).receipt(result["id"]))
    assert unresolved["journal_state"] == "intent_only" and unresolved["may_have_applied"]
    assert unresolved["dispatch_started"] is None and unresolved["protocol_status"] == "unknown"
    assert unresolved["protocol_accepted"] is None and unresolved["readback"]["status"] == "unknown"
    assert unresolved["intent_snapshot"]["dispatch_started"] is False
    assert unresolved["status"] == "unknown" and len(peer.writes) == 1


async def test_reconcile_after_library_restart_reads_without_any_further_write(connected, tmp_path):
    peer, client, _, _, service, _ = connected
    plan = await preview(connected)
    peer.mode = "drop"
    result = json.loads(await service.apply(**apply_options(plan)))
    assert result["protocol_status"] == "unknown"
    restarted = NativeWeeklyDayWrites(
        client,
        client.store,
        NativeScheduleLibrary(tmp_path),
        timeout=0.1,
        operation_timeout=5,
        request_gap=0,
    )
    assert not restarted.library.reviews
    before = len(peer.writes)
    report = json.loads(
        await restarted.reconcile(operation_id="explicit_reconcile", receipt_id=result["id"])
    )
    assert (
        report["read_only"]
        and report["writes_sent"] == 0
        and report["readback"]["status"] == "match"
    )
    assert len(peer.writes) == before
    assert_retired(client)


def test_journal_exact_bytes_bounds_seals_and_unresolved_restart(tmp_path, monkeypatch):
    import bms_tool.native_schedule_write as module

    store = Store(tmp_path)
    journal = WeeklyWriteJournal(store)
    receipt = {"id": "a" * 32, "profile": module.PROFILE, "status": "not_sent", "value": -0.0}
    intent_hash = journal.intent(receipt)
    assert len(intent_hash) == 64
    recovered = json.loads(journal.receipt(receipt["id"]))
    assert recovered["status"] == "unknown" and recovered["may_have_applied"]
    assert recovered["dispatch_started"] is None and recovered["protocol_status"] == "unknown"
    assert recovered["protocol_accepted"] is None and recovered["readback"]["status"] == "unknown"
    assert recovered["intent_sha256"] == intent_hash
    raw = journal.result(receipt)
    assert b'"value":-0.0' in raw and journal.receipt(receipt["id"]) == raw
    with pytest.raises(ValueError, match="immutable"):
        journal.result(receipt)
    monkeypatch.setattr(module, "JOURNAL_RECORDS", 1)
    with pytest.raises(ValueError, match="capacity"):
        journal.intent({**receipt, "id": "b" * 32})
    with store.connect() as db:
        db.execute(
            "UPDATE native_weekly_writes SET result=? WHERE id=?",
            (encoded(seal({**receipt, "id": "b" * 32})), receipt["id"]),
        )
    with pytest.raises(ValueError, match="seal"):
        journal.receipt(receipt["id"])


@pytest.mark.parametrize(
    "routed,mode",
    [
        (False, "forwarded"),
        (False, "broadcast"),
        (True, "forwarded"),
        (True, "broadcast"),
        (True, "rogue_hop"),
        (True, "wrong_dnet"),
        (True, "wrong_mac"),
        (False, "reserved_npdu"),
        (True, "reserved_npdu"),
    ],
)
async def test_raw_next_hop_bvlc_and_routed_source_cannot_forge_protocol_acceptance(
    tmp_path, routed, mode
):
    parts = await link(tmp_path, routed=routed)
    peer, client, inventory, _, service, _ = parts
    rogue, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    peer.rogue_transport = rogue
    try:
        plan = await preview(parts)
        assert plan["can_apply"]
        peer.mode = mode
        result = json.loads(await service.apply(**apply_options(plan)))
        assert result["protocol_status"] == "unknown" and not result["protocol_accepted"], result
        assert result["may_have_applied"] and result["readback"]["status"] == "match"
        assert len(peer.writes) == 1 and not peer.errors
        assert_retired(client)
    finally:
        await service.close()
        await inventory.close()
        client.close()
        peer.close()
        rogue.close()


async def test_owned_hooks_do_not_replace_an_unrelated_observer_or_request(connected):
    from bacpypes3.apdu import ReadPropertyRequest
    from bacpypes3.pdu import Address
    from bacpypes3.primitivedata import ObjectIdentifier
    from bms_tool.bacnet_exchange import confirmed_exchange
    from bms_tool.scoped_hooks import ScopedAttribute

    peer, client, _, _, service, _ = connected
    app = client.require()
    layer = app.nsap.local_adapter.clientPeer
    mux = layer.multiplexer
    original = mux.confirmation
    observed = []

    async def observer(packet):
        observed.append(bytes(packet.pduData))
        return await original(packet)

    hook = ScopedAttribute(mux, "confirmation", observer)
    try:
        plan = await preview(connected)
        peer.mode = "hold"
        task = asyncio.create_task(service.apply(**apply_options(plan)))
        await asyncio.wait_for(peer.write_entered.wait(), 1)
        # A different owned invoke remains routable while the write awaits ACK.
        request = ReadPropertyRequest(
            objectIdentifier=ObjectIdentifier("device,42"),
            propertyIdentifier="object-identifier",
            destination=Address(peer.endpoint),
        )
        response = await asyncio.wait_for(confirmed_exchange(app, request, single_attempt=True), 1)
        assert response.objectIdentifier == ObjectIdentifier("device,42")
        result = json.loads(await task)
        assert result["may_have_applied"] and observed
        assert mux.__dict__["confirmation"] is observer
        assert_retired(client)
    finally:
        hook.close()


async def test_tampered_native_draft_or_capture_proof_never_produces_field_write(connected):
    peer, _, _, library, service, capture = connected
    review = draft(library, capture)
    altered = copy.deepcopy(review)
    altered["new"]["encoded_hex"] = "0e0f"
    library.reviews[review["id"]] = encoded(altered)
    with pytest.raises(ValueError, match="changed"):
        await service.preview(
            operation_id="tampered_draft",
            draft_id=review["id"],
            operator_name="Operator",
            rationale="Authored",
        )
    assert not peer.writes


async def test_cancelled_partial_readback_preserves_dated_rows_without_match_claim(connected):
    peer, client, _, _, service, _ = connected
    plan = await preview(connected)
    peer.mode = "partial_readback"
    arguments = apply_options(plan)
    task = asyncio.create_task(service.apply(**arguments))
    await asyncio.wait_for(peer.entered.wait(), 1)
    service.cancel(arguments["operation_id"])
    result = json.loads(await task)
    assert result["protocol_accepted"] and result["may_have_applied"]
    readback = result["readback"]
    assert readback["status"] == "unavailable" and readback["selected_day_matches"] is None
    evidence = readback["evidence"]
    assert not evidence["complete"] and evidence["pending_read"]["array_index"] == 4
    weekly = evidence["objects"][0]["properties"]["weekly-schedule"]
    assert not weekly["complete"] and len(weekly["elements"]) == 3
    assert all(
        row["received_at"] and row["encoded_value"]["complete"] for row in weekly["elements"]
    )
    assert result["transport_candidates"]["response"]["response_apdu_hex"].startswith("20")
    assert len(peer.writes) == 1 and not peer.errors
    assert_retired(client)


async def test_change_after_fresh_check_is_reported_without_claiming_cas_or_rollback(
    connected, monkeypatch
):
    peer, _, _, _, service, _ = connected
    plan = await preview(connected)
    original = service.journal.intent

    def concurrent_change(receipt):
        result = original(receipt)
        peer.days[6] = b"\x0e\x0f"
        return result

    monkeypatch.setattr(service.journal, "intent", concurrent_change)
    result = json.loads(await service.apply(**apply_options(plan)))
    assert result["protocol_accepted"] and result["may_have_applied"]
    assert result["readback"]["selected_day_matches"] is True
    assert result["readback"]["other_static_context_matches"] is False
    assert result["readback"]["status"] == "mismatch" and len(peer.writes) == 1
    assert peer.days[6] == b"\x0e\x0f"


@pytest.mark.parametrize(
    "native_type,old,value_text,new",
    [
        ("Boolean", "11", "false", "10"),
        ("Unsigned", "2102", "4294967295", "24ffffffff"),
        ("Integer", "31ff", "-2147483648", "3480000000"),
        ("Enumerated", "9102", "4294967295", "94ffffffff"),
        ("Real", "4480000000", "0.1", "443dcccccd"),
        ("Double", "55088000000000000000", "1e20", "55084415af1d78b58c40"),
    ],
)
async def test_wire_primitive_domains_and_explicit_null_preserve_exact_literal_tags(
    tmp_path, native_type, old, value_text, new
):
    parts = await link(tmp_path, primitive=bytes.fromhex(old))
    peer, client, inventory, _, service, _ = parts
    try:
        plan = await preview(
            parts,
            transitions=[
                {"time": [8, 0, 0, 0], "native_type": native_type, "value_text": value_text},
                {"time": [17, 0, 0, 0], "native_type": "Null", "value_text": "null"},
            ],
        )
        assert plan["can_apply"], plan
        result = json.loads(await service.apply(**apply_options(plan)))
        assert result["protocol_accepted"] and result["readback"]["status"] == "match", result
        expected = bytes.fromhex("0eb408000000" + new + "b411000000000f")
        assert peer.writes == [(1, expected)] and not peer.errors
        assert result["review"]["native_draft"]["source"]["observed_native_type"] == native_type
        assert_retired(client)
    finally:
        await service.close()
        await inventory.close()
        client.close()
        peer.close()


def test_unresolved_intents_reserve_result_space_across_journal_instances(tmp_path, monkeypatch):
    import bms_tool.native_schedule_write as module

    monkeypatch.setattr(module, "RECORD_BYTES", 1000)
    monkeypatch.setattr(module, "JOURNAL_BYTES", 1900)
    store = Store(tmp_path)
    first, second = WeeklyWriteJournal(store), WeeklyWriteJournal(store)
    receipt = {"id": "a" * 32, "profile": module.PROFILE, "status": "not_sent"}
    first.intent(receipt)
    with pytest.raises(ValueError, match="capacity"):
        second.intent({**receipt, "id": "b" * 32})
    first.result(receipt)
    second.intent({**receipt, "id": "b" * 32})
    assert first.status()["reserved_result_bytes"] == 1000


@pytest.mark.parametrize(
    "corruption",
    ["empty_result", "text_result", "both_null", "wrong_intent_hash", "altered_intent"],
)
def test_journal_corrupt_result_never_falls_back_to_an_apparent_completed_intent(
    tmp_path, corruption
):
    import bms_tool.native_schedule_write as module

    store = Store(tmp_path)
    journal = WeeklyWriteJournal(store)
    receipt = {"id": "a" * 32, "profile": module.PROFILE, "status": "not_sent"}
    journal.intent(receipt)
    result = json.loads(journal.result(receipt))
    with store.connect() as db:
        if corruption == "empty_result":
            db.execute("UPDATE native_weekly_writes SET result=?", (b"",))
        elif corruption == "text_result":
            db.execute("UPDATE native_weekly_writes SET result=?", (encoded(result).decode(),))
        elif corruption == "both_null":
            db.execute("UPDATE native_weekly_writes SET result=NULL,intent=NULL")
        elif corruption == "wrong_intent_hash":
            result.pop("evidence_sha256")
            db.execute(
                "UPDATE native_weekly_writes SET result=?",
                (encoded(seal({**result, "intent_sha256": "b" * 64})),),
            )
        else:
            intent = json.loads(db.execute("SELECT intent FROM native_weekly_writes").fetchone()[0])
            intent.pop("evidence_sha256")
            db.execute(
                "UPDATE native_weekly_writes SET intent=?",
                (encoded(seal({**intent, "changed": True})),),
            )
    with pytest.raises(ValueError, match="BLOB|intent"):
        journal.receipt(receipt["id"])


def test_large_multi_observation_journal_uses_receipt_profile_without_relaxing_sources(tmp_path):
    import bms_tool.native_schedule_write as module
    from bms_tool.native_schedule_library import strict_json

    # Each observation represents fixed7days, complete32exceptions with32
    # transitions, plus a bounded reference list. It is not a forged native
    # capture: this exercises only a multi-observation local receipt envelope.
    atomic = {
        "native_datatype": "Real",
        "value": -0.0,
        "encoded": {
            "type": "any",
            "encoding": "hex",
            "value": "4480000000",
            "bytes": 5,
            "sha256": "a" * 64,
        },
    }
    transition = {"time": {"native_datatype": "Time", "fields": [8, 0, 0, 0]}, "value": atomic}
    daily = {"daySchedule": [transition] * 32}
    reference = {
        "objectIdentifier": {
            "native_datatype": "ObjectIdentifier",
            "value": "analog-value,1",
            "object_type": 2,
            "instance": 1,
        },
        "propertyIdentifier": {
            "native_datatype": "PropertyIdentifier",
            "value": 85,
            "name": "present-value",
            "known": True,
        },
        "deviceIdentifier": {
            "native_datatype": "ObjectIdentifier",
            "value": "device,42",
            "object_type": 8,
            "instance": 42,
        },
    }
    observation = {
        "objects": [
            {
                "properties": {
                    "weekly-schedule": {"elements": [{"value": daily}] * 7},
                    "exception-schedule": {
                        "elements": [
                            {"value": {"listOfTimeValues": [transition] * 32, "eventPriority": 8}}
                        ]
                        * 32
                    },
                    "list-of-object-property-references": {"value": [reference] * 800},
                }
            }
        ]
    }
    receipt = {
        "id": "a" * 32,
        "profile": module.PROFILE,
        "status": "unknown",
        "review": {"fresh": observation},
        "fresh": observation,
        "readback": {"status": "mismatch", "evidence": observation},
    }
    raw = encoded(receipt)

    def count(value):
        pending, total = [value], 0
        while pending:
            item = pending.pop()
            total += 1
            if isinstance(item, dict):
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        return total

    assert count(receipt) > 100000 and len(raw) < module.RECORD_BYTES
    with pytest.raises(ValueError, match="structure"):
        strict_json(raw, module.RECORD_BYTES)
    with pytest.raises(ValueError, match="structure"):
        strict_json(encoded([0] * 100000), module.RECORD_BYTES)  # 100001values
    journal = WeeklyWriteJournal(Store(tmp_path))
    journal.intent(receipt)
    saved = journal.result(receipt)
    assert journal.receipt(receipt["id"]) == saved
    restored = strict_json(saved, module.RECORD_BYTES, max_values=module.MAX_RECEIPT_VALUES)
    assert restored["readback"]["evidence"] == observation
    assert b'"value":-0.0' in saved


@pytest.mark.parametrize("max_values", [False, 0, 1000001, 1.5])
def test_explicit_receipt_json_profile_cannot_remove_reader_bounds(max_values):
    from bms_tool.native_schedule_library import strict_json

    with pytest.raises(ValueError, match="bound"):
        strict_json(b"{}", 1024, max_values=max_values)
