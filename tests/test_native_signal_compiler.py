"""Literal native records and saved-slot bytes qualify one narrow compiler."""

import gzip
import hashlib
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Real
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_signal_compiler import EffectiveSignalCompiler, SignalCompilerService
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_moi_parameters import parameters_source
from .test_native_applications import native_link as native_link  # noqa: F401

BASE = "/api/bacnet/controller/native-application/signal-default"
FIRST, SECOND = "controller/signal-10", "controller/signal-11"


def slot(oid, cid, pid, kind, position):
    row = (
        oid.to_bytes(4, "big")
        + pid.to_bytes(2, "big")
        + bytes([0x6F, kind])
        + cid.to_bytes(2, "big")
        + position.to_bytes(2, "big")
        + b"\x12\x34"
    )
    return (len(row) + 2).to_bytes(2, "big") + row


def inline(oid, cid, pid, text):
    value = b"\x1e" + encoded(CharacterString(text)) + b"\x1f" + b"\0" * 5
    row = (
        oid.to_bytes(4, "big")
        + pid.to_bytes(2, "big")
        + b"\x4f\x07"
        + cid.to_bytes(2, "big")
        + value
        + b"\x56\x78"
    )
    return (len(row) + 2).to_bytes(2, "big") + row


def signal_files(*, compressed=True, extended=False):
    archive, static, dynamic = parameters_source(compressed=False)
    data = bytearray(archive)
    data[10:14] = (int.from_bytes(data[10:14], "little") + 2).to_bytes(4, "little")
    for index, (cid, default, saved) in enumerate([(526, 23.5, 42.0), (527, 5.0, 7.0)], 10):
        record = native_record(
            cid,
            index,
            [
                (32527, encoded(CharacterString(f"controller/signal-{index}"))),
                (75, encoded(ObjectIdentifier((2, index)))),
                (2390, encoded(CharacterString(f"Authored signal {index}"))),
                (3113, encoded(Real(default))),
                (65000, b"\x4e\x21\x03\x4f"),
            ],
        )
        data.extend(
            b"\0\0" + struct.pack("<I", len(record) + 6)
            if extended
            else struct.pack("<H", len(record) + 2)
        )
        data.extend(record)
        static += slot((2 << 22) | index, cid, 3113, 4, len(dynamic))
        payload = struct.pack(">f", saved)
        dynamic += payload + bytes([header_crc(payload) ^ 255])
    return {
        3: gzip.compress(bytes(data), mtime=0) if compressed else bytes(data),
        11: static,
        12: dynamic,
    }


def retained(storage, files=None, **metadata):
    return storage.save(
        {
            "target": {"address": "127.0.0.1:47819", "router": None, "dnet": None},
            "device": "device,5136",
            "identity": {
                "object-name": "Authored controller",
                "model-name": "UNLISTED-MODEL",
                "vendor-identifier": 5,
            },
            "source_identity_matches": True,
            "connector_config": {"local_address": "127.0.0.1:47818"},
            "read_only": False,
            **metadata,
        },
        files or signal_files(),
    )


def query(source, ref=FIRST, value="0.1"):
    field = next(row for row in source["fields"] if row["ref"] == ref)
    return {
        "capture_id": source["capture_id"],
        "snapshot_sha256": source["snapshot_sha256"],
        "record_ref": ref,
        "encoded_sha256": field["encoded_sha256"],
        "value_text": value,
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("ref", [FIRST, SECOND])
def test_saved_merge_precedes_exact_four_byte_edit_and_all_other_settings_survive(
    compressed, extended, ref
):
    files = signal_files(compressed=compressed, extended=extended)
    original = dict(files)
    compiler = EffectiveSignalCompiler(files)
    fields = {row["ref"]: row for row in compiler.fields()}
    assert fields[FIRST]["archive_value"] == 23.5 and fields[FIRST]["effective_value"] == 42.0
    assert fields[SECOND]["archive_value"] == 5.0 and fields[SECOND]["effective_value"] == 7.0
    assert all(row["saved_value_differs"] for row in fields.values())
    output, report = compiler.compile(
        record_ref=ref, encoded_sha256=fields[ref]["encoded_sha256"], value_text="0.1"
    )
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    before, after = MoiIdentity(merged), MoiIdentity(output)
    offset = report["selected_edit"]["native_byte_offset"]
    expected = bytearray(before.data)
    expected[offset : offset + 4] = encoded(Real(0.1))[1:]
    assert after.data == bytes(expected)
    assert report["selected_edit"]["after_bits"] == "3dcccccd"
    assert (
        report["selected_edit"]["stored_value"] == struct.unpack(">f", bytes.fromhex("3dcccccd"))[0]
    )
    assert (
        after.reader.scalar(after.root, 900) == 3.5
        and after.reader.scalar(after.root, 904) == "saved"
    )
    other = SECOND if ref == FIRST else FIRST
    assert (
        after.reader.scalar(after.reader.records[other], 3113) == fields[other]["effective_value"]
    )
    assert files == original and report["other_merged_bytes_preserved"]
    assert report["controller_write"] is False and report["field_transfer_enabled"] is False


def test_unchanged_selected_value_still_contains_the_other_saved_settings():
    compiler = EffectiveSignalCompiler(signal_files())
    first = next(row for row in compiler.fields() if row["ref"] == FIRST)
    output, report = compiler.compile(
        record_ref=FIRST, encoded_sha256=first["encoded_sha256"], value_text="42"
    )
    assert not report["selected_field_changed"] and report["parameter_merge"]["changed_parameters"]
    assert output == compiler.merged and output != compiler.archive.editor.source


@pytest.mark.parametrize("fault", ["saved-name", "swapped-references", "bad-crc", "missing-file"])
def test_ambiguous_saved_source_or_identity_never_compiles(fault):
    files = signal_files()
    if fault == "saved-name":
        files[11] += inline((8 << 22) | 5136, 470, 2390, "Another controller")
    elif fault == "swapped-references":
        files[11] += inline((2 << 22) | 10, 526, 32527, SECOND) + inline(
            (2 << 22) | 11, 527, 32527, FIRST
        )
    elif fault == "bad-crc":
        files[12] = bytes([files[12][0] ^ 1]) + files[12][1:]
    else:
        files.pop(11)
    with pytest.raises(ValueError):
        EffectiveSignalCompiler(files)


@pytest.mark.parametrize(
    "value", ["NaN", "1e39", "1e-50", "", "null", "+1e99999999999999999999999"]
)
def test_bad_values_have_no_output(value):
    compiler = EffectiveSignalCompiler(signal_files())
    first = compiler.fields()[0]
    with pytest.raises(ValueError):
        compiler.compile(
            record_ref=first["ref"], encoded_sha256=first["encoded_sha256"], value_text=value
        )


def test_source_reviewer_and_export_are_snapshot_property_and_text_bound(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    snapshot = retained(storage)
    service = SignalCompilerService(storage)
    source = service.source(snapshot["id"])
    q = query(source)
    output, review = service.preview(q)
    assert service.export(q | {"review_sha256": review["review_sha256"]})[0] == output
    for changed in [
        {"value_text": "0.2"},
        {"encoded_sha256": "0" * 64},
        {"snapshot_sha256": "1" * 64},
        {"record_ref": SECOND},
    ]:
        with pytest.raises(ValueError):
            service.export(q | {"review_sha256": review["review_sha256"]} | changed)
    assert len(storage.captures()) == 1 and not storage.receipts()


@pytest.mark.parametrize("bad", ["vendor", "unverified", "identity"])
def test_unqualified_retained_snapshots_are_not_compiler_sources(tmp_path, bad):
    storage = ApplicationStore(Store(tmp_path))
    metadata = (
        {"source_identity_matches": False}
        if bad == "unverified"
        else {
            "identity": {
                "vendor-identifier": 999 if bad == "vendor" else 5,
                "object-name": "Mismatch",
                "model-name": "UNLISTED-MODEL",
            }
        }
    )
    snapshot = retained(storage, **metadata)
    with pytest.raises(ValueError):
        SignalCompilerService(storage).source(snapshot["id"])


def test_offline_production_api_exports_real_compiled_bytes_and_does_not_open_network(tmp_path):
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    snapshot = retained(storage)
    originals = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (storage.directory / snapshot["id"]).iterdir()
    }
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.get(BASE + "/sources").json()["sources"][0]["id"] == snapshot["id"]
        assert client.post(BASE + "/source", json={"capture_id": snapshot["id"]}).status_code == 403
        source = client.post(
            BASE + "/source", headers=headers, json={"capture_id": snapshot["id"]}
        ).json()
        q = query(source)
        preview = client.post(BASE + "/preview", headers=headers, json=q)
        assert preview.status_code == 200, preview.text
        review = preview.json()
        exported = client.post(
            BASE + "/export", headers=headers, json=q | {"review_sha256": review["review_sha256"]}
        )
        assert exported.status_code == 200, exported.text
        assert (
            hashlib.sha256(exported.content).hexdigest()
            == exported.headers["X-Studio-Artifact-Sha256"]
            == review["compilation"]["compiled_sha256"]
        )
        parsed = MoiIdentity(exported.content)
        assert (
            parsed.reader.scalar(parsed.reader.records[FIRST], 3113)
            == struct.unpack(">f", bytes.fromhex("3dcccccd"))[0]
        )
        assert client.get("/api/session").json()["field_network_open"] is False
        assert not storage.receipts()
    assert originals == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (storage.directory / snapshot["id"]).iterdir()
    }


async def test_actual_native_backup_is_an_offline_compiler_source_without_more_wire_requests(
    native_link,
):
    peer, connector, _store, native, target = native_link
    peer.files = signal_files()
    requests = []
    original = peer.indication

    async def observed(apdu):
        requests.append(type(apdu).__name__)
        return await original(apdu)

    peer.indication = observed
    snapshot = await native.capture(**target, operation_id="native-default-source")
    assert snapshot["source_identity_matches"] and not snapshot["read_only"]
    assert "ReinitializeDeviceRequest" in requests and "AtomicReadFileRequest" in requests
    before = list(requests)
    connector.close()
    compiler = SignalCompilerService(native.storage)
    source = compiler.source(snapshot["id"])
    output, review = compiler.preview(query(source))
    assert compiler.export(query(source) | {"review_sha256": review["review_sha256"]})[0] == output
    assert requests == before and not any(event[0] == "write" for event in peer.events)
    assert not native.storage.receipts()


@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_retained_file_substitution_cannot_compile_even_with_original_review(tmp_path, file_id):
    storage = ApplicationStore(Store(tmp_path))
    snapshot = retained(storage)
    service = SignalCompilerService(storage)
    request = query(service.source(snapshot["id"]))
    _, review = service.preview(request)
    path = storage.directory / snapshot["id"] / f"file-{file_id}.bin"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="integrity"):
        service.export(request | {"review_sha256": review["review_sha256"]})


def test_missing_or_redirected_snapshot_is_visible_and_never_creates_source_files(tmp_path):
    storage = ApplicationStore(Store(tmp_path))
    service = SignalCompilerService(storage)
    with pytest.raises(ValueError, match="unavailable"):
        service.source("a" * 32)
    original = retained(storage)
    redirect = storage.directory / ("b" * 32)
    redirect.symlink_to(storage.directory / original["id"], target_is_directory=True)
    with pytest.raises(ValueError, match="original storage folder"):
        service.source("b" * 32)
    assert not storage.receipts()
