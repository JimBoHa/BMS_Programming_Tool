"""Recorded input evidence remains local, attributable and separate from live authority."""

import copy
import json
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_input_ledger import input_reference
from bms_tool.native_inputs import PROFILE, NativeInputCompiler, compile_input
from fastapi.testclient import TestClient

from .test_change_ledger import application as application  # noqa: F401
from .test_change_ledger import native, query
from .test_native_applications import native_link as native_link
from .test_native_input_transfer import apply, install_input_peer, preview
from .test_native_inputs import allocation, config, source


def authored_body():
    edit = allocation()
    output, compilation = compile_input(source(), edit)
    return {
        "change_kind": "input",
        "operation_profile": PROFILE,
        "input_edit": compilation["input_edit"],
        "compilation": compilation,
        "native_payload_sha256": sha(MoiIdentity(output).data),
        "payload_sha256": sha(output),
        "physical_wiring_confirmed": True,
        "old_instance": 5136,
        "new_instance": 5136,
    }


def removal_body():
    files = source()
    allocated, origin = compile_input(files, allocation())
    files = {**files, 3: allocated}
    point = NativeInputCompiler(files).source()["inputs"][0]
    edit = {
        "action": "remove-allocated",
        "object_instance": 3000010,
        "slot": 1,
        "configuration_sha256": point["configuration_sha256"],
        "allocation_receipt": "a" * 32,
    }
    output, compilation = compile_input(files, edit, allocation_origin=origin)
    return {
        **authored_body(),
        "input_edit": compilation["input_edit"],
        "compilation": compilation,
        "allocation_origin": origin,
        "payload_sha256": sha(output),
        "native_payload_sha256": sha(MoiIdentity(output).data),
    }


@pytest.mark.parametrize("case", ["missing", "profile", "slot", "object", "self_reference"])
def test_inconsistent_recorded_removal_origin_grants_no_structured_lineage(case):
    body = removal_body()
    assert input_reference(body)["native_input"]["state"] == "recorded"
    if case == "missing":
        body["allocation_origin"] = None
    elif case == "profile":
        body["allocation_origin"]["profile"] = "other"
    elif case == "slot":
        body["allocation_origin"]["input_edit"]["slot"] = 2
    elif case == "object":
        body["allocation_origin"]["object_id"] = "analog-input,9"
    elif case == "self_reference":
        body["id"] = body["input_edit"]["allocation_receipt"]
    assert input_reference(body)["native_input"]["state"] == "unavailable"


async def actual_records(link):
    peer, service = install_input_peer(link)
    _, plan = await preview(link, allocation(), "ledger-allocation")
    first = await service.apply_input(**apply(plan, "ledger-allocation"))
    assert first["result"]["status"] == "verified", first
    point = NativeInputCompiler(peer.files).source()["inputs"][0]
    edit = {
        "action": "mode",
        "object_instance": 3000010,
        "slot": 1,
        "configuration_sha256": point["configuration_sha256"],
        "configuration": config("resistance"),
    }
    _, plan = await preview(link, edit, "ledger-mode")
    second = await service.apply_input(**apply(plan, "ledger-mode"))
    assert second["result"]["status"] == "verified", second
    point = NativeInputCompiler(peer.files).source()["inputs"][0]
    edit = {
        "action": "remove-allocated",
        "object_instance": 3000010,
        "slot": 1,
        "configuration_sha256": point["configuration_sha256"],
        "allocation_receipt": first["intent"]["id"],
    }
    _, plan = await preview(link, edit, "ledger-removal")
    third = await service.apply_input(**apply(plan, "ledger-removal"))
    assert third["result"]["status"] == "verified", third
    return [first, second, third]


async def seed_input_records(directory):
    # Exercise the same independent UDP fixture in browser seed processes.
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(directory, patch)) as generator:
            return await actual_records(await anext(generator))


async def test_actual_allocate_mode_remove_receipts_survive_restart_with_zero_ledger_traffic(
    native_link,
    tmp_path,
    monkeypatch,
):
    records = await actual_records(native_link)
    peer = native_link[0]
    before_events = copy.deepcopy(peer.events)
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Input ledger attempted field access or backup/parent revalidation")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    storage = app.state.native_applications.storage
    originals = {row["intent"]["id"]: storage.receipt(row["intent"]["id"]) for row in records}
    monkeypatch.setattr(storage, "load", forbidden)
    monkeypatch.setattr(storage, "verified_readback", forbidden)
    report = await query(app, source="native")
    assert not report["errors"] and report["field_requests"] == 0 and report["read_only"]
    found = {row["id"]: row for row in report["rows"]}
    for receipt, action in zip(records, ("allocate", "mode", "remove-allocated"), strict=True):
        row = found[receipt["intent"]["id"]]
        assert row["label"] == "Native input configuration transfer"
        assert row["native_change_kind"] == "input" and row["object"] == "analog-input,3000010"
        info = row["native_input"]
        assert info["state"] == "recorded" and info["action"] == action and info["slot"] == 1
        assert info["record_ref"] == "controller/0_3000010"
        assert info["terminal_label"] == "UI IN1"
        assert info["requested_name"] == receipt["intent"]["input_edit"]["name"]
        assert info["wiring_confirmation_recorded"] is True
        assert row["state"] == "verified" and row["dispatch"] == "possible"
        assert storage.receipt(row["id"]) == originals[row["id"]]
    assert (
        found[records[2]["intent"]["id"]]["native_input"]["allocation_receipt_id"]
        == records[0]["intent"]["id"]
    )
    assert peer.events == before_events and not app.state.bacnet.status()["connected"]


@pytest.mark.parametrize(
    "case",
    [
        "profile",
        "compilation_profile",
        "edit",
        "object",
        "reference",
        "preserved",
        "wires",
        "payload",
        "stored_keys",
        "stored_type",
        "stored_value",
        "stored_not_real32",
        "stored_signed_zero",
        "stored_boolean",
        "requested_type",
        "requested_extra",
        "unknown_action",
        "bad_slot",
    ],
)
async def test_invalid_recorded_bindings_keep_originals_and_withhold_structured_metadata(
    application, case
):
    body = authored_body()
    compilation = body["compilation"]
    if case == "profile":
        body["operation_profile"] = "future-input/2"
    elif case == "compilation_profile":
        compilation["profile"] = "future-input/2"
    elif case == "edit":
        compilation["input_edit"] = {**compilation["input_edit"], "slot": 2}
    elif case == "object":
        compilation["object_id"] = "analog-input,9"
    elif case == "reference":
        compilation["record_ref"] = "controller/\ninput"
    elif case == "preserved":
        compilation["other_records_preserved"] = 1
    elif case == "wires":
        compilation["wires_changed"] = 0
    elif case == "payload":
        body["native_payload_sha256"] = "f" * 64
    elif case == "stored_keys":
        compilation["stored_configuration"]["extra"] = 1
    elif case == "stored_type":
        compilation["stored_configuration"]["units"] = True
    elif case == "stored_value":
        compilation["stored_configuration"]["output_high"] = 99
    elif case == "stored_not_real32":
        body["input_edit"]["configuration"]["output_high"] = 0.1
        compilation["stored_configuration"]["output_high"] = 0.1000000001
    elif case == "stored_signed_zero":
        compilation["stored_configuration"]["input_low"] = -0.0
    elif case == "stored_boolean":
        compilation["stored_configuration"]["input_low"] = False
    elif case == "requested_type":
        body["input_edit"]["configuration"]["input_high"] = "10"
    elif case == "requested_extra":
        body["input_edit"]["can_apply"] = True
    elif case == "unknown_action":
        body["input_edit"]["action"] = "reassign"
    elif case == "bad_slot":
        body["input_edit"]["slot"] = True
    intent = native(application, **body)
    before = application.state.native_applications.storage.receipt(intent["id"])
    result = await query(application, source="native", text=intent["id"])
    assert not result["errors"] and len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["native_input"]["state"] == "unavailable" and row["object"] == ""
    assert row["native_change_kind"] == "input" and result["field_requests"] == 0
    assert application.state.native_applications.storage.receipt(intent["id"]) == before


def test_projection_keeps_exact_requested_rounding_signed_zero_and_copy_isolation():
    body = authored_body()
    body["input_edit"]["configuration"]["output_low"] = -0.0
    body["compilation"]["stored_configuration"]["output_low"] = -0.0
    info = input_reference(body)["native_input"]
    assert info["state"] == "recorded"
    assert json.dumps(info["stored_configuration"]["output_low"]) == "-0.0"
    info["stored_configuration"]["output_low"] = 42
    assert body["compilation"]["stored_configuration"]["output_low"] == 0


async def test_later_input_readback_does_not_rewrite_original_uncertain_dispatch(application):
    intent = native(application, **authored_body())
    storage = application.state.native_applications.storage
    storage.finish(
        intent["id"],
        {
            "intent_sha256": intent["evidence_sha256"],
            "status": "unknown",
            "may_have_applied": True,
        },
    )
    storage.resolve(intent["id"], {"status": "verified", "may_have_applied": False})
    original = storage.receipt(intent["id"])
    report = await query(application, source="native", text=intent["id"])
    (row,) = report["rows"]
    assert row["state"] == "verified" and row["dispatch"] == "possible"
    assert row["native_input"]["state"] == "recorded"
    assert storage.receipt(intent["id"]) == original and original["result"]["status"] == "unknown"


def test_actual_local_query_and_original_HTTP_export_need_no_interface(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        app = client.app
        intent = native(app, **authored_body())
        assert client.post("/api/changes/query", json={"source": "native"}).status_code == 403
        token = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            "/api/changes/query", headers=token, json={"source": "native", "text": "UI IN1"}
        )
        assert response.status_code == 200
        assert len(response.json()["rows"]) == 1
        response = client.post(
            "/api/changes/query", headers=token, json={"source": "native", "text": "3000010"}
        )
        (row,) = response.json()["rows"]
        assert row["native_input"]["state"] == "recorded"
        path = "/api" + row["detail_path"]
        original = client.get(path)
        assert original.status_code == 200 and original.json()["intent"] == intent
        assert original.content == client.get(path).content
        assert not client.get("/api/session").json()["field_network_open"]
