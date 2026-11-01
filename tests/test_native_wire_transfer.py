"""Existing-wire native transfers use actual UDP, fresh guards and one restore."""

import copy
import gzip
import struct
import time
import types

import pytest
from bms_tool.moi_identity import MoiIdentity
from bms_tool.mstp import header_crc
from bms_tool.native_applications import NativeApplications
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_wire_compiler import EffectiveWireService
from bms_tool.native_wire_transfer import verify_wire_preservation
from fastapi.testclient import TestClient

from .test_moi_wire_sources import REF, A, B
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import mutations, real_slot
from .test_native_signal_compiler import slot
from .test_native_wire_compiler import proposal, query, wire_files


def applying(plan, **changes):
    return {
        "operation_id": "native-wire-apply",
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        "wire_change_confirmed": True,
        "application_transfer_confirmed": True,
        **changes,
    }


async def wire_review(link, *, target=None, mode="normal", configuration=False):
    peer, _, _, native, original_target = link
    peer.files = wire_files(target_class=538)
    if configuration:
        for instance, cid in [(10, 551), (11, 551), (12, 538)]:
            peer.files[11] += slot((2 << 22) | instance, cid, 65000, 2, len(peer.files[12]))
            payload = (1).to_bytes(4, "big")
            peer.files[12] += payload + bytes([header_crc(payload) ^ 255])
    peer.metadata["object-name"] = "Authored native wire controller"
    peer.mode = mode

    async def no_collision(_):
        raise AssertionError("A wire edit must not allocate/scan for Device identities.")

    native.instances._collision = no_collision
    target = target or original_target
    capture = await native.capture(**target, operation_id="native-wire-capture")
    snapshot, _ = native.storage.load(capture["id"])
    service = EffectiveWireService(NativeBackupRecords(native.storage))
    body = proposal(service, query(service, snapshot))
    plan = await native.preview_wire(**target, **body, operation_id="native-wire-preview")
    return body, plan


async def test_wire_udp_restore_keeps_other_fresh_numeric_boolean_values_and_is_durable(
    native_link,
):
    peer, _, _, native, _ = native_link
    body, plan = await wire_review(native_link)
    real_slot(peer.files, 0, struct.pack(">f", 45))
    raw = bytearray(peer.files[12])
    raw[10:12] = b"\x00" + bytes([header_crc(b"\x00") ^ 255])
    peer.files[12] = bytes(raw)
    original = copy.deepcopy(peer.files)

    def durable():
        (receipt,) = native.storage.receipts()
        assert receipt["pending"] and receipt["intent"]["change_kind"] == "wire-source"
        assert (
            native.storage.directory / receipt["intent"]["backup_id"] / "reviewed-application.bin"
        ).is_file()
        assert any(r["stage"] == "dispatch-application-block" for r in receipt["events"])

    peer.dispatch = durable
    result = await native.apply_wire(**applying(plan))
    assert result["result"]["status"] == "verified" and not result["pending"], result
    assert result["intent"]["operation_profile"] == "native-effective-wire-source-transfer/1"
    assert result["intent"]["payload_sha256"] != plan["payload_sha256"]
    observed = MoiIdentity(peer.files[3])
    assert observed.reader.diagram(REF)["connections"][0]["source_ref"] == B
    assert observed.reader.scalar(observed.reader.records[A], 3113) == 45
    assert observed.reader.scalar(observed.reader.records[B], 3113) == 17
    assert (
        observed.reader.scalar(observed.reader.records["controller/retained-boolean"], 3113)
        is False
    )
    assert native.storage.load(result["intent"]["backup_id"])[1] == original
    assert (
        mutations(peer).count(("state", "start-restore"))
        == mutations(peer).count(("state", "end-restore"))
        == 1
    )
    assert all(r[1] == 3 for r in mutations(peer) if r[0] == "write")
    assert result["result"]["preservation"]["selected_wire"]["effective_connection_verified"]
    before = list(mutations(peer))
    with pytest.raises(ValueError, match="consumed"):
        await native.apply_wire(**applying(plan))
    assert mutations(peer) == before
    verify_wire_preservation(original, peer.files, body, result["intent"]["wire_guard"])


@pytest.mark.parametrize(
    "change", ["application", "directory", "capacity", "credentials", "expired", "nonfinite-saved"]
)
async def test_wire_fresh_preflight_refuses_changes_before_restore(native_link, change):
    peer, _, _, native, _ = native_link
    _, plan = await wire_review(native_link)
    if change == "application":
        peer.files[3] = gzip.compress(
            gzip.decompress(peer.files[3]).replace(
                b"Opaque metadata retained", b"Unsafe metadata retained"
            ),
            mtime=0,
        )
    elif change == "directory":
        peer.files[11] = peer.files[11][:-1] + bytes([peer.files[11][-1] ^ 1])
    elif change == "capacity":
        peer.application_capacity = 1
    elif change == "credentials":
        native.credentials.set("changed-backup", "changed-restore")
    elif change == "expired":
        native.plans[plan["token"]]["expires"] = time.monotonic() - 1
    else:
        real_slot(peer.files, 0, bytes.fromhex("7fc00000"))
    result = await native.apply_wire(**applying(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert not mutations(peer) and not native.storage.receipts()


async def test_wire_lost_commit_ack_reconciles_after_restart_without_second_restore(native_link):
    peer, bacnet, store, native, _ = native_link
    _, plan = await wire_review(native_link)
    peer.mode = "drop-end"
    result = await native.apply_wire(**applying(plan))
    assert result["pending"] and result["result"]["status"] == "unknown"
    before = list(mutations(peer))
    peer.mode = "normal"
    await native.close()
    restarted = NativeApplications(bacnet, store, native.instances, request_timeout=0.1, gap=0)
    try:
        verified = await restarted.reconcile(
            operation_id="native-wire-readback-restart", receipt_id=result["intent"]["id"]
        )
        assert not verified["pending"] and verified["latest_readback"]["status"] == "verified", (
            verified
        )
        assert mutations(peer) == before
        assert verified["latest_readback"]["preservation"]["selected_wire"]["source_ref"] == B
    finally:
        await restarted.close()


@pytest.mark.parametrize("mode", ["bad-crc", "changed-saved", "changed-native", "retained-wire"])
async def test_acknowledged_restore_requires_full_native_and_saved_readback(native_link, mode):
    peer, _, _, native, _ = native_link
    _, plan = await wire_review(native_link)
    initial = peer.files[3]
    original = peer.do_ReinitializeDeviceRequest

    async def state(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) != "end-restore":
            return
        if mode == "bad-crc":
            self.files[12] = self.files[12][:-1] + bytes([self.files[12][-1] ^ 1])
        elif mode == "changed-saved":
            real_slot(self.files, 0, struct.pack(">f", 99))
        elif mode == "retained-wire":
            self.files[3] = initial
        else:
            self.files[3] = gzip.compress(
                gzip.decompress(self.files[3]).replace(
                    b"Opaque metadata retained", b"Unsafe metadata retained"
                ),
                mtime=0,
            )

    peer.do_ReinitializeDeviceRequest = types.MethodType(state, peer)
    result = await native.apply_wire(**applying(plan))
    assert (
        result["result"]["protocol_accepted"]
        and result["pending"]
        and result["result"]["status"] == "unknown"
    ), result
    assert mutations(peer).count(("state", "start-restore")) == 1 and native.has_pending()


async def test_wire_route_and_strict_confirmation_profiles_cannot_be_confused(native_link):
    peer, _, _, native, target = native_link
    body, plan = await wire_review(native_link)
    wrong = {
        "operation_id": "native-wrong-default",
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        "default_change_confirmed": True,
        "application_transfer_confirmed": True,
    }
    with pytest.raises(ValueError, match="different native transfer"):
        await native.apply_default(**wrong)
    plan = await native.preview_wire(**target, **body, operation_id="native-wire-preview-new")
    with pytest.raises(ValueError, match="Confirm"):
        await native.apply_wire(**applying(plan, wire_change_confirmed=False))
    assert not mutations(peer)
    # Exercise the router directly with the same qualified native service.
    from bms_tool.native_applications import native_application_router
    from fastapi import FastAPI

    http = FastAPI()
    http.include_router(native_application_router(native))
    with TestClient(http) as c:
        for value in [1, "true", None]:
            assert (
                c.post(
                    "/api/bacnet/controller/native-application/wire-source/transfer/apply",
                    json=applying(plan, wire_change_confirmed=value),
                ).status_code
                == 422
            )
        assert (
            c.post(
                "/api/bacnet/controller/native-application/wire-source/transfer/preview",
                json={**target, **body, "operation_id": "native-http-unknown", "new_instance": 20},
            ).status_code
            == 422
        )
    assert not mutations(peer)


@pytest.mark.parametrize("target_change", [False, True])
async def test_selected_source_and_target_configuration_guard_blocks_otherwise_valid_rewire(
    native_link, target_change
):
    peer, _, _, native, _ = native_link
    body, plan = await wire_review(native_link, configuration=True)
    for position in [27] if target_change else [17, 22]:
        real_slot(peer.files, position, (2).to_bytes(4, "big"))
    # Both sources remain compatible if changed together; the reviewed opaque configuration still changed.
    from bms_tool.moi_effective_wire import EffectiveWireCompiler

    assert EffectiveWireCompiler(peer.files).effective.inspect(REF)["available"]
    result = await native.apply_wire(**applying(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert "configuration changed after review" in str(result)
    assert not mutations(peer) and not native.storage.receipts()


async def test_routed_wire_transfer_pins_actual_station_and_verifies_full_payload(native_link):
    import asyncio

    from .test_native_default_transfer import NativeRouter

    peer, _, _, native, target = native_link
    address, port = target["address"].rsplit(":", 1)
    transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: NativeRouter((address, int(port))), local_addr=("127.0.0.1", 0)
    )
    routed = {"address": "3001:7", "device": "device,5136", "router": proxy.endpoint, "dnet": 3001}
    try:
        _, plan = await wire_review(native_link, target=routed)
        result = await native.apply_wire(**applying(plan))
        assert result["result"]["status"] == "verified" and not result["pending"], result
        assert result["intent"]["target"] == {k: v for k, v in routed.items() if k != "device"}
        assert not proxy.errors
        assert mutations(peer).count(("state", "start-restore")) == 1
    finally:
        transport.close()


@pytest.mark.parametrize(
    "field,value",
    [("operation_profile", "unsupported-profile"), ("wire_guard", None), ("wire_edit", None)],
)
async def test_unknown_or_malformed_wire_readback_evidence_is_refused_before_field_queries(
    native_link, field, value
):
    peer, _, _, native, _ = native_link
    _, plan = await wire_review(native_link)
    intent = {**plan, field: value}
    before = list(peer.events)
    with pytest.raises(ValueError):
        await native.verify(None, intent)
    assert peer.events == before and not mutations(peer)


async def test_noop_wire_preview_cannot_prepare_a_controller_restore(native_link):
    peer, _, _, native, target = native_link
    body, _ = await wire_review(native_link)
    with pytest.raises(ValueError, match="different existing native wire source"):
        await native.preview_wire(
            **target, **(body | {"source_ref": A}), operation_id="native-wire-noop-preview"
        )
    assert not mutations(peer) and not native.storage.receipts()


@pytest.mark.parametrize("kind", ["real", "boolean"])
async def test_wire_endpoint_cannot_apply_another_typed_native_plan(native_link, kind):
    from .test_native_boolean_transfer import boolean_review
    from .test_native_default_transfer import default_review

    peer, _, _, native, _ = native_link
    _, _, _, plan = await (boolean_review if kind == "boolean" else default_review)(native_link)
    with pytest.raises(ValueError, match="different native transfer"):
        await native.apply_wire(**applying(plan))
    assert not mutations(peer) and not native.storage.receipts()


def test_registered_wire_routes_require_token_and_strict_explicit_confirmation(tmp_path):
    from bms_tool.app import create_app

    with TestClient(create_app(tmp_path)) as client:
        path = "/api/bacnet/controller/native-application/wire-source/transfer/apply"
        assert client.post(path, json={}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        request = {
            "operation_id": "native-wire-http-closed",
            "token": "a" * 32,
            "review_sha256": "b" * 64,
            "wire_change_confirmed": True,
            "application_transfer_confirmed": True,
        }
        for alteration in [
            {"wire_change_confirmed": 1},
            {"application_transfer_confirmed": "true"},
            {"default_change_confirmed": True},
        ]:
            assert client.post(path, json=request | alteration, headers=headers).status_code == 422
        result = client.post(path, json=request, headers=headers)
        assert result.status_code == 422 and "already consumed" in result.json()["detail"]
        assert not client.get("/api/session").json()["field_network_open"]
