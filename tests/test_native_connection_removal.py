"""Independent saved values, immutable source guards and local HTTP removal copies."""

import gzip

import pytest
from bacpypes3.primitivedata import Boolean, CharacterString, Real
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_connection_removal import (
    EffectiveConnectionRemovals,
    NativeConnectionRemovals,
)
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_controller_application import encoded
from .test_moi_connection_copies import frames, packed, property_bytes
from .test_moi_connection_removal import LITERAL, METADATA, WIRES
from .test_moi_wire_sources import REF, A, B
from .test_native_connection_copies import filesystem
from .test_native_signal_compiler import inline, retained
from .test_native_wire_compiler import BOOLEAN, wire_files

BASE = "/api/bacnet/controller/native-application/inspection/"
ROUTES = ["connection-removal-copy", "effective-connection-removal-copy"]


def removal_files(*, compressed=True, metadata=True, metadata_first=False, wires=None, **kwargs):
    wires = WIRES if wires is None else wires
    files = wire_files(compressed=False, wires=wires, **kwargs)
    rows = []
    for width, body in frames(files[3]):
        if metadata and int.from_bytes(body[:2], "little") in (536, 575):
            extra = property_bytes(3384, b"".join(METADATA[: len(wires)]))
            body = (
                body[:12] + extra + body[12:] if metadata_first else body[:-1] + extra + body[-1:]
            )
        rows.append((width, body))
    native = packed(files[3][:14], rows)
    files[3] = gzip.compress(native, mtime=123) if compressed else native
    return files


def setup(tmp_path, *, effective=True, files=None, index=0, **metadata):
    storage = ApplicationStore(Store(tmp_path))
    files = files or removal_files()
    snapshot = retained(
        storage,
        files,
        **{
            "identity": {
                "object-name": "Authored native wire controller",
                "vendor-identifier": 5,
                "model-name": "UNLISTED-MODEL",
            },
            **metadata,
        },
    )
    service = (EffectiveConnectionRemovals if effective else NativeConnectionRemovals)(
        NativeBackupRecords(storage)
    )
    query = {
        "capture_id": snapshot["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
        "source_sha256": sha(files[3]),
        "diagram_ref": REF,
        "record_sha256": MoiIdentity(files[3]).reader.records[REF]["sha256"],
        "wire_index": index,
    }
    return storage, service, files, query


def proposal(service, query):
    source = service.source(query)
    selected = source["selection"]
    return {
        **query,
        "property_sha256": selected["property_sha256"],
        "metadata_property_sha256": selected["metadata_property_sha256"],
        "old": selected["selected_wire"]["old"],
        "connection_count": selected["connection_count"],
        **(
            {
                "effective_sha256": source["effective_sha256"],
                "effective_record_sha256": selected["record_sha256"],
            }
            if source["saved_settings_merged"]
            else {}
        ),
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
@pytest.mark.parametrize("metadata_first", [False, True])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_exact_literal_saved_merge_precedes_only_selected_connection_removal(
    tmp_path, compressed, extended, diagram_class, metadata_first, index
):
    files = removal_files(
        compressed=compressed,
        extended=extended,
        diagram_class=diagram_class,
        metadata_first=metadata_first,
    )
    storage, service, _, query = setup(tmp_path, files=files, index=index)
    before = filesystem(storage.directory)
    request = proposal(service, query)
    output, review = service.preview(request)
    original, actual = MoiIdentity(files[3]), MoiIdentity(output)
    expected = []
    for width, body in frames(original.data):
        cid, instance = (
            int.from_bytes(body[:2], "little"),
            int.from_bytes(body[6:10], "big") & 0x3FFFFF,
        )
        if cid == 551 and instance in (10, 11):
            old = property_bytes(3113, encoded(Real(1 if instance == 10 else 2)))
            assert body.count(old) == 1
            body = body.replace(
                old, property_bytes(3113, encoded(Real(42 if instance == 10 else 17))), 1
            )
        elif cid == 530 and instance == 20:
            old = property_bytes(3113, encoded(Boolean(False)))
            assert body.count(old) == 1
            body = body.replace(old, property_bytes(3113, encoded(Boolean(True))), 1)
        elif cid == diagram_class:
            old_wire = property_bytes(3118, b"".join(LITERAL))
            old_meta = property_bytes(3384, b"".join(METADATA))
            assert body.count(old_wire) == body.count(old_meta) == 1
            body = body.replace(
                old_wire,
                property_bytes(3118, b"".join(LITERAL[:index] + LITERAL[index + 1 :])),
                1,
            ).replace(
                old_meta,
                property_bytes(3384, b"".join(METADATA[:index] + METADATA[index + 1 :])),
                1,
            )
        expected.append((width, body))
    assert actual.data == packed(original.data[:14], expected)
    assert actual.reader.scalar(actual.reader.records[A], 3113) == 42
    assert actual.reader.scalar(actual.reader.records[B], 3113) == 17
    assert actual.reader.scalar(actual.reader.records[BOOLEAN], 3113) is True
    report = review["compilation"]
    assert report["connection_removal"]["old"] == list(WIRES[index])
    assert report["connection_removal"]["connection_count_after"] == 2
    assert report["files"] == review["files"]
    assert report["parameter_merge"]["matched_parameters"] == 3
    assert report["other_merged_bytes_preserved"] and report["saved_settings_merged"]
    assert report["compiled_native_sha256"] == sha(actual.data)
    assert (
        seal({k: v for k, v in report.items() if k != "compilation_sha256"})
        == report["compilation_sha256"]
    )
    assert not any(
        review[k]
        for k in [
            "current_identity_verified",
            "controller_write",
            "can_apply",
            "field_transfer_enabled",
        ]
    )
    assert service.export({**request, "review_sha256": review["review_sha256"]}) == (output, review)
    assert filesystem(storage.directory) == before and not storage.receipts()


@pytest.mark.parametrize("effective", [False, True])
@pytest.mark.parametrize("metadata", [False, True])
def test_last_wire_empty_graph_retains_explicit_metadata_and_original_saved_basis(
    tmp_path, effective, metadata
):
    storage, service, files, query = setup(
        tmp_path, effective=effective, files=removal_files(wires=WIRES[:1], metadata=metadata)
    )
    output, review = service.preview(proposal(service, query))
    reader = MoiIdentity(output).reader
    assert reader.diagram(REF)["connections"] == [] and len(reader.diagram(REF)["blocks"]) == 4
    assert (3384 in reader.records[REF]["properties"]) is metadata
    assert reader.scalar(reader.records[A], 3113) == (42 if effective else 1)
    assert review["saved_settings_merged"] is effective
    assert storage.load(query["capture_id"])[1] == files


@pytest.mark.parametrize("fault", ["unknown", "crc", "identity", "vendor", "name", "reference"])
def test_unqualified_saved_sources_leave_archive_removal_available_and_originals_intact(
    tmp_path, fault
):
    files, metadata = removal_files(), {}
    if fault == "unknown":
        files[11], files[12] = b"Unknown saved directory", b"Opaque saved values"
    elif fault == "crc":
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    elif fault == "identity":
        metadata["source_identity_matches"] = False
    elif fault == "vendor":
        metadata["identity"] = {
            "object-name": "Authored native wire controller",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 99,
        }
    elif fault == "name":
        files[11] += inline((8 << 22) | 5136, 470, 2390, "Changed controller")
    else:
        files[11] += inline((2 << 22) | 10, 551, 32527, "controller/changed-reference")
    storage, effective, _, query = setup(tmp_path, files=files, **metadata)
    before = filesystem(storage.directory)
    with pytest.raises(ValueError):
        effective.source(query)
    archive = NativeConnectionRemovals(effective.records)
    assert archive.source(query)["selection"]["available"]
    assert archive.preview(proposal(archive, query))[1]["can_apply"] is False
    assert filesystem(storage.directory) == before and not storage.receipts()


@pytest.mark.parametrize("present", [False, True])
def test_saved_values_cannot_change_or_create_connection_continuation(tmp_path, present):
    files = removal_files(metadata=present, wires=WIRES[:1])
    value = (
        b"\x3e"
        + encoded(Boolean(False))
        + encoded(CharacterString("Changed continuation"))
        + b"\x3f"
    )
    row = (
        (1).to_bytes(4, "big")
        + (3384).to_bytes(2, "big")
        + b"\x4f\x18"
        + (575).to_bytes(2, "big")
        + b"\x1e"
        + value
        + b"\x1f"
        + b"\0" * 7
    )
    files[11] += (len(row) + 2).to_bytes(2, "big") + row
    storage, service, _, query = setup(tmp_path, files=files)
    before = filesystem(storage.directory)
    with pytest.raises(ValueError, match="continuation metadata"):
        service.source(query)
    archive = NativeConnectionRemovals(service.records)
    assert archive.preview(proposal(archive, query))
    assert filesystem(storage.directory) == before


@pytest.mark.parametrize("effective", [False, True])
@pytest.mark.parametrize(
    "field,value",
    [
        ("snapshot_sha256", "0" * 64),
        ("source_sha256", "0" * 64),
        ("record_sha256", "0" * 64),
        ("property_sha256", "0" * 64),
        ("metadata_property_sha256", None),
        ("wire_index", 1),
        ("old", [0, 85, 3, 7000]),
        ("connection_count", 2),
        ("review_sha256", "0" * 64),
    ],
)
def test_export_rechecks_original_and_selected_edge_guards(tmp_path, effective, field, value):
    storage, service, _, query = setup(tmp_path, effective=effective)
    body = proposal(service, query)
    _, review = service.preview(body)
    before = filesystem(storage.directory)
    with pytest.raises(ValueError):
        service.export({**body, "review_sha256": review["review_sha256"], field: value})
    assert filesystem(storage.directory) == before and not storage.receipts()


@pytest.mark.parametrize("field", ["effective_sha256", "effective_record_sha256"])
def test_effective_export_keeps_both_merged_hash_guards(tmp_path, field):
    _, service, _, query = setup(tmp_path)
    body = proposal(service, query)
    _, review = service.preview(body)
    with pytest.raises(ValueError):
        service.export({**body, "review_sha256": review["review_sha256"], field: "0" * 64})


@pytest.mark.parametrize("effective", [False, True])
def test_actual_http_copy_keeps_strict_admission_exact_artifact_and_zero_field_calls(
    tmp_path, monkeypatch, effective
):
    storage, service, _, query = setup(tmp_path, effective=effective)
    body = proposal(service, query)
    output, review = service.preview(body)
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("A local removal copy attempted controller access or a transfer intent")

    for name in ["require", "connect", "disconnect", "release"]:
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    before = filesystem(storage.directory)
    route = BASE + ROUTES[int(effective)]
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(route + "/source", json=query).status_code == 403
        opened = client.post(route + "/source", headers=headers, json=query)
        assert opened.status_code == 200 and opened.json()["selection"]["available"]
        assert opened.json()["source_immutable"]
        result = client.post(route + "/preview", headers=headers, json=body)
        assert result.status_code == 200 and result.json() == review
        exported = client.post(
            route + "/export",
            headers=headers,
            json={**body, "review_sha256": review["review_sha256"]},
        )
        assert exported.status_code == 200 and exported.content == output
        for key, expected in [
            ("Artifact", sha(output)),
            ("Review", review["review_sha256"]),
            ("Snapshot", query["snapshot_sha256"]),
            ("Source", query["source_sha256"]),
            ("Compilation", review["compilation"]["compilation_sha256"]),
        ]:
            assert exported.headers[f"X-Studio-{key}-Sha256"] == expected
        for change in [
            {"wire_index": True},
            {"wire_index": 1.0},
            {"connection_count": True},
            {"old": [False, 85, 2, 7000]},
            {"old": [0, 85, 2]},
            {"source_ref": A},
            {"controller_write": True},
            {"operation_id": "unexpected-write"},
        ]:
            assert (
                client.post(route + "/preview", headers=headers, json=body | change).status_code
                == 422
            )
        assert (
            client.post(
                route + "/export", headers=headers, json={**body, "review_sha256": "0" * 64}
            ).status_code
            == 422
        )
        assert client.get("/api/session").json()["field_network_open"] is False
    assert filesystem(storage.directory) == before and not storage.receipts()
