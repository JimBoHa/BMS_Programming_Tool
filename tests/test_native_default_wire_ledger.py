"""Recorded combined edits remain bounded local references, without field authority."""

import copy
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_default_wire_ledger import combined_reference
from bms_tool.native_default_wire_transfer import PROFILE, compile_combined
from fastapi.testclient import TestClient

from .test_change_ledger import query
from .test_moi_wire_sources import REF, B, C
from .test_native_applications import native_link
from .test_native_default_wire import proposal, setup
from .test_native_default_wire_transfer import applying, combined_files, review


def authored_body(tmp_path):
    files = combined_files()
    _, service, snapshot = setup(tmp_path, files)
    edit = proposal(service, snapshot, value="-0")
    output, compilation = compile_combined(files, edit)
    return {
        "change_kind": "default-wire",
        "operation_profile": PROFILE,
        "combined_edit": edit,
        "combined_guard": compilation["combined_guard"],
        "compilation": compilation,
        "payload_sha256": sha(output),
        "native_payload_sha256": sha(MoiIdentity(output).data),
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": "Authored native wire controller",
        "new_name": "Authored native wire controller",
        "default_change_confirmed": True,
        "wire_change_confirmed": True,
        "application_transfer_confirmed": True,
    }


def test_recorded_projection_preserves_negative_zero_and_original_proposal(tmp_path):
    body = authored_body(tmp_path)
    before = copy.deepcopy(body)
    projected = combined_reference(body)
    assert projected["object"] == C
    data = projected["native_default_wire"]
    assert data["state"] == "recorded" and data["profile"] == PROFILE
    assert data["before_bits"] == "40600000" and data["after_bits"] == "80000000"
    assert data["diagram_ref"] == REF and data["source_ref"] == B
    assert data["target_ref"] == C and data["transfer_confirmation_recorded"] is True
    assert data["field_authority"] is False and "no transfer authority" in data["scope"]
    data["new"][0] = 99
    data["old"][0] = 99
    assert body == before


@pytest.mark.parametrize(
    "case",
    [
        "profile",
        "edit-extra",
        "edit",
        "guard",
        "compile-profile",
        "guard-binding",
        "hash",
        "real-bits",
        "wire-source",
        "wire-tuple",
        "tuple-bool",
        "real-class",
        "real-property",
        "nan",
        "identity",
        "rename",
        "confirmation",
        "field-authority",
        "control-ref",
        "prior-profile",
        "recovery-origin",
    ],
)
def test_inconsistent_record_withholds_combined_reference(tmp_path, case):
    body = authored_body(tmp_path)
    compilation = body["compilation"]
    if case == "profile":
        body["operation_profile"] = "future/2"
    elif case == "edit-extra":
        body["combined_edit"]["token"] = "forbidden"
    elif case == "edit":
        body["combined_edit"]["value_text"] = "99"
    elif case == "guard":
        body["combined_guard"]["record_ref"] = B
    elif case == "compile-profile":
        compilation["profile"] = "future/2"
    elif case == "guard-binding":
        body["combined_guard"] = copy.deepcopy(body["combined_guard"])
        body["combined_guard"]["wire_guard"]["configuration_sha256"] = "0" * 64
    elif case == "hash":
        body["native_payload_sha256"] = "0" * 64
    elif case == "real-bits":
        compilation["selected_default"]["after_bits"] = "00000000"
    elif case == "wire-source":
        compilation["selected_wire"]["source_ref"] = C
    elif case == "wire-tuple":
        compilation["selected_wire"]["new"][3] += 1
    elif case == "tuple-bool":
        compilation["selected_wire"]["new"][0] = True
    elif case == "real-class":
        compilation["selected_default"]["class_id"] = 530
    elif case == "real-property":
        compilation["selected_default"]["property"] = 85
    elif case == "nan":
        body["combined_guard"]["prior_bits"] = "7fc00000"
        compilation["selected_default"]["before_bits"] = "7fc00000"
    elif case == "identity":
        body["new_instance"] += 1
    elif case == "rename":
        body["new_name"] = "Another name"
    elif case == "confirmation":
        body["wire_change_confirmed"] = 1
    elif case == "field-authority":
        compilation["field_transfer_enabled"] = True
    elif case == "control-ref":
        compilation["selected_wire"]["target_ref"] = "bad\nreference"
    elif case == "prior-profile":
        body["default_edit"] = {}
    else:
        body["recovery_origin"] = {}
    assert combined_reference(body)["native_default_wire"]["state"] == "unavailable"


async def test_actual_receipt_is_searchable_local_history_without_backup_or_field_access(
    tmp_path, monkeypatch
):
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(tmp_path, patch)) as generator:
            link = await anext(generator)
            _, plan = await review(link)
            receipt = await link[3].apply_default_wire(**applying(plan))
            assert receipt["result"]["status"] == "verified", receipt
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Recorded combined evidence attempted a field request or source reload")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    storage = app.state.native_applications.storage
    monkeypatch.setattr(storage, "load", forbidden)
    report = await query(app, source="native", text=B)
    row = next(r for r in report["rows"] if r["id"] == receipt["intent"]["id"])
    assert row["label"] == "Native Real default and connection transfer"
    assert row["native_change_kind"] == "default-wire" and row["object"] == C
    assert row["native_default_wire"]["target_ref"] == C
    assert row["state"] == "verified" and report["field_requests"] == 0
    assert report["read_only"] and "native_recovery" not in row
    assert storage.receipt(row["id"]) == receipt
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post("/api/changes/query", json={"source": "native"}, headers=headers)
        assert response.status_code == 200 and response.json()["field_requests"] == 0
