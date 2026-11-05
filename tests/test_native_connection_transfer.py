"""Authored UDP connection append, guarded fresh settings and durable readback."""

import asyncio
import copy
import gzip
import struct
import time
import types

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_applications import NativeApplications, native_application_router
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_connection_compiler import EffectiveConnectionService
from bms_tool.native_connection_transfer import (
    PROFILE,
    verify_connection_preservation,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .test_moi_wire_sources import REF, A, B, C, D
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_connection_compiler import connection_files, proposal
from .test_native_default_transfer import NativeRouter, mutations, real_slot
from .test_native_signal_compiler import slot
from .test_native_wire_compiler import BOOLEAN

BASE = "/api/bacnet/controller/native-application/matching-connection/transfer"


def applying(plan, **changes):
    return {
        "operation_id": "native-connection-apply",
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        "connection_change_confirmed": True,
        "application_transfer_confirmed": True,
        **changes,
    }


async def connection_review(link, *, target=None, configuration=False, **formats):
    peer, _, _, native, original_target = link
    peer.files = connection_files(target_class=538, **formats)
    if configuration:
        for instance, cid in [(10, 551), (11, 551), (12, 538), (13, 538)]:
            peer.files[11] += slot((2 << 22) | instance, cid, 65000, 2, len(peer.files[12]))
            payload = (1).to_bytes(4, "big")
            peer.files[12] += payload + bytes([header_crc(payload) ^ 255])
    peer.metadata["object-name"] = "Authored native wire controller"

    async def no_collision(_):
        pytest.fail("A connection append must not allocate or scan Device identities")

    native.instances._collision = no_collision
    target = target or original_target
    capture = await native.capture(**target, operation_id="native-connection-capture")
    snapshot, _ = native.storage.load(capture["id"])
    service = EffectiveConnectionService(NativeBackupRecords(native.storage))
    query = {
        "capture_id": capture["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
        "source_sha256": sha(peer.files[3]),
        "diagram_ref": REF,
        "record_sha256": MoiIdentity(peer.files[3]).reader.records[REF]["sha256"],
        "prototype_index": 0,
        "source_ref": None,
    }
    body = proposal(service, query)
    plan = await native.preview_connection(
        **target, **body, operation_id="native-connection-preview"
    )
    return body, plan


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("metadata", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
async def test_udp_append_keeps_fresh_defaults_members_order_continuation_and_durable_original(
    native_link, compressed, metadata, diagram_class
):
    peer, _, _, native, _ = native_link
    body, plan = await connection_review(
        native_link, compressed=compressed, metadata=metadata, diagram_class=diagram_class
    )
    real_slot(peer.files, 0, struct.pack(">f", 45))
    raw = bytearray(peer.files[12])
    raw[10:12] = b"\x00" + bytes([header_crc(b"\x00") ^ 255])
    peer.files[12] = bytes(raw)
    original = copy.deepcopy(peer.files)

    def durable():
        (receipt,) = native.storage.receipts()
        assert receipt["pending"] and receipt["intent"]["change_kind"] == "connection"
        folder = native.storage.directory / receipt["intent"]["backup_id"]
        assert (folder / "reviewed-application.bin").is_file()
        assert native.storage.load(receipt["intent"]["backup_id"])[1] == original
        assert any(r["stage"] == "dispatch-application-block" for r in receipt["events"])

    peer.dispatch = durable
    result = await native.apply_connection(**applying(plan))
    assert result["result"]["status"] == "verified" and not result["pending"], result
    assert result["intent"]["operation_profile"] == PROFILE
    assert result["intent"]["payload_sha256"] != plan["payload_sha256"]
    observed = MoiIdentity(peer.files[3])
    wires = observed.reader.diagram(REF)["connections"]
    assert len(wires) == 2 and wires[1]["source_ref"] == A and wires[1]["target_ref"] == D
    assert observed.reader.scalar(observed.reader.records[A], 3113) == 45
    assert observed.reader.scalar(observed.reader.records[B], 3113) == 17
    assert observed.reader.scalar(observed.reader.records[BOOLEAN], 3113) is False
    preservation = result["result"]["preservation"]
    assert preservation["selected_connection"]["new"] == [0, 85, 3, 7000]
    assert preservation["selected_connection"]["effective_connection_verified"]
    assert (
        preservation["identity_unchanged"]
        and preservation["other_merged_application_bytes_preserved"]
    )
    assert mutations(peer).count(("state", "start-restore")) == 1
    assert mutations(peer).count(("state", "end-restore")) == 1
    assert all(r[1] == 3 for r in mutations(peer) if r[0] == "write")
    assert not result["intent"].get("recovery_origin")
    verify_connection_preservation(original, peer.files, body, result["intent"]["connection_guard"])
    before = list(mutations(peer))
    with pytest.raises(ValueError, match="consumed"):
        await native.apply_connection(**applying(plan))
    assert mutations(peer) == before
    status = native.status()
    assert status["matching_connection_transfer_profile"] == PROFILE
    assert status["receipts"][0]["connection_edit"] == body


@pytest.mark.parametrize(
    "change", ["application", "directory", "capacity", "credentials", "expired", "nonfinite", "crc"]
)
async def test_fresh_preflight_refuses_drift_before_any_restore(native_link, change):
    peer, _, _, native, _ = native_link
    _, plan = await connection_review(native_link)
    if change == "application":
        peer.files[3] = gzip.compress(
            gzip.decompress(peer.files[3]).replace(
                b"Opaque metadata retained", b"Changed metadata retained"
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
    elif change == "nonfinite":
        real_slot(peer.files, 0, bytes.fromhex("7fc00000"))
    else:
        peer.files[12] = peer.files[12][:-1] + bytes([peer.files[12][-1] ^ 1])
    result = await native.apply_connection(**applying(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert not mutations(peer) and not native.storage.receipts()


@pytest.mark.parametrize("positions", [(17,), (27,), (32,), (17, 22), (27, 32)])
async def test_selected_and_prototype_configurations_remain_guarded(native_link, positions):
    peer, _, _, native, _ = native_link
    _, plan = await connection_review(native_link, configuration=True)
    for position in positions:
        real_slot(peer.files, position, (2).to_bytes(4, "big"))
    result = await native.apply_connection(**applying(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert "configuration changed after review" in str(result)
    assert not mutations(peer) and not native.storage.receipts()


async def test_other_member_configuration_can_advance_and_remains_preserved(native_link):
    peer, _, _, native, _ = native_link
    _, plan = await connection_review(native_link, configuration=True)
    real_slot(peer.files, 22, (2).to_bytes(4, "big"))
    result = await native.apply_connection(**applying(plan))
    assert result["result"]["status"] == "verified" and not result["pending"], result
    actual = MoiIdentity(peer.files[3])
    assert actual.reader.scalar(actual.reader.records[B], 65000) == 2
    assert actual.reader.scalar(actual.reader.records[A], 65000) == 1


@pytest.mark.parametrize(
    "change",
    ["device", "address", "snapshot", "record", "source", "occupied-target", "count", "prototype"],
)
async def test_review_refuses_wrong_source_or_route_before_querying_controller(native_link, change):
    peer, _, _, native, target = native_link
    body, _ = await connection_review(native_link)
    options = {**target, **body, "operation_id": "native-connection-wrong-source"}
    if change == "device":
        options["device"] = "device,5137"
    elif change == "address":
        options["address"] = "127.0.0.1:1"
    elif change == "snapshot":
        options["snapshot_sha256"] = "f" * 64
    elif change == "record":
        options["record_sha256"] = "f" * 64
    elif change == "source":
        options["source_ref"] = B
    elif change == "occupied-target":
        options["target_ref"] = C
    elif change == "count":
        options["connection_count"] = 2
    else:
        options["prototype_old"] = [1, 85, 2, 7000]
    before = list(peer.events)
    with pytest.raises(ValueError):
        await native.preview_connection(**options)
    assert peer.events == before and not mutations(peer) and not native.storage.receipts()


async def test_changed_retained_plan_is_refused_before_any_field_query(native_link):
    peer, _, _, native, _ = native_link
    _, plan = await connection_review(native_link)
    native.plans[plan["token"]]["body"]["compilation"]["compiled_native_sha256"] = "f" * 64
    before = list(peer.events)
    with pytest.raises(ValueError, match="retained native connection review changed"):
        await native.apply_connection(**applying(plan))
    assert peer.events == before and not mutations(peer) and not native.storage.receipts()


@pytest.mark.parametrize("kind", ["real", "boolean", "enum", "wire", "point-name"])
async def test_connection_endpoint_cannot_apply_another_native_operation_review(native_link, kind):
    from .test_native_boolean_transfer import boolean_review
    from .test_native_default_transfer import default_review
    from .test_native_enum_transfer import enum_review
    from .test_native_point_names import name_review
    from .test_native_wire_transfer import wire_review

    peer, _, _, native, _ = native_link
    prepare = {
        "real": default_review,
        "boolean": boolean_review,
        "enum": enum_review,
        "wire": wire_review,
        "point-name": name_review,
    }[kind]
    plan = (await prepare(native_link))[-1]
    before = list(peer.events)
    with pytest.raises(ValueError, match="different native transfer"):
        await native.apply_connection(**applying(plan))
    assert peer.events == before and not mutations(peer) and not native.storage.receipts()


@pytest.mark.parametrize("mode", ["drop-start", "drop-block", "drop-end"])
async def test_dropped_ack_stays_uncertain_without_restore_retry(native_link, mode):
    peer, bacnet, store, native, _ = native_link
    _, plan = await connection_review(native_link)
    peer.mode = mode
    result = await native.apply_connection(**applying(plan))
    assert result["pending"] and result["result"]["status"] == "unknown", result
    assert mutations(peer).count(("state", "start-restore")) == 1
    assert mutations(peer).count(("state", "end-restore")) <= 1
    before = list(mutations(peer))
    peer.mode = "normal"
    await native.close()
    restarted = NativeApplications(bacnet, store, native.instances, request_timeout=0.1, gap=0)
    try:
        if mode == "drop-end":
            verified = await restarted.reconcile(
                operation_id="native-connection-readback", receipt_id=result["intent"]["id"]
            )
            assert not verified["pending"] and verified["latest_readback"]["status"] == "verified"
            assert (
                verified["latest_readback"]["preservation"]["selected_connection"]["target_ref"]
                == D
            )
        else:
            assert restarted.has_pending()
        assert mutations(peer) == before
    finally:
        await restarted.close()


@pytest.mark.parametrize(
    "mode", ["bad-crc", "changed-saved", "changed-native", "retained-original"]
)
async def test_commit_ack_requires_exact_native_connection_and_saved_readback(native_link, mode):
    peer, _, _, native, _ = native_link
    _, plan = await connection_review(native_link)
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
        elif mode == "retained-original":
            self.files[3] = initial
        else:
            self.files[3] = gzip.compress(
                gzip.decompress(self.files[3]).replace(
                    b"Opaque metadata retained", b"Changed metadata retained"
                ),
                mtime=0,
            )

    peer.do_ReinitializeDeviceRequest = types.MethodType(state, peer)
    result = await native.apply_connection(**applying(plan))
    assert result["result"]["protocol_accepted"]
    assert result["pending"] and result["result"]["status"] == "unknown", result
    assert mutations(peer).count(("state", "start-restore")) == 1


async def test_original_image_recovery_is_distinct_from_appending_connection(native_link):
    peer, _, _, native, _ = native_link
    _, plan = await connection_review(native_link)
    original_image, _ = ParameterApplication(
        peer.files[3], peer.files[11], peer.files[12]
    ).compile()
    original = peer.do_ReinitializeDeviceRequest

    async def state(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) == "end-restore":
            self.files[3] = original_image

    peer.do_ReinitializeDeviceRequest = types.MethodType(state, peer)
    result = await native.apply_connection(**applying(plan))
    assert not result["pending"] and result["result"]["status"] == "recovered_original", result
    assert result["result"]["proposed_change_verified"] is False
    assert len(MoiIdentity(peer.files[3]).reader.diagram(REF)["connections"]) == 1
    assert mutations(peer).count(("state", "start-restore")) == 1


async def test_routed_append_retains_exact_station_and_device(native_link):
    peer, _, _, native, target = native_link
    address, port = target["address"].rsplit(":", 1)
    transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: NativeRouter((address, int(port))), local_addr=("127.0.0.1", 0)
    )
    routed = {"address": "3001:7", "device": "device,5136", "router": proxy.endpoint, "dnet": 3001}
    try:
        _, plan = await connection_review(native_link, target=routed)
        result = await native.apply_connection(**applying(plan))
        assert result["result"]["status"] == "verified" and not result["pending"], result
        assert result["intent"]["target"] == {k: v for k, v in routed.items() if k != "device"}
        assert not proxy.errors and mutations(peer).count(("state", "start-restore")) == 1
    finally:
        transport.close()


@pytest.mark.parametrize("key", ["operation_profile", "connection_edit", "connection_guard"])
async def test_malformed_or_future_evidence_is_refused_before_readback(native_link, key):
    peer, _, _, native, _ = native_link
    _, plan = await connection_review(native_link)
    events = list(peer.events)
    with pytest.raises(ValueError):
        await native.verify(None, {**plan, key: None})
    assert peer.events == events and not mutations(peer)


async def test_operation_and_confirmation_profiles_cannot_be_confused(native_link):
    peer, _, _, native, target = native_link
    body, plan = await connection_review(native_link)
    with pytest.raises(ValueError, match="different native transfer"):
        await native.apply_wire(
            **{k: v for k, v in applying(plan).items() if k != "connection_change_confirmed"},
            wire_change_confirmed=True,
        )
    plan = await native.preview_connection(
        **target, **body, operation_id="native-connection-preview-new"
    )
    with pytest.raises(ValueError, match="Confirm"):
        await native.apply_connection(**applying(plan, connection_change_confirmed=False))
    http = FastAPI()
    http.include_router(native_application_router(native))
    with TestClient(http) as client:
        for value in (1, "true", None):
            assert (
                client.post(
                    BASE + "/apply", json=applying(plan, connection_change_confirmed=value)
                ).status_code
                == 422
            )
        assert (
            client.post(
                BASE + "/preview",
                json={**target, **body, "operation_id": "native-http-unknown", "new_instance": 20},
            ).status_code
            == 422
        )
    assert not mutations(peer)


def test_registered_routes_require_session_token_and_strict_confirmation(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(BASE + "/apply", json={}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        request = applying({"token": "a" * 32, "review_sha256": "b" * 64})
        for change in (
            {"connection_change_confirmed": 1},
            {"application_transfer_confirmed": "true"},
            {"wire_change_confirmed": True},
        ):
            assert (
                client.post(BASE + "/apply", headers=headers, json=request | change).status_code
                == 422
            )
        assert not client.get("/api/session").json()["field_network_open"]
