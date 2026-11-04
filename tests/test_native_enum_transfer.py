"""Literal saved Enum storage and real authored UDP restore/readback evidence."""

import asyncio
import copy
import gzip
import struct
import time
import types

import pytest
from bms_tool.app import create_app
from bms_tool.moi_effective_enum import EffectiveEnumCompiler
from bms_tool.moi_identity import MoiIdentity
from bms_tool.mstp import header_crc
from bms_tool.native_applications import NativeApplications
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_enum_compiler import EffectiveEnumService
from bms_tool.native_enum_transfer import compile_enum_default, verify_enum_preservation
from fastapi.testclient import TestClient

from .native_capability_profiles import capability_profiles
from .test_moi_effective_enum import enum_files
from .test_moi_enum_defaults import REF
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import NativeRouter, apply_request, mutations, real_slot
from .test_native_enum_compiler import proposal


def enum_slot(files, value):
    """The independently authored selected slot is the final two payload bytes plus CRC."""
    payload = value.to_bytes(2, "big")
    files[12] = files[12][:-3] + payload + bytes([header_crc(payload) ^ 255])


def add_enum_states_slot(files, *, cid=528):
    """Independent fixed property931 slot before the final Default Value payload."""
    position = len(files[12]) - 3
    default = bytearray(files[11][-16:])
    assert int.from_bytes(default[12:14], "big") == position
    default[12:14] = (position + 3).to_bytes(2, "big")
    row = (
        b"\x00\x10"
        + ((19 << 22) | 1).to_bytes(4, "big")
        + b"\x03\xa3\x6f\x09"
        + cid.to_bytes(2, "big")
        + position.to_bytes(2, "big")
        + b"\x12\x34"
    )
    payload = b"\x01\x23"
    files[11] = files[11][:-16] + bytes(default) + row
    files[12] = files[12][:-3] + payload + bytes([header_crc(payload) ^ 255]) + files[12][-3:]


def enum_states_slot(files, value):
    payload = value.to_bytes(2, "big")
    position = len(files[12]) - 6
    files[12] = (
        files[12][:position]
        + payload
        + bytes([header_crc(payload) ^ 255])
        + files[12][position + 3 :]
    )


def enum_storage(peer, *, mode="consume", value=65535):
    original = peer.do_ReinitializeDeviceRequest

    async def state(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) != "end-restore":
            return
        if mode == "shrink":
            self.files[11], self.files[12] = self.files[11][:-16], self.files[12][:-3]
        elif mode != "retain":
            enum_slot(self.files, value)
        if mode == "other-saved":
            real_slot(self.files, 4, struct.pack(">f", 99))
        elif mode == "bad-crc":
            self.files[12] = self.files[12][:-1] + bytes([self.files[12][-1] ^ 1])
        elif mode == "unknown-record":
            image = MoiIdentity(self.files[3])
            changed = image.data.replace(b"opaque footer", b"unsafe footer")
            self.files[3] = gzip.compress(changed, mtime=0) if image.compressed else changed

    peer.do_ReinitializeDeviceRequest = types.MethodType(state, peer)


async def enum_review(
    link,
    *,
    mode="consume",
    value=65535,
    cid=528,
    compressed=True,
    target=None,
    slot=True,
    states_slot=False,
):
    peer, _, _, service, original_target = link
    peer.files = enum_files(cid=cid, compressed=compressed, slot=slot)
    if states_slot:
        add_enum_states_slot(peer.files, cid=cid)
    enum_storage(peer, mode=mode, value=value)

    async def no_collision(_):
        raise AssertionError("An Enum code edit must not allocate or scan a Device instance.")

    service.instances._collision = no_collision
    target = target or original_target
    captured = await service.capture(**target, operation_id="native-enum-capture")
    source = EffectiveEnumService(NativeBackupRecords(service.storage)).source(
        {"capture_id": captured["id"], "snapshot_sha256": captured["snapshot_evidence_sha256"]}
    )
    body = proposal(source, value)
    plan = await service.preview_enum_default(**target, operation_id="native-enum-preview", **body)
    return captured, source, body, plan


@pytest.mark.parametrize("cid", [528, 529])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("mode", ["consume", "shrink"])
@pytest.mark.parametrize("value", [0, 65535])
async def test_enum_udp_transfer_preserves_other_fresh_settings_and_durable_one_use_restore(
    native_link, cid, compressed, mode, value
):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await enum_review(
        native_link, cid=cid, compressed=compressed, mode=mode, value=value
    )
    real_slot(peer.files, 4, struct.pack(">f", 9.25))
    originals = copy.deepcopy(peer.files)

    def durable():
        (receipt,) = service.storage.receipts()
        intent = receipt["intent"]
        folder = service.storage.directory / intent["backup_id"]
        assert receipt["pending"] and intent["change_kind"] == "enum-default"
        assert intent["operation_profile"] == "native-effective-enum-default-transfer/1"
        assert intent["enum_semantics_verified"] is False
        assert (folder / "reviewed-application.bin").is_file()
        for key in (3, 11, 12):
            assert (folder / f"file-{key}.bin").read_bytes() == originals[key]
        assert any(row["stage"] == "dispatch-application-block" for row in receipt["events"])

    peer.dispatch = durable
    receipt = await service.apply_enum_default(**apply_request(plan))
    assert receipt["result"]["status"] == "verified" and not receipt["pending"], receipt
    assert receipt["result"]["protocol_accepted"]
    assert receipt["intent"]["payload_sha256"] != plan["payload_sha256"]
    proof = receipt["result"]["preservation"]
    assert proof["profile"] == "native-effective-enum-default-preservation/1"
    assert proof["identity_unchanged"] and proof["application_identical_except_selected_default"]
    assert proof["selected_default"]["effective_value"] == value
    assert type(proof["selected_default"]["effective_value"]) is int
    assert not proof["enum_semantics_verified"]
    actual = MoiIdentity(peer.files[3])
    prop = actual.reader.records[REF]["properties"][3113]
    assert (
        actual.data[prop["value_start_offset"] : prop["value_end_offset"]]
        == b"\x92" + value.to_bytes(2, "big") + b"\x2f"
    )
    assert actual.reader.scalar(actual.root, 900) == 9.25
    assert actual.reader.scalar(actual.root, 901) == 70000
    assert actual.reader.scalar(actual.reader.records[REF], 931) == 0x123
    assert actual.instance == 5136 and actual.summary()["name"] == "Authored controller"
    assert service.storage.load(receipt["intent"]["backup_id"])[1] == originals
    assert (
        mutations(peer).count(("state", "start-restore"))
        == mutations(peer).count(("state", "end-restore"))
        == 1
    )
    assert all(row[1] == 3 for row in mutations(peer) if row[0] == "write")
    before = list(mutations(peer))
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_enum_default(**apply_request(plan))
    assert mutations(peer) == before


@pytest.mark.parametrize(
    "change", ["selected", "application", "directory", "capacity", "credentials", "expired"]
)
async def test_fresh_enum_guard_never_restores_a_changed_selected_code_or_source(
    native_link, change
):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await enum_review(native_link)
    if change == "selected":
        enum_slot(peer.files, 42)
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
    result = await service.apply_enum_default(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert not mutations(peer) and not service.storage.receipts()
    if change == "selected":
        assert "selected effective Enum code changed" in str(result)


@pytest.mark.parametrize("mode", ["retain", "other-saved", "bad-crc", "unknown-record"])
async def test_acknowledged_enum_restore_does_not_verify_wrong_saved_or_native_bytes(
    native_link, mode
):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await enum_review(native_link, mode=mode)
    receipt = await service.apply_enum_default(**apply_request(plan))
    assert (
        receipt["result"]["protocol_accepted"]
        and receipt["pending"]
        and receipt["result"]["status"] == "unknown"
    ), receipt
    assert service.has_pending() and mutations(peer).count(("state", "start-restore")) == 1


async def test_enum_lost_commit_ack_reconciles_after_restart_without_replay(native_link):
    peer, bacnet, store, service, _ = native_link
    _, _, _, plan = await enum_review(native_link)
    peer.mode = "drop-end"
    receipt = await service.apply_enum_default(**apply_request(plan))
    assert receipt["pending"] and receipt["result"]["status"] == "unknown"
    before = list(mutations(peer))
    peer.mode = "normal"
    await service.close()
    restarted = NativeApplications(bacnet, store, service.instances, request_timeout=0.1, gap=0)
    try:
        resolved = await restarted.reconcile(
            operation_id="enum-reconcile-restart", receipt_id=receipt["intent"]["id"]
        )
        assert not resolved["pending"] and resolved["latest_readback"]["status"] == "verified", (
            resolved
        )
        assert (
            resolved["latest_readback"]["preservation"]["selected_default"]["effective_value"]
            == 65535
        )
        assert mutations(peer) == before
    finally:
        await restarted.close()


async def test_enum_explicit_router_dnet_mac_uses_actual_udp_envelopes(native_link):
    peer, _, _, service, target = native_link
    host, port = target["address"].split(":")
    transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
    )
    try:
        routed = target | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
        _, _, _, plan = await enum_review(native_link, cid=529, value=0, target=routed)
        receipt = await service.apply_enum_default(**apply_request(plan))
        assert receipt["result"]["status"] == "verified", receipt
        assert (
            not proxy.errors and not proxy.clients and len(proxy.requests) == len(proxy.responses)
        )
        assert any(row["type"] == "AtomicWriteFileRequest" for row in proxy.requests)
        assert mutations(peer).count(("state", "start-restore")) == 1
    finally:
        transport.close()
        await asyncio.sleep(0.02)


async def test_enum_local_uint32_without_selected_saved_slot_cannot_prepare_field_transfer(
    native_link,
):
    peer, _, _, service, _ = native_link
    with pytest.raises(ValueError, match="selected captured fixed Enum slot"):
        await enum_review(native_link, slot=False)
    assert not mutations(peer) and not service.plans and not service.storage.receipts()


async def test_enum_review_checks_source_route_code_confirmation_profile_and_datatype(native_link):
    peer, _, _, service, target = native_link
    _, _, body, plan = await enum_review(native_link)
    before = list(peer.events)
    with pytest.raises(ValueError, match="exact controller route"):
        await service.preview_enum_default(
            **(target | {"address": "127.0.0.1:1"}), operation_id="wrong-enum-route", **body
        )
    assert peer.events == before
    with pytest.raises(ValueError, match="different native transfer"):
        await service.apply_boolean_default(**apply_request(plan))
    for extra in (
        {"value": True},
        {"value": 1.0},
        {"value": "1"},
        {"value": -1},
        {"value": 65536},
        {"value": 513},
        {"source_sha256": "0" * 64},
    ):
        with pytest.raises(ValueError):
            await service.preview_enum_default(
                **target, operation_id="invalid-enum-code", **(body | extra)
            )
    plan = await service.preview_enum_default(**target, operation_id="enum-confirm-preview", **body)
    with pytest.raises(ValueError, match="Confirm"):
        await service.apply_enum_default(
            **(apply_request(plan) | {"default_change_confirmed": False})
        )
    before = list(peer.events)
    with pytest.raises(ValueError, match="evidence version"):
        await service.verify({}, {"change_kind": "enum-default", "operation_profile": "future/99"})
    assert peer.events == before and not mutations(peer)


async def test_enum_intent_failure_prevents_restore(native_link, monkeypatch):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await enum_review(native_link)
    original = service.storage.intent
    monkeypatch.setattr(
        service.storage, "intent", lambda body: original(body | {"oversized": "x" * (128 * 1024)})
    )
    receipt = await service.apply_enum_default(**apply_request(plan))
    assert receipt["result"]["status"] == "not_sent" and not receipt["pending"]
    assert not mutations(peer) and not service.storage.receipts()


async def test_enum_cancel_after_restore_start_retains_unknown_without_file_blocks(
    native_link, monkeypatch
):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await enum_review(native_link)
    original = peer.do_ReinitializeDeviceRequest

    async def cancel_started(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) == "start-restore":
            service.cancel("native-default-apply")

    monkeypatch.setattr(
        peer, "do_ReinitializeDeviceRequest", types.MethodType(cancel_started, peer)
    )
    receipt = await service.apply_enum_default(**apply_request(plan))
    assert receipt["pending"] and receipt["result"]["status"] == "unknown"
    assert receipt["result"]["may_have_applied"]
    assert mutations(peer) == [("state", "start-restore")]


@pytest.mark.parametrize("value", [0, 255, 256, 65535])
def test_pure_enum_transfer_preservation_and_incomplete_readback(value):
    files = enum_files()
    field = EffectiveEnumCompiler(files).fields()[0]
    edit = {"record_ref": REF, "encoded_sha256": field["encoded_sha256"], "value": value}
    output, _ = compile_enum_default(files, edit)
    after = files | {3: output}
    enum_slot(after, value)
    assert (
        verify_enum_preservation(files, after, edit)["selected_default"]["effective_value"] == value
    )
    with pytest.raises(ValueError, match="complete"):
        verify_enum_preservation(files, {}, edit)


def test_enum_http_admission_rejects_coercions_and_extra_authority_without_connecting(tmp_path):
    app = create_app(tmp_path)
    base = "/api/bacnet/controller/native-application/enum-default/transfer"
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        body = {
            "operation_id": "enum-preview-http",
            "address": "127.0.0.1:47808",
            "device": "device,5136",
            "capture_id": "a" * 32,
            "snapshot_sha256": "b" * 64,
            "source_sha256": "c" * 64,
            "record_ref": REF,
            "encoded_sha256": "d" * 64,
            "value": 65535,
        }
        assert client.post(base + "/preview", json=body).status_code == 403
        for extra in (
            {"value": True},
            {"value": 1.0},
            {"value": "1"},
            {"value_text": "1"},
            {"new_instance": 5336},
            {"recovery_parent_receipt": "e" * 32},
            {"expected_states_text_sha256": "0" * 64},
        ):
            assert (
                client.post(base + "/preview", json=body | extra, headers=headers).status_code
                == 422
            )
        assert not client.get("/api/session").json()["field_network_open"]
        assert not app.state.native_applications.storage.receipts()


@pytest.mark.parametrize(
    "context,expected",
    [
        ("direct", "preflight-required"),
        ("routed", "preflight-required"),
        ("serial", "transport-unavailable"),
        ("foreign", "transport-unavailable"),
        ("no-fixed-slot", "unsupported-source"),
        ("unknown-saved", "unsupported-source"),
        ("unverified", "source-mismatch"),
        ("wrong-vendor", "source-mismatch"),
    ],
)
def test_enum_source_capability_separates_actual_storage_identity_and_transport(
    tmp_path, context, expected
):
    from .test_native_backup_capabilities import operations, source

    files = enum_files(slot=context != "no-fixed-slot")
    metadata = {"connector_config": {"local_address": "127.0.0.1:47918"}}
    if context == "routed":
        metadata["target"] = {"address": "10", "router": "127.0.0.1:47919", "dnet": 200}
    elif context == "serial":
        metadata["connector_config"] = {"transport": "mstp", "serial_port": "/dev/authored-only"}
    elif context == "foreign":
        metadata["connector_config"]["bbmd_address"] = "127.0.0.1:47999"
    elif context == "unknown-saved":
        files[11], files[12] = b"Unknown directory", b"Opaque saved values"
    elif context == "unverified":
        metadata["source_identity_matches"] = False
    elif context == "wrong-vendor":
        metadata["identity"] = {
            "vendor-identifier": 99,
            "object-name": "Authored controller",
            "model-name": "UNLISTED-MODEL",
        }
    storage, records, request = source(tmp_path, files, **metadata)
    before = copy.deepcopy(storage.load(request["capture_id"]))
    legacy, current = capability_profiles(records, request)
    assert legacy["capability_profile"] == "native-backup-operation-capabilities/11"
    assert len(legacy["operations"]) == 22
    for report in (legacy, current):
        assert operations(report)["enum-default-transfer"]["status"] == expected
        if context == "no-fixed-slot":
            assert operations(report)["effective-enum-compile"]["status"] == "source-qualified"
            assert report["qualification"]["effective_enum_unknown_storage_count"] == 1
        assert operations(report)["enum-default-copy"]["status"] == "source-qualified"
        assert (
            not report["can_apply"]
            and not report["controller_queries"]
            and not report["qualification"]["enum_semantics_verified"]
        )
    for key in ("matching-connection-copy", "effective-connection-compile"):
        assert operations(current)[key]["status"] == "unsupported-source"
    assert storage.load(request["capture_id"]) == before and not storage.receipts()


async def test_enum_expiry_during_fresh_capture_never_enters_restore(native_link, monkeypatch):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await enum_review(native_link)
    original, held = service.capture_session, service.plans[plan["token"]]

    async def expires(*args, **kwargs):
        result = await original(*args, **kwargs)
        held["expires"] = 0
        return result

    monkeypatch.setattr(service, "capture_session", expires)
    receipt = await service.apply_enum_default(**apply_request(plan))
    assert receipt["result"]["status"] == "not_sent" and not receipt["pending"]
    assert not mutations(peer) and not service.storage.receipts()


@pytest.mark.parametrize("cid", [528, 529])
@pytest.mark.parametrize("compressed", [False, True])
async def test_changed_selected_saved_enum_states_metadata_refuses_restore(
    native_link, cid, compressed
):
    peer, _, _, service, _ = native_link
    _, source, _, plan = await enum_review(
        native_link, cid=cid, compressed=compressed, states_slot=True
    )
    assert (
        plan["compilation"]["states_text_encoded_sha256"]
        == source["fields"][0]["states_text_encoded_sha256"]
    )
    enum_states_slot(peer.files, 292)
    result = await service.apply_enum_default(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert "selected Enum state metadata changed" in str(result)
    assert not mutations(peer) and not service.storage.receipts()


@pytest.mark.parametrize("cid", [528, 529])
@pytest.mark.parametrize("value", [0, 65535])
async def test_unchanged_selected_enum_state_slot_preserves_other_fresh_values(
    native_link, cid, value
):
    peer, _, _, service, _ = native_link
    _, _, _, plan = await enum_review(native_link, cid=cid, value=value, states_slot=True)
    real_slot(peer.files, 4, struct.pack(">f", 9.25))
    result = await service.apply_enum_default(**apply_request(plan))
    assert result["result"]["status"] == "verified" and not result["pending"], result
    proof = result["result"]["preservation"]
    assert (
        proof["selected_default"]["states_text_encoded_sha256"]
        == plan["compilation"]["states_text_encoded_sha256"]
    )
    actual = MoiIdentity(peer.files[3])
    assert actual.reader.scalar(actual.reader.records[REF], 931) == 291
    assert actual.reader.scalar(actual.root, 900) == 9.25
