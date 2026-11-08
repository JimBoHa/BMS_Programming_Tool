"""Recorded restore lineage never revalidates files or grants field authority."""

import asyncio
import copy
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import seal
from bms_tool.native_snapshot_restore_ledger import restore_reference
from fastapi.testclient import TestClient

from .test_native_applications import native_link
from .test_native_snapshot_restore import apply_request, prepared


async def retained(directory):
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(directory, patch)) as generator:
            link = await anext(generator)
            old, _, plan = await prepared(link)
            receipt = await link[3].apply_snapshot_restore(**apply_request(plan))
            assert receipt["result"]["status"] == "verified"
            return copy.deepcopy(receipt), old, directory


@pytest.fixture(scope="module")
def actual_restore(tmp_path_factory):
    return asyncio.run(retained(tmp_path_factory.mktemp("recorded-application-restore")))


def reseal(body):
    desired = body["restore_source"]
    desired["evidence_sha256"] = seal({k: v for k, v in desired.items() if k != "evidence_sha256"})
    c = body["compilation"]
    c["restore_source_evidence_sha256"] = desired["evidence_sha256"]
    c["compilation_sha256"] = seal({k: v for k, v in c.items() if k != "compilation_sha256"})


def test_recorded_restore_preserves_three_distinct_origins_and_immutable_receipt(actual_restore):
    receipt, old, _ = actual_restore
    before = copy.deepcopy(receipt)
    value = restore_reference(receipt["intent"])["native_application_restore"]
    assert value["state"] == "recorded"
    assert value["restore_capture_id"] == old["id"]
    assert value["review_capture_id"] == receipt["intent"]["review_capture_id"]
    assert value["prewrite_backup_id"] == receipt["intent"]["backup_id"]
    assert (
        len({value[k] for k in ("restore_capture_id", "review_capture_id", "prewrite_backup_id")})
        == 3
    )
    assert value["difference"]["removed_records"] == 3
    assert all(
        value[k] is False
        for k in ("field_authority", "source_revalidated", "current_device_verified")
    )
    value["difference"].clear()
    assert receipt == before


@pytest.mark.parametrize(
    "fault",
    [
        "profile",
        "source-scope",
        "source-extra",
        "source-authority",
        "vendor-bool",
        "source-time",
        "source-files",
        "source-count-bool",
        "source-format-bool",
        "source-hash",
        "qualification",
        "compilation-extra",
        "kind",
        "child-id",
        "review-id",
        "review-hash",
        "own-source",
        "own-current",
        "current-equals-source",
        "counter-count",
        "counter-type",
        "payload",
        "native-payload",
        "negative-count",
        "bool-count",
        "count-arithmetic",
        "changed-count",
        "foreign-edit",
        "recovery-authority",
        "difference-scope",
        "difference-extra",
    ],
)
def test_resealed_malformed_recorded_restore_is_unavailable(actual_restore, fault):
    body = copy.deepcopy(actual_restore[0]["intent"])
    desired, c = body["restore_source"], body["compilation"]
    if fault == "profile":
        body["operation_profile"] += "future"
    elif fault == "source-scope":
        desired["scope"] += "future"
    elif fault == "source-extra":
        desired["unqualified_authority"] = True
    elif fault == "source-authority":
        desired["can_apply"] = True
    elif fault == "vendor-bool":
        desired["identity"]["vendor-identifier"] = True
        body["identity"]["vendor-identifier"] = True
    elif fault == "source-time":
        desired["captured_at"] = "not a date"
    elif fault == "source-files":
        desired["compilation"]["files"].pop("11")
    elif fault == "source-count-bool":
        desired["compilation"]["native_record_count"] = True
    elif fault == "source-format-bool":
        desired["compilation"]["format_versions"]["acs"] = True
    elif fault == "source-hash":
        desired["compilation"]["files"]["3"]["sha256"] += "\n"
    elif fault == "qualification":
        desired["compilation"]["omitted_field_qualification"]["model_inventory_used"] = True
    elif fault == "compilation-extra":
        c["future_authority"] = True
    elif fault == "kind":
        body["change_kind"] = "execution-order"
    elif fault == "child-id":
        body["id"] = "unknown"
    elif fault == "review-id":
        body["review_capture_id"] = "f" * 32
    elif fault == "review-hash":
        body["review_snapshot_sha256"] = "f" * 64
    elif fault == "own-source":
        body["backup_id"] = desired["request"]["restore_capture_id"]
    elif fault == "own-current":
        body["backup_id"] = body["review_capture_id"]
    elif fault == "current-equals-source":
        body["review_capture_id"] = desired["request"]["restore_capture_id"]
        c["reviewed_current"]["capture_id"] = body["review_capture_id"]
    elif fault == "counter-count":
        c["prewrite_guard"]["counter_count"] = c["prewrite_guard"]["saved_parameter_count"] + 1
    elif fault == "counter-type":
        c["prewrite_guard"]["counter_count"] = True
    elif fault == "payload":
        body["payload_sha256"] = "f" * 64
    elif fault == "native-payload":
        body["native_payload_sha256"] = "f" * 64
    elif fault == "negative-count":
        c["difference"]["added_records"] = -1
    elif fault == "bool-count":
        c["difference"]["removed_records"] = True
    elif fault == "count-arithmetic":
        c["difference"]["added_records"] += 1
    elif fault == "changed-count":
        c["difference"]["changed_existing_records"] = 999
    elif fault == "foreign-edit":
        body["order_edit"] = {}
    elif fault == "difference-scope":
        c["difference"]["scope"] += "future"
    elif fault == "difference-extra":
        c["difference"]["future_authority"] = True
    else:
        body["recovery_profile"] = "invented-restore"
    reseal(body)
    assert restore_reference(body)["native_application_restore"]["state"] == "unavailable", fault


def test_changes_query_retains_recorded_reference_when_historical_file_is_missing(actual_restore):
    receipt, old, directory = actual_restore
    matches = [p for p in directory.rglob("file-3.bin") if p.parent.name == old["id"]]
    assert len(matches) == 1
    path, raw = matches[0], matches[0].read_bytes()
    try:
        path.unlink()
        with TestClient(create_app(directory)) as client:
            headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
            response = client.post("/api/changes/query", headers=headers, json={"source": "native"})
            assert response.status_code == 200, response.text
            (row,) = [r for r in response.json()["rows"] if r["id"] == receipt["intent"]["id"]]
        assert row["native_change_kind"] == "application-restore"
        assert row["native_application_restore"]["state"] == "recorded"
        assert row["native_application_restore"]["source_revalidated"] is False
        assert "native_recovery" not in row
    finally:
        path.write_bytes(raw)
