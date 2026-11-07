"""Recorded batch history stays local, bounded and without field authority."""

import copy
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_default_batch_ledger import batch_reference
from bms_tool.native_default_batch_transfer import PROFILE

from .test_change_ledger import query
from .test_native_applications import native_link
from .test_native_default_batch_transfer import applying, local_plan, review_native


def authored_body(tmp_path):
    _, edit, output, compilation = local_plan(tmp_path)
    return {
        "change_kind": "default-batch",
        "operation_profile": PROFILE,
        "batch_edit": edit,
        "batch_guard": compilation["batch_guard"],
        "compilation": compilation,
        "payload_sha256": sha(output),
        "native_payload_sha256": sha(MoiIdentity(output).data),
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": "Authored batch",
        "new_name": "Authored batch",
        "defaults_change_confirmed": True,
        "application_transfer_confirmed": True,
    }


def test_projection_keeps_all_typed_encodings_without_mutating_original(tmp_path):
    body = authored_body(tmp_path)
    original = copy.deepcopy(body)
    projected = batch_reference(body)
    assert projected["object"] == "4 typed defaults"
    row = projected["native_default_batch"]
    assert row["state"] == "recorded" and not row["field_authority"]
    assert len(row["selected"]) == 4 and "no transfer authority" in row["scope"]
    assert row["selected"][1]["after_encoding_hex"] == "44800000002f"
    row["selected"][0]["record_ref"] = "mutated"
    assert body == original


@pytest.mark.parametrize(
    "fault",
    [
        "profile",
        "edit",
        "guard",
        "hash",
        "bits",
        "confirmation",
        "authority",
        "identity",
        "foreign",
        "count",
        "order",
        "enum",
    ],
)
def test_inconsistent_history_withholds_metadata(tmp_path, fault):
    body = authored_body(tmp_path)
    if fault == "profile":
        body["operation_profile"] = "future/2"
    elif fault == "edit":
        body["batch_edit"]["changes"][0]["value_text"] = "99"
    elif fault == "guard":
        body["batch_guard"] = None
    elif fault == "hash":
        body["native_payload_sha256"] = "0" * 64
    elif fault == "bits":
        body["compilation"]["selected"][0]["before_encoding_hex"] = "44000000002f"
    elif fault == "confirmation":
        body["defaults_change_confirmed"] = False
    elif fault == "authority":
        body["compilation"]["field_transfer_enabled"] = True
    elif fault == "identity":
        body["new_instance"] += 1
    elif fault == "foreign":
        body["recovery_origin"] = {}
    elif fault == "count":
        body["compilation"]["changed_count"] = True
    elif fault == "order":
        body["compilation"]["selected"].reverse()
    elif fault == "enum":
        body["compilation"]["selected"][-1]["after_encoding_hex"] = "94000100002f"
    assert batch_reference(body)["native_default_batch"]["state"] == "unavailable"


async def test_actual_batch_history_queries_no_source_or_field(tmp_path, monkeypatch):
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(tmp_path, patch)) as generator:
            link = await anext(generator)
            _, plan = await review_native(link)
            receipt = await link[3].apply_default_batch(**applying(plan))
            assert receipt["result"]["status"] == "verified", receipt
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Recorded history attempted source or field access")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "load", forbidden)
    report = await query(app, source="native", text="typed")
    row = next(r for r in report["rows"] if r["id"] == receipt["intent"]["id"])
    assert (
        row["native_change_kind"] == "default-batch"
        and row["label"] == "Native typed default batch transfer"
    )
    assert row["native_default_batch"]["state"] == "recorded" and "native_recovery" not in row
    assert report["field_requests"] == 0 and report["read_only"]
