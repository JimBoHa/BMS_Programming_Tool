"""Independent saved-slot and wire bytes qualify effective local compilation."""

import gzip
import struct
import types

import pytest
from bacpypes3.primitivedata import Boolean, CharacterString, ObjectIdentifier, Real, Unsigned
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_effective_wire import EffectiveWireCompiler
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_wire_compiler import EffectiveWireService
from bms_tool.native_wire_copies import NativeWireCopies
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_moi_wire_sources import REF, A, B, source
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_signal_compiler import inline, retained, slot

BASE = "/api/bacnet/controller/native-application/inspection/effective-wire-source"
BOOLEAN = "controller/retained-boolean"


def wire_files(*, compressed=True, extended=False, **kwargs):
    data = bytearray(source(compressed=False, extended=extended, **kwargs))
    data[10:14] = (int.from_bytes(data[10:14], "little") + 1).to_bytes(4, "little")
    record = native_record(
        530,
        20,
        [
            (32527, encoded(CharacterString(BOOLEAN))),
            (75, encoded(ObjectIdentifier(("binary-value", 20)))),
            (2390, encoded(CharacterString("Authored retained Boolean"))),
            (3113, encoded(Boolean(False))),
        ],
    )
    data.extend(
        b"\x00\x00" + struct.pack("<I", len(record) + 6)
        if extended
        else struct.pack("<H", len(record) + 2)
    )
    data.extend(record)
    static, dynamic = b"", b""
    for oid, cid, pid, kind, payload in [
        ((2 << 22) | 10, 551, 3113, 4, struct.pack(">f", 42)),
        ((2 << 22) | 11, 551, 3113, 4, struct.pack(">f", 17)),
        ((5 << 22) | 20, 530, 3113, 1, b"\x01"),
        ((2 << 22) | 99, 777, 900, 2, (123).to_bytes(4, "big")),
    ]:
        static += slot(oid, cid, pid, kind, len(dynamic))
        dynamic += payload + bytes([header_crc(payload) ^ 255])
    return {
        3: gzip.compress(data, mtime=123) if compressed else bytes(data),
        11: static,
        12: dynamic,
    }


def setup(tmp_path, files=None, **metadata):
    storage = ApplicationStore(Store(tmp_path))
    snapshot = retained(
        storage,
        files or wire_files(),
        **{
            "identity": {
                "object-name": "Authored native wire controller",
                "vendor-identifier": 5,
                "model-name": "UNLISTED-MODEL",
            },
            **metadata,
        },
    )
    return storage, EffectiveWireService(NativeBackupRecords(storage)), snapshot


def query(service, snapshot, *, index=0):
    _, files = service.records.storage.load(snapshot["id"])
    editor = MoiIdentity(files[3])
    return {
        "capture_id": snapshot["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
        "source_sha256": sha(files[3]),
        "diagram_ref": REF,
        "record_sha256": editor.reader.records[REF]["sha256"],
        "wire_index": index,
    }


def proposal(service, q, *, source_ref=B):
    data = service.source(q)
    return q | {
        "effective_sha256": data["effective_sha256"],
        "effective_record_sha256": data["selection"]["record_sha256"],
        "property_sha256": data["selection"]["property_sha256"],
        "old": data["selection"]["selected_wire"]["old"],
        "source_ref": source_ref,
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("index,replacement", [(0, B), (1, A)])
def test_saved_numeric_boolean_values_merge_before_exact_wire_patch(
    tmp_path, compressed, extended, index, replacement
):
    files = wire_files(compressed=compressed, extended=extended)
    original = dict(files)
    storage, service, snapshot = setup(tmp_path, files)
    q = query(service, snapshot, index=index)
    body = proposal(service, q, source_ref=replacement)
    output, review = service.preview(body)
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    before, after = MoiIdentity(merged), MoiIdentity(output)
    edit = review["compilation"]["wire_edit"]
    offset, width = edit["source_index_offset"], edit["source_index_bytes"]
    assert after.data == (
        before.data[:offset] + edit["new"][0].to_bytes(width, "big") + before.data[offset + width :]
    )
    assert after.reader.diagram(REF)["connections"][index]["source_ref"] == replacement
    assert after.reader.scalar(after.reader.records[A], 3113) == 42
    assert after.reader.scalar(after.reader.records[B], 3113) == 17
    assert after.reader.scalar(after.reader.records[BOOLEAN], 3113) is True
    assert len(after.reader.records) == len(before.reader.records)
    assert review["compilation"]["other_merged_bytes_preserved"]
    assert review["saved_settings_merged"] and not review["field_transfer_enabled"]
    assert not review["controller_write"] and not review["current_identity_verified"]
    assert service.export(body | {"review_sha256": review["review_sha256"]}) == (output, review)
    assert storage.load(snapshot["id"])[1] == files == original and not storage.receipts()


def test_no_wire_change_still_merges_other_saved_values(tmp_path):
    _, service, snapshot = setup(tmp_path)
    q = query(service, snapshot)
    output, review = service.preview(proposal(service, q, source_ref=A))
    compiler = EffectiveWireCompiler(wire_files())
    assert output == compiler.merged and output != wire_files()[3]
    assert not review["compilation"]["wire_edit"]["changed"]
    assert review["compilation"]["parameter_merge"]["matched_parameters"] == 3


@pytest.mark.parametrize(
    "fault", ["unknown", "crc", "name", "reference", "object", "wire", "members", "order", "layout"]
)
def test_saved_identity_graph_changes_and_unknown_storage_refuse_effective_compilation(
    tmp_path, fault
):
    files = wire_files()
    if fault == "unknown":
        files[11], files[12] = b"Unknown selectors", b"Opaque values"
    elif fault == "crc":
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    elif fault == "name":
        files[11] += inline((8 << 22) | 5136, 470, 2390, "Another controller")
    elif fault == "reference":
        files[11] += inline((2 << 22) | 10, 551, 32527, "controller/another-reference")
    else:
        value = (
            encoded(ObjectIdentifier((2, 100)))
            if fault == "object"
            else b"\x3e"
            + b"".join(encoded(Unsigned(v)) for v in [1, 85, 2, 7000])
            + b"\x3f\x3e"
            + b"".join(encoded(Unsigned(v)) for v in [1, 85, 3, 7000])
            + b"\x3f"
        )
        oid, cid, pid = ((2 << 22) | 10, 551, 75) if fault == "object" else (1, 575, 3118)
        if fault == "members":
            pid = 3375
            value = b"".join(encoded(ObjectIdentifier((2, n))) for n in (11, 10, 12, 13))
        elif fault == "order":
            pid = 3117
            value = b"".join(encoded(Unsigned(n)) for n in (1, 0, 2, 3))
        elif fault == "layout":
            pid = 3383
            value = b"".join(
                b"\x3e"
                + encoded(Real(i * 30 + 1))
                + encoded(Real(i * 20))
                + encoded(Unsigned(0))
                + b"\x3f"
                for i in range(4)
            )
        row = (
            oid.to_bytes(4, "big")
            + pid.to_bytes(2, "big")
            + b"\x4f\x18"
            + cid.to_bytes(2, "big")
            + b"\x1e"
            + value
            + b"\x1f"
            + b"\0" * 7
        )
        files[11] += (len(row) + 2).to_bytes(2, "big") + row
    storage, service, snapshot = setup(tmp_path, files)
    q = query(service, snapshot)
    with pytest.raises(
        ValueError, match="diagram" if fault in {"wire", "members", "order", "layout"} else None
    ):
        service.source(q)
    # Its original archive remains independently eligible; no settings were applied.
    archive = NativeWireCopies(service.records)
    original = archive.source(q)["selection"]
    output, report = archive.preview(
        q
        | {
            "old": original["selected_wire"]["old"],
            "property_sha256": original["property_sha256"],
            "source_ref": B,
        }
    )
    assert output and not report["saved_settings_merged"] and not storage.receipts()


@pytest.mark.parametrize("fault", ["unverified", "vendor", "device", "name", "model"])
def test_retained_identity_is_recomputed_for_effective_wire_compilation(tmp_path, fault):
    metadata = (
        {"source_identity_matches": False}
        if fault == "unverified"
        else {"device": "device,5137"}
        if fault == "device"
        else {
            "identity": {
                "vendor-identifier": 99 if fault == "vendor" else 5,
                "object-name": "Mismatch" if fault == "name" else "Authored native wire controller",
                "model-name": "Mismatch" if fault == "model" else "UNLISTED-MODEL",
            }
        }
    )
    _, service, snapshot = setup(tmp_path, **metadata)
    with pytest.raises(ValueError):
        service.source(query(service, snapshot))


@pytest.mark.parametrize(
    "field,value",
    [
        ("effective_sha256", "0" * 64),
        ("effective_record_sha256", "1" * 64),
        ("source_sha256", "2" * 64),
        ("record_sha256", "3" * 64),
        ("source_ref", A),
        ("wire_index", 1),
        ("old", [1, 85, 2, 7000]),
        ("property_sha256", "4" * 64),
    ],
)
def test_export_recomputes_archive_effective_encoding_and_proposal(tmp_path, field, value):
    _, service, snapshot = setup(tmp_path)
    body = proposal(service, query(service, snapshot))
    _, review = service.preview(body)
    with pytest.raises(ValueError):
        service.export(body | {"review_sha256": review["review_sha256"], field: value})


@pytest.mark.parametrize("key", [3, 11, 12])
def test_every_source_file_is_rechecked_before_review_and_export(tmp_path, key):
    storage, service, snapshot = setup(tmp_path)
    q = query(service, snapshot)
    body = proposal(service, q)
    _, review = service.preview(body)
    path = storage.directory / snapshot["id"] / f"file-{key}.bin"
    assert path.is_file()
    path.write_bytes(b"Changed retained bytes")
    for action, request in [
        (service.source, q),
        (service.preview, body),
        (service.export, body | {"review_sha256": review["review_sha256"]}),
    ]:
        with pytest.raises(ValueError):
            action(request)


def test_http_is_closed_strict_offline_and_exports_exact_sealed_bytes(tmp_path):
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    service = EffectiveWireService(NativeBackupRecords(storage))
    snapshot = retained(
        storage,
        wire_files(),
        identity={
            "object-name": "Authored native wire controller",
            "vendor-identifier": 5,
            "model-name": "UNLISTED-MODEL",
        },
    )
    q = query(service, snapshot)
    with TestClient(app) as c:
        headers = {"X-Studio-Token": c.get("/api/session").json()["token"]}
        assert c.post(BASE + "/source", json=q).status_code == 403
        response = c.post(BASE + "/source", json=q, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["saved_settings_merged"]
        body = proposal(service, q)
        for alteration in [
            {"router": "127.0.0.1:47999"},
            {"wire_index": True},
            {"old": [False, 85, 2, 7000]},
            {"effective_sha256": "bad"},
        ]:
            assert (
                c.post(BASE + "/preview", json=body | alteration, headers=headers).status_code
                == 422
            )
        review = c.post(BASE + "/preview", json=body, headers=headers).json()
        exported = c.post(
            BASE + "/export",
            json=body | {"review_sha256": review["review_sha256"]},
            headers=headers,
        )
        assert exported.status_code == 200, exported.text
        assert (
            sha(exported.content)
            == review["output_sha256"]
            == exported.headers["X-Studio-Artifact-Sha256"]
        )
        assert exported.headers["X-Studio-Review-Sha256"] == review["review_sha256"]
        assert exported.headers["X-Studio-Snapshot-Sha256"] == q["snapshot_sha256"]
        assert not c.get("/api/session").json()["field_network_open"] and not storage.receipts()


async def test_actual_native_capture_can_compile_wire_after_disconnect_without_more_requests(
    native_link,
):
    peer, bacnet, _, native, target = native_link
    peer.files = wire_files()
    peer.metadata["object-name"] = "Authored native wire controller"
    seen = []
    original = peer.indication

    async def watch(self, apdu):
        seen.append(type(apdu).__name__)
        await original(apdu)

    peer.indication = types.MethodType(watch, peer)
    captured = await native.capture(**target, operation_id="capture-for-effective-wire")
    snapshot, _ = native.storage.load(captured["id"])
    await bacnet.disconnect()
    before = list(seen)
    service = EffectiveWireService(NativeBackupRecords(native.storage))
    body = proposal(service, query(service, snapshot))
    output, review = service.preview(body)
    assert service.export(body | {"review_sha256": review["review_sha256"]}) == (output, review)
    assert seen == before and not native.storage.receipts()


@pytest.mark.parametrize(
    "case,expected",
    [
        ("plain", "source-qualified"),
        ("serial", "source-qualified"),
        ("unknown", "unsupported-source"),
        ("unverified", "unsupported-source"),
        ("saved-config", "unsupported-source"),
    ],
)
def test_capabilities_use_actual_effective_candidates_independently_of_transport(
    tmp_path, case, expected
):
    files = wire_files()
    metadata = {}
    if case == "serial":
        metadata = {"connector_config": {"transport": "mstp", "serial_port": "/dev/authored"}}
    if case == "unknown":
        files[11], files[12] = b"Unknown selectors", b"Opaque values"
    if case == "unverified":
        metadata = {"source_identity_matches": False}
    if case == "saved-config":
        files[11] += slot((2 << 22) | 11, 551, 65000, 2, len(files[12]))
        payload = (2).to_bytes(4, "big")
        files[12] += payload + bytes([header_crc(payload) ^ 255])
    storage, service, snapshot = setup(tmp_path, files, **metadata)
    report = service.records.capabilities(
        {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    )
    rows = {r["id"]: r for r in report["operations"]}
    assert report["capability_profile"] == "native-backup-operation-capabilities/7"
    assert len(rows) == 18
    assert rows["wire-source-copy"]["status"] == "source-qualified"
    assert rows["effective-wire-compile"]["status"] == expected
    assert rows["wire-source-transfer"]["status"] == (
        "preflight-required"
        if case == "plain"
        else "transport-unavailable"
        if case == "serial"
        else "source-mismatch"
        if case == "unverified"
        else "unsupported-source"
    )
    assert rows["general-logic"]["status"] == "unavailable"
    assert (
        not report["field_actions"] and not report["controller_queries"] and not storage.receipts()
    )
    assert storage.load(snapshot["id"])[1] == files
    if case == "saved-config":
        q = query(service, snapshot)
        assert not service.source(q)["selection"]["available"]
        with pytest.raises(ValueError, match="configuration differs"):
            service.preview(proposal(service, q))


def test_effective_wire_compiler_does_not_require_standard_real_signal_fields(tmp_path):
    _, service, snapshot = setup(tmp_path, wire_files(target_class=538))
    q = query(service, snapshot)
    body = proposal(service, q)
    assert service.source(q)["selection"]["available"]
    output, review = service.preview(body)
    assert output and review["compilation"]["other_merged_bytes_preserved"]
    report = service.records.capabilities(
        {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    )
    rows = {r["id"]: r for r in report["operations"]}
    assert rows["effective-wire-compile"]["status"] == "source-qualified"
    assert rows["effective-default-compile"]["status"] == "unsupported-source"


def test_original_and_effective_record_hashes_are_separate_when_saved_name_changes(tmp_path):
    files = wire_files()
    files[11] += inline(1, 575, 2390, "Saved native sequence")
    _, service, snapshot = setup(tmp_path, files)
    q = query(service, snapshot)
    info = service.source(q)
    assert info["archive_record_sha256"] == q["record_sha256"]
    assert info["selection"]["record_sha256"] != q["record_sha256"]
    body = proposal(service, q)
    output, review = service.preview(body)
    assert MoiIdentity(output).reader.diagram(REF)["name"] == "Saved native sequence"
    assert review["compilation"]["other_merged_bytes_preserved"]
    with pytest.raises(ValueError, match="graph record or wire property changed"):
        service.preview(body | {"effective_record_sha256": q["record_sha256"]})
