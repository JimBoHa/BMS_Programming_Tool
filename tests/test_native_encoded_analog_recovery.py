"""Previous-terminal drafts bind verified journals and original/current native files."""

import copy
import secrets
import struct

import pytest
from bacpypes3.primitivedata import Real
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_encoded_analog_recovery import PROFILE, NativeEncodedAnalogRecovery
from bms_tool.native_inputs import InputEdit, NativeInputCompiler, verify_input_preservation
from fastapi.testclient import TestClient

from .test_controller_application import encoded
from .test_native_connection_copies import filesystem
from .test_native_default_transfer import real_slot
from .test_native_encoded_terminal_input import edit as terminal_edit
from .test_native_encoded_terminal_input import nonlinear
from .test_native_inputs import initialized_input_files
from .test_native_signal_compiler import retained
from .test_native_terminal_copies import literal_effective
from .test_native_terminal_copies import setup as original_source
from .test_native_terminal_labels import observed_shape

BASE = "/api/bacnet/controller/native-application/input/encoded-terminal/recovery/prepare"


def setup(
    tmp_path, *, outcome="verified", possible=True, change=None, files=None, result_change=None
):
    storage, _, files, source = original_source(
        tmp_path, files=files or nonlinear(observed_shape(binary=False, compressed=True))
    )
    before = storage.load(source["capture_id"])[0]
    compiler = NativeInputCompiler(files)
    edit = InputEdit.model_validate(terminal_edit(compiler)).model_dump()
    output, compilation = compiler.compile(edit)
    body = {
        "id": secrets.token_hex(16),
        "target": before["target"],
        "identity": before["identity"],
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": "Authored controller",
        "new_name": "Authored controller",
        "change_kind": "input",
        "operation_profile": "native-local-universal-input-transfer/4",
        "physical_wiring_confirmed": True,
        "input_change_confirmed": True,
        "application_transfer_confirmed": True,
        "backup_id": before["id"],
        "input_edit": copy.deepcopy(edit),
        "compilation": compilation,
        "payload_sha256": sha(output),
        "native_payload_sha256": sha(MoiIdentity(output).data),
    }
    if change:
        change(body)
    intent = storage.intent(body)
    verification = {
        "intent_sha256": intent["evidence_sha256"],
        "status": outcome,
        "may_have_applied": possible,
        "operational": True,
        "system_status": 0,
        "native_sha256": sha(MoiIdentity(output).data),
        "preservation": verify_input_preservation(files, {**files, 3: output}, edit),
    }
    if result_change:
        result_change(verification)
    if outcome != "intent-only":
        storage.finish(intent["id"], verification)
    current_files = {**files, 3: output}
    current = retained(storage, current_files, identity=before["identity"])
    query = {
        "receipt_id": intent["id"],
        "capture_id": current["id"],
        "snapshot_sha256": current["evidence_sha256"],
    }
    return (
        storage,
        NativeEncodedAnalogRecovery(NativeBackupRecords(storage)),
        query,
        before,
        current_files,
        verification,
    )


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("encoding", [0, 4])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("wide", [False, True])
@pytest.mark.parametrize("slot_width", [1, 2, 3, 4])
def test_complete_literal_inverse_preserves_current_other_values_and_retained_evidence(
    tmp_path, compressed, wide, slot_width, encoding, missing
):
    original = observed_shape(
        binary=False, compressed=compressed, wide=wide, slot_width=slot_width, encoding=encoding
    )
    if missing:
        original = nonlinear(original)
    storage, service, query, before, files, _ = setup(tmp_path, files=original)
    current = copy.deepcopy(files)
    # An unrelated saved Real changes after the original move, without changing File3/11.
    real_slot(current, 4, struct.pack(">f", 9.25))
    capture = retained(storage, current, identity=before["identity"])
    query |= {"capture_id": capture["id"], "snapshot_sha256": capture["evidence_sha256"]}
    unchanged = filesystem(storage.directory)
    report = service.prepare(query)
    assert report["profile"] == PROFILE and not report["already_recorded"]
    assert report["new_review_required"] and not report["can_apply"]
    assert (
        report["read_only"]
        and not report["controller_queries"]
        and not report["controller_writes"]
        and not report["field_actions"]
    )
    assert report["parent_lineage_enforced_by_field_transfer"] is False and "token" not in report
    assert report["origin"]["previous_slot"] == report["origin"]["proposal_slot"] == 1
    assert report["origin"]["current_slot"] == report["origin"]["recorded_after_slot"] == 3
    assert seal(report["origin"]) == report["origin_sha256"]
    assert (
        seal({k: v for k, v in report.items() if k != "evidence_sha256"})
        == report["evidence_sha256"]
    )
    proposal = report["proposal"]
    assert proposal["edit"]["action"] == "encoded-terminal"
    assert (
        report["inverse_compilation"]["configuration_storage"]["linear_output_endpoints_present"]
        is not missing
    )
    assert (
        report["inverse_compilation"]["terminal_compilation"]["device_type_character_encoding"]
        == encoding
    )
    output, compiled = NativeInputCompiler(current).compile(proposal["edit"])
    expected = literal_effective(MoiIdentity(original[3]).data)
    actual = MoiIdentity(output)
    # Fresh root saved value is preserved; the selected two terminal payloads return exactly.
    assert actual.reader.scalar(actual.root, 900) == 9.25
    assert actual.data.count(encoded(Real(9.25))) == 1
    assert actual.data.replace(encoded(Real(9.25)), encoded(Real(3.5)), 1) == expected
    assert report["inverse_compilation"] == compiled and report["inverse_output_sha256"] == sha(
        output
    )
    assert verify_input_preservation(current, {**current, 3: output}, proposal["edit"])[
        "other_configuration_preserved"
    ]
    assert MoiIdentity(expected).reader.scalar(MoiIdentity(expected).root, 900) == 3.5
    assert filesystem(storage.directory) == unchanged


def test_already_previous_merged_native_image_returns_no_inverse_or_authority(tmp_path):
    storage, service, query, before, _, _ = setup(tmp_path)
    _, original = storage.load(before["id"])
    previous = {**original, 3: NativeInputCompiler(original).app.source}
    current = retained(storage, previous, identity=before["identity"])
    report = service.prepare(
        query | {"capture_id": current["id"], "snapshot_sha256": current["evidence_sha256"]}
    )
    assert report["already_recorded"] and not report["new_review_required"]
    assert all(
        report[k] is None for k in ["proposal", "inverse_compilation", "inverse_output_sha256"]
    )


@pytest.mark.parametrize(
    "outcome,possible",
    [
        ("intent-only", True),
        ("unknown", True),
        ("failed", True),
        ("not_sent", False),
        ("verified", False),
    ],
)
def test_unresolved_unverified_or_not_dispatched_parent_never_supplies_an_inverse(
    tmp_path, outcome, possible
):
    _, service, query, *_ = setup(tmp_path, outcome=outcome, possible=possible)
    with pytest.raises(ValueError):
        service.prepare(query)


@pytest.mark.parametrize(
    "key,value",
    [
        ("operation_profile", "native-local-universal-input-transfer/1"),
        ("change_kind", "signal-default"),
        ("physical_wiring_confirmed", False),
        ("input_change_confirmed", False),
        ("application_transfer_confirmed", False),
        ("new_instance", 5137),
        ("old_instance", True),
        ("payload_sha256", "0" * 64),
        ("native_payload_sha256", "0" * 64),
        ("old_name", "Different"),
    ],
)
def test_parent_identity_confirmations_profile_and_payload_are_recomputed(tmp_path, key, value):
    _, service, query, *_ = setup(tmp_path, change=lambda b: b.update({key: value}))
    with pytest.raises(ValueError):
        service.prepare(query)


@pytest.mark.parametrize(
    "fault",
    [
        "slot",
        "config",
        "compilation",
        "bool-alias",
        "extra-edit",
        "result-hash",
        "result-preservation",
    ],
)
def test_resealed_but_inconsistent_parent_or_verified_outcome_is_refused(tmp_path, fault):
    def change(b):
        if fault == "slot":
            b["input_edit"]["slot"] = 2
        elif fault == "config":
            b["input_edit"]["configuration_sha256"] = "0" * 64
        elif fault == "compilation":
            b["compilation"]["terminal_compilation"]["destination_slot"] = 2
        elif fault == "bool-alias":
            b["compilation"]["terminal_compilation"]["old_slot"] = True
        elif fault == "extra-edit":
            b["input_edit"]["unexpected"] = True

    def result(v):
        if fault == "result-hash":
            v["native_sha256"] = "0" * 64
        elif fault == "result-preservation":
            v["preservation"]["other_configuration_preserved"] = False

    _, service, query, *_ = setup(tmp_path, change=change, result_change=result)
    with pytest.raises(ValueError):
        service.prepare(query)


@pytest.mark.parametrize(
    "fault",
    ["route", "identity", "static", "program", "selected-config", "stale-snapshot", "unverified"],
)
def test_current_source_must_remain_the_recorded_controller_and_application(tmp_path, fault):
    storage, service, query, before, files, _ = setup(tmp_path)
    metadata = {"identity": before["identity"]}
    if fault == "route":
        metadata["target"] = {"address": "127.0.0.2:47819", "router": None, "dnet": None}
    elif fault == "identity":
        metadata["identity"] = {**before["identity"], "object-name": "Other"}
    elif fault == "static":
        files[11] += b"changed"
    elif fault == "program":
        files[3] = MoiIdentity(files[3]).data.replace(b"opaque footer", b"OPAQUE footer")
    elif fault == "selected-config":
        app = MoiIdentity(files[3])
        record = next(r for r in app.records if app.reader.scalar(r, 75) == "analog-input,101")
        prop = record["properties"][1293]
        files[3] = (
            app.data[: prop["value_start_offset"]]
            + encoded(Real(1))
            + app.data[prop["value_end_offset"] - 1 :]
        )
    elif fault == "unverified":
        metadata["source_identity_matches"] = False
    current = retained(storage, files, **metadata)
    query |= {"capture_id": current["id"], "snapshot_sha256": current["evidence_sha256"]}
    if fault == "stale-snapshot":
        query["snapshot_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        service.prepare(query)


def test_current_saved_selected_configuration_cannot_change_under_an_unchanged_raw_image(tmp_path):
    files = initialized_input_files(
        observed_shape(binary=False), instance=101, fields=[(1294, 4, struct.pack(">f", 10))]
    )
    storage, service, query, before, current, _ = setup(tmp_path, files=files)
    original_image = current[3]
    real_slot(current, -5, struct.pack(">f", 5))
    capture = retained(storage, current, identity=before["identity"])
    assert current[3] == original_image
    with pytest.raises(ValueError, match="configuration changed"):
        service.prepare(
            query | {"capture_id": capture["id"], "snapshot_sha256": capture["evidence_sha256"]}
        )


def test_unknown_original_dispatch_can_use_a_later_immutable_verified_readback(tmp_path):
    storage, service, query, _, _, verification = setup(tmp_path, outcome="unknown")
    verification["status"] = "verified"
    storage.resolve(query["receipt_id"], verification)
    report = service.prepare(query)
    assert report["origin"]["verified_proof"]["kind"] == "readback-event"
    assert storage.receipt(query["receipt_id"])["result"]["status"] == "unknown"


def test_strict_local_http_preparation_has_no_field_or_transfer_effect(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    storage, service, query, *_ = setup(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Local recovery preparation attempted a field/intent path")

    for name in ["require", "_read", "connect", "disconnect", "release"]:
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    before = filesystem(storage.directory)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE, json=query).status_code == 403
        response = client.post(BASE, headers=headers, json=query)
        assert response.status_code == 200 and response.json() == service.prepare(query)
        for change in [
            {"token": "A" * 32},
            {"can_apply": True},
            {"edit": {}},
            {"receipt_id": True},
            {"snapshot_sha256": "0" * 64},
        ]:
            assert client.post(BASE, headers=headers, json=query | change).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]
        assert not app.state.native_applications.plans
    assert filesystem(storage.directory) == before


@pytest.mark.parametrize("fault", ["profile", "identity", "selected-edit", "status-type"])
def test_verified_result_requires_exact_typed_preservation_evidence(tmp_path, fault):
    def changed(result):
        if fault == "profile":
            result["preservation"]["profile"] = "native-local-universal-input-transfer/2"
        elif fault == "identity":
            result["preservation"]["identity_unchanged"] = False
        elif fault == "selected-edit":
            result["preservation"]["selected_edit"]["slot"] = 3.0
        else:
            result["system_status"] = 0.0

    _, service, query, *_ = setup(tmp_path, result_change=changed)
    with pytest.raises(ValueError, match="complete native preservation"):
        service.prepare(query)


def test_legacy_terminal_receipt_cannot_supply_a_typed_recovery_proposal(tmp_path):
    from .test_native_terminal_recovery import setup as legacy_setup

    storage, _, query, *_ = legacy_setup(tmp_path)
    before = filesystem(storage.directory)
    with pytest.raises(ValueError, match="configured analog"):
        NativeEncodedAnalogRecovery(NativeBackupRecords(storage)).prepare(query)
    assert filesystem(storage.directory) == before
