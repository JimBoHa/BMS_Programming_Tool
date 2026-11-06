"""Explicit historical source references retain immutable comparisons without field authority."""

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from bms_tool import caf_source_references as module
from bms_tool.app import create_app
from bms_tool.caf_native_correlation import correlate
from bms_tool.caf_native_file_correlation import file_source
from bms_tool.caf_source_references import FLAGS, REQUEST, CafSourceReferences, digest, encoded
from bms_tool.moi_identity import seal
from fastapi.testclient import TestClient

from .test_caf_native_correlation import ROWS, caf_source
from .test_caf_native_file_correlation import retained_file
from .test_native_signal_compiler import retained


def setup(directory, kind="backup", *, caf=None, different=False):
    app = create_app(directory)
    caf = caf or caf_source()
    target = {"address": "3001:7", "router": "127.0.0.1:47919", "dnet": 3001}
    if kind == "backup":
        snapshot = retained(app.state.native_applications.storage, target=target)
        request = {
            "source_kind": kind,
            "source_sha256": caf.hash,
            "capture_id": snapshot["id"],
            "snapshot_sha256": snapshot["evidence_sha256"],
        }
    else:
        receipt = retained_file(
            app.state.bacnet_files,
            target={"address": "legacy-recorded-address", "device": "device,5136"},
            config={
                "router": target["router"],
                "dnet": 3001,
                "transport": "mstp",
                "serial_port": "/dev/authored-only",
            },
            identity={"model-name": "Another"} if different else None,
        )
        source = file_source(receipt)
        request = {
            "source_kind": kind,
            "source_sha256": caf.hash,
            "capture_id": receipt["id"],
            "receipt_sha256": source["receipt_sha256"],
            "file_sha256": source["sha256"],
        }
    return app, caf, request


def compare(app, caf, request):
    args = {key: value for key, value in request.items() if key != "source_kind"} | {
        "query": "",
        "offset": 0,
        "limit": 128,
    }
    return (
        correlate(caf, app.state.native_backup_records, args)
        if request["source_kind"] == "backup"
        else app.state.caf_source_references.native_files.compare(caf, args)
    )


def forbid_field(app, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Reference operation attempted a controller operation")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)


@pytest.mark.parametrize("kind", ["backup", "file"])
def test_saved_reference_is_server_recomputed_original_bytes_and_keeps_exact_route(
    tmp_path, monkeypatch, kind
):
    app, caf, request = setup(tmp_path, kind)
    forbid_field(app, monkeypatch)
    service = app.state.caf_source_references
    before_audit = app.state.store.audit()
    expected = encoded(compare(app, caf, request))
    saved = service.save(caf, request)
    assert saved["created"] and not saved["deduplicated"]
    item = saved["reference"]
    assert item["source_kind"] == kind and item["caf_sha256"] == caf.hash
    assert item["source"]["target"]["router"] == "127.0.0.1:47919"
    assert item["source"]["target"]["dnet"] == 3001
    assert item["source"]["target"]["address"] == (
        "3001:7" if kind == "backup" else "legacy-recorded-address"
    )
    assert item["classification"] == "recorded-identities-equal"
    assert {key: item[key] for key in FLAGS} == FLAGS
    assert service.report(caf.hash, item["id"]) == expected
    assert item["report_sha256"] == digest(expected)
    assert item["comparison_report_sha256"] == json.loads(expected)["report_sha256"]
    duplicate = service.save(caf, request)
    assert duplicate["reference"] == item and duplicate["deduplicated"] and not duplicate["created"]
    listing = service.list(caf.hash)
    assert listing["references"] == [item] and listing["capacity"]["count"] == 1
    assert app.state.store.audit() == before_audit
    assert not app.state.native_applications.plans


@pytest.mark.parametrize("kind", ["backup", "file"])
@pytest.mark.parametrize("fault", ["missing", "tampered"])
def test_restart_list_export_remove_need_neither_open_caf_nor_available_sources(
    tmp_path, monkeypatch, kind, fault
):
    app, caf, request = setup(tmp_path, kind)
    item = app.state.caf_source_references.save(caf, request)["reference"]
    original = app.state.caf_source_references.report(caf.hash, item["id"])
    source = (
        app.state.native_applications.storage.directory / request["capture_id"]
        if kind == "backup"
        else app.state.bacnet_files.directory / (request["capture_id"] + ".capture")
    )
    if fault == "missing":
        shutil.rmtree(source) if source.is_dir() else source.unlink()
    else:
        (source / "file-3.bin" if source.is_dir() else source).write_bytes(b"changed source")
    restarted = create_app(tmp_path)
    forbid_field(restarted, monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("Saved reference attempted source revalidation")

    monkeypatch.setattr(restarted.state.native_backup_records, "load", forbidden)
    monkeypatch.setattr(restarted.state.bacnet_files, "capture_data", forbidden)
    monkeypatch.setattr(restarted.state.caf_source_references.native_files, "compare", forbidden)
    base = "/api/caf/" + caf.hash + "/source-references"
    with TestClient(restarted) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        listed = client.get(base)
        assert listed.status_code == 200 and listed.json()["references"] == [item]
        report = client.get(base + "/" + item["id"] + "/report")
        assert report.status_code == 200 and report.content == original
        assert report.headers["X-Studio-Artifact-Sha256"] == digest(original)
        assert (
            client.post(base, headers=headers, json=request).status_code == 422
        )  # Original CAF is not open.
        assert client.delete(base + "/" + item["id"]).status_code == 403
        removed = client.delete(base + "/" + item["id"], headers=headers)
        assert removed.status_code == 200 and removed.json()["removed"]
        assert client.get(base).json()["references"] == []
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize("kind", ["backup", "file"])
def test_same_hash_reopen_restores_reference_but_changed_caf_never_inherits_it(tmp_path, kind):
    app, caf, request = setup(tmp_path, kind)
    item = app.state.caf_source_references.save(caf, request)["reference"]
    changed = caf_source(name="Changed original CAF")
    assert changed.hash != caf.hash
    restarted = create_app(tmp_path)
    with TestClient(restarted) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for archive, expected in ((caf, [item]), (changed, [])):
            upload = client.post(
                "/api/caf", headers=headers, files={"file": ("renamed.caf", archive.original)}
            )
            assert upload.status_code == 200
            assert (
                client.get("/api/caf/" + archive.hash + "/source-references").json()["references"]
                == expected
            )
        with pytest.raises(ValueError):
            restarted.state.caf_source_references.report(changed.hash, item["id"])
        assert not restarted.state.caf_source_references.remove(changed.hash, item["id"])["removed"]
        assert restarted.state.caf_source_references.list(caf.hash)["references"] == [item]


@pytest.mark.parametrize("kind", ["backup", "file"])
def test_full_counts_cover_all_records_while_original_details_are_first128_only(tmp_path, kind):
    caf = caf_source(rows=ROWS + [(f"controller/extra-{i}", 526, i + 100) for i in range(140)])
    app, _, request = setup(tmp_path, kind, caf=caf)
    service = app.state.caf_source_references
    item = service.save(caf, request)["reference"]
    report = json.loads(service.report(caf.hash, item["id"]))
    assert item["classification"] == "recorded-differences"
    assert item["coverage"]["union_references"] == 148
    assert item["coverage"]["record_status_counts"] == {"same-record-identity": 8, "caf-only": 140}
    assert item["pagination"] == {
        "query": "",
        "offset": 0,
        "limit": 128,
        "total_matches": 148,
        "next_offset": 128,
        "records_retained": 128,
    }
    assert len(report["records"]) == 128 and report["total_matches"] == 148
    assert report["request"]["query"] == "" and report["request"]["offset"] == 0


def test_identity_disagreement_stays_incomplete_and_does_not_gain_authority(tmp_path):
    app, caf, request = setup(tmp_path, "file", different=True)
    item = app.state.caf_source_references.save(caf, request)["reference"]
    assert item["classification"] == "identity-incomplete"
    assert {key: item[key] for key in FLAGS} == FLAGS


@pytest.mark.parametrize(
    "change",
    [
        {"report": {}},
        {"query": "filtered"},
        {"offset": 1},
        {"limit": 1},
        {"source_kind": "other"},
        {"source_sha256": True},
        {"capture_id": "../source"},
        {"snapshot_sha256": "bad"},
        {"can_apply": True},
        {"target": {}},
    ],
)
def test_http_save_accepts_only_explicit_strict_source_selection(tmp_path, change):
    app, caf, request = setup(tmp_path)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        client.post("/api/caf", headers=headers, files={"file": ("test.caf", caf.original)})
        base = "/api/caf/" + caf.hash + "/source-references"
        assert client.post(base, json=request).status_code == 403
        assert client.post(base, headers=headers, json=request | change).status_code == 422
        assert client.get(base).json()["references"] == []


@pytest.mark.parametrize(
    "kind,key",
    [
        ("backup", "source_sha256"),
        ("backup", "snapshot_sha256"),
        ("file", "source_sha256"),
        ("file", "receipt_sha256"),
        ("file", "file_sha256"),
    ],
)
def test_changed_source_hashes_are_rejected_without_persisting_reference(tmp_path, kind, key):
    app, caf, request = setup(tmp_path, kind)
    with pytest.raises(ValueError):
        app.state.caf_source_references.save(caf, request | {key: "0" * 64})
    assert app.state.caf_source_references.list(caf.hash)["references"] == []


def test_source_families_have_separate_immutable_references(tmp_path):
    app, caf, backup = setup(tmp_path)
    _, _, file = setup(tmp_path, "file")
    service = app.state.caf_source_references
    first = service.save(caf, backup)["reference"]
    second = service.save(caf, file)["reference"]
    assert first["id"] != second["id"] and first["source_kind"] != second["source_kind"]
    assert len(service.list(caf.hash)["references"]) == 2


@pytest.mark.parametrize("limit", ["rows", "bytes"])
def test_duplicate_at_full_capacity_preserves_original_timestamp_and_never_evicts(
    tmp_path, monkeypatch, limit
):
    app, caf, request = setup(tmp_path)
    service = app.state.caf_source_references
    first = service.save(caf, request)["reference"]
    capacity = service.list(caf.hash)["capacity"]
    monkeypatch.setattr(
        module,
        "MAX_REFERENCES" if limit == "rows" else "MAX_TOTAL_BYTES",
        1 if limit == "rows" else capacity["bytes"],
    )
    duplicate = service.save(caf, request)
    assert duplicate["deduplicated"] and duplicate["reference"] == first
    other = retained(app.state.native_applications.storage)
    with pytest.raises(ValueError, match="capacity"):
        service.save(
            caf, request | {"capture_id": other["id"], "snapshot_sha256": other["evidence_sha256"]}
        )
    assert service.list(caf.hash)["references"] == [first]
    assert service.remove(caf.hash, first["id"])["removed"]
    assert service.save(caf, request)["created"]


def test_concurrent_duplicate_saves_create_one_reference(tmp_path):
    app, caf, request = setup(tmp_path)
    barrier = Barrier(6)

    def run(_):
        service = CafSourceReferences(
            app.state.store,
            app.state.native_backup_records,
            app.state.caf_source_references.native_files,
        )
        barrier.wait()
        return service.save(caf, request)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, range(6)))
    assert sum(result["created"] for result in results) == 1
    assert len({result["reference"]["id"] for result in results}) == 1
    assert app.state.caf_source_references.list(caf.hash)["capacity"]["count"] == 1


def test_two_distinct_concurrent_saves_cannot_overbook_last_capacity_slot(tmp_path, monkeypatch):
    app, caf, request = setup(tmp_path)
    other = retained(app.state.native_applications.storage)
    requests = [
        request,
        request | {"capture_id": other["id"], "snapshot_sha256": other["evidence_sha256"]},
    ]
    monkeypatch.setattr(module, "MAX_REFERENCES", 1)
    barrier = Barrier(2)

    def run(body):
        barrier.wait()
        try:
            return app.state.caf_source_references.save(caf, body)
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, requests))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert any(isinstance(result, str) and "capacity" in result for result in results)
    assert app.state.caf_source_references.list(caf.hash)["capacity"]["count"] == 1


@pytest.mark.parametrize(
    "fault",
    [
        "report-bytes",
        "summary-bytes",
        "report-sha",
        "summary-sha",
        "classification",
        "route",
        "coverage",
        "inner-seal",
        "false-authority",
        "caf-binding",
        "source-binding",
        "dedupe-key",
    ],
)
def test_corrupt_row_is_isolated_download_refuses_and_explicit_removal_frees_capacity(
    tmp_path, fault
):
    app, caf, request = setup(tmp_path)
    service = app.state.caf_source_references
    item = service.save(caf, request)["reference"]
    _, _, other_request = setup(tmp_path, "file")
    other = service.save(caf, other_request)["reference"]
    with app.state.store.connect() as db:
        row = dict(
            db.execute("SELECT * FROM caf_source_references WHERE id=?", (item["id"],)).fetchone()
        )
        report, summary = json.loads(row["report"]), json.loads(row["summary"])
        if fault == "report-bytes":
            row["report"] = b"tampered"
        elif fault == "summary-bytes":
            row["summary"] = b"tampered"
        elif fault == "report-sha":
            row["report_sha256"] = "0" * 64
        elif fault == "summary-sha":
            row["summary_sha256"] = "0" * 64
        elif fault in ("classification", "route", "coverage"):
            if fault == "classification":
                summary["classification"] = "identity-incomplete"
            elif fault == "route":
                summary["source"]["target"]["address"] = "other"
            else:
                summary["coverage"]["union_references"] += 1
            row["summary"] = encoded(summary)
            row["summary_sha256"] = digest(row["summary"])
        elif fault in ("inner-seal", "false-authority", "caf-binding", "source-binding"):
            if fault == "inner-seal":
                report["report_sha256"] = "0" * 64
            elif fault == "false-authority":
                report["application_association_granted"] = True
            elif fault == "caf-binding":
                report["caf"]["sha256"] = "0" * 64
            else:
                report["native_backup"]["capture_id"] = "0" * 32
            if fault != "inner-seal":
                report["report_sha256"] = seal(
                    {key: value for key, value in report.items() if key != "report_sha256"}
                )
            row["report"] = encoded(report)
            row["report_sha256"] = digest(row["report"])
        else:
            row["dedupe_sha256"] = "0" * 64
        db.execute(
            "UPDATE caf_source_references SET report=?,report_sha256=?,summary=?,summary_sha256=?,dedupe_sha256=? WHERE id=?",
            (
                row["report"],
                row["report_sha256"],
                row["summary"],
                row["summary_sha256"],
                row["dedupe_sha256"],
                item["id"],
            ),
        )
    rows = {row["id"]: row for row in service.list(caf.hash)["references"]}
    assert rows[other["id"]] == other and rows[item["id"]]["state"] == "unavailable"
    with pytest.raises(ValueError):
        service.report(caf.hash, item["id"])
    assert service.remove(caf.hash, item["id"])["removed"]
    assert service.list(caf.hash)["references"] == [other]


def test_report_size_budget_rejects_before_insert(tmp_path, monkeypatch):
    app, caf, request = setup(tmp_path)
    monkeypatch.setattr(module, "MAX_REPORT_BYTES", 128)
    with pytest.raises(ValueError, match="size limit"):
        app.state.caf_source_references.save(caf, request)
    assert app.state.caf_source_references.list(caf.hash)["references"] == []


@pytest.mark.parametrize("value", [True, "../source", "a" * 63, "A" * 64, ""])
def test_hash_and_reference_paths_never_become_filesystem_paths(tmp_path, value):
    app, caf, request = setup(tmp_path)
    service = app.state.caf_source_references
    item = service.save(caf, request)["reference"]
    with pytest.raises(ValueError):
        service.list(value)
    with pytest.raises(ValueError):
        service.report(caf.hash, value)
    with pytest.raises(ValueError):
        service.remove(value, item["id"])


def test_discriminator_never_coerces_or_accepts_other_family_fields():
    backup = {
        "source_kind": "backup",
        "source_sha256": "a" * 64,
        "capture_id": "b" * 32,
        "snapshot_sha256": "c" * 64,
    }
    with pytest.raises(ValueError):
        REQUEST.validate_python(backup | {"receipt_sha256": "d" * 64})
    with pytest.raises(ValueError):
        REQUEST.validate_python(backup | {"source_kind": "file"})


@pytest.mark.parametrize("kind", ["backup", "file"])
def test_failed_new_save_after_source_tamper_keeps_original_reference(tmp_path, kind):
    app, caf, request = setup(tmp_path, kind)
    service = app.state.caf_source_references
    original = service.save(caf, request)["reference"]
    raw = service.report(caf.hash, original["id"])
    path = (
        app.state.native_applications.storage.directory / request["capture_id"] / "file-3.bin"
        if kind == "backup"
        else app.state.bacnet_files.directory / (request["capture_id"] + ".capture")
    )
    path.write_bytes(b"changed")
    with pytest.raises((ValueError, OSError)):
        service.save(caf, request)
    assert service.list(caf.hash)["references"] == [original]
    assert service.report(caf.hash, original["id"]) == raw


@pytest.mark.parametrize("fault", ["recursive-report", "oversized-report", "oversized-summary"])
def test_malformed_stored_artifact_is_bounded_and_removable(tmp_path, fault):
    app, caf, request = setup(tmp_path)
    service = app.state.caf_source_references
    item = service.save(caf, request)["reference"]
    column = "summary" if fault == "oversized-summary" else "report"
    data = (
        (b"[" * 3000 + b"0" + b"]" * 3000)
        if fault == "recursive-report"
        else b"x" * (module.MAX_REPORT_BYTES + 1)
    )
    with app.state.store.connect() as db:
        db.execute(
            f"UPDATE caf_source_references SET {column}=?,{column}_sha256=? WHERE id=?",
            (data, digest(data), item["id"]),
        )
        row = db.execute(
            f"SELECT {service.bounded_columns()} FROM caf_source_references WHERE id=?",
            (item["id"],),
        ).fetchone()
        if fault.startswith("oversized"):
            assert row[column] is None
    assert service.list(caf.hash)["references"][0]["state"] == "unavailable"
    with pytest.raises(ValueError):
        service.report(caf.hash, item["id"])
    assert service.remove(caf.hash, item["id"])["removed"]


def test_concurrent_distinct_saves_obey_combined_byte_capacity(tmp_path, monkeypatch):
    app, caf, first = setup(tmp_path)
    other = retained(app.state.native_applications.storage)
    second = first | {"capture_id": other["id"], "snapshot_sha256": other["evidence_sha256"]}
    service = app.state.caf_source_references
    sample = service.save(caf, first)["reference"]
    size = service.list(caf.hash)["capacity"]["bytes"]
    service.remove(caf.hash, sample["id"])
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", size + 512)
    barrier = Barrier(2)

    def save(request):
        barrier.wait()
        try:
            return service.save(caf, request)
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [first, second]))
    assert sum(isinstance(result, dict) for result in results) == 1
    capacity = service.list(caf.hash)["capacity"]
    assert capacity["count"] == 1 and capacity["bytes"] <= capacity["byte_limit"]
