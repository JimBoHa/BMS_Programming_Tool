"""Recorded point names never substitute for live names or source revalidation."""

import copy
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_point_name_ledger import SCOPE, point_name_reference
from bms_tool.native_point_names import PROFILE, compile_point_name
from fastapi.testclient import TestClient

from .test_change_ledger import native, query
from .test_native_applications import native_link
from .test_native_point_names import apply_args, edit_for, name_review, point_files


def authored_body():
    files = point_files()
    edit = edit_for(files)
    output, compilation = compile_point_name(files, edit)
    return {
        "change_kind": "point-name",
        "operation_profile": PROFILE,
        "point_name_edit": edit,
        "compilation": compilation,
        "native_payload_sha256": sha(MoiIdentity(output).data),
        "payload_sha256": sha(output),
        "old_instance": 5136,
        "new_instance": 5136,
        "point_name_confirmed": True,
    }


async def seed_point_name_record(directory):
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(directory, patch)) as generator:
            link = await anext(generator)
            _, plan = await name_review(link)
            result = await link[3].apply_point_name(**apply_args(plan))
            assert result["result"]["status"] == "verified", result
            return result


def test_recorded_projection_is_copied_and_does_not_change_proposal():
    body = authored_body()
    before = copy.deepcopy(body)
    info = point_name_reference(body)
    assert info["object"] == body["point_name_edit"]["object_id"]
    meta = info["native_point_name"]
    assert meta["state"] == "recorded" and meta["profile"] == PROFILE and meta["scope"] == SCOPE
    assert meta["before"] == body["compilation"]["selected_edit"]["before"]
    assert meta["after"] == body["point_name_edit"]["new_name"]
    assert meta["name_confirmation_recorded"] is True
    meta["after"] = "changed"
    assert body == before


@pytest.mark.parametrize(
    "case",
    [
        "profile",
        "compilation_profile",
        "edit",
        "extra_edit",
        "object",
        "reference",
        "before",
        "after",
        "encoding",
        "changed",
        "preserved",
        "payload",
        "record_count",
        "root_identity",
        "before_limit",
    ],
)
def test_inconsistent_metadata_withholds_recorded_values_and_tool_binding(case):
    body = authored_body()
    report = body["compilation"]
    selected = report["selected_edit"]
    if case == "profile":
        body["operation_profile"] = "future/2"
    elif case == "compilation_profile":
        report["profile"] = "future/2"
    elif case == "edit":
        body["point_name_edit"]["new_name"] = "Another proposal"
    elif case == "extra_edit":
        body["point_name_edit"]["token"] = "forbidden"
    elif case == "object":
        selected["object_id"] = "analog-input,99"
    elif case == "reference":
        selected["record_ref"] = "controller/other"
    elif case == "before":
        selected["before"] = None
    elif case == "after":
        selected["after"] = "Another proposal"
    elif case == "encoding":
        selected["character_encoding"] = True
    elif case == "changed":
        selected["changed"] = False
    elif case == "preserved":
        report["other_merged_bytes_preserved"] = False
    elif case == "payload":
        body["native_payload_sha256"] = "f" * 64
    elif case == "record_count":
        report["native_record_count"] = True
    elif case == "root_identity":
        body["new_instance"] += 1
    elif case == "before_limit":
        selected["before"] = "x" * 4097
    assert point_name_reference(body)["native_point_name"]["state"] == "unavailable"


async def test_real_transfer_receipt_restarts_as_read_only_searchable_metadata(
    tmp_path, monkeypatch
):
    original = await seed_point_name_record(tmp_path)
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Ledger attempted a field operation or reopened an original backup")

    for method in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, method, forbidden)
    storage = app.state.native_applications.storage
    monkeypatch.setattr(storage, "load", forbidden)
    report = await query(app, source="native")
    row = next(r for r in report["rows"] if r["id"] == original["intent"]["id"])
    assert (
        row["label"] == "Native point-name transfer" and row["native_change_kind"] == "point-name"
    )
    assert row["object"] == original["intent"]["point_name_edit"]["object_id"]
    assert row["native_point_name"]["after"] == "Changed input" and row["state"] == "verified"
    assert report["field_requests"] == 0 and report["read_only"]
    assert (await query(app, source="native", text="Changed input"))["rows"][0]["id"] == row["id"]
    assert storage.receipt(row["id"]) == original
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post("/api/changes/query", headers=headers, json={"source": "native"})
        assert response.status_code == 200 and response.json()["field_requests"] == 0
        retained = client.get("/api/bacnet/controller/native-application/receipts/" + row["id"])
        assert retained.status_code == 200 and retained.json() == original


async def test_malformed_and_future_point_name_records_remain_readable_without_metadata(tmp_path):
    app = create_app(tmp_path)
    first = native(app, **authored_body())
    bad = authored_body()
    bad["operation_profile"] = "future/2"
    second = native(app, 2, **bad)
    report = await query(app, source="native")
    rows = {r["id"]: r for r in report["rows"]}
    assert rows[first["id"]]["native_point_name"]["state"] == "recorded"
    assert rows[second["id"]]["native_point_name"]["state"] == "unavailable"
    assert app.state.native_applications.storage.receipt(second["id"])["intent"] == second
