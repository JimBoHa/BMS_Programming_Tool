"""Closed recorded binary lineage never opens parent/source or field paths."""

import copy
import shutil
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import PROFILE as TRANSFER_PROFILE
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.native_binary_terminal import BinaryTerminalCompiler
from bms_tool.native_binary_terminal_ledger import binary_terminal_reference
from bms_tool.native_binary_terminal_recovery_ledger import (
    PROFILE,
    SCOPE,
    binary_terminal_recovery_reference,
)
from bms_tool.native_binary_terminal_recovery_transfer import KEYS
from bms_tool.native_binary_terminal_recovery_transfer import PROFILE as FIELD_PROFILE
from bms_tool.native_inputs import NativeInputCompiler
from bms_tool.native_terminal_recovery_transfer import KEYS as LEGACY_KEYS
from fastapi.testclient import TestClient

from .test_change_ledger import application as application  # noqa: F401
from .test_change_ledger import native, query
from .test_native_applications import native_link
from .test_native_binary_terminal_recovery import setup, without_optional
from .test_native_binary_terminal_recovery_transfer_peer import inverse
from .test_native_binary_terminal_transfer import tick
from .test_native_connection_copies import filesystem
from .test_native_input_transfer import apply
from .test_native_terminal_labels import observed_shape


def body(tmp_path, *, encoding=4, absent=()):
    files = observed_shape(binary=True, compressed=True, encoding=encoding)
    storage, service, request, _, files, _ = setup(
        tmp_path, files=without_optional(files, absent) if absent else files
    )
    draft = service.prepare(request)
    output, compilation = NativeInputCompiler(files).compile(draft["proposal"]["edit"])
    current, _ = storage.load(request["capture_id"])
    return {
        "id": "c" * 32,
        "profile": TRANSFER_PROFILE,
        "target": current["target"],
        "identity": {**current["identity"], "device": "device,5136"},
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": "Authored controller",
        "new_name": "Authored controller",
        "change_kind": "input",
        "operation_profile": compilation["profile"],
        "physical_wiring_confirmed": True,
        "input_change_confirmed": True,
        "application_transfer_confirmed": True,
        "review_capture_id": request["capture_id"],
        "backup_id": "d" * 32,
        "input_edit": draft["proposal"]["edit"],
        "compilation": compilation,
        "native_payload_sha256": sha(MoiIdentity(output).data),
        "payload_sha256": sha(output),
        "binary_terminal_recovery_profile": FIELD_PROFILE,
        "binary_terminal_recovery_lineage_enforced": True,
        "binary_terminal_recovery_parent_receipt": request["receipt_id"],
        "binary_terminal_recovery_origin": draft["origin"],
        "binary_terminal_recovery_origin_sha256": draft["origin_sha256"],
    }


async def seed_recovery_records(directory, *, uncertain=False):
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(directory, patch)) as generator:
            link = await anext(generator)
            peer, service, parent, _, _, plan = await inverse(link, counters=True)
            for offset, value in zip(peer.recovery_counter_offsets, (999999, 1000000), strict=True):
                tick(peer, offset, value)
            if uncertain:
                peer.mode = "drop-end"
            child = await service.apply_input(**apply(plan, "binary-ledger-inverse"))
            assert child["result"]["status"] == ("unknown" if uncertain else "verified"), child
            return parent, child


def reference(value, terminal=None):
    if terminal is None:
        terminal = binary_terminal_reference(value)["native_binary_terminal"]
    return binary_terminal_recovery_reference(value, terminal)["native_binary_terminal_recovery"]


@pytest.mark.parametrize("encoding", [0, 4])
@pytest.mark.parametrize("absent", [(), (15,), (33,), (84,), (15, 33, 84)])
def test_recorded_origin_preserves_typed_configuration_presence_charset_without_authority(
    tmp_path, encoding, absent
):
    value = body(tmp_path, encoding=encoding, absent=absent)
    before = copy.deepcopy(value)
    terminal = binary_terminal_reference(value)["native_binary_terminal"]
    result = reference(value, terminal)
    assert result == {
        "state": "recorded",
        "profile": PROFILE,
        "origin": value["binary_terminal_recovery_origin"],
        "origin_sha256": value["binary_terminal_recovery_origin_sha256"],
        "instance": 5136,
        "lineage_enforced_recorded": True,
        "parent_and_source_revalidated": False,
        "transfer_authority": False,
        "scope": SCOPE,
    }
    assert len(result["origin"]) == 16
    assert terminal["old_slot"] == 3 and terminal["slot"] == 1
    assert terminal["device_type_character_encoding"] == encoding
    assert terminal["stored_configuration"]["polarity"] == (None if 84 in absent else 1)
    assert set(terminal["captured_counter_values"]) == {"15", "33"} - set(map(str, absent))
    assert terminal["stored_configuration"] == value["compilation"]["stored_configuration"]
    result["origin"]["verified_proof"]["sha256"] = "0" * 64
    terminal["stored_configuration"]["states_text_index"] = 999
    assert value == before


@pytest.mark.parametrize(
    "key,replacement",
    [
        ("profile", "native-analog-terminal-recovery-draft/1"),
        ("parent_receipt_id", "0" * 32),
        ("parent_intent_sha256", "bad"),
        ("original_dispatch", True),
        ("original_backup_id", True),
        ("original_snapshot_sha256", "bad"),
        ("current_capture_id", "0" * 32),
        ("current_snapshot_sha256", True),
        ("object_id", "binary-input,102"),
        ("record_ref", "controller/3_102"),
        ("previous_slot", True),
        ("recorded_after_slot", 3.0),
        ("current_slot", 2),
        ("proposal_slot", 2),
        ("current_configuration_sha256", "0" * 64),
        ("extra", "unknown"),
        ("verified_proof", {"kind": "result", "sha256": "0" * 64, "time": "2026-11-05"}),
        (
            "verified_proof",
            {"kind": "result", "sha256": "bad", "time": "2026-11-05T00:00:00+00:00"},
        ),
    ],
)
def test_resealed_inconsistent_untyped_and_unknown_origin_fields_are_unavailable(
    tmp_path, key, replacement
):
    value = body(tmp_path)
    value["binary_terminal_recovery_origin"][key] = replacement
    value["binary_terminal_recovery_origin_sha256"] = seal(value["binary_terminal_recovery_origin"])
    before = copy.deepcopy(value)
    assert reference(value)["state"] == "unavailable"
    assert value == before


@pytest.mark.parametrize("key", sorted(KEYS))
def test_each_namespace_field_is_required_and_missing_lineage_never_falls_back(tmp_path, key):
    value = body(tmp_path)
    del value[key]
    assert reference(value)["state"] == "unavailable"


@pytest.mark.parametrize("key", sorted(LEGACY_KEYS))
def test_even_null_or_apparently_matching_legacy_lineage_cannot_mix_namespaces(tmp_path, key):
    value = body(tmp_path)
    value[key] = value["binary_terminal_recovery_origin"] if key == "recovery_origin" else None
    assert reference(value)["state"] == "unavailable"


@pytest.mark.parametrize(
    "fault",
    [
        "transfer-profile",
        "field-profile",
        "origin-seal",
        "self-parent",
        "same-source",
        "same-backup",
        "same-terminals",
        "flag",
        "child-id",
        "identity",
        "instance",
        "target-device",
        "target-address",
        "confirmation",
        "typed-config",
        "presence",
        "charset",
        "forged-terminal",
    ],
)
def test_child_bindings_and_independent_base_evidence_are_required(tmp_path, fault):
    value = body(tmp_path)
    origin = value["binary_terminal_recovery_origin"]
    terminal = None
    if fault == "transfer-profile":
        value["profile"] = "future/1"
    elif fault == "field-profile":
        value["binary_terminal_recovery_profile"] = "future/1"
    elif fault == "origin-seal":
        value["binary_terminal_recovery_origin_sha256"] = "0" * 64
    elif fault == "self-parent":
        origin["parent_receipt_id"] = value["binary_terminal_recovery_parent_receipt"] = value["id"]
    elif fault == "same-source":
        origin["original_backup_id"] = origin["current_capture_id"]
    elif fault == "same-backup":
        value["backup_id"] = origin["original_backup_id"]
    elif fault == "same-terminals":
        origin["previous_slot"] = origin["proposal_slot"] = origin["current_slot"]
    elif fault == "flag":
        value["binary_terminal_recovery_lineage_enforced"] = 1
    elif fault == "child-id":
        value["id"] = True
    elif fault == "identity":
        value["identity"]["device"] = "device,999"
    elif fault == "instance":
        value["new_instance"] = True
    elif fault == "target-device":
        value["target"]["device"] = "device,999"
    elif fault == "target-address":
        value["target"]["address"] = ""
    elif fault == "confirmation":
        value["physical_wiring_confirmed"] = 1
    elif fault == "typed-config":
        value["compilation"]["stored_configuration"]["polarity"] = True
    elif fault == "presence":
        value["compilation"]["captured_counter_values"]["other"] = 1
    elif fault == "charset":
        proof = value["compilation"]["terminal_compilation"]
        proof["device_type_character_encoding"] = False
        proof["compilation_sha256"] = seal(
            {k: v for k, v in proof.items() if k != "compilation_sha256"}
        )
    elif fault == "forged-terminal":
        terminal = binary_terminal_reference(value)["native_binary_terminal"]
        terminal["stored_configuration"]["states_text_index"] = 999
    if fault != "origin-seal":
        value["binary_terminal_recovery_origin_sha256"] = seal(origin)
    before = copy.deepcopy(value)
    assert reference(value, terminal)["state"] == "unavailable"
    assert value == before


def test_ordinary_profile_three_has_no_recovery_projection(tmp_path):
    value = body(tmp_path)
    for key in KEYS:
        del value[key]
    assert binary_terminal_recovery_reference(value, None) == {}


async def test_ordinary_binary_body_preserves_legacy_unavailable_lineage(application, tmp_path):
    value = body(tmp_path)
    value["recovery_origin"] = value["binary_terminal_recovery_origin"]
    value["recovery_origin_sha256"] = value["binary_terminal_recovery_origin_sha256"]
    for key in KEYS:
        del value[key]
    intent = native(application, **value)
    result = await query(application, source="native")
    row = next(r for r in result["rows"] if r["id"] == intent["id"])
    assert row["native_binary_terminal"]["state"] == "recorded"
    assert row["native_terminal_recovery"]["state"] == "unavailable"
    assert "native_binary_terminal_recovery" not in row and "native_recovery" not in row
    assert row["outcome"] == "attention" and result["field_requests"] == 0


@pytest.mark.parametrize("fault", ["missing", "legacy", "profile-action", "kind"])
async def test_invalid_binary_lineage_never_dispatches_to_legacy_families(
    application, tmp_path, fault
):
    value = body(tmp_path)
    if fault == "missing":
        del value["binary_terminal_recovery_origin"]
    elif fault == "legacy":
        value["recovery_origin"] = value["binary_terminal_recovery_origin"]
        value["recovery_origin_sha256"] = value["binary_terminal_recovery_origin_sha256"]
    elif fault == "profile-action":
        value["operation_profile"] = "native-local-universal-input-transfer/2"
        value["input_edit"]["action"] = "terminal"
    else:
        value["change_kind"] = "signal-default"
    intent = native(application, **value)
    result = await query(application, source="native")
    row = next(r for r in result["rows"] if r["id"] == intent["id"])
    assert row["native_binary_terminal_recovery"]["state"] == "unavailable"
    assert not {
        "native_recovery",
        "native_terminal_recovery",
        "native_input",
        "native_terminal",
        "native_encoded_analog_terminal",
    }.intersection(row)
    assert row["outcome"] == "attention" and row["state"] != "verified"
    assert result["field_requests"] == 0


@pytest.mark.parametrize("uncertain", [False, True])
async def test_actual_child_http_history_survives_restart_without_parent_source_compiler_or_io(
    tmp_path, monkeypatch, uncertain
):
    parent, child = await seed_recovery_records(tmp_path, uncertain=uncertain)
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    identifier = child["intent"]["id"]
    before = storage.receipt(identifier)
    original_download = (
        TestClient(app)
        .get("/api/bacnet/controller/native-application/receipts/" + identifier)
        .content
    )
    # Parent availability is deliberately removed in this authored store: the child
    # reports its immutable origin, without claiming the parent is still available.
    with app.state.store.connect() as db:
        db.execute("DELETE FROM application_transfers WHERE id=?", (parent["intent"]["id"],))
    for folder in list(storage.directory.iterdir()):
        if folder.is_dir():
            shutil.rmtree(folder)
    original_receipt = storage.receipt

    def receipt(receipt_id, **kwargs):
        assert receipt_id == identifier, "Recorded projection attempted a parent receipt lookup"
        return original_receipt(receipt_id, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("Recorded lineage attempted source, compiler, journal mutation or field access")

    monkeypatch.setattr(storage, "receipt", receipt)
    for name in ("load", "verified_readback", "intent", "finish", "resolve", "save"):
        monkeypatch.setattr(storage, name, forbidden)
    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(NativeInputCompiler, "__init__", forbidden)
    monkeypatch.setattr(BinaryTerminalCompiler, "__init__", forbidden)
    retained_files = filesystem(storage.directory)
    client = TestClient(app)
    headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
    response = client.post("/api/changes/query", headers=headers, json={"source": "native"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert not result["errors"] and result["read_only"] and result["field_requests"] == 0
    row = next(r for r in result["rows"] if r["id"] == identifier)
    info = row["native_binary_terminal_recovery"]
    assert info["state"] == "recorded" and info["profile"] == PROFILE
    assert info["origin"] == before["intent"]["binary_terminal_recovery_origin"]
    assert info["origin"]["parent_receipt_id"] == parent["intent"]["id"]
    assert not info["parent_and_source_revalidated"] and not info["transfer_authority"]
    assert row["state"] == ("unknown" if uncertain else "verified")
    assert row["outcome"] == ("attention" if uncertain else "verified")
    assert row["native_binary_terminal"]["state"] == "recorded"
    assert not {"native_recovery", "native_terminal_recovery", "native_terminal"}.intersection(row)
    exported = client.get("/api" + row["detail_path"])
    assert exported.status_code == 200 and exported.json() == before
    assert exported.content == original_download
    assert row["native_binary_terminal"]["captured_counter_values"] == {"15": 999999, "33": 1000000}
    assert (
        parent["intent"]["compilation"]["captured_counter_values"]
        != row["native_binary_terminal"]["captured_counter_values"]
    )
    assert original_receipt(identifier) == before
    assert filesystem(storage.directory) == retained_files
    assert not app.state.native_applications.plans
    assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize(
    "key",
    [
        "encoded_analog_recovery_profile",
        "encoded_analog_recovery_origin",
        "encoded_analog_recovery_origin_sha256",
        "encoded_analog_recovery_parent_receipt",
        "encoded_analog_recovery_lineage_enforced",
    ],
)
def test_mixed_new_analog_namespace_cannot_supply_recorded_binary_lineage(tmp_path, key):
    value = body(tmp_path)
    value[key] = None
    assert reference(value)["state"] == "unavailable"


@pytest.mark.parametrize("value", [None, True, "", "bad", "A" * 32])
def test_child_backup_identifier_is_required_typed_and_complete(tmp_path, value):
    child = body(tmp_path)
    child["backup_id"] = value
    assert reference(child)["state"] == "unavailable"


def test_child_backup_is_a_distinct_fresh_capture_from_selected_source(tmp_path):
    child = body(tmp_path)
    child["backup_id"] = child["binary_terminal_recovery_origin"]["current_capture_id"]
    assert reference(child)["state"] == "unavailable"
    del child["backup_id"]
    assert reference(child)["state"] == "unavailable"


@pytest.mark.parametrize(
    "counters",
    [
        {"15": -1},
        {"15": 4294967296},
        {"15": True},
        {"33": 1.0},
        {"33": "1"},
        None,
        [],
        {"other": 1},
    ],
)
def test_child_counter_metadata_requires_closed_optional_unsigned32_values(tmp_path, counters):
    child = body(tmp_path)
    child["compilation"]["captured_counter_values"] = counters
    assert reference(child)["state"] == "unavailable"


@pytest.mark.parametrize("counters", [{}, {"15": 0}, {"33": 4294967295}, {"15": 3, "33": 7}])
def test_historical_counter_shape_is_not_compared_with_unavailable_parent_values(
    tmp_path, counters
):
    child = body(tmp_path)
    child["compilation"]["captured_counter_values"] = counters
    info = reference(child)
    assert info["state"] == "recorded"
    assert info["parent_and_source_revalidated"] is False and info["transfer_authority"] is False
    assert len(info["origin"]) == 16 and "captured_counter_values" not in info["origin"]


@pytest.mark.parametrize("only_unknown", [False, True])
async def test_unknown_binary_namespace_dominates_fallback_and_stays_unavailable(
    application, tmp_path, only_unknown
):
    value = body(tmp_path)
    if only_unknown:
        for key in KEYS:
            del value[key]
    value["binary_terminal_recovery_unknown"] = "future"
    assert reference(value)["state"] == "unavailable"
    intent = native(application, **value)
    response = await query(application, source="native")
    row = next(row for row in response["rows"] if row["id"] == intent["id"])
    assert row["native_binary_terminal_recovery"]["state"] == "unavailable"
    assert row["native_binary_terminal"]["state"] == "recorded"
    assert not {
        "native_recovery",
        "native_terminal_recovery",
        "native_encoded_analog_recovery",
    }.intersection(row)


@pytest.mark.parametrize(
    "kind", ["connection", "point-name", "signal-default", [], None, "unknown"]
)
async def test_new_namespace_never_falls_back_for_other_or_malformed_kinds(
    application, tmp_path, kind
):
    value = body(tmp_path)
    value["change_kind"] = kind
    value["recovery_origin"] = {"profile": "native-point-name-recovery-draft/1"}
    value["connection_edit"] = {"record_ref": "controller/other"}
    intent = native(application, **value)
    response = await query(application, source="native")
    row = next(row for row in response["rows"] if row["id"] == intent["id"])
    assert row["native_binary_terminal_recovery"]["state"] == "unavailable"
    assert not {
        "native_recovery",
        "native_terminal_recovery",
        "native_encoded_analog_recovery",
        "native_encoded_analog_terminal",
        "native_connection",
        "native_point_name",
        "native_point_name_recovery",
        "native_input",
    }.intersection(row)
    assert response["field_requests"] == 0


async def test_mixed_new_binary_and_analog_namespace_never_projects_analog_links(
    application, tmp_path
):
    value = body(tmp_path)
    value["encoded_analog_recovery_profile"] = "native-encoded-analog-terminal-recovery-transfer/1"
    value["encoded_analog_recovery_parent_receipt"] = "a" * 32
    value["input_edit"]["action"] = "encoded-terminal"
    value["operation_profile"] = "native-local-universal-input-transfer/4"
    intent = native(application, **value)
    response = await query(application, source="native")
    row = next(row for row in response["rows"] if row["id"] == intent["id"])
    assert row["native_binary_terminal_recovery"]["state"] == "unavailable"
    assert not {
        "native_encoded_analog_recovery",
        "native_encoded_analog_terminal",
        "native_recovery",
        "native_terminal_recovery",
    }.intersection(row)
