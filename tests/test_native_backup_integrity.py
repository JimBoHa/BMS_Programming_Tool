"""Damaged storage stays inspectable without becoming a usable backup."""

import errno
import os

import pytest
from bms_tool import native_backup_integrity as module
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore, encoded, evidence
from bms_tool.moi_identity import seal, sha
from bms_tool.native_backup_integrity import ENTRY_LIMIT, NativeBackupIntegrity
from bms_tool.native_backup_lifecycle import NativeBackupLifecycle
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_signal_compiler import retained

BASE = "/api/bacnet/controller/native-application/backup-library"


def setup(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    capture = retained(storage)
    return storage, capture, NativeBackupIntegrity(storage)


def request(storage, capture):
    return {
        "capture_id": capture["id"],
        "manifest_sha256": sha((storage.directory / capture["id"] / "manifest.json").read_bytes()),
    }


def verified(report):
    body = {key: value for key, value in report.items() if key != "report_sha256"}
    assert report["report_sha256"] == seal(body)
    assert report["profile"] == "native-backup-integrity/1"
    assert report["read_only"] and not report["storage_mutations"]
    assert not report["controller_queries"] and not report["field_actions"]


def originals(storage):
    return {
        str(p.relative_to(storage.store.directory)): (p.read_bytes(), p.stat().st_mode & 0o777)
        for p in storage.store.directory.rglob("*")
        if p.is_file() and not p.is_symlink()
    }


def test_damaged_and_unpublished_entries_do_not_hide_intact_source_or_read_payloads(
    tmp_path, monkeypatch
):
    storage, capture, service = setup(tmp_path)
    damaged = retained(storage)
    (storage.directory / damaged["id"] / "manifest.json").write_bytes(b"{damaged original")
    partial = "ab" * 16
    (storage.directory / partial).mkdir()
    (storage.directory / partial / "file-3.bin").write_bytes(b"unpublished original")
    (storage.directory / "operator-note.txt").write_text("Never interpret this as a capture")
    before = originals(storage)
    read = module.read_private
    reads = []

    def observe(path, maximum):
        reads.append(path.name)
        assert path.name == "manifest.json", "Inventory read a payload or unrelated entry"
        return read(path, maximum)

    monkeypatch.setattr(module, "read_private", observe)
    result = service.inventory({})
    verified(result)
    rows = {row["entry_name"]: row for row in result["entries"]}
    assert result["scan_complete"] and result["observed_entries"] == 4
    assert rows[capture["id"]]["status"] == "manifest_available"
    assert rows[capture["id"]]["source"]["target"] == capture["target"]
    assert rows[capture["id"]]["snapshot_sha256"] == capture["evidence_sha256"]
    assert rows[damaged["id"]]["status"] == rows[partial]["status"] == "manifest_unavailable"
    assert rows["operator-note.txt"]["capture_id"] is None
    assert rows["operator-note.txt"]["status"] == "unrecognized_entry"
    assert all(row["original_files_checked"] is False for row in rows.values())
    assert len(reads) == 3 and originals(storage) == before
    with pytest.raises(ValueError):
        NativeBackupLifecycle(storage).list({})
    assert storage.load(capture["id"])[0] == capture


def test_explicit_original_check_seals_all_three_observations_without_storage_or_catalog_writes(
    tmp_path, monkeypatch
):
    storage, capture, service = setup(tmp_path)
    before = originals(storage)
    monkeypatch.setattr(
        storage.store, "connect", lambda **kw: pytest.fail("Diagnostic opened the catalog database")
    )
    result = service.check(request(storage, capture))
    verified(result)
    assert result["integrity"] == "matches_manifest" and not result["observation_is_atomic"]
    assert [row["file_id"] for row in result["files"]] == [3, 11, 12]
    for row in result["files"]:
        raw = (storage.directory / capture["id"] / f"file-{row['file_id']}.bin").read_bytes()
        assert row["status"] == "matches"
        assert row["expected_bytes"] == row["observed_bytes"] == len(raw)
        assert row["expected_sha256"] == row["observed_sha256"] == sha(raw)
    assert result["source"]["device"] == capture["device"]
    assert originals(storage) == before


@pytest.mark.parametrize("file_id", [3, 11, 12])
@pytest.mark.parametrize("mutation", ["same_size", "empty", "missing", "oversize"])
def test_mismatch_and_missing_originals_remain_exactly_as_observed(tmp_path, file_id, mutation):
    storage, capture, service = setup(tmp_path)
    path = storage.directory / capture["id"] / f"file-{file_id}.bin"
    if mutation == "missing":
        path.unlink()
    elif mutation == "same_size":
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    else:
        path.write_bytes(b"" if mutation == "empty" else b"x" * (2097152 + 1))
    before = originals(storage)
    result = service.check(request(storage, capture))
    verified(result)
    row = next(row for row in result["files"] if row["file_id"] == file_id)
    unavailable = mutation in ("missing", "oversize")
    assert result["integrity"] == ("incomplete" if unavailable else "mismatch")
    assert row["status"] == ("unavailable" if unavailable else "mismatch")
    assert sum(row["status"] == "matches" for row in result["files"]) == 2
    assert originals(storage) == before
    with pytest.raises(ValueError if mutation in ("same_size", "empty", "oversize") else OSError):
        storage.load(capture["id"])


@pytest.mark.parametrize(
    "case",
    [
        "list",
        "bad_seal",
        "wrong_id",
        "wrong_files",
        "bool_size",
        "large_size",
        "bad_hash",
        "null_files",
    ],
)
def test_malformed_manifest_isolated_and_explicit_check_refused(tmp_path, case):
    storage, capture, service = setup(tmp_path)
    path = storage.directory / capture["id"] / "manifest.json"
    body = {k: v for k, v in capture.items() if k != "evidence_sha256"}
    if case == "list":
        raw = b"[]"
    else:
        if case == "wrong_id":
            body["id"] = "cd" * 16
        if case == "wrong_files":
            body["files"]["9"] = body["files"].pop("12")
        if case == "bool_size":
            body["files"]["3"]["bytes"] = True
        if case == "large_size":
            body["files"]["3"]["bytes"] = 2097153
        if case == "bad_hash":
            body["files"]["3"]["sha256"] = "not-a-hash"
        if case == "null_files":
            body["files"] = None
        row = evidence(body)
        if case == "bad_seal":
            row["evidence_sha256"] = "0" * 64
        raw = encoded(row)
    path.write_bytes(raw)
    (row,) = service.inventory({})["entries"]
    assert row["status"] == "manifest_unavailable" and row["manifest_sha256"] is None
    with pytest.raises(ValueError, match="Original manifest unavailable"):
        service.check(request(storage, capture))
    assert path.read_bytes() == raw


def test_manifest_substitution_before_or_during_check_never_reports_a_match(tmp_path, monkeypatch):
    storage, capture, service = setup(tmp_path)
    proposal = request(storage, capture)
    path = storage.directory / capture["id"] / "manifest.json"
    raw = path.read_bytes()
    path.write_bytes(raw + b"\n")
    with pytest.raises(ValueError, match="manifest changed"):
        service.check(proposal)
    assert path.read_bytes() == raw + b"\n"
    path.write_bytes(raw)
    read = module.read_private

    def replace(path_to_read, maximum):
        value = read(path_to_read, maximum)
        if path_to_read.name == "file-3.bin":
            path.write_bytes(raw + b"\n")
        return value

    monkeypatch.setattr(module, "read_private", replace)
    with pytest.raises(ValueError, match="manifest changed during inspection"):
        service.check(proposal)
    assert path.read_bytes() == raw + b"\n"


def test_page_search_and_bound_include_unpublished_entries_without_changing_capture_capacity(
    tmp_path,
):
    storage = ApplicationStore(Store(tmp_path))
    service = NativeBackupIntegrity(storage)
    for index in range(ENTRY_LIMIT + 1):
        (storage.directory / f"{index:032x}").mkdir()
    result = service.inventory({"limit": 32})
    verified(result)
    assert not result["scan_complete"] and result["observed_entries"] == ENTRY_LIMIT
    assert result["matching_observed_entries"] == ENTRY_LIMIT and len(result["entries"]) == 32
    assert result["has_more"] and all(
        row["status"] == "manifest_unavailable" for row in result["entries"]
    )
    assert service.inventory({"offset": ENTRY_LIMIT})["entries"] == []
    # Publication limits still count complete active captures, not diagnostic rows.
    assert storage.captures() == []
    for index in range(ENTRY_LIMIT + 1):
        (storage.directory / f"{index:032x}").rmdir()
    for index in range(33):
        (storage.directory / f"{index:032x}").mkdir()
    a = service.inventory({})
    b = service.inventory({"offset": 16})
    c = service.inventory({"offset": 32})
    assert a["scan_complete"] and a["has_more"] and b["has_more"] and not c["has_more"]
    assert len({row["entry_name"] for p in (a, b, c) for row in p["entries"]}) == 33
    needle = "00000000000000000000000000000010"
    result = service.inventory({"query": needle})
    assert [row["entry_name"] for row in result["entries"]] == [needle]


@pytest.mark.parametrize("kind", ["capture_link", "manifest_link", "payload_link", "payload_fifo"])
def test_redirected_and_nonregular_evidence_is_refused_without_following_or_blocking(
    tmp_path, kind
):
    if kind == "payload_fifo" and not hasattr(os, "mkfifo"):
        pytest.skip("Unix FIFO creation is not available")
    storage, capture, service = setup(tmp_path)
    proposal = request(storage, capture)
    folder = storage.directory / capture["id"]
    if kind == "capture_link":
        original = tmp_path / "retained-original"
        folder.rename(original)
        folder.symlink_to(original, target_is_directory=True)
    else:
        name = "manifest.json" if kind == "manifest_link" else "file-3.bin"
        path = folder / name
        raw = path.read_bytes()
        path.unlink()
        if kind == "payload_fifo":
            os.mkfifo(path)
        else:
            outside = tmp_path / "outside-original"
            outside.write_bytes(raw)
            path.symlink_to(outside)
    (row,) = service.inventory({})["entries"]
    if kind in ("capture_link", "manifest_link"):
        assert row["status"] == "manifest_unavailable"
        with pytest.raises(ValueError, match="manifest unavailable"):
            service.check(proposal)
    else:
        result = service.check(proposal)
        assert result["integrity"] == "incomplete" and result["files"][0]["status"] == "unavailable"
    if kind != "payload_fifo":
        assert (
            tmp_path / ("retained-original" if kind == "capture_link" else "outside-original")
        ).exists()


def test_root_redirection_and_read_denial_are_explicit(tmp_path, monkeypatch):
    storage, capture, service = setup(tmp_path)
    read = module.read_private

    def denied(path, maximum):
        if path.name == "file-11.bin":
            raise PermissionError(errno.EACCES, "authored denial")
        return read(path, maximum)

    monkeypatch.setattr(module, "read_private", denied)
    result = service.check(request(storage, capture))
    assert result["files"][1]["status"] == "unavailable"
    assert "permissions" in result["files"][1]["problem"]
    original = tmp_path / "original-root"
    storage.directory.rename(original)
    storage.directory.symlink_to(original, target_is_directory=True)
    with pytest.raises(ValueError, match="original storage folder"):
        service.inventory({})


@pytest.mark.parametrize("with_ui", [False, True])
def test_strict_local_http_has_no_controller_or_catalog_effects_even_with_malformed_neighbor(
    tmp_path,
    monkeypatch,
    with_ui,
):
    from bms_tool import app as app_module

    if with_ui and app_module.web_directory() is None:
        pytest.skip("Build the production UI to qualify its existing static fallback.")
    if not with_ui:
        monkeypatch.setattr(app_module, "web_directory", lambda: None)
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    capture = retained(storage)
    bad = storage.directory / ("ef" * 16)
    bad.mkdir()
    (bad / "manifest.json").write_bytes(b"[]")
    with TestClient(app) as client:
        before = originals(storage)
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for endpoint, body in (
            ("storage-inventory", {}),
            ("check-originals", request(storage, capture)),
        ):
            # The existing built-UI fallback yields static 404 for a wrong verb.
            assert client.get(BASE + "/" + endpoint).status_code == (404 if with_ui else 405)
            assert client.post(BASE + "/" + endpoint, json=body).status_code == 403
            assert (
                client.post(
                    BASE + "/" + endpoint, headers=headers, json=body | {"apply": True}
                ).status_code
                == 422
            )
            response = client.post(BASE + "/" + endpoint, headers=headers, json=body)
            assert response.status_code == 200, response.text
            verified(response.json())
        for body in (
            {"offset": True},
            {"limit": 33},
            {"offset": 1153},
            {"query": "x" * 257},
            {"path": "/tmp"},
        ):
            assert (
                client.post(BASE + "/storage-inventory", headers=headers, json=body).status_code
                == 422
            )
        for body in (
            {"capture_id": "../original", "manifest_sha256": "a" * 64},
            {"capture_id": capture["id"], "manifest_sha256": "0" * 64},
        ):
            assert (
                client.post(BASE + "/check-originals", headers=headers, json=body).status_code
                == 422
            )
        assert not client.get("/api/session").json()["field_network_open"]
        assert storage.receipts() == []
    assert originals(storage) == before
