"""Literal Boolean tags, exact other-byte preservation and local-only copies."""

import gzip
import hashlib
import struct
import types

import pytest
from bacpypes3.primitivedata import Boolean, CharacterString, ObjectIdentifier
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_boolean_defaults import MoiBooleanDefaults
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_boolean_copies import NativeBooleanCopies
from bms_tool.native_signal_compiler import SignalCompilerService
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_moi_parameters import parameters_source
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_signal_compiler import retained, signal_files, slot

BASE = "/api/bacnet/controller/native-application/inspection/boolean-default"
FIRST, SECOND = "controller/boolean-20", "controller/boolean-21"


def boolean_files(*, compressed=True, extended=False, real_signals=True):
    files = (
        signal_files(compressed=False, extended=extended)
        if real_signals
        else dict(zip((3, 11, 12), parameters_source(compressed=False), strict=True))
    )
    data = bytearray(files[3])
    data[10:14] = (int.from_bytes(data[10:14], "little") + 2).to_bytes(4, "little")
    for index, cid, value in [(20, 530, False), (21, 531, True)]:
        record = native_record(
            cid,
            index,
            [
                (32527, encoded(CharacterString(f"controller/boolean-{index}"))),
                (75, encoded(ObjectIdentifier((5, index)))),
                (2390, encoded(CharacterString(f"Authored Boolean {index}"))),
                (3113, encoded(Boolean(value))),
                (65000, b"\x4e\x21\x07\x4f"),
            ],
        )
        data.extend(
            b"\0\0" + struct.pack("<I", len(record) + 6)
            if extended
            else struct.pack("<H", len(record) + 2)
        )
        data.extend(record)
        files[11] += slot((5 << 22) | index, cid, 3113, 1, len(files[12]))
        saved = bytes([int(not value)])
        files[12] += saved + bytes([header_crc(saved) ^ 255])
    files[3] = gzip.compress(bytes(data), mtime=0) if compressed else bytes(data)
    return files


def query(editor, *, ref=FIRST, value=True):
    _, prop = editor.candidates[ref]
    return dict(
        source_sha256=editor.editor.source_sha256,
        record_ref=ref,
        encoded_sha256=prop["encoded_sha256"],
        value=value,
    )


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("ref,value", [(FIRST, True), (SECOND, False)])
def test_only_one_literal_boolean_tag_changes(compressed, extended, ref, value):
    files = boolean_files(compressed=compressed, extended=extended)
    editor = MoiBooleanDefaults(files[3])
    assert len(editor.candidates) == 2
    q = query(editor, ref=ref, value=value)
    plan = editor.preview(**q)
    output, report = editor.export(**q, plan_sha256=plan["plan_sha256"])
    actual = MoiIdentity(output)
    expected = bytearray(editor.editor.data)
    expected[plan["native_byte_offset"]] = 0x11 if value else 0x10
    assert actual.data == bytes(expected) and len(actual.records) == 11
    assert actual.summary()["instance"] == 5136
    assert type(actual.reader.scalar(actual.reader.records[ref], 3113)) is bool
    assert actual.reader.scalar(actual.reader.records[ref], 3113) is value
    assert not report["saved_settings_merged"] and not report["controller_write"]
    assert hashlib.sha256(output).hexdigest() == report["output_sha256"]
    if compressed:
        assert output[:10] == files[3][:10] and gzip.decompress(output) == bytes(expected)


@pytest.mark.parametrize("ref,value", [(FIRST, False), (SECOND, True)])
def test_noop_compressed_copy_is_byte_exact_and_saved_values_remain_separate(ref, value):
    files = boolean_files()
    editor = MoiBooleanDefaults(files[3])
    q = query(editor, ref=ref, value=value)
    plan = editor.preview(**q)
    output, report = editor.export(**q, plan_sha256=plan["plan_sha256"])
    assert output == files[3] and not report["changed"]
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    actual = MoiIdentity(merged)
    assert actual.reader.scalar(actual.reader.records[ref], 3113) is not value


@pytest.mark.parametrize("value", [0, 1, "true", "false", None, [], {}])
def test_boolean_values_are_never_coerced(value):
    editor = MoiBooleanDefaults(boolean_files()[3])
    with pytest.raises(ValueError, match="explicit Boolean"):
        editor.preview(**query(editor, value=value))


@pytest.mark.parametrize(
    "changed",
    [
        {"source_sha256": "0" * 64},
        {"encoded_sha256": "1" * 64},
        {"record_ref": "controller/signal-10"},
        {"record_ref": "controller"},
    ],
)
def test_source_property_class_and_review_guards(changed):
    editor = MoiBooleanDefaults(boolean_files()[3])
    with pytest.raises(ValueError):
        editor.preview(**(query(editor) | changed))
    q = query(editor)
    plan = editor.preview(**q)
    with pytest.raises(ValueError, match="review changed"):
        editor.export(**(q | {"value": False}), plan_sha256=plan["plan_sha256"])


@pytest.mark.parametrize(
    "fault", ["other-class", "other-property", "noncanonical", "duplicate", "trailing"]
)
def test_unsupported_fields_and_ambiguous_archives_never_become_boolean_edits(fault):
    files = boolean_files(compressed=False)
    editor = MoiIdentity(files[3])
    data = bytearray(editor.data)
    record = editor.reader.records[FIRST]
    prop = record["properties"][3113]
    if fault == "other-class":
        # Preserve frame width while making the actual record a different class.
        data[record["offset"] : record["offset"] + 2] = (526).to_bytes(2, "little")
    elif fault == "other-property":
        marker = b"\x0a\x0c\x29\x2e\x10\x2f"
        assert marker in data
        data = data.replace(marker, b"\x0a\x0c\x2a\x2e\x10\x2f", 1)
    elif fault == "noncanonical":
        data[prop["value_start_offset"]] = 0x12
    elif fault == "duplicate":
        raw = bytes(data[record["offset"] : record["end_offset"]])
        data[10:14] = (12).to_bytes(4, "little")
        data.extend(struct.pack("<H", len(raw) + 2) + raw)
    else:
        data.extend(b"trailing")
    try:
        checked = MoiBooleanDefaults(bytes(data))
    except ValueError:
        return
    assert FIRST not in checked.candidates


@pytest.mark.parametrize(
    "unknown_saved,unverified", [(False, False), (True, False), (False, True), (True, True)]
)
def test_original_archive_copy_needs_no_saved_schema_and_changes_no_retained_file(
    tmp_path, unknown_saved, unverified
):
    storage = ApplicationStore(Store(tmp_path))
    files = boolean_files()
    if unknown_saved:
        files[11], files[12] = b"Unknown saved schema", b"Opaque saved values"
    capture = retained(storage, files, source_identity_matches=not unverified)
    service = NativeBooleanCopies(NativeBackupRecords(storage))
    body = {
        "capture_id": capture["id"],
        "snapshot_sha256": capture["evidence_sha256"],
        **query(MoiBooleanDefaults(files[3])),
    }
    output, review = service.preview(body)
    assert service.export(body | {"review_sha256": review["review_sha256"]})[0] == output
    for changed in [
        {"value": False},
        {"snapshot_sha256": "0" * 64},
        {"source_sha256": "1" * 64},
        {"record_ref": SECOND},
    ]:
        with pytest.raises(ValueError):
            service.export(body | {"review_sha256": review["review_sha256"]} | changed)
    assert storage.load(capture["id"])[1] == files and not storage.receipts()


def test_http_admission_strict_values_exact_headers_and_all_original_file_hashes(tmp_path):
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    files = boolean_files()
    capture = retained(storage, files)
    body = {
        "capture_id": capture["id"],
        "snapshot_sha256": capture["evidence_sha256"],
        **query(MoiBooleanDefaults(files[3])),
    }
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE + "/preview", json=body).status_code == 403
        for bad in [0, 1, "true", None]:
            assert (
                client.post(
                    BASE + "/preview", json=body | {"value": bad}, headers=headers
                ).status_code
                == 422
            )
        assert (
            client.post(
                BASE + "/preview", json=body | {"address": "127.0.0.1:1"}, headers=headers
            ).status_code
            == 422
        )
        response = client.post(BASE + "/preview", json=body, headers=headers)
        assert response.status_code == 200, response.text
        review = response.json()
        assert not review["controller_write"] and not review["field_transfer_enabled"]
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
        assert exported.headers["X-Studio-Snapshot-Sha256"] == capture["evidence_sha256"]
        assert not client.get("/api/session").json()["field_network_open"]
        (storage.directory / capture["id"] / "file-12.bin").write_bytes(b"changed")
        assert (
            client.post(
                BASE + "/export",
                json=body | {"review_sha256": review["review_sha256"]},
                headers=headers,
            ).status_code
            == 422
        )


def test_boolean_copy_capability_does_not_expand_real_effective_compilation_or_transfer(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    snapshot = retained(storage, boolean_files())
    report = NativeBackupRecords(storage).capabilities(
        {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    )
    rows = {row["id"]: row for row in report["operations"]}
    assert report["capability_profile"] == "native-backup-operation-capabilities/3"
    assert report["qualification"]["archive_boolean_default_count"] == 2
    assert rows["boolean-default-copy"]["status"] == "source-qualified"
    assert "no Boolean field transfer" in rows["boolean-default-copy"]["next_step"]
    compiler = SignalCompilerService(storage).source(snapshot["id"])
    assert len(compiler["fields"]) == 2
    assert FIRST not in {field["ref"] for field in compiler["fields"]}


async def test_actual_native_capture_then_disconnected_copy_has_zero_wire_actions(native_link):
    peer, bacnet, _, native, target = native_link
    peer.files = boolean_files()
    seen = []
    original = peer.indication

    async def watch(self, apdu):
        seen.append(type(apdu).__name__)
        await original(apdu)

    peer.indication = types.MethodType(watch, peer)
    capture = await native.capture(**target, operation_id="capture-for-Boolean-copy")
    snapshot, files = native.storage.load(capture["id"])
    await bacnet.disconnect()
    before = list(seen)
    service = NativeBooleanCopies(NativeBackupRecords(native.storage))
    body = {
        "capture_id": snapshot["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
        **query(MoiBooleanDefaults(files[3])),
    }
    output, review = service.preview(body)
    assert service.export(body | {"review_sha256": review["review_sha256"]})[0] == output
    assert (
        "ReinitializeDeviceRequest" in before and seen == before and not native.storage.receipts()
    )
