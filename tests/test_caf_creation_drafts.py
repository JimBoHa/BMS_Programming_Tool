"""Authored recorded-copy checkpoints, without native encoding or controller access."""

import copy
import importlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.caf_comparison_copy import CafComparisonCopies
from bms_tool.caf_creation_drafts import (
    FLAGS,
    INSPECTORS,
    CafCreationDrafts,
    selection_context,
)
from bms_tool.caf_scalar_drafts import encoded
from bms_tool.moi_identity import seal, sha
from bms_tool.storage import Conflict, Store
from fastapi.testclient import TestClient

from .test_caf_constant_copy import PROTOTYPE, REF, example, packed

FAMILIES = [
    ("float", "constant", {}),
    ("boolean", "boolean", {}),
    ("enumeration", "enum_creation", {}),
    ("comparison", "comparison", {}),
    ("comparison", "enum_comparison", {}),
    ("math", "math", {}),
    ("timer", "timer", {}),
    ("timer", "timer", {"encoding": 21, "mode": "4"}),
    ("booleanLogic", "boolean_logic", {}),
    ("reliability", "reliability", {}),
    ("reliability", "reliability", {"kind": "enum"}),
    ("multiplexer", "float_multiplexer", {}),
    ("multiplexer", "enum_selector_multiplexer", {}),
    ("multiplexer", "enum_multiplexer", {}),
    ("multiplexer", "enum_enum_selector_multiplexer", {}),
    ("multiplexer", "boolean_multiplexer", {}),
    ("multiplexer", "boolean_multiplexer", {"kind": "enum-two"}),
    ("multiplexer", "boolean_multiplexer", {"kind": "enum-five-a"}),
    ("multiplexer", "boolean_multiplexer", {"kind": "enum-five-b"}),
]


def selection(caf, kind="float", diagram=REF, prototype=PROTOTYPE, **changes):
    observed = INSPECTORS[kind](caf).inspect(diagram, prototype)
    return {
        "kind": kind,
        "diagram_ref": diagram,
        "prototype_ref": prototype,
        "selection_sha256": observed["selection_sha256"],
        "x": "1e-",
        "y": "",
        **changes,
    }


def token(saved):
    return {k: saved[k] for k in ("id", "revision")}


def match(saved):
    return {**selection_context(saved["selection"]), "expected": token(saved)}


@pytest.mark.parametrize("kind,module_name,changes", FAMILIES)
def test_all_existing_copy_inspectors_retain_raw_text_restart_and_exact_report_without_encoding(
    tmp_path, monkeypatch, kind, module_name, changes
):
    suffix = module_name if module_name.endswith("creation") else module_name + "_copy"
    module = importlib.import_module("tests.test_caf_" + suffix)
    original = module.example(zero=True, **changes)
    caf = CafArchive(original)
    row = selection(caf, kind, module.REF, module.PROTOTYPE, x="+1e-", y="  unfinished α\n")

    def forbidden(*args, **kwargs):
        raise AssertionError("Checkpoint must never encode/export a CAF")

    monkeypatch.setattr(CafArchive, "_copy_xml", forbidden)
    monkeypatch.setattr(CafArchive, "patch", forbidden)
    for engine in set(INSPECTORS.values()) | {CafComparisonCopies}:
        monkeypatch.setattr(engine, "compile", forbidden)
    service = CafCreationDrafts(Store(tmp_path))
    result = service.save(caf, {"selection": row, "expected": None})
    saved = result["checkpoint"]
    assert saved["selection"] == row
    assert {key: result[key] for key in FLAGS} == FLAGS
    assert result["source_revalidated"] is True
    assert saved["checkpoint_sha256"] == seal(
        {k: v for k, v in saved.items() if k != "checkpoint_sha256"}
    )
    restarted = CafCreationDrafts(Store(tmp_path))
    assert restarted.restore(caf, match(saved))["checkpoint"] == saved
    assert restarted.status(caf.hash, selection_context(row))["checkpoint"] == saved
    assert restarted.report(caf.hash, match(saved)) == encoded(saved)
    assert caf.original == original


def test_generations_stale_revision_delete_recreate_and_atomic_duplicate_save(tmp_path):
    caf = CafArchive(example())
    service = CafCreationDrafts(Store(tmp_path))

    def save_once(_):
        try:
            return service.save(caf, {"selection": selection(caf), "expected": None})["checkpoint"]
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save_once, range(2)))
    (first,) = [r for r in results if r]
    assert service.status(caf.hash, selection_context(first["selection"]))["capacity"]["count"] == 1
    second = service.save(caf, {"selection": selection(caf, x="-"), "expected": token(first)})[
        "checkpoint"
    ]
    assert second["id"] == first["id"] and second["revision"] == 2
    assert second["created_at"] == first["created_at"]
    for action in (
        lambda: service.restore(caf, match(first)),
        lambda: service.report(caf.hash, match(first)),
        lambda: service.remove(caf.hash, match(first)),
    ):
        with pytest.raises(Conflict):
            action()
    service.remove(caf.hash, match(second))
    third = service.save(caf, {"selection": selection(caf), "expected": None})["checkpoint"]
    assert third["id"] != first["id"] and third["revision"] == 1
    with pytest.raises(Conflict):
        service.restore(caf, match(second))


@pytest.mark.parametrize(
    "mutation",
    [
        {"kind": "unsupported"},
        {"kind": True},
        {"kind": "boolean"},
        {"diagram_ref": "missing"},
        {"prototype_ref": "missing"},
        {"selection_sha256": "0" * 64},
        {"x": 1},
        {"y": False},
        {"x": None},
        {"x": "x" * 8193},
        {"extra": "authority"},
    ],
)
def test_invalid_selection_has_no_checkpoint_or_compilation_side_effect(tmp_path, mutation):
    caf = CafArchive(example())
    service = CafCreationDrafts(Store(tmp_path))
    row = selection(caf)
    with pytest.raises(ValueError):
        service.save(caf, {"selection": {**row, **mutation}, "expected": None})
    assert service.status(caf.hash, selection_context(row))["checkpoint"] is None


@pytest.mark.parametrize(
    "fault",
    ["bytes", "oversize", "extra", "profile", "timestamp", "SQL", "digest", "resealed_evidence"],
)
def test_unavailable_checkpoint_cannot_restore_and_explicit_removal_preserves_original(
    tmp_path, fault
):
    caf = CafArchive(example())
    service = CafCreationDrafts(Store(tmp_path))
    saved = service.save(caf, {"selection": selection(caf), "expected": None})["checkpoint"]
    altered = copy.deepcopy(saved)
    with service.store.connect() as db:
        if fault == "bytes":
            db.execute("UPDATE caf_creation_drafts SET content=?", (b"not JSON",))
        elif fault == "oversize":
            db.execute("UPDATE caf_creation_drafts SET content=?", (b"x" * (1024 * 1024 + 1),))
        elif fault == "SQL":
            db.execute("UPDATE caf_creation_drafts SET updated_at='different'")
        else:
            if fault == "extra":
                altered["can_apply"] = True
            elif fault == "profile":
                altered["profile"] = "other/1"
            elif fault == "timestamp":
                altered["created_at"] = "not a date"
            elif fault == "digest":
                altered["selection"]["selection_sha256"] = "0" * 64
            else:
                altered["source_evidence"]["prototype_sha256"] = "0" * 64
            altered["checkpoint_sha256"] = seal(
                {k: v for k, v in altered.items() if k != "checkpoint_sha256"}
            )
            raw = encoded(altered)
            db.execute("UPDATE caf_creation_drafts SET content=?,sha256=?", (raw, sha(raw)))
    status = service.status(caf.hash, selection_context(saved["selection"]))
    if fault != "resealed_evidence":
        assert status["checkpoint"]["state"] == "unavailable"
    with pytest.raises(ValueError):
        service.restore(caf, match(saved))
    if fault != "resealed_evidence":
        with pytest.raises(ValueError):
            service.report(caf.hash, match(saved))
        with pytest.raises(ValueError):
            service.save(caf, {"selection": selection(caf), "expected": token(saved)})
    service.remove(caf.hash, match(saved))
    assert service.status(caf.hash, selection_context(saved["selection"]))["checkpoint"] is None
    assert caf.original == example()


@pytest.mark.parametrize("limit", ["MAX_CONTEXTS", "MAX_TOTAL_BYTES", "MAX_RECORD_BYTES"])
def test_capacity_refusal_preserves_prior_generation_without_eviction(tmp_path, monkeypatch, limit):
    from bms_tool import caf_creation_drafts as module

    caf = CafArchive(example())
    service = CafCreationDrafts(Store(tmp_path))
    row = selection(caf)
    saved = service.save(caf, {"selection": row, "expected": None})["checkpoint"]
    other = CafArchive(
        packed(caf.xml.replace(b"Preserve this exactly.", b"Another original source."))
    )
    monkeypatch.setattr(module, limit, len(encoded(saved)) if limit == "MAX_RECORD_BYTES" else 1)
    if limit == "MAX_CONTEXTS":
        with pytest.raises(ValueError, match="capacity"):
            service.save(other, {"selection": selection(other), "expected": None})
        assert service.status(caf.hash, selection_context(row))["checkpoint"] == saved
    else:
        with pytest.raises(ValueError, match="capacity|unavailable"):
            service.save(
                caf, {"selection": selection(caf, x="changed" * 100), "expected": token(saved)}
            )
        monkeypatch.undo()
        assert service.status(caf.hash, selection_context(row))["checkpoint"] == saved


def test_original_archive_hash_changes_have_separate_drafts_and_reject_old_tokens(tmp_path):
    caf = CafArchive(example())
    service = CafCreationDrafts(Store(tmp_path))
    first = service.save(caf, {"selection": selection(caf), "expected": None})["checkpoint"]
    other = CafArchive(
        packed(caf.xml.replace(b"Preserve this exactly.", b"Another original source."))
    )
    assert service.status(other.hash, selection_context(first["selection"]))["checkpoint"] is None
    with pytest.raises(Conflict):
        service.restore(other, match(first))
    second = service.save(other, {"selection": selection(other), "expected": None})["checkpoint"]
    assert first["id"] != second["id"]
    assert service.restore(caf, match(first))["checkpoint"] == first


def test_http_restart_status_report_removal_need_no_CAF_cache_and_other_stores_stay_separate(
    tmp_path,
):
    caf = CafArchive(example())
    row = selection(caf)
    base = f"/api/caf/{caf.hash}/creation-draft"
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(base, json={"selection": row, "expected": None}).status_code == 403
        client.headers["X-Studio-Token"] = client.get("/api/session").json()["token"]
        assert (
            client.post("/api/caf", files={"file": ("authored.caf", caf.original)}).status_code
            == 200
        )
        saved = client.post(base, json={"selection": row, "expected": None}).json()["checkpoint"]
        assert client.post(base + "/restore", json=match(saved)).json()["checkpoint"] == saved
        assert client.get(f"/api/caf/{caf.hash}/scalar-draft").json()["checkpoint"] is None
        assert (
            client.get(f"/api/caf/{caf.hash}/wiring-draft", params={"diagram_ref": REF}).json()[
                "checkpoint"
            ]
            is None
        )
        assert client.get("/api/session").json()["field_network_open"] is False
    with TestClient(create_app(tmp_path)) as restarted:
        restarted.headers["X-Studio-Token"] = restarted.get("/api/session").json()["token"]
        assert restarted.get(base, params=selection_context(row)).json()["checkpoint"] == saved
        report = restarted.post(base + "/report", json=match(saved))
        assert report.content == encoded(saved) and report.headers[
            "X-Studio-Artifact-Sha256"
        ] == sha(encoded(saved))
        assert restarted.post(base + "/restore", json=match(saved)).status_code == 422
        assert restarted.request("DELETE", base, json=match(saved)).status_code == 200
        assert restarted.get(base, params=selection_context(row)).json()["checkpoint"] is None
