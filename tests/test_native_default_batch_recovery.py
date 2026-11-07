"""Previous typed batches require verified originals and matching retained outcomes."""

import asyncio
import copy
import secrets
import struct

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_default_batch_recovery import NativeDefaultBatchRecovery
from bms_tool.native_default_batch_transfer import compile_batch_defaults
from fastapi.testclient import TestClient

from .test_moi_wire_sources import D
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_batch import batch_files, local, request
from .test_native_default_batch_transfer import applying, edits, review_native, update_saved
from .test_native_default_transfer import real_slot
from .test_native_signal_compiler import retained

BASE = "/api/bacnet/controller/native-application/default-batch/recovery/prepare"


def setup(
    path,
    *,
    outcome="verified",
    possible=True,
    mutation=None,
    compact=False,
    omit_d=False,
    source_files=None,
):
    storage, _, before, query, opened = local(path, source_files)
    _, files = storage.load(before["id"])
    selected = [r for r in edits(opened) if not omit_d or r["record_ref"] != D]
    edit = request(query, opened, selected[:16])
    output, compilation = compile_batch_defaults(files, edit)
    body = {
        "id": secrets.token_hex(16),
        "target": before["target"],
        "identity": before["identity"],
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": before["identity"]["object-name"],
        "new_name": before["identity"]["object-name"],
        "change_kind": "default-batch",
        "operation_profile": "native-effective-default-batch-transfer/1",
        "enum_semantics_verified": False,
        "backup_id": before["id"],
        "batch_edit": edit,
        "batch_guard": compilation["batch_guard"],
        "compilation": compilation,
        "payload_sha256": sha(output),
        "native_payload_sha256": sha(MoiIdentity(output).data),
    }
    if mutation:
        mutation(body)
    intent = storage.intent(body)
    if outcome != "intent-only":
        storage.finish(
            intent["id"],
            {
                "intent_sha256": intent["evidence_sha256"],
                "status": outcome,
                "may_have_applied": possible,
            },
        )
    current_files = files | {3: output}
    update_saved(current_files, compact=compact)
    current = retained(storage, current_files, identity=before["identity"], target=before["target"])
    query = {
        "receipt_id": intent["id"],
        "capture_id": current["id"],
        "snapshot_sha256": current["evidence_sha256"],
    }
    return (
        storage,
        NativeDefaultBatchRecovery(NativeBackupRecords(storage)),
        query,
        before,
        current_files,
    )


def test_actual_prior_effective_batch_compiles_locally_and_preserves_all_originals(tmp_path):
    storage, service, query, _, files = setup(tmp_path)
    original = copy.deepcopy(storage.receipt(query["receipt_id"]))
    report = service.prepare(query)
    assert report["profile"] == "native-default-batch-recovery-draft/1"
    assert report["read_only"] and report["new_review_required"] and not report["already_recorded"]
    assert not any(
        report[k]
        for k in (
            "controller_queries",
            "field_actions",
            "can_apply",
            "field_transfer_enabled",
            "enum_semantics_verified",
        )
    )
    rows = report["origin"]["fields"]
    assert len(rows) == 4
    assert [r["previous"] for r in rows] == [
        {"bits": "40600000"},
        {"bits": "40800000"},
        {"value": True},
        {"value": 513},
    ]
    assert rows[1]["recorded_after"] == {"bits": "80000000"}
    output, compilation = compile_batch_defaults(files, report["proposal"])
    assert report["compilation"] == compilation and compilation["changed_count"] == 4
    assert report["output_sha256"] == sha(output)
    assert storage.receipt(query["receipt_id"]) == original
    assert storage.load(query["capture_id"])[1] == files


def current_source(storage, query, files, **metadata):
    before = storage.load(query["capture_id"])[0]
    metadata.setdefault("identity", before["identity"])
    metadata.setdefault("target", before["target"])
    source = retained(storage, files, **metadata)
    return query | {"capture_id": source["id"], "snapshot_sha256": source["evidence_sha256"]}


def test_unselected_current_saved_settings_survive_and_all_previous_values_create_no_proposal(
    tmp_path,
):
    storage, service, query, before, files = setup(tmp_path, omit_d=True)
    real_slot(files, 0, struct.pack(">f", 45))
    query = current_source(storage, query, files)
    report = service.prepare(query)
    output, _ = compile_batch_defaults(files, report["proposal"])
    assert (
        MoiIdentity(output).reader.scalar(
            MoiIdentity(output).reader.records["controller/575_1.2_10"], 3113
        )
        == 45
    )
    original = storage.load(before["id"])[1]
    files[12] = original[12]
    report = service.prepare(current_source(storage, query, files))
    assert report["already_recorded"] and not report["new_review_required"]
    assert report["proposal"] is report["compilation"] is report["output_sha256"] is None


@pytest.mark.parametrize(
    "field",
    [
        "operation_profile",
        "change_kind",
        "enum_semantics_verified",
        "batch_edit",
        "batch_guard",
        "compilation",
        "payload_sha256",
        "native_payload_sha256",
        "new_name",
        "new_instance",
    ],
)
def test_forged_or_unsupported_parent_never_creates_recovery(tmp_path, field):
    _, service, query, _, _ = setup(tmp_path, mutation=lambda body: body.__setitem__(field, None))
    with pytest.raises(ValueError):
        service.prepare(query)


@pytest.mark.parametrize("outcome", ["unknown", "intent-only"])
def test_pending_original_cannot_prepare_and_historical_verified_readback_is_immutable(
    tmp_path, outcome
):
    storage, service, query, _, _ = setup(tmp_path, outcome=outcome)
    with pytest.raises(ValueError, match="Reconcile"):
        service.prepare(query)
    storage.resolve(query["receipt_id"], {"status": "verified"})
    original = copy.deepcopy(storage.receipt(query["receipt_id"]))
    report = service.prepare(query)
    assert report["origin"]["verified_proof"]["kind"] == "readback-event"
    storage.event(query["receipt_id"], "readback", {"status": "unknown"})
    assert service.prepare(query)["origin"] == report["origin"]
    assert storage.receipt(query["receipt_id"])["intent"] == original["intent"]


def test_no_dispatch_refusal_cannot_acquire_recovery_from_later_readback(tmp_path):
    storage, service, query, _, _ = setup(tmp_path, outcome="not_sent", possible=False)
    storage.resolve(query["receipt_id"], {"status": "verified"})
    with pytest.raises(ValueError, match="no possible"):
        service.prepare(query)


def test_actual_saved_directory_compaction_requires_separate_engineering(tmp_path):
    _, service, query, _, _ = setup(tmp_path, compact=True)
    with pytest.raises(ValueError, match="static directory"):
        service.prepare(query)


@pytest.mark.parametrize(
    "change", ["route", "device", "vendor", "unverified", "application", "third-value", "bad-crc"]
)
def test_different_current_source_never_yields_a_previous_batch(tmp_path, change):
    storage, service, query, _, files = setup(tmp_path)
    metadata = {}
    if change == "route":
        metadata["target"] = {"address": "127.0.0.1:47999", "router": None, "dnet": None}
    if change == "device":
        metadata["identity"] = {
            **storage.load(query["capture_id"])[0]["identity"],
            "device": "device,99",
        }
    if change == "vendor":
        metadata["identity"] = {
            **storage.load(query["capture_id"])[0]["identity"],
            "vendor-identifier": 42,
        }
    if change == "unverified":
        metadata["source_identity_matches"] = False
    if change == "application":
        files[3] = storage.load(storage.receipt(query["receipt_id"])["intent"]["backup_id"])[1][3]
    if change == "third-value":
        real_slot(files, 17, struct.pack(">f", 19))
    if change == "bad-crc":
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    with pytest.raises(ValueError):
        service.prepare(current_source(storage, query, files, **metadata))


def test_local_http_session_extra_fields_and_unchanged_field_transfer_admission(tmp_path):
    storage, _, query, _, _ = setup(tmp_path)
    original = copy.deepcopy(storage.receipt(query["receipt_id"]))
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(BASE, json=query).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(BASE, json=query, headers=headers)
        assert response.status_code == 200 and response.json()["can_apply"] is False
        for extra in (
            {"token": "x" * 32},
            {"can_apply": True},
            {"recovery_parent_receipt": query["receipt_id"]},
        ):
            assert client.post(BASE, json=query | extra, headers=headers).status_code == 422
        proposal = response.json()["proposal"]
        assert (
            client.post(
                BASE.replace("/recovery/prepare", "/transfer/preview"),
                json=proposal | {"recovery_parent_receipt": query["receipt_id"]},
                headers=headers,
            ).status_code
            == 422
        )
        assert storage.receipt(query["receipt_id"]) == original


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("historical", [False, True])
async def test_real_authored_transfer_then_disconnected_preparation_makes_no_further_queries(
    native_link, monkeypatch, routed, historical
):
    from .test_native_default_transfer import NativeRouter

    peer, bacnet, _, native, target = native_link
    transport = None
    if routed:
        address, port = target["address"].rsplit(":", 1)
        transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: NativeRouter((address, int(port))), local_addr=("127.0.0.1", 0)
        )
        target = {
            "address": "3001:7",
            "device": "device,5136",
            "router": proxy.endpoint,
            "dnet": 3001,
        }
    try:
        _, plan = await review_native(native_link, target=target)
        if historical:
            peer.mode = "drop-end"
        receipt = await native.apply_default_batch(**applying(plan))
        if historical:
            assert receipt["pending"] and receipt["result"]["status"] == "unknown"
            peer.mode = "normal"
            receipt = await native.reconcile(
                operation_id="readback-original-batch-recovery", receipt_id=receipt["intent"]["id"]
            )
            assert not receipt["pending"] and receipt["latest_readback"]["status"] == "verified"
        else:
            assert receipt["result"]["status"] == "verified"
        capture = await native.capture(**target, operation_id="capture-batch-recovery-current")
        snapshot, files = native.storage.load(capture["id"])
        await bacnet.disconnect()
        before = copy.deepcopy(peer.events)
        plans = copy.deepcopy(native.plans)
        receipts = native.storage.receipts()

        def forbidden(*args, **kwargs):
            raise AssertionError("Preparation must not preview or apply a field transfer.")

        monkeypatch.setattr(native, "preview_default_batch", forbidden)
        monkeypatch.setattr(native, "apply_default_batch", forbidden)
        report = native.default_batch_recovery.prepare(
            {
                "receipt_id": receipt["intent"]["id"],
                "capture_id": capture["id"],
                "snapshot_sha256": snapshot["evidence_sha256"],
            }
        )
        assert report["compilation"]["changed_count"] == 4 and peer.events == before
        assert native.plans == plans and native.storage.receipts() == receipts
        assert native.storage.load(capture["id"])[1] == files
        assert report["origin"]["verified_proof"]["kind"] == (
            "readback-event" if historical else "result"
        )
        if routed:
            assert not proxy.errors
    finally:
        if transport:
            transport.close()


def test_previous_signed_zero_is_proposed_by_exact_float32_bits(tmp_path):
    files = batch_files()
    real_slot(files, 17, bytes.fromhex("80000000"))
    _, service, query, _, current = setup(tmp_path, source_files=files)
    report = service.prepare(query)
    field = report["origin"]["fields"][0]
    assert field["previous"] == {"bits": "80000000"}
    assert report["proposal"]["changes"][0]["value_text"] == "-0.0"
    output, _ = compile_batch_defaults(current, report["proposal"])
    app = MoiIdentity(output)
    assert (
        struct.pack(">f", app.reader.scalar(app.reader.records[field["record_ref"]], 3113)).hex()
        == "80000000"
    )


def test_sixteen_recorded_fields_are_bounded_and_no_model_inventory_is_used(tmp_path):
    _, service, query, _, _ = setup(tmp_path, source_files=batch_files(extra=20))
    report = service.prepare(query)
    assert len(report["origin"]["fields"]) == len(report["proposal"]["changes"]) == 16
    assert report["compilation"]["changed_count"] == 16
    assert (
        report["compilation"]["parameter_transfer_qualification"]["model_inventory_used"] is False
    )


@pytest.mark.parametrize("key", [3, 11, 12])
def test_changed_original_backup_cannot_reconstruct_previous_values(tmp_path, key):
    storage, service, query, before, _ = setup(tmp_path)
    (storage.directory / before["id"] / f"file-{key}.bin").write_bytes(b"Changed original")
    with pytest.raises(ValueError):
        service.prepare(query)
