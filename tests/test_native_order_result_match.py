"""Retained order correlation reconstructs the original and grants no field authority."""

import asyncio
import copy
import struct

import pytest
from bms_tool.app import create_app
from bms_tool.moi_execution_order import MoiExecutionOrder
from bms_tool.moi_identity import MoiIdentity, seal
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_order_result_match import NativeOrderResultMatch, order_comparisons
from fastapi.testclient import TestClient

from .test_moi_wire_sources import REF
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import NativeRouter, real_slot
from .test_native_order_transfer import applying, order_review


async def order_match_source(link, *, historical=False, routed=False, kind="match", **formats):
    peer, _, _, native, target = link
    _, plan = await order_review(link, **formats)
    if historical:
        peer.mode = "drop-end"
    receipt = await native.apply_order(**applying(plan))
    if historical:
        assert receipt["pending"]
        peer.mode = "normal"
        await native.reconcile(
            operation_id="order-match-historical-readback", receipt_id=receipt["intent"]["id"]
        )
        native.storage.event(receipt["intent"]["id"], "readback", {"status": "unknown"})
        receipt = native.storage.receipt(receipt["intent"]["id"])
    assert not receipt["pending"]
    if kind == "saved":
        real_slot(peer.files, 0, struct.pack(">f", 47))
    elif kind == "order":
        editor = MoiExecutionOrder(peer.files[3])
        selection = editor.inspect(REF)
        peer.files[3], _ = editor.compile(
            diagram_ref=REF,
            selection_sha256=selection["selection_sha256"],
            proposed_order=[0, 1, 2, 3],
        )
    elif kind == "reencoded":
        raw = bytearray(peer.files[3])
        raw[4:8] = (1234).to_bytes(4, "little")
        peer.files[3] = bytes(raw)
    transport = None
    try:
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
        capture = await native.capture(**target, operation_id="capture-order-result-comparison")
    finally:
        if transport:
            transport.close()
    snapshot, _ = native.storage.load(capture["id"])
    return receipt, {
        "receipt_id": receipt["intent"]["id"],
        "capture_id": capture["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
@pytest.mark.parametrize("historical", [False, True])
async def test_actual_result_reconstruction_and_complete_current_order_without_actions(
    native_link, compressed, diagram_class, historical
):
    peer, _, _, native, _ = native_link
    receipt, args = await order_match_source(
        native_link, compressed=compressed, diagram_class=diagram_class, historical=historical
    )
    before = copy.deepcopy(peer.events)
    original = copy.deepcopy(native.storage.receipt(args["receipt_id"]))
    plans = copy.deepcopy(native.plans)
    report = NativeOrderResultMatch(NativeBackupRecords(native.storage)).compare(args)
    assert report["state"] == "application-and-order-match" and all(report["comparisons"].values())
    assert (
        report["expected_selection"]["original_order"]
        == report["source"]["selection"]["original_order"]
        == [1, 0, 2, 3]
    )
    assert report["verified_proof"]["kind"] == ("readback-event" if historical else "result")
    assert report["evidence_sha256"] == seal(
        {k: v for k, v in report.items() if k != "evidence_sha256"}
    )
    assert report["read_only"] and all(
        report[k] is False
        for k in (
            "controller_queries",
            "field_actions",
            "can_apply",
            "field_transfer_enabled",
            "current_device_verified",
            "parent_revalidated",
        )
    )
    assert (
        peer.events == before
        and native.plans == plans
        and native.storage.receipt(args["receipt_id"]) == original
    )
    assert receipt["intent"]["id"] == report["receipt_id"]


@pytest.mark.parametrize("kind", ["saved", "order", "routed", "reencoded"])
async def test_current_source_differences_remain_separate(native_link, kind):
    peer, _, _, native, _ = native_link
    _, args = await order_match_source(
        native_link, kind=kind if kind != "routed" else "match", routed=kind == "routed"
    )
    before = copy.deepcopy(peer.events)
    report = NativeOrderResultMatch(NativeBackupRecords(native.storage)).compare(args)
    c = report["comparisons"]
    assert report["state"] == (
        "application-and-order-match" if kind == "reencoded" else "different"
    )
    assert c["route_matches"] is (kind != "routed")
    assert c["selected_order_matches"] is (kind != "order")
    assert c["expanded_application_matches"] is (kind != "order")
    assert c["effective_application_matches"] is (kind not in ("saved", "order"))
    assert c["membership_matches"] and c["wire_relationships_match"] and c["payload_widths_match"]
    assert peer.events == before


@pytest.mark.parametrize("dimension", ["diagram_class", "membership", "object", "width", "phase"])
async def test_observed_order_dimensions_cannot_be_inferred_from_the_permutation(
    native_link, dimension
):
    _, _, _, native, _ = native_link
    _, args = await order_match_source(native_link)
    report = NativeOrderResultMatch(NativeBackupRecords(native.storage)).compare(args)
    expected = report["expected_selection"]
    changed = copy.deepcopy(expected)
    if dimension == "diagram_class":
        changed["diagram_class_id"] = 536 if expected["diagram_class_id"] == 575 else 575
    elif dimension == "membership":
        changed["members"][0]["ref"] = "different/native/ref"
    elif dimension == "object":
        changed["members"][0]["object"] = {"unexpected": "object"}
    elif dimension == "width":
        changed["slots"][0]["payload_bytes"] += 1
    else:
        changed["edge_relationships"][0]["phase"] = "different"
    result = order_comparisons(expected, changed)
    assert result["selected_order_matches"] and not all(result.values())


@pytest.mark.parametrize(
    "fault",
    [
        "profile",
        "kind",
        "operation",
        "instance",
        "name",
        "identity",
        "target",
        "compilation",
        "compilation-marker",
        "payload",
        "native",
        "guard",
        "pending",
        "not-dispatched",
        "unverified",
        "recovery",
    ],
)
async def test_inconsistent_original_result_refuses_without_actions(
    native_link, monkeypatch, fault
):
    peer, _, _, native, _ = native_link
    receipt, args = await order_match_source(native_link)
    changed = copy.deepcopy(receipt)
    intent = changed["intent"]
    if fault == "profile":
        intent["profile"] = "unknown/2"
    elif fault == "kind":
        intent["change_kind"] = "default-batch"
    elif fault == "operation":
        intent["operation_profile"] = "unknown/2"
    elif fault == "instance":
        intent["new_instance"] += 1
    elif fault == "name":
        intent["new_name"] = "Other"
    elif fault == "identity":
        intent["identity"]["model-name"] = "Other"
    elif fault == "target":
        intent["target"]["address"] = "3001:99"
    elif fault == "compilation":
        intent["compilation"]["order_edit"]["proposed_order"] = [0, 1, 2, 3]
    elif fault == "compilation-marker":
        intent["compilation"]["controller_write"] = 0
    elif fault == "payload":
        intent["payload_sha256"] = "f" * 64
    elif fault == "native":
        intent["native_payload_sha256"] = "f" * 64
    elif fault == "guard":
        intent["order_guard"]["configuration_sha256"] = "f" * 64
    elif fault == "pending":
        changed["pending"] = True
    elif fault == "not-dispatched":
        changed["result"]["may_have_applied"] = False
    elif fault == "unverified":
        changed["result"]["status"] = "unknown"
    else:
        intent["recovery_origin"] = {"unsupported": True}
    before = copy.deepcopy(peer.events)
    monkeypatch.setattr(native.storage, "receipt", lambda *a, **kw: copy.deepcopy(changed))
    with pytest.raises(ValueError):
        NativeOrderResultMatch(NativeBackupRecords(native.storage)).compare(args)
    assert peer.events == before


@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize(
    "fault", ["native", "identity", "selected", "selected-marker", "seal", "receipt"]
)
async def test_changed_selected_proof_refuses_even_when_resealed(
    native_link, monkeypatch, historical, fault
):
    peer, _, _, native, _ = native_link
    receipt, args = await order_match_source(native_link, historical=historical)
    changed = copy.deepcopy(receipt)
    proof = (
        copy.deepcopy(native.storage.verified_readback(args["receipt_id"]))
        if historical
        else changed["result"]
    )
    observed = proof["detail"] if historical else proof
    if fault == "native":
        observed["native_sha256"] = "f" * 64
    elif fault == "identity":
        observed["readback"]["identity"]["object-name"] = "Other"
    elif fault == "selected":
        observed["preservation"]["selected_order"]["after"] = [0, 1, 2, 3]
    elif fault == "selected-marker":
        observed["preservation"]["selected_order"]["effective_order_verified"] = 1
    elif fault == "receipt":
        proof["receipt_id"] = "f" * 32
    proof["evidence_sha256"] = (
        "f" * 64
        if fault == "seal"
        else seal({k: v for k, v in proof.items() if k != "evidence_sha256"})
    )
    if historical:
        monkeypatch.setattr(native.storage, "verified_readback", lambda *_: copy.deepcopy(proof))
    monkeypatch.setattr(native.storage, "receipt", lambda *a, **kw: copy.deepcopy(changed))
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        NativeOrderResultMatch(NativeBackupRecords(native.storage)).compare(args)
    assert peer.events == before


@pytest.mark.parametrize("which", ["original", "current"])
async def test_missing_original_files_or_changed_snapshot_refuse(native_link, which):
    peer, _, _, native, _ = native_link
    receipt, args = await order_match_source(native_link)
    identifier = receipt["intent"]["backup_id"] if which == "original" else args["capture_id"]
    path = native.storage.directory / identifier / "file-3.bin"
    raw = path.read_bytes()
    before = copy.deepcopy(peer.events)
    try:
        path.unlink()
        with pytest.raises(ValueError):
            NativeOrderResultMatch(NativeBackupRecords(native.storage)).compare(args)
    finally:
        path.write_bytes(raw)
    assert peer.events == before


def test_local_api_requires_token_and_rejects_authority_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("BMS_STUDIO_DATA", str(tmp_path))
    app = create_app()
    with TestClient(app) as client:
        path = "/api/bacnet/controller/native-application/execution-order/result/compare"
        body = {"receipt_id": "a" * 32, "capture_id": "b" * 32, "snapshot_sha256": "c" * 64}
        assert client.post(path, json=body).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(path, json=body | {"can_apply": True}, headers=headers).status_code == 422
        )


async def test_a_different_coherent_native_identity_is_reported_as_a_difference(native_link):
    peer, _, _, native, target = native_link
    _, args = await order_match_source(native_link)
    editor = MoiIdentity(peer.files[3])
    options = {
        "source_sha256": editor.source_sha256,
        "expected_instance": 5136,
        "new_instance": 5136,
        "expected_name": editor.summary()["name"],
        "new_name": "Another authored native controller",
    }
    plan = editor.preview(**options)
    peer.files[3], _ = editor.export(plan_sha256=plan["plan_sha256"], **options)
    peer.metadata["object-name"] = options["new_name"]
    capture = await native.capture(**target, operation_id="capture-other-native-order-identity")
    snapshot, _ = native.storage.load(capture["id"])
    args.update(capture_id=capture["id"], snapshot_sha256=snapshot["evidence_sha256"])
    before = copy.deepcopy(peer.events)
    report = NativeOrderResultMatch(NativeBackupRecords(native.storage)).compare(args)
    assert report["state"] == "different"
    assert report["comparisons"]["identity_matches"] is False
    assert report["comparisons"]["selected_order_matches"] is True
    assert report["source"]["identity"]["object-name"] == options["new_name"]
    assert peer.events == before
