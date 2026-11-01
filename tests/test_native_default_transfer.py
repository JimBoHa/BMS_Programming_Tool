"""One-default native transfers against literal saved bytes and actual UDP peers."""

import asyncio
import copy
import gzip
import struct
import time
import types

import pytest
from bacpypes3.apdu import (
    APDU,
    APCISequence,
    AtomicReadFileRequest,
    AtomicWriteFileRequest,
    ConfirmedPrivateTransferRequest,
    ReadPropertyRequest,
    ReinitializeDeviceRequest,
)
from bacpypes3.pdu import PDU
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity
from bms_tool.mstp import header_crc
from bms_tool.native_applications import NativeApplications
from bms_tool.native_default_transfer import verify_default_preservation
from bms_tool.native_signal_compiler import SignalCompilerService
from fastapi.testclient import TestClient

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_signal_compiler import FIRST, SECOND, query, signal_files


def real_slot(files, position, payload):
    raw = bytearray(files[12])
    if position < 0:
        position += len(raw)
    raw[position : position + 5] = payload + bytes([header_crc(payload) ^ 255])
    files[12] = bytes(raw)


def controller_storage(peer, *, mode="consume", ref=FIRST, bits="3dcccccd"):
    """Author the storage outcome independently of the compiler's merge implementation."""
    original = peer.do_ReinitializeDeviceRequest

    async def state(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) != "end-restore":
            return
        if mode == "shrink":
            self.files[11], self.files[12] = self.files[11][:-32], self.files[12][:-10]
        elif mode != "retain":
            real_slot(self.files, -10 if ref == FIRST else -5, bytes.fromhex(bits))
        if mode == "other-saved":
            real_slot(self.files, 4, struct.pack(">f", 99))
        elif mode == "bad-crc":
            self.files[12] = self.files[12][:-1] + bytes([self.files[12][-1] ^ 1])
        elif mode == "unknown-record":
            self.files[3] = gzip.compress(
                gzip.decompress(self.files[3]).replace(b"opaque footer", b"unsafe footer"),
                mtime=0,
            )

    peer.do_ReinitializeDeviceRequest = types.MethodType(state, peer)


async def default_review(link, *, mode="consume", ref=FIRST, value="0.1", target=None):
    peer, _, _, service, original_target = link
    peer.files = signal_files()
    controller_storage(peer, mode=mode, ref=ref, bits="80000000" if value == "-0" else "3dcccccd")

    async def no_identity_collision(_):
        raise AssertionError("A default edit must not allocate or scan for a Device instance.")

    service.instances._collision = no_identity_collision
    target = target or original_target
    captured = await service.capture(**target, operation_id="native-default-capture")
    source = SignalCompilerService(service.storage).source(captured["id"])
    proposal = query(source, ref=ref, value=value)
    plan = await service.preview_default(
        **target, operation_id="native-default-preview", **proposal
    )
    return captured, source, proposal, plan


def apply_request(plan):
    return {
        "operation_id": "native-default-apply",
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        "default_change_confirmed": True,
        "application_transfer_confirmed": True,
    }


def mutations(peer):
    return [
        row
        for row in peer.events
        if row[0] == "write" or (row[0] == "state" and "restore" in row[1])
    ]


@pytest.mark.parametrize("mode", ["consume", "shrink"])
@pytest.mark.parametrize("ref,value,bits", [(FIRST, "0.1", "3dcccccd"), (SECOND, "-0", "80000000")])
async def test_udp_default_transfer_preserves_fresh_other_settings_and_exact_identity(
    native_link, mode, ref, value, bits
):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await default_review(native_link, mode=mode, ref=ref, value=value)
    # This different saved setting changes after review and must be merged, not lost.
    real_slot(peer.files, 4, struct.pack(">f", 9.25))
    original = copy.deepcopy(peer.files)

    def durable_before_block():
        (receipt,) = service.storage.receipts()
        assert receipt["pending"]
        assert (
            service.storage.directory / receipt["intent"]["backup_id"] / "reviewed-application.bin"
        ).is_file()
        assert receipt["intent"]["change_kind"] == "signal-default"
        assert any(event["stage"] == "dispatch-application-block" for event in receipt["events"])

    peer.dispatch = durable_before_block
    result = await service.apply_default(**apply_request(plan))
    assert result["result"]["status"] == "verified", result
    assert not result["pending"] and result["result"]["protocol_accepted"]
    checked = result["result"]["preservation"]
    assert (
        checked["identity_unchanged"] and checked["application_identical_except_selected_default"]
    )
    assert checked["selected_default"]["effective_bits"] == bits
    archive = MoiIdentity(peer.files[3])
    assert archive.instance == 5136 and archive.summary()["name"] == "Authored controller"
    assert archive.reader.scalar(archive.root, 900) == 9.25
    _, original_files = service.storage.load(result["intent"]["backup_id"])
    assert original_files == original
    assert result["intent"]["payload_sha256"] != plan["payload_sha256"]
    assert mutations(peer).count(("state", "start-restore")) == 1
    assert mutations(peer).count(("state", "end-restore")) == 1
    assert all(row[1] == 3 for row in mutations(peer) if row[0] == "write")
    before = list(mutations(peer))
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_default(**apply_request(plan))
    assert mutations(peer) == before


@pytest.mark.parametrize(
    "change", ["selected", "application", "directory", "capacity", "credentials", "expired"]
)
async def test_fresh_preflight_refuses_changed_selected_value_or_source_without_restore(
    native_link, change
):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await default_review(native_link)
    if change == "selected":
        real_slot(peer.files, -10, struct.pack(">f", 43))
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
    result = await service.apply_default(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert not mutations(peer) and not service.storage.receipts()
    if change == "selected":
        assert "selected effective default changed" in str(result)


@pytest.mark.parametrize("mode", ["retain", "other-saved", "bad-crc", "unknown-record"])
async def test_acknowledged_restore_does_not_verify_wrong_effective_or_other_saved_values(
    native_link, mode
):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await default_review(native_link, mode=mode)
    result = await service.apply_default(**apply_request(plan))
    assert result["result"]["status"] == "unknown", result
    assert result["result"]["protocol_accepted"] and result["pending"]
    assert result["result"]["may_have_applied"]
    assert mutations(peer).count(("state", "start-restore")) == 1
    assert service.has_pending()


async def test_lost_commit_ack_is_resolved_after_service_restart_without_replay(native_link):
    peer, bacnet, store, service, _ = native_link
    _, _, _, plan = await default_review(native_link)
    peer.mode = "drop-end"
    result = await service.apply_default(**apply_request(plan))
    assert result["pending"] and result["result"]["status"] == "unknown"
    original_mutations = mutations(peer)
    peer.mode = "normal"
    restarted = NativeApplications(bacnet, store, service.instances, request_timeout=0.1, gap=0)
    try:
        resolved = await restarted.reconcile(
            operation_id="native-default-reconcile", receipt_id=result["intent"]["id"]
        )
        assert not resolved["pending"] and resolved["latest_readback"]["status"] == "verified", (
            resolved
        )
        assert (
            resolved["latest_readback"]["preservation"]["selected_default"]["effective_bits"]
            == "3dcccccd"
        )
        assert mutations(peer) == original_mutations
    finally:
        await restarted.close()


async def test_wrong_operation_route_and_missing_confirmation_cannot_send(native_link):
    peer, _, _, service, target = native_link
    _, source, proposal, plan = await default_review(native_link)
    with pytest.raises(ValueError, match="different native transfer"):
        await service.apply(
            **{k: v for k, v in apply_request(plan).items() if k != "default_change_confirmed"},
            allocation_confirmed=True,
        )
    plan = await service.preview_default(**target, operation_id="default-second-review", **proposal)
    with pytest.raises(ValueError, match="Confirm"):
        await service.apply_default(**(apply_request(plan) | {"default_change_confirmed": False}))
    assert not mutations(peer)
    with pytest.raises(ValueError, match="different effective"):
        await service.preview_default(
            **target, operation_id="default-no-op-review", **(proposal | {"value_text": "42"})
        )
    with pytest.raises(ValueError, match="snapshot changed"):
        await service.preview_default(
            **target,
            operation_id="default-stale-review",
            **(proposal | {"snapshot_sha256": "0" * 64}),
        )
    assert not mutations(peer) and source["controller_write"] is False


async def test_journal_size_failure_before_restore_is_not_sent(native_link, monkeypatch):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await default_review(native_link)
    original = service.storage.intent

    def oversized(body):
        return original(body | {"oversized": "x" * (128 * 1024)})

    monkeypatch.setattr(service.storage, "intent", oversized)
    result = await service.apply_default(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"]
    assert "readable evidence limit" in str(result) and not mutations(peer)
    assert not service.storage.receipts()


class NativeRouter(asyncio.DatagramProtocol):
    """Literal routed envelope proxy; native service payloads are forwarded unchanged."""

    def __init__(self, upstream):
        self.upstream = upstream
        self.clients = {}
        self.requests = []
        self.responses = []
        self.errors = []

    def connection_made(self, transport):
        self.transport = transport
        host, port = transport.get_extra_info("sockname")
        self.endpoint = f"{host}:{port}"

    def datagram_received(self, frame, source):
        try:
            assert frame[:2] == b"\x81\x0a" and int.from_bytes(frame[2:4], "big") == len(frame)
            npdu = frame[4:]
            if source == self.upstream:
                assert npdu[:2] == b"\x01\x00"
                apdu = npdu[2:]
                recipient = self.clients.pop(apdu[1])
                payload = b"\x01\x08" + struct.pack(">H", 3001) + b"\x01\x07" + apdu
                self.responses.append(frame.hex())
            else:
                assert npdu[:7] == b"\x01\x24" + struct.pack(">H", 3001) + b"\x01\x07\xff"
                apdu = npdu[7:]
                request = APCISequence.decode(APDU.decode(PDU(apdu)))
                assert isinstance(
                    request,
                    (
                        ReadPropertyRequest,
                        AtomicReadFileRequest,
                        AtomicWriteFileRequest,
                        ConfirmedPrivateTransferRequest,
                        ReinitializeDeviceRequest,
                    ),
                )
                assert not request.apduSeg
                self.clients[request.apduInvokeID] = source
                self.requests.append({"type": type(request).__name__, "frame": frame.hex()})
                payload = b"\x01\x04" + apdu
                recipient = self.upstream
            self.transport.sendto(
                b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload, recipient
            )
        except Exception as error:
            self.errors.append(repr(error))


async def test_explicit_router_dnet_mac_native_default_transfer_uses_original_udp_envelopes(
    native_link,
):
    peer, _, _, service, target = native_link
    host, port = target["address"].split(":")
    transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
    )
    routed = target | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
    try:
        _, _, _, plan = await default_review(native_link, target=routed)
        result = await service.apply_default(**apply_request(plan))
        assert result["result"]["status"] == "verified", result
        assert result["intent"]["target"] == {k: routed[k] for k in ("address", "router", "dnet")}
        assert not proxy.errors and not proxy.clients
        assert len(proxy.requests) == len(proxy.responses)
        assert any(row["type"] == "AtomicWriteFileRequest" for row in proxy.requests)
        assert mutations(peer).count(("state", "start-restore")) == 1
    finally:
        transport.close()
        await asyncio.sleep(0.02)


def test_incomplete_default_readback_is_refused():
    with pytest.raises(ValueError, match="complete"):
        verify_default_preservation(signal_files(), {}, {})


def test_http_default_transfer_admission_is_strict_and_opens_no_interface(tmp_path):
    app = create_app(tmp_path)
    prefix = "/api/bacnet/controller/native-application/signal-default/transfer"
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        headers = {"X-Studio-Token": token}
        preview = {
            "operation_id": "strict-default-preview",
            "address": "127.0.0.1:47808",
            "device": "device,5136",
            "capture_id": "a" * 32,
            "snapshot_sha256": "b" * 64,
            "record_ref": FIRST,
            "encoded_sha256": "c" * 64,
            "value_text": "0.1",
        }
        apply = {
            "operation_id": "strict-default-apply",
            "token": "a" * 32,
            "review_sha256": "b" * 64,
            "default_change_confirmed": True,
            "application_transfer_confirmed": True,
        }
        for route, body in [("/preview", preview), ("/apply", apply)]:
            assert client.post(prefix + route, json=body).status_code == 403
        for body in [preview | {"new_instance": 5336}, preview | {"value_text": 1.2}]:
            assert client.post(prefix + "/preview", headers=headers, json=body).status_code == 422
        for body in [
            apply | {"default_change_confirmed": "true"},
            apply | {"allocation_confirmed": True},
        ]:
            assert client.post(prefix + "/apply", headers=headers, json=body).status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False
        assert not app.state.native_applications.storage.receipts()


async def test_default_review_requires_exact_capture_route_and_operation_kind(native_link):
    peer, _, _, service, target = native_link
    _, _, proposal, _ = await default_review(native_link)
    before = list(peer.events)
    with pytest.raises(ValueError, match="exact controller route"):
        await service.preview_default(
            **(target | {"address": "127.0.0.1:1"}), operation_id="wrong-source-route", **proposal
        )
    assert peer.events == before
    name = await service.preview(
        **target,
        operation_id="name-review-next",
        capture_id=proposal["capture_id"],
        new_instance=5136,
        new_name="New authored name",
    )
    with pytest.raises(ValueError, match="different native transfer"):
        await service.apply_default(**apply_request(name))
    assert not mutations(peer)


async def test_expiry_during_fresh_default_backup_never_enters_restore(native_link, monkeypatch):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await default_review(native_link)
    original = service.capture_session
    held = service.plans[plan["token"]]

    async def expires(*args, **kwargs):
        result = await original(*args, **kwargs)
        held["expires"] = 0
        return result

    monkeypatch.setattr(service, "capture_session", expires)
    result = await service.apply_default(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"]
    assert not mutations(peer) and not service.storage.receipts()


async def test_unknown_default_evidence_version_is_refused_before_any_read(native_link):
    peer, _, _, service, _ = native_link
    before = list(peer.events)
    with pytest.raises(ValueError, match="evidence version"):
        await service.verify(
            {}, {"change_kind": "signal-default", "operation_profile": "future/99"}
        )
    assert peer.events == before


async def test_cancel_after_restore_dispatch_retains_unknown_without_file_blocks(
    native_link, monkeypatch
):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await default_review(native_link)
    original = peer.do_ReinitializeDeviceRequest

    async def cancel_during_state(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) == "start-restore":
            service.cancel("native-default-apply")

    monkeypatch.setattr(
        peer, "do_ReinitializeDeviceRequest", types.MethodType(cancel_during_state, peer)
    )
    result = await service.apply_default(**apply_request(plan))
    assert result["pending"] and result["result"]["status"] == "unknown"
    assert result["result"]["may_have_applied"]
    assert mutations(peer) == [("state", "start-restore")]
