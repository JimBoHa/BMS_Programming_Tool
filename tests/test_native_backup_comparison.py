"""Original byte/record evidence stays separate from semantics and field access."""

import gzip
import hashlib
import json
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, Integer, Real, Unsigned
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.native_backup_comparison import NativeBackupComparison
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_native_signal_compiler import retained, signal_files

BASE = "/api/bacnet/controller/native-application/inspection/compare"


def record(ref="observed/ref", *, cid=526, value=None, properties=None, index=10):
    return native_record(
        cid,
        index,
        [
            (32527, encoded(CharacterString(ref))),
            (3113, encoded(Real(2.0)) if value is None else value),
        ]
        + (properties or []),
    )


def archive(*records, compressed=False):
    header = bytearray(signal_files(compressed=False)[3][:14])
    header[10:14] = len(records).to_bytes(4, "little")
    data = bytes(header) + b"".join(struct.pack("<H", len(row) + 2) + row for row in records)
    return gzip.compress(data, mtime=0) if compressed else data


def source(storage, application, **metadata):
    snap = retained(
        storage,
        {3: application, 11: b"Opaque saved directory", 12: b"Original saved bytes"},
        source_identity_matches=False,
        source_identity_error="Authored archive-only fixture; no acquisition identity asserted.",
        **metadata,
    )
    return {"capture_id": snap["id"], "snapshot_sha256": snap["evidence_sha256"]}


def setup(tmp_path, first=None, second=None):
    storage = ApplicationStore(Store(tmp_path))
    service = NativeBackupComparison(NativeBackupRecords(storage))
    first = archive(record()) if first is None else first
    second = first if second is None else second
    return storage, service, {"left": source(storage, first), "right": source(storage, second)}


def test_equal_sources_preserve_original_bytes_and_independent_report_seal(tmp_path):
    storage, service, request = setup(tmp_path)
    originals = [storage.load(request[side]["capture_id"])[1] for side in ("left", "right")]
    report = service.compare(request)
    assert report["rows"] == [] and all(row["equal"] for row in report["files"])
    assert report["structured_comparison"]["scan_complete"]
    assert not report["semantics_verified"] and not report["restore_plan"]
    assert report["read_only"] and not report["controller_queries"] and not report["field_actions"]
    expected = hashlib.sha256(
        json.dumps(
            {k: v for k, v in report.items() if k != "evidence_sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert expected == report["evidence_sha256"]
    assert [storage.load(request[s]["capture_id"])[1] for s in ("left", "right")] == originals


@pytest.mark.parametrize("compressed", [False, True])
def test_encoding_change_keeps_float_signed_zero_and_opaque_value_evidence(tmp_path, compressed):
    first = archive(
        record(value=encoded(Real(-0.0)), properties=[(65000, b"\x4e\x21\x03\x4f")]),
        compressed=compressed,
    )
    second = archive(
        record(value=encoded(Real(0.0)), properties=[(65000, b"\x4e\x21\x04\x4f")]),
        compressed=not compressed,
    )
    _, service, request = setup(tmp_path, first, second)
    report = service.compare(request)
    assert [row["kind"] for row in report["rows"]] == [
        "record-bytes-changed",
        "property-encoding-changed",
        "property-encoding-changed",
    ]
    zero = report["rows"][1]
    assert zero["property"] == 3113 and zero["left"]["scalar"]["datatype"] == "Real"
    assert struct.pack(">d", zero["left"]["scalar"]["value"]) == struct.pack(">d", -0.0)
    assert zero["left"]["encoded_sha256"] != zero["right"]["encoded_sha256"]
    opaque = report["rows"][2]
    assert opaque["left"]["scalar"] is None and opaque["right"]["scalar"] is None
    assert opaque["left"]["encoded_sha256"] != opaque["right"]["encoded_sha256"]


def test_equal_numeric_codes_with_different_native_types_are_changes(tmp_path):
    _, service, request = setup(
        tmp_path,
        archive(record(value=encoded(Integer(2)))),
        archive(record(value=encoded(Unsigned(2)))),
    )
    value = service.compare(request)["rows"][1]
    assert value["left"]["scalar"] == {"datatype": "Integer", "value": 2}
    assert value["right"]["scalar"] == {"datatype": "Unsigned", "value": 2}


def test_references_align_records_after_offset_changes_and_report_added_removed(tmp_path):
    _, service, request = setup(
        tmp_path,
        archive(record("remove"), record("keep", index=11)),
        archive(record("add", index=12), record("keep", index=11)),
    )
    report = service.compare(request)
    assert [(r["kind"], r["reference"]) for r in report["rows"]] == [
        ("record-added", "add"),
        ("record-removed", "remove"),
    ]
    assert report["structured_comparison"]["records_compared"] == 3


def test_changed_class_is_replacement_without_property_schema_alignment(tmp_path):
    _, service, request = setup(
        tmp_path, archive(record()), archive(record(cid=527, value=encoded(Real(3))))
    )
    rows = service.compare(request)["rows"]
    assert len(rows) == 1 and rows[0]["kind"] == "record-class-changed"
    assert rows[0]["left"]["class_id"] == 526 and rows[0]["right"]["class_id"] == 527


def test_metadata_compares_as_unaligned_multiset_and_compression_is_separate(tmp_path):
    first = native_record(7, 1, [(2390, encoded(CharacterString("First metadata")))])
    second = native_record(7, 2, [(2390, encoded(CharacterString("Second metadata")))])
    _, service, request = setup(
        tmp_path,
        archive(record(), first, second),
        archive(second, first, record(), compressed=True),
    )
    report = service.compare(request)
    assert report["rows"] == [] and not report["files"][0]["equal"]
    assert report["structured_comparison"]["metadata_hash_multisets_equal"] is True
    assert report["left"]["metadata_records"]["count"] == 2


@pytest.mark.parametrize("second", [b"Opaque native source", archive(record(), record(index=11))])
def test_unsupported_or_ambiguous_record_sources_keep_file_evidence_without_alignment(
    tmp_path, second
):
    _, service, request = setup(tmp_path, second=second)
    report = service.compare(request)
    assert len(report["files"]) == 3
    assert not report["structured_comparison"]["supported"]
    assert not report["structured_comparison"]["scan_complete"]
    assert report["structured_comparison"]["reasons"] and report["rows"] == []


def test_unknown_saved_schema_and_changed_saved_bytes_never_merge_archive_values(tmp_path):
    storage, service, request = setup(tmp_path)
    files = storage.load(request["right"]["capture_id"])[1]
    request["right"] = source(storage, files[3])
    snap = retained(storage, {**files, 12: b"Different saved bytes"})
    request["right"] = {"capture_id": snap["id"], "snapshot_sha256": snap["evidence_sha256"]}
    report = service.compare(request)
    assert report["rows"] == [] and report["files"][0]["equal"]
    assert not report["files"][2]["equal"]


@pytest.mark.parametrize("budget", ["MAX_RECORDS", "MAX_PROPERTIES", "MAX_CHANGES"])
def test_budget_stop_is_explicit_even_with_no_displayed_differences(tmp_path, monkeypatch, budget):
    import bms_tool.native_backup_comparison as module

    monkeypatch.setattr(module, budget, 1)
    _, service, request = setup(
        tmp_path,
        archive(record("a"), record("b", index=11)),
        archive(record("a", value=encoded(Real(5))), record("b", index=11)),
    )
    report = service.compare(request | {"query": "no matching evidence"})
    assert report["rows"] == []
    assert not report["structured_comparison"]["scan_complete"]
    assert report["structured_comparison"]["budget_reason"]


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_any_tampered_original_file_refuses_pair(tmp_path, side, file_id):
    storage, service, request = setup(tmp_path)
    (storage.directory / request[side]["capture_id"] / f"file-{file_id}.bin").write_bytes(
        b"tampered"
    )
    with pytest.raises(ValueError, match="integrity"):
        service.compare(request)


@pytest.mark.parametrize("side", ["left", "right"])
def test_stale_manifest_is_not_rebound(tmp_path, side):
    _, service, request = setup(tmp_path)
    request[side]["snapshot_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="evidence changed"):
        service.compare(request)


def test_paging_query_and_scalar_preview_are_bounded_original_evidence(tmp_path):
    long = "x" * 600
    _, service, request = setup(
        tmp_path,
        archive(record(properties=[(65000, encoded(CharacterString(long)))])),
        archive(record(properties=[(65000, encoded(CharacterString(long + "y")))])),
    )
    first = service.compare(request | {"limit": 1})
    second = service.compare(request | {"offset": 1, "limit": 1})
    assert first["next_offset"] == 1 and second["next_offset"] is None
    assert second["rows"][0]["property"] == 65000
    assert second["rows"][0]["left"]["preview_truncated"]
    assert len(second["rows"][0]["left"]["scalar"]["value"]) == 256
    assert service.compare(request | {"query": "65000"})["total_matches"] == 1


def test_http_is_token_guarded_and_cannot_open_a_field_interface(tmp_path):
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    request = {side: source(storage, archive(record())) for side in ("left", "right")}
    with TestClient(app) as client:
        assert client.post(BASE, json=request).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(BASE, json=request, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["rows"] == []
        assert not client.get("/api/session").json()["field_network_open"]
        for changes in [
            {"address": "127.0.0.1:1"},
            {"limit": True},
            {"limit": 65},
            {"query": "x" * 257},
            {"offset": -1},
            {"left": {"capture_id": "../bad", "snapshot_sha256": "0" * 64}},
        ]:
            assert client.post(BASE, json=request | changes, headers=headers).status_code == 422


def test_added_and_removed_properties_keep_their_own_types(tmp_path):
    _, service, request = setup(
        tmp_path,
        archive(record(properties=[(900, encoded(Integer(-4)))])),
        archive(record(properties=[(901, encoded(Unsigned(4)))])),
    )
    rows = service.compare(request)["rows"]
    assert [(r["kind"], r["property"]) for r in rows] == [
        ("record-bytes-changed", None),
        ("property-removed", 900),
        ("property-added", 901),
    ]
    assert rows[1]["right"] is None and rows[1]["left"]["scalar"]["value"] == -4
    assert rows[2]["left"] is None and rows[2]["right"]["scalar"]["value"] == 4


def test_changed_metadata_is_visible_without_fabricating_property_alignment(tmp_path):
    first = native_record(7, 1, [(2390, encoded(CharacterString("Original metadata")))])
    second = native_record(7, 1, [(2390, encoded(CharacterString("Different metadata")))])
    _, service, request = setup(tmp_path, archive(record(), first), archive(record(), second))
    report = service.compare(request)
    assert report["rows"] == []
    assert report["structured_comparison"]["metadata_hash_multisets_equal"] is False
    assert report["structured_comparison"]["scan_complete"]
    assert not report["files"][0]["equal"] and not report["semantics_verified"]


def test_missing_interface_is_unknown_and_other_routes_remain_separate(tmp_path):
    storage, service, request = setup(tmp_path)
    files = storage.load(request["right"]["capture_id"])[1]
    other = retained(
        storage,
        files,
        connector_config=None,
        target={"address": "3001:8", "router": "127.0.0.1:49000", "dnet": 3001},
    )
    request["right"] = {"capture_id": other["id"], "snapshot_sha256": other["evidence_sha256"]}
    report = service.compare(request)
    assert report["same_recorded_interface"] is None and report["same_recorded_target"] is False
    assert report["left"]["target"]["address"] == "127.0.0.1:47819"
    assert report["right"]["target"]["address"] == "3001:8"


@pytest.mark.parametrize(
    "first,second",
    [
        ({"mac": True}, {"mac": 1}),
        ({"baudrate": 38400}, {"baudrate": 38400.0}),
        ({"port": "a"}, {"port": "b"}),
    ],
)
def test_recorded_interface_comparison_preserves_json_types(tmp_path, first, second):
    storage, service, request = setup(tmp_path)
    files = storage.load(request["left"]["capture_id"])[1]
    for side, config in [("left", first), ("right", second)]:
        snap = retained(storage, files, connector_config=config)
        request[side] = {"capture_id": snap["id"], "snapshot_sha256": snap["evidence_sha256"]}
    assert service.compare(request)["same_recorded_interface"] is False


def test_invalid_recorded_interface_never_becomes_a_same_interface_claim(tmp_path):
    storage, service, request = setup(tmp_path)
    files = storage.load(request["left"]["capture_id"])[1]
    for side in ["left", "right"]:
        snap = retained(storage, files, connector_config="Opaque historical metadata")
        request[side] = {"capture_id": snap["id"], "snapshot_sha256": snap["evidence_sha256"]}
    assert service.compare(request)["same_recorded_interface"] is None
