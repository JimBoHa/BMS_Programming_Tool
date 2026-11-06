"""Authored unfinished wiring checkpoints; no encoder, compiler or field calls."""

import copy

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.caf_wiring_drafts import (
    FLAGS,
    CafWiringDrafts,
)
from bms_tool.moi_identity import seal, sha
from bms_tool.storage import Conflict, Store
from fastapi.testclient import TestClient

from .test_caf_graph import REF, make_graph, pack


def selection(**updates):
    row = {
        "diagram_ref": REF,
        "wire_index": 0,
        "connection_count": 2,
        "old": [0, 663, 2, 513],
        "rewire_source_ref": "",
        "connection_source_ref": REF + ".2_11",
        "connection_target_ref": "",
    }
    row.update(updates)
    return row


def token(saved):
    return {key: saved[key] for key in ("id", "revision")}


def match(saved):
    return {"diagram_ref": saved["selection"]["diagram_ref"], "expected": token(saved)}


@pytest.mark.parametrize(
    "row",
    [
        selection(),
        selection(rewire_source_ref=REF + ".2_11"),
        selection(connection_target_ref=REF + ".2_13"),
        selection(rewire_source_ref=REF + ".2_12"),
    ],
)
def test_exact_partial_choices_restart_without_export_compatibility_or_authority(
    tmp_path, monkeypatch, row
):
    from bms_tool.caf_graph import CafGraph

    def unexpected(*args):
        raise AssertionError("Checkpoint must not run an encoder")

    monkeypatch.setattr(CafGraph, "rewire_sources", unexpected)
    monkeypatch.setattr(CafGraph, "add_connections", unexpected)
    caf = CafArchive(make_graph())
    service = CafWiringDrafts(Store(tmp_path))
    result = service.save(caf, {"selection": row, "expected": None})
    saved = result["checkpoint"]
    assert saved["selection"] == row and result["source_revalidated"] is True
    assert {key: result[key] for key in FLAGS} == FLAGS
    assert saved["checkpoint_sha256"] == seal(
        {k: v for k, v in saved.items() if k != "checkpoint_sha256"}
    )
    restarted = CafWiringDrafts(Store(tmp_path))
    assert restarted.restore(caf, match(saved))["checkpoint"] == saved
    assert restarted.status(caf.hash, REF)["checkpoint"] == saved
    assert caf.original == make_graph()


def test_generations_revisions_delete_recreate_and_stale_mutations(tmp_path):
    caf = CafArchive(make_graph())
    service = CafWiringDrafts(Store(tmp_path))
    first = service.save(caf, {"selection": selection(), "expected": None})["checkpoint"]
    with pytest.raises(Conflict):
        service.save(caf, {"selection": selection(), "expected": None})
    second = service.save(
        caf, {"selection": selection(rewire_source_ref=REF + ".2_11"), "expected": token(first)}
    )["checkpoint"]
    assert second["id"] == first["id"] and second["revision"] == 2
    for action in (service.restore, lambda _, req: service.remove(caf.hash, req)):
        with pytest.raises(Conflict):
            action(caf, match(first))
    service.remove(caf.hash, match(second))
    third = service.save(caf, {"selection": selection(), "expected": None})["checkpoint"]
    assert third["id"] != first["id"] and third["revision"] == 1
    with pytest.raises(Conflict):
        service.restore(caf, match(first))


@pytest.mark.parametrize(
    "fault",
    [
        "tuple",
        "count",
        "index",
        "unknown_ref",
        "unknown_diagram",
        "empty",
        "boolean_index",
        "extra",
    ],
)
def test_original_selection_and_closed_types_are_rechecked(tmp_path, fault):
    caf = CafArchive(make_graph())
    service = CafWiringDrafts(Store(tmp_path))
    row = selection()
    if fault == "tuple":
        row["old"][0] = 1
    if fault == "count":
        row["connection_count"] = 1
    if fault == "index":
        row["wire_index"] = 500
    if fault == "unknown_ref":
        row["connection_source_ref"] = REF + ".2_999"
    if fault == "unknown_diagram":
        row["diagram_ref"] = "not-present"
    if fault == "empty":
        row["connection_source_ref"] = ""
    if fault == "boolean_index":
        row["wire_index"] = False
    if fault == "extra":
        row["exported"] = True
    with pytest.raises(ValueError):
        service.save(caf, {"selection": row, "expected": None})
    assert service.status(caf.hash, REF)["checkpoint"] is None


def test_same_semantic_graph_different_archive_does_not_inherit_checkpoint(tmp_path):
    caf = CafArchive(make_graph())
    service = CafWiringDrafts(Store(tmp_path))
    saved = service.save(caf, {"selection": selection(), "expected": None})["checkpoint"]
    other = CafArchive(pack(caf.xml.replace(b"Preserve job", b"Different job")))
    assert service.status(other.hash, REF)["checkpoint"] is None
    with pytest.raises(Conflict):
        service.restore(other, match(saved))


@pytest.mark.parametrize("fault", ["digest", "resealed_evidence", "metadata", "oversized"])
def test_corruption_refuses_restore_and_save_but_valid_generation_can_be_removed(tmp_path, fault):
    caf = CafArchive(make_graph())
    service = CafWiringDrafts(Store(tmp_path))
    saved = service.save(caf, {"selection": selection(), "expected": None})["checkpoint"]
    altered = copy.deepcopy(saved)
    with service.store.connect() as db:
        if fault == "digest":
            db.execute("UPDATE caf_wiring_drafts SET sha256=?", ("0" * 64,))
        elif fault == "metadata":
            db.execute("UPDATE caf_wiring_drafts SET updated_at=?", ("different",))
        elif fault == "oversized":
            db.execute("UPDATE caf_wiring_drafts SET content=?", (b"x" * (1024 * 1024 + 1),))
        else:
            from bms_tool.caf_scalar_drafts import encoded

            altered["source_evidence"]["continuation_text"] = "altered"
            altered["checkpoint_sha256"] = seal(
                {k: v for k, v in altered.items() if k != "checkpoint_sha256"}
            )
            raw = encoded(altered)
            db.execute("UPDATE caf_wiring_drafts SET content=?,sha256=?", (raw, sha(raw)))
    if fault != "resealed_evidence":
        assert service.status(caf.hash, REF)["checkpoint"]["state"] == "unavailable"
    with pytest.raises(ValueError):
        service.restore(caf, match(saved))
    if fault != "resealed_evidence":
        with pytest.raises(ValueError):
            service.save(caf, {"selection": selection(), "expected": token(saved)})
    service.remove(caf.hash, match(saved))
    assert service.status(caf.hash, REF)["checkpoint"] is None


def test_bounded_capacity_refuses_new_context_without_evicting_existing_work(tmp_path, monkeypatch):
    from bms_tool import caf_wiring_drafts as module

    caf = CafArchive(make_graph())
    service = CafWiringDrafts(Store(tmp_path))
    saved = service.save(caf, {"selection": selection(), "expected": None})["checkpoint"]
    monkeypatch.setattr(module, "MAX_CONTEXTS", 1)
    other = CafArchive(pack(caf.xml.replace(b"Preserve job", b"Another original")))
    with pytest.raises(ValueError, match="capacity"):
        service.save(other, {"selection": selection(), "expected": None})
    assert service.status(caf.hash, REF)["checkpoint"] == saved
    assert (
        service.save(caf, {"selection": selection(), "expected": token(saved)})["checkpoint"][
            "revision"
        ]
        == 2
    )


def test_two_actual_diagrams_in_one_source_keep_separate_checkpoint_generations(tmp_path):
    first = CafArchive(make_graph())
    second_ref = "8-1/575_2"
    fragment = first.xml.split(b">", 1)[1].rsplit(b"</objects>", 1)[0].split(b"<jobInfo>", 1)[0]
    other = fragment.replace(REF.encode(), second_ref.encode()).replace(
        b'objectid="1"', b'objectid="2"', 1
    )
    caf = CafArchive(pack(first.xml.replace(b"</objects>", other + b"</objects>")))
    service = CafWiringDrafts(Store(tmp_path))
    a = service.save(caf, {"selection": selection(), "expected": None})["checkpoint"]
    row = selection(diagram_ref=second_ref, connection_source_ref=second_ref + ".2_11")
    b = service.save(caf, {"selection": row, "expected": None})["checkpoint"]
    assert a["id"] != b["id"]
    assert service.restore(caf, match(a))["checkpoint"] == a
    assert service.restore(caf, match(b))["checkpoint"] == b
    assert service.status(caf.hash, REF)["capacity"]["count"] == 2


def test_failed_byte_budget_replacement_leaves_prior_checkpoint_exact(tmp_path, monkeypatch):
    from bms_tool import caf_wiring_drafts as module

    caf = CafArchive(make_graph())
    service = CafWiringDrafts(Store(tmp_path))
    saved = service.save(caf, {"selection": selection(), "expected": None})["checkpoint"]
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", 1)
    with pytest.raises(ValueError, match="capacity"):
        service.save(
            caf, {"selection": selection(rewire_source_ref=REF + ".2_11"), "expected": token(saved)}
        )
    assert service.status(caf.hash, REF)["checkpoint"] == saved


def test_http_status_removal_need_no_original_cache_and_scalar_store_remains_independent(tmp_path):
    caf = CafArchive(make_graph())
    with TestClient(create_app(tmp_path)) as client:
        client.headers["X-Studio-Token"] = client.get("/api/session").json()["token"]
        assert (
            client.post("/api/caf", files={"file": ("authored.caf", caf.original)}).status_code
            == 200
        )
        base = "/api/caf/" + caf.hash + "/wiring-draft"
        saved = client.post(base, json={"selection": selection(), "expected": None}).json()[
            "checkpoint"
        ]
        assert client.post(base + "/restore", json=match(saved)).json()["checkpoint"] == saved
        assert client.get("/api/caf/" + caf.hash + "/scalar-draft").json()["checkpoint"] is None
    with TestClient(create_app(tmp_path)) as restarted:
        restarted.headers["X-Studio-Token"] = restarted.get("/api/session").json()["token"]
        assert restarted.get(base, params={"diagram_ref": REF}).json()["checkpoint"] == saved
        assert restarted.request("DELETE", base, json=match(saved)).status_code == 200
        assert restarted.get(base, params={"diagram_ref": REF}).json()["checkpoint"] is None
