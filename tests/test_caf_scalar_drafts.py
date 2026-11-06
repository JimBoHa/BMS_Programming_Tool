"""Exact unfinished scalar checkpoints recover local work, not export or field authority."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from bms_tool import caf_scalar_drafts as module
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.caf_scalar_drafts import FLAGS, CafScalarDrafts, encoded
from bms_tool.moi_identity import seal, sha
from bms_tool.storage import Conflict, Store
from fastapi.testclient import TestClient

from .test_caf_enum_defaults import REF as ENUM_REF
from .test_caf_enum_defaults import enum_caf
from .test_formats_caf import make_caf


def source():
    return CafArchive(enum_caf()[0])


def proposals(value="1e"):
    return [
        {"ref": "controller/real", "property": "3113", "old": "23.5", "value": value},
        {"ref": ENUM_REF, "property": "3113", "old": "1", "value": "unfinished enum"},
        {"ref": "controller/real", "property": "28", "old": "blue", "value": "  keep\n\t🙂  "},
    ]


def expected(saved):
    return {"id": saved["id"], "revision": saved["revision"]}


def save(service, caf=None, changes=None, prior=None):
    return service.save(
        caf or source(),
        {"changes": changes or proposals(), "expected": expected(prior) if prior else None},
    )["checkpoint"]


@pytest.mark.parametrize(
    "raw", ["-", "1e", "", " ", "\t\n", "NaN", "Infinity", "0000003", "-0", "🙂\x00"]
)
def test_unfinished_raw_text_is_exact_and_never_parsed_or_exported(tmp_path, monkeypatch, raw):
    caf = source()
    service = CafScalarDrafts(Store(tmp_path))
    changes = proposals(raw)
    changes[1]["value"] = raw
    changes[2]["value"] = raw

    def forbidden(*args, **kwargs):
        pytest.fail("Saving/restoring unfinished text invoked CAF export")

    monkeypatch.setattr(CafArchive, "patch", forbidden)
    original = caf.original
    saved = save(service, caf, changes)
    assert saved["changes"] == changes and saved["revision"] == 1
    assert saved["checkpoint_sha256"] == seal(
        {k: v for k, v in saved.items() if k != "checkpoint_sha256"}
    )
    restored = service.restore(caf, {"expected": expected(saved)})
    assert restored["checkpoint"] == saved and restored["source_revalidated"] is True
    assert {key: restored[key] for key in FLAGS} == FLAGS
    assert caf.original == original
    assert len(restored["fields"]) == 3
    assert restored["fields"][0]["property"]["scalar"]["text"] == "23.5"
    enum = restored["fields"][1]
    assert enum["ref"] == ENUM_REF and enum["class_id"] == "528"
    assert enum["property"]["scalar"]["attributes"] == {"set": "state&set"}
    assert enum["property"]["enum_code_copy"]["source_sha256"] == caf.hash
    assert enum["property"]["enum_code_copy"]["record_ref"] == ENUM_REF
    assert enum["property"]["enum_code_copy"]["original_code"] == 1
    assert enum["property"]["enum_code_copy"]["enum_semantics_verified"] is False
    assert set(saved["changes"][1]) == {"ref", "property", "old", "value"}
    restored["checkpoint"]["changes"][0]["value"] = "changed response"
    assert service.status(caf.hash)["checkpoint"] == saved


def test_restart_status_and_guarded_delete_need_no_open_original_caf(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    caf = source()
    saved = save(app.state.caf_scalar_drafts, caf)
    restarted = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Local draft operation attempted field access")

    for name in ("require", "connect", "_read", "disconnect", "release"):
        monkeypatch.setattr(restarted.state.bacnet, name, forbidden)
    monkeypatch.setattr(restarted.state.native_applications.storage, "intent", forbidden)
    base = "/api/caf/" + caf.hash + "/scalar-draft"
    with TestClient(restarted) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        status = client.get(base)
        assert status.status_code == 200 and status.json()["checkpoint"] == saved
        assert status.json()["source_revalidated"] is False
        assert (
            client.post(
                base + "/restore", headers=headers, json={"expected": expected(saved)}
            ).status_code
            == 422
        )
        assert (
            client.post(
                base, headers=headers, json={"expected": expected(saved), "changes": proposals()}
            ).status_code
            == 422
        )
        assert client.request("DELETE", base, json={"expected": expected(saved)}).status_code == 403
        removed = client.request(
            "DELETE", base, headers=headers, json={"expected": expected(saved)}
        )
        assert removed.status_code == 200 and removed.json()["removed"]
        assert client.get(base).json()["checkpoint"] is None
        assert not client.get("/api/session").json()["field_network_open"]


def test_same_original_reopens_and_restores_but_changed_caf_has_independent_context(tmp_path):
    app = create_app(tmp_path)
    caf = source()
    saved = save(app.state.caf_scalar_drafts, caf)
    restarted = create_app(tmp_path)
    changed = CafArchive(enum_caf(text="2")[0])
    with TestClient(restarted) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for archive in (caf, changed):
            upload = client.post(
                "/api/caf", headers=headers, files={"file": ("renamed.caf", archive.original)}
            )
            assert upload.status_code == 200
        base = "/api/caf/" + caf.hash + "/scalar-draft"
        restored = client.post(
            base + "/restore", headers=headers, json={"expected": expected(saved)}
        )
        assert restored.status_code == 200 and restored.json()["checkpoint"] == saved
        foreign = "/api/caf/" + changed.hash + "/scalar-draft"
        assert client.get(foreign).json()["checkpoint"] is None
        assert (
            client.post(
                foreign + "/restore", headers=headers, json={"expected": expected(saved)}
            ).status_code
            == 409
        )
        assert (
            client.request(
                "DELETE", foreign, headers=headers, json={"expected": expected(saved)}
            ).status_code
            == 409
        )
        assert client.get(base).json()["checkpoint"] == saved


@pytest.mark.parametrize(
    "fault",
    [
        "object",
        "property",
        "old",
        "duplicate",
        "enum-metadata",
        "property-number",
        "value-number",
        "unknown",
        "empty",
        "too-many",
        "too-long-value",
        "too-long-ref",
        "noncanonical-property",
    ],
)
def test_invalid_checkpoint_requests_preserve_existing_work(tmp_path, fault):
    service, caf = CafScalarDrafts(Store(tmp_path)), source()
    previous = save(service, caf)
    changes = proposals()
    if fault == "object":
        changes[0]["ref"] = "missing"
    elif fault == "property":
        changes[0]["property"] = "65000"
    elif fault == "old":
        changes[0]["old"] = "wrong"
    elif fault == "duplicate":
        changes.append(copy.deepcopy(changes[0]))
    elif fault == "enum-metadata":
        changes[1]["enum_code_copy"] = {"eligible": True}
    elif fault == "property-number":
        changes[0]["property"] = 3113
    elif fault == "value-number":
        changes[0]["value"] = 1
    elif fault == "unknown":
        changes[0]["extra"] = "unknown"
    elif fault == "empty":
        changes = []
    elif fault == "too-many":
        changes = [changes[0]] * 1001
    elif fault == "too-long-value":
        changes[0]["value"] = "x" * 8193
    elif fault == "too-long-ref":
        changes[0]["ref"] = "x" * 513
    else:
        changes[0]["property"] = "03113"
    with pytest.raises(ValueError):
        service.save(caf, {"changes": changes, "expected": expected(previous)})
    assert service.status(caf.hash)["checkpoint"] == previous


@pytest.mark.parametrize(
    "options", [{"cid": "527"}, {"attributes": " future='1'"}, {"simulation": True}]
)
def test_unsupported_original_enum_schema_cannot_be_saved_by_forged_eligibility(tmp_path, options):
    caf = CafArchive(enum_caf(**options)[0])
    service = CafScalarDrafts(Store(tmp_path))
    with pytest.raises(ValueError):
        save(service, caf, [{"ref": ENUM_REF, "property": "3113", "old": "1", "value": "-"}])
    assert service.status(caf.hash)["checkpoint"] is None


def test_two_tabs_conflict_and_delete_recreate_does_not_revive_stale_generation(tmp_path):
    caf, service = source(), CafScalarDrafts(Store(tmp_path))
    first = save(service, caf)
    second = save(service, caf, proposals("later"), first)
    assert second["id"] == first["id"] and second["revision"] == 2
    assert second["created_at"] == first["created_at"]
    for action in (
        lambda: save(service, caf, proposals("stale"), first),
        lambda: service.restore(caf, {"expected": expected(first)}),
        lambda: service.remove(caf.hash, {"expected": expected(first)}),
        lambda: save(service, caf),
    ):
        with pytest.raises(Conflict):
            action()
        assert service.status(caf.hash)["checkpoint"] == second
    service.remove(caf.hash, {"expected": expected(second)})
    with pytest.raises(Conflict):
        save(service, caf, prior=second)
    recreated = save(service, caf)
    assert recreated["revision"] == first["revision"] == 1 and recreated["id"] != first["id"]
    for action in (
        lambda: save(service, caf, prior=first),
        lambda: service.restore(caf, {"expected": expected(first)}),
        lambda: service.remove(caf.hash, {"expected": expected(first)}),
    ):
        with pytest.raises(Conflict):
            action()
    assert service.status(caf.hash)["checkpoint"] == recreated


@pytest.mark.parametrize("limit", ["contexts", "bytes", "record"])
def test_capacity_never_evicts_or_overwrites_prior_work_on_failure(tmp_path, monkeypatch, limit):
    caf, service = source(), CafScalarDrafts(Store(tmp_path))
    first = save(service, caf)
    before = service.status(caf.hash)
    if limit == "contexts":
        monkeypatch.setattr(module, "MAX_CONTEXTS", 1)
        other = CafArchive(enum_caf(cid="529")[0])
        with pytest.raises(ValueError, match="capacity"):
            save(service, other)
        assert save(service, caf, prior=first)["revision"] == 2
    else:
        monkeypatch.setattr(
            module,
            "MAX_TOTAL_BYTES" if limit == "bytes" else "MAX_RECORD_BYTES",
            before["capacity"]["bytes"],
        )
        with pytest.raises(ValueError, match="capacity|size limit"):
            save(service, caf, proposals("x" * 8192), first)
        assert service.status(caf.hash)["checkpoint"] == first


def test_concurrent_create_and_update_cas_have_one_winner(tmp_path):
    store, caf = Store(tmp_path), source()
    service = CafScalarDrafts(store)
    barrier = Barrier(4)

    def create(_):
        own = CafScalarDrafts(store)
        barrier.wait()
        try:
            return save(own, caf)
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create, range(4)))
    assert sum(value is not None for value in results) == 1
    first = service.status(caf.hash)["checkpoint"]
    barrier = Barrier(2)

    def update(value):
        barrier.wait()
        try:
            return save(service, caf, proposals(value), first)
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["left", "right"]))
    assert sum(value is not None for value in results) == 1
    assert service.status(caf.hash)["checkpoint"]["revision"] == 2


@pytest.mark.parametrize("limit", ["contexts", "bytes"])
def test_concurrent_different_caf_saves_cannot_overbook_capacity(tmp_path, monkeypatch, limit):
    service = CafScalarDrafts(Store(tmp_path))
    one, two = source(), CafArchive(enum_caf(cid="529")[0])
    sample = save(service, one)
    size = service.status(one.hash)["capacity"]["bytes"]
    service.remove(one.hash, {"expected": expected(sample)})
    monkeypatch.setattr(
        module,
        "MAX_CONTEXTS" if limit == "contexts" else "MAX_TOTAL_BYTES",
        1 if limit == "contexts" else size + 128,
    )
    barrier = Barrier(2)

    def create(caf):
        barrier.wait()
        try:
            return save(service, caf)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, [one, two]))
    assert sum(value is not None for value in results) == 1
    capacity = service.status(one.hash)["capacity"]
    assert capacity["count"] == 1 and capacity["bytes"] <= capacity["byte_limit"]


@pytest.mark.parametrize(
    "fault",
    [
        "bytes",
        "sha",
        "seal",
        "extra",
        "id",
        "caf",
        "revision",
        "typed-revision",
        "recursive",
        "oversized",
    ],
)
def test_corrupt_checkpoint_is_unavailable_and_guarded_remove_remains_local(tmp_path, fault):
    service, caf = CafScalarDrafts(Store(tmp_path)), source()
    saved = save(service, caf)
    with service.store.connect() as db:
        row = db.execute(
            "SELECT * FROM caf_scalar_drafts WHERE caf_sha256=?", (caf.hash,)
        ).fetchone()
        data, raw, digest = json.loads(row["content"]), row["content"], row["sha256"]
        if fault == "bytes":
            raw = b"tampered"
        elif fault == "sha":
            digest = "0" * 64
        elif fault == "recursive":
            raw = b"[" * 3000 + b"0" + b"]" * 3000
            digest = sha(raw)
        elif fault == "oversized":
            raw = b"x" * (module.MAX_RECORD_BYTES + 1)
            digest = sha(raw)
        else:
            if fault == "seal":
                data["checkpoint_sha256"] = "0" * 64
            elif fault == "extra":
                data["export_success_restored"] = True
            elif fault == "id":
                data["id"] = "0" * 32
            elif fault == "caf":
                data["caf_sha256"] = "0" * 64
            elif fault == "revision":
                data["revision"] = 2
            else:
                data["revision"] = True
            if fault != "seal":
                data["checkpoint_sha256"] = seal(
                    {k: v for k, v in data.items() if k != "checkpoint_sha256"}
                )
            raw, digest = encoded(data), sha(encoded(data))
        db.execute(
            "UPDATE caf_scalar_drafts SET content=?,sha256=? WHERE caf_sha256=?",
            (raw, digest, caf.hash),
        )
        if fault == "oversized":
            assert service.row(db, caf.hash)["content"] is None
    status = service.status(caf.hash)
    assert status["checkpoint"]["state"] == "unavailable"
    assert status["checkpoint"]["id"] == saved["id"]
    with pytest.raises(ValueError):
        service.restore(caf, {"expected": expected(saved)})
    with pytest.raises(ValueError):
        save(service, caf, prior=saved)
    assert service.remove(caf.hash, {"expected": expected(saved)})["removed"]
    assert service.status(caf.hash)["checkpoint"] is None


def test_restore_rechecks_actual_source_instead_of_trusting_stored_eligibility(
    tmp_path, monkeypatch
):
    caf, service = source(), CafScalarDrafts(Store(tmp_path))
    saved = save(service, caf)
    monkeypatch.setattr(caf, "_editable", lambda *a, **k: False)
    with pytest.raises(ValueError, match="editable"):
        service.restore(caf, {"expected": expected(saved)})
    assert service.status(caf.hash)["checkpoint"] == saved


def test_restored_valid_proposals_use_unchanged_export_guard_and_same_exact_output(tmp_path):
    caf, service = source(), CafScalarDrafts(Store(tmp_path))
    changes = proposals("72.25")
    changes[1]["value"] = "256"
    changes[2]["value"] = "A & B"
    saved = save(service, caf, changes)
    restored = service.restore(caf, {"expected": expected(saved)})
    expected_output = caf.patch(changes)
    assert caf.patch(restored["checkpoint"]["changes"]) == expected_output
    assert caf.patch([])[0] == caf.original
    invalid = save(service, caf, proposals("-"), saved)
    raw = service.restore(caf, {"expected": expected(invalid)})["checkpoint"]["changes"]
    with pytest.raises(ValueError):
        caf.patch(raw)
    assert service.status(caf.hash)["checkpoint"] == invalid


@pytest.mark.parametrize(
    "changes",
    [
        {"expected": {"id": "a" * 32, "revision": True}},
        {"expected": {"id": "../bad", "revision": 1}},
        {"expected": {}},
        {"can_apply": True},
        {"exported": True},
        {"fields": []},
    ],
)
def test_http_schema_refuses_authority_or_invalid_concurrency_metadata(tmp_path, changes):
    app, caf = create_app(tmp_path), source()
    with TestClient(app) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        client.post("/api/caf", headers=h, files={"file": ("draft.caf", caf.original)})
        base = "/api/caf/" + caf.hash + "/scalar-draft"
        body = {"changes": proposals(), "expected": None}
        assert client.post(base, json=body).status_code == 403
        assert client.post(base, headers=h, json=body | changes).status_code == 422
        assert client.get(base).json()["checkpoint"] is None


@pytest.mark.parametrize("hash_value", ["../draft", "A" * 64, "a" * 63, ""])
def test_source_identifiers_never_become_filesystem_paths(tmp_path, hash_value):
    service = CafScalarDrafts(Store(tmp_path))
    with pytest.raises(ValueError):
        service.status(hash_value)
    with pytest.raises(ValueError):
        service.remove(hash_value, {"expected": {"id": "a" * 32, "revision": 1}})


def test_original_scalar_old_text_cannot_be_silently_normalized(tmp_path):
    caf = CafArchive(make_caf())
    service = CafScalarDrafts(Store(tmp_path))
    change = {"ref": "8-1", "property": "3113", "old": "72.000000", "value": "1e"}
    saved = save(service, caf, [change])
    with pytest.raises(ValueError, match="original text"):
        save(service, caf, [change | {"old": "72"}], saved)
    assert service.restore(caf, {"expected": expected(saved)})["checkpoint"]["changes"] == [change]


def test_ordinary_editable_scalar_without_recorded_class_remains_recoverable(tmp_path):
    original = CafArchive(make_caf())
    caf = CafArchive(make_caf(original.xml.replace(b'classid="194" ', b"")))
    service = CafScalarDrafts(Store(tmp_path))
    change = {"ref": "8-1", "property": "3113", "old": "72.000000", "value": "1e"}
    saved = save(service, caf, [change])
    restored = service.restore(caf, {"expected": expected(saved)})
    assert restored["fields"][0]["class_id"] is None
    assert restored["fields"][0]["property"]["editable"]
    assert "enum_code_copy" not in restored["fields"][0]["property"]


def test_invalid_unicode_request_is_rejected_without_erasing_prior_raw_text(tmp_path):
    service, caf = CafScalarDrafts(Store(tmp_path)), source()
    saved = save(service, caf)
    with pytest.raises(ValueError):
        save(service, caf, proposals("\ud800"), saved)
    assert service.status(caf.hash)["checkpoint"] == saved


def test_restore_rechecks_saved_old_text_even_when_stored_hashes_are_consistent(tmp_path):
    service, caf = CafScalarDrafts(Store(tmp_path)), source()
    saved = save(service, caf)
    changed = copy.deepcopy(saved)
    changed["changes"][0]["old"] = "24"
    changed["checkpoint_sha256"] = seal(
        {k: v for k, v in changed.items() if k != "checkpoint_sha256"}
    )
    raw = encoded(changed)
    with service.store.connect() as db:
        db.execute(
            "UPDATE caf_scalar_drafts SET content=?,sha256=? WHERE caf_sha256=?",
            (raw, sha(raw), caf.hash),
        )
    assert service.status(caf.hash)["checkpoint"] == changed
    with pytest.raises(ValueError, match="original text"):
        service.restore(caf, {"expected": expected(saved)})


def test_concurrent_delete_and_update_cannot_both_mutate_one_revision(tmp_path):
    service, caf = CafScalarDrafts(Store(tmp_path)), source()
    first = save(service, caf)
    barrier = Barrier(2)

    def mutate(operation):
        barrier.wait()
        try:
            if operation == "delete":
                return service.remove(caf.hash, {"expected": expected(first)})
            return save(service, caf, proposals("newer"), first)
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(mutate, ["delete", "update"]))
    assert sum(value is not None for value in results) == 1
    current = service.status(caf.hash)["checkpoint"]
    assert current is None or current["revision"] == 2
