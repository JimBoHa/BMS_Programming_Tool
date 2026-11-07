"""Portable evidence is checked from bytes without importing storage or field authority."""

import asyncio
import copy
import io
import json
import socket
import stat
import zipfile
from pathlib import Path

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore, encoded
from bms_tool.moi_identity import seal, sha
from bms_tool.native_backup_import import NativeBackupImports
from bms_tool.native_batch_bundle_inspection import MAX_BUNDLE, inspect_bundle
from bms_tool.native_default_batch_evidence import NativeDefaultBatchEvidence
from bms_tool.native_default_batch_result_match import NativeDefaultBatchResultMatch
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_applications import native_link
from .test_native_default_batch_evidence import evidence_source
from .test_native_default_batch_result_match import comparison_source

KINDS = (
    "valid",
    "historical",
    "recovery",
    "different",
    "routed",
    "same-capture",
    "reencoded",
    "recovery-historical",
)


@pytest.fixture(scope="module")
def bundle_samples(tmp_path_factory):
    async def seed():
        result = {}
        for kind in KINDS:
            folder = tmp_path_factory.mktemp("bundle-inspection-" + kind)
            patch = pytest.MonkeyPatch()
            generator = native_link.__wrapped__(folder, patch)
            link = await anext(generator)
            try:
                native = link[3]
                if kind == "recovery-historical":
                    _, args = await comparison_source(link, recovery=True, historical=True)
                    report = NativeDefaultBatchResultMatch(
                        native.default_batch_recovery.records
                    ).compare(args)
                    args["comparison_sha256"] = report["evidence_sha256"]
                else:
                    _, args, report = await evidence_source(link, kind)
                raw, _ = NativeDefaultBatchEvidence(native.default_batch_recovery.records).export(
                    args
                )
                result[kind] = raw, report
            finally:
                await generator.aclose()
                patch.undo()
        return result

    return asyncio.run(seed())


def contents(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def packed(rows, *, mode=zipfile.ZIP_STORED, comment=b"", symlink=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", mode) as archive:
        archive.comment = comment
        for name, value in rows:
            if name == symlink:
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, value)
            else:
                archive.writestr(name, value)
    return out.getvalue()


def reseal(value):
    value["evidence_sha256"] = seal({k: v for k, v in value.items() if k != "evidence_sha256"})
    return encoded(value)


def altered_bundle(raw, fault):
    members = contents(raw)
    manifest = json.loads(members.pop("manifest.json"))
    report = json.loads(members["comparison.json"])
    if fault.startswith("manifest-"):
        key = fault.removeprefix("manifest-")
        if key == "extra":
            manifest["plan_token"] = "untrusted"
        elif key == "scope":
            manifest["scope"] = "Complete backup"
        elif key == "state":
            manifest["comparison_state"] = "different"
        elif key == "capture":
            manifest["current_capture_id"] = "f" * 32
        elif key == "binding":
            manifest["captures"][manifest["current_capture_id"]] = "f" * 64
        elif key == "hash":
            manifest["members"]["proof.json"]["sha256"] = "f" * 64
        elif key == "size":
            manifest["members"]["proof.json"]["bytes"] = True
        else:
            manifest[key] = True
    elif fault.startswith("proof-"):
        proof = json.loads(members["proof.json"])
        key = fault.removeprefix("proof-")
        if key == "receipt":
            proof["receipt_id"] = "f" * 32
        elif key == "intent":
            proof["intent_sha256"] = "f" * 64
        elif key == "time":
            proof["finished_at"] = "bad-time"
        elif key == "native":
            proof["native_sha256"] = "f" * 64
        elif key == "identity":
            proof["readback"]["identity"]["object-name"] = "Other controller"
        elif key == "status":
            proof["status"] = "recovered_original"
        elif key == "operational":
            proof["operational"] = 1
        elif key == "system-status":
            proof["system_status"] = False
        elif key == "selected":
            proof["preservation"]["selected_defaults"][0]["effective_value_verified"] = False
        elif key == "source":
            proof["preservation"]["source_application_sha256"] = "f" * 64
        members["proof.json"] = reseal(proof)
        manifest["verified_proof"].update(
            sha256=proof["evidence_sha256"], time=proof["finished_at"]
        )
        report["verified_proof"] = copy.deepcopy(manifest["verified_proof"])
        members["comparison.json"] = reseal(report)
    elif fault.startswith("comparison-"):
        key = fault.removeprefix("comparison-")
        if key == "state":
            report["state"] = "different"
        elif key == "typed":
            report["selected"][0]["expected"]["bits"] = "00000000"
        elif key == "route":
            report["current_target"]["address"] = "3001:99"
        elif key == "flags":
            report["current_device_verified"] = True
        else:
            report["comparisons"]["selected_values_match"] = False
        members["comparison.json"] = reseal(report)
    elif fault.startswith("intent-"):
        intent = json.loads(members["intent.json"])
        if fault == "intent-compilation":
            intent["compilation"]["changed_count"] += 1
        elif fault == "intent-dispatch":
            intent["may_have_applied"] = False
        else:
            intent["batch_guard"]["fields"][0]["prior_bits"] = "00000000"
        members["intent.json"] = reseal(intent)
        manifest["intent_sha256"] = intent["evidence_sha256"]
        proof = json.loads(members["proof.json"])
        proof["intent_sha256"] = intent["evidence_sha256"]
        members["proof.json"] = reseal(proof)
        manifest["verified_proof"]["sha256"] = proof["evidence_sha256"]
    elif fault == "nested-file":
        name = "captures/" + manifest["current_capture_id"] + ".zip"
        nested = contents(members[name])
        nested["file-3.bin"] = b"not its original bytes"
        members[name] = packed(nested.items(), mode=zipfile.ZIP_DEFLATED)
    elif fault == "nested-path":
        name = "captures/" + manifest["current_capture_id"] + ".zip"
        nested = contents(members[name])
        nested["../file-3.bin"] = nested.pop("file-3.bin")
        members[name] = packed(nested.items(), mode=zipfile.ZIP_DEFLATED)
    elif fault == "nested-duplicate-json":
        name = "captures/" + manifest["current_capture_id"] + ".zip"
        nested = contents(members[name])
        nested["manifest.json"] = b'{"id":"bad",' + nested["manifest.json"][1:]
        members[name] = packed(nested.items(), mode=zipfile.ZIP_DEFLATED)
    if not fault.startswith("manifest-"):
        manifest["members"] = {
            name: {"bytes": len(value), "sha256": sha(value)} for name, value in members.items()
        }
        manifest["comparison_sha256"] = json.loads(members["comparison.json"])["evidence_sha256"]
    return packed([("manifest.json", reseal(manifest)), *sorted(members.items())])


@pytest.mark.parametrize("kind", KINDS)
def test_actual_export_reconstructs_exact_historical_comparison_in_memory(
    bundle_samples, monkeypatch, kind
):
    raw, expected = bundle_samples[kind]

    def forbidden(*args, **kwargs):
        pytest.fail("Inspection must not open storage, files, credentials or sockets")

    for cls, method in (
        (ApplicationStore, "load"),
        (ApplicationStore, "receipt"),
        (ApplicationStore, "intent"),
        (NativeBackupImports, "import_archive"),
        (Store, "connect"),
        (Path, "write_bytes"),
        (Path, "write_text"),
        (socket, "socket"),
    ):
        monkeypatch.setattr(cls, method, forbidden)
    report = inspect_bundle(raw)
    assert encoded(report["comparison"]) == encoded(expected)
    assert report["bundle_sha256"] == sha(raw) and report["bundle_bytes"] == len(raw)
    assert report["capture_count"] == (1 if kind == "same-capture" else 2)
    assert report["internal_consistency_verified"] and report["native_result_reconstructed"]
    assert report["inspection_sha256"] == seal(
        {k: v for k, v in report.items() if k != "inspection_sha256"}
    )
    assert all(
        report[k] is False
        for k in (
            "storage_imported",
            "receipt_restored",
            "vendor_provenance_verified",
            "controller_queries",
            "field_actions",
            "can_apply",
            "current_device_verified",
            "credentials_restored",
            "reviews_restored",
        )
    )
    assert report["members"] == [
        {"name": name, "bytes": len(value), "sha256": sha(value)}
        for name, value in sorted(contents(raw).items())
    ]


FAULTS = (
    "manifest-extra",
    "manifest-scope",
    "manifest-state",
    "manifest-capture",
    "manifest-binding",
    "manifest-hash",
    "manifest-size",
    "manifest-can_apply",
    "manifest-field_actions",
    "manifest-controller_queries",
    "manifest-reviews_restored",
    "manifest-credentials_restored",
    "proof-receipt",
    "proof-intent",
    "proof-time",
    "proof-native",
    "proof-identity",
    "proof-status",
    "proof-operational",
    "proof-system-status",
    "proof-selected",
    "proof-source",
    "comparison-state",
    "comparison-typed",
    "comparison-route",
    "comparison-flags",
    "comparison-result",
    "intent-compilation",
    "intent-dispatch",
    "intent-guard",
    "nested-file",
    "nested-path",
    "nested-duplicate-json",
)


@pytest.mark.parametrize("fault", FAULTS)
def test_resealed_inconsistent_evidence_refuses(bundle_samples, fault):
    with pytest.raises(ValueError):
        inspect_bundle(altered_bundle(bundle_samples["valid"][0], fault))


@pytest.mark.parametrize(
    "fault",
    (
        "prefix",
        "trailing",
        "truncated",
        "crc",
        "local-size",
        "directory",
        "comment",
        "compressed",
        "symlink",
        "path",
        "duplicate",
        "extra",
    ),
)
def test_archive_layout_and_boundaries_refuse(bundle_samples, fault):
    raw = bundle_samples["valid"][0]
    rows = list(contents(raw).items())
    if fault == "prefix":
        raw = b"prefix" + raw
    elif fault == "trailing":
        raw += b"trailing"
    elif fault == "truncated":
        raw = raw[:-1]
    elif fault in ("crc", "local-size", "directory"):
        data = bytearray(raw)
        data[14 if fault == "crc" else 18 if fault == "local-size" else len(data) - 22] ^= 1
        raw = bytes(data)
    elif fault == "comment":
        raw = packed(rows, comment=b"comment")
    elif fault == "compressed":
        raw = packed(rows, mode=zipfile.ZIP_DEFLATED)
    elif fault == "symlink":
        raw = packed(rows, symlink="proof.json")
    elif fault == "path":
        raw = packed([(n if n != "proof.json" else "../proof.json", v) for n, v in rows])
    elif fault == "duplicate":
        with pytest.warns(UserWarning):
            raw = packed([*rows, rows[0]])
    else:
        raw = packed([*rows, ("extra", b"unexpected")])
    with pytest.raises(ValueError):
        inspect_bundle(raw)


@pytest.mark.parametrize("fault", ("duplicate", "nan", "deep", "oversize"))
def test_strict_manifest_json_bounds(bundle_samples, fault):
    rows = contents(bundle_samples["valid"][0])
    if fault == "duplicate":
        rows["manifest.json"] = b'{"profile":"bad",' + rows["manifest.json"][1:]
    elif fault == "nan":
        rows["manifest.json"] = b'{"value":NaN}'
    elif fault == "deep":
        rows["manifest.json"] = b"[" * 66 + b"0" + b"]" * 66
    else:
        rows["manifest.json"] = b" " * (64 * 1024 + 1)
    with pytest.raises(ValueError):
        inspect_bundle(packed(rows.items()))


def test_total_size_and_non_zip_refuse():
    for raw in (b"", b"not a zip", b"x" * (MAX_BUNDLE + 1)):
        with pytest.raises(ValueError):
            inspect_bundle(raw)


def test_large_upload_uses_its_own_bound_without_relaxing_other_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("BMS_STUDIO_DATA", str(tmp_path))
    with TestClient(create_app()) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        path = "/api/bacnet/controller/native-application/default-batch/result/inspect-evidence"
        # Invalid ZIP bytes still reach the bounded parser above the old global
        # request limit, rather than being rejected by an unrelated upload cap.
        raw = b"x" * (9 * 1024 * 1024 + 512 * 1024)
        response = client.post(path, files={"file": ("large.zip", raw)}, headers=headers)
        assert response.status_code == 422 and "ZIP" in response.json()["detail"]
        assert (
            client.post(
                "/api/import", files={"file": ("large.zip", raw)}, headers=headers
            ).status_code
            == 413
        )
        assert (
            client.post(
                path, content=b"x" * (MAX_BUNDLE + 64 * 1024 + 1), headers=headers
            ).status_code
            == 413
        )


def test_api_requires_session_and_keeps_catalog_journal_and_interface_unchanged(
    bundle_samples, tmp_path, monkeypatch
):
    monkeypatch.setenv("BMS_STUDIO_DATA", str(tmp_path))
    app = create_app()
    with TestClient(app) as client:
        path = "/api/bacnet/controller/native-application/default-batch/result/inspect-evidence"
        raw = bundle_samples["valid"][0]
        assert client.post(path, files={"file": ("evidence.zip", raw)}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        before = {
            str(f.relative_to(tmp_path)): f.read_bytes()
            for f in tmp_path.rglob("*")
            if f.is_file() and f.suffix not in ("-shm", "-wal")
        }
        result = client.post(path, files={"file": ("evidence.zip", raw)}, headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["receipt_restored"] is False
        assert (
            client.post(path, files={"file": ("bad.zip", b"bad")}, headers=headers).status_code
            == 422
        )
        after = {
            str(f.relative_to(tmp_path)): f.read_bytes()
            for f in tmp_path.rglob("*")
            if f.is_file() and f.suffix not in ("-shm", "-wal")
        }
        assert before == after
