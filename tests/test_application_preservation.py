"""Authored differing programs, parameter stores and expansion inventories."""

import gzip
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, Real, Unsigned
from bms_tool.application_preservation import verify_preservation
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc

from .test_controller_application import encoded, native_record
from .test_moi_parameters import parameters_source


def snapshots(*, model="UNLISTED-MODEL", cid=470, modules=5, compressed=True):
    archive, static, dynamic = parameters_source(
        model=model, cid=cid, modules=modules, compressed=compressed
    )
    before = {3: archive, 11: static, 12: dynamic}
    merged, _ = ParameterApplication(archive, static, dynamic).compile()
    app = MoiIdentity(merged)
    query = dict(source_sha256=app.source_sha256, expected_instance=5136, new_instance=5336)
    plan = app.preview(**query)
    changed, _ = app.export(**query, plan_sha256=plan["plan_sha256"])
    updated = bytearray(static)
    offset = 0
    while offset < len(updated):
        size = int.from_bytes(updated[offset : offset + 2], "big")
        updated[offset + 2 : offset + 6] = ((8 << 22) | 5336).to_bytes(4, "big")
        offset += size
    return before, {3: changed, 11: bytes(updated), 12: dynamic}


@pytest.mark.parametrize(
    "model,cid,modules", [("HEAT-PUMP", 194, 0), ("VAV", 470, 5), ("OTHER", 777, 12)]
)
@pytest.mark.parametrize("compressed", [True, False])
def test_each_own_program_and_saved_values_are_preserved(model, cid, modules, compressed):
    before, after = snapshots(model=model, cid=cid, modules=modules, compressed=compressed)
    report = verify_preservation(before, after, old_instance=5136, new_instance=5336)
    assert report["application_identical_except_instance"] is True
    assert report["saved_application_parameters_verified"] == 7
    assert report["runtime_counter_changes"] == []
    assert not report["controller_writes"]
    # The verified controller has the saved value, not the archive's old draft.
    actual = MoiIdentity(after[3])
    assert actual.reader.scalar(actual.root, 900) == 3.5
    assert actual.reader.scalar(actual.root, 904) == "saved"


def test_smaller_post_directory_does_not_mean_the_application_lost_settings():
    before, after = snapshots()
    after[11], after[12] = after[11][:32], after[12][:4]
    report = verify_preservation(before, after, old_instance=5136, new_instance=5336)
    assert report["saved_application_parameters_verified"] == 7
    assert report["post_saved_parameters"] == 2


def test_replacing_an_unknown_expansion_property_is_rejected():
    before, after = snapshots()
    raw = gzip.decompress(after[3]).replace(b"opaque footer", b"unsafe footer")
    after[3] = gzip.compress(raw, mtime=0)
    with pytest.raises(ValueError, match="Non-identity application"):
        verify_preservation(before, after, old_instance=5136, new_instance=5336)


def test_another_controllers_application_is_rejected():
    before, _ = snapshots(model="HEAT-PUMP", modules=5)
    _, other = snapshots(model="COOLING-ONLY", modules=0)
    with pytest.raises(ValueError, match="Non-identity application"):
        verify_preservation(before, other, old_instance=5136, new_instance=5336)


def test_changed_current_saved_setpoint_is_rejected_even_with_matching_application():
    before, after = snapshots()
    after[11] = after[11].replace(b"saved", b"other")
    with pytest.raises(ValueError, match="current saved parameter differs"):
        verify_preservation(before, after, old_instance=5136, new_instance=5336)


def test_invalid_post_parameter_crc_is_rejected():
    before, after = snapshots()
    bad = bytearray(after[12])
    bad[0] ^= 1
    after[12] = bytes(bad)
    with pytest.raises(ValueError, match="checksum"):
        verify_preservation(before, after, old_instance=5136, new_instance=5336)


def test_elapsed_runtime_counter_can_advance_without_changing_configuration():
    before, after = snapshots(compressed=False)
    counter = native_record(
        168,
        17,
        [(32527, encoded(CharacterString("controller/run-counter"))), (33, encoded(Unsigned(10)))],
    )
    framed = struct.pack("<H", len(counter) + 2) + counter
    for files in (before, after):
        data = bytearray(files[3])
        struct.pack_into("<I", data, 10, struct.unpack_from("<I", data, 10)[0] + 1)
        data.extend(framed)
        files[3] = bytes(data)
        position = len(files[12])
        payload = (10 if files is before else 11).to_bytes(4, "big")
        files[12] += payload + bytes([header_crc(payload) ^ 255])
        body = ((3 << 22) | 17).to_bytes(4, "big") + (33).to_bytes(2, "big")
        body += b"\x6f\x02" + (168).to_bytes(2, "big") + position.to_bytes(2, "big") + b"\x12\x34"
        files[11] += (len(body) + 2).to_bytes(2, "big") + body
    report = verify_preservation(before, after, old_instance=5136, new_instance=5336)
    assert report["saved_application_parameters_verified"] == 8
    assert report["runtime_counter_changes"] == [
        {
            "class": 168,
            "instance": 17,
            "property": 33,
            "changed": True,
            "property_name": "Elapsed Active Time",
        }
    ]


def test_wrong_instance_or_incomplete_capture_cannot_pass():
    before, after = snapshots()
    with pytest.raises(ValueError, match="identities"):
        verify_preservation(before, after, old_instance=5136, new_instance=5337)
    with pytest.raises(ValueError, match="complete native snapshots"):
        verify_preservation(before, {3: after[3]}, old_instance=5136, new_instance=5336)


def renamed_snapshots():
    before, _ = snapshots()
    merged, _ = ParameterApplication(before[3], before[11], before[12]).compile()
    editor = MoiIdentity(merged)
    query = dict(
        source_sha256=editor.source_sha256,
        expected_instance=5136,
        new_instance=5136,
        expected_name=editor.summary()["name"],
        new_name="Reviewed name",
    )
    plan = editor.preview(**query)
    output, _ = editor.export(**query, plan_sha256=plan["plan_sha256"])
    return before, {3: output, 11: before[11], 12: before[12]}


def name_proof(before, after):
    return verify_preservation(
        before,
        after,
        old_instance=5136,
        new_instance=5136,
        old_name="Authored controller",
        new_name="Reviewed name",
    )


def test_name_only_preserves_different_program_and_seven_live_saved_settings():
    before, after = renamed_snapshots()
    proof = name_proof(before, after)
    assert proof["application_identical_except_name"] is True
    assert proof["application_identical_except_instance"] is False
    assert proof["saved_application_parameters_verified"] == 7


def test_name_edit_cannot_hide_an_unrelated_application_record_change():
    before, after = renamed_snapshots()
    after[3] = gzip.compress(
        gzip.decompress(after[3]).replace(b"opaque footer", b"unsafe footer"), mtime=0
    )
    with pytest.raises(ValueError, match="non-name application record"):
        name_proof(before, after)


def test_name_edit_cannot_hide_a_changed_current_saved_value():
    before, after = renamed_snapshots()
    after[11] = after[11].replace(b"saved", b"other")
    with pytest.raises(ValueError, match="current saved parameter differs"):
        name_proof(before, after)


def add_saved_real(files, cid, pid, current):
    record = native_record(
        cid, 73, [(32527, encoded(CharacterString("controller/flow"))), (pid, encoded(Real(0.25)))]
    )
    raw = bytearray(gzip.decompress(files[3]))
    struct.pack_into("<I", raw, 10, struct.unpack_from("<I", raw, 10)[0] + 1)
    raw.extend(struct.pack("<H", len(record) + 2) + record)
    files[3] = gzip.compress(raw, mtime=0)
    position = len(files[12])
    payload = struct.pack(">f", current)
    files[12] += payload + bytes([header_crc(payload) ^ 255])
    body = ((2 << 22) | 73).to_bytes(4, "big") + pid.to_bytes(2, "big")
    body += b"\x6f\x04" + cid.to_bytes(2, "big") + position.to_bytes(2, "big") + b"\x12\x34"
    files[11] += (len(body) + 2).to_bytes(2, "big") + body


def test_calculated_flow_zero_offset_is_reported_separately_from_settings():
    before, after = renamed_snapshots()
    add_saved_real(before, 570, 3506, 0.25)
    add_saved_real(after, 570, 3506, -0.125)
    proof = name_proof(before, after)
    assert proof["saved_application_parameters_verified"] == 8
    assert proof["runtime_counter_changes"] == []
    assert proof["device_calculated_changes"] == [
        {
            "class": 570,
            "instance": 73,
            "property": 3506,
            "changed": True,
            "property_name": "Autocalibrate Offset",
            "application_value": 0.25,
            "current_saved_value": -0.125,
            "reason": "Flow module calculated zero-flow calibration output",
        }
    ]


@pytest.mark.parametrize("cid,pid", [(571, 3506), (570, 3505), (570, 900)])
def test_flow_exception_cannot_allow_other_parameters_or_other_module_classes(cid, pid):
    before, after = renamed_snapshots()
    add_saved_real(before, cid, pid, 0.25)
    add_saved_real(after, cid, pid, -0.125)
    with pytest.raises(ValueError, match="current saved parameter differs"):
        name_proof(before, after)


def test_flow_calibration_nonfinite_saved_value_still_fails():
    before, after = renamed_snapshots()
    add_saved_real(before, 570, 3506, 0.25)
    add_saved_real(after, 570, 3506, float("nan"))
    with pytest.raises(ValueError, match="Nonfinite"):
        name_proof(before, after)
