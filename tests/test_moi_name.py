"""Name-only edits preserve native encodings, record bodies and Device instances."""

import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, OctetString
from bms_tool.moi_identity import MoiIdentity

from .test_controller_application import encoded, native_record
from .test_moi_identity import source


def rename(editor, name, **changes):
    query = {
        "source_sha256": editor.source_sha256,
        "expected_instance": editor.instance,
        "new_instance": editor.instance,
        "expected_name": editor.summary()["name"],
        "new_name": name,
        **changes,
    }
    plan = editor.preview(**query)
    output, report = editor.export(**query, plan_sha256=plan["plan_sha256"])
    return MoiIdentity(output), report


@pytest.mark.parametrize("encoding", [0, 3, 4, 5])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("new_name", ["X", "Another controller with a longer name"])
def test_rename_preserves_every_non_name_record_byte_and_native_encoding(
    encoding, compressed, new_name
):
    original = MoiIdentity(
        source(cid=777, modules=12, compressed=compressed, name_encoding=encoding)
    )
    changed, report = rename(original, new_name)
    assert changed.instance == original.instance == 5136
    assert changed.summary()["name"] == new_name
    assert changed.summary()["root_ref"] == original.summary()["root_ref"]
    assert len(changed.records) == len(original.records)
    assert report["edits"][0]["character_encoding"] == encoding
    for before, after in zip(original.records, changed.records, strict=True):
        left = original.data[before["offset"] : before["end_offset"]]
        right = changed.data[after["offset"] : after["end_offset"]]
        if before is original.root:
            a, b = before["properties"][2390], after["properties"][2390]
            assert (
                original.data[before["offset"] : a["value_start_offset"]]
                == changed.data[after["offset"] : b["value_start_offset"]]
            )
            assert (
                original.data[a["value_end_offset"] : before["end_offset"]]
                == changed.data[b["value_end_offset"] : after["end_offset"]]
            )
        else:
            assert left == right


def test_unicode_name_keeps_utf16_encoding_and_noop_is_exact():
    original = MoiIdentity(source(name_encoding=4, compressed=True))
    changed, _ = rename(original, "Zone contrôlée Ω")
    assert changed.summary()["name"] == "Zone contrôlée Ω"
    same, report = rename(original, original.summary()["name"])
    assert same.source == original.source and report["edits"] == []


@pytest.mark.parametrize("name", ["", " X", "X ", "X\x00", "X\n", "X" * 129, 123])
def test_invalid_names_fail_before_a_plan(name):
    with pytest.raises(ValueError):
        rename(MoiIdentity(source()), name)


def test_name_review_rejects_stale_name_and_combined_instance_change():
    editor = MoiIdentity(source())
    with pytest.raises(ValueError, match="name changed"):
        rename(editor, "New", expected_name="Stale")
    with pytest.raises(ValueError, match="not both"):
        rename(editor, "New", new_instance=5336)


def test_name_growth_promotes_only_root_record_to_extended_framing():
    def root(padding):
        return native_record(
            470,
            5136,
            [
                (32527, encoded(CharacterString("root"))),
                (75, encoded(ObjectIdentifier((8, 5136)))),
                (2390, encoded(CharacterString("A"))),
                (70, encoded(CharacterString("Unlisted"))),
                (65000, encoded(OctetString(b"x" * padding))),
            ],
        )

    padding = 65000
    padding += 65535 - len(root(padding)) - 2
    record = root(padding)
    assert len(record) + 2 == 65535
    content = (
        struct.pack("<6sHHI", b"\x02\x00MOI\x00", 470, 1, 1)
        + struct.pack("<H", len(record) + 2)
        + record
    )
    editor = MoiIdentity(content)
    changed, _ = rename(editor, "A much longer reviewed name")
    assert changed.data[14:16] == b"\x00\x00" and changed.instance == 5136
    assert changed.summary()["name"] == "A much longer reviewed name"
    assert changed.data.endswith(b"x" * 100 + b"\x2f\x1f")
