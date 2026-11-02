"""Recorded Enum provenance remains local, strict and distinct from field authority."""

import copy
import gzip
import secrets
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier
from bms_tool.moi_identity import seal, sha
from bms_tool.native_applications import NativeApplications
from bms_tool.native_enum_recovery_ledger import PROFILE, SCOPE, enum_recovery_lineage
from bms_tool.native_enum_transfer import PROFILE as TRANSFER_PROFILE
from bms_tool.native_enum_transfer import compile_enum_default
from bms_tool.native_ledger_details import native_reference
from fastapi.testclient import TestClient

from .test_change_ledger import application as application  # noqa: F401
from .test_change_ledger import query
from .test_controller_application import encoded, native_record
from .test_moi_effective_enum import enum_files
from .test_moi_enum_defaults import REF
from .test_moi_parameters import parameters_source
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import apply_request, mutations
from .test_native_enum_recovery import setup
from .test_native_enum_recovery_transfer import recovery_review
from .test_native_signal_compiler import retained


def recorded_child(
    app,
    change=None,
    *,
    cid=528,
    previous=0,
    after=65535,
    possible=True,
    later_proof=False,
    states_slot=True,
):
    storage, service, request, _, files = setup(
        app.state.store.directory,
        cid=cid,
        previous=previous,
        after=after,
        states_slot=states_slot,
        outcome="unknown" if later_proof else "verified",
    )
    if later_proof:
        storage.resolve(request["receipt_id"], {"status": "verified"})
    report = service.prepare(request)
    source = storage.load(request["capture_id"])[0]
    edit = {k: report["proposal"][k] for k in ("record_ref", "encoded_sha256", "value")}
    output, compilation = compile_enum_default(files, edit)
    fresh = retained(storage, files, target=source["target"], identity=source["identity"])
    body = {
        "id": secrets.token_hex(16),
        "target": source["target"],
        "identity": source["identity"],
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": source["identity"]["object-name"],
        "new_name": source["identity"]["object-name"],
        "connector_config": source["connector_config"],
        "change_kind": "enum-default",
        "operation_profile": TRANSFER_PROFILE,
        "enum_semantics_verified": False,
        "review_capture_id": request["capture_id"],
        "review_snapshot_sha256": request["snapshot_sha256"],
        "backup_id": fresh["id"],
        "default_edit": edit,
        "compilation": compilation,
        "payload_sha256": sha(output),
        "native_payload_sha256": compilation["compiled_native_sha256"],
        "review_sha256": seal({"authored_review": report["origin_sha256"]}),
        "default_change_confirmed": True,
        "application_transfer_confirmed": True,
        "recovery_origin": report["origin"],
        "recovery_origin_sha256": report["origin_sha256"],
    }
    if change:
        change(body)
    intent = storage.intent(body)
    storage.finish(
        intent["id"],
        {
            "intent_sha256": intent["evidence_sha256"],
            "status": "unknown" if possible else "not_sent",
            "may_have_applied": possible,
        },
    )
    return intent, request["receipt_id"]


@pytest.mark.parametrize("cid", [528, 529])
@pytest.mark.parametrize("previous,after", [(0, 65535), (513, 0)])
@pytest.mark.parametrize("later_proof", [False, True])
async def test_recorded_enum_origin_keeps_actual_codes_widths_and_historical_proof(
    application, monkeypatch, cid, previous, after, later_proof
):
    intent, parent = recorded_child(
        application, cid=cid, previous=previous, after=after, later_proof=later_proof
    )
    storage = application.state.native_applications.storage
    before = storage.receipt(intent["id"])

    def forbidden(*args):
        pytest.fail("Recorded lineage queried original sources or parent proof")

    monkeypatch.setattr(storage, "load", forbidden)
    monkeypatch.setattr(storage, "verified_readback", forbidden)
    report = await query(application, source="native", text=intent["id"])
    assert not report["errors"] and len(report["rows"]) == 1 and report["field_requests"] == 0
    row = report["rows"][0]
    assert row["native_change_kind"] == "enum-default" and row["dispatch"] == "possible"
    result = row["native_recovery"]
    assert (
        result["state"] == "recorded"
        and result["profile"] == PROFILE
        and result["datatype"] == "Enumerated"
    )
    assert result["before_value"] == after and result["after_value"] == previous
    assert result["parent_receipt_id"] == parent and result["class_id"] == cid
    assert result["scope"] == SCOPE and not result["enum_semantics_verified"]
    assert result["verified_proof"]["kind"] == ("readback-event" if later_proof else "result")
    assert result["verified_proof"] == intent["recovery_origin"]["verified_proof"]
    if previous == 0:
        assert (
            result["previous_encoding_hex"] == "91002f"
            and result["after_encoding_hex"] == "9200002f"
        )
    assert storage.receipt(intent["id"]) == before


@pytest.mark.parametrize("possible", [False, True])
async def test_original_child_dispatch_fact_stays_separate_from_later_readback(
    application, possible
):
    intent, _ = recorded_child(application, possible=possible)
    storage = application.state.native_applications.storage
    storage.resolve(intent["id"], {"status": "verified", "may_have_applied": not possible})
    row = (await query(application, source="native", text=intent["id"]))["rows"][0]
    assert not row["pending"] and row["readback"] == "verified"
    assert row["dispatch"] == ("possible" if possible else "not entered")
    assert row["native_recovery"]["state"] == "recorded"


FAULTS = [
    "boolean-code",
    "float-code",
    "string-code",
    "overrange-code",
    "negative-code",
    "same-code",
    "wrong-class",
    "wrong-property",
    "semantic-authority",
    "numeric-semantic-flag",
    "extra-origin",
    "proof-kind",
    "proof-timezone",
    "proof-digest",
    "wrong-encoding-code",
    "wrong-encoding-width",
    "wrong-current-fingerprint",
    "storage-type",
    "storage-width",
    "storage-offset",
    "state-context",
    "missing-state-context",
    "parent-self",
    "origin-seal",
    "capture",
    "snapshot",
    "reference",
    "compiled-code",
    "compiled-type",
    "compiled-state",
    "payload",
    "native-payload",
    "compiler-profile",
    "confirmation",
    "numeric-confirmation",
    "instance",
    "identity",
    "vendor",
    "name",
]


def malformed(body, fault):
    o, s = body["recovery_origin"], body["compilation"]["selected_edit"]
    if fault == "boolean-code":
        o["proposal_value"] = False
    elif fault == "float-code":
        o["previous_effective_value"] = 0.0
    elif fault == "string-code":
        o["recorded_after_value"] = "65535"
    elif fault == "overrange-code":
        o["current_effective_value"] = 65536
    elif fault == "negative-code":
        o["previous_effective_value"] = -1
    elif fault == "same-code":
        o["previous_effective_value"] = o["recorded_after_value"]
    elif fault == "wrong-class":
        o["class_id"] = 527
    elif fault == "wrong-property":
        o["property"] = 931
    elif fault == "semantic-authority":
        o["enum_semantics_verified"] = True
    elif fault == "numeric-semantic-flag":
        o["enum_semantics_verified"] = 0
    elif fault == "extra-origin":
        o["can_apply"] = True
    elif fault == "proof-kind":
        o["verified_proof"]["kind"] = "snapshot"
    elif fault == "proof-timezone":
        o["verified_proof"]["time"] = "2026-11-02T10:00:00"
    elif fault == "proof-digest":
        o["verified_proof"]["sha256"] = "bad"
    elif fault == "wrong-encoding-code":
        o["previous_encoding_hex"] = "91012f"
    elif fault == "wrong-encoding-width":
        o["proposal_encoding_hex"] = "91002f"
    elif fault == "wrong-current-fingerprint":
        body["default_edit"]["encoded_sha256"] = "0" * 64
    elif fault == "storage-type":
        o["saved_storage"]["datatype"] = True
    elif fault == "storage-width":
        o["saved_storage"]["bytes"] = 4
    elif fault == "storage-offset":
        o["saved_storage"]["dynamic_value_offset"] = 131072
    elif fault == "state-context":
        o["states_text_encoded_sha256"] = None
    elif fault == "missing-state-context":
        del o["states_text_encoded_sha256"]
    elif fault == "parent-self":
        o["parent_receipt_id"] = body["id"]
    elif fault == "origin-seal":
        body["recovery_origin_sha256"] = "0" * 64
        return
    elif fault == "capture":
        body["review_capture_id"] = "0" * 32
    elif fault == "snapshot":
        body["review_snapshot_sha256"] = "0" * 64
    elif fault == "reference":
        s["record_ref"] = "controller/other"
    elif fault == "compiled-code":
        s["after_value"] = 1
    elif fault == "compiled-type":
        s["datatype"] = "Unsigned"
    elif fault == "compiled-state":
        del body["compilation"]["states_text_encoded_sha256"]
    elif fault == "payload":
        body["payload_sha256"] = "0" * 64
    elif fault == "native-payload":
        body["native_payload_sha256"] = "0" * 64
    elif fault == "compiler-profile":
        body["compilation"]["profile"] = "future/99"
    elif fault == "confirmation":
        body["default_change_confirmed"] = False
    elif fault == "numeric-confirmation":
        body["application_transfer_confirmed"] = 1
    elif fault == "instance":
        body["new_instance"] = 5137
    elif fault == "identity":
        body["identity"]["device"] = "device,5137"
    elif fault == "vendor":
        body["identity"]["vendor-identifier"] = 99
    elif fault == "name":
        body["new_name"] = "Other controller"
    else:
        raise AssertionError(fault)
    body["recovery_origin_sha256"] = seal(o)


@pytest.mark.parametrize("fault", FAULTS)
async def test_malformed_recorded_lineage_keeps_child_evidence_and_other_rows(application, fault):
    intent, _ = recorded_child(application, lambda body: malformed(body, fault))
    storage = application.state.native_applications.storage
    original = storage.receipt(intent["id"])
    report = await query(application, source="native", text=intent["id"])
    assert not report["errors"] and len(report["rows"]) == 1
    assert report["rows"][0]["native_recovery"]["state"] == "unavailable"
    assert report["field_requests"] == 0 and storage.receipt(intent["id"]) == original
    all_rows = await query(application, source="native")
    assert len(all_rows["rows"]) == 2 and not all_rows["errors"]


async def test_missing_parent_and_original_files_do_not_change_recorded_projection(
    application, monkeypatch
):
    intent, parent = recorded_child(application)
    storage = application.state.native_applications.storage
    before = (await query(application, source="native", text=intent["id"]))["rows"][0][
        "native_recovery"
    ]
    with storage.store.connect() as db:
        db.execute("DELETE FROM application_transfers WHERE id=?", (parent,))
    for key in ("original_backup_id", "current_capture_id"):
        folder = storage.directory / intent["recovery_origin"][key]
        folder.rename(folder.with_name(folder.name + "-unavailable"))

    def forbidden(*args):
        pytest.fail("Projection revalidated parent/source availability")

    monkeypatch.setattr(storage, "load", forbidden)
    monkeypatch.setattr(storage, "verified_readback", forbidden)
    assert (await query(application, source="native", text=intent["id"]))["rows"][0][
        "native_recovery"
    ] == before
    assert "does not revalidate" in before["scope"]


async def test_actual_new_enum_recovery_receipt_projects_without_new_datagrams(
    application, native_link
):
    peer, _, _, service, _ = native_link
    _, _, prepared, _, plan = await recovery_review(native_link, previous=0)
    receipt = await service.apply_enum_default(**apply_request(plan))
    assert receipt["result"]["status"] == "verified", receipt
    before = list(peer.events), list(mutations(peer))
    row = (await query(application, source="native", text=receipt["intent"]["id"]))["rows"][0]
    assert row["native_recovery"]["state"] == "recorded"
    assert row["native_recovery"]["origin_sha256"] == prepared["origin_sha256"]
    assert row["native_recovery"]["after_value"] == 0 and row["outcome"] == "verified"
    assert (peer.events, mutations(peer)) == before


def test_offline_http_detail_and_restart_preserve_exact_original_and_no_apply_authority(
    application,
):
    intent, _ = recorded_child(application)
    original = copy.deepcopy(application.state.native_applications.storage.receipt(intent["id"]))
    with TestClient(application) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        body = {"source": "native", "text": intent["id"]}
        assert client.post("/api/changes/query", json=body).status_code == 403
        result = client.post("/api/changes/query", headers=headers, json=body)
        assert result.status_code == 200 and result.json()["field_requests"] == 0
        row = result.json()["rows"][0]
        assert row["native_recovery"]["profile"] == PROFILE
        assert client.get("/api" + row["detail_path"]).json() == original
        assert (
            client.post(
                "/api/changes/query", headers=headers, json=body | {"apply": True}
            ).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]
    restarted = NativeApplications(
        application.state.bacnet, application.state.store, application.state.device_instances
    )
    assert restarted.storage.receipt(intent["id"]) == original


def test_non_enum_receipt_and_conflicting_reference_cannot_gain_enum_lineage(application):
    intent, _ = recorded_child(application)
    reference = native_reference("enum-default", intent["default_edit"])
    for body, ref in (
        (intent | {"change_kind": "boolean-default"}, reference),
        (intent, {"object": reference["object"], "native_reference_issue": "conflicting"}),
    ):
        assert enum_recovery_lineage(body, ref)["state"] == "unavailable"


async def test_explicitly_absent_state_metadata_is_not_an_invented_state_domain(
    application, monkeypatch
):
    def without_state_metadata(**options):
        files = enum_files(**options)
        cid = options.get("cid", 528)
        base, _, _ = parameters_source(compressed=False)
        root = bytearray(base)
        struct.pack_into("<I", root, 10, struct.unpack_from("<I", root, 10)[0] + 1)
        record = native_record(
            cid,
            1,
            [
                (32527, encoded(CharacterString(REF))),
                (75, encoded(ObjectIdentifier((cid, 1)))),
                (3113, b"\x91\x01"),
                (65000, encoded(CharacterString(""))),
            ],
        )
        raw = bytes(root) + struct.pack("<H", len(record) + 2) + record
        files[3] = gzip.compress(raw, mtime=123) if options.get("compressed", True) else raw
        return files

    monkeypatch.setattr("tests.test_native_enum_recovery.enum_files", without_state_metadata)
    intent, parent = recorded_child(application, states_slot=False)
    rows = {r["id"]: r for r in (await query(application, source="native"))["rows"]}
    assert rows[intent["id"]]["native_recovery"]["state"] == "recorded"
    assert rows[intent["id"]]["native_recovery"]["states_text_encoded_sha256"] is None
    assert "native_recovery" not in rows[parent]
