"""Recorded name-recovery metadata does not load sources or admit a transfer."""

import copy
import secrets

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import seal
from bms_tool.native_applications import NativeApplications
from bms_tool.native_ledger_details import recovery_lineage
from fastapi.testclient import TestClient

from .test_native_name_recovery import setup


def child(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    report = service.prepare(request)
    _, compilation = NativeApplications.compile(files, 5136, "Authored controller")
    backup = storage.load(request["capture_id"])[0]
    body = {
        "id": secrets.token_hex(16),
        "change_kind": "name",
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": "Renamed controller",
        "new_name": "Authored controller",
        "target": backup["target"],
        "identity": backup["identity"],
        "name_change_confirmed": True,
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


def test_recorded_name_lineage_and_local_http_do_not_load_sources(tmp_path, monkeypatch):
    storage, body = child(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("Recorded metadata must not load source files or historical proofs.")

    monkeypatch.setattr(type(storage), "load", forbidden)
    monkeypatch.setattr(type(storage), "verified_readback", forbidden)
    result = recovery_lineage(body, "name", {})
    assert result["state"] == "recorded" and result["datatype"] == "CharacterString"
    assert (
        result["before_value"] == "Renamed controller"
        and result["after_value"] == "Authored controller"
    )
    assert result["instance"] == 5136
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
        "name",
        "instance",
        "boolean-instance",
        "capture",
        "root",
        "profile",
        "confirmation",
        "self-parent",
        "old-outcome",
        "property-float",
        "extra",
    ],
)
def test_inconsistent_recorded_name_origin_stays_unavailable(tmp_path, change):
    storage, body = child(tmp_path)
    altered = copy.deepcopy(body)
    origin = altered["recovery_origin"]
    if change == "seal":
        altered["recovery_origin_sha256"] = "0" * 64
    elif change == "name":
        altered["new_name"] = "Other name"
    elif change == "instance":
        altered["new_instance"] = 5137
    elif change == "boolean-instance":
        altered["old_instance"] = True
    elif change == "capture":
        altered["review_capture_id"] = "0" * 32
    elif change == "root":
        origin["root_ref"] = "another-root"
    elif change == "profile":
        origin["profile"] = "unknown/1"
    elif change == "confirmation":
        altered["name_change_confirmed"] = 1
    elif change == "self-parent":
        origin["parent_receipt_id"] = body["id"]
    elif change == "old-outcome":
        origin["current_name"] = origin["previous_name"]
    elif change == "property-float":
        origin["property"] = 2390.0
    else:
        origin["guessed_live_state"] = True
    if change != "seal":
        altered["recovery_origin_sha256"] = seal(origin)
    assert recovery_lineage(altered, "name", {})["state"] == "unavailable"
    assert storage.receipt(body["id"])["intent"] == body


def test_normal_name_receipts_keep_their_original_lineage_shape(tmp_path):
    _, body = child(tmp_path)
    del body["recovery_origin"]
    del body["recovery_origin_sha256"]
    assert recovery_lineage(body, "name", {}) is None
