"""Recorded inverse lineage admits typed bindings without parent/source revalidation."""

import copy
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import PROFILE as TRANSFER_PROFILE
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.native_inputs import NativeInputCompiler
from bms_tool.native_terminal_ledger import terminal_reference
from bms_tool.native_terminal_recovery_ledger import PROFILE, terminal_recovery_reference
from bms_tool.native_terminal_recovery_transfer import PROFILE as FIELD_PROFILE

from .test_change_ledger import application as application  # noqa: F401
from .test_change_ledger import native, query
from .test_native_applications import native_link
from .test_native_input_transfer import apply
from .test_native_terminal_recovery import setup
from .test_native_terminal_recovery_transfer_peer import inverse


def body(tmp_path):
    _, service, request, _, files, _ = setup(tmp_path)
    draft = service.prepare(request)
    output, compilation = NativeInputCompiler(files).compile(draft["proposal"]["edit"])
    return {
        "id": "c" * 32,
        "profile": TRANSFER_PROFILE,
        "target": {"address": "127.0.0.1:47819", "router": None, "dnet": None},
        "identity": {"device": "device,5136", "object-name": "Authored controller"},
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": "Authored controller",
        "new_name": "Authored controller",
        "change_kind": "input",
        "operation_profile": "native-local-universal-input-transfer/2",
        "physical_wiring_confirmed": True,
        "input_change_confirmed": True,
        "application_transfer_confirmed": True,
        "review_capture_id": request["capture_id"],
        "backup_id": request["capture_id"],
        "input_edit": draft["proposal"]["edit"],
        "compilation": compilation,
        "native_payload_sha256": sha(MoiIdentity(output).data),
        "payload_sha256": sha(output),
        "terminal_recovery_profile": FIELD_PROFILE,
        "terminal_recovery_lineage_enforced": True,
        "recovery_parent_receipt": request["receipt_id"],
        "recovery_origin": draft["origin"],
        "recovery_origin_sha256": draft["origin_sha256"],
    }


async def seed_recovery_records(directory):
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(directory, patch)) as generator:
            link = await anext(generator)
            _, service, parent, _, _, plan = await inverse(link)
            child = await service.apply_input(**apply(plan, "ledger-inverse"))
            assert child["result"]["status"] == "verified", child
            return parent, child


def test_valid_recorded_lineage_preserves_all_origin_references_without_authority(tmp_path):
    value = body(tmp_path)
    before = copy.deepcopy(value)
    terminal = terminal_reference(value)["native_terminal"]
    result = terminal_recovery_reference(value, terminal)["native_terminal_recovery"]
    assert result["state"] == "recorded" and result["profile"] == PROFILE
    assert result["origin"] == value["recovery_origin"]
    assert (
        result["lineage_enforced_recorded"]
        and not result["parent_and_source_revalidated"]
        and not result["transfer_authority"]
    )
    result["origin"]["previous_slot"] = 6
    assert value == before


@pytest.mark.parametrize(
    "fault",
    [
        "field-profile",
        "origin-profile",
        "seal",
        "parent",
        "self",
        "capture",
        "config",
        "old-slot",
        "after-slot",
        "proposal",
        "bool",
        "extra",
        "proof-time",
        "proof-sha",
        "same-source",
        "confirmation",
        "identity",
        "instance",
        "target-device",
        "terminal",
        "flag",
    ],
)
def test_resealed_inconsistent_or_untyped_lineage_stays_unavailable(tmp_path, fault):
    value = body(tmp_path)
    origin = value["recovery_origin"]
    if fault == "field-profile":
        value["terminal_recovery_profile"] = "future/1"
    elif fault == "origin-profile":
        origin["profile"] = "future/1"
    elif fault == "seal":
        value["recovery_origin_sha256"] = "0" * 64
    elif fault == "parent":
        value["recovery_parent_receipt"] = "0" * 32
    elif fault == "self":
        origin["parent_receipt_id"] = value["recovery_parent_receipt"] = value["id"]
    elif fault == "capture":
        origin["current_capture_id"] = "0" * 32
    elif fault == "config":
        origin["current_configuration_sha256"] = "0" * 64
    elif fault == "old-slot":
        origin["current_slot"] = 2
    elif fault == "after-slot":
        origin["recorded_after_slot"] = 2
    elif fault == "proposal":
        origin["proposal_slot"] = 2
    elif fault == "bool":
        origin["previous_slot"] = True
    elif fault == "extra":
        origin["extra"] = "unknown"
    elif fault == "proof-time":
        origin["verified_proof"]["time"] = "2026-11-05T01:00:00"
    elif fault == "proof-sha":
        origin["verified_proof"]["sha256"] = "bad"
    elif fault == "same-source":
        origin["original_backup_id"] = origin["current_capture_id"]
    elif fault == "confirmation":
        value["application_transfer_confirmed"] = False
    elif fault == "identity":
        value["identity"]["device"] = "device,999"
    elif fault == "instance":
        value["new_instance"] = True
    elif fault == "target-device":
        value["target"]["device"] = "device,999"
    elif fault == "terminal":
        value["compilation"]["terminal_compilation"]["profile"] = "bad/2"
    elif fault == "flag":
        value["terminal_recovery_lineage_enforced"] = 1
    if fault != "seal":
        value["recovery_origin_sha256"] = seal(origin)
    before = copy.deepcopy(value)
    assert (
        terminal_recovery_reference(value, terminal_reference(value)["native_terminal"])[
            "native_terminal_recovery"
        ]["state"]
        == "unavailable"
    )
    assert value == before


async def test_recorded_provenance_does_not_promote_an_uncertain_child(application, tmp_path):
    value = body(tmp_path)
    intent = native(application, **value)
    result = await query(application, source="native")
    row = next(r for r in result["rows"] if r["id"] == intent["id"])
    assert row["native_terminal_recovery"]["state"] == "recorded"
    assert row["outcome"] == "attention" and row["state"] != "verified"
    assert "native_recovery" not in row and result["field_requests"] == 0


def test_ordinary_terminal_metadata_has_no_added_recovery_projection(tmp_path):
    value = body(tmp_path)
    for key in [
        "terminal_recovery_profile",
        "terminal_recovery_lineage_enforced",
        "recovery_parent_receipt",
        "recovery_origin",
        "recovery_origin_sha256",
    ]:
        del value[key]
    assert terminal_recovery_reference(value, terminal_reference(value)["native_terminal"]) == {}


async def test_actual_inverse_survives_restart_without_parent_source_or_controller_lookup(
    tmp_path, monkeypatch
):
    parent, child = await seed_recovery_records(tmp_path)
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    before = storage.receipt(child["intent"]["id"])

    def forbidden(*args, **kwargs):
        pytest.fail("Recorded lineage attempted parent/source or controller revalidation")

    for name in ["require", "_read", "connect", "disconnect", "release"]:
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(storage, "load", forbidden)
    monkeypatch.setattr(storage, "verified_readback", forbidden)
    result = await query(app, source="native")
    row = next(r for r in result["rows"] if r["id"] == child["intent"]["id"])
    info = row["native_terminal_recovery"]
    assert (
        info["state"] == "recorded"
        and info["origin"]["parent_receipt_id"] == parent["intent"]["id"]
    )
    assert "native_recovery" not in row and not info["parent_and_source_revalidated"]
    assert result["read_only"] and result["field_requests"] == 0
    assert storage.receipt(child["intent"]["id"]) == before
