"""Previous effective values require immutable outcome and exact current image evidence."""

import gzip
import secrets
import struct

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.mstp import header_crc
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_default_recovery import NativeDefaultRecovery
from bms_tool.native_default_transfer import PROFILE as DEFAULT_PROFILE
from bms_tool.native_default_transfer import compile_default
from bms_tool.native_signal_compiler import SignalCompilerService
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_signal_compiler import FIRST, SECOND, query, retained, signal_files

BASE = "/api/bacnet/controller/native-application/signal-default/recovery/prepare"


def set_saved(files, value, *, second=False):
    changed = dict(files)
    data = bytearray(files[12])
    position = len(data) - (5 if second else 10)
    payload = struct.pack(">f", value)
    data[position : position + 5] = payload + bytes([header_crc(payload) ^ 255])
    changed[12] = bytes(data)
    return changed


def setup(
    tmp_path,
    *,
    outcome="verified",
    may_have_applied=True,
    changes=None,
    compressed=False,
    previous=42.0,
    after="-0.0",
):
    storage = ApplicationStore(Store(tmp_path))
    before_files = signal_files(compressed=compressed)
    if struct.pack(">f", previous) != struct.pack(">f", 42):
        before_files = set_saved(before_files, previous)
    identity = {
        "device": "device,5136",
        "object-name": "Authored controller",
        "model-name": "UNLISTED-MODEL",
        "vendor-identifier": 5,
    }
    before = retained(storage, before_files, identity=identity)
    src = SignalCompilerService(storage).source(before["id"])
    edit = {
        k: v
        for k, v in query(src, value=after).items()
        if k in {"record_ref", "encoded_sha256", "value_text"}
    }
    output, compilation = compile_default(before_files, edit)
    parent_id = secrets.token_hex(16)
    intent = storage.intent(
        {
            "id": parent_id,
            "target": before["target"],
            "identity": before["identity"],
            "old_instance": 5136,
            "new_instance": 5136,
            "old_name": before["identity"]["object-name"],
            "new_name": before["identity"]["object-name"],
            "change_kind": "signal-default",
            "operation_profile": DEFAULT_PROFILE,
            "backup_id": before["id"],
            "default_edit": edit,
            "compilation": compilation,
            "payload_sha256": sha(output),
            "native_payload_sha256": sha(MoiIdentity(output).data),
            **(changes or {}),
        }
    )
    if outcome != "intent-only":
        storage.finish(
            parent_id,
            {
                "intent_sha256": intent["evidence_sha256"],
                "status": outcome,
                "may_have_applied": may_have_applied,
            },
        )
    current_files = set_saved({**before_files, 3: output}, float(after))
    current = retained(storage, current_files, identity=identity)
    request = {
        "receipt_id": parent_id,
        "capture_id": current["id"],
        "snapshot_sha256": current["evidence_sha256"],
    }
    return (
        storage,
        NativeDefaultRecovery(NativeBackupRecords(storage)),
        request,
        before,
        current_files,
    )


def current_source(storage, request, files, **metadata):
    metadata.setdefault("identity", storage.load(request["capture_id"])[0]["identity"])
    snap = retained(storage, files, **metadata)
    return {**request, "capture_id": snap["id"], "snapshot_sha256": snap["evidence_sha256"]}


def test_local_proposal_uses_previous_effective_value_instead_of_archive_default(tmp_path):
    storage, service, request, before, files = setup(tmp_path)
    old_receipt = storage.receipt(request["receipt_id"])
    result = service.prepare(request)
    assert result["profile"] == "native-real-default-recovery-draft/1"
    assert result["previous_effective_value"] == 42.0  # Original archive value was 23.5.
    assert result["origin"]["previous_effective_bits"] == struct.pack(">f", 42).hex()
    assert result["origin"]["recorded_after_bits"] == "80000000"
    assert result["proposal"]["value_text"] == "42.0"
    assert result["proposal"]["recovery_parent_receipt"] == request["receipt_id"]
    assert result["read_only"] and result["new_review_required"] and not result["can_apply"]
    assert not result["controller_queries"] and not result["field_actions"]
    assert storage.receipt(request["receipt_id"]) == old_receipt
    assert len(storage.receipts()) == 1
    assert storage.load(request["capture_id"])[1] == files
    assert storage.load(before["id"])[1] == signal_files(compressed=False)


def test_other_current_saved_values_remain_current_in_the_new_compilation(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    files = set_saved(files, 17.5, second=True)
    request = current_source(storage, request, files)
    proposal = service.prepare(request)["proposal"]
    output, compiled = compile_default(
        files, {k: proposal[k] for k in ["record_ref", "encoded_sha256", "value_text"]}
    )
    assert compiled["selected_edit"]["before_bits"] == "80000000"
    assert compiled["selected_edit"]["after_bits"] == struct.pack(">f", 42).hex()
    # Inspect the actual compiled archive without re-merging the old selected slot.
    from bms_tool.moi_signal_defaults import MoiSignalDefaults

    parsed = MoiSignalDefaults(output)
    record, prop = parsed.candidates[SECOND]
    assert prop["scalar"]["value"] == 17.5
    assert parsed.candidates[FIRST][1]["scalar"]["value"] == 42.0


@pytest.mark.parametrize("previous", [-0.0, 1.401298464324817e-45, -3.4028234663852886e38])
def test_previous_finite_float32_bits_round_trip_exactly(tmp_path, previous):
    _, service, request, _, files = setup(tmp_path, previous=previous, after="42")
    prepared = service.prepare(request)
    proposal = prepared["proposal"]
    _, compiled = compile_default(
        files, {key: proposal[key] for key in ("record_ref", "encoded_sha256", "value_text")}
    )
    assert compiled["selected_edit"]["after_bits"] == struct.pack(">f", previous).hex()
    if previous == 0:
        assert proposal["value_text"] == "-0.0"


@pytest.mark.parametrize("compressed", [False, True])
def test_container_recompression_preserves_native_image_qualification(tmp_path, compressed):
    storage, service, request, _, files = setup(tmp_path, compressed=compressed)
    native = MoiIdentity(files[3]).data
    changed = {**files, 3: gzip.compress(native, mtime=123)}
    request = current_source(storage, request, changed)
    assert service.prepare(request)["proposal"]["value_text"] == "42.0"


def test_already_recorded_previous_value_is_not_a_controller_restore_claim(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    request = current_source(storage, request, set_saved(files, 42))
    result = service.prepare(request)
    assert result["already_recorded"] and result["proposal"] is None
    assert not result["new_review_required"] and not result["can_apply"]
    assert result["origin"]["current_effective_bits"] == result["origin"]["previous_effective_bits"]
    assert not result["controller_queries"]


def test_changed_selected_saved_value_refuses_instead_of_overwriting_another_edit(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    request = current_source(storage, request, set_saved(files, 19.0))
    with pytest.raises(ValueError, match="effective value changed"):
        service.prepare(request)


def test_changed_application_refuses_even_if_the_selected_value_is_still_the_outcome(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    from bms_tool.moi_signal_defaults import MoiSignalDefaults

    edit = MoiSignalDefaults(files[3])
    record, prop = edit.candidates[SECOND]
    preview = edit.preview(
        source_sha256=sha(files[3]),
        record_ref=SECOND,
        encoded_sha256=prop["encoded_sha256"],
        value_text="9.0",
    )
    changed, _ = edit.export(
        source_sha256=sha(files[3]),
        record_ref=SECOND,
        encoded_sha256=prop["encoded_sha256"],
        value_text="9.0",
        plan_sha256=preview["plan_sha256"],
    )
    request = current_source(storage, request, {**files, 3: changed})
    with pytest.raises(ValueError, match="application or static"):
        service.prepare(request)


@pytest.mark.parametrize("which", ["route", "device", "identity", "unverified", "saved-schema"])
def test_different_or_unqualified_current_source_refuses(tmp_path, which):
    storage, service, request, _, files = setup(tmp_path)
    metadata = {}
    if which == "route":
        metadata["target"] = {"address": "3001:8", "router": "127.0.0.1:49000", "dnet": 3001}
    if which == "device":
        metadata["device"] = "device,5137"
    if which == "identity":
        metadata["identity"] = {
            "object-name": "Other",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 5,
        }
    if which == "unverified":
        metadata["source_identity_matches"] = False
    if which == "saved-schema":
        files = {**files, 11: b"Unknown directory"}
    request = current_source(storage, request, files, **metadata)
    with pytest.raises(ValueError):
        service.prepare(request)


def test_new_engineering_bind_is_allowed_only_as_a_local_proposal(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    request = current_source(
        storage, request, files, connector_config={"local_address": "127.0.0.1:49023"}
    )
    assert service.prepare(request)["proposal"]["record_ref"] == FIRST


@pytest.mark.parametrize("outcome", ["unknown", "intent-only"])
def test_pending_original_outcome_never_grants_recovery(tmp_path, outcome):
    _, service, request, _, _ = setup(tmp_path, outcome=outcome)
    with pytest.raises(ValueError, match="Reconcile"):
        service.prepare(request)


@pytest.mark.parametrize("outcome", ["unknown", "intent-only"])
def test_historical_verified_readback_survives_later_observations_without_rewriting_dispatch(
    tmp_path, outcome
):
    storage, service, request, _, _ = setup(tmp_path, outcome=outcome)
    original = storage.receipt(request["receipt_id"], include_events=False)["result"]
    storage.resolve(
        request["receipt_id"], {"status": "verified", "authored": "Original independent readback"}
    )
    first = service.prepare(request)
    storage.event(
        request["receipt_id"],
        "readback",
        {"status": "unresolved", "authored": "Later unrelated saved setting"},
    )
    second = service.prepare(request)
    assert first["origin"]["verified_proof"] == second["origin"]["verified_proof"]
    assert second["origin"]["verified_proof"]["kind"] == "readback-event"
    assert storage.receipt(request["receipt_id"], include_events=False)["result"] == original


def test_explicit_no_dispatch_refusal_is_not_rewritten_by_later_matching_readback(tmp_path):
    storage, service, request, _, _ = setup(tmp_path, outcome="refused", may_have_applied=False)
    storage.resolve(request["receipt_id"], {"status": "verified"})
    with pytest.raises(ValueError, match="no possible application dispatch"):
        service.prepare(request)


def test_local_http_preparation_requires_token_and_has_no_field_or_intent_side_effects(tmp_path):
    storage, _, request, _, _ = setup(tmp_path)
    original = storage.receipt(request["receipt_id"])
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.post(BASE, json=request).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(BASE, json=request, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["proposal"]["value_text"] == "42.0"
        for change in [
            {"capture_id": "../outside"},
            {"snapshot_sha256": "bad"},
            {"receipt_id": "not-a-receipt"},
            {"operation_id": "not-a-field-operation"},
        ]:
            assert client.post(BASE, json=request | change, headers=headers).status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False
        assert not app.state.native_applications.plans
        assert app.state.native_applications.storage.receipt(request["receipt_id"]) == original
        assert len(storage.receipts()) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"change_kind": "name"},
        {"change_kind": "boolean-default"},
        {"operation_profile": "unknown"},
        {"new_instance": 5137},
        {"new_name": "Other"},
        {"backup_id": "../outside"},
        {"native_payload_sha256": "0" * 64},
        {"default_edit": None},
        {"compilation": None},
    ],
)
def test_unsupported_or_inconsistent_parent_evidence_refuses(tmp_path, changes):
    _, service, request, _, _ = setup(tmp_path, changes=changes)
    with pytest.raises(ValueError):
        service.prepare(request)


@pytest.mark.parametrize("side", ["original", "current"])
@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_tampered_original_or_current_files_cannot_prepare_a_proposal(tmp_path, side, file_id):
    storage, service, request, before, _ = setup(tmp_path)
    capture = before["id"] if side == "original" else request["capture_id"]
    (storage.directory / capture / f"file-{file_id}.bin").write_bytes(b"Tampered")
    with pytest.raises(ValueError, match="integrity"):
        service.prepare(request)
