"""Effective Boolean compilation preserves all other actual saved application values."""

import hashlib
import types

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_boolean_defaults import MoiBooleanDefaults
from bms_tool.moi_effective_boolean import EffectiveBooleanCompiler
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_boolean_compiler import EffectiveBooleanService
from bms_tool.native_boolean_copies import NativeBooleanCopies
from bms_tool.native_signal_compiler import SignalCompilerService
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_boolean_copies import FIRST, SECOND, boolean_files
from .test_native_signal_compiler import inline, retained

BASE = "/api/bacnet/controller/native-application/boolean-default-compiler"


def setup(tmp_path, files=None, **metadata):
    storage = ApplicationStore(Store(tmp_path))
    snapshot = retained(storage, files or boolean_files(), **metadata)
    source = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    return storage, EffectiveBooleanService(NativeBackupRecords(storage)), source


def query(source, *, ref=FIRST, value=False):
    field = next(row for row in source["fields"] if row["ref"] == ref)
    return {
        "capture_id": source["capture_id"],
        "snapshot_sha256": source["snapshot_sha256"],
        "source_sha256": source["source_sha256"],
        "record_ref": ref,
        "encoded_sha256": field["encoded_sha256"],
        "value": value,
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("ref,value", [(FIRST, False), (SECOND, True)])
def test_only_selected_merged_byte_changes_and_all_other_saved_values_survive(
    compressed, extended, ref, value
):
    files = boolean_files(compressed=compressed, extended=extended)
    compiler = EffectiveBooleanCompiler(files)
    fields = {row["ref"]: row for row in compiler.fields()}
    assert fields[FIRST]["archive_value"] is False and fields[FIRST]["effective_value"] is True
    assert fields[SECOND]["archive_value"] is True and fields[SECOND]["effective_value"] is False
    output, report = compiler.compile(
        record_ref=ref, encoded_sha256=fields[ref]["encoded_sha256"], value=value
    )
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    expected = bytearray(MoiIdentity(merged).data)
    expected[report["selected_edit"]["native_byte_offset"]] = 0x11 if value else 0x10
    actual = MoiIdentity(output)
    assert actual.data == bytes(expected)
    assert actual.reader.scalar(actual.reader.records[ref], 3113) is value
    other = SECOND if ref == FIRST else FIRST
    assert (
        actual.reader.scalar(actual.reader.records[other], 3113) is fields[other]["effective_value"]
    )
    assert actual.reader.scalar(actual.root, 900) == 3.5
    assert actual.reader.scalar(actual.reader.records["controller/signal-10"], 3113) == 42
    assert report["other_merged_bytes_preserved"] and report["saved_settings_merged"]
    assert not report["controller_write"] and not report["field_transfer_enabled"]


def test_boolean_only_signal_source_does_not_require_real_default_support(tmp_path):
    storage, service, source = setup(tmp_path, boolean_files(real_signals=False))
    assert len(service.source(source)["fields"]) == 2
    assert SignalCompilerService(storage).source(source["capture_id"])["fields"] == []
    report = NativeBackupRecords(storage).capabilities(source)
    rows = {row["id"]: row for row in report["operations"]}
    assert rows["effective-boolean-compile"]["status"] == "source-qualified"
    assert rows["effective-default-compile"]["status"] == "unsupported-source"
    assert rows["default-transfer"]["status"] == "unsupported-source"


def test_unchanged_effective_default_still_merges_other_saved_settings():
    files = boolean_files()
    compiler = EffectiveBooleanCompiler(files)
    field = next(row for row in compiler.fields() if row["ref"] == FIRST)
    output, report = compiler.compile(
        record_ref=FIRST, encoded_sha256=field["encoded_sha256"], value=True
    )
    assert not report["selected_edit"]["changed"]
    assert output == compiler.merged and output != files[3]


@pytest.mark.parametrize("fault", ["unknown", "crc", "name", "references"])
def test_unknown_or_reassigned_saved_values_never_compile(tmp_path, fault):
    files = boolean_files()
    if fault == "unknown":
        files[11], files[12] = b"Unknown selectors", b"Opaque values"
    elif fault == "crc":
        files[12] = bytes([files[12][0] ^ 1]) + files[12][1:]
    elif fault == "name":
        files[11] += inline((8 << 22) | 5136, 470, 2390, "Another Device")
    else:
        files[11] += inline((5 << 22) | 20, 530, 32527, SECOND) + inline(
            (5 << 22) | 21, 531, 32527, FIRST
        )
    storage, service, source = setup(tmp_path, files)
    with pytest.raises(ValueError):
        service.source(source)
    # Archive-only copying retains its separate, weaker local qualification.
    editor = MoiBooleanDefaults(files[3])
    _, prop = editor.candidates[FIRST]
    _, reviewed = NativeBooleanCopies(NativeBackupRecords(storage)).preview(
        source
        | {
            "source_sha256": editor.editor.source_sha256,
            "record_ref": FIRST,
            "encoded_sha256": prop["encoded_sha256"],
            "value": True,
        }
    )
    assert not reviewed["field_transfer_enabled"] and not storage.receipts()


@pytest.mark.parametrize("fault", ["unverified", "vendor", "device", "name", "model"])
def test_effective_compilation_recomputes_retained_identity(tmp_path, fault):
    metadata = (
        {"source_identity_matches": False}
        if fault == "unverified"
        else {"device": "device,5137"}
        if fault == "device"
        else {
            "identity": {
                "vendor-identifier": 99 if fault == "vendor" else 5,
                "object-name": "Mismatch" if fault == "name" else "Authored controller",
                "model-name": "Mismatch" if fault == "model" else "UNLISTED-MODEL",
            }
        }
    )
    _, service, source = setup(tmp_path, **metadata)
    with pytest.raises(ValueError):
        service.source(source)


def test_source_request_and_review_bind_original_archive_effective_encoding_and_value(tmp_path):
    storage, service, source = setup(tmp_path)
    data = service.source(source)
    body = query(data)
    output, review = service.preview(body)
    assert service.export(body | {"review_sha256": review["review_sha256"]})[0] == output
    original = MoiBooleanDefaults(storage.load(source["capture_id"])[1][3])
    old = original.candidates[FIRST][1]["encoded_sha256"]
    for altered in [
        {"value": True},
        {"encoded_sha256": old},
        {"record_ref": SECOND},
        {"snapshot_sha256": "0" * 64},
        {"source_sha256": "1" * 64},
    ]:
        with pytest.raises(ValueError):
            service.export(body | {"review_sha256": review["review_sha256"]} | altered)
    assert not storage.receipts()


def test_local_http_uses_strict_booleans_exact_headers_and_no_field_interface(tmp_path):
    app = create_app(tmp_path)
    snapshot = retained(app.state.native_applications.storage, boolean_files())
    source = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE + "/source", json=source).status_code == 403
        response = client.post(BASE + "/source", json=source, headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()
        body = query(data)
        assert data["saved_settings_merged"] and not data["current_identity_verified"]
        for bad in [0, 1, "false", None]:
            assert (
                client.post(
                    BASE + "/preview", json=body | {"value": bad}, headers=headers
                ).status_code
                == 422
            )
        review = client.post(BASE + "/preview", json=body, headers=headers).json()
        exported = client.post(
            BASE + "/export",
            json=body | {"review_sha256": review["review_sha256"]},
            headers=headers,
        )
        assert exported.status_code == 200, exported.text
        assert (
            hashlib.sha256(exported.content).hexdigest()
            == exported.headers["X-Studio-Artifact-Sha256"]
            == review["output_sha256"]
        )
        assert exported.headers["X-Studio-Snapshot-Sha256"] == source["snapshot_sha256"]
        assert not client.get("/api/session").json()["field_network_open"]


async def test_actual_native_backup_can_compile_effective_boolean_after_disconnect(native_link):
    peer, bacnet, _, native, target = native_link
    peer.files = boolean_files()
    seen = []
    original = peer.indication

    async def watch(self, apdu):
        seen.append(type(apdu).__name__)
        await original(apdu)

    peer.indication = types.MethodType(watch, peer)
    captured = await native.capture(**target, operation_id="capture-for-effective-Boolean")
    snapshot, _ = native.storage.load(captured["id"])
    await bacnet.disconnect()
    before = list(seen)
    service = EffectiveBooleanService(NativeBackupRecords(native.storage))
    source = service.source(
        {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    )
    output, review = service.preview(query(source))
    assert service.export(query(source) | {"review_sha256": review["review_sha256"]})[0] == output
    assert seen == before and not native.storage.receipts()
