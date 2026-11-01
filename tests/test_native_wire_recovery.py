"""Previous wire proposals use independent literal graph bytes and retained journals."""

import copy
import gzip
import secrets
import struct

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_effective_wire import EffectiveWireCompiler
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_wire_compiler import EffectiveWireService
from bms_tool.native_wire_recovery import NativeWireRecovery
from bms_tool.native_wire_transfer import PROFILE as TRANSFER_PROFILE
from bms_tool.native_wire_transfer import compile_wire, verify_wire_preservation
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_moi_wire_sources import REF, A, B
from .test_native_default_transfer import real_slot
from .test_native_signal_compiler import retained
from .test_native_wire_compiler import BOOLEAN, proposal, query, wire_files

BASE = "/api/bacnet/controller/native-application/wire-source/recovery/prepare"
IDENTITY = {
    "device": "device,5136",
    "object-name": "Authored native wire controller",
    "model-name": "UNLISTED-MODEL",
    "vendor-identifier": 5,
}
FANOUT = [(0, 85, 2, 7000), (1, 85, 3, 7000), (0, 85, 3, 7001), (1, 85, 2, 7001)]


def setup(
    tmp_path, *, index=0, outcome="verified", possible=True, change=None, files=None, **file_options
):
    storage = ApplicationStore(Store(tmp_path))
    file_options.setdefault("wires", FANOUT)
    files = wire_files(target_class=538, **file_options) if files is None else files
    before = retained(storage, files, identity=IDENTITY)
    service = EffectiveWireService(NativeBackupRecords(storage))
    edit = proposal(service, query(service, before, index=index), source_ref=B if index == 0 else A)
    output, compilation = compile_wire(files, edit)
    body = {
        "id": secrets.token_hex(16),
        "target": before["target"],
        "identity": IDENTITY,
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": IDENTITY["object-name"],
        "new_name": IDENTITY["object-name"],
        "change_kind": "wire-source",
        "operation_profile": TRANSFER_PROFILE,
        "wire_change_confirmed": True,
        "application_transfer_confirmed": True,
        "backup_id": before["id"],
        "wire_edit": edit,
        "wire_guard": compilation["wire_guard"],
        "compilation": compilation,
        "payload_sha256": sha(output),
        "native_payload_sha256": sha(MoiIdentity(output).data),
    }
    verification = (
        {
            "operational": True,
            "system_status": 0,
            "native_sha256": sha(MoiIdentity(output).data),
            "preservation": verify_wire_preservation(
                files, {**files, 3: output}, edit, compilation["wire_guard"]
            ),
        }
        if outcome == "verified"
        else {}
    )
    if change:
        change(body)
    intent = storage.intent(body)
    if outcome != "intent-only":
        storage.finish(
            intent["id"],
            {
                "intent_sha256": intent["evidence_sha256"],
                "status": outcome,
                "may_have_applied": possible,
                **verification,
            },
        )
    current_files = {**files, 3: output}
    current = retained(storage, current_files, identity=IDENTITY)
    request = {
        "receipt_id": intent["id"],
        "capture_id": current["id"],
        "snapshot_sha256": current["evidence_sha256"],
    }
    return storage, NativeWireRecovery(NativeBackupRecords(storage)), request, before, current_files


def current_source(storage, request, files, **metadata):
    old = storage.load(request["capture_id"])[0]
    metadata.setdefault("identity", old["identity"])
    metadata.setdefault("target", old["target"])
    current = retained(storage, files, **metadata)
    return {**request, "capture_id": current["id"], "snapshot_sha256": current["evidence_sha256"]}


@pytest.mark.parametrize("index,prior,after", [(0, A, B), (1, B, A)])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
def test_exact_previous_tuple_and_single_native_payload_patch_are_local(
    tmp_path, index, prior, after, compressed, extended, diagram_class
):
    storage, service, request, _, files = setup(
        tmp_path, index=index, compressed=compressed, extended=extended, diagram_class=diagram_class
    )
    original = copy.deepcopy(storage.receipt(request["receipt_id"]))
    report = service.prepare(request)
    assert report["profile"] == "native-wire-source-recovery-draft/1"
    origin = report["origin"]
    assert origin["previous_source_ref"] == prior and origin["recorded_after_source_ref"] == after
    assert origin["wire_index"] == index and origin["property"] == 3118
    assert origin["class_id"] == diagram_class
    assert origin["previous_tuple"][1:] == origin["recorded_after_tuple"][1:]
    assert report["proposal"]["source_ref"] == prior
    assert report["read_only"] and report["new_review_required"]
    assert (
        not report["can_apply"] and not report["controller_queries"] and not report["field_actions"]
    )
    proposal = {k: v for k, v in report["proposal"].items() if k != "recovery_parent_receipt"}
    output, compiled = compile_wire(files, proposal)
    merged = EffectiveWireCompiler(files).effective.editor.data
    offset = compiled["wire_edit"]["source_index_offset"]
    width = compiled["wire_edit"]["source_index_bytes"]
    observed = MoiIdentity(output)
    assert (
        observed.data
        == merged[:offset]
        + origin["previous_tuple"][0].to_bytes(width, "big")
        + merged[offset + width :]
    )
    assert observed.reader.diagram(REF)["connections"][index]["source_ref"] == prior
    assert storage.receipt(request["receipt_id"]) == original and len(storage.receipts()) == 1
    assert storage.load(request["capture_id"])[1] == files


def test_other_current_saved_values_survive_new_wire_compilation(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    real_slot(files, 0, struct.pack(">f", 45))
    report = service.prepare(current_source(storage, request, files))
    output, _ = compile_wire(
        files, {k: v for k, v in report["proposal"].items() if k != "recovery_parent_receipt"}
    )
    image = MoiIdentity(output)
    assert image.reader.scalar(image.reader.records[A], 3113) == 45
    assert image.reader.scalar(image.reader.records[B], 3113) == 17
    assert image.reader.scalar(image.reader.records[BOOLEAN], 3113) is True


def test_exact_previous_merged_image_is_already_recorded_without_live_claim(tmp_path):
    storage, service, request, before, files = setup(tmp_path)
    files[3] = EffectiveWireCompiler(storage.load(before["id"])[1]).merged
    report = service.prepare(current_source(storage, request, files))
    assert report["already_recorded"] and report["proposal"] is None
    assert not report["new_review_required"] and not report["controller_queries"]


def test_recompressed_current_container_retains_expanded_binding(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    files[3] = gzip.compress(MoiIdentity(files[3]).data, mtime=999)
    assert service.prepare(current_source(storage, request, files))["proposal"]["source_ref"] == A


def test_previous_source_without_a_current_observed_pin_remains_unsupported(tmp_path):
    _, service, request, _, _ = setup(tmp_path, wires=FANOUT[:2])
    with pytest.raises(ValueError, match="no observed outgoing"):
        service.prepare(request)


@pytest.mark.parametrize(
    "change",
    ["route", "device", "identity", "unverified", "directory", "application", "saved-config"],
)
def test_changed_or_unqualified_current_source_refuses(tmp_path, change):
    storage, service, request, _, files = setup(tmp_path)
    metadata = {}
    if change == "route":
        metadata["target"] = {"address": "3001:8", "router": "127.0.0.1:49000", "dnet": 3001}
    elif change == "device":
        metadata["device"] = "device,5137"
    elif change == "identity":
        metadata["identity"] = {**IDENTITY, "object-name": "Other"}
    elif change == "unverified":
        metadata["source_identity_matches"] = False
    elif change == "directory":
        files[11] = b"unknown saved directory"
    elif change == "application":
        files[3] = gzip.compress(
            MoiIdentity(files[3]).data.replace(
                b"Opaque metadata retained", b"Unsafe metadata retained"
            ),
            mtime=0,
        )
    else:
        # A non-finite saved Real is never silently merged during recovery.
        real_slot(files, 0, bytes.fromhex("7fc00000"))
    with pytest.raises(ValueError):
        service.prepare(current_source(storage, request, files, **metadata))


@pytest.mark.parametrize("outcome", ["unknown", "intent-only"])
def test_uncertain_original_requires_verified_reconciliation(tmp_path, outcome):
    storage, service, request, _, _ = setup(tmp_path, outcome=outcome)
    before = storage.receipt(request["receipt_id"], include_events=False)["result"]
    with pytest.raises(ValueError, match="Reconcile"):
        service.prepare(request)
    storage.resolve(request["receipt_id"], {"status": "verified"})
    first = service.prepare(request)
    storage.event(request["receipt_id"], "readback", {"status": "unresolved"})
    assert service.prepare(request)["origin"]["verified_proof"] == first["origin"]["verified_proof"]
    assert first["origin"]["verified_proof"]["kind"] == "readback-event"
    assert storage.receipt(request["receipt_id"], include_events=False)["result"] == before


def test_no_dispatch_cannot_be_rewritten_by_later_readback(tmp_path):
    storage, service, request, _, _ = setup(tmp_path, outcome="not_sent", possible=False)
    storage.resolve(request["receipt_id"], {"status": "verified"})
    with pytest.raises(ValueError, match="no possible"):
        service.prepare(request)


@pytest.mark.parametrize(
    "change",
    [
        "kind",
        "operation",
        "instance",
        "name",
        "boolean-index",
        "tuple-alias",
        "source",
        "payload",
        "guard",
    ],
)
def test_original_intent_must_reconstruct_exact_native_outcome(tmp_path, change):
    def mutate(body):
        if change == "kind":
            body["change_kind"] = "boolean-default"
        elif change == "operation":
            body["operation_profile"] = "unknown"
        elif change == "instance":
            body["new_instance"] = 5137
        elif change == "name":
            body["new_name"] = "Other"
        elif change == "boolean-index":
            body["wire_edit"]["wire_index"] = False
        elif change == "tuple-alias":
            body["compilation"]["wire_edit"]["old"][0] = False
        elif change == "source":
            body["compilation"]["wire_edit"]["old_source_ref"] = B
        elif change == "payload":
            body["native_payload_sha256"] = "0" * 64
        else:
            body["wire_guard"]["configuration_sha256"] = "0" * 64

    _, service, request, _, _ = setup(tmp_path, change=mutate)
    with pytest.raises(ValueError):
        service.prepare(request)


@pytest.mark.parametrize("side", ["original", "current"])
@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_original_and_current_file_integrity_required(tmp_path, side, file_id):
    storage, service, request, before, _ = setup(tmp_path)
    capture = before["id"] if side == "original" else request["capture_id"]
    (storage.directory / capture / f"file-{file_id}.bin").write_bytes(b"Tampered")
    with pytest.raises(ValueError, match="integrity"):
        service.prepare(request)


def test_token_admitted_prepare_never_opens_interface_or_creates_intent(tmp_path):
    storage, _, request, _, _ = setup(tmp_path)
    before = copy.deepcopy(storage.receipt(request["receipt_id"]))
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(BASE, json=request).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(BASE, json=request, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["proposal"]["source_ref"] == A
        for change in [
            {"receipt_id": "bad"},
            {"snapshot_sha256": "bad"},
            {"operation_id": "not-a-field-action"},
        ]:
            assert client.post(BASE, json=request | change, headers=headers).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]
    assert storage.receipt(request["receipt_id"]) == before and len(storage.receipts()) == 1
