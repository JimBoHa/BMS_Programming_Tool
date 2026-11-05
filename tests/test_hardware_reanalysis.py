"""Saved source reanalysis preserves old evidence, verifies bytes and stays disconnected."""

import copy
import hashlib

import pytest
from bms_tool.app import create_app
from bms_tool.hardware_reanalysis import PROFILE, reanalyze_archive
from bms_tool.hardware_workbench import digest
from fastapi.testclient import TestClient

from .test_hardware_survey import authored_archive


def seed(app):
    w = app.state.hardware_workbench
    raw = authored_archive(root_input_ref=True)
    parent = w.import_archive(
        raw,
        "old-hardware.moi",
        origin={
            "kind": "saved-bacnet-file",
            "capture_id": "a" * 32,
            "receipt": {"target": {"address": "127.0.0.1:47809", "device": "device,123"}},
        },
    )
    # Reproduce older cached inference while preserving the exact original bytes.
    parent = copy.deepcopy(parent)
    p = next(p for p in parent["inputs"] if p["object"] == "analog-input,56")
    p["host"] = {"kind": "local-configured", "sa_mac": None}
    p["errors"] = []
    parent["inventory"]["complete"] = True
    w._write("archive", parent["id"], parent)
    return w, raw, parent


def test_new_analysis_uses_source_not_cached_host_claim_and_retains_parent_after_restart(
    tmp_path, monkeypatch
):
    app = create_app(tmp_path)
    w, raw, parent = seed(app)

    def forbidden(*a, **k):
        pytest.fail("Saved archive reanalysis used field or native compilation")

    for name in ("require", "connect", "disconnect", "release", "_read"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    oldpath = w._path("archive", parent["id"])
    oldbytes = oldpath.read_bytes()
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        route = "/api/bacnet/hardware/archives/" + parent["id"] + "/reanalyze"
        body = {"source_sha256": parent["source"]["sha256"]}
        assert client.post(route, json=body).status_code == 403
        r = client.post(route, json=body, headers=headers)
        assert r.status_code == 200, r.text
        child = r.json()
        assert child["id"] != parent["id"] and child["source"] == parent["source"]
        assert (
            next(p for p in child["inputs"] if p["object"] == "analog-input,56")["host"]["kind"]
            == "unknown"
        )
        assert not child["inventory"]["complete"] and all(
            c["status"] == "unverified" for c in child["candidates"]
        )
        origin = child["origin"]
        assert origin == {
            "kind": "saved-archive-reanalysis",
            "profile": PROFILE,
            "parent_archive_id": parent["id"],
            "parent_source_sha256": hashlib.sha256(raw).hexdigest(),
            "parent_evidence_sha256": digest(parent),
            "parent_origin": parent["origin"],
            "controller_queries": False,
            "controller_writes": False,
            "current_controller_identity_verified": False,
        }
        assert oldpath.read_bytes() == oldbytes and w.archive(parent["id"]) == parent
        assert not client.get("/api/session").json()["field_network_open"]
    with TestClient(create_app(tmp_path)) as client:
        for value in (parent, child):
            assert client.get("/api/bacnet/hardware/archives/" + value["id"]).json() == value
            response = client.get(
                "/api/bacnet/hardware/archives/" + value["id"] + "/export?format=source"
            )
            assert response.status_code == 200 and response.content == raw


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "missing",
        "symlink",
        "directory",
        "changed",
        "size",
        "metadata-size",
        "metadata-hash",
        "open-swap",
        "retention",
        "storage",
    ],
)
def test_failed_reanalysis_keeps_parent_and_creates_no_partial_child(tmp_path, monkeypatch, fault):
    app = create_app(tmp_path)
    w, raw, parent = seed(app)
    key = parent["id"]
    path = w.directory / ("source-" + key + ".bin")
    expected = parent["source"]["sha256"]
    if fault == "hash":
        expected = "0" * 64
    if fault == "missing":
        path.unlink()
    if fault == "symlink":
        path.unlink()
        outside = tmp_path / "outside.moi"
        outside.write_bytes(raw)
        path.symlink_to(outside)
    if fault == "directory":
        path.unlink()
        path.mkdir()
    if fault == "changed":
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    if fault == "size":
        path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    if fault == "metadata-size":
        parent["source"]["bytes"] = False
        w._write("archive", key, parent)
    if fault == "metadata-hash":
        parent["source"]["sha256"] = "0" * 64
        w._write("archive", key, parent)
    if fault == "open-swap":
        import bms_tool.hardware_reanalysis as module

        original = module.os.open

        def swapped(path, *args):
            replacement = w.directory / "replacement.bin"
            replacement.write_bytes(raw)
            replacement.replace(path)
            return original(path, *args)

        monkeypatch.setattr(module.os, "open", swapped)
    if fault in ("retention", "storage"):
        import bms_tool.hardware_workbench as module

        monkeypatch.setattr(module, "MAX_ARCHIVES" if fault == "retention" else "MAX_STORAGE", 1)
    before = {
        p.name: p.read_bytes() for p in w.directory.iterdir() if p.is_file() and not p.is_symlink()
    }
    with pytest.raises(ValueError):
        reanalyze_archive(w, key, expected)
    after = {
        p.name: p.read_bytes() for p in w.directory.iterdir() if p.is_file() and not p.is_symlink()
    }
    assert before == after
    assert not list(w.directory.glob(".pending-*")) and not list(
        w.directory.glob(".pending-source-*")
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"source_sha256": True},
        {"source_sha256": "bad"},
        {"source_sha256": "a" * 64, "controller_write": True},
    ],
)
def test_api_requires_exact_hash_without_write_options(tmp_path, body):
    app = create_app(tmp_path)
    _, _, parent = seed(app)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        r = client.post(
            "/api/bacnet/hardware/archives/" + parent["id"] + "/reanalyze",
            json=body,
            headers=headers,
        )
        assert r.status_code == 422 and not client.get("/api/session").json()["field_network_open"]
