"""Independent literal native graph/tuple bytes for local wire-source copies."""

import gzip
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Real, Unsigned
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_wire_sources import MoiWireSources

from .test_controller_application import encoded, native_record

REF = "controller/575_1"
A, B, C, D = (f"{REF}.2_{n}" for n in (10, 11, 12, 13))


def source(
    *,
    compressed=True,
    extended=False,
    config=False,
    source_class=551,
    order=(0, 1, 2, 3),
    wires=None,
    positions=True,
    empty=False,
):
    wires = [(0, 85, 2, 7000), (1, 85, 3, 7000)] if wires is None else wires
    if empty:
        wires = []
    objects = [
        native_record(
            470,
            5136,
            [
                (32527, encoded(CharacterString("controller"))),
                (75, encoded(ObjectIdentifier(("device", 5136)))),
                (2390, encoded(CharacterString("Authored native wire controller"))),
                (70, encoded(CharacterString("UNLISTED-MODEL"))),
                (4128, encoded(Unsigned(62))),
                (4129, encoded(Unsigned(62))),
            ],
        )
    ]
    props = [
        (32527, encoded(CharacterString(REF))),
        (75, encoded(ObjectIdentifier((575, 1)))),
        (2390, encoded(CharacterString("Authored native sequence"))),
        (3375, b"".join(encoded(ObjectIdentifier(("analog-value", n))) for n in (10, 11, 12, 13))),
        (3117, b"".join(encoded(Unsigned(v)) for v in order)),
        (
            3118,
            b"".join(
                b"\x3e" + b"".join(encoded(Unsigned(v)) for v in row) + b"\x3f" for row in wires
            ),
        ),
        (65001, bytes.fromhex("4e21014f")),
    ]
    if positions:
        props.append(
            (
                3383,
                b"".join(
                    b"\x3e"
                    + encoded(Real(i * 30))
                    + encoded(Real(i * 20))
                    + encoded(Unsigned(0))
                    + b"\x3f"
                    for i in range(4)
                ),
            )
        )
    objects.append(native_record(575, 1, props))
    for i, ref in enumerate((A, B, C, D)):
        cid = 551 if i == 0 else source_class if i == 1 else 527
        objects.append(
            native_record(
                cid,
                10 + i,
                [
                    (32527, encoded(CharacterString(ref))),
                    (75, encoded(ObjectIdentifier(("analog-value", 10 + i)))),
                    (2390, encoded(CharacterString("Authored source/target " + str(i)))),
                    (28, encoded(CharacterString("Separate descriptive text " + str(i)))),
                    (3113, encoded(Real(1 + i))),
                    (65000, encoded(Unsigned(2 if config and i == 1 else 1))),
                    (65002, bytes.fromhex("4e21014f")),
                ],
            )
        )
    objects.append(
        native_record(127, 9, [(65001, encoded(CharacterString("Opaque metadata retained")))])
    )
    parts = [
        (
            b"\x00\x00" + struct.pack("<I", len(raw) + 6)
            if extended
            else struct.pack("<H", len(raw) + 2)
        )
        + raw
        for raw in objects
    ]
    data = struct.pack("<6sHHI", b"\x02\x00MOI\x00", 470, 1, len(parts)) + b"".join(parts)
    return gzip.compress(data, mtime=123) if compressed else data


def request(editor, **updates):
    info = editor.inspect(REF)
    return {
        "source_sha256": editor.editor.source_sha256,
        "diagram_ref": REF,
        "record_sha256": info["record_sha256"],
        "property_sha256": info["property_sha256"],
        "wire_index": 0,
        "old": [0, 85, 2, 7000],
        "source_ref": B,
        **updates,
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("positions", [False, True])
def test_exact_one_unsigned_payload_and_all_other_native_graph_bytes_survive(
    compressed, extended, positions
):
    original = source(compressed=compressed, extended=extended, positions=positions)
    editor = MoiWireSources(original)
    info = editor.inspect(REF)
    assert [x["ref"] for x in info["candidates"]] == [A, B]
    output, report = editor.compile(**request(editor))
    before = editor.editor.data
    after = MoiIdentity(output)
    offset = report["source_index_offset"]
    assert report["source_index_bytes"] == 1 and before[offset] == 0 and after.data[offset] == 1
    assert after.data == before[:offset] + b"\x01" + before[offset + 1 :]
    graph = after.reader.diagram(REF)
    assert graph["connections"] == [
        {"index": 0, "source_ref": B, "source_port": 85, "target_ref": C, "target_port": 7000},
        {"index": 1, "source_ref": B, "source_port": 85, "target_ref": D, "target_port": 7000},
    ]
    assert graph["execution_order"] == [0, 1, 2, 3] and graph["native_layout"] is positions
    assert report["old"] == [0, 85, 2, 7000] and report["new"] == [1, 85, 2, 7000]
    assert not report["saved_settings_merged"] and not report["controller_write"]
    assert not report["field_transfer_enabled"]
    assert report["native_structure_readback_verified"] and report["other_expanded_bytes_preserved"]
    assert editor.editor.source == original
    if compressed:
        assert output[:10] == original[:10]
        assert gzip.decompress(output) == after.data


def wide_source():
    count = 260
    objects = [
        native_record(
            470,
            5136,
            [
                (32527, encoded(CharacterString("controller"))),
                (75, encoded(ObjectIdentifier(("device", 5136)))),
                (2390, encoded(CharacterString("Wide authored graph"))),
                (70, encoded(CharacterString("UNLISTED-MODEL"))),
            ],
        )
    ]
    rows = [(0, 85, 258, 7000), (256, 85, 259, 7000)]
    objects.append(
        native_record(
            575,
            1,
            [
                (32527, encoded(CharacterString(REF))),
                (75, encoded(ObjectIdentifier((575, 1)))),
                (
                    3375,
                    b"".join(
                        encoded(ObjectIdentifier(("analog-value", 10 + i))) for i in range(count)
                    ),
                ),
                (3117, b"".join(encoded(Unsigned(i)) for i in range(count))),
                (
                    3118,
                    b"".join(
                        b"\x3e" + b"".join(encoded(Unsigned(v)) for v in row) + b"\x3f"
                        for row in rows
                    ),
                ),
            ],
        )
    )
    for i in range(count):
        objects.append(
            native_record(
                551 if i in (0, 256) else 527,
                10 + i,
                [
                    (32527, encoded(CharacterString(f"{REF}.2_{10 + i}"))),
                    (75, encoded(ObjectIdentifier(("analog-value", 10 + i)))),
                    (3113, encoded(Real(1))),
                ],
            )
        )
    return struct.pack("<6sHHI", b"\x02\x00MOI\x00", 470, 1, len(objects)) + b"".join(
        struct.pack("<H", len(row) + 2) + row for row in objects
    )


def test_wider_candidate_index_never_resizes_the_original_unsigned_payload():
    original = wide_source()
    editor = MoiWireSources(original)
    ref = f"{REF}.2_266"
    assert ref not in [row["ref"] for row in editor.inspect(REF)["candidates"]]
    with pytest.raises(ValueError, match="payload width"):
        editor.compile(**request(editor, old=[0, 85, 258, 7000], source_ref=ref))
    assert editor.editor.source == original


def test_member_record_header_must_match_its_typed_object_instance():
    original = source(compressed=False)
    app = MoiIdentity(original)
    offset = app.reader.records[B]["offset"] + 6
    altered = original[:offset] + ((551 << 22) | 999).to_bytes(4, "big") + original[offset + 4 :]
    with pytest.raises(ValueError, match="header and object instance"):
        MoiWireSources(altered).inspect(REF)


def test_same_source_noop_is_byte_exact_including_gzip_bytes():
    original = source()
    editor = MoiWireSources(original)
    output, report = editor.compile(**request(editor, source_ref=A))
    assert output == original and not report["changed"]


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"config": True}, "configuration"),
        ({"source_class": 526}, "configuration"),
        ({"wires": [(0, 85, 2, 7000)]}, "observed outgoing"),
        ({"order": (0, 2, 1, 3)}, "execute before"),
        ({"wires": [(0, 85, 2, 7000), (1, 85, 3, 7000), (2, 85, 1, 7000)]}, "cycle"),
    ],
)
def test_opaque_config_class_port_order_and_new_cycle_guards(kwargs, message):
    editor = MoiWireSources(source(**kwargs))
    assert B not in [row["ref"] for row in editor.inspect(REF)["candidates"]]
    with pytest.raises(ValueError, match=message):
        editor.compile(**request(editor))


@pytest.mark.parametrize(
    "changed",
    [
        {"source_sha256": "0" * 64},
        {"record_sha256": "0" * 64},
        {"property_sha256": "0" * 64},
        {"old": [1, 85, 2, 7000]},
        {"old": [False, 85, 2, 7000]},
        {"source_ref": "another/source"},
        {"wire_index": -1},
        {"wire_index": True},
        {"wire_index": 9},
    ],
)
def test_exact_original_archive_record_property_tuple_and_reference_are_required(changed):
    editor = MoiWireSources(source())
    with pytest.raises(ValueError):
        editor.compile(**request(editor, **changed))


def test_empty_native_graph_never_generates_a_connection():
    editor = MoiWireSources(source(empty=True))
    info = editor.inspect(REF)
    assert not info["wires"] and not info["available"] and info["selected_wire"] is None
    with pytest.raises(ValueError, match="existing native wire"):
        editor.compile(**request(editor))


@pytest.mark.parametrize("index", [-1, True, 4096])
def test_source_inspection_rejects_invalid_indices(index):
    with pytest.raises(ValueError):
        MoiWireSources(source()).inspect(REF, index)
