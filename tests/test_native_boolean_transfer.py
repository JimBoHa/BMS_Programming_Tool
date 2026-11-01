"""One Boolean native restore, exact saved preservation, and no replay on uncertainty."""

import asyncio
import copy
import gzip
import struct
import time
import types

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity
from bms_tool.mstp import header_crc
from bms_tool.native_applications import NativeApplications
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_boolean_compiler import EffectiveBooleanService
from bms_tool.native_boolean_transfer import verify_boolean_preservation
from fastapi.testclient import TestClient

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_boolean_compiler import query
from .test_native_boolean_copies import FIRST, SECOND, boolean_files
from .test_native_default_transfer import NativeRouter, apply_request, mutations, real_slot


def boolean_slot(files, ref, value):
    raw = bytearray(files[12])
    position = len(raw) - (4 if ref == FIRST else 2)
    payload = bytes([int(value)])
    raw[position : position + 2] = payload + bytes([header_crc(payload) ^ 255])
    files[12] = bytes(raw)


def storage_outcome(peer, *, mode="consume", ref=FIRST, value=False):
    original = peer.do_ReinitializeDeviceRequest

    async def state(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) != "end-restore":
            return
        if mode == "shrink":
            self.files[11], self.files[12] = self.files[11][:-32], self.files[12][:-4]
        elif mode != "retain":
            boolean_slot(self.files, ref, value)
        if mode == "other-saved":
            real_slot(self.files, 4, struct.pack(">f", 99))
        elif mode == "bad-crc":
            self.files[12] = self.files[12][:-1] + bytes([self.files[12][-1] ^ 1])
        elif mode == "unknown-record":
            self.files[3] = gzip.compress(
                gzip.decompress(self.files[3]).replace(b"opaque footer", b"unsafe footer"), mtime=0
            )

    peer.do_ReinitializeDeviceRequest = types.MethodType(state, peer)


async def boolean_review(link, *, mode="consume", ref=FIRST, value=False, target=None):
    peer, _, _, service, original_target = link
    peer.files = boolean_files()
    storage_outcome(peer, mode=mode, ref=ref, value=value)

    async def no_collision(_):
        raise AssertionError("A Boolean default must not allocate or scan a Device instance.")

    service.instances._collision = no_collision
    target = target or original_target
    captured = await service.capture(**target, operation_id="native-boolean-capture")
    source = EffectiveBooleanService(NativeBackupRecords(service.storage)).source(
        {"capture_id": captured["id"], "snapshot_sha256": captured["snapshot_evidence_sha256"]}
    )
    proposal = query(source, ref=ref, value=value)
    plan = await service.preview_boolean_default(
        **target, operation_id="native-boolean-preview", **proposal
    )
    return captured, source, proposal, plan


@pytest.mark.parametrize("mode", ["consume", "shrink"])
@pytest.mark.parametrize("ref,value", [(FIRST, False), (SECOND, True)])
async def test_boolean_udp_transfer_preserves_other_fresh_settings_and_one_restore(
    native_link, mode, ref, value
):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await boolean_review(native_link, mode=mode, ref=ref, value=value)
    real_slot(peer.files, 4, struct.pack(">f", 9.25))
    other = SECOND if ref == FIRST else FIRST
    boolean_slot(peer.files, other, ref == FIRST)
    original = copy.deepcopy(peer.files)

    def durable():
        (receipt,) = service.storage.receipts()
        assert receipt["pending"] and receipt["intent"]["change_kind"] == "boolean-default"
        assert (
            service.storage.directory / receipt["intent"]["backup_id"] / "reviewed-application.bin"
        ).is_file()
        assert any(row["stage"] == "dispatch-application-block" for row in receipt["events"])

    peer.dispatch = durable
    result = await service.apply_boolean_default(**apply_request(plan))
    assert result["result"]["status"] == "verified" and not result["pending"], result
    assert result["intent"]["operation_profile"] == "native-effective-boolean-default-transfer/1"
    assert result["intent"]["payload_sha256"] != plan["payload_sha256"]
    selected = result["result"]["preservation"]["selected_default"]
    assert selected["effective_value"] is value and selected["after_value"] is value
    actual = MoiIdentity(peer.files[3])
    assert actual.reader.scalar(actual.root, 900) == 9.25 and actual.instance == 5136
    assert actual.reader.scalar(actual.reader.records[ref], 3113) is value
    assert actual.reader.scalar(actual.reader.records[other], 3113) is (ref == FIRST)
    assert service.storage.load(result["intent"]["backup_id"])[1] == original
    assert (
        mutations(peer).count(("state", "start-restore"))
        == mutations(peer).count(("state", "end-restore"))
        == 1
    )
    assert all(row[1] == 3 for row in mutations(peer) if row[0] == "write")
    before = list(mutations(peer))
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_boolean_default(**apply_request(plan))
    assert mutations(peer) == before


@pytest.mark.parametrize(
    "change", ["selected", "application", "directory", "capacity", "credentials", "expired"]
)
async def test_fresh_boolean_preflight_never_restores_changed_value_or_source(native_link, change):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await boolean_review(native_link)
    if change == "selected":
        boolean_slot(peer.files, FIRST, False)
    elif change == "application":
        peer.files[3] = gzip.compress(
            gzip.decompress(peer.files[3]).replace(b"opaque footer", b"unsafe footer"), mtime=0
        )
    elif change == "directory":
        peer.files[11] = peer.files[11].replace(b"saved", b"other")
    elif change == "capacity":
        peer.application_capacity = 1
    elif change == "credentials":
        service.credentials.set("changed-backup", "changed-restore")
    else:
        service.plans[plan["token"]]["expires"] = time.monotonic() - 1
    result = await service.apply_boolean_default(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert not mutations(peer) and not service.storage.receipts()
    if change == "selected":
        assert "selected effective Boolean default changed" in str(result)


@pytest.mark.parametrize("mode", ["retain", "other-saved", "bad-crc", "unknown-record"])
async def test_acknowledged_boolean_restore_does_not_verify_wrong_saved_or_native_bytes(
    native_link, mode
):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await boolean_review(native_link, mode=mode)
    result = await service.apply_boolean_default(**apply_request(plan))
    assert (
        result["result"]["protocol_accepted"]
        and result["pending"]
        and result["result"]["status"] == "unknown"
    ), result
    assert service.has_pending() and mutations(peer).count(("state", "start-restore")) == 1


async def test_boolean_lost_commit_ack_reconciles_after_restart_without_replay(native_link):
    peer, bacnet, store, service, _ = native_link
    _, _, _, plan = await boolean_review(native_link)
    peer.mode = "drop-end"
    result = await service.apply_boolean_default(**apply_request(plan))
    assert result["pending"] and result["result"]["status"] == "unknown"
    before = list(mutations(peer))
    peer.mode = "normal"
    await service.close()
    restarted = NativeApplications(bacnet, store, service.instances, request_timeout=0.1, gap=0)
    try:
        resolved = await restarted.reconcile(
            operation_id="boolean-reconcile-restart", receipt_id=result["intent"]["id"]
        )
        assert not resolved["pending"] and resolved["latest_readback"]["status"] == "verified", (
            resolved
        )
        assert (
            resolved["latest_readback"]["preservation"]["selected_default"]["effective_value"]
            is False
        )
        assert mutations(peer) == before
    finally:
        await restarted.close()


async def test_boolean_preview_apply_routes_confirmations_and_archive_hash_are_strict(native_link):
    peer, _, _, service, target = native_link
    _, _, proposal, plan = await boolean_review(native_link)
    with pytest.raises(ValueError, match="different native transfer"):
        await service.apply_default(**apply_request(plan))
    plan = await service.preview_boolean_default(
        **target, operation_id="boolean-second-preview", **proposal
    )
    with pytest.raises(ValueError, match="Confirm"):
        await service.apply_boolean_default(
            **(apply_request(plan) | {"default_change_confirmed": False})
        )
    with pytest.raises(ValueError, match="different effective"):
        await service.preview_boolean_default(
            **target, operation_id="boolean-noop-preview", **(proposal | {"value": True})
        )
    with pytest.raises(ValueError, match="archive changed"):
        await service.preview_boolean_default(
            **target,
            operation_id="boolean-stale-archive",
            **(proposal | {"source_sha256": "0" * 64}),
        )
    assert not mutations(peer)


async def test_boolean_explicit_router_dnet_mac_uses_actual_udp_envelopes(native_link):
    peer, _, _, service, target = native_link
    host, port = target["address"].split(":")
    transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
    )
    try:
        routed = target | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
        _, _, _, plan = await boolean_review(native_link, target=routed)
        result = await service.apply_boolean_default(**apply_request(plan))
        assert result["result"]["status"] == "verified", result
        assert (
            not proxy.errors and not proxy.clients and len(proxy.requests) == len(proxy.responses)
        )
        assert any(row["type"] == "AtomicWriteFileRequest" for row in proxy.requests)
        assert mutations(peer).count(("state", "start-restore")) == 1
    finally:
        transport.close()
        await asyncio.sleep(0.02)


async def test_unknown_boolean_profile_is_refused_before_reads(native_link):
    peer, _, _, service, _ = native_link
    before = list(peer.events)
    with pytest.raises(ValueError, match="evidence version"):
        await service.verify(
            {}, {"change_kind": "boolean-default", "operation_profile": "future/99"}
        )
    assert peer.events == before


def test_incomplete_boolean_readback_is_refused():
    with pytest.raises(ValueError, match="complete"):
        verify_boolean_preservation(boolean_files(), {}, {})


async def test_boolean_journal_failure_prevents_restore(native_link, monkeypatch):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await boolean_review(native_link)
    original = service.storage.intent

    def oversized(body):
        return original(body | {"oversized": "x" * (128 * 1024)})

    monkeypatch.setattr(service.storage, "intent", oversized)
    result = await service.apply_boolean_default(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"]
    assert not mutations(peer) and not service.storage.receipts()


async def test_boolean_expiry_during_fresh_backup_never_enters_restore(native_link, monkeypatch):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await boolean_review(native_link)
    original = service.capture_session
    held = service.plans[plan["token"]]

    async def expires(*args, **kwargs):
        result = await original(*args, **kwargs)
        held["expires"] = 0
        return result

    monkeypatch.setattr(service, "capture_session", expires)
    result = await service.apply_boolean_default(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"]
    assert not mutations(peer) and not service.storage.receipts()


async def test_boolean_cancel_after_restore_start_keeps_unknown_without_file_blocks(
    native_link, monkeypatch
):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await boolean_review(native_link)
    original = peer.do_ReinitializeDeviceRequest

    async def cancel_started(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) == "start-restore":
            service.cancel("native-default-apply")

    monkeypatch.setattr(
        peer, "do_ReinitializeDeviceRequest", types.MethodType(cancel_started, peer)
    )
    result = await service.apply_boolean_default(**apply_request(plan))
    assert result["pending"] and result["result"]["status"] == "unknown"
    assert result["result"]["may_have_applied"]
    assert mutations(peer) == [("state", "start-restore")]


async def test_boolean_source_route_and_wrong_real_review_refuse_without_wire(native_link):
    from .test_native_default_transfer import default_review

    peer, _, _, service, target = native_link
    _, _, proposal, _ = await boolean_review(native_link)
    before = list(peer.events)
    with pytest.raises(ValueError, match="exact controller route"):
        await service.preview_boolean_default(
            **(target | {"address": "127.0.0.1:1"}),
            operation_id="wrong-bool-source-route",
            **proposal,
        )
    assert peer.events == before
    _, _, _, real = await default_review(native_link)
    before = list(peer.events)
    with pytest.raises(ValueError, match="different native transfer"):
        await service.apply_boolean_default(**apply_request(real))
    assert peer.events == before and not mutations(peer)


def test_http_boolean_admission_rejects_numeric_bool_and_extra_fields_without_connecting(tmp_path):
    app = create_app(tmp_path)
    base = "/api/bacnet/controller/native-application/boolean-default/transfer"
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        body = {
            "operation_id": "boolean-preview-http",
            "address": "127.0.0.1:47808",
            "device": "device,5136",
            "capture_id": "a" * 32,
            "snapshot_sha256": "b" * 64,
            "source_sha256": "c" * 64,
            "record_ref": FIRST,
            "encoded_sha256": "d" * 64,
            "value": False,
        }
        assert client.post(base + "/preview", json=body).status_code == 403
        for extra in [
            {"value": 0},
            {"value": "false"},
            {"value_text": "0"},
            {"new_instance": 5336},
        ]:
            assert (
                client.post(base + "/preview", json=body | extra, headers=headers).status_code
                == 422
            )
        assert (
            not client.get("/api/session").json()["field_network_open"]
            and not app.state.native_applications.storage.receipts()
        )
