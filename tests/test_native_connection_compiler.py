"""Independent retained values, graph bytes and offline saved-connection APIs."""

import gzip

import pytest
from bacpypes3.primitivedata import Boolean, CharacterString, Real
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_connection_compiler import (
    EffectiveConnectionService,
    effective_connection_router,
)
from bms_tool.native_connection_copies import NativeConnectionCopies
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_controller_application import encoded
from .test_moi_connection_copies import ADDED, WIRE, frames, packed, property_bytes
from .test_moi_wire_sources import REF, A, B, D
from .test_native_connection_copies import filesystem
from .test_native_signal_compiler import inline, retained
from .test_native_wire_compiler import BOOLEAN, wire_files

BASE = "/api/bacnet/controller/native-application/inspection/effective-connection-copy"
META = (
    b"\x3e"
    + encoded(Boolean(True))
    + encoded(CharacterString("Recorded é🙂 continuation"))
    + b"\x3f"
)


def connection_files(*, metadata=True, metadata_first=False, compressed=True, **kwargs):
    files = wire_files(compressed=False, wires=[(0, 85, 2, 7000)], **kwargs)
    rows = []
    for width, body in frames(files[3]):
        if int.from_bytes(body[:2], "little") in (536, 575) and metadata:
            added = property_bytes(3384, META)
            body = (
                body[:12] + added + body[12:] if metadata_first else body[:-1] + added + body[-1:]
            )
        rows.append((width, body))
    raw = packed(files[3][:14], rows)
    files[3] = gzip.compress(raw, mtime=123) if compressed else raw
    return files


def setup(tmp_path, files=None, **metadata):
    storage = ApplicationStore(Store(tmp_path))
    files = files or connection_files()
    snapshot = retained(
        storage,
        files,
        **{
            "identity": {
                "object-name": "Authored native wire controller",
                "model-name": "UNLISTED-MODEL",
                "vendor-identifier": 5,
            },
            **metadata,
        },
    )
    record = MoiIdentity(files[3]).reader.records[REF]
    query = {
        "capture_id": snapshot["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
        "source_sha256": sha(files[3]),
        "diagram_ref": REF,
        "record_sha256": record["sha256"],
        "prototype_index": 0,
        "source_ref": None,
    }
    return storage, EffectiveConnectionService(NativeBackupRecords(storage)), files, query


def proposal(service, query):
    source = service.source(query)
    s = source["selection"]
    return {
        **query,
        "source_ref": A,
        "target_ref": D,
        "effective_sha256": source["effective_sha256"],
        "effective_record_sha256": s["record_sha256"],
        "property_sha256": s["property_sha256"],
        "metadata_property_sha256": s["metadata_property_sha256"],
        "prototype_old": s["prototype"]["old"],
        "connection_count": s["connection_count"],
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
@pytest.mark.parametrize("metadata_first", [False, True])
def test_saved_values_and_one_literal_connection_with_continuation_survive_exactly(
    tmp_path, compressed, extended, diagram_class, metadata_first
):
    files = connection_files(
        compressed=compressed,
        extended=extended,
        diagram_class=diagram_class,
        metadata_first=metadata_first,
    )
    storage, service, _, query = setup(tmp_path, files)
    before = filesystem(storage.directory)
    request = proposal(service, query)
    output, review = service.preview(request)
    original = MoiIdentity(files[3])
    actual = MoiIdentity(output)
    expected = []
    for width, raw in frames(original.data):
        cid = int.from_bytes(raw[:2], "little")
        instance = int.from_bytes(raw[6:10], "big") & 0x3FFFFF
        if cid == 551 and instance in (10, 11):
            old = property_bytes(3113, encoded(Real(1 if instance == 10 else 2)))
            new = property_bytes(3113, encoded(Real(42 if instance == 10 else 17)))
            assert raw.count(old) == 1
            raw = raw.replace(old, new, 1)
        elif cid == 530 and instance == 20:
            old = property_bytes(3113, encoded(Boolean(False)))
            assert raw.count(old) == 1
            raw = raw.replace(old, property_bytes(3113, encoded(Boolean(True))), 1)
        elif cid == diagram_class:
            raw = raw.replace(WIRE + b"\x2f", WIRE + ADDED + b"\x2f", 1)
            raw = raw.replace(META + b"\x2f", META + META + b"\x2f", 1)
        expected.append((width, raw))
    assert actual.data == packed(original.data[:14], expected)
    assert actual.reader.scalar(actual.reader.records[A], 3113) == 42
    assert actual.reader.scalar(actual.reader.records[B], 3113) == 17
    assert actual.reader.scalar(actual.reader.records[BOOLEAN], 3113) is True
    assert review["compilation"]["connection_edit"]["new"] == [0, 85, 3, 7000]
    assert review["parameter_merge"]["matched_parameters"] == 3
    assert review["saved_settings_merged"] and review["source_immutable"]
    assert (
        not review["current_identity_verified"]
        and not review["can_apply"]
        and not review["controller_write"]
        and not review["field_transfer_enabled"]
    )
    assert service.export({**request, "review_sha256": review["review_sha256"]}) == (output, review)
    assert filesystem(storage.directory) == before and not storage.receipts()


def test_no_continuation_remains_absent_and_original_archive_mode_keeps_unmerged_values(tmp_path):
    storage, service, files, query = setup(tmp_path, connection_files(metadata=False))
    output, review = service.preview(proposal(service, query))
    assert review["compilation"]["connection_edit"]["continuation_prototype_sha256"] is None
    archive = NativeConnectionCopies(NativeBackupRecords(storage))
    s = archive.source(query)["selection"]
    body = {
        **query,
        "source_ref": A,
        "target_ref": D,
        "property_sha256": s["property_sha256"],
        "metadata_property_sha256": None,
        "prototype_old": s["prototype"]["old"],
        "connection_count": 1,
    }
    original_copy, original_review = archive.preview(body)
    reader = MoiIdentity(original_copy).reader
    assert reader.scalar(reader.records[A], 3113) == 1
    assert not original_review["saved_settings_merged"] and original_copy != output
    assert storage.load(query["capture_id"])[1] == files


@pytest.mark.parametrize("present", [False, True])
def test_saved_continuation_change_or_new_property_is_refused_without_harming_original_copy(
    tmp_path, present
):
    files = connection_files(metadata=present)
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
    storage, service, _, query = setup(tmp_path, files)
    before = filesystem(storage.directory)
    with pytest.raises(ValueError, match="continuation metadata"):
        service.source(query)
    assert NativeConnectionCopies(NativeBackupRecords(storage)).source(query)["selection"][
        "available"
    ]
    assert filesystem(storage.directory) == before


@pytest.mark.parametrize("fault", ["unknown", "crc", "identity", "vendor", "name", "reference"])
def test_unknown_schema_bad_crc_and_identity_changes_refuse_saved_compilation_but_preserve_sources(
    tmp_path, fault
):
    files = connection_files()
    metadata = {}
    if fault == "unknown":
        files[11], files[12] = b"Unknown directory", b"Opaque values"
    elif fault == "crc":
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    elif fault == "identity":
        metadata = {"source_identity_matches": False}
    elif fault == "vendor":
        metadata = {
            "identity": {
                "object-name": "Authored native wire controller",
                "model-name": "UNLISTED-MODEL",
                "vendor-identifier": 99,
            }
        }
    elif fault == "name":
        files[11] += inline((8 << 22) | 5136, 470, 2390, "Changed controller")
    elif fault == "reference":
        files[11] += inline((2 << 22) | 10, 551, 32527, "controller/changed-reference")
    storage, service, _, query = setup(tmp_path, files, **metadata)
    before = filesystem(storage.directory)
    with pytest.raises(ValueError):
        service.source(query)
    assert NativeConnectionCopies(NativeBackupRecords(storage)).source(query)["selection"][
        "available"
    ]
    assert filesystem(storage.directory) == before


@pytest.mark.parametrize(
    "key,value",
    [
        ("effective_sha256", "0" * 64),
        ("effective_record_sha256", "0" * 64),
        ("source_sha256", "0" * 64),
        ("record_sha256", "0" * 64),
        ("property_sha256", "0" * 64),
        ("metadata_property_sha256", None),
        ("snapshot_sha256", "0" * 64),
        ("prototype_index", 1),
        ("prototype_old", [1, 85, 2, 7000]),
        ("connection_count", 2),
        ("source_ref", B),
        ("target_ref", A),
        ("review_sha256", "0" * 64),
    ],
)
def test_all_original_effective_and_proposal_guards_are_required_again_for_export(
    tmp_path, key, value
):
    storage, service, _, query = setup(tmp_path)
    body = proposal(service, query)
    _, review = service.preview(body)
    request = {**body, "review_sha256": review["review_sha256"], key: value}
    before = filesystem(storage.directory)
    with pytest.raises(ValueError):
        service.export(request)
    assert filesystem(storage.directory) == before


def test_strict_local_http_exposes_only_three_token_routes_and_exact_output_proofs(tmp_path):
    storage, service, _, query = setup(tmp_path)
    body = proposal(service, query)
    before = filesystem(storage.directory)
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Effective connection compilation attempted a field operation")

    for name in ("require", "connect", "disconnect", "_read", "release"):
        setattr(app.state.bacnet, name, forbidden)
    assert {r.path: r.methods for r in effective_connection_router(service).routes} == {
        BASE + suffix: {"POST"} for suffix in ("/source", "/preview", "/export")
    }
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for suffix, request in [
            ("/source", query),
            ("/preview", body),
            ("/export", {**body, "review_sha256": "0" * 64}),
        ]:
            assert client.post(BASE + suffix, json=request).status_code == 403
        source = client.post(BASE + "/source", headers=headers, json=query)
        assert source.status_code == 200 and source.json() == service.source(query)
        response = client.post(BASE + "/preview", headers=headers, json=body)
        assert response.status_code == 200, response.text
        review = response.json()
        output = client.post(
            BASE + "/export",
            headers=headers,
            json={**body, "review_sha256": review["review_sha256"]},
        )
        assert output.status_code == 200 and output.content == service.preview(body)[0]
        for key, value in {
            "Artifact": sha(output.content),
            "Review": review["review_sha256"],
            "Snapshot": query["snapshot_sha256"],
            "Source": query["source_sha256"],
            "Compilation": review["compilation"]["compilation_sha256"],
        }.items():
            assert output.headers["X-Studio-" + key + "-Sha256"] == value
        for extra in [
            {"effective_sha256": True},
            {"effective_record_sha256": 42},
            {"can_apply": True},
            {"prototype_old": [False, 85, 2, 7000]},
            {"connection_count": True},
        ]:
            assert (
                client.post(BASE + "/preview", headers=headers, json={**body, **extra}).status_code
                == 422
            )
        assert not client.get("/api/session").json()["field_network_open"]
    assert filesystem(storage.directory) == before and not storage.receipts()
