"""Independent literal native wire bytes and separately authored record framing."""

import copy
import gzip
import struct

import pytest
from bacpypes3.primitivedata import Boolean, CharacterString, Unsigned
from bms_tool.moi_connection_copies import MoiConnectionCopies
from bms_tool.moi_identity import MoiIdentity

from .test_controller_application import encoded
from .test_moi_wire_sources import REF, A, B, C, D, source, wide_source

WIRE = bytes.fromhex("3e210021552102221b583f")
ADDED = bytes.fromhex("3e210021552103221b583f")


def property_bytes(pid, raw):
    key = pid.to_bytes(max(1, (pid.bit_length() + 7) // 8), "big")
    return bytes([8 | len(key)]) + key + b"\x2e" + raw + b"\x2f"


def frames(raw):
    # Fixture decoder uses only declared little-endian record lengths.
    out = []
    offset = 14
    while offset < len(raw):
        n = int.from_bytes(raw[offset : offset + 2], "little")
        width = 2
        if n == 0:
            n = int.from_bytes(raw[offset + 2 : offset + 6], "little")
            width = 6
        assert n >= width and offset + n <= len(raw)
        out.append((width, raw[offset + width : offset + n]))
        offset += n
    assert offset == len(raw)
    return out


def packed(header, records):
    return header + b"".join(
        (
            b"\0\0" + struct.pack("<I", len(body) + 6)
            if width == 6 or len(body) + 2 > 65535
            else struct.pack("<H", len(body) + 2)
        )
        + body
        for width, body in records
    )


def authored(
    *,
    compressed=True,
    extended=False,
    metadata=None,
    metadata_first=False,
    pad_to=None,
    target_config=False,
    **options,
):
    data = source(
        compressed=False,
        extended=extended,
        wires=options.pop("wires", [(0, 85, 2, 7000)]),
        **options,
    )
    records = []
    for width, body in frames(data):
        cid = int.from_bytes(body[:2], "little")
        instance = int.from_bytes(body[6:10], "big") & 0x3FFFFF
        if cid in (536, 575):
            if metadata is not None:
                extra = property_bytes(3384, metadata)
                body = (
                    body[:12] + extra + body[12:]
                    if metadata_first
                    else body[:-1] + extra + body[-1:]
                )
            if pad_to is not None:
                size = max(0, pad_to - len(body) - 10)
                for _ in range(4):
                    extra = property_bytes(65003, encoded(CharacterString("x" * size)))
                    difference = pad_to - len(body) - len(extra)
                    if not difference:
                        break
                    size += difference
                assert len(body) + len(extra) == pad_to
                body = body[:-1] + extra + body[-1:]
        if target_config and instance == 13:
            before = property_bytes(65000, encoded(Unsigned(1)))
            assert body.count(before) == 1
            body = body.replace(before, property_bytes(65000, encoded(Unsigned(2))))
        records.append((width, body))
    native = packed(data[:14], records)
    return gzip.compress(native, mtime=123) if compressed else native


def request(editor, **updates):
    s = editor.inspect(REF, source_ref=updates.get("source_ref"))
    return {
        "source_sha256": editor.editor.source_sha256,
        "diagram_ref": REF,
        "record_sha256": s["record_sha256"],
        "property_sha256": s["property_sha256"],
        "metadata_property_sha256": s["metadata_property_sha256"],
        "prototype_index": 0,
        "prototype_old": s["prototype"]["old"],
        "connection_count": s["connection_count"],
        "source_ref": s["source_ref"],
        "target_ref": D,
        **updates,
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
@pytest.mark.parametrize("metadata_first", [False, True])
def test_only_literal_new_wire_and_selected_metadata_row_are_added(
    compressed, extended, diagram_class, metadata_first
):
    metadata = (
        b"\x3e"
        + encoded(Boolean(True))
        + encoded(CharacterString("Recorded é🙂 continuation"))
        + b"\x3f"
    )
    raw = authored(
        compressed=compressed,
        extended=extended,
        diagram_class=diagram_class,
        metadata=metadata,
        metadata_first=metadata_first,
    )
    editor = MoiConnectionCopies(raw)
    before = editor.editor.data
    output, report = editor.compile(**request(editor))
    after = MoiIdentity(output)
    old_frames, new_frames = frames(before), frames(after.data)
    assert before[:14] == after.data[:14] and len(old_frames) == len(new_frames)
    for (old_width, old), (new_width, new) in zip(old_frames, new_frames, strict=True):
        if int.from_bytes(old[:2], "little") == diagram_class:
            expected = old.replace(WIRE + b"\x2f", WIRE + ADDED + b"\x2f", 1)
            expected = expected.replace(metadata + b"\x2f", metadata + metadata + b"\x2f", 1)
            assert new == expected and new_width == old_width
        else:
            assert new == old and new_width == old_width
    assert report["new"] == [0, 85, 3, 7000] and report["new_encoding_hex"] == ADDED.hex()
    assert report["connection_count_before"] == 1 and report["connection_count_after"] == 2
    assert report["continuation_prototype_sha256"]
    assert report["other_expanded_bytes_preserved"] and report["native_structure_readback_verified"]
    assert (
        not report["saved_settings_merged"]
        and not report["controller_write"]
        and not report["field_transfer_enabled"]
    )
    assert editor.editor.source == raw and editor.editor.data == before
    if compressed:
        assert output[:10] == raw[:10] and gzip.decompress(output) == after.data


@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_new_tuple_retains_original_unsigned_payload_widths_when_sufficient(width):
    raw = authored(source_index_width=width)
    editor = MoiConnectionCopies(raw)
    output, report = editor.compile(**request(editor))
    expected = b"\x3e" + bytes([0x20 | width]) + b"\0" * width + bytes.fromhex("21552103221b583f")
    assert report["new_encoding_hex"] == expected.hex()
    assert expected in MoiIdentity(output).data


def test_new_index_width_can_grow_without_rewriting_the_recorded_prototype():
    raw = wide_source()
    editor = MoiConnectionCopies(raw)
    s = editor.inspect(REF, source_ref=f"{REF}.2_266")
    assert any(row["index"] == 257 for row in s["targets"])
    body = request(editor, source_ref=f"{REF}.2_266", target_ref=f"{REF}.2_267")
    output, p = editor.compile(**body)
    assert p["new"] == [256, 85, 257, 7000]
    assert p["new_encoding_hex"] == "3e2201002155220101221b583f"
    after = MoiIdentity(output)
    assert bytes.fromhex(p["prototype_encoding_hex"]) in after.data
    assert len(after.reader.diagram(REF)["connections"]) == 3


def test_selected_short_record_promotes_to_extended_framing_without_changing_others():
    raw = authored(compressed=False, pad_to=65530)
    editor = MoiConnectionCopies(raw)
    output, p = editor.compile(**request(editor))
    before, after = frames(raw), frames(output)
    assert p["record_prefix_growth"] == 4 and p["native_bytes_growth"] == len(ADDED) + 4
    for (a, old), (b, new) in zip(before, after, strict=True):
        if int.from_bytes(old[:2], "little") == 575:
            assert a == 2 and b == 6 and len(new) == len(old) + len(ADDED)
        else:
            assert a == b and old == new


def test_empty_or_fully_used_graphs_have_no_invented_destination_or_pin():
    empty = MoiConnectionCopies(authored(empty=True))
    s = empty.inspect(REF)
    assert not s["available"] and s["prototype"] is None and not s["sources"] and not s["targets"]
    full = MoiConnectionCopies(source())
    assert not full.inspect(REF)["available"]
    with pytest.raises(ValueError, match="ownership|order|cycle"):
        full.compile(**request(full))


@pytest.mark.parametrize(
    "options,source_ref,target_ref",
    [
        ({}, B, D),
        (
            {"source_class": 550, "wires": [(0, 85, 2, 7000), (1, 85, 2, 7001)]},
            B,
            D,
        ),
        (
            {"config": True, "wires": [(0, 85, 2, 7000), (1, 85, 2, 7001)]},
            B,
            D,
        ),
        ({}, A, C),
        ({"target_config": True}, A, D),
        ({"order": (3, 0, 1, 2)}, A, D),
        (
            {
                "target_class": 551,
                "wires": [(0, 85, 1, 7000), (1, 85, 2, 7000), (2, 85, 3, 7000)],
                "order": (2, 0, 1, 3),
            },
            C,
            A,
        ),
    ],
)
def test_unobserved_source_occupied_input_configuration_order_and_cycle_are_refused(
    options, source_ref, target_ref
):
    editor = MoiConnectionCopies(authored(**options))
    before = editor.editor.source
    with pytest.raises(ValueError):
        editor.compile(**request(editor, source_ref=source_ref, target_ref=target_ref))
    assert editor.editor.source == before


@pytest.mark.parametrize(
    "fault",
    [
        "source",
        "record",
        "wire",
        "metadata",
        "index",
        "bool-index",
        "old",
        "bool-old",
        "count",
        "bool-count",
        "missing-source",
        "missing-target",
    ],
)
def test_every_original_prototype_guard_and_explicit_type_remains_required(fault):
    editor = MoiConnectionCopies(authored())
    body = request(editor)
    if fault == "source":
        body["source_sha256"] = "0" * 64
    if fault == "record":
        body["record_sha256"] = "0" * 64
    if fault == "wire":
        body["property_sha256"] = "0" * 64
    if fault == "metadata":
        body["metadata_property_sha256"] = "0" * 64
    if fault == "index":
        body["prototype_index"] = 1
    if fault == "bool-index":
        body["prototype_index"] = False
    if fault == "old":
        body["prototype_old"] = [1, 85, 2, 7000]
    if fault == "bool-old":
        body["prototype_old"][0] = False
    if fault == "count":
        body["connection_count"] = 2
    if fault == "bool-count":
        body["connection_count"] = True
    if fault == "missing-source":
        body["source_ref"] = None
    if fault == "missing-target":
        body["target_ref"] = None
    with pytest.raises(ValueError):
        editor.compile(**body)


@pytest.mark.parametrize(
    "metadata",
    [
        b"",
        b"\x3e" + encoded(Unsigned(1)) + encoded(CharacterString("wrong type")) + b"\x3f",
        (b"\x3e" + encoded(Boolean(False)) + encoded(CharacterString("extra")) + b"\x3f") * 2,
    ],
)
def test_unknown_or_misaligned_continuation_metadata_refuses_new_connection(metadata):
    editor = MoiConnectionCopies(authored(metadata=metadata))
    with pytest.raises(ValueError):
        editor.inspect(REF)


def test_duplicate_existing_destination_and_tag_budget_are_not_relaxed():
    editor = MoiConnectionCopies(authored(wires=[(0, 85, 2, 7000), (1, 85, 2, 7000)]))
    with pytest.raises(ValueError, match="ambiguous input ownership"):
        editor.inspect(REF)
    raw = authored(wires=[(0, 85, 2, index) for index in range(3333)])
    editor = MoiConnectionCopies(raw)
    assert not editor.inspect(REF)["budget_available"]
    with pytest.raises(ValueError, match="tag budget"):
        editor.compile(**request(editor))


def test_repeated_review_is_deterministic_and_source_stays_immutable():
    editor = MoiConnectionCopies(authored())
    body = request(editor)
    before = copy.deepcopy(editor.editor.reader.summary())
    first = editor.compile(**body)
    assert first == editor.compile(**body)
    assert editor.editor.reader.summary() == before
