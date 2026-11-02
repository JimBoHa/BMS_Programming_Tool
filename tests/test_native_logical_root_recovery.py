"""Logical-root storage stays qualified through a previous-instance proposal."""

import gzip
import struct

import pytest
from bms_tool.application_preservation import verify_preservation
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_applications import NativeApplications

from . import test_native_instance_recovery as fixture


def logical_root_files(original, **options):
    files = original(**options)
    app = MoiIdentity(files[3])
    reference = app.root["properties"][32527]
    rebuilt, previous = bytearray(app.data[:14]), 14
    for record in app.records:
        raw = app.data[record["offset"] : record["end_offset"]]
        if record is app.root:
            start = reference["value_start_offset"] - record["offset"]
            end = reference["value_end_offset"] - record["offset"]
            # Independent UTF8 CharacterString("8-41") and closing context2.
            raw = raw[:start] + bytes.fromhex("750500382d34312f") + raw[end:]
        prefix = record["offset"] - previous
        rebuilt.extend(
            b"\x00\x00" + struct.pack("<I", len(raw) + 6)
            if prefix == 6
            else struct.pack("<H", len(raw) + 2)
        )
        rebuilt.extend(raw)
        previous = record["end_offset"]
    native = bytes(rebuilt)
    payload = gzip.compress(native, mtime=0) if app.compressed else native
    return {**files, 3: payload, 11: fixture.rekey(files[11], 5136, 41)}


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
def test_declared_logical_root_preserves_all_settings_through_inverse_instance_proposal(
    tmp_path, monkeypatch, compressed, extended
):
    original = fixture.signal_files
    monkeypatch.setattr(
        fixture, "signal_files", lambda **options: logical_root_files(original, **options)
    )
    storage, service, request, before, _, files = fixture.setup(
        tmp_path, compressed=compressed, extended=extended
    )
    original_receipt = storage.receipt(request["receipt_id"])
    original_before = storage.load(before["id"])
    report = service.prepare(request)
    assert report["proposal"]["new_instance"] == 5136
    assert report["current_instance"] == 5336 and report["origin"]["root_ref"] == "8-41"
    assert (
        not report["controller_queries"] and not report["field_actions"] and not report["can_apply"]
    )
    inverse, _ = NativeApplications.compile(files, 5136)
    assert MoiIdentity(inverse).ref == "8-41" and MoiIdentity(inverse).instance == 5136
    preserved = verify_preservation(
        files, {**files, 3: inverse}, old_instance=5336, new_instance=5136
    )
    assert preserved["saved_application_parameters_verified"] == 9
    assert storage.receipt(request["receipt_id"]) == original_receipt
    assert storage.load(before["id"]) == original_before
