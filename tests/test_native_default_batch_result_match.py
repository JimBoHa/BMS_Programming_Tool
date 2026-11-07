"""Retained source/result comparison never creates field or recovery authority."""

import asyncio
import copy
import struct

import pytest
from bms_tool.moi_identity import seal
from bms_tool.native_default_batch_result_match import NativeDefaultBatchResultMatch

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_batch_recovery_transfer import original_and_proposal
from .test_native_default_batch_transfer import applying, review_native
from .test_native_default_transfer import NativeRouter, mutations, real_slot


async def comparison_source(link, *, recovery=False, historical=False, current_routed=False):
    peer, _, _, native, target = link
    if recovery:
        _, _, args = await original_and_proposal(link)
        plan = await native.preview_default_batch(**args)
    else:
        _, plan = await review_native(link)
    if historical:
        peer.mode = "drop-end"
    receipt = await native.apply_default_batch(**applying(plan))
    if historical:
        assert receipt["pending"]
        peer.mode = "normal"
        receipt = await native.reconcile(
            operation_id="match-historical-batch-readback", receipt_id=receipt["intent"]["id"]
        )
        native.storage.event(receipt["intent"]["id"], "readback", {"status": "unknown"})
        receipt = native.storage.receipt(receipt["intent"]["id"])
    transport = None
    try:
        if current_routed:
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
        current = await native.capture(**target, operation_id="capture-for-result-comparison")
        if current_routed:
            assert not proxy.errors
    finally:
        if transport:
            transport.close()
    snapshot, _ = native.storage.load(current["id"])
    args = {
        "receipt_id": receipt["intent"]["id"],
        "capture_id": current["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
    }
    return receipt, args


async def test_routed_capture_with_same_device_and_values_keeps_original_route_difference(
    native_link,
):
    peer, _, _, native, _ = native_link
    _, args = await comparison_source(native_link, current_routed=True)
    before = copy.deepcopy(peer.events)
    report = NativeDefaultBatchResultMatch(native.default_batch_recovery.records).compare(args)
    assert report["state"] == "different" and not report["comparisons"]["route_matches"]
    assert report["comparisons"]["identity_matches"]
    assert report["comparisons"]["expanded_application_matches"]
    assert report["comparisons"]["effective_application_matches"]
    assert report["comparisons"]["selected_values_match"]
    assert report["current_target"]["address"] == "3001:7"
    assert peer.events == before


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize("historical", [False, True])
async def test_reconstructed_verified_result_matches_actual_retained_source_without_actions(
    native_link, recovery, historical
):
    peer, _, _, native, _ = native_link
    receipt, args = await comparison_source(native_link, recovery=recovery, historical=historical)
    events = copy.deepcopy(peer.events)
    saved_receipt = copy.deepcopy(native.storage.receipt(args["receipt_id"]))
    plans = copy.deepcopy(native.plans)
    report = NativeDefaultBatchResultMatch(native.default_batch_recovery.records).compare(args)
    assert report["state"] == "application-and-values-match"
    assert report["recorded_recovery_child"] is recovery
    assert report["comparisons"]["selected_values_match"]
    assert len(report["selected"]) == 4
    assert report["verified_proof"]["kind"] == ("readback-event" if historical else "result")
    if not recovery:
        assert report["selected"][1]["expected"] == {"bits": "80000000"}
    assert all(
        report[k] is False
        for k in (
            "controller_queries",
            "field_actions",
            "can_apply",
            "field_transfer_enabled",
            "current_device_verified",
            "parent_revalidated",
            "enum_semantics_verified",
        )
    )
    assert report["evidence_sha256"] == seal(
        {k: v for k, v in report.items() if k != "evidence_sha256"}
    )
    assert peer.events == events and native.plans == plans
    assert native.storage.receipt(args["receipt_id"]) == saved_receipt
    assert receipt["intent"]["id"] == report["receipt_id"]


@pytest.mark.parametrize("selected", [False, True])
async def test_current_saved_changes_are_reported_without_recovery_value_restriction(
    native_link, selected
):
    peer, _, _, native, target = native_link
    _, args = await comparison_source(native_link)
    real_slot(peer.files, 17 if selected else 0, struct.pack(">f", 19 if selected else 47))
    current = await native.capture(**target, operation_id="capture-different-saved-values")
    snapshot, _ = native.storage.load(current["id"])
    args.update(capture_id=current["id"], snapshot_sha256=snapshot["evidence_sha256"])
    before = list(mutations(peer))
    report = NativeDefaultBatchResultMatch(native.default_batch_recovery.records).compare(args)
    assert report["state"] == "different"
    assert report["comparisons"]["expanded_application_matches"] is True
    assert report["comparisons"]["effective_application_matches"] is False
    assert report["comparisons"]["selected_values_match"] is (not selected)
    if selected:
        assert report["selected"][0]["current"]["value"] == {"bits": struct.pack(">f", 19).hex()}
        assert report["selected"][0]["matches"] is False
    assert mutations(peer) == before


FAULTS = (
    "profile",
    "kind",
    "operation",
    "enum",
    "instance",
    "name",
    "identity",
    "target",
    "compilation",
    "payload",
    "native",
    "guard",
    "pending",
    "not-dispatched",
    "unverified",
    "unknown-recovery",
)


@pytest.mark.parametrize("fault", FAULTS)
async def test_inconsistent_original_refuses_without_field_actions(native_link, monkeypatch, fault):
    peer, _, _, native, _ = native_link
    receipt, args = await comparison_source(native_link)
    record = copy.deepcopy(receipt)
    body = record["intent"]
    if fault == "profile":
        body["profile"] = "unsupported/2"
    elif fault == "kind":
        body["change_kind"] = "input"
    elif fault == "operation":
        body["operation_profile"] = "unsupported/2"
    elif fault == "enum":
        body["enum_semantics_verified"] = True
    elif fault == "instance":
        body["new_instance"] = 1
    elif fault == "name":
        body["new_name"] = "Different"
    elif fault == "identity":
        body["identity"]["object-name"] = "Different"
    elif fault == "target":
        body["target"]["address"] = "127.0.0.1:1"
    elif fault == "compilation":
        body["compilation"]["changed_count"] = 1
    elif fault == "payload":
        body["payload_sha256"] = "a" * 64
    elif fault == "native":
        body["native_payload_sha256"] = "a" * 64
    elif fault == "guard":
        body["batch_guard"] = None
    elif fault == "pending":
        record["pending"] = True
    elif fault == "not-dispatched":
        record["result"]["may_have_applied"] = False
    elif fault == "unverified":
        record["result"]["status"] = "unknown"
    elif fault == "unknown-recovery":
        body["recovery_profile"] = "unsupported/2"
    original = native.storage.receipt
    monkeypatch.setattr(
        native.storage,
        "receipt",
        lambda identifier, **kw: (
            record if identifier == args["receipt_id"] else original(identifier, **kw)
        ),
    )
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        NativeDefaultBatchResultMatch(native.default_batch_recovery.records).compare(args)
    assert peer.events == before


async def test_recovery_child_comparison_does_not_reopen_its_original_parent(native_link):
    peer, _, _, native, _ = native_link
    receipt, args = await comparison_source(native_link, recovery=True)
    original = receipt["intent"]["recovery_origin"]["original_backup_id"]
    path = native.storage.directory / original / "file-3.bin"
    raw = path.read_bytes()
    try:
        path.unlink()
        before = copy.deepcopy(peer.events)
        report = NativeDefaultBatchResultMatch(native.default_batch_recovery.records).compare(args)
        assert (
            report["state"] == "application-and-values-match" and not report["parent_revalidated"]
        )
        assert peer.events == before
    finally:
        path.write_bytes(raw)


async def test_changed_gzip_header_preserves_native_and_effective_result_match(native_link):
    peer, _, _, native, target = native_link
    receipt, args = await comparison_source(native_link)
    encoded = bytearray(peer.files[3])
    assert encoded[:2] == b"\x1f\x8b"
    encoded[4:8] = (1234).to_bytes(4, "little")
    peer.files[3] = bytes(encoded)
    current = await native.capture(**target, operation_id="capture-reencoded-batch-result")
    snapshot, _ = native.storage.load(current["id"])
    args.update(capture_id=current["id"], snapshot_sha256=snapshot["evidence_sha256"])
    before = copy.deepcopy(peer.events)
    report = NativeDefaultBatchResultMatch(native.default_batch_recovery.records).compare(args)
    assert report["state"] == "application-and-values-match"
    assert report["source"]["source_sha256"] != receipt["intent"]["payload_sha256"]
    assert report["current_native_sha256"] == report["expected_native_sha256"]
    assert report["current_effective_native_sha256"] == report["expected_native_sha256"]
    assert peer.events == before


async def test_local_http_requires_session_and_refuses_field_authority_fields(
    native_link, tmp_path
):
    from bms_tool.app import create_app
    from fastapi.testclient import TestClient

    peer, _, _, native, _ = native_link
    _, args = await comparison_source(native_link)
    before = copy.deepcopy(peer.events)
    original = copy.deepcopy(native.storage.receipt(args["receipt_id"]))
    with TestClient(create_app(tmp_path)) as client:
        path = "/api/bacnet/controller/native-application/default-batch/result/compare"
        assert client.post(path, json=args).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(path, json=args, headers=headers)
        assert response.status_code == 200 and response.json()["can_apply"] is False
        for extra in (
            {"token": "x" * 32},
            {"can_apply": True},
            {"operation_id": "not-a-field-action"},
        ):
            assert client.post(path, json=args | extra, headers=headers).status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False
    assert peer.events == before and native.storage.receipt(args["receipt_id"]) == original
