"""Literal saved Enum slots qualify numeric capacity, not state meanings."""

import copy

import pytest
from bms_tool.moi_effective_enum import PROFILE, EffectiveEnumCompiler, compiler_from_snapshot
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.mstp import header_crc

from .test_moi_enum_defaults import REF, enum_source
from .test_moi_parameters import parameters_source


def enum_files(*, cid=528, compressed=True, saved=513, slot=True):
    _, static, dynamic = parameters_source(compressed=compressed)
    archive = enum_source(cid=cid, compressed=compressed)
    if slot:
        # Independent literal 16-byte directory row: external selector,
        # property3113, saved flags, Enum storage kind9, native class, offset,
        # retained opaque footer. Payload uses the captured two-byte profile.
        row = (
            b"\x00\x10"
            + ((19 << 22) | 1).to_bytes(4, "big")
            + b"\x0c\x29\x6f\x09"
            + cid.to_bytes(2, "big")
            + len(dynamic).to_bytes(2, "big")
            + b"\x12\x34"
        )
        payload = saved.to_bytes(2, "big")
        static += row
        dynamic += payload + bytes([header_crc(payload) ^ 255])
    return {3: archive, 11: static, 12: dynamic}


@pytest.mark.parametrize("cid", [528, 529])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("value", [0, 255, 256, 65535])
def test_saved_enum_merge_preserves_other_settings_identity_metadata_and_originals(
    cid, compressed, value
):
    files = enum_files(cid=cid, compressed=compressed)
    originals = copy.deepcopy(files)
    compiler = EffectiveEnumCompiler(files)
    (field,) = compiler.fields()
    assert field["archive_value"] == 1 and field["effective_value"] == 513
    assert field["maximum_code"] == 65535
    assert field["saved_storage"]["datatype"] == 9 and field["saved_storage"]["bytes"] == 2
    assert not field["enum_semantics_verified"]
    output, proof = compiler.compile(
        record_ref=REF, encoded_sha256=field["encoded_sha256"], value=value
    )
    checked = MoiIdentity(output)
    record = checked.reader.records[REF]
    assert checked.reader.scalar(record, 3113) == value
    prop = record["properties"][3113]
    assert (
        checked.data[prop["value_start_offset"] : prop["value_end_offset"]]
        == b"\x92" + value.to_bytes(2, "big") + b"\x2f"
    )
    assert checked.reader.scalar(checked.root, 900) == 3.5
    assert checked.reader.scalar(checked.root, 901) == 70000
    assert checked.reader.scalar(checked.root, 902) == -300
    assert checked.reader.scalar(checked.root, 903) is True
    assert checked.reader.scalar(checked.root, 904) == "saved"
    assert checked.reader.scalar(record, 931) == 0x123
    assert checked.instance == 5136 and checked.summary()["name"] == "Authored controller"
    assert (
        proof["profile"] == PROFILE
        and proof["other_merged_bytes_preserved"]
        and proof["saved_settings_merged"]
    )
    assert (
        not proof["controller_write"]
        and not proof["field_transfer_enabled"]
        and not proof["enum_semantics_verified"]
    )
    assert proof["compiled_sha256"] == sha(output) and files == originals


@pytest.mark.parametrize("value", [65536, 4294967295])
def test_known_two_byte_saved_capacity_is_not_replaced_by_a_model_or_enum_label(value):
    compiler = EffectiveEnumCompiler(enum_files())
    (field,) = compiler.fields()
    with pytest.raises(ValueError, match="saved-storage capacity"):
        compiler.compile(record_ref=REF, encoded_sha256=field["encoded_sha256"], value=value)


def test_without_a_saved_slot_only_local_unsigned32_representation_is_checked():
    compiler = EffectiveEnumCompiler(enum_files(slot=False))
    (field,) = compiler.fields()
    assert field["saved_storage"] is None and field["maximum_code"] == 4294967295
    assert field["archive_value"] == field["effective_value"] == 1
    output, proof = compiler.compile(
        record_ref=REF, encoded_sha256=field["encoded_sha256"], value=4294967295
    )
    actual = MoiIdentity(output)
    assert actual.reader.scalar(actual.reader.records[REF], 3113) == 4294967295
    assert proof["saved_storage"] is None and not proof["enum_semantics_verified"]


def test_no_selected_edit_returns_merged_settings_instead_of_the_original_archive():
    files = enum_files()
    compiler = EffectiveEnumCompiler(files)
    (field,) = compiler.fields()
    output, proof = compiler.compile(
        record_ref=REF, encoded_sha256=field["encoded_sha256"], value=513
    )
    assert output == compiler.merged and output != files[3]
    assert proof["selected_edit"]["changed"] is False and proof["saved_settings_merged"]


def test_bad_checksum_wrong_datatype_and_old_encoded_fingerprints_are_refused():
    files = enum_files()
    bad = files | {12: files[12][:-1] + bytes([files[12][-1] ^ 1])}
    with pytest.raises(ValueError, match="checksum"):
        EffectiveEnumCompiler(bad)
    # Change only the final row's type9 Enumerated to type18 Unsigned (same
    # payload width), retaining its payload/CRC; datatype consistency must fail.
    static = bytearray(files[11])
    static[-7] = 18
    with pytest.raises(ValueError, match="datatype differs"):
        EffectiveEnumCompiler(files | {11: bytes(static)})
    compiler = EffectiveEnumCompiler(files)
    original = compiler.archive.candidates[REF][1]["encoded_sha256"]
    with pytest.raises(ValueError, match="encoding changed"):
        compiler.compile(record_ref=REF, encoded_sha256=original, value=2)


@pytest.mark.parametrize("fault", ["unverified", "vendor", "instance", "name", "model"])
def test_recorded_snapshot_identity_is_required_without_claiming_current_identity(fault):
    files = enum_files()
    snapshot = {
        "source_identity_matches": True,
        "device": "device,5136",
        "identity": {
            "vendor-identifier": 5,
            "object-name": "Authored controller",
            "model-name": "UNLISTED-MODEL",
        },
    }
    if fault == "unverified":
        snapshot["source_identity_matches"] = False
    if fault == "vendor":
        snapshot["identity"]["vendor-identifier"] = 99
    if fault == "instance":
        snapshot["device"] = "device,5137"
    if fault == "name":
        snapshot["identity"]["object-name"] = "Another"
    if fault == "model":
        snapshot["identity"]["model-name"] = "Another"
    with pytest.raises(ValueError):
        compiler_from_snapshot(snapshot, files)
