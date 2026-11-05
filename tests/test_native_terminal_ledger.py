"""Recorded profile-two terminal metadata is local and cannot inherit field authority."""

import copy
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.native_inputs import NativeInputCompiler
from bms_tool.native_terminal_ledger import terminal_reference

from .test_change_ledger import application as application  # noqa: F401
from .test_change_ledger import native, query
from .test_native_applications import native_link as native_link
from .test_native_input_transfer import apply, preview
from .test_native_inputs import source
from .test_native_terminal_input import terminal_edit
from .test_native_terminal_transfer_guards import configured_peer


def terminal_body():
    c = NativeInputCompiler(source(existing=True))
    output, compilation = c.compile(terminal_edit(c))
    return {
        "change_kind": "input",
        "operation_profile": compilation["profile"],
        "input_edit": compilation["input_edit"],
        "compilation": compilation,
        "native_payload_sha256": sha(MoiIdentity(output).data),
        "payload_sha256": sha(output),
        "physical_wiring_confirmed": True,
    }


async def seed_terminal_records(directory):
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(directory, patch)) as generator:
            link = await anext(generator)
            peer, service = configured_peer(link)
            _, plan = await preview(
                link, terminal_edit(NativeInputCompiler(peer.files)), "ledger-terminal"
            )
            result = await service.apply_input(**apply(plan, "ledger-terminal"))
            assert result["result"]["status"] == "verified", result
            return result


def test_recorded_binding_keeps_previous_destination_configuration_and_fingerprints():
    body = terminal_body()
    original = copy.deepcopy(body)
    value = terminal_reference(body)
    assert value["object"] == "analog-input,101"
    info = value["native_terminal"]
    assert info["state"] == "recorded" and info["old_slot"] == 1 and info["slot"] == 3
    assert info["old_terminal_label"] == "UI IN1" and info["terminal_label"] == "UI IN3"
    assert info["stored_configuration"] == body["compilation"]["stored_configuration"]
    assert info["wiring_confirmation_recorded"] is True
    assert "current value" in info["scope"] and "transfer authority" in info["scope"]
    assert "can_apply" not in info and "controller_write" not in info
    info["stored_configuration"]["input_low"] = 999
    assert body == original


async def test_recorded_terminal_proposal_does_not_promote_an_unverified_outcome(application):
    intent = native(application, **terminal_body())
    result = await query(application, source="native")
    row = next(r for r in result["rows"] if r["id"] == intent["id"])
    assert row["native_terminal"]["state"] == "recorded"
    assert row["state"] != "verified" and row["outcome"] == "attention"
    assert result["field_requests"] == 0


@pytest.mark.parametrize(
    "fault",
    [
        "profile",
        "compiler",
        "action",
        "edit",
        "object",
        "reference",
        "old_slot",
        "destination_bool",
        "old_label",
        "new_label",
        "source",
        "native_source",
        "artifact",
        "native_artifact",
        "record_hash",
        "property_hash",
        "seal",
        "payload",
        "overlap",
        "preserved",
        "write",
        "wiring_authority",
        "record_count",
        "original_count_bool",
        "allocation",
        "changes_bool",
        "stored_keys",
        "stored_bool",
        "stored_not_real32",
    ],
)
async def test_malformed_terminal_evidence_stays_readable_without_structured_metadata(
    application, fault
):
    body = terminal_body()
    c = body["compilation"]
    p = c["terminal_compilation"]
    if fault == "profile":
        body["operation_profile"] = "native-local-universal-input-transfer/1"
    elif fault == "compiler":
        c["profile"] = "other/2"
    elif fault == "action":
        body["input_edit"]["action"] = "mode"
    elif fault == "edit":
        c["input_edit"] = {**c["input_edit"], "slot": 2}
    elif fault == "object":
        c["object_id"] = "analog-input,102"
    elif fault == "reference":
        c["record_ref"] = "controller/module/0_101"
    elif fault == "old_slot":
        p["old_slot"] = True
    elif fault == "destination_bool":
        p["destination_slot"] = True
    elif fault == "old_label":
        p["old_device_type"] = "UI IN2"
    elif fault == "new_label":
        p["new_device_type"] = "BI IN3"
    elif fault == "source":
        p["source_sha256"] = "0" * 64
    elif fault == "native_source":
        p["source_native_sha256"] = "0" * 64
    elif fault == "artifact":
        body["payload_sha256"] = "0" * 64
    elif fault == "native_artifact":
        body["native_payload_sha256"] = "0" * 64
    elif fault == "record_hash":
        p["record_sha256"] = "bad"
    elif fault == "property_hash":
        p["slot_property_sha256"] = "bad"
    elif fault == "seal":
        p["compilation_sha256"] = "0" * 64
    elif fault == "payload":
        p["payloads"][0]["after"] = "02"
    elif fault == "overlap":
        p["payloads"][1]["offset"] = p["payloads"][0]["offset"]
    elif fault == "preserved":
        p["other_expanded_bytes_preserved"] = 1
    elif fault == "write":
        p["controller_write"] = True
    elif fault == "wiring_authority":
        p["physical_terminal_or_wiring_verified"] = True
    elif fault == "record_count":
        c["native_record_count"] += 1
    elif fault == "original_count_bool":
        c["original_native_record_count"] = True
    elif fault == "allocation":
        c["allocated_record_hex"] = "00"
    elif fault == "changes_bool":
        c["changes"][1]["before"] = True
    elif fault == "stored_keys":
        c["stored_configuration"]["extra"] = 0
    elif fault == "stored_bool":
        c["stored_configuration"]["input_low"] = False
    else:
        c["stored_configuration"]["output_high"] = 0.1
    if fault != "seal":
        p["compilation_sha256"] = seal({k: v for k, v in p.items() if k != "compilation_sha256"})
    original = copy.deepcopy(body)
    assert terminal_reference(body)["native_terminal"]["state"] == "unavailable"
    assert body == original
    intent = native(application, **body)
    result = await query(application, source="native")
    row = next(r for r in result["rows"] if r["id"] == intent["id"])
    # A wrong version belongs to its old/unknown parser, never the new profile.
    info = row.get("native_terminal", row.get("native_input"))
    assert info["state"] == "unavailable" and result["field_requests"] == 0


async def test_actual_terminal_receipt_survives_restart_without_source_or_controller_revalidation(
    tmp_path, monkeypatch
):
    receipt = await seed_terminal_records(tmp_path)
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Terminal ledger entered a source, parent or field path")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    storage = app.state.native_applications.storage
    original = storage.receipt(receipt["intent"]["id"])
    monkeypatch.setattr(storage, "load", forbidden)
    monkeypatch.setattr(storage, "verified_readback", forbidden)
    result = await query(app, source="native")
    row = next(r for r in result["rows"] if r["id"] == receipt["intent"]["id"])
    assert row["native_terminal"]["state"] == "recorded" and row["state"] == "verified"
    assert "native_input" not in row
    assert (
        row["native_terminal"]["old_terminal_label"] == "UI IN1"
        and row["native_terminal"]["terminal_label"] == "UI IN3"
    )
    assert result["read_only"] and result["field_requests"] == 0
    assert storage.receipt(receipt["intent"]["id"]) == original
