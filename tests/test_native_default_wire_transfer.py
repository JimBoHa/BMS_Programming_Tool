"""Combined native transfers use actual isolated UDP and independent saved bytes."""

import asyncio
import copy
import gzip
import struct
import time
import types

import pytest
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_applications import NativeApplications
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_default_wire import NativeDefaultWire
from bms_tool.native_default_wire_transfer import verify_combined_preservation
from fastapi.testclient import TestClient

from .test_moi_wire_sources import REF, A, B, C
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import mutations, real_slot
from .test_native_default_wire import proposal
from .test_native_signal_compiler import slot
from .test_native_wire_compiler import BOOLEAN, wire_files


def combined_files():
    files = wire_files()
    for instance, cid, pid, kind, payload in [
        (12, 527, 3113, 4, struct.pack(">f", 3.5)),
        (11, 551, 65000, 2, (1).to_bytes(4, "big")),
    ]:
        files[11] += slot((2 << 22) | instance, cid, pid, kind, len(files[12]))
        files[12] += payload + bytes([header_crc(payload) ^ 255])
    return files


def saved(files, offset, payload):
    raw = bytearray(files[12])
    raw[offset : offset + len(payload) + 1] = payload + bytes([header_crc(payload) ^ 255])
    files[12] = bytes(raw)


def consume_selected_default(peer, *, mode="consume", bits="3dcccccd"):
    original = peer.do_ReinitializeDeviceRequest

    async def state(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) != "end-restore":
            return
        if mode != "retain-default":
            saved(self.files, 17, bytes.fromhex(bits))
        if mode == "other-saved":
            real_slot(self.files, 0, struct.pack(">f", 99))
        elif mode == "bad-crc":
            self.files[12] = self.files[12][:-1] + bytes([self.files[12][-1] ^ 1])
        elif mode == "old-wire":
            checked = MoiIdentity(self.files[3])
            raw = bytearray(checked.data)
            offset = checked.reader.records[REF]["properties"][3118]["value_start_offset"] + 2
            raw[offset] = 0
            self.files[3] = gzip.compress(raw, mtime=123)

    peer.do_ReinitializeDeviceRequest = types.MethodType(state, peer)


async def review(link, *, mode="consume", value="0.1", target=None, replacement=B):
    peer, _, _, native, original_target = link
    peer.files = combined_files()
    peer.metadata["object-name"] = "Authored native wire controller"
    consume_selected_default(peer, mode=mode, bits="80000000" if value == "-0" else "3dcccccd")

    async def no_collision(_):
        raise AssertionError("A combined edit must not scan or allocate Device identities.")

    native.instances._collision = no_collision
    target = target or original_target
    captured = await native.capture(**target, operation_id="capture-for-combined-transfer")
    snapshot, _ = native.storage.load(captured["id"])
    service = NativeDefaultWire(NativeBackupRecords(native.storage))
    body = proposal(service, snapshot, value=value, replacement=replacement)
    plan = await native.preview_default_wire(
        **target, **body, operation_id="preview-combined-transfer"
    )
    return body, plan


def applying(plan, **changes):
    return {
        "operation_id": "apply-combined-transfer",
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        "default_change_confirmed": True,
        "wire_change_confirmed": True,
        "application_transfer_confirmed": True,
        **changes,
    }


@pytest.mark.parametrize("value,bits", [("0.1", "3dcccccd"), ("-0", "80000000")])
async def test_two_edits_use_one_durable_restore_and_preserve_every_other_fresh_byte(
    native_link, value, bits
):
    peer, _, _, native, _ = native_link
    body, plan = await review(native_link, value=value)
    real_slot(peer.files, 0, struct.pack(">f", 45))
    saved(peer.files, 10, b"\0")
    original = copy.deepcopy(peer.files)

    def durable():
        (receipt,) = native.storage.receipts()
        assert receipt["pending"] and receipt["intent"]["change_kind"] == "default-wire"
        assert (
            native.storage.directory / receipt["intent"]["backup_id"] / "reviewed-application.bin"
        ).is_file()
        assert any(e["stage"] == "dispatch-application-block" for e in receipt["events"])

    peer.dispatch = durable
    result = await native.apply_default_wire(**applying(plan))
    assert result["result"]["status"] == "verified" and not result["pending"], result
    assert result["intent"]["operation_profile"] == "native-effective-default-wire-transfer/1"
    assert result["intent"]["payload_sha256"] != plan["payload_sha256"]
    merged, _ = ParameterApplication(original[3], original[11], original[12]).compile()
    before, after = MoiIdentity(merged), MoiIdentity(peer.files[3])
    expected = bytearray(before.data)
    offset = before.reader.records[C]["properties"][3113]["value_start_offset"] + 1
    expected[offset : offset + 4] = bytes.fromhex(bits)
    offset = before.reader.records[REF]["properties"][3118]["value_start_offset"] + 2
    expected[offset] = 1
    assert after.data == bytes(expected)
    assert after.reader.scalar(after.reader.records[A], 3113) == 45
    assert after.reader.scalar(after.reader.records[B], 3113) == 17
    assert after.reader.scalar(after.reader.records[BOOLEAN], 3113) is False
    assert after.reader.diagram(REF)["connections"][0]["source_ref"] == B
    assert native.storage.load(result["intent"]["backup_id"])[1] == original
    assert (
        mutations(peer).count(("state", "start-restore"))
        == mutations(peer).count(("state", "end-restore"))
        == 1
    )
    assert all(r[1] == 3 for r in mutations(peer) if r[0] == "write")
    proof = result["result"]["preservation"]
    assert proof["selected_default"]["effective_bits"] == bits
    assert proof["selected_wire"]["effective_connection_verified"]
    verify_combined_preservation(original, peer.files, body, result["intent"]["combined_guard"])
    before_events = list(mutations(peer))
    with pytest.raises(ValueError, match="consumed"):
        await native.apply_default_wire(**applying(plan))
    assert mutations(peer) == before_events


@pytest.mark.parametrize(
    "fault",
    ["selected", "configuration", "application", "directory", "capacity", "credentials", "expired"],
)
async def test_changed_selected_source_or_limits_refuse_before_restore(native_link, fault):
    peer, _, _, native, _ = native_link
    _, plan = await review(native_link)
    if fault == "selected":
        saved(peer.files, 17, struct.pack(">f", 9))
    elif fault == "configuration":
        saved(peer.files, 22, (2).to_bytes(4, "big"))
    elif fault == "application":
        peer.files[3] = gzip.compress(
            gzip.decompress(peer.files[3]).replace(
                b"Opaque metadata retained", b"Unsafe metadata retained"
            ),
            mtime=123,
        )
    elif fault == "directory":
        peer.files[11] = peer.files[11][:-1] + bytes([peer.files[11][-1] ^ 1])
    elif fault == "capacity":
        peer.application_capacity = 1
    elif fault == "credentials":
        native.credentials.set("changed-backup", "changed-restore")
    else:
        native.plans[plan["token"]]["expires"] = time.monotonic() - 1
    result = await native.apply_default_wire(**applying(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert not mutations(peer) and not native.storage.receipts()


@pytest.mark.parametrize(
    "confirmation",
    ["default_change_confirmed", "wire_change_confirmed", "application_transfer_confirmed"],
)
async def test_each_confirmation_is_required_and_token_is_not_replayed(native_link, confirmation):
    peer, _, _, native, _ = native_link
    _, plan = await review(native_link)
    with pytest.raises(ValueError, match="Confirm"):
        await native.apply_default_wire(**applying(plan, **{confirmation: False}))
    with pytest.raises(ValueError, match="consumed"):
        await native.apply_default_wire(**applying(plan))
    assert not mutations(peer)


@pytest.mark.parametrize("mode", ["retain-default", "other-saved", "old-wire", "bad-crc"])
async def test_acknowledged_restore_with_wrong_effective_values_stays_uncertain(native_link, mode):
    peer, _, _, native, _ = native_link
    _, plan = await review(native_link, mode=mode)
    result = await native.apply_default_wire(**applying(plan))
    assert result["pending"] and result["result"]["status"] == "unknown", result
    assert result["result"]["protocol_accepted"] and result["result"]["may_have_applied"]
    assert mutations(peer).count(("state", "start-restore")) == 1


async def test_lost_commit_ack_reconciles_after_restart_without_another_restore(native_link):
    peer, bacnet, store, native, _ = native_link
    _, plan = await review(native_link)
    peer.mode = "drop-end"
    result = await native.apply_default_wire(**applying(plan))
    assert result["pending"] and result["result"]["status"] == "unknown"
    before = list(mutations(peer))
    peer.mode = "normal"
    await native.close()
    restarted = NativeApplications(bacnet, store, native.instances, request_timeout=0.1, gap=0)
    try:
        checked = await restarted.reconcile(
            operation_id="readback-combined-restart", receipt_id=result["intent"]["id"]
        )
        assert not checked["pending"] and checked["latest_readback"]["status"] == "verified", (
            checked
        )
        assert mutations(peer) == before
    finally:
        await restarted.close()


async def test_unchanged_combined_proposal_has_no_transfer_review(native_link):
    with pytest.raises(ValueError, match="Change the selected"):
        await review(native_link, value="3.5", replacement=A)


@pytest.mark.parametrize("other", ["default", "wire", "instance"])
async def test_combined_review_cannot_be_applied_through_an_older_kind(native_link, other):
    peer, _, _, native, _ = native_link
    _, plan = await review(native_link)
    request = applying(plan)
    method = (
        native.apply_default
        if other == "default"
        else native.apply_wire
        if other == "wire"
        else native.apply
    )
    if other == "default":
        request.pop("wire_change_confirmed")
    elif other == "wire":
        request.pop("default_change_confirmed")
    else:
        request.pop("wire_change_confirmed")
        request.pop("default_change_confirmed")
        request["allocation_confirmed"] = True
    with pytest.raises(ValueError, match="different native"):
        await method(**request)
    assert not mutations(peer)


async def test_routed_combined_transfer_pins_station_and_verifies_both_edits(native_link):
    from .test_native_default_transfer import NativeRouter

    peer, _, _, native, target = native_link
    address, port = target["address"].rsplit(":", 1)
    transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: NativeRouter((address, int(port))), local_addr=("127.0.0.1", 0)
    )
    routed = {"address": "3001:7", "device": "device,5136", "router": proxy.endpoint, "dnet": 3001}
    try:
        _, plan = await review(native_link, target=routed)
        result = await native.apply_default_wire(**applying(plan))
        assert result["result"]["status"] == "verified" and not result["pending"], result
        assert result["intent"]["target"] == {k: v for k, v in routed.items() if k != "device"}
        assert result["result"]["preservation"]["selected_wire"]["effective_connection_verified"]
        assert mutations(peer).count(("state", "start-restore")) == 1 and not proxy.errors
    finally:
        transport.close()


@pytest.mark.parametrize("stage", ["operation_profile", "combined_edit", "combined_guard"])
async def test_wrong_or_malformed_readback_evidence_stops_before_field_queries(native_link, stage):
    peer, _, _, native, _ = native_link
    _, plan = await review(native_link)
    before = list(peer.events)
    with pytest.raises(ValueError):
        await native.verify(None, {**plan, stage: None})
    assert peer.events == before


@pytest.mark.parametrize(
    "field,value", [("combined_guard", None), ("payload_sha256", "0" * 64), ("combined_edit", None)]
)
async def test_in_memory_review_edits_cannot_bypass_its_seal(native_link, field, value):
    peer, _, _, native, _ = native_link
    _, plan = await review(native_link)
    native.plans[plan["token"]]["body"][field] = value
    with pytest.raises(ValueError, match="exact combined native review"):
        await native.apply_default_wire(**applying(plan))
    assert not mutations(peer)


@pytest.mark.parametrize("mode", ["drop-start", "drop-block", "drop-end"])
async def test_lost_restore_ack_is_not_resent_and_remains_durable(native_link, mode):
    peer, _, _, native, _ = native_link
    _, plan = await review(native_link)
    peer.mode = mode
    result = await native.apply_default_wire(**applying(plan))
    assert result["pending"] and result["result"]["status"] == "unknown", result
    assert native.storage.receipts()[0]["intent"]["change_kind"] == "default-wire"
    assert mutations(peer).count(("state", "start-restore")) == 1
    writes = [r[2] for r in mutations(peer) if r[0] == "write"]
    assert len(writes) == len(set(writes))


def test_http_registration_is_session_protected_and_confirmation_types_are_closed(tmp_path):
    from bms_tool.app import create_app

    path = "/api/bacnet/controller/native-application/default-wire/transfer/apply"
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(path, json={}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        request = applying({"token": "a" * 32, "review_sha256": "b" * 64})
        for changes in [
            {"default_change_confirmed": 1},
            {"wire_change_confirmed": "true"},
            {"application_transfer_confirmed": None},
            {"allocation_confirmed": True},
        ]:
            assert client.post(path, json=request | changes, headers=headers).status_code == 422
        result = client.post(path, json=request, headers=headers)
        assert result.status_code == 422 and "already consumed" in result.json()["detail"]
        assert not client.get("/api/session").json()["field_network_open"]
