"""Recorded previous-number metadata is local evidence rather than allocation authority."""

import copy
import secrets

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import seal
from bms_tool.native_applications import NativeApplications
from bms_tool.native_ledger_details import recovery_lineage
from fastapi.testclient import TestClient

from .test_native_instance_recovery import setup


def child(path):
    storage, service, request, _, _, files = setup(path)
    report = service.prepare(request)
    _, compilation = NativeApplications.compile(files, 5136)
    source, _ = storage.load(request["capture_id"])
    body = {
        "id": secrets.token_hex(16),
        "change_kind": "instance",
        "old_instance": 5336,
        "new_instance": 5136,
        "old_name": "Authored controller",
        "new_name": "Authored controller",
        "target": source["target"],
        "identity": source["identity"],
        "allocation_confirmed": True,
        "name_change_confirmed": False,
        "application_transfer_confirmed": True,
        "review_capture_id": request["capture_id"],
        "backup_id": secrets.token_hex(16),
        "compilation": compilation,
        "recovery_origin": report["origin"],
        "recovery_origin_sha256": report["origin_sha256"],
    }
    intent = storage.intent(body)
    storage.finish(
        body["id"],
        {
            "intent_sha256": intent["evidence_sha256"],
            "status": "verified",
            "may_have_applied": True,
        },
    )
    return storage, intent


def test_local_ledger_projects_actual_number_patches_without_source_or_parent_proof_loads(
    tmp_path, monkeypatch
):
    storage, body = child(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("Recorded lineage must not load source files or verification history.")

    monkeypatch.setattr(type(storage), "load", forbidden)
    monkeypatch.setattr(type(storage), "verified_readback", forbidden)
    result = recovery_lineage(body, "instance", {})
    assert result["state"] == "recorded" and result["datatype"] == "ObjectIdentifier"
    assert result["before_instance"] == 5336 and result["after_instance"] == 5136
    assert result["unchanged_name"] == "Authored controller"
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post("/api/changes/query", headers=headers, json={"source": "native"})
        assert response.status_code == 200, response.text
        report = response.json()
        row = next(row for row in report["rows"] if row["id"] == body["id"])
        assert row["native_recovery"] == result
        assert report["read_only"] and report["field_requests"] == 0
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize(
    "change",
    [
        "seal",
        "number",
        "boolean-number",
        "name",
        "capture",
        "root",
        "profile",
        "allocation",
        "self-parent",
        "old-outcome",
        "property-float",
        "extra",
        "directory",
        "archive",
        "patch-value",
        "patch-location",
        "patch-offset",
        "patch-count",
        "alias-count",
    ],
)
def test_inconsistent_instance_provenance_is_unavailable_and_original_evidence_remains(
    tmp_path, change
):
    storage, body = child(tmp_path)
    altered = copy.deepcopy(body)
    origin = altered["recovery_origin"]
    edit = altered["compilation"]["identity_edit"]
    if change == "seal":
        altered["recovery_origin_sha256"] = "0" * 64
    elif change == "number":
        altered["new_instance"] = 5137
    elif change == "boolean-number":
        origin["previous_instance"] = True
    elif change == "name":
        altered["new_name"] = "Different name"
    elif change == "capture":
        altered["review_capture_id"] = "0" * 32
    elif change == "root":
        origin["root_ref"] = "another-root"
    elif change == "profile":
        origin["profile"] = "unknown/1"
    elif change == "allocation":
        altered["allocation_confirmed"] = 1
    elif change == "self-parent":
        origin["parent_receipt_id"] = body["id"]
    elif change == "old-outcome":
        origin["current_instance"] = origin["previous_instance"]
    elif change == "property-float":
        origin["property"] = 75.0
    elif change == "extra":
        origin["number_reserved"] = True
    elif change == "directory":
        altered["compilation"]["parameters"]["static_sha256"] = "0" * 64
    elif change == "archive":
        altered["compilation"]["parameters"]["source_sha256"] = "0" * 64
    elif change == "patch-value":
        edit["edits"][1]["after"] = "02001411"
    elif change == "patch-location":
        edit["edits"][0]["location"] = "guessed-header"
    elif change == "patch-offset":
        edit["edits"][0]["native_byte_offset"] = True
    elif change == "patch-count":
        edit["edits"].pop()
    else:
        origin["normalized_root_selectors"] = True
    if change != "seal":
        altered["recovery_origin_sha256"] = seal(origin)
    assert recovery_lineage(altered, "instance", {})["state"] == "unavailable"
    assert storage.receipt(body["id"])["intent"] == body


def test_ordinary_instance_receipts_keep_their_original_metadata_shape(tmp_path):
    _, body = child(tmp_path)
    del body["recovery_origin"]
    del body["recovery_origin_sha256"]
    assert recovery_lineage(body, "instance", {}) is None
