"""Portable comparison evidence preserves original files and grants no authority."""

import copy
import io
import json
import stat
import struct
import zipfile

import pytest
from bms_tool import native_default_batch_evidence as module
from bms_tool.application_store import encoded
from bms_tool.moi_identity import seal, sha
from bms_tool.native_default_batch_evidence import NativeDefaultBatchEvidence
from bms_tool.native_default_batch_result_match import NativeDefaultBatchResultMatch
from fastapi.responses import JSONResponse

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_batch_result_match import comparison_source
from .test_native_default_transfer import real_slot


async def evidence_source(link, kind="valid"):
    peer, _, _, native, target = link
    receipt, args = await comparison_source(
        link,
        recovery=kind == "recovery",
        historical=kind == "historical",
        current_routed=kind == "routed",
    )
    if kind == "same-capture":
        snapshot, _ = native.storage.load(receipt["intent"]["backup_id"])
        args.update(capture_id=snapshot["id"], snapshot_sha256=snapshot["evidence_sha256"])
    elif kind in ("different", "reencoded"):
        if kind == "different":
            real_slot(peer.files, 17, struct.pack(">f", 19))
        else:
            raw = bytearray(peer.files[3])
            raw[4:8] = (1234).to_bytes(4, "little")
            peer.files[3] = bytes(raw)
        current = await native.capture(**target, operation_id="capture-evidence-bundle-source")
        snapshot, _ = native.storage.load(current["id"])
        args.update(capture_id=current["id"], snapshot_sha256=snapshot["evidence_sha256"])
    report = NativeDefaultBatchResultMatch(native.default_batch_recovery.records).compare(args)
    return receipt, args | {"comparison_sha256": report["evidence_sha256"]}, report


@pytest.mark.parametrize(
    "kind",
    [
        "valid",
        "historical",
        "recovery",
        "different",
        "routed",
        "same-capture",
        "reencoded",
    ],
)
async def test_actual_bundle_preserves_files_proof_report_and_manifest_without_actions(
    native_link, monkeypatch, kind
):
    peer, _, _, native, _ = native_link
    receipt, args, report = await evidence_source(native_link, kind)
    before = copy.deepcopy(peer.events)
    original_receipt = copy.deepcopy(native.storage.receipt(args["receipt_id"]))
    plans = copy.deepcopy(native.plans)
    captured = {}
    original_export = native.storage.export

    def observe(identifier):
        raw = original_export(identifier)
        captured[identifier] = raw
        return raw

    monkeypatch.setattr(native.storage, "export", observe)
    raw, metadata = NativeDefaultBatchEvidence(native.default_batch_recovery.records).export(args)
    assert metadata["bundle_sha256"] == sha(raw) and metadata["bytes"] == len(raw)
    assert metadata["capture_count"] == (1 if kind == "same-capture" else 2)
    assert metadata["member_count"] == metadata["capture_count"] + 4
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.testzip() is None
        manifest_bytes = archive.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        assert metadata["manifest_sha256"] == sha(manifest_bytes)
        assert manifest["evidence_sha256"] == seal(
            {k: v for k, v in manifest.items() if k != "evidence_sha256"}
        )
        assert set(archive.namelist()) == {"manifest.json", *manifest["members"]}
        for name, detail in manifest["members"].items():
            content = archive.read(name)
            assert detail == {"bytes": len(content), "sha256": sha(content)}
        assert archive.read("intent.json") == encoded(receipt["intent"])
        assert archive.read("comparison.json") == JSONResponse(report).body
        proof = json.loads(archive.read("proof.json"))
        assert proof["evidence_sha256"] == report["verified_proof"]["sha256"]
        assert (
            seal({k: v for k, v in proof.items() if k != "evidence_sha256"})
            == proof["evidence_sha256"]
        )
        for identifier, snapshot_sha256 in manifest["captures"].items():
            payload = archive.read(f"captures/{identifier}.zip")
            assert payload == captured[identifier]
            snapshot, files = native.storage.load(identifier)
            assert snapshot["evidence_sha256"] == snapshot_sha256
            with zipfile.ZipFile(io.BytesIO(payload)) as nested:
                assert nested.read("manifest.json") == encoded(snapshot)
                assert all(
                    nested.read(f"file-{number}.bin") == data for number, data in files.items()
                )
        assert manifest["read_only"] and all(
            manifest[k] is False
            for k in (
                "controller_queries",
                "field_actions",
                "can_apply",
                "field_transfer_enabled",
                "current_device_verified",
                "credentials_restored",
                "reviews_restored",
                "complete_controller_backup",
                "complete_journal",
            )
        )
    assert peer.events == before and native.plans == plans
    assert native.storage.receipt(args["receipt_id"]) == original_receipt


async def test_old_comparison_hash_refuses_before_archive_generation(native_link, monkeypatch):
    peer, _, _, native, _ = native_link
    _, args, _ = await evidence_source(native_link)
    monkeypatch.setattr(
        native.storage, "export", lambda *a: pytest.fail("Unexpected archive generation")
    )
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError, match="comparison changed"):
        NativeDefaultBatchEvidence(native.default_batch_recovery.records).export(
            args | {"comparison_sha256": "a" * 64}
        )
    assert peer.events == before


@pytest.mark.parametrize("fault", ["intent-sha", "intent-body", "proof-sha", "proof-body"])
async def test_changed_intent_or_proof_refuses_before_archives(native_link, monkeypatch, fault):
    peer, _, _, native, _ = native_link
    _, args, _ = await evidence_source(native_link)
    original = native.storage.receipt
    calls = 0

    def changing(identifier, **kwargs):
        nonlocal calls
        calls += 1
        receipt = copy.deepcopy(original(identifier, **kwargs))
        if calls == 2:
            if fault == "intent-sha":
                receipt["intent"]["evidence_sha256"] = "a" * 64
            elif fault == "intent-body":
                receipt["intent"]["new_name"] = "Changed intent"
            elif fault == "proof-sha":
                receipt["result"]["evidence_sha256"] = "a" * 64
            else:
                receipt["result"]["unexpected"] = True
        return receipt

    monkeypatch.setattr(native.storage, "receipt", changing)
    monkeypatch.setattr(
        native.storage, "export", lambda *a: pytest.fail("Unexpected archive generation")
    )
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        NativeDefaultBatchEvidence(native.default_batch_recovery.records).export(args)
    assert peer.events == before


async def test_recovery_child_bundle_does_not_reopen_earlier_parent_files(native_link):
    peer, _, _, native, _ = native_link
    receipt, args, _ = await evidence_source(native_link, "recovery")
    parent_backup = receipt["intent"]["recovery_origin"]["original_backup_id"]
    path = native.storage.directory / parent_backup / "file-3.bin"
    raw = path.read_bytes()
    before = copy.deepcopy(peer.events)
    try:
        path.unlink()
        bundle, metadata = NativeDefaultBatchEvidence(native.default_batch_recovery.records).export(
            args
        )
        assert metadata["bundle_sha256"] == sha(bundle)
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            assert f"captures/{parent_backup}.zip" not in archive.namelist()
        assert peer.events == before
    finally:
        path.write_bytes(raw)


@pytest.mark.parametrize(
    "kind", ["original-missing", "original-corrupt", "current-missing", "current-corrupt"]
)
async def test_changed_source_evidence_refuses_without_an_archive(native_link, kind):
    peer, _, _, native, _ = native_link
    _, args, report = await evidence_source(native_link)
    identifier = report["original_backup_id"] if kind.startswith("original") else args["capture_id"]
    path = native.storage.directory / identifier / "file-3.bin"
    raw = path.read_bytes()
    before = copy.deepcopy(peer.events)
    try:
        if kind.endswith("missing"):
            path.unlink()
        else:
            path.write_bytes(b"Changed source evidence")
        with pytest.raises((ValueError, OSError)):
            NativeDefaultBatchEvidence(native.default_batch_recovery.records).export(args)
        assert peer.events == before
    finally:
        path.write_bytes(raw)


@pytest.mark.parametrize(
    "fault", ["file", "manifest", "extra", "missing", "path", "symlink", "comment", "invalid-zip"]
)
async def test_changed_exported_capture_refuses_portable_bundle(native_link, monkeypatch, fault):
    peer, _, _, native, _ = native_link
    _, args, _ = await evidence_source(native_link)
    original = native.storage.export

    def changed(identifier):
        raw = original(identifier)
        if fault == "invalid-zip":
            return b"Not a capture archive"
        with zipfile.ZipFile(io.BytesIO(raw)) as old:
            entries = {name: old.read(name) for name in old.namelist()}
        if fault == "file":
            entries["file-3.bin"] = (
                bytes([entries["file-3.bin"][0] ^ 1]) + entries["file-3.bin"][1:]
            )
        elif fault == "manifest":
            entries["manifest.json"] = b" " + entries["manifest.json"]
        elif fault == "extra":
            entries["unrelated.txt"] = b"Unrelated data"
        elif fault == "missing":
            entries.pop("file-12.bin")
        elif fault == "path":
            entries["../file-3.bin"] = entries.pop("file-3.bin")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            if fault == "comment":
                archive.comment = b"Unexpected data"
            for name, data in entries.items():
                if fault == "symlink" and name == "file-3.bin":
                    info = zipfile.ZipInfo(name)
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, data)
                else:
                    archive.writestr(name, data)
        return output.getvalue()

    monkeypatch.setattr(native.storage, "export", changed)
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        NativeDefaultBatchEvidence(native.default_batch_recovery.records).export(args)
    assert peer.events == before


@pytest.mark.parametrize("limit", ["MAX_BUNDLE", "MAX_CAPTURE", "MAX_COMPARISON", "MAX_PROOF"])
async def test_export_bounds_refuse_without_changing_native_state(native_link, monkeypatch, limit):
    peer, _, _, native, _ = native_link
    _, args, _ = await evidence_source(native_link)
    before = copy.deepcopy(peer.events)
    monkeypatch.setattr(module, limit, 1)
    with pytest.raises(ValueError):
        NativeDefaultBatchEvidence(native.default_batch_recovery.records).export(args)
    assert peer.events == before


async def test_local_http_session_and_no_field_authority(native_link, tmp_path):
    from bms_tool.app import create_app
    from fastapi.testclient import TestClient

    peer, _, _, native, _ = native_link
    _, args, _ = await evidence_source(native_link)
    before = copy.deepcopy(peer.events)
    with TestClient(create_app(tmp_path)) as client:
        path = "/api/bacnet/controller/native-application/default-batch/result/evidence"
        assert client.post(path, json=args).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(path, json=args, headers=headers)
        assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
        metadata = json.loads(response.headers[module.HEADER])
        assert metadata["bundle_sha256"] == sha(response.content)
        for extra in (
            {"token": "x" * 32},
            {"can_apply": True},
            {"operation_id": "no-field-operation"},
        ):
            assert client.post(path, json=args | extra, headers=headers).status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False
    assert peer.events == before
