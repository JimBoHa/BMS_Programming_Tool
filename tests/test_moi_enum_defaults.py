"""Literal Enum application tags, record framing, gzip and opaque preservation."""

import gzip
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier
from bms_tool.moi_enum_defaults import PROFILE, MoiEnumDefaults
from bms_tool.moi_identity import MoiIdentity, sha

from .test_controller_application import encoded, native_record
from .test_moi_parameters import parameters_source

REF = "controller/enum-1"


def enum_source(
    *, code=1, width=1, compressed=True, cid=528, padding=0, extended=False, value=None
):
    base, _, _ = parameters_source(compressed=False)
    # Independently authored BACnet Enumerated application tag plus the native
    # property closing tag; no production Enum encoder supplies this fixture.
    tagged = bytes([0x90 | width]) + code.to_bytes(width, "big") if value is None else value
    record = native_record(
        cid,
        1,
        [
            (32527, encoded(CharacterString(REF))),
            (75, encoded(ObjectIdentifier((cid, 1)))),
            (3113, tagged),
            (931, b"\x92\x01\x23"),
            (65000, encoded(CharacterString("x" * padding))),
        ],
    )
    root = bytearray(base)
    struct.pack_into("<I", root, 10, struct.unpack_from("<I", root, 10)[0] + 1)
    prefix = (
        b"\x00\x00" + struct.pack("<I", len(record) + 6)
        if extended or len(record) + 2 > 65535
        else struct.pack("<H", len(record) + 2)
    )
    raw = bytes(root) + prefix + record
    return gzip.compress(raw, mtime=123) if compressed else raw


def request(source, value):
    editor = MoiEnumDefaults(source)
    record, prop = editor.candidates[REF]
    return {
        "source_sha256": sha(source),
        "record_ref": REF,
        "encoded_sha256": prop["encoded_sha256"],
        "value": value,
    }


@pytest.mark.parametrize("cid", [528, 529])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize(
    "before,old_width,after,new_width",
    [
        (0, 1, 255, 1),
        (255, 1, 256, 2),
        (65535, 2, 65536, 3),
        (16777215, 3, 4294967295, 4),
        (4294967295, 4, 0, 4),
    ],
)
def test_unsigned32_code_and_growth_preserve_every_unrelated_byte(
    cid, compressed, before, old_width, after, new_width
):
    source = enum_source(code=before, width=old_width, compressed=compressed, cid=cid)
    editor = MoiEnumDefaults(source)
    args = request(source, after)
    plan = editor.preview(**args)
    output, result = editor.export(**args, plan_sha256=plan["plan_sha256"])
    assert (
        plan["profile"] == PROFILE
        and plan["before_value"] == before
        and plan["after_value"] == after
    )
    assert plan["after_value_width"] == new_width
    assert result["unrelated_native_bytes_preserved"] and not plan["enum_semantics_verified"]
    assert not plan["controller_write"] and not plan["saved_settings_merged"]
    actual = MoiIdentity(output)
    record = actual.reader.records[REF]
    assert actual.reader.scalar(record, 3113) == after
    assert (
        actual.data[
            record["properties"][3113]["value_start_offset"] : record["properties"][3113][
                "value_end_offset"
            ]
        ]
        == bytes([0x90 | new_width]) + after.to_bytes(new_width, "big") + b"\x2f"
    )
    assert actual.instance == 5136 and actual.summary()["name"] == "Authored controller"
    for old, new in zip(editor.editor.records[:-1], actual.records[:-1], strict=True):
        assert (
            editor.editor.data[old["offset"] : old["end_offset"]]
            == actual.data[new["offset"] : new["end_offset"]]
        )
    assert actual.reader.scalar(record, 931) == 0x123
    if compressed:
        assert output[:10] == source[:10]


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_noop_retains_original_archive_bytes_including_nonminimal_value_width(compressed, width):
    source = enum_source(code=1, width=width, compressed=compressed, extended=True)
    editor = MoiEnumDefaults(source)
    args = request(source, 1)
    plan = editor.preview(**args)
    output, report = editor.export(**args, plan_sha256=plan["plan_sha256"])
    assert output == source and not report["changed"] and report["unrelated_native_bytes_preserved"]


def test_value_growth_can_promote_the_selected_record_to_extended_framing():
    # Choose the exact boundary using an authored literal record, then grow only
    # the Enum payload by three bytes across the short-record length limit.
    initial = enum_source(compressed=False)
    selected = MoiIdentity(initial).records[-1]
    raw_length = selected["end_offset"] - selected["offset"]
    padding = 65533 - raw_length - 3  # CharacterString's extended length header adds three bytes.
    source = enum_source(padding=padding, compressed=False)
    old = MoiIdentity(source)
    selected = old.records[-1]
    assert selected["end_offset"] - selected["offset"] <= 65533
    editor = MoiEnumDefaults(source)
    args = request(source, 4294967295)
    plan = editor.preview(**args)
    output, _ = editor.export(**args, plan_sha256=plan["plan_sha256"])
    new = MoiIdentity(output)
    assert new.records[-1]["offset"] - new.records[-2]["end_offset"] == 6


@pytest.mark.parametrize("value", [True, False, -1, 4294967296, 1.0, "1", None])
def test_invalid_code_coercions_are_rejected(value):
    source = enum_source()
    editor = MoiEnumDefaults(source)
    with pytest.raises(ValueError, match="unsigned32"):
        editor.preview(**(request(source, 1) | {"value": value}))


@pytest.mark.parametrize(
    "field,value",
    [("source_sha256", "0" * 64), ("record_ref", "controller/other"), ("encoded_sha256", "0" * 64)],
)
def test_stale_source_field_and_encoding_are_refused(field, value):
    source = enum_source()
    editor = MoiEnumDefaults(source)
    with pytest.raises(ValueError):
        editor.preview(**(request(source, 2) | {field: value}))


@pytest.mark.parametrize(
    "cid,value", [(530, b"\x91\x01"), (528, b"\x21\x01"), (529, b"\x31\x01"), (528, b"\x10")]
)
def test_other_classes_unsigned_integer_and_boolean_tags_are_not_enum_candidates(cid, value):
    assert MoiEnumDefaults(enum_source(cid=cid, value=value)).candidates == {}


def test_changed_review_cannot_export_and_future_headers_are_not_rewritten():
    source = enum_source()
    editor = MoiEnumDefaults(source)
    with pytest.raises(ValueError, match="review changed"):
        editor.export(**request(source, 2), plan_sha256="0" * 64)
    changed = bytearray(source)
    changed[3] = 8
    with pytest.raises(ValueError):
        MoiEnumDefaults(bytes(changed))
