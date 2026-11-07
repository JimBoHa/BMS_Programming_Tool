"""Recorded recovery lineage is useful without revalidating parent or field state."""

import asyncio
import copy
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import seal
from bms_tool.native_default_batch_recovery_ledger import recovery_reference

from .test_change_ledger import query
from .test_native_applications import native_link
from .test_native_default_batch_recovery_transfer import original_and_proposal
from .test_native_default_batch_transfer import applying


async def retained_recovery(directory, mode="verified"):
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(directory, patch)) as generator:
            link = await anext(generator)
            peer, _, _, native, _ = link
            parent, _, args = await original_and_proposal(link)
            plan = await native.preview_default_batch(**args)
            if mode != "verified":
                peer.mode = "drop-end"
            receipt = await native.apply_default_batch(**applying(plan))
            if mode == "later-unknown":
                peer.mode = "normal"
                receipt = await native.reconcile(
                    operation_id="ledger-batch-recovery-readback",
                    receipt_id=receipt["intent"]["id"],
                )
                native.storage.event(receipt["intent"]["id"], "readback", {"status": "unknown"})
                receipt = native.storage.receipt(receipt["intent"]["id"])
            return copy.deepcopy(receipt), parent


@pytest.fixture(scope="module")
def actual_recovery(tmp_path_factory):
    return asyncio.run(retained_recovery(tmp_path_factory.mktemp("recorded-batch-recovery")))


def test_actual_origin_projects_typed_values_and_seals_without_mutating_receipt(actual_recovery):
    receipt, parent = actual_recovery
    original = copy.deepcopy(receipt)
    row = recovery_reference(receipt["intent"])
    projected = row["native_default_batch_recovery"]
    assert projected["state"] == row["native_default_batch"]["state"] == "recorded"
    assert projected["origin"]["parent_receipt_id"] == parent["intent"]["id"]
    assert projected["origin_sha256"] == seal(projected["origin"])
    assert projected["origin"]["fields"][1]["recorded_after"] == {"bits": "80000000"}
    assert all(
        projected[k] is False
        for k in (
            "field_authority",
            "parent_revalidated",
            "source_revalidated",
            "current_device_verified",
        )
    )
    projected["origin"]["fields"].clear()
    assert receipt == original


FAULTS = (
    "profile",
    "scope",
    "unknown",
    "extra-origin",
    "empty",
    "over-limit",
    "order",
    "duplicate",
    "proof",
    "proof-time-number",
    "proof-naive-time",
    "own-parent",
    "capture",
    "snapshot",
    "backup",
    "origin-native-hash",
    "third-current",
    "previous",
    "recorded-after",
    "already",
    "real-nan",
    "real-uppercase",
    "boolean-number",
    "enum-bool",
    "enum-overflow",
    "class",
    "property",
    "encoded",
    "seal",
    "selected",
    "payload",
    "child-capture",
    "child-snapshot",
    "child-id",
    "vendor-bool",
    "device",
    "name",
    "target",
)


def alter(body, fault):
    o = body["recovery_origin"]
    f = o["fields"][0]
    if fault == "profile":
        body["recovery_profile"] = "unsupported/2"
    elif fault == "scope":
        body["recovery_scope"] = "Live verification"
    elif fault == "unknown":
        body["recovery_future"] = True
    elif fault == "extra-origin":
        o["authority"] = True
    elif fault == "empty":
        o["fields"] = []
    elif fault == "over-limit":
        o["fields"] = o["fields"] * 5
    elif fault == "order":
        o["fields"].reverse()
    elif fault == "duplicate":
        o["fields"][1] = copy.deepcopy(f)
    elif fault == "proof":
        o["verified_proof"]["kind"] = "unverified"
    elif fault == "proof-time-number":
        o["verified_proof"]["time"] = 1
    elif fault == "proof-naive-time":
        o["verified_proof"]["time"] = "2026-11-06T08:00:00"
    elif fault == "own-parent":
        o["parent_receipt_id"] = body["id"]
    elif fault == "capture":
        o["current_capture_id"] = "a" * 32
    elif fault == "snapshot":
        o["current_snapshot_sha256"] = "a" * 64
    elif fault == "backup":
        o["original_backup_id"] = o["current_capture_id"]
    elif fault == "origin-native-hash":
        o["recorded_native_payload_sha256"] = "invalid"
    elif fault == "third-current":
        f["current"]["bits"] = "3f800000"
    elif fault == "previous":
        f["previous"]["bits"] = "3f800000"
    elif fault == "recorded-after":
        f["recorded_after"]["bits"] = "3f800000"
    elif fault == "already":
        f["already_recorded"] = not f["already_recorded"]
    elif fault == "real-nan":
        f["previous"]["bits"] = "7fc00000"
    elif fault == "real-uppercase":
        f["previous"]["bits"] = "7F800001"
    elif fault == "boolean-number":
        o["fields"][2]["previous"]["value"] = 1
    elif fault == "enum-bool":
        o["fields"][3]["previous"]["value"] = True
    elif fault == "enum-overflow":
        o["fields"][3]["previous"]["value"] = 65536
    elif fault == "class":
        f["class_id"] = 530
    elif fault == "property":
        f["property"] = 1
    elif fault == "encoded":
        f["current_encoded_sha256"] = "a" * 64
    elif fault == "selected":
        body["compilation"]["selected"][0]["after_encoding_hex"] = "443f8000002f"
    elif fault == "payload":
        body["native_payload_sha256"] = "a" * 64
    elif fault == "child-capture":
        body["review_capture_id"] = "a" * 32
    elif fault == "child-snapshot":
        body["batch_edit"]["snapshot_sha256"] = "a" * 64
    elif fault == "child-id":
        body["id"] = "invalid"
    elif fault == "vendor-bool":
        body["identity"]["vendor-identifier"] = True
    elif fault == "device":
        body["identity"]["device"] = "device,1"
    elif fault == "name":
        body["identity"]["object-name"] = "Different"
    elif fault == "target":
        body["target"]["device"] = "device,1"
    body["recovery_origin_sha256"] = "a" * 64 if fault == "seal" else seal(o)


@pytest.mark.parametrize("fault", FAULTS)
def test_malformed_resealed_origin_or_child_withholds_recorded_projection(actual_recovery, fault):
    body = copy.deepcopy(actual_recovery[0]["intent"])
    alter(body, fault)
    result = recovery_reference(body)
    assert result["native_default_batch_recovery"]["state"] == "unavailable"
    assert result["native_default_batch"]["state"] == "unavailable"


@pytest.mark.parametrize("mode", ["verified", "uncertain", "later-unknown"])
async def test_parent_search_keeps_child_outcome_and_queries_no_sources_or_field(
    tmp_path, monkeypatch, mode
):
    receipt, parent = await retained_recovery(tmp_path, mode)
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Recorded recovery attempted backup or controller access")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "load", forbidden)
    report = await query(app, source="native", text=parent["intent"]["id"])
    rows = {r["id"]: r for r in report["rows"]}
    row = rows[receipt["intent"]["id"]]
    assert row["native_default_batch_recovery"]["state"] == "recorded"
    assert row["pending"] is (mode == "uncertain")
    assert row["state"] == ("verified" if mode == "verified" else "unknown")
    assert parent["intent"]["id"] in rows
    assert report["field_requests"] == 0 and report["read_only"]


async def test_child_lineage_remains_recorded_when_parent_reader_is_unavailable(
    tmp_path, monkeypatch
):
    receipt, parent = await retained_recovery(tmp_path)
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    original_reader = storage.receipt

    def own_only(identifier, *args, **kwargs):
        if identifier == parent["intent"]["id"]:
            raise ValueError("Original parent is unavailable")
        return original_reader(identifier, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("Recorded lineage tried to reopen source files")

    monkeypatch.setattr(storage, "receipt", own_only)
    monkeypatch.setattr(storage, "load", forbidden)
    report = await query(app, source="native", text=receipt["intent"]["id"])
    row = next(r for r in report["rows"] if r["id"] == receipt["intent"]["id"])
    assert (
        row["native_default_batch_recovery"]["origin"]["parent_receipt_id"]
        == parent["intent"]["id"]
    )
    assert row["native_default_batch_recovery"]["parent_revalidated"] is False
    assert report["field_requests"] == 0
