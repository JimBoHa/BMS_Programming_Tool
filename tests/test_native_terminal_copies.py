"""Immutable original/effective retained copies, strict HTTP and no network authority."""

import struct

import pytest
from bacpypes3.primitivedata import Boolean, CharacterString, Integer, Real, Unsigned
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_terminal_copies import EffectiveNativeTerminalCopies, NativeTerminalCopies
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_moi_connection_copies import frames, packed, property_bytes
from .test_moi_terminal_copies import authored, literal_move
from .test_native_connection_copies import filesystem
from .test_native_signal_compiler import inline, retained

BASE = "/api/bacnet/controller/native-application/inputs/"


def setup(tmp_path, *, effective=True, files=None, **metadata):
    storage = ApplicationStore(Store(tmp_path))
    files = files or authored(compressed=True)
    snapshot = retained(
        storage,
        files,
        **{
            "identity": {
                "object-name": "Authored controller",
                "model-name": "M4-CVM03050-0",
                "vendor-identifier": 5,
            },
            **metadata,
        },
    )
    service = (EffectiveNativeTerminalCopies if effective else NativeTerminalCopies)(
        NativeBackupRecords(storage)
    )
    query = {
        "capture_id": snapshot["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
        "source_sha256": sha(files[3]),
    }
    return storage, service, files, query


def proposal(service, query):
    source = service.source(query)
    row = next(p for p in source["inventory"]["inputs"] if p["movable"])
    return {
        **query,
        "ref": row["ref"],
        "record_sha256": row.get("archive_record_sha256", row["record_sha256"]),
        "slot_property_sha256": row["slot_property_sha256"],
        "device_type_property_sha256": row["device_type_property_sha256"],
        "old_slot": row["slot"],
        "destination_slot": 3,
        **(
            {
                "effective_sha256": source["effective_sha256"],
                "effective_record_sha256": row["record_sha256"],
            }
            if source["saved_settings_merged"]
            else {}
        ),
    }


def literal_effective(raw):
    changes = [
        (900, Real(1.25), Real(3.5)),
        (901, Unsigned(1), Unsigned(70000)),
        (902, Integer(-1), Integer(-300)),
        (903, Boolean(False), Boolean(True)),
        (904, CharacterString("draft"), CharacterString("saved")),
    ]
    rows = []
    for width, body in frames(raw):
        if int.from_bytes(body[:2], "little") == 470:
            for pid, old, new in changes:
                before = property_bytes(pid, encoded(old))
                assert body.count(before) == 1
                body = body.replace(before, property_bytes(pid, encoded(new)))
        rows.append((width, body))
    return packed(raw[:14], rows)


@pytest.mark.parametrize("effective", [False, True])
@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("wide", [False, True])
def test_literal_saved_merge_then_two_payload_changes_leaves_retained_files_exact(
    tmp_path, effective, binary, compressed, wide
):
    storage, service, files, query = setup(
        tmp_path,
        effective=effective,
        files=authored(binary=binary, compressed=compressed, wide=wide),
    )
    before = filesystem(storage.directory)
    request = proposal(service, query)
    output, review = service.preview(request)
    original, actual = MoiIdentity(files[3]), MoiIdentity(output)
    basis = literal_effective(original.data) if effective else original.data
    assert actual.data == literal_move(basis, binary=binary)
    assert actual.reader.scalar(actual.root, 900) == (3.5 if effective else 1.25)
    assert actual.reader.scalar(actual.root, 901) == (70000 if effective else 1)
    assert review["saved_settings_merged"] is effective
    assert review["source_immutable"] and review["read_only"]
    assert not any(
        review[k]
        for k in (
            "can_apply",
            "field_transfer_enabled",
            "controller_write",
            "current_identity_verified",
            "controller_queries",
            "field_actions",
        )
    )
    report = review["compilation"]
    assert (
        seal({k: v for k, v in report.items() if k != "compilation_sha256"})
        == report["compilation_sha256"]
    )
    assert (
        seal({k: v for k, v in review.items() if k != "review_sha256"}) == review["review_sha256"]
    )
    assert service.export({**request, "review_sha256": review["review_sha256"]}) == (output, review)
    assert filesystem(storage.directory) == before and not storage.receipts()
    assert storage.load(query["capture_id"])[1] == files


@pytest.mark.parametrize(
    "fault", ["unknown", "crc", "identity", "vendor", "name", "reference", "format"]
)
def test_unqualified_saved_sources_refuse_effective_but_keep_original_copy_available(
    tmp_path, fault
):
    files, metadata = authored(), {}
    if fault == "unknown":
        files[11], files[12] = b"unknown directory", b"opaque values"
    elif fault == "crc":
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    elif fault == "identity":
        metadata["source_identity_matches"] = False
    elif fault == "vendor":
        metadata["identity"] = {
            "object-name": "Authored controller",
            "model-name": "M4-CVM03050-0",
            "vendor-identifier": 99,
        }
    elif fault == "name":
        files[11] += inline((8 << 22) | 5136, 470, 2390, "Changed controller")
    elif fault == "reference":
        files[11] += inline(101, 240, 32527, "controller/changed-input")
    else:
        # Retained root versions are 62/62; change the saved ACS to an unsupported pair.
        dynamic = bytearray(files[12])
        dynamic[0] = 99
        from bms_tool.mstp import header_crc

        dynamic[1] = header_crc(bytes([99])) ^ 255
        files[12] = bytes(dynamic)
    storage, effective, _, query = setup(tmp_path, files=files, **metadata)
    before = filesystem(storage.directory)
    with pytest.raises(ValueError):
        effective.source(query)
    archive = NativeTerminalCopies(effective.records)
    assert not archive.preview(proposal(archive, query))[1]["can_apply"]
    assert filesystem(storage.directory) == before and not storage.receipts()


@pytest.mark.parametrize("effective", [False, True])
@pytest.mark.parametrize(
    "field",
    [
        "snapshot_sha256",
        "source_sha256",
        "record_sha256",
        "slot_property_sha256",
        "device_type_property_sha256",
        "review_sha256",
    ],
)
def test_stale_source_property_or_review_never_exports(tmp_path, effective, field):
    storage, service, _, query = setup(tmp_path, effective=effective)
    request = proposal(service, query)
    output, review = service.preview(request)
    before = filesystem(storage.directory)
    with pytest.raises(ValueError):
        service.export({**request, "review_sha256": review["review_sha256"], field: "0" * 64})
    assert filesystem(storage.directory) == before and not storage.receipts() and output


@pytest.mark.parametrize("field", ["effective_sha256", "effective_record_sha256"])
def test_effective_guards_must_match_merged_record_and_full_image(tmp_path, field):
    _, service, _, query = setup(tmp_path)
    with pytest.raises(ValueError):
        service.preview({**proposal(service, query), field: "0" * 64})


@pytest.mark.parametrize("present", [False, True])
def test_saved_graph_continuation_cannot_be_created_or_replaced_by_terminal_merge(
    tmp_path, present
):
    files = authored()
    graph = native_record(
        575,
        700,
        [
            (32527, encoded(CharacterString("controller/diagram"))),
            *([(3384, b"\x3e\x11\x75\x02\x00x\x3f")] if present else []),
        ],
    )
    header = bytearray(files[3][:14])
    struct.pack_into("<I", header, 10, len(frames(files[3])) + 1)
    files[3] = packed(bytes(header), frames(files[3]) + [(2, graph)])
    value = b"\x3e\x10\x75\x02\x00y\x3f"
    row = (
        (700).to_bytes(4, "big")
        + (3384).to_bytes(2, "big")
        + b"\x4f\x18"
        + (575).to_bytes(2, "big")
        + b"\x1e"
        + value
        + b"\x1f"
        + b"\0" * 7
    )
    files[11] += (len(row) + 2).to_bytes(2, "big") + row
    storage, effective, _, query = setup(tmp_path, files=files)
    before = filesystem(storage.directory)
    with pytest.raises(ValueError, match="continuation metadata"):
        effective.source(query)
    archive = NativeTerminalCopies(effective.records)
    assert archive.preview(proposal(archive, query))
    assert filesystem(storage.directory) == before


@pytest.mark.parametrize("effective", [False, True])
def test_http_local_copy_has_exact_headers_strict_payload_and_zero_field_paths(
    tmp_path, monkeypatch, effective
):
    app = create_app(tmp_path)
    native = app.state.native_applications
    _, service, _, query = setup(tmp_path / "fixture", effective=effective)
    snapshot, files = service.records.storage.load(query["capture_id"])
    saved = native.storage.save(
        {
            key: snapshot[key]
            for key in (
                "target",
                "device",
                "identity",
                "source_identity_matches",
                "connector_config",
                "read_only",
            )
        },
        files,
    )
    query.update(capture_id=saved["id"], snapshot_sha256=saved["evidence_sha256"])

    def forbidden(*args, **kwargs):
        pytest.fail("A local terminal copy entered a field or mutation path")

    for name in ("require", "connect", "_read", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden, raising=False)
    monkeypatch.setattr(native.storage, "intent", forbidden)
    before = filesystem(native.storage.directory)
    route = BASE + ("effective-terminal-copy" if effective else "terminal-copy")
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(route + "/source", json=query).status_code == 403
        response = client.post(route + "/source", headers=headers, json=query)
        assert response.status_code == 200, response.text
        source = response.json()
        row = next(p for p in source["inventory"]["inputs"] if p["movable"])
        body = {
            **query,
            "ref": row["ref"],
            "record_sha256": row.get("archive_record_sha256", row["record_sha256"]),
            "slot_property_sha256": row["slot_property_sha256"],
            "device_type_property_sha256": row["device_type_property_sha256"],
            "old_slot": row["slot"],
            "destination_slot": 3,
        }
        if effective:
            body.update(
                effective_sha256=source["effective_sha256"],
                effective_record_sha256=row["record_sha256"],
            )
        response = client.post(route + "/preview", headers=headers, json=body)
        assert response.status_code == 200, response.text
        review = response.json()
        export_body = {**body, "review_sha256": review["review_sha256"]}
        exported = client.post(route + "/export", headers=headers, json=export_body)
        assert exported.status_code == 200, exported.text
        for key, value in [
            ("Artifact", sha(exported.content)),
            ("Review", review["review_sha256"]),
            ("Snapshot", query["snapshot_sha256"]),
            ("Source", query["source_sha256"]),
            ("Compilation", review["compilation"]["compilation_sha256"]),
        ]:
            assert exported.headers[f"X-Studio-{key}-Sha256"] == value
        assert exported.headers["content-type"] == "application/octet-stream"
        assert review["output_sha256"] == sha(exported.content)
        for change in [
            {"destination_slot": True},
            {"destination_slot": 3.0},
            {"old_slot": "1"},
            {"controller_write": True},
            {"operation_id": "unexpected-write"},
            {"host": "sa"},
        ]:
            assert (
                client.post(route + "/preview", headers=headers, json=body | change).status_code
                == 422
            )
        assert (
            client.post(
                route + "/export", headers=headers, json=export_body | {"review_sha256": "0" * 64}
            ).status_code
            == 422
        )
        assert (
            client.post(
                route + "/export", headers=headers, json=export_body | {"destination_slot": 2}
            ).status_code
            == 422
        )
        assert client.get("/api/session").json()["field_network_open"] is False
    assert (
        filesystem(native.storage.directory) == before
        and not native.storage.receipts()
        and not native.plans
    )
