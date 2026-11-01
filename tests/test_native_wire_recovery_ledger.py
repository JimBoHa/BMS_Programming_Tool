"""Wire lineage remains bounded recorded evidence, separate from transfer authority."""

import secrets

import pytest
from bms_tool.moi_identity import seal, sha
from bms_tool.native_wire_transfer import PROFILE as TRANSFER_PROFILE
from bms_tool.native_wire_transfer import compile_wire

from .test_change_ledger import application as application  # noqa: F401
from .test_change_ledger import query
from .test_moi_wire_sources import REF, A, B
from .test_native_wire_recovery import setup


def recovery_record(app, change=None, *, possible=True, parent_outcome="verified", index=0):
    storage, service, request, _, files = setup(
        app.state.store.directory, outcome=parent_outcome, index=index
    )
    if parent_outcome != "verified":
        storage.resolve(request["receipt_id"], {"status": "verified"})
    report = service.prepare(request)
    source = storage.load(request["capture_id"])[0]
    edit = {k: v for k, v in report["proposal"].items() if k != "recovery_parent_receipt"}
    output, compilation = compile_wire(files, edit)
    body = {
        "id": secrets.token_hex(16),
        "target": source["target"],
        "identity": source["identity"],
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": source["identity"]["object-name"],
        "new_name": source["identity"]["object-name"],
        "connector_config": source["connector_config"],
        "change_kind": "wire-source",
        "operation_profile": TRANSFER_PROFILE,
        "review_capture_id": request["capture_id"],
        "backup_id": request["capture_id"],
        "wire_edit": edit,
        "compilation": compilation,
        "wire_guard": compilation["wire_guard"],
        "payload_sha256": sha(output),
        "native_payload_sha256": compilation["compiled_native_sha256"],
        "recovery_origin": report["origin"],
        "recovery_origin_sha256": report["origin_sha256"],
    }
    if change:
        change(body)
    intent = storage.intent(body)
    storage.finish(
        intent["id"],
        {
            "intent_sha256": intent["evidence_sha256"],
            "status": "unknown" if possible else "not_sent",
            "may_have_applied": possible,
        },
    )
    return intent, request["receipt_id"]


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("possible", [False, True])
async def test_recorded_wire_origin_keeps_zero_index_tuples_and_original_outcome(
    application, monkeypatch, index, possible
):
    intent, parent = recovery_record(application, index=index, possible=possible)
    storage = application.state.native_applications.storage
    storage.resolve(intent["id"], {"status": "verified", "may_have_applied": not possible})
    before = storage.receipt(intent["id"])

    def forbidden(*args):
        pytest.fail("Ledger revalidated a parent or backup")

    monkeypatch.setattr(storage, "load", forbidden)
    monkeypatch.setattr(storage, "verified_readback", forbidden)
    report = await query(application, source="native", text=intent["id"])
    assert not report["errors"] and len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["native_change_kind"] == "wire-source" and row["object"] == REF
    assert row["native_wire_index"] == index
    assert row["dispatch"] == ("possible" if possible else "not entered")
    assert row["readback"] == "verified" and not row["pending"]
    origin = row["native_recovery"]
    assert origin["state"] == "recorded" and origin["datatype"] == "Wire"
    assert origin["wire_index"] == index
    assert origin["before_source_ref"] == (B if index == 0 else A)
    assert origin["after_source_ref"] == (A if index == 0 else B)
    assert origin["before_tuple"] == intent["compilation"]["wire_edit"]["old"]
    assert origin["after_tuple"] == intent["compilation"]["wire_edit"]["new"]
    assert origin["parent_receipt_id"] == parent
    assert "does not revalidate" in origin["scope"] and report["field_requests"] == 0
    assert storage.receipt(intent["id"]) == before


async def test_verified_readback_history_is_recorded_without_rewriting_dispatch(application):
    intent, _ = recovery_record(application, parent_outcome="unknown")
    row = (await query(application, source="native", text=intent["id"]))["rows"][0]
    assert row["native_recovery"]["verified_proof"]["kind"] == "readback-event"
    assert (
        application.state.native_applications.storage.receipt(intent["id"])["result"]["status"]
        == "unknown"
    )
    assert row["dispatch"] == "possible"


@pytest.mark.parametrize(
    "change",
    [
        "index-bool",
        "tuple-bool",
        "class",
        "port",
        "source",
        "target",
        "child-index",
        "child-tuple-bool",
        "seal",
        "capture",
        "self-parent",
    ],
)
async def test_invalid_wire_origin_does_not_hide_original_receipt(application, change):
    def mutate(body):
        origin = body["recovery_origin"]
        if change == "index-bool":
            origin["wire_index"] = False
        elif change == "tuple-bool":
            origin["previous_tuple"][0] = False
        elif change == "class":
            origin["class_id"] = 530
        elif change == "port":
            origin["previous_tuple"][1] = 86
        elif change == "source":
            origin["previous_source_ref"] = "other/source"
        elif change == "target":
            origin["target_ref"] = "other/target"
        elif change == "child-index":
            body["compilation"]["wire_edit"]["wire_index"] = False
        elif change == "child-tuple-bool":
            body["compilation"]["wire_edit"]["new"][0] = False
        elif change == "capture":
            origin["current_capture_id"] = "0" * 32
        elif change == "self-parent":
            origin["parent_receipt_id"] = body["id"]
        body["recovery_origin_sha256"] = "0" * 64 if change == "seal" else seal(origin)

    intent, _ = recovery_record(application, change=mutate)
    storage = application.state.native_applications.storage
    before = storage.receipt(intent["id"])
    report = await query(application, source="native", text=intent["id"])
    assert not report["errors"] and len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["native_recovery"]["state"] == "unavailable"
    assert row["object"] == REF and row["dispatch"] == "possible"
    assert storage.receipt(intent["id"]) == before and report["field_requests"] == 0
