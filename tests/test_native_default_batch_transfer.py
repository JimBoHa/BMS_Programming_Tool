"""Actual mixed native defaults require fresh typed guards and full saved readback."""

import asyncio
import copy
import struct
import types

import pytest
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_default_batch import NativeDefaultBatch
from bms_tool.native_default_batch_transfer import (
    BatchTransferApply,
    compile_batch_defaults,
    validate_batch_evidence,
    verify_batch_preservation,
)

from .test_moi_enum_defaults import REF as UNSAVED_ENUM
from .test_moi_wire_sources import C, D
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_batch import SAVED_ENUM, batch_files, changes, local, request
from .test_native_default_transfer import mutations, real_slot
from .test_native_wire_compiler import BOOLEAN


def edits(opened):
    return [c for c in changes(opened) if c["record_ref"] != UNSAVED_ENUM]


def update_saved(files, *, compact=False, omit_kind=None):
    """Independent fixed PSS rows consume the defaults from actual restored File3."""
    app = MoiIdentity(files[3])
    selected = {}
    for ref, kind in [(C, "real"), (D, "real"), (BOOLEAN, "boolean"), (SAVED_ENUM, "enum")]:
        record = app.reader.records[ref]
        oid = int.from_bytes(app.data[record["offset"] + 6 : record["offset"] + 10], "big")
        selected[record["class_id"], oid & 4194303, 3113] = kind, app.reader.scalar(record, 3113)
    static, dynamic = bytearray(), bytearray()
    offset = 0
    while offset < len(files[11]):
        size = int.from_bytes(files[11][offset : offset + 2], "big")
        row = bytearray(files[11][offset : offset + size])
        assert size == 16 and row[8] in (0x6F, 0xEF)
        key = (
            int.from_bytes(row[10:12], "big"),
            int.from_bytes(row[2:6], "big") & 4194303,
            int.from_bytes(row[6:8], "big"),
        )
        width = {1: 1, 2: 4, 4: 4, 9: 2}[row[9]]
        start = int.from_bytes(row[12:14], "big")
        payload = files[12][start : start + width]
        if key in selected:
            kind, value = selected[key]
            if compact:
                offset += size
                continue
            if kind != omit_kind:
                payload = (
                    struct.pack(">f", value)
                    if kind == "real"
                    else bytes([int(value)])
                    if kind == "boolean"
                    else value.to_bytes(2, "big")
                )
        row[12:14] = len(dynamic).to_bytes(2, "big")
        static.extend(row)
        dynamic.extend(payload + bytes([header_crc(payload) ^ 255]))
        offset += size
    files[11], files[12] = bytes(static), bytes(dynamic)


def local_plan(tmp_path):
    storage, _, snapshot, query, opened = local(tmp_path)
    _, files = storage.load(snapshot["id"])
    body = request(query, opened, edits(opened))
    output, compilation = compile_batch_defaults(files, body)
    return files, body, output, compilation


@pytest.mark.parametrize("compact", [False, True])
def test_all_four_typed_values_and_full_other_bytes_survive_saved_directory_compaction(
    tmp_path, compact
):
    files, body, output, compilation = local_plan(tmp_path)
    after = {**files, 3: output}
    update_saved(after, compact=compact)
    proof = verify_batch_preservation(files, after, body, compilation["batch_guard"])
    assert proof["application_identical_except_selected_defaults"] and proof["identity_unchanged"]
    assert len(proof["selected_defaults"]) == 4 and all(
        f["effective_value_verified"] for f in proof["selected_defaults"]
    )
    assert not proof["enum_semantics_verified"] and not proof["controller_writes"]
    assert (
        next(f for f in proof["selected_defaults"] if f["record_ref"] == D)["after_bits"]
        == "80000000"
    )
    assert (
        next(f for f in proof["selected_defaults"] if f["kind"] == "enum")["after_value"] == 65535
    )


@pytest.mark.parametrize("kind", ["real", "boolean", "enum"])
def test_retained_old_saved_values_cannot_be_reported_as_verified(tmp_path, kind):
    files, body, output, compilation = local_plan(tmp_path)
    after = {**files, 3: output}
    update_saved(after, omit_kind=kind)
    with pytest.raises(ValueError, match="selected saved"):
        verify_batch_preservation(files, after, body, compilation["batch_guard"])


def test_other_fresh_settings_merge_without_relaxing_selected_guards(tmp_path):
    files, body, output, compilation = local_plan(tmp_path)
    fresh = dict(files)
    real_slot(fresh, 0, struct.pack(">f", 45))
    actual, c = compile_batch_defaults(
        fresh, body, fresh=True, expected_guard=compilation["batch_guard"]
    )
    assert actual != output and c["batch_guard"] == compilation["batch_guard"]
    app = MoiIdentity(actual)
    assert app.reader.scalar(app.reader.records["controller/575_1.2_10"], 3113) == 45
    after = {**fresh, 3: actual}
    update_saved(after)
    assert verify_batch_preservation(fresh, after, body, compilation["batch_guard"])[
        "identity_unchanged"
    ]


def test_unfixed_enum_is_local_only_and_not_promoted_into_transfer(tmp_path):
    storage, _, snapshot, query, opened = local(tmp_path)
    _, files = storage.load(snapshot["id"])
    with pytest.raises(ValueError, match="captured fixed"):
        compile_batch_defaults(files, request(query, opened))


@pytest.mark.parametrize("fault", ["missing", "kind", "encoding", "bits", "capacity", "authority"])
def test_changed_guards_refuse_fresh_compile_without_mutating_originals(tmp_path, fault):
    files, body, _, compilation = local_plan(tmp_path)
    original, guard = copy.deepcopy(files), copy.deepcopy(compilation["batch_guard"])
    if fault == "missing":
        guard["fields"].pop()
    if fault == "kind":
        guard["fields"][0]["kind"] = "boolean"
    if fault == "encoding":
        guard["fields"][0]["encoded_sha256"] = "0" * 64
    if fault == "bits":
        guard["fields"][0]["prior_bits"] = "00000000"
    if fault == "capacity":
        guard["fields"][-1]["saved_storage"]["maximum_code"] = 4294967295
    if fault == "authority":
        guard["can_apply"] = True
    with pytest.raises(ValueError):
        compile_batch_defaults(files, body, fresh=True, expected_guard=guard)
    assert files == original


def test_fresh_compile_requires_the_selected_guard_and_original_application(tmp_path):
    files, body, _, compilation = local_plan(tmp_path)
    with pytest.raises(ValueError, match="reviewed selected-field"):
        compile_batch_defaults(files, body, fresh=True)
    with pytest.raises(ValueError, match="application changed"):
        compile_batch_defaults(files, {**body, "source_sha256": "0" * 64})
    with pytest.raises(ValueError, match="saved merge"):
        compile_batch_defaults(files, {**body, "effective_sha256": "0" * 64})
    validate_batch_evidence(body, compilation["batch_guard"])


def test_apply_confirmations_are_closed_and_strict():
    args = {
        "operation_id": "batch-test-apply",
        "token": "x" * 32,
        "review_sha256": "0" * 64,
        "defaults_change_confirmed": True,
        "application_transfer_confirmed": True,
    }
    assert BatchTransferApply(**args).defaults_change_confirmed
    for extra in [{"defaults_change_confirmed": 1}, {"controller_write": True}]:
        with pytest.raises(ValueError):
            BatchTransferApply(**(args | extra))


async def review_native(link, *, compact=False, omit_kind=None, target=None):
    peer, _, _, native, original_target = link
    peer.files = batch_files()
    peer.metadata["object-name"] = "Authored native wire controller"
    original = peer.do_ReinitializeDeviceRequest

    async def state(self, message):
        await original(message)
        if str(message.reinitializedStateOfDevice) == "end-restore":
            update_saved(self.files, compact=compact, omit_kind=omit_kind)

    peer.do_ReinitializeDeviceRequest = types.MethodType(state, peer)

    async def no_collision(_):
        raise AssertionError("Default batches must not allocate or scan Device instances.")

    native.instances._collision = no_collision
    target = target or original_target
    captured = await native.capture(**target, operation_id="capture-for-batch-transfer")
    snapshot, _ = native.storage.load(captured["id"])
    query = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    opened = NativeDefaultBatch(NativeBackupRecords(native.storage)).source(query)
    body = request(query, opened, edits(opened))
    plan = await native.preview_default_batch(
        **target, **body, operation_id="review-native-batch-transfer"
    )
    return body, plan


def applying(plan, **changes):
    return {
        "operation_id": "apply-native-batch-transfer",
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        "defaults_change_confirmed": True,
        "application_transfer_confirmed": True,
        **changes,
    }


@pytest.mark.parametrize("compact", [False, True])
async def test_mixed_batch_uses_one_durable_restore_and_preserves_other_fresh_settings(
    native_link, compact
):
    peer, _, _, native, _ = native_link
    body, plan = await review_native(native_link, compact=compact)
    real_slot(peer.files, 0, struct.pack(">f", 45))
    before = copy.deepcopy(peer.files)

    def durable():
        (receipt,) = native.storage.receipts()
        assert receipt["pending"] and receipt["intent"]["change_kind"] == "default-batch"
        assert (
            native.storage.directory / receipt["intent"]["backup_id"] / "reviewed-application.bin"
        ).is_file()

    peer.dispatch = durable
    result = await native.apply_default_batch(**applying(plan))
    assert result["result"]["status"] == "verified" and not result["pending"], result
    assert result["intent"]["operation_profile"] == "native-effective-default-batch-transfer/1"
    assert result["intent"]["payload_sha256"] != plan["payload_sha256"]
    assert len(result["result"]["preservation"]["selected_defaults"]) == 4
    assert native.storage.load(result["intent"]["backup_id"])[1] == before
    assert (
        mutations(peer).count(("state", "start-restore"))
        == mutations(peer).count(("state", "end-restore"))
        == 1
    )
    assert all(row[1] == 3 for row in mutations(peer) if row[0] == "write")
    verify_batch_preservation(before, peer.files, body, result["intent"]["batch_guard"])
    events = list(peer.events)
    with pytest.raises(ValueError, match="consumed"):
        await native.apply_default_batch(**applying(plan))
    assert peer.events == events


@pytest.mark.parametrize("kind", ["real", "boolean", "enum"])
async def test_old_selected_saved_value_keeps_acknowledged_transfer_uncertain(native_link, kind):
    _, _, _, native, _ = native_link
    _, plan = await review_native(native_link, omit_kind=kind)
    result = await native.apply_default_batch(**applying(plan))
    assert result["result"]["status"] == "unknown" and result["pending"], result
    assert result["result"]["protocol_accepted"] and result["result"]["may_have_applied"]


@pytest.mark.parametrize(
    "fault",
    ["selected-real", "selected-boolean", "selected-enum", "directory", "capacity", "credentials"],
)
async def test_fresh_changed_selected_or_transfer_limits_refuse_before_restore(native_link, fault):
    peer, _, _, native, _ = native_link
    _, plan = await review_native(native_link)
    if fault == "selected-real":
        real_slot(peer.files, 17, struct.pack(">f", 9))
    elif fault == "selected-boolean":
        raw = bytearray(peer.files[12])
        raw[10:12] = b"\x00" + bytes([header_crc(b"\x00") ^ 255])
        peer.files[12] = bytes(raw)
    elif fault == "selected-enum":
        raw = bytearray(peer.files[12])
        payload = (9).to_bytes(2, "big")
        raw[22:25] = payload + bytes([header_crc(payload) ^ 255])
        peer.files[12] = bytes(raw)
    elif fault == "directory":
        peer.files[11] = peer.files[11][:-1] + bytes([peer.files[11][-1] ^ 1])
    elif fault == "capacity":
        peer.application_capacity = 1
    else:
        native.credentials.set("changed-backup", "changed-restore")
    result = await native.apply_default_batch(**applying(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert not mutations(peer)


@pytest.mark.parametrize("mode", ["drop-start", "drop-block", "drop-end"])
async def test_lost_ack_is_never_replayed_and_retains_one_batch_intent(native_link, mode):
    peer, _, _, native, _ = native_link
    _, plan = await review_native(native_link)
    peer.mode = mode
    result = await native.apply_default_batch(**applying(plan))
    assert result["pending"] and result["result"]["status"] == "unknown", result
    assert mutations(peer).count(("state", "start-restore")) == 1
    writes = [row[2] for row in mutations(peer) if row[0] == "write"]
    assert len(writes) == len(set(writes))
    assert native.storage.receipts()[0]["intent"]["change_kind"] == "default-batch"


async def test_routed_batch_pins_actual_station_and_proves_every_selected_value(native_link):
    from .test_native_default_transfer import NativeRouter

    peer, _, _, native, target = native_link
    address, port = target["address"].rsplit(":", 1)
    transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: NativeRouter((address, int(port))), local_addr=("127.0.0.1", 0)
    )
    routed = {"address": "3001:7", "device": "device,5136", "router": proxy.endpoint, "dnet": 3001}
    try:
        _, plan = await review_native(native_link, target=routed)
        result = await native.apply_default_batch(**applying(plan))
        assert not result["pending"] and result["result"]["status"] == "verified", result
        assert result["intent"]["target"] == {k: v for k, v in routed.items() if k != "device"}
        assert len(result["result"]["preservation"]["selected_defaults"]) == 4
        assert mutations(peer).count(("state", "start-restore")) == 1 and not proxy.errors
    finally:
        transport.close()


async def test_lost_commit_ack_reconciles_after_restart_without_replaying_batch(native_link):
    from bms_tool.native_applications import NativeApplications

    peer, bacnet, store, native, _ = native_link
    _, plan = await review_native(native_link)
    peer.mode = "drop-end"
    result = await native.apply_default_batch(**applying(plan))
    assert result["pending"] and result["result"]["status"] == "unknown"
    sent = list(mutations(peer))
    peer.mode = "normal"
    await native.close()
    restarted = NativeApplications(bacnet, store, native.instances, request_timeout=0.1, gap=0)
    try:
        checked = await restarted.reconcile(
            operation_id="readback-batch-restart", receipt_id=result["intent"]["id"]
        )
        assert not checked["pending"] and checked["latest_readback"]["status"] == "verified", (
            checked
        )
        assert mutations(peer) == sent
    finally:
        await restarted.close()


async def test_original_application_recovery_is_distinct_from_verification_of_batch(native_link):
    peer, _, _, native, _ = native_link
    _, plan = await review_native(native_link)
    original = copy.deepcopy(peer.files)
    peer.mode = "drop-end"
    result = await native.apply_default_batch(**applying(plan))
    assert result["pending"]
    sent = list(mutations(peer))
    peer.mode = "normal"
    peer.files = original
    peer.files[3] = ParameterApplication(original[3], original[11], original[12]).compile()[0]
    checked = await native.reconcile(
        operation_id="readback-batch-original", receipt_id=result["intent"]["id"]
    )
    assert (
        not checked["pending"] and checked["latest_readback"]["status"] == "recovered_original"
    ), checked
    assert checked["latest_readback"]["proposed_change_verified"] is False
    assert mutations(peer) == sent


@pytest.mark.parametrize(
    "field,value", [("batch_guard", None), ("batch_edit", None), ("payload_sha256", "0" * 64)]
)
async def test_sealed_batch_cannot_be_changed_before_apply(native_link, field, value):
    peer, _, _, native, _ = native_link
    _, plan = await review_native(native_link)
    native.plans[plan["token"]]["body"][field] = value
    with pytest.raises(ValueError):
        await native.apply_default_batch(**applying(plan))
    assert not mutations(peer)


@pytest.mark.parametrize("field", ["operation_profile", "batch_edit", "batch_guard"])
async def test_malformed_readback_fails_before_any_field_query(native_link, field):
    peer, _, _, native, _ = native_link
    _, plan = await review_native(native_link)
    events = list(peer.events)
    with pytest.raises(ValueError):
        await native.verify(None, {**plan, field: None})
    assert peer.events == events


def test_batch_http_requires_session_and_strict_typed_confirmations(tmp_path):
    from bms_tool.app import create_app
    from fastapi.testclient import TestClient

    root = "/api/bacnet/controller/native-application/default-batch/transfer"
    with TestClient(create_app(tmp_path)) as client:
        for route in ("preview", "apply"):
            assert client.post(root + "/" + route, json={}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        request = applying({"token": "a" * 32, "review_sha256": "b" * 64})
        for changes in (
            {"defaults_change_confirmed": 1},
            {"application_transfer_confirmed": "true"},
            {"allocation_confirmed": True},
        ):
            assert (
                client.post(root + "/apply", json=request | changes, headers=headers).status_code
                == 422
            )
        assert client.post(root + "/apply", json=request, headers=headers).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]
