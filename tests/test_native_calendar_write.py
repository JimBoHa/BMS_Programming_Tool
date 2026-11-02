"""Independently authored Calendar Date_List APDUs and durable uncertainty."""

import asyncio
import copy
import json
import struct

import pytest
from bms_tool import native_calendar_write as module
from bms_tool.connections import Bacnet
from bms_tool.native_calendar_drafts import NativeCalendarDrafts
from bms_tool.native_calendar_write import (
    PROFILE,
    CalendarPreview,
    CalendarWriteJournal,
    NativeCalendarWrites,
)
from bms_tool.native_schedule_library import NativeScheduleLibrary
from bms_tool.schedule_inventory import ScheduleInventory
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_native_schedule_library import reseal
from .test_schedule_inventory import SchedulePeer, options, text, unsigned

OLD = bytes.fromhex("0cff0d20ff1ea4ff0101ffa4ff0c1fff1f2bff0607")
NEW = bytes.fromhex("0c7e0b02ff")
DATE = {"kind": "date", "date": [126, 11, 2, 255]}


class CalendarPeer(SchedulePeer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.date_list, self.maximum, self.revision = OLD, 480, 18
        self.mode, self.overrides = "accept", {}
        self.writes, self.write_packets = [], []
        self.write_entered = asyncio.Event()
        self.rogue_transport = None

    def value(self, obj, prop, index):
        if (str(obj), prop, index) in self.overrides:
            return self.overrides[str(obj), prop, index]
        if str(obj) == "calendar,1" and prop == "date-list":
            return self.date_list
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
            # Object type6, instance1; property23; context3. No array-index or priority.
            assert body[:8] == bytes.fromhex("0c0180000119173e") and body[-1] == 0x3F
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
                self.date_list = value
            if self.mode == "normalize":
                self.date_list = b""
            if self.mode == "other_changed":
                self.overrides["calendar,1", "description", None] = text("Changed during write")
            if self.mode == "unavailable":
                self.hold_property = "date-list"
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


async def link(tmp_path, *, routed=False, entries=None, old_date_list=OLD):
    peer = CalendarPeer(routed=routed)
    peer.date_list = old_date_list
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    inventory = ScheduleInventory(
        client, client.store, timeout=0.25, operation_timeout=5, request_gap=0
    )
    try:
        capture = await inventory.read(**options(peer, object_ids=["calendar,1"]))
        assert capture["complete"] and capture["identity_verified"] and not peer.errors
        library = NativeScheduleLibrary(tmp_path, inventory)
        saved = library.save(capture["id"])
        draft = {
            "capture_id": saved["id"],
            "object_id": "calendar,1",
            "entries": [DATE] if entries is None else entries,
        }
        local = NativeCalendarDrafts(library).review(draft)
        service = NativeCalendarWrites(
            client, client.store, library, timeout=0.25, operation_timeout=5, request_gap=0
        )
        request = {
            "operation_id": "preview_calendar",
            "draft": draft,
            "expected_review_id": local["id"],
            "operator_name": "Authored Operator",
            "rationale": "Authored loopback Calendar change",
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
    peer.close()
    await asyncio.sleep(0.01)
    assert not peer.errors


async def apply(service, review, operation_id="apply_calendar"):
    return json.loads(
        await service.apply(
            operation_id=operation_id, token=review["token"], review_sha256=review["review_sha256"]
        )
    )


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_literal_date_list_write_one_attempt_and_independent_readback(tmp_path, routed):
    peer, client, inventory, library, service, request = await link(tmp_path, routed=routed)
    originals = {p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()}
    try:
        preview = await service.preview(**request)
        assert preview["can_apply"], preview
        assert preview["property"] == "date-list" and preview["array_index"] is None
        assert preview["request_service_body_hex"] == "0c0180000119173e" + NEW.hex() + "3f"
        assert not peer.writes
        result = await apply(service, preview)
        assert result["profile"] == PROFILE
        assert result["protocol_status"] == "accepted" and result["protocol_accepted"]
        assert result["readback"]["status"] == "match"
        assert result["readback"]["selected_value_matches"] is True
        assert result["readback"]["other_static_context_matches"] is True
        assert result["may_have_applied"] and result["dispatch_started"]
        assert peer.writes == [NEW] and peer.date_list == NEW
        assert (
            result["native_request"]["array_index"] is None
            and result["native_request"]["request_priority"] is None
        )
        retained = service.journal.receipt(result["id"])
        assert json.loads(retained) == result
        restarted = NativeCalendarWrites(
            client,
            client.store,
            NativeScheduleLibrary(tmp_path),
            timeout=0.25,
            operation_timeout=5,
            request_gap=0,
        )
        reconciled = json.loads(
            await restarted.reconcile(operation_id="reconcile_calendar", receipt_id=result["id"])
        )
        assert reconciled["read_only"] and reconciled["writes_sent"] == 0
        assert reconciled["readback"]["status"] == "match"
        assert restarted.journal.receipt(result["id"]) == retained and peer.writes == [NEW]
        assert {
            p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()
        } == originals
        with pytest.raises(ValueError, match="already used"):
            await apply(service, preview)
        await restarted.close()
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
@pytest.mark.parametrize(
    "mode,protocol,readback,selected,other",
    [
        ("error", "rejected", "match", True, True),
        ("reject", "rejected", "mismatch", False, True),
        ("server_abort", "rejected", "mismatch", False, True),
        ("client_abort", "unknown", "mismatch", False, True),
        ("wrong_service", "unknown", "mismatch", False, True),
        ("wrong_invoke", "unknown", "mismatch", False, True),
        ("trailing", "unknown", "mismatch", False, True),
        ("drop", "unknown", "match", True, True),
        ("no_apply_drop", "unknown", "mismatch", False, True),
        ("normalize", "accepted", "mismatch", False, True),
        ("other_changed", "accepted", "mismatch", True, False),
        ("unavailable", "accepted", "unavailable", None, None),
    ],
)
async def test_protocol_and_independent_value_context_observations_stay_separate(
    tmp_path, routed, mode, protocol, readback, selected, other
):
    peer, client, inventory, library, service, request = await link(tmp_path, routed=routed)
    try:
        preview = await service.preview(**request)
        assert preview["can_apply"], preview
        peer.mode = mode
        result = await apply(service, preview)
        assert result["protocol_status"] == protocol, result
        assert result["protocol_accepted"] is (
            True if protocol == "accepted" else False if protocol == "rejected" else None
        )
        assert result["readback"]["status"] == readback, result
        assert result["readback"]["selected_value_matches"] is selected
        assert result["readback"]["other_static_context_matches"] is other
        assert result["dispatch_started"] and result["may_have_applied"]
        assert len(peer.writes) == 1
        assert json.loads(service.journal.receipt(result["id"])) == result
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("stage", ["preview", "apply"])
@pytest.mark.parametrize(
    "changed",
    ["date-list", "object-name", "description", "object-identifier", "device-identity", "maximum"],
)
async def test_fresh_conflicts_never_dispatch_a_calendar_write(tmp_path, stage, changed):
    peer, client, inventory, library, service, request = await link(tmp_path)
    try:
        preview = await service.preview(**request) if stage == "apply" else None
        if changed == "date-list":
            peer.date_list = b""
        elif changed == "maximum":
            peer.maximum = 50
        elif changed == "device-identity":
            peer.overrides["device,42", "object-identifier", None] = bytes.fromhex("c40200002b")
        elif changed == "object-identifier":
            peer.overrides["calendar,1", changed, None] = bytes.fromhex("c401800002")
        else:
            peer.overrides["calendar,1", changed, None] = text("Changed after capture")
        if stage == "preview":
            result = await service.preview(**request)
            # A smaller, still-sufficient maximum is read from the actual target.
            assert result["can_apply"] is (changed == "maximum"), result
        else:
            result = await apply(service, preview)
            assert result["status"] == "not_sent" and result["dispatch_started"] is False, result
            assert result["may_have_applied"] is False
        assert peer.writes == []
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("revision,eligible", [(17, False), (18, True), (22, True)])
async def test_new_week_patterns_require_actual_protocol_revision(tmp_path, revision, eligible):
    entries = [{"kind": "weekNDay", "fields": [255, 7, 1]}]
    peer, client, inventory, library, service, request = await link(tmp_path, entries=entries)
    try:
        peer.revision = revision
        result = await service.preview(**request)
        assert result["can_apply"] is eligible, result
        if eligible:
            applied = await apply(service, result)
            assert applied["readback"]["status"] == "match"
            assert peer.writes == [bytes.fromhex("2bff0701")]
        else:
            assert "revision 18" in str(result["reasons"]) and not peer.writes
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("modern", [False, True])
async def test_unknown_revision_is_observed_without_inventing_compatibility(tmp_path, modern):
    entries = [{"kind": "weekNDay", "fields": [255, 7, 1]}] if modern else [DATE]
    peer, client, inventory, library, service, request = await link(tmp_path, entries=entries)
    try:
        peer.overrides["device,42", "protocol-revision", None] = b"\x00"
        result = await service.preview(**request)
        assert result["can_apply"] is not modern, result
        if not modern:
            assert result["capabilities"]["protocol_revision"] is None
        assert not peer.writes
    finally:
        await close(peer, client, inventory, service)


async def test_protocol_revision_change_before_dispatch_retires_review(tmp_path):
    peer, client, inventory, library, service, request = await link(
        tmp_path, entries=[{"kind": "weekNDay", "fields": [255, 8, 1]}]
    )
    try:
        preview = await service.preview(**request)
        assert preview["can_apply"]
        peer.revision = 17
        result = await apply(service, preview)
        assert result["status"] == "not_sent" and not result["may_have_applied"]
        assert not peer.writes
    finally:
        await close(peer, client, inventory, service)


async def test_replacing_an_existing_newer_week_pattern_also_checks_revision(tmp_path):
    peer, client, inventory, library, service, request = await link(
        tmp_path, entries=[], old_date_list=bytes.fromhex("2bff0701")
    )
    try:
        peer.revision = 17
        result = await service.preview(**request)
        assert not result["can_apply"] and "revision 18" in str(result["reasons"])
        assert not peer.writes
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("fault", ["missing_description", "unqualified_name", "unknown_property"])
async def test_locally_retained_context_does_not_automatically_grant_field_eligibility(
    tmp_path, fault
):
    peer, client, inventory, library, service, request = await link(tmp_path)
    try:
        report = json.loads(library.source(request["draft"]["capture_id"]))
        props = report["objects"][0]["properties"]
        if fault == "missing_description":
            del props["description"]
        elif fault == "unqualified_name":
            props["object-name"] = {
                "status": "unavailable",
                "error": "Authored partial observation",
            }
        else:
            props["unrecognized-extension"] = {
                "status": "unavailable",
                "error": "Retained opaque evidence",
            }
        captured = library._store(reseal(report), "imported")
        draft = {**request["draft"], "capture_id": captured["id"]}
        local = NativeCalendarDrafts(library).review(draft)
        before = len(peer.requests)
        with pytest.raises(ValueError):
            await service.preview(**{**request, "draft": draft, "expected_review_id": local["id"]})
        assert len(peer.requests) == before and not peer.writes
    finally:
        await close(peer, client, inventory, service)


async def test_dynamic_boolean_observation_does_not_become_a_static_lock(tmp_path):
    peer, client, inventory, library, service, request = await link(tmp_path)
    try:
        peer.overrides["calendar,1", "present-value", None] = b"\x10"
        preview = await service.preview(**request)
        assert preview["can_apply"], preview
        result = await apply(service, preview)
        assert result["readback"]["status"] == "match" and peer.writes == [NEW]
    finally:
        await close(peer, client, inventory, service)


async def test_noop_does_not_allocate_token_and_empty_list_is_a_real_replacement(tmp_path):
    peer, client, inventory, library, service, request = await link(tmp_path)
    try:
        source = NativeCalendarDrafts(library).source(request["draft"]["capture_id"])
        draft = {**request["draft"], "entries": source["calendars"][0]["entries"]}
        local = NativeCalendarDrafts(library).review(draft)
        result = await service.preview(
            **{**request, "draft": draft, "expected_review_id": local["id"]}
        )
        assert result["status"] == "no_change" and result["token"] is None and not service.plans
        empty = {**draft, "entries": []}
        local = NativeCalendarDrafts(library).review(empty)
        preview = await service.preview(
            **{**request, "draft": empty, "expected_review_id": local["id"]}
        )
        assert preview["request_service_body_hex"] == "0c0180000119173e3f"
        result = await apply(service, preview)
        assert result["readback"]["status"] == "match" and peer.writes == [b""]
    finally:
        await close(peer, client, inventory, service)


async def test_actual_remote_apdu_limit_and_native_ceiling_do_not_split_values(tmp_path):
    peer, client, inventory, library, service, request = await link(tmp_path, entries=[DATE] * 8)
    try:
        peer.maximum = 50
        preview = await service.preview(**request)
        assert not preview["can_apply"] and "remote APDU" in str(preview["reasons"]), preview
        assert not peer.writes
        reviewed = NativeCalendarDrafts(library).review(request["draft"])
        internal = copy.deepcopy(reviewed)
        internal["new"]["encoded_hex"] = NEW.hex() * 100
        with pytest.raises(ValueError, match="480-byte"):
            service._request(internal, peer.endpoint)
        with pytest.raises(ValueError):
            CalendarPreview(**{**request, "draft": {**request["draft"], "entries": [DATE] * 33}})
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize(
    "fault",
    ["changed_hash", "consumed", "expired", "clock_reversal", "new_review", "interface_aba"],
)
async def test_review_authority_is_one_use_expiring_and_interface_bound(tmp_path, fault):
    peer, client, inventory, library, service, request = await link(tmp_path)
    try:
        preview = await service.preview(**request)
        if fault == "changed_hash":
            changed = {**preview, "review_sha256": "0" * 64}
            with pytest.raises(ValueError):
                await apply(service, changed)
        elif fault == "consumed":
            service.plans.pop(preview["token"])
        elif fault == "expired":
            service.plans[preview["token"]]["created"] -= 31
        elif fault == "clock_reversal":
            service.plans[preview["token"]]["created"] += 31
        elif fault == "new_review":
            newer = await service.preview(**{**request, "operation_id": "newer_preview"})
            assert newer["can_apply"] and newer["token"] != preview["token"]
        elif fault == "interface_aba":
            config = copy.deepcopy(client.config)
            client.close()
            # DatagramTransport closes its descriptor in a queued callback.
            # Yield that callback before rebinding the exact original endpoint.
            await asyncio.sleep(0)
            await client.connect(**config)
            result = await apply(service, preview)
            assert result["status"] == "not_sent" and not result["may_have_applied"]
            assert not peer.writes
            return
        with pytest.raises(ValueError):
            await apply(service, preview)
        assert not peer.writes
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("stage", ["preview", "before_dispatch", "after_dispatch", "reconcile"])
async def test_owned_cancellation_keeps_possible_dispatch_and_partial_evidence(tmp_path, stage):
    peer, client, inventory, library, service, request = await link(tmp_path)
    try:
        if stage == "preview":
            peer.hold_property = "date-list"
            peer.entered.clear()
            task = asyncio.create_task(service.preview(**request))
            await peer.entered.wait()
            denied = await service.preview(**{**request, "operation_id": "concurrent_preview"})
            assert not denied["can_apply"] and "active" in str(denied["reasons"])
            service.cancel(request["operation_id"])
            result = await task
            assert (
                result["status"] == "cancelled"
                and result["fresh"]["pending_read"]["property"] == "date-list"
            )
            assert not peer.writes
        else:
            preview = await service.preview(**request)
            if stage == "reconcile":
                receipt = await apply(service, preview)
                original = service.journal.receipt(receipt["id"])
                peer.hold_property = "date-list"
                peer.entered.clear()
                task = asyncio.create_task(
                    service.reconcile(operation_id="cancel_reconcile", receipt_id=receipt["id"])
                )
                await peer.entered.wait()
                service.cancel("cancel_reconcile")
                result = json.loads(await task)
                assert result["read_only"] and result["status"] == "cancelled"
                assert (
                    result["readback"]["status"] == "unavailable"
                    and result["readback"]["evidence"]["pending_read"]["property"] == "date-list"
                )
                assert service.journal.receipt(receipt["id"]) == original and peer.writes == [NEW]
            else:
                if stage == "before_dispatch":
                    peer.hold_property = "date-list"
                    peer.entered.clear()
                else:
                    peer.mode = "hold"
                task = asyncio.create_task(
                    service.apply(
                        operation_id="cancel_apply",
                        token=preview["token"],
                        review_sha256=preview["review_sha256"],
                    )
                )
                await (
                    peer.entered.wait() if stage == "before_dispatch" else peer.write_entered.wait()
                )
                service.cancel("cancel_apply")
                result = json.loads(await task)
                possible = stage == "after_dispatch"
                assert (
                    result["may_have_applied"] is possible
                    and result["dispatch_started"] is possible
                )
                assert len(peer.writes) == int(possible)
                assert json.loads(service.journal.receipt(result["id"])) == result
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize(
    "fault",
    [
        "intent",
        "result",
        "after_intent_deadline",
        "after_intent_expiry",
        "fresh_expiry",
        "encoded_packet",
    ],
)
async def test_storage_and_final_dispatch_guards_do_not_retry_or_hide_intent(
    tmp_path, monkeypatch, fault
):
    peer, client, inventory, library, service, request = await link(tmp_path)
    try:
        preview = await service.preview(**request)

        def failed(*args, **kwargs):
            raise OSError("Authored storage failure")

        if fault == "intent":
            monkeypatch.setattr(service.journal, "intent", failed)
        elif fault == "result":
            monkeypatch.setattr(service.journal, "result", failed)
        elif fault in ("after_intent_deadline", "after_intent_expiry"):
            original = service.journal.intent
            retained_plan = service.plans[preview["token"]]

            def recorded(receipt):
                digest = original(receipt)
                if fault == "after_intent_deadline":
                    service.active["deadline"] = asyncio.get_running_loop().time() - 1
                else:
                    retained_plan["created"] -= 31
                return digest

            monkeypatch.setattr(service.journal, "intent", recorded)
        elif fault == "fresh_expiry":
            original_fresh = service._fresh
            retained_plan = service.plans[preview["token"]]

            async def expired(*args, **kwargs):
                result = await original_fresh(*args, **kwargs)
                retained_plan["created"] -= 31
                return result

            monkeypatch.setattr(service, "_fresh", expired)
        elif fault == "encoded_packet":
            exchange = module.confirmed_exchange

            async def changed(app, request, **kwargs):
                request.propertyArrayIndex = 1
                return await exchange(app, request, **kwargs)

            monkeypatch.setattr(module, "confirmed_exchange", changed)
        result = await apply(service, preview)
        if fault == "result":
            assert (
                peer.writes == [NEW]
                and result["readback"]["status"] == "match"
                and result.get("journal_error")
            )
            original = CalendarWriteJournal(client.store).receipt(result["id"])
            unresolved = json.loads(original)
            assert unresolved["status"] == "unknown" and unresolved["dispatch_started"] is None
            assert (
                unresolved["protocol_accepted"] is None
                and unresolved["readback"]["status"] == "unknown"
            )
            reconciled = json.loads(
                await service.reconcile(operation_id="recover_intent", receipt_id=result["id"])
            )
            assert (
                reconciled["readback"]["status"] == "match"
                and CalendarWriteJournal(client.store).receipt(result["id"]) == original
            )
        else:
            assert (
                result["status"] == "not_sent"
                and not result["may_have_applied"]
                and peer.writes == []
            )
        assert len(peer.writes) == int(fault == "result")
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_caller_cancellation_propagates_after_retaining_the_original_uncertain_receipt(
    tmp_path, routed
):
    peer, client, inventory, library, service, request = await link(tmp_path, routed=routed)
    try:
        preview = await service.preview(**request)
        peer.mode = "hold"
        task = asyncio.create_task(
            service.apply(
                operation_id="caller_cancel_apply",
                token=preview["token"],
                review_sha256=preview["review_sha256"],
            )
        )
        await peer.write_entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        row = service.journal.status()["records"][0]
        assert not row["unresolved"]
        receipt = json.loads(service.journal.receipt(row["id"]))
        assert receipt["may_have_applied"] and receipt["dispatch_started"]
        assert receipt["protocol_status"] == "unknown" and receipt["protocol_accepted"] is None
        assert peer.writes == [NEW] and service.active is None
        peer.mode = "accept"
        observed = json.loads(
            await service.reconcile(operation_id="caller_later_read", receipt_id=row["id"])
        )
        assert observed["readback"]["status"] == "match" and peer.writes == [NEW]
    finally:
        await close(peer, client, inventory, service)
