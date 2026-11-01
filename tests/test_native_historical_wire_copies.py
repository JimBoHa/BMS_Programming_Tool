"""Historical-pin local HTTP copies are exact and never confer field-transfer authority."""

import copy

import pytest
from bms_tool.app import create_app
from bms_tool.moi_effective_wire import EffectiveWireCompiler
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.native_historical_wire_copies import NativeHistoricalWireCopies
from bms_tool.native_historical_wire_recovery import NativeHistoricalWireRecovery
from fastapi.testclient import TestClient

from .test_moi_wire_sources import REF, A
from .test_native_wire_recovery import FANOUT, setup

BASE = "/api/bacnet/controller/native-application/inspection/historical-wire-source"


def local_case(tmp_path, *, fanout=False):
    storage, ordinary, request, before, files = setup(
        tmp_path, wires=FANOUT if fanout else FANOUT[:2]
    )
    recovery = NativeHistoricalWireRecovery(ordinary.records)
    report = recovery.prepare(request)
    body = report["proposal"] | {"recovery_origin_sha256": report["origin_sha256"]}
    return storage, recovery, report, body, before, files


def test_local_http_copy_keeps_exact_review_and_native_bytes_without_queries_or_new_intents(
    tmp_path,
):
    storage, _, report, body, _, files = local_case(tmp_path)
    parent = copy.deepcopy(storage.receipt(body["recovery_parent_receipt"]))
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(BASE + "/preview", json=body).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(BASE + "/preview", json=body, headers=headers)
        assert response.status_code == 200, response.text
        review = response.json()
        assert review["recovery_profile"] == report["profile"]
        assert review["recovery_origin"] == report["origin"]
        assert review["recovery_origin_sha256"] == report["origin_sha256"]
        assert (
            review["compilation"]["historical_pin_evidence_sha256"]
            == report["origin"]["historical_pin_sha256"]
        )
        assert (
            review["read_only"]
            and not review["can_apply"]
            and not review["field_actions"]
            and not review["controller_queries"]
        )
        exported = client.post(
            BASE + "/export",
            json=body | {"review_sha256": review["review_sha256"]},
            headers=headers,
        )
        assert exported.status_code == 200, exported.text
        assert (
            exported.headers["X-Studio-Artifact-Sha256"]
            == sha(exported.content)
            == review["output_sha256"]
        )
        assert exported.headers["X-Studio-Snapshot-Sha256"] == body["snapshot_sha256"]
        image = MoiIdentity(exported.content)
        merged = EffectiveWireCompiler(files).effective.editor.data
        edit = review["compilation"]["wire_edit"]
        offset, width = edit["source_index_offset"], edit["source_index_bytes"]
        assert image.data == merged[:offset] + b"\x00" * width + merged[offset + width :]
        assert image.reader.diagram(REF)["connections"][0]["source_ref"] == A
        assert not client.get("/api/session").json()["field_network_open"]
    assert storage.receipt(body["recovery_parent_receipt"]) == parent
    assert len(storage.receipts()) == 1 and storage.load(body["capture_id"])[1] == files


@pytest.mark.parametrize(
    "change", ["source", "wire", "origin", "parent", "injected-pin", "apply-flag", "missing-parent"]
)
def test_local_copy_rejects_unbound_or_injected_purpose(tmp_path, change):
    storage, _, _, body, _, files = local_case(tmp_path)
    if change == "source":
        body["source_ref"] = "other/source"
    elif change == "wire":
        body["wire_index"] = 1
    elif change == "origin":
        body["recovery_origin_sha256"] = "0" * 64
    elif change == "parent":
        body["recovery_parent_receipt"] = "0" * 32
    elif change == "injected-pin":
        body["historical_pin"] = {"source_ref": A, "old": [0, 85, 2, 7000]}
    elif change == "apply-flag":
        body["application_transfer_confirmed"] = True
    else:
        del body["recovery_parent_receipt"]
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        result = client.post(BASE + "/preview", json=body, headers=headers)
        assert result.status_code in (400, 404, 422), result.text
        assert not client.get("/api/session").json()["field_network_open"]
    assert len(storage.receipts()) == 1 and storage.load(body["capture_id"])[1] == files


def test_current_observed_pin_keeps_ordinary_compilation_endpoint(tmp_path):
    _, recovery, _, body, _, _ = local_case(tmp_path, fanout=True)
    with pytest.raises(ValueError, match="ordinary effective"):
        NativeHistoricalWireCopies(recovery.records, recovery).preview(body)


def test_parent_proof_rechecked_before_export(tmp_path):
    storage, recovery, _, body, before, _ = local_case(tmp_path)
    service = NativeHistoricalWireCopies(recovery.records, recovery)
    _, review = service.preview(body)
    (storage.directory / before["id"] / "file-12.bin").write_bytes(b"Tampered")
    with pytest.raises(ValueError, match="integrity"):
        service.export(body | {"review_sha256": review["review_sha256"]})


def test_changed_copy_review_seal_is_not_an_export(tmp_path):
    _, recovery, _, body, _, _ = local_case(tmp_path)
    service = NativeHistoricalWireCopies(recovery.records, recovery)
    with pytest.raises(ValueError, match="review changed"):
        service.export(body | {"review_sha256": seal({"not": "the review"})})
