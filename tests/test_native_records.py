"""Bounded inspection of actual native source records, not physical I/O inventories."""

import hashlib

import pytest
from bms_tool.controller_application import ControllerApplication
from bms_tool.moi_application import MoiApplication

from .test_bacnet_files import link as link
from .test_controller_application import authored_application
from .test_moi_identity import source


@pytest.mark.parametrize("compressed", [False, True])
def test_engineering_and_metadata_records_keep_source_ids_offsets_and_hashes(compressed):
    app = MoiApplication(source(modules=3, compressed=compressed))
    first = app.record_inventory(limit=2)
    second = app.record_inventory(offset=first["next_offset"], limit=2)
    last = app.record_inventory(offset=second["next_offset"], limit=2)
    rows = first["records"] + second["records"] + last["records"]
    assert first["recognized_record_count"] == 5 and len(rows) == 5
    assert len({row["id"] for row in rows}) == 5
    assert first["coverage"] == "recognized-records-only"
    assert first["record_framing"] == "declared-lengths"
    assert last["next_offset"] is None
    assert [row["kind"] for row in rows] == ["engineering"] * 4 + ["metadata"]
    for row in rows:
        raw = app.data[row["expanded_offset"] : row["expanded_end_offset"]]
        assert len(raw) == row["expanded_bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["record_sha256"]
    metadata = app.record_details(rows[-1]["id"])
    prop = metadata["properties"][0]
    assert prop["id"] == 65001 and prop["scalar"] is None and "tags" not in prop
    assert prop["encoded_bytes"] == prop["value_end_offset"] - prop["value_start_offset"]
    assert (
        prop["encoded_sha256"]
        == hashlib.sha256(
            app.data[prop["value_start_offset"] : prop["value_end_offset"]]
        ).hexdigest()
    )


def test_search_is_literal_case_insensitive_and_includes_stored_property_values():
    app = MoiApplication(source(modules=2, model="UNKNOWN-NATIVE-MODEL"))
    assert app.record_inventory(query="unknown-native-model")["total_matches"] == 1
    assert app.record_inventory(query="65001")["records"][0]["kind"] == "metadata"
    assert app.record_inventory(query="UNLISTED EXPANSION")["total_matches"] == 2
    assert app.record_inventory(query="[.*")["total_matches"] == 0
    assert app.record_inventory(offset=100)["records"] == []


def test_properties_page_without_reordering_or_losing_unknown_values():
    app = MoiApplication(source())
    record = app.record_inventory()["records"][0]
    full = app.record_details(record["id"])
    first = app.record_details(record["id"], limit=2)
    second = app.record_details(record["id"], offset=2, limit=2)
    assert first["properties"] + second["properties"] == full["properties"][:4]
    assert [prop["index"] for prop in full["properties"]] == list(range(record["property_count"]))
    found = app.record_details(record["id"], query="UNLISTED-CONTROLLER")
    assert found["total_matches"] == 1 and found["properties"][0]["id"] == 70
    assert found["offset_scope"] == "expanded application bytes"
    with pytest.raises(ValueError, match="actual record"):
        app.record_details("record:0")


def test_reference_scan_coverage_is_distinct_from_declared_native_framing():
    app = MoiApplication(authored_application())
    report = app.record_inventory()
    assert report["record_framing"] == "scanned-reference-records"
    assert report["recognized_record_count"] == 3
    assert report["records"][1]["object"] == "analog-value,10"
    props = app.record_details(report["records"][1]["id"])["properties"]
    assert next(prop for prop in props if prop["id"] == 65000)["scalar"] is None


async def test_record_reads_use_only_retained_bytes_and_reject_other_target_or_interface(link):
    peer, connector, files, target = link
    peer.payload = source(modules=2)
    peer.stream.fileType = ".moi"
    peer.stream.fileSize = len(peer.payload)
    service = ControllerApplication(connector, connector.store, files)
    captured = await service.read_application(target)
    requests = list(peer.all_requests)
    options = {**target, "capture_id": captured["receipt"]["id"]}
    report = service.records(options)
    detail = service.records({**options, "record_id": report["records"][0]["id"]}, detail=True)
    assert report["capture_id"] == detail["capture_id"] == captured["receipt"]["id"]
    assert report["sha256"] == detail["sha256"] == captured["receipt"]["sha256"]
    assert report["read_only"] and detail["read_only"]
    assert not report["field_actions"] and not report["identity_verified"]
    assert peer.all_requests == requests
    with pytest.raises(ValueError, match="different controller"):
        service.records({**options, "address": "127.0.0.1:49999"})
    connector.config = {**connector.config, "instance": 200}
    with pytest.raises(ValueError, match="different controller"):
        service.records(options)
    assert peer.all_requests == requests
