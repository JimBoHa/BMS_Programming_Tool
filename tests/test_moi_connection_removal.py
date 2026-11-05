"""Literal whole-application deletion oracles, independent of removal implementation."""

import copy
import gzip

import pytest
from bacpypes3.primitivedata import Boolean, CharacterString, Unsigned
from bms_tool.moi_connection_removal import MoiConnectionRemoval
from bms_tool.moi_identity import MoiIdentity, seal, sha

from .test_controller_application import encoded
from .test_moi_connection_copies import authored, frames, packed, property_bytes
from .test_moi_wire_sources import REF

WIRES = [(0, 85, 2, 7000), (1, 85, 3, 7000), (0, 86, 3, 7001)]
LITERAL = [
    bytes.fromhex("3e210021552102221b583f"),
    bytes.fromhex("3e210121552103221b583f"),
    bytes.fromhex("3e210021562103221b593f"),
]
METADATA = [
    b"\x3e" + encoded(Boolean(True)) + encoded(CharacterString("first")) + b"\x3f",
    b"\x3e" + encoded(Boolean(False)) + encoded(CharacterString("middle é🙂")) + b"\x3f",
    b"\x3e" + encoded(Boolean(True)) + encoded(CharacterString("")) + b"\x3f",
]


def request(editor, index=0, **changes):
    selected = editor.inspect(REF, index)
    return {
        "source_sha256": editor.editor.source_sha256,
        "diagram_ref": REF,
        "record_sha256": selected["record_sha256"],
        "property_sha256": selected["property_sha256"],
        "metadata_property_sha256": selected["metadata_property_sha256"],
        "wire_index": index,
        "old": selected["selected_wire"]["old"] if selected["selected_wire"] else [],
        "connection_count": selected["connection_count"],
        **changes,
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
@pytest.mark.parametrize("metadata_first", [False, True])
@pytest.mark.parametrize("positions", [False, True])
@pytest.mark.parametrize("metadata_present", [False, True])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_literal_wire_and_its_metadata_row_are_the_only_removed_bytes(
    compressed, extended, diagram_class, metadata_first, positions, metadata_present, index
):
    raw = authored(
        compressed=compressed,
        extended=extended,
        diagram_class=diagram_class,
        metadata=b"".join(METADATA) if metadata_present else None,
        metadata_first=metadata_first,
        positions=positions,
        wires=WIRES,
    )
    editor = MoiConnectionRemoval(raw)
    before = editor.editor.data
    unchanged = copy.deepcopy(editor.wire.reader.summary())
    output, report = editor.compile(**request(editor, index))
    checked = MoiIdentity(output)
    expected = []
    for width, body in frames(before):
        if int.from_bytes(body[:2], "little") == diagram_class:
            old_wire = property_bytes(3118, b"".join(LITERAL))
            old_meta = property_bytes(3384, b"".join(METADATA))
            assert body.count(old_wire) == 1
            body = body.replace(
                old_wire,
                property_bytes(3118, b"".join(LITERAL[:index] + LITERAL[index + 1 :])),
                1,
            )
            if metadata_present:
                assert body.count(old_meta) == 1
                body = body.replace(
                    old_meta,
                    property_bytes(3384, b"".join(METADATA[:index] + METADATA[index + 1 :])),
                    1,
                )
        expected.append((width, body))
    assert checked.data == packed(before[:14], expected)
    assert report["removed_encoding_hex"] == LITERAL[index].hex()
    assert report["removed_continuation_sha256"] == (
        sha(METADATA[index]) if metadata_present else None
    )
    assert report["removed_continuation_bytes"] == (len(METADATA[index]) if metadata_present else 0)
    assert report["native_bytes_growth"] == -len(LITERAL[index]) - (
        len(METADATA[index]) if metadata_present else 0
    )
    assert report["record_prefix_growth"] == 0
    assert report["connection_count_before"] == 3 and report["connection_count_after"] == 2
    graph = checked.reader.diagram(REF)
    assert [w["index"] for w in graph["connections"]] == [0, 1]
    assert graph["execution_order"] == [0, 1, 2, 3] and graph["native_layout"] is positions
    assert len(graph["blocks"]) == 4
    assert editor.editor.source == raw and editor.editor.data == before
    assert editor.wire.reader.summary() == unchanged
    assert report["native_structure_readback_verified"] and report["other_expanded_bytes_preserved"]
    assert report["destination_configuration_preserved"]
    assert not any(
        report[k]
        for k in [
            "controller_write",
            "field_transfer_enabled",
            "saved_settings_merged",
            "native_fallback_or_retention_verified",
        ]
    )
    body = {k: v for k, v in report.items() if k != "compilation_sha256"}
    assert seal(body) == report["compilation_sha256"]
    if compressed:
        assert output[:10] == raw[:10] and gzip.decompress(output) == checked.data


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("metadata", [False, True])
@pytest.mark.parametrize("extended", [False, True])
def test_final_connection_leaves_explicit_empty_arrays_and_all_blocks(
    compressed, metadata, extended
):
    raw = authored(
        wires=[WIRES[0]],
        metadata=METADATA[0] if metadata else None,
        compressed=compressed,
        extended=extended,
    )
    editor = MoiConnectionRemoval(raw)
    output, report = editor.compile(**request(editor))
    checked = MoiIdentity(output)
    expected = []
    for width, body in frames(editor.editor.data):
        if int.from_bytes(body[:2], "little") == 575:
            body = body.replace(property_bytes(3118, LITERAL[0]), property_bytes(3118, b""), 1)
            if metadata:
                body = body.replace(property_bytes(3384, METADATA[0]), property_bytes(3384, b""), 1)
        expected.append((width, body))
    assert checked.data == packed(editor.editor.data[:14], expected)
    after = MoiConnectionRemoval(output).inspect(REF)
    assert after["connection_count"] == 0 and after["selected_wire"] is None
    assert not after["available"] and after["block_count"] == 4
    assert (3384 in checked.reader.records[REF]["properties"]) is metadata
    assert report["removed_continuation_sha256"] == (sha(METADATA[0]) if metadata else None)
    with pytest.raises(ValueError, match="exact existing"):
        MoiConnectionRemoval(output).compile(**request(MoiConnectionRemoval(output)))


@pytest.mark.parametrize("width", [1, 2, 3, 4])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_removal_preserves_every_other_recorded_unsigned_width(width, index):
    raw = authored(wires=WIRES, source_index_width=width, compressed=False)
    editor = MoiConnectionRemoval(raw)
    output, _ = editor.compile(**request(editor, index))
    literal = [
        b"\x3e" + bytes([0x20 | width]) + w[0].to_bytes(width, "big") + LITERAL[n][3:]
        for n, w in enumerate(WIRES)
    ]
    expected = []
    for prefix, body in frames(raw):
        if int.from_bytes(body[:2], "little") == 575:
            body = body.replace(
                property_bytes(3118, b"".join(literal)),
                property_bytes(3118, b"".join(literal[:index] + literal[index + 1 :])),
                1,
            )
        expected.append((prefix, body))
    assert output == packed(raw[:14], expected)


def test_large_record_keeps_its_original_wide_prefix_after_crossing_short_threshold():
    raw = authored(compressed=False, pad_to=65536)
    editor = MoiConnectionRemoval(raw)
    output, report = editor.compile(**request(editor))
    before, after = frames(raw), frames(output)
    for (a, old), (b, new) in zip(before, after, strict=True):
        assert a == b
        if int.from_bytes(old[:2], "little") == 575:
            assert a == b == report["record_prefix_bytes"] == 6
            assert len(old) + 2 > 65535 and len(new) + 2 <= 65535
            assert new == old.replace(
                property_bytes(3118, LITERAL[0]), property_bytes(3118, b""), 1
            )
        else:
            assert old == new


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_sha256", "0" * 64),
        ("record_sha256", "0" * 64),
        ("property_sha256", "0" * 64),
        ("metadata_property_sha256", "0" * 64),
        ("metadata_property_sha256", None),
        ("wire_index", True),
        ("wire_index", -1),
        ("wire_index", 4096),
        ("wire_index", 3),
        ("connection_count", True),
        ("connection_count", 2),
        ("old", [False, 85, 2, 7000]),
        ("old", [1, 85, 2, 7000]),
        ("old", [0, 85, 2]),
        ("old", [0, 85, 2, 65536]),
    ],
)
def test_stale_or_untyped_removal_guards_never_modify_the_original(field, value):
    raw = authored(wires=WIRES, metadata=b"".join(METADATA))
    editor = MoiConnectionRemoval(raw)
    with pytest.raises(ValueError):
        editor.compile(**request(editor, **{field: value}))
    assert editor.editor.source == raw


@pytest.mark.parametrize(
    "metadata",
    [
        b"",
        b"\x3e" + encoded(Unsigned(1)) + encoded(CharacterString("wrong")) + b"\x3f",
        METADATA[0] * 2,
    ],
)
def test_misaligned_or_unrecognized_continuation_refuses_removal(metadata):
    with pytest.raises(ValueError):
        MoiConnectionRemoval(authored(metadata=metadata)).inspect(REF)


def test_ambiguous_input_ownership_remains_refused_and_repeated_review_is_stable():
    with pytest.raises(ValueError, match="ambiguous input"):
        MoiConnectionRemoval(authored(wires=[WIRES[0], WIRES[0]])).inspect(REF)
    editor = MoiConnectionRemoval(authored(wires=WIRES))
    body = request(editor, 1)
    assert editor.compile(**body) == editor.compile(**body)
