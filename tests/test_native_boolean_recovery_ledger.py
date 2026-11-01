"""Boolean lineage is recorded local evidence, with strict values and literal tags."""

import secrets

import pytest
from bms_tool.moi_identity import seal, sha
from bms_tool.native_boolean_transfer import PROFILE as TRANSFER_PROFILE
from bms_tool.native_boolean_transfer import compile_boolean_default

from .test_change_ledger import application as application  # noqa: F401
from .test_change_ledger import query
from .test_native_boolean_recovery import setup


def recovery_record(app, change=None, *, possible=True, parent_outcome="verified"):
    storage, service, request, _, files = setup(app.state.store.directory, outcome=parent_outcome)
    if parent_outcome != "verified":
        storage.resolve(request["receipt_id"], {"status": "verified"})
    report = service.prepare(request)
    source = storage.load(request["capture_id"])[0]
    edit = {key: report["proposal"][key] for key in ("record_ref", "encoded_sha256", "value")}
    output, compilation = compile_boolean_default(files, edit)
    body = {
        "id": secrets.token_hex(16),
        "target": source["target"],
        "identity": source["identity"],
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": source["identity"]["object-name"],
        "new_name": source["identity"]["object-name"],
        "connector_config": source["connector_config"],
        "change_kind": "boolean-default",
        "operation_profile": TRANSFER_PROFILE,
        "review_capture_id": request["capture_id"],
        "backup_id": request["capture_id"],
        "default_edit": edit,
        "compilation": compilation,
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


@pytest.mark.parametrize("possible", [False, True])
@pytest.mark.parametrize("parent_outcome", ["verified", "unknown"])
async def test_recorded_boolean_origin_keeps_exact_values_and_original_attempt_facts(
    application, monkeypatch, possible, parent_outcome
):
    intent, parent = recovery_record(application, possible=possible, parent_outcome=parent_outcome)
    storage = application.state.native_applications.storage
    storage.resolve(intent["id"], {"status": "verified", "may_have_applied": not possible})
    before = storage.receipt(intent["id"])

    def forbidden(*args):
        pytest.fail("Ledger attempted parent/backup revalidation")

    monkeypatch.setattr(storage, "load", forbidden)
    monkeypatch.setattr(storage, "verified_readback", forbidden)
    report = await query(application, source="native", text=intent["id"])
    assert not report["errors"] and len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["native_change_kind"] == "boolean-default"
    assert row["object"] == "controller/boolean-20"
    assert row["dispatch"] == ("possible" if possible else "not entered")
    assert row["readback"] == "verified" and not row["pending"]
    origin = row["native_recovery"]
    assert origin["state"] == "recorded" and origin["datatype"] == "Boolean"
    assert origin["before_value"] is False and origin["after_value"] is True
    assert origin["before_tag"] == "10" and origin["after_tag"] == "11"
    assert origin["parent_receipt_id"] == parent
    assert origin["verified_proof"] == intent["recovery_origin"]["verified_proof"]
    assert "does not revalidate" in origin["scope"] and report["field_requests"] == 0
    assert storage.receipt(intent["id"]) == before


def malformed(body, change):
    origin = body["recovery_origin"]
    if change == "previous-1":
        origin["previous_effective_value"] = 1
    elif change == "current-0":
        origin["current_effective_value"] = 0
    elif change == "proposal-1":
        origin["proposal_value"] = 1
    elif change == "class":
        origin["class_id"] = 526
    elif change == "tag":
        origin["previous_tag"] = "10"
    elif change == "before-0":
        body["compilation"]["selected_edit"]["before_value"] = 0
    elif change == "after-1":
        body["compilation"]["selected_edit"]["after_value"] = 1
    elif change == "edit-1":
        body["default_edit"]["value"] = 1
    elif change == "edit-other":
        body["default_edit"]["value"] = False
    elif change == "capture":
        body["review_capture_id"] = "0" * 32
    elif change == "profile":
        origin["profile"] = "future"
    else:
        raise AssertionError(change)
    body["recovery_origin_sha256"] = seal(origin)


@pytest.mark.parametrize(
    "change",
    [
        "previous-1",
        "current-0",
        "proposal-1",
        "class",
        "tag",
        "before-0",
        "after-1",
        "edit-1",
        "edit-other",
        "capture",
        "profile",
    ],
)
async def test_malformed_boolean_origin_never_becomes_qualified_recovery_lineage(
    application, change
):
    intent, _ = recovery_record(application, lambda body: malformed(body, change))
    before = application.state.native_applications.storage.receipt(intent["id"])
    report = await query(application, source="native", text=intent["id"])
    assert not report["errors"] and len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["native_recovery"]["state"] == "unavailable"
    assert "parent_receipt_id" not in row["native_recovery"]
    assert row["pending"] and row["dispatch"] == "possible"
    assert application.state.native_applications.storage.receipt(intent["id"]) == before
