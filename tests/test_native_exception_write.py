"""Literal direct/routed exception writes, source conflicts and durable uncertainty."""

import asyncio
import copy
import json
import struct

import pytest
from bms_tool import native_exception_write as module
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.native_exception_write import ExceptionWriteJournal, NativeExceptionWrites
from bms_tool.native_schedule_exceptions import NativeScheduleExceptions
from bms_tool.native_schedule_library import NativeScheduleLibrary
from bms_tool.schedule_inventory import ScheduleInventory
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_connections import free_udp
from .test_native_schedule_exceptions import EVENTS, NEW, OLD
from .test_schedule_inventory import SchedulePeer, oid, options, text, unsigned

BASE = "/api/bacnet/schedule-exceptions/writes"


def split_events(raw):
    """Independent bounded TLV walk; no product SpecialEvent decoder in the peer."""
    events, stack, start, cursor = [], [], 0, 0
    while cursor < len(raw):
        header = raw[cursor]
        cursor += 1
        number, context, length = header >> 4, bool(header & 8), header & 7
        if number == 15:
            number = raw[cursor]
            cursor += 1
        if context and length in (6, 7):
            if length == 6:
                stack.append(number)
            else:
                assert stack.pop() == number
            continue
        if length == 5:
            length = raw[cursor]
            cursor += 1
            if length in (254, 255):
                width = 2 if length == 254 else 4
                length = int.from_bytes(raw[cursor : cursor + width], "big")
                cursor += width
        if not context and number == 1:
            length = 0  # application Boolean encodes its value in LVT
        cursor += length
        assert cursor <= len(raw)
        if context and number == 3 and not stack:
            events.append(raw[start:cursor])
            start = cursor
    assert not stack and start == len(raw)
    return events


class ExceptionPeer(SchedulePeer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.events, self.maximum, self.revision = split_events(bytes.fromhex(OLD)), 480, 18
        self.mode, self.overrides = "accept", {}
        self.writes, self.write_packets = [], []
        self.write_entered = asyncio.Event()
        self.rogue_transport = None

    def value(self, obj, prop, index):
        if (str(obj), prop, index) in self.overrides:
            return self.overrides[str(obj), prop, index]
        if str(obj) == "schedule,1" and prop == "exception-schedule":
            return unsigned(len(self.events)) if index == 0 else self.events[index - 1]
        if prop == "max-apdu-length-accepted":
            return unsigned(self.maximum)
        if prop == "protocol-revision":
            return unsigned(self.revision)
        return super().value(obj, prop, index)

    async def reply(self, data, source):
        offset = 11 if self.routed else 6
        payload = data[offset:]
        if len(payload) < 4 or payload[3] != 15:
            return await super().reply(data, source)
        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            assert payload[0] in (0, 2)
            invoke, body = payload[2], payload[4:]
            # Object type17, instance1; property38; context3. No array-index or priority.
            assert body[:8] == bytes.fromhex("0c0440000119263e") and body[-1] == 0x3F
            value = body[8:-1]
            self.writes.append(value)
            self.write_packets.append(bytes(data))
            self.write_entered.set()
            if self.mode not in (
                "reject",
                "server_abort",
                "client_abort",
                "wrong_service",
                "wrong_invoke",
                "trailing",
                "no_apply_drop",
            ):
                self.events = split_events(value)
            if self.mode == "normalize":
                self.events = []
            if self.mode == "other_changed":
                self.overrides["schedule,1", "description", None] = text("Changed during write")
            if self.mode == "unavailable":
                self.hold_property = "exception-schedule"
            if self.mode in ("drop", "no_apply_drop", "hold"):
                return
            apdu = {
                "error": bytes([0x50, invoke, 15]) + b"\x91\x02\x91\x20",
                "reject": bytes([0x60, invoke, 9]),
                "server_abort": bytes([0x71, invoke, 1]),
                "client_abort": bytes([0x70, invoke, 1]),
                "wrong_service": bytes([0x20, invoke, 12]),
                "wrong_invoke": bytes([0x20, (invoke + 17) % 256, 15]),
                "trailing": bytes([0x20, invoke, 15, 0]),
            }.get(self.mode, bytes([0x20, invoke, 15]))
            npdu = b"\x01\x08\x0b\xb9\x01\x07" if self.routed else b"\x01\x00"
            frame = b"\x81\x0a" + struct.pack(">H", 4 + len(npdu) + len(apdu)) + npdu + apdu
            self.transport.sendto(frame, source)
        except Exception as error:
            self.errors.append(error)


async def link(tmp_path, *, routed=False, events=None, old=OLD):
    peer = ExceptionPeer(routed=routed)
    peer.events = split_events(bytes.fromhex(old))
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    inventory = ScheduleInventory(
        client, client.store, timeout=0.25, operation_timeout=5, request_gap=0
    )
    try:
        capture = await inventory.read(**options(peer, object_ids=["schedule,1"]))
        assert capture["complete"] and capture["identity_verified"] and not peer.errors
        library = NativeScheduleLibrary(tmp_path, inventory)
        saved = library.save(capture["id"])
        draft = {
            "capture_id": saved["id"],
            "object_id": "schedule,1",
            "events": copy.deepcopy(EVENTS if events is None else events),
        }
        local = NativeScheduleExceptions(library).review(draft)
        service = NativeExceptionWrites(
            client, client.store, library, timeout=0.25, operation_timeout=5, request_gap=0
        )
        request = {
            "operation_id": "preview_exceptions",
            "draft": draft,
            "expected_review_id": local["id"],
            "operator_name": "Authored Operator",
            "rationale": "Authored loopback exception replacement",
        }
        return peer, client, inventory, library, service, request
    except BaseException:
        await inventory.close()
        client.close()
        peer.close()
        raise


async def close(peer, client, inventory, service):
    await service.close()
    await inventory.close()
    client.close()
    tasks = list(peer.tasks)
    peer.close()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert not peer.errors


async def apply(service, review):
    return json.loads(
        await service.apply(
            operation_id="apply_exceptions",
            token=review["token"],
            review_sha256=review["review_sha256"],
        )
    )


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_literal_whole_array_one_dispatch_exact_source_and_readback(tmp_path, routed):
    peer, client, inventory, library, service, request = await link(tmp_path, routed=routed)
    originals = {p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()}
    try:
        review = await service.preview(**request)
        assert review["can_apply"], review["reasons"]
        assert review["request_service_body_hex"] == "0c0440000119263e" + NEW + "3f"
        assert review["capabilities"] == {
            "remote_max_apdu": 480,
            "protocol_revision": 18,
            "calendar_references": ["calendar,2"],
        }
        assert review["fresh"]["calendar_references"][0]["object"] == "calendar,2"
        receipt = await apply(service, review)
        assert receipt["protocol_accepted"] is True and receipt["readback"]["status"] == "match"
        assert receipt["readback"]["other_static_context_matches"] is True
        assert peer.writes == [bytes.fromhex(NEW)]
        assert (
            receipt["array_index"] is None and receipt["native_request"]["request_priority"] is None
        )
        assert receipt["review"]["token"] is None
        raw = service.journal.receipt(receipt["id"])
        assert json.loads(raw) == receipt
        restarted = NativeExceptionWrites(
            client,
            client.store,
            NativeScheduleLibrary(tmp_path),
            timeout=0.25,
            operation_timeout=5,
            request_gap=0,
        )
        observation = json.loads(
            await restarted.reconcile(operation_id="reconcile_exceptions", receipt_id=receipt["id"])
        )
        assert observation["writes_sent"] == 0 and observation["readback"]["status"] == "match"
        assert restarted.journal.receipt(receipt["id"]) == raw
        assert peer.writes == [bytes.fromhex(NEW)]
        await restarted.close()
        with pytest.raises(ValueError, match="invalid|already used"):
            await apply(service, review)
        assert {
            p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()
        } == originals
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize(
    "mode,protocol,readback",
    [
        ("accept", True, "match"),
        ("error", False, "match"),
        ("reject", False, "mismatch"),
        ("server_abort", False, "mismatch"),
        ("client_abort", None, "mismatch"),
        ("drop", None, "match"),
        ("no_apply_drop", None, "mismatch"),
        ("wrong_service", None, "mismatch"),
        ("wrong_invoke", None, "mismatch"),
        ("trailing", None, "mismatch"),
        ("normalize", True, "mismatch"),
        ("other_changed", True, "mismatch"),
        ("unavailable", True, "unavailable"),
    ],
)
async def test_protocol_response_and_observation_are_separate_never_retry(
    tmp_path, mode, protocol, readback
):
    peer, client, inventory, _, service, request = await link(tmp_path)
    try:
        review = await service.preview(**request)
        assert review["can_apply"], review["reasons"]
        peer.mode = mode
        receipt = await apply(service, review)
        assert receipt["protocol_accepted"] is protocol
        assert receipt["readback"]["status"] == readback
        assert receipt["may_have_applied"] is True
        assert len(peer.writes) == 1
        assert service.journal.receipt(receipt["id"])
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("stage", ["preview", "apply"])
@pytest.mark.parametrize(
    "changed", ["name", "description", "default", "weekly", "exceptions", "device", "schedule"]
)
async def test_all_static_source_conflicts_block_dispatch(tmp_path, stage, changed):
    peer, client, inventory, _, service, request = await link(tmp_path)
    try:
        if stage == "apply":
            review = await service.preview(**request)
            assert review["can_apply"], review["reasons"]
        if changed == "exceptions":
            peer.events = []
        elif changed == "weekly":
            peer.overrides["schedule,1", "weekly-schedule", 4] = bytes.fromhex("0e0f")
        else:
            key, value = {
                "name": (("schedule,1", "object-name", None), text("Changed")),
                "description": (("schedule,1", "description", None), text("Changed")),
                "default": (("schedule,1", "schedule-default", None), bytes.fromhex("4440400000")),
                "device": (("device,42", "object-identifier", None), b"\xc4" + oid(8, 43)),
                "schedule": (("schedule,1", "object-identifier", None), b"\xc4" + oid(17, 2)),
            }[changed]
            peer.overrides[key] = value
        if stage == "preview":
            result = await service.preview(**request)
            assert result["can_apply"] is False and result["token"] is None
        else:
            result = await apply(service, review)
            assert result["dispatch_started"] is False
        assert peer.writes == []
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("revision,allowed", [(17, False), (18, True), (22, True)])
async def test_modern_original_or_proposed_week_requires_actual_revision(
    tmp_path, revision, allowed
):
    peer, client, inventory, _, service, request = await link(tmp_path)
    try:
        peer.revision = revision
        review = await service.preview(**request)
        assert review["can_apply"] is allowed, review["reasons"]
        if allowed:
            peer.revision = 17
            assert (await apply(service, review))["dispatch_started"] is False
        assert not peer.writes
    finally:
        await close(peer, client, inventory, service)


async def test_dynamic_observations_do_not_become_static_locks_and_missing_old_reference_can_be_removed(
    tmp_path,
):
    peer, client, inventory, _, service, request = await link(tmp_path, events=[])
    try:
        peer.overrides["calendar,2", "object-identifier", None] = b"\xc4" + oid(6, 99)
        peer.overrides["schedule,1", "present-value", None] = bytes.fromhex("4440400000")
        peer.overrides["schedule,1", "status-flags", None] = bytes.fromhex("820480")
        peer.overrides["schedule,1", "reliability", None] = bytes.fromhex("9101")
        review = await service.preview(**request)
        assert review["can_apply"], review["reasons"]
        assert review["capabilities"]["calendar_references"] == []
        receipt = await apply(service, review)
        assert receipt["readback"]["status"] == "match" and peer.events == []
        assert peer.writes == [b""]
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("stage", ["preview", "apply"])
async def test_proposed_calendar_reference_requires_same_device_native_identity(tmp_path, stage):
    peer, client, inventory, _, service, request = await link(tmp_path)
    try:
        if stage == "apply":
            review = await service.preview(**request)
            assert review["can_apply"]
        peer.overrides["calendar,2", "object-identifier", None] = b"\xc4" + oid(6, 99)
        if stage == "preview":
            result = await service.preview(**request)
            assert result["can_apply"] is False
        else:
            assert (await apply(service, review))["dispatch_started"] is False
        assert not peer.writes
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize(
    "fault",
    ["expired", "intent_failure", "expired_after_intent", "result_failure", "changed_interface"],
)
async def test_final_authority_and_storage_failures_keep_exact_uncertainty(
    tmp_path, fault, monkeypatch
):
    peer, client, inventory, _, service, request = await link(tmp_path)
    try:
        review = await service.preview(**request)
        assert review["can_apply"], review["reasons"]
        original = service.journal.intent
        if fault == "expired":
            service.plans[review["token"]]["created"] -= 31
            with pytest.raises(ValueError, match="expired"):
                await apply(service, review)
        else:
            if fault == "intent_failure":

                def fail(receipt):
                    raise OSError("authored intent failure")

                monkeypatch.setattr(service.journal, "intent", fail)
            elif fault == "expired_after_intent":

                def expire(receipt):
                    result = original(receipt)
                    monkeypatch.setattr(module.time, "monotonic", lambda: 10**12)
                    return result

                monkeypatch.setattr(service.journal, "intent", expire)
            elif fault == "result_failure":

                def fail(receipt):
                    raise OSError("authored result failure")

                monkeypatch.setattr(service.journal, "result", fail)
            elif fault == "changed_interface":
                await client.connect(f"127.0.0.1:{free_udp()}")
            receipt = await apply(service, review)
            assert receipt["dispatch_started"] is (fault == "result_failure")
            retained = json.loads(ExceptionWriteJournal(client.store).receipt(receipt["id"]))
            if fault == "result_failure":
                assert retained["journal_state"] == "intent_only"
                assert (
                    retained["protocol_accepted"] is None and retained["dispatch_started"] is None
                )
                assert retained["may_have_applied"] is True
        assert len(peer.writes) == (1 if fault == "result_failure" else 0)
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("routed", [False, True])
async def test_owned_cancellation_after_dispatch_and_readonly_restart_reconciliation(
    tmp_path, routed
):
    peer, client, inventory, _, service, request = await link(tmp_path, routed=routed)
    try:
        review = await service.preview(**request)
        assert review["can_apply"]
        peer.mode = "drop"
        pending = asyncio.create_task(apply(service, review))
        await asyncio.wait_for(peer.write_entered.wait(), 1)
        service.cancel("apply_exceptions")
        receipt = await pending
        assert receipt["may_have_applied"] is True and len(peer.writes) == 1
        raw = service.journal.receipt(receipt["id"])
        result = json.loads(
            await service.reconcile(operation_id="readback_cancelled", receipt_id=receipt["id"])
        )
        assert result["readback"]["status"] == "match" and result["writes_sent"] == 0
        assert service.journal.receipt(receipt["id"]) == raw and len(peer.writes) == 1
    finally:
        await close(peer, client, inventory, service)


async def test_noop_and_apdu_bounds_never_allocate_unusable_authority(tmp_path):
    peer, client, inventory, _, service, request = await link(tmp_path)
    try:
        noop = copy.deepcopy(request)
        noop["draft"]["events"] = NativeScheduleExceptions(service.library).source(
            request["draft"]["capture_id"]
        )["schedules"][0]["events"]
        noop["expected_review_id"] = NativeScheduleExceptions(service.library).review(
            noop["draft"]
        )["id"]
        result = await service.preview(**noop)
        assert result["status"] == "no_change" and result["token"] is None and not service.plans
        peer.maximum = 50
        assert (await service.preview(**request))["can_apply"] is False
        peer.maximum = 480
        huge = copy.deepcopy(request)
        huge["draft"]["events"] *= 8
        huge["expected_review_id"] = NativeScheduleExceptions(service.library).review(
            huge["draft"]
        )["id"]
        assert (await service.preview(**huge))["can_apply"] is False
        assert not peer.writes
    finally:
        await close(peer, client, inventory, service)


def test_independent_profile_and_studio_token_strict_mutation_models(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(BASE + "/profile").json()["profile"] == module.PROFILE
        assert client.post(BASE + "/preview", json={}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                BASE + "/cancel",
                headers=headers,
                json={"operation_id": "cancel_authored", "target": {"device": "device,42"}},
            ).status_code
            == 422
        )
        assert (
            client.post(
                BASE + "/reconcile",
                headers=headers,
                json={"operation_id": "read_authored", "receipt_id": "0" * 32, "token": "no"},
            ).status_code
            == 422
        )
        assert client.get(BASE + "/receipts/" + "0" * 32).status_code == 422
        assert (
            client.get("/api/bacnet/calendars/writes/profile").json()["profile"] != module.PROFILE
        )


@pytest.mark.parametrize("fault", ["changed_hash", "clock_reversal", "new_review", "interface_aba"])
async def test_review_cannot_return_through_changed_hash_new_review_or_interface_aba(
    tmp_path, fault
):
    peer, client, inventory, _, service, request = await link(tmp_path)
    try:
        preview = await service.preview(**request)
        assert preview["can_apply"]
        if fault == "changed_hash":
            preview = {**preview, "review_sha256": "0" * 64}
        elif fault == "clock_reversal":
            service.plans[preview["token"]]["created"] += 31
        elif fault == "new_review":
            newer = await service.preview(**{**request, "operation_id": "newer_exceptions"})
            assert newer["can_apply"] and newer["token"] != preview["token"]
        else:
            config = copy.deepcopy(client.config)
            client.close()
            await asyncio.sleep(0)
            await client.connect(**config)
            assert (await apply(service, preview))["dispatch_started"] is False
            return
        with pytest.raises(ValueError):
            await apply(service, preview)
        assert not peer.writes
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("stage", ["preview", "apply"])
@pytest.mark.parametrize(
    "fault", ["default_type", "array_count", "weekly_count", "native_identity_type"]
)
async def test_malformed_native_context_never_dispatches(tmp_path, stage, fault):
    peer, client, inventory, _, service, request = await link(tmp_path)
    try:
        if stage == "apply":
            preview = await service.preview(**request)
            assert preview["can_apply"]
        key, value = {
            "default_type": (("schedule,1", "schedule-default", None), bytes.fromhex("2101")),
            "array_count": (("schedule,1", "exception-schedule", 0), unsigned(33)),
            "weekly_count": (("schedule,1", "weekly-schedule", 0), unsigned(6)),
            "native_identity_type": (("schedule,1", "object-name", None), unsigned(8)),
        }[fault]
        peer.overrides[key] = value
        if stage == "preview":
            assert (await service.preview(**request))["can_apply"] is False
        else:
            assert (await apply(service, preview))["dispatch_started"] is False
        assert not peer.writes
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("modern", [False, True])
async def test_unavailable_revision_is_observed_and_never_invented(tmp_path, modern):
    peer, client, inventory, _, service, request = await link(
        tmp_path, events=EVENTS if modern else EVENTS[:1]
    )
    try:
        peer.hold_property = "protocol-revision"
        preview = await service.preview(**request)
        assert preview["can_apply"] is (not modern), preview["reasons"]
        assert preview["fresh"]["failed_reads"]
        if not modern:
            assert preview["capabilities"]["protocol_revision"] is None
        assert not peer.writes
    finally:
        await close(peer, client, inventory, service)


async def test_original_modern_week_still_requires_revision_when_new_array_removes_it(tmp_path):
    old = "0e2bff07010f2eb4091e000044400000002f3908"
    peer, client, inventory, _, service, request = await link(tmp_path, events=[], old=old)
    try:
        peer.revision = 17
        review = await service.preview(**request)
        assert review["can_apply"] is False
        assert any("revision18" in reason for reason in review["reasons"])
        assert not peer.writes
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize(
    "atom,kind,value_text,expected",
    [
        ("10", "Boolean", "true", "11"),
        ("2101", "Unsigned", "4294967295", "24ffffffff"),
        ("3101", "Integer", "-2147483648", "3480000000"),
        ("9101", "Enumerated", "4294967295", "94ffffffff"),
        ("4440000000", "Real", "-0", "4480000000"),
        ("55084000000000000000", "Double", "-0", "55088000000000000000"),
        ("74006f6c64", "CharacterString", "é", "7300c3a9"),
    ],
)
async def test_all_observed_default_domains_and_null_reach_literal_wire(
    tmp_path, atom, kind, value_text, expected
):
    # No exception/weekly values may disagree with the observed default basis.
    peer = ExceptionPeer()
    peer.events = []
    peer.overrides["schedule,1", "schedule-default", None] = bytes.fromhex(atom)
    peer.overrides["schedule,1", "present-value", None] = bytes.fromhex(atom)
    for i in range(1, 8):
        peer.overrides["schedule,1", "weekly-schedule", i] = b"\x0e\x0f"
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    inventory = ScheduleInventory(
        client, client.store, timeout=0.25, operation_timeout=5, request_gap=0
    )
    service = NativeExceptionWrites(
        client,
        client.store,
        NativeScheduleLibrary(tmp_path, inventory),
        timeout=0.25,
        operation_timeout=5,
        request_gap=0,
    )
    try:
        capture = await inventory.read(**options(peer, object_ids=["schedule,1"]))
        assert capture["complete"]
        saved = service.library.save(capture["id"])
        draft = {
            "capture_id": saved["id"],
            "object_id": "schedule,1",
            "events": [
                {
                    "period": {"kind": "date", "date": [126, 11, 2, 1]},
                    "priority": 8,
                    "transitions": [
                        {"time": [8, 0, 0, 0], "native_type": kind, "value_text": value_text},
                        {"time": [18, 0, 0, 0], "native_type": "Null", "value_text": "null"},
                    ],
                }
            ],
        }
        local = service.drafts.review(draft)
        review = await service.preview(
            operation_id="typed_exception_preview",
            draft=draft,
            expected_review_id=local["id"],
            operator_name="Authored",
            rationale="Native type proof",
        )
        assert review["can_apply"], review["reasons"]
        receipt = await apply(service, review)
        assert receipt["readback"]["status"] == "match"
        assert peer.writes == [
            bytes.fromhex("0e0c7e0b02010f2eb408000000" + expected + "b412000000002f3908")
        ]
    finally:
        await close(peer, client, inventory, service)


async def test_explicit_preview_cancellation_retires_its_token_without_evicting_another_review(
    tmp_path,
):
    peer, client, inventory, _, service, request = await link(tmp_path)
    try:
        first = await service.preview(**request)
        assert first["can_apply"]
        retired = service.cancel(request["operation_id"])
        assert retired["reviews_retired"] == 1 and retired["cancel_requested"] is False
        with pytest.raises(ValueError, match="invalid|already used"):
            await apply(service, first)
        newer = await service.preview(**{**request, "operation_id": "retained_other_preview"})
        assert newer["can_apply"]
        service.cancel("unrelated_operation")
        assert newer["token"] in service.plans and not peer.writes
    finally:
        await close(peer, client, inventory, service)
