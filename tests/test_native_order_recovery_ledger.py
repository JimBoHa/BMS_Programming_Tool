"""Actual recovery lineage remains recorded without parent/source/field revalidation."""

import asyncio
import copy
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import seal
from bms_tool.native_order_recovery_ledger import recovery_reference
from bms_tool.native_order_recovery_transfer import recorded_parent
from fastapi.testclient import TestClient

from .test_native_applications import native_link
from .test_native_order_recovery_transfer import original_and_proposal
from .test_native_order_transfer import applying


async def retained_recovery(directory):
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(directory, patch)) as generator:
            link = await anext(generator)
            _, _, _, native, _ = link
            parent, _, args = await original_and_proposal(link)
            plan = await native.preview_order(**args)
            receipt = await native.apply_order(
                **applying(plan, operation_id="ledger-previous-order")
            )
            return copy.deepcopy(receipt), copy.deepcopy(parent), directory


@pytest.fixture(scope="module")
def actual_recovery(tmp_path_factory):
    return asyncio.run(retained_recovery(tmp_path_factory.mktemp("recorded-order-recovery")))


def test_actual_order_and_origin_project_without_altering_receipt(actual_recovery):
    receipt, parent, _ = actual_recovery
    before = copy.deepcopy(receipt)
    data = recovery_reference(receipt["intent"])["native_order_recovery"]
    assert data["state"] == "recorded"
    assert data["before"] == [1, 0, 2, 3] and data["after"] == [0, 1, 2, 3]
    assert data["origin"]["parent_receipt_id"] == parent["intent"]["id"]
    assert data["origin_sha256"] == seal(data["origin"])
    assert all(
        data[key] is False
        for key in (
            "field_authority",
            "parent_revalidated",
            "source_revalidated",
            "current_device_verified",
        )
    )
    data["before"].clear()
    data["origin"].clear()
    assert receipt == before


@pytest.mark.parametrize(
    "fault",
    [
        "profile",
        "scope",
        "unknown",
        "missing-origin",
        "origin-time",
        "origin-seal",
        "own-parent",
        "child-id",
        "kind",
        "operation",
        "instance-bool",
        "new-instance-bool",
        "vendor-bool",
        "device",
        "capture",
        "snapshot",
        "diagram",
        "before-bool",
        "width-bool",
        "selection",
        "compilation-seal",
        "payload",
    ],
)
def test_resealed_inconsistent_recorded_metadata_is_unavailable(actual_recovery, fault):
    receipt, _, _ = actual_recovery
    body = copy.deepcopy(receipt["intent"])
    if fault == "profile":
        body["recovery_profile"] += "future"
    elif fault == "scope":
        body["recovery_scope"] += "future"
    elif fault == "unknown":
        body["recovery_other"] = False
    elif fault == "missing-origin":
        body.pop("recovery_origin")
    elif fault == "origin-time":
        body["recovery_origin"]["verified_proof"]["time"] = "2026-01-01T00:00:00"
        body["recovery_origin_sha256"] = seal(body["recovery_origin"])
    elif fault == "origin-seal":
        body["recovery_origin_sha256"] = "a" * 64
    elif fault == "own-parent":
        body["id"] = body["recovery_origin"]["parent_receipt_id"]
    elif fault == "child-id":
        body["id"] = "unknown"
    elif fault == "kind":
        body["change_kind"] = "wire-source"
    elif fault == "operation":
        body["operation_profile"] += "future"
    elif fault == "instance-bool":
        body["old_instance"] = True
    elif fault == "new-instance-bool":
        body["new_instance"] = True
    elif fault == "vendor-bool":
        body["identity"]["vendor-identifier"] = True
    elif fault == "device":
        body["identity"]["device"] = "device,99"
    elif fault == "capture":
        body["review_capture_id"] = "a" * 32
    elif fault == "snapshot":
        body["review_snapshot_sha256"] = "a" * 64
    elif fault == "diagram":
        body["order_edit"]["diagram_ref"] += "other"
    elif fault == "before-bool":
        body["order_guard"]["original_order"][0] = True
    elif fault == "width-bool":
        body["order_guard"]["payload_widths"][0] = True
    elif fault == "selection":
        body["compilation"]["order_edit"]["selection"]["original_order"] = [0, 1, 2, 3]
    elif fault == "compilation-seal":
        body["compilation"]["order_compilation_sha256"] = "a" * 64
    else:
        body["native_payload_sha256"] = "a" * 64
    if fault != "compilation-seal":
        body["compilation"]["order_compilation_sha256"] = seal(
            {k: v for k, v in body["compilation"].items() if k != "order_compilation_sha256"}
        )
    assert recovery_reference(body)["native_order_recovery"]["state"] == "unavailable", fault


@pytest.mark.parametrize("value", [None, {}, True, {"parent_receipt_id": "a" * 32}])
def test_malformed_historical_origin_does_not_break_status_parent_listing(actual_recovery, value):
    body = copy.deepcopy(actual_recovery[0]["intent"])
    body["recovery_origin"] = value
    assert recorded_parent(body) is None


def test_changes_query_keeps_recorded_lineage_when_original_parent_file_is_missing(actual_recovery):
    receipt, parent, directory = actual_recovery
    # Use the actual retained folder, not a guessed persistent-store layout.
    matches = [
        p for p in directory.rglob("file-3.bin") if p.parent.name == parent["intent"]["backup_id"]
    ]
    assert len(matches) == 1
    path = matches[0]
    raw = path.read_bytes()
    try:
        path.unlink()
        with TestClient(create_app(directory)) as client:
            token = client.get("/api/session").json()["token"]
            response = client.post(
                "/api/changes/query", json={"source": "native"}, headers={"X-Studio-Token": token}
            )
            assert response.status_code == 200, response.text
            report = response.json()
        row = next(r for r in report["rows"] if r["id"] == receipt["intent"]["id"])
        assert row["native_order_recovery"]["state"] == "recorded"
        assert row["native_order_recovery"]["parent_revalidated"] is False
        assert row["native_order_recovery"]["origin"]["parent_receipt_id"] == parent["intent"]["id"]
        assert "native_recovery" not in row
    finally:
        path.write_bytes(raw)
