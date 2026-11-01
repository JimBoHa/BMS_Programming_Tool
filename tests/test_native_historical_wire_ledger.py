"""Recorded original-pin lineage remains local metadata, without new write authority."""

import secrets

import pytest
from bms_tool.moi_identity import seal, sha
from bms_tool.native_wire_transfer import compile_wire

from .test_change_ledger import application as application  # noqa: F401
from .test_change_ledger import query
from .test_moi_wire_sources import REF, A
from .test_native_historical_wire_copies import local_case


def recorded(app, change=None, *, possible=True):
    storage, recovery, report, body, _, files = local_case(app.state.store.directory)
    snapshot = storage.load(body["capture_id"])[0]
    edit = {
        k: v
        for k, v in body.items()
        if k not in {"recovery_parent_receipt", "recovery_origin_sha256"}
    }
    output, compilation = compile_wire(files, edit, _compiler=recovery.compiler_for(report, files))
    purpose = {
        "id": secrets.token_hex(16),
        "target": snapshot["target"],
        "identity": snapshot["identity"],
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": snapshot["identity"]["object-name"],
        "new_name": snapshot["identity"]["object-name"],
        "connector_config": snapshot["connector_config"],
        "change_kind": "wire-source",
        "operation_profile": "native-effective-wire-source-transfer/1",
        "review_capture_id": body["capture_id"],
        "backup_id": body["capture_id"],
        "wire_edit": edit,
        "wire_guard": compilation["wire_guard"],
        "compilation": compilation,
        "payload_sha256": sha(output),
        "native_payload_sha256": compilation["compiled_native_sha256"],
        "recovery_origin": report["origin"],
        "recovery_origin_sha256": report["origin_sha256"],
    }
    if change:
        change(purpose)
    intent = storage.intent(purpose)
    storage.finish(
        intent["id"],
        {
            "intent_sha256": intent["evidence_sha256"],
            "status": "unknown" if possible else "not_sent",
            "may_have_applied": possible,
        },
    )
    return storage, intent, body["recovery_parent_receipt"]


@pytest.mark.parametrize("possible", [False, True])
async def test_lineage_records_pin_and_keeps_original_dispatch_independent(
    application, monkeypatch, possible
):
    storage, intent, parent = recorded(application, possible=possible)
    storage.resolve(intent["id"], {"status": "verified"})
    before = storage.receipt(intent["id"])

    def forbidden(*args):
        pytest.fail("Recorded pin listing tried to revalidate source/parent files")

    monkeypatch.setattr(application.state.native_applications.storage, "load", forbidden)
    monkeypatch.setattr(
        application.state.native_applications.storage, "verified_readback", forbidden
    )
    report = await query(application, source="native", text=intent["id"])
    assert not report["errors"] and len(report["rows"]) == 1 and report["field_requests"] == 0
    row = report["rows"][0]
    lineage = row["native_recovery"]
    assert (
        row["dispatch"] == ("possible" if possible else "not entered")
        and row["readback"] == "verified"
    )
    assert (
        lineage["state"] == "recorded"
        and lineage["datatype"] == "Wire"
        and lineage["parent_receipt_id"] == parent
    )
    assert (
        lineage["historical_pin"]["source_ref"] == A
        and lineage["historical_pin"]["source_port"] == 85
    )
    assert lineage["historical_pin"]["source_class"] == 551
    assert (
        lineage["historical_pin"]["evidence_sha256"]
        == intent["recovery_origin"]["historical_pin_sha256"]
    )
    assert "no current outgoing connection" in lineage["historical_pin"]["scope"]
    assert storage.receipt(intent["id"]) == before


@pytest.mark.parametrize(
    "change",
    [
        "profile",
        "pin-sha",
        "compiled-sha",
        "port",
        "source-class",
        "source-signature",
        "original-capture",
        "wire-alias",
        "child-class-alias",
        "child-profile",
        "origin-seal",
        "current-capture",
    ],
)
async def test_malformed_pin_provenance_stays_readable_and_unavailable(application, change):
    def mutate(body):
        origin = body["recovery_origin"]
        pin = origin["historical_pin"]
        if change == "profile":
            pin["profile"] = "unknown"
        elif change == "pin-sha":
            origin["historical_pin_sha256"] = "0" * 64
        elif change == "compiled-sha":
            body["compilation"]["historical_pin_evidence_sha256"] = "0" * 64
        elif change == "port":
            pin["old"][1] = 86
        elif change == "source-class":
            pin["source_class"] = 530
        elif change == "source-signature":
            pin["source_configuration_sha256"] = "0" * 64
        elif change == "original-capture":
            pin["original_capture_id"] = "0" * 32
        elif change == "wire-alias":
            pin["wire_index"] = False
        elif change == "child-class-alias":
            body["compilation"]["wire_edit"]["source_class"] = True
        elif change == "child-profile":
            body["compilation"]["wire_edit"]["profile"] = "unknown"
        elif change == "current-capture":
            origin["current_capture_id"] = "0" * 32
        body["recovery_origin_sha256"] = "0" * 64 if change == "origin-seal" else seal(origin)

    storage, intent, _ = recorded(application, mutate)
    before = storage.receipt(intent["id"])
    report = await query(application, source="native", text=intent["id"])
    assert not report["errors"] and len(report["rows"]) == 1 and report["field_requests"] == 0
    row = report["rows"][0]
    assert row["object"] == REF and row["native_recovery"]["state"] == "unavailable"
    assert row["dispatch"] == "possible" and storage.receipt(intent["id"]) == before
