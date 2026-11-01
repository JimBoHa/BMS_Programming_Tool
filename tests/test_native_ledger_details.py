"""Production native identifiers and recorded recovery lineage stay local and exact."""

import copy
import secrets
import struct

import pytest
from bms_tool.moi_identity import seal, sha
from bms_tool.native_default_transfer import PROFILE as DEFAULT_PROFILE
from bms_tool.native_default_transfer import compile_default

from .test_change_ledger import application as application  # noqa: F401
from .test_change_ledger import native, query
from .test_native_default_recovery import setup


def recovery_record(app, mutate=None, *, possible=True, parent_outcome="verified"):
    storage, service, request, _, files = setup(app.state.store.directory, outcome=parent_outcome)
    if parent_outcome != "verified":
        storage.resolve(request["receipt_id"], {"status": "verified"})
    prepared = service.prepare(request)
    source = storage.load(request["capture_id"])[0]
    edit = {k: prepared["proposal"][k] for k in ("record_ref", "encoded_sha256", "value_text")}
    payload, compilation = compile_default(files, edit)
    body = {
        "id": secrets.token_hex(16),
        "target": source["target"],
        "identity": source["identity"],
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": source["identity"]["object-name"],
        "new_name": source["identity"]["object-name"],
        "connector_config": source["connector_config"],
        "change_kind": "signal-default",
        "operation_profile": DEFAULT_PROFILE,
        "review_capture_id": request["capture_id"],
        "backup_id": request["capture_id"],
        "default_edit": edit,
        "compilation": compilation,
        "payload_sha256": sha(payload),
        "recovery_origin": prepared["origin"],
        "recovery_origin_sha256": prepared["origin_sha256"],
    }
    if mutate:
        mutate(body)
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


@pytest.mark.parametrize("kind", ["signal-default", "boolean-default"])
async def test_actual_native_default_receipts_show_record_ref_and_search_its_tail(
    application, kind
):
    reference = "controller/" + "long-source-" * 14 + "actual-tail"
    intent = native(
        application,
        change_kind=kind,
        new_instance=123,
        default_edit={"record_ref": reference},
    )
    before = application.state.native_applications.storage.receipt(intent["id"])
    report = await query(application, source="native", text="actual-tail")
    assert not report["errors"] and len(report["rows"]) == 1
    assert report["rows"][0]["object"] == reference
    assert report["field_requests"] == 0 and report["read_only"]
    assert application.state.native_applications.storage.receipt(intent["id"]) == before


@pytest.mark.parametrize("possible", [False, True])
@pytest.mark.parametrize("parent_outcome", ["verified", "unknown"])
async def test_recorded_recovery_lineage_preserves_original_dispatch_after_later_readback(
    application, monkeypatch, possible, parent_outcome
):
    intent, parent = recovery_record(application, possible=possible, parent_outcome=parent_outcome)
    storage = application.state.native_applications.storage
    storage.resolve(intent["id"], {"status": "verified", "may_have_applied": not possible})
    before = storage.receipt(intent["id"])

    def forbidden(*args):
        pytest.fail("Ledger recovery metadata attempted backup/history revalidation")

    monkeypatch.setattr(storage, "load", forbidden)
    monkeypatch.setattr(storage, "verified_readback", forbidden)
    report = await query(application, source="native", text=intent["id"])
    assert not report["errors"] and len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["object"] == "controller/signal-10"
    assert row["dispatch"] == ("possible" if possible else "not entered")
    assert row["outcome"] == "verified" and row["readback"] == "verified"
    lineage = row["native_recovery"]
    assert lineage["state"] == "recorded" and lineage["parent_receipt_id"] == parent
    assert lineage["before_bits"] == "80000000" and lineage["after_bits"] == "42280000"
    assert lineage["before_value"] == 0 and lineage["after_value"] == 42
    assert struct.pack(">f", lineage["before_value"]).hex() == "80000000"
    assert lineage["verified_proof"] == intent["recovery_origin"]["verified_proof"]
    assert "does not revalidate" in lineage["scope"]
    assert storage.receipt(intent["id"]) == before
    parent_row = next(
        row
        for row in (await query(application, source="native", text=parent))["rows"]
        if row["id"] == parent
    )
    assert "native_recovery" not in parent_row


def malformed_recovery(body, change):
    origin = body["recovery_origin"]
    if change == "hash":
        body["recovery_origin_sha256"] = "0" * 64
        return
    if change == "missing-origin":
        del body["recovery_origin"]
        return
    if change == "missing-hash":
        del body["recovery_origin_sha256"]
        return
    if change == "profile":
        origin["profile"] = "future-profile"
    elif change == "proof":
        origin["verified_proof"]["kind"] = "invented"
    elif change == "time":
        origin["verified_proof"]["time"] = "2026-01-01T00:00:00"
    elif change == "capture":
        body["review_capture_id"] = "0" * 32
    elif change == "field":
        body["default_edit"]["record_ref"] = "different"
    elif change == "compilation":
        body["compilation"] = None
    elif change == "bits":
        origin["previous_effective_bits"] = "7f800000"
    elif change == "self-parent":
        origin["parent_receipt_id"] = body["id"]
    elif change == "kind":
        body["change_kind"] = "boolean-default"
    elif change == "operation":
        body["operation_profile"] = "unsupported"
    elif change == "selected":
        body["compilation"]["selected_edit"]["after_bits"] = "42240000"
    elif change == "nested-extra":
        origin["unqualified"] = {"nested": "extra"}
    else:
        raise AssertionError(change)
    body["recovery_origin_sha256"] = seal(origin)


@pytest.mark.parametrize(
    "change",
    [
        "hash",
        "missing-origin",
        "missing-hash",
        "profile",
        "proof",
        "time",
        "capture",
        "field",
        "compilation",
        "bits",
        "self-parent",
        "kind",
        "operation",
        "selected",
        "nested-extra",
    ],
)
async def test_malformed_recovery_metadata_keeps_original_receipt_without_inventing_lineage(
    application, change
):
    intent, _ = recovery_record(application, lambda b: malformed_recovery(b, change))
    before = application.state.native_applications.storage.receipt(intent["id"])
    report = await query(application, source="native", text=intent["id"])
    assert not report["errors"] and len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["native_recovery"]["state"] == "unavailable"
    assert "parent_receipt_id" not in row["native_recovery"]
    assert row["pending"] and row["dispatch"] == "possible"
    assert application.state.native_applications.storage.receipt(intent["id"]) == before


@pytest.mark.parametrize(
    "selection,expected,issue",
    [
        ({"ref": "legacy"}, "legacy", False),
        ({"record_ref": "canonical", "ref": "canonical"}, "canonical", False),
        ({"record_ref": "canonical", "ref": "different"}, "", True),
        ({"record_ref": None, "ref": "legacy"}, "", True),
        ({"record_ref": True}, "", True),
        ({"record_ref": "a" * 513}, "", True),
        ({}, "", True),
    ],
)
async def test_canonical_and_legacy_refs_require_unambiguous_recorded_strings(
    application, selection, expected, issue
):
    intent = native(
        application,
        change_kind="signal-default",
        new_instance=123,
        default_edit=copy.deepcopy(selection),
        object_id="unrelated-fallback",
    )
    (row,) = (await query(application, source="native", text=intent["id"]))["rows"]
    assert row["object"] == expected
    assert ("native_reference_issue" in row) is issue


@pytest.mark.parametrize("index", [0, 4095, True, -1, 4096, "0"])
async def test_wire_index_keeps_exact_zero_based_identity_without_coercion(application, index):
    native(
        application,
        change_kind="wire-source",
        new_instance=123,
        wire_edit={"diagram_ref": "controller/actual-diagram", "wire_index": index},
    )
    (row,) = (await query(application, source="native"))["rows"]
    assert row["object"] == "controller/actual-diagram"
    if type(index) is int and 0 <= index <= 4095:
        assert row["native_wire_index"] == index and "native_reference_issue" not in row
    else:
        assert "native_wire_index" not in row and "native_reference_issue" in row
