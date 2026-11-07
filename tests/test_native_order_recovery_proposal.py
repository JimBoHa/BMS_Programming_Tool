"""Actual inverse compilation from verified authored peers, without a field action."""

import copy

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, seal
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_execution_order import NativeExecutionOrder
from bms_tool.native_order_recovery_proposal import NativeOrderRecoveryProposal
from fastapi.testclient import TestClient

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_order_result_match import order_match_source

BASE = "/api/bacnet/controller/native-application/execution-order/recovery/prepare"


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
@pytest.mark.parametrize("historical", [False, True])
async def test_original_permutation_compiles_to_original_logic_and_keeps_all_other_current_bytes(
    native_link, compressed, diagram_class, historical
):
    peer, _, _, native, _ = native_link
    receipt, args = await order_match_source(
        native_link, compressed=compressed, diagram_class=diagram_class, historical=historical
    )
    records = NativeBackupRecords(native.storage)
    original_receipt = copy.deepcopy(native.storage.receipt(args["receipt_id"]))
    events, plans = copy.deepcopy(peer.events), copy.deepcopy(native.plans)
    folders = sorted(path.name for path in native.storage.directory.iterdir())
    current, files = native.storage.load(args["capture_id"])
    file_bytes = dict(files)
    result = NativeOrderRecoveryProposal(records).prepare(args)
    assert result["proposal"]["proposed_order"] == [0, 1, 2, 3]
    assert result["comparison"]["source"]["selection"]["original_order"] == [1, 0, 2, 3]
    assert result["origin"]["verified_proof"]["kind"] == (
        "readback-event" if historical else "result"
    )
    output, preview = NativeExecutionOrder(records).preview(result["proposal"])
    assert preview == result["preview"]
    _, before = native.storage.load(receipt["intent"]["backup_id"])
    # Independent saved-parameter application to the original before image gives
    # the expected complete native data, not just a second order permutation.
    expected, _ = ParameterApplication(before[3], files[11], files[12]).compile()
    assert MoiIdentity(output).data == MoiIdentity(expected).data
    if compressed:
        assert output[:10] == files[3][:10]
    selection = preview["compilation"]["order_edit"]["selection"]
    assert (
        selection["edge_relationships"]
        == result["comparison"]["expected_selection"]["edge_relationships"]
    )
    assert [s["payload_bytes"] for s in selection["slots"]] == receipt["intent"]["order_guard"][
        "payload_widths"
    ]
    assert result["evidence_sha256"] == seal(
        {k: v for k, v in result.items() if k != "evidence_sha256"}
    )
    assert result["origin_sha256"] == seal(result["origin"])
    assert result["read_only"] and result["new_review_required"]
    assert all(
        result[key] is False
        for key in [
            "controller_queries",
            "field_actions",
            "can_apply",
            "field_transfer_enabled",
            "current_device_verified",
            "recovery_lineage_recorded",
        ]
    )
    assert current["evidence_sha256"] == args["snapshot_sha256"]
    assert files == file_bytes
    assert native.storage.load(args["capture_id"])[1] == file_bytes
    assert peer.events == events and native.plans == plans
    assert native.storage.receipt(args["receipt_id"]) == original_receipt
    assert sorted(path.name for path in native.storage.directory.iterdir()) == folders


@pytest.mark.parametrize("kind", ["saved", "order", "routed"])
async def test_current_differences_refuse_a_previous_order_instead_of_inventing_recovery(
    native_link, kind
):
    peer, _, _, native, _ = native_link
    _, args = await order_match_source(
        native_link, kind=kind if kind != "routed" else "match", routed=kind == "routed"
    )
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError, match="must match"):
        NativeOrderRecoveryProposal(NativeBackupRecords(native.storage)).prepare(args)
    assert peer.events == before


async def test_reencoded_original_wrapper_keeps_its_current_header_and_original_order(native_link):
    _, _, _, native, _ = native_link
    _, args = await order_match_source(native_link, kind="reencoded")
    records = NativeBackupRecords(native.storage)
    result = NativeOrderRecoveryProposal(records).prepare(args)
    output, _ = NativeExecutionOrder(records).preview(result["proposal"])
    _, files = native.storage.load(args["capture_id"])
    assert output[:10] == files[3][:10] and output[4:8] == (1234).to_bytes(4, "little")


@pytest.mark.parametrize(
    "fault",
    [
        "pending",
        "recovery",
        "guard",
        "proof",
        "proof-marker",
        "intent-change",
        "source-change",
        "directory",
    ],
)
async def test_changed_or_unsupported_parent_source_and_static_directory_refuse(
    native_link, monkeypatch, fault
):
    peer, _, _, native, _ = native_link
    receipt, args = await order_match_source(native_link)
    records = NativeBackupRecords(native.storage)
    service = NativeOrderRecoveryProposal(records)
    changed = copy.deepcopy(receipt)
    if fault == "pending":
        changed["pending"] = True
    elif fault == "recovery":
        changed["intent"]["recovery_parent_receipt"] = "a" * 32
    elif fault == "guard":
        changed["intent"]["order_guard"]["original_order"] = [0, 0, 2, 3]
    elif fault in ("proof", "proof-marker"):
        result = changed["result"]
        if fault == "proof":
            result["native_sha256"] = "a" * 64
        else:
            result["preservation"]["selected_order"]["effective_order_verified"] = 1
        result["evidence_sha256"] = seal(
            {k: v for k, v in result.items() if k != "evidence_sha256"}
        )
    if fault in ("pending", "recovery", "guard", "proof", "proof-marker"):
        monkeypatch.setattr(native.storage, "receipt", lambda *a, **kw: copy.deepcopy(changed))
    elif fault in ("intent-change", "directory"):
        report = service.compare(args)
        if fault == "directory":
            report["comparisons"]["original_saved_directory_matches"] = False
        else:
            report["intent_sha256"] = "a" * 64
        monkeypatch.setattr(service, "compare", lambda *_: report)
    else:
        original_preview = NativeExecutionOrder.preview

        def changed_preview(self, request):
            output, report = original_preview(self, request)
            report["source"]["captured_at"] = "different source"
            return output, report

        monkeypatch.setattr(NativeExecutionOrder, "preview", changed_preview)
    events = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        service.prepare(args)
    assert peer.events == events


@pytest.mark.parametrize("which", ["original", "current"])
async def test_missing_source_originals_refuse(native_link, which):
    peer, _, _, native, _ = native_link
    receipt, args = await order_match_source(native_link)
    identifier = args["capture_id"] if which == "current" else receipt["intent"]["backup_id"]
    path = native.storage.directory / identifier / "file-3.bin"
    raw = path.read_bytes()
    events = copy.deepcopy(peer.events)
    try:
        path.unlink()
        with pytest.raises(ValueError):
            NativeOrderRecoveryProposal(NativeBackupRecords(native.storage)).prepare(args)
    finally:
        path.write_bytes(raw)
    assert peer.events == events


async def test_real_api_requires_session_token_preserves_own_receipt_and_has_no_authority_fields(
    native_link,
):
    peer, _, store, native, _ = native_link
    _, args = await order_match_source(native_link)
    expected = NativeOrderRecoveryProposal(NativeBackupRecords(native.storage)).prepare(args)
    before = copy.deepcopy(peer.events)
    with TestClient(create_app(store.directory)) as client:
        assert client.post(BASE, json=args).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(BASE, json=args, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == expected
        for field in ("can_apply", "token", "order_change_confirmed"):
            assert client.post(BASE, json=args | {field: True}, headers=headers).status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False
    assert peer.events == before
