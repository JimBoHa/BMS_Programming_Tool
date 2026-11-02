"""Recorded origins remain readable without parent resolution or native files."""

import copy
import secrets
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.native_point_name_ledger import point_name_reference
from bms_tool.native_point_name_recovery_ledger import PROFILE, SCOPE, point_name_recovery_reference
from bms_tool.native_point_names import compile_point_name
from fastapi.testclient import TestClient

from .test_change_ledger import native, query
from .test_native_applications import native_link
from .test_native_point_name_recovery import recovery_review, setup
from .test_native_point_names import apply_args


def authored_body(path):
    identity = {
        "device": "device,5136",
        "object-name": "Authored controller",
        "model-name": "UNLISTED-MODEL",
        "vendor-identifier": 5,
    }
    storage, service, request, _, files = setup(path, identity=identity)
    report = service.prepare(request)
    edit = {
        k: report["proposal"][k] for k in ("object_id", "record_ref", "encoded_sha256", "new_name")
    }
    output, compilation = compile_point_name(files, edit)
    return {
        "id": secrets.token_hex(16),
        "profile": "native-application-transfer/1",
        "target": storage.load(request["capture_id"])[0]["target"],
        "identity": identity,
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": "Authored controller",
        "new_name": "Authored controller",
        "change_kind": "point-name",
        "operation_profile": "native-point-name-transfer/1",
        "point_name_confirmed": True,
        "application_transfer_confirmed": True,
        "backup_id": secrets.token_hex(16),
        "review_capture_id": request["capture_id"],
        "point_name_edit": edit,
        "compilation": compilation,
        "payload_sha256": sha(output),
        "native_payload_sha256": sha(MoiIdentity(output).data),
        "recovery_origin": report["origin"],
        "recovery_origin_sha256": report["origin_sha256"],
    }


def projected(body):
    return point_name_recovery_reference(body, point_name_reference(body).get("native_point_name"))


def test_recorded_projection_is_isolated_and_contains_no_field_authority(tmp_path):
    body = authored_body(tmp_path)
    before = copy.deepcopy(body)
    value = projected(body)["native_point_name_recovery"]
    assert value["state"] == "recorded" and value["profile"] == PROFILE and value["scope"] == SCOPE
    assert value["before"] == "Changed input" and value["after"] == "Authored input"
    assert value["parent_receipt_id"] == body["recovery_origin"]["parent_receipt_id"]
    assert value["object_id"] == "analog-input,101" and value["instance"] == 5136
    value["verified_proof"]["kind"] = "changed"
    assert body == before and not {"token", "can_apply", "review_sha256"} & set(value)


@pytest.mark.parametrize(
    "case",
    [
        "profile",
        "origin_profile",
        "origin_extra",
        "parent_self",
        "backup_reused",
        "capture_reused",
        "current_capture",
        "current_snapshot",
        "current_name_hash",
        "object",
        "reference",
        "encoding_bool",
        "encoding_unknown",
        "class_bool",
        "class_limit",
        "property",
        "proof_time",
        "proof_kind",
        "proof_digest",
        "before",
        "after",
        "proposal",
        "origin_seal",
        "child_profile",
        "child_encoding",
        "child_changed",
        "child_instance",
        "child_identity",
        "child_root_name",
        "child_confirm",
        "transfer_confirm",
        "missing_origin",
        "missing_hash",
        "missing_target",
        "target_device",
        "future_transfer",
    ],
)
def test_inconsistent_recorded_bindings_withhold_metadata(tmp_path, case):
    body = authored_body(tmp_path)
    origin = body["recovery_origin"]
    if case == "profile":
        body["profile"] = "future/2"
    elif case == "origin_profile":
        origin["profile"] = "future/2"
    elif case == "origin_extra":
        origin["token"] = "not-authority"
    elif case == "parent_self":
        origin["parent_receipt_id"] = body["id"]
    elif case == "backup_reused":
        body["backup_id"] = origin["original_backup_id"]
    elif case == "capture_reused":
        origin["original_backup_id"] = origin["current_capture_id"]
    elif case == "current_capture":
        origin["current_capture_id"] = "f" * 32
    elif case == "current_snapshot":
        origin["current_snapshot_sha256"] = "bad"
    elif case == "current_name_hash":
        origin["current_name_sha256"] = "f" * 64
    elif case == "object":
        origin["object_id"] = "analog-input,102"
    elif case == "reference":
        origin["record_ref"] = "controller/other"
    elif case == "encoding_bool":
        origin["character_encoding"] = False
    elif case == "encoding_unknown":
        origin["character_encoding"] = 2
    elif case == "class_bool":
        origin["native_class"] = True
    elif case == "class_limit":
        origin["native_class"] = 65536
    elif case == "property":
        origin["property"] = 2391
    elif case == "proof_time":
        origin["verified_proof"]["time"] = "2026-11-02T00:00:00"
    elif case == "proof_kind":
        origin["verified_proof"]["kind"] = "current-live-value"
    elif case == "proof_digest":
        origin["verified_proof"]["sha256"] = "bad"
    elif case == "before":
        origin["current_name"] = "Other name"
    elif case == "after":
        origin["previous_name"] = "Other name"
    elif case == "proposal":
        origin["proposal_name"] = "Other name"
    elif case == "child_profile":
        body["compilation"]["profile"] = "future/2"
    elif case == "child_encoding":
        body["compilation"]["selected_edit"]["character_encoding"] = True
    elif case == "child_changed":
        body["compilation"]["selected_edit"]["changed"] = False
    elif case == "child_instance":
        body["new_instance"] = 5137
    elif case == "child_identity":
        body["identity"]["device"] = "device,5137"
    elif case == "child_root_name":
        body["new_name"] = "changed controller"
    elif case == "child_confirm":
        body["point_name_confirmed"] = False
    elif case == "transfer_confirm":
        body["application_transfer_confirmed"] = False
    elif case == "missing_origin":
        body.pop("recovery_origin")
    elif case == "missing_hash":
        body.pop("recovery_origin_sha256")
    elif case == "missing_target":
        body.pop("target")
    elif case == "target_device":
        body["target"]["device"] = "device,5137"
    elif case == "future_transfer":
        body["operation_profile"] = "future/2"
    if case != "missing_hash":
        body["recovery_origin_sha256"] = "f" * 64 if case == "origin_seal" else seal(origin)
    before = copy.deepcopy(body)
    assert projected(body)["native_point_name_recovery"]["state"] == "unavailable"
    assert body == before


def test_ordinary_point_receipts_keep_their_existing_projection(tmp_path):
    body = authored_body(tmp_path)
    body.pop("recovery_origin")
    body.pop("recovery_origin_sha256")
    assert projected(body) == {}


async def seed_recovery_record(directory):
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(directory, patch)) as generator:
            link = await anext(generator)
            _, service, _, args = await recovery_review(link)
            plan = await service.preview_point_name(**args)
            result = await service.apply_point_name(**apply_args(plan))
            assert result["result"]["status"] == "verified", result
            return result


async def test_actual_recovery_receipt_projects_after_restart_with_original_readers_forbidden(
    tmp_path, monkeypatch
):
    original = await seed_recovery_record(tmp_path)
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    parent = original["intent"]["recovery_origin"]["parent_receipt_id"]
    parent_before = storage.receipt(parent)

    def forbidden(*args, **kwargs):
        pytest.fail("Recorded lineage attempted field or original/parent revalidation")

    for method in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, method, forbidden)
    monkeypatch.setattr(storage, "load", forbidden)
    monkeypatch.setattr(storage, "verified_readback", forbidden)
    monkeypatch.setattr(app.state.native_applications.point_name_recovery, "prepare", forbidden)
    report = await query(app, source="native", text=original["intent"]["id"])
    (row,) = report["rows"]
    assert row["native_point_name_recovery"]["state"] == "recorded" and "native_recovery" not in row
    assert row["native_point_name_recovery"]["parent_receipt_id"] == parent
    assert row["state"] == "verified" and report["field_requests"] == 0 and report["read_only"]
    found = await query(app, source="native", text=parent)
    assert {r["id"] for r in found["rows"]} == {parent, original["intent"]["id"]}
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post("/api/changes/query", headers=headers, json={"source": "native"})
        assert response.status_code == 200 and response.json()["field_requests"] == 0
        assert (
            client.get(
                "/api/bacnet/controller/native-application/receipts/" + original["intent"]["id"]
            ).json()
            == original
        )
    assert storage.receipt(parent) == parent_before


async def test_recorded_parent_and_backup_references_need_not_resolve_for_metadata(
    tmp_path, monkeypatch
):
    body = authored_body(tmp_path / "authoring")
    app = create_app(tmp_path / "recorded-only")
    intent = native(app, **body)

    def forbidden(*args, **kwargs):
        pytest.fail("Recorded-only projection tried to resolve a reference")

    monkeypatch.setattr(app.state.native_applications.storage, "load", forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "verified_readback", forbidden)
    (row,) = (await query(app, source="native", text=body["recovery_origin"]["parent_receipt_id"]))[
        "rows"
    ]
    assert row["id"] == intent["id"] and row["native_point_name_recovery"]["state"] == "recorded"
    assert not app.state.native_applications.storage.captures()
