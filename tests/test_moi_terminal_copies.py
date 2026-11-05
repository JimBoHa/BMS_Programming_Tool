"""Literal whole-image expectations for existing native local terminal bindings."""

import gzip
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.moi_terminal_copies import MoiTerminalCopies

from .test_controller_application import encoded, native_record
from .test_moi_connection_copies import frames, packed, property_bytes
from .test_native_inputs import source


def authored(*, binary=False, compressed=False, wide=False, slot_width=1, **kwargs):
    files = source(existing=True, binary=binary, compressed=False, **kwargs)
    rows = []
    for width, body in frames(files[3]):
        if int.from_bytes(body[:2], "little") in (240, 242) and b"UI IN1" in body:
            old = property_bytes(519, b"\x21\x01")
            assert body.count(old) == 1
            body = body.replace(
                old,
                property_bytes(519, bytes([0x20 + slot_width]) + (1).to_bytes(slot_width, "big")),
            )
        rows.append((6 if wide else width, body))
    raw = packed(files[3][:14], rows)
    return {**files, 3: gzip.compress(raw, mtime=12345) if compressed else raw}


def proposal(compiler, **updates):
    row = next(p for p in compiler.inspect()["inputs"] if p["movable"])
    return {
        "source_sha256": compiler.editor.source_sha256,
        **{
            k: row[k]
            for k in ("ref", "record_sha256", "slot_property_sha256", "device_type_property_sha256")
        },
        "old_slot": row["slot"],
        "destination_slot": 3,
        **updates,
    }


def literal_move(raw, *, binary=False, slot_width=1):
    selected_class = 242 if binary else 240
    rows = []
    for width, body in frames(raw):
        if int.from_bytes(body[:2], "little") == selected_class and b"UI IN1" in body:
            a = property_bytes(519, bytes([0x20 + slot_width]) + (1).to_bytes(slot_width, "big"))
            b = property_bytes(31, b"\x75\x07\x00UI IN1")
            assert body.count(a) == body.count(b) == 1
            body = body.replace(
                a, property_bytes(519, bytes([0x20 + slot_width]) + (3).to_bytes(slot_width, "big"))
            )
            body = body.replace(b, property_bytes(31, b"\x75\x07\x00UI IN3"))
        rows.append((width, body))
    return packed(raw[:14], rows)


@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("wide", [False, True])
@pytest.mark.parametrize("slot_width", [1, 2, 3, 4])
def test_literal_whole_image_changes_only_two_existing_payloads(
    binary, compressed, wide, slot_width
):
    original = authored(binary=binary, compressed=compressed, wide=wide, slot_width=slot_width)[3]
    compiler = MoiTerminalCopies(original)
    output, report = compiler.compile(**proposal(compiler))
    actual = MoiIdentity(output)
    assert actual.data == literal_move(compiler.editor.data, binary=binary, slot_width=slot_width)
    assert actual.summary()["instance"] == 5136 and actual.summary()["model"] == "M4-CVM03050-0"
    assert len(actual.records) == len(compiler.editor.records)
    assert [w for w, _ in frames(actual.data)] == [w for w, _ in frames(compiler.editor.data)]
    assert MoiTerminalCopies(output).inspect()["unassigned_slots"] == [1, 2]
    assert report["changed"] and report["other_expanded_bytes_preserved"]
    assert (
        report["native_structure_readback_verified"]
        and report["identities_modes_graph_and_record_framing_preserved"]
    )
    assert (
        not report["controller_write"]
        and not report["field_transfer_enabled"]
        and not report["physical_terminal_or_wiring_verified"]
    )
    assert report["output_sha256"] == sha(output) and report["output_native_sha256"] == sha(
        actual.data
    )
    assert (
        seal({k: v for k, v in report.items() if k != "compilation_sha256"})
        == report["compilation_sha256"]
    )
    if compressed:
        assert output[:10] == original[:10]
    noop, review = compiler.compile(**proposal(compiler, destination_slot=1))
    assert noop == original and not review["changed"]


@pytest.mark.parametrize(
    "model,slots",
    [
        ("MS-VMA1630-0", 3),
        ("MS-VMA1615-0", 3),
        ("FX-PCV1630-0", 3),
        ("FX-PCV1615-0", 3),
        ("FX-PCG2611-0", 6),
    ],
)
@pytest.mark.parametrize("versions", [(60, 60), (62, 62), (66, 65)])
def test_documented_capacity_and_native_format_pair_are_required(model, slots, versions):
    files = authored(model=model, internal=model != "FX-PCG2611-0")
    data = files[3]
    for pid, value in zip((4128, 4129), versions, strict=True):
        old = property_bytes(pid, encoded(Unsigned(62)))
        assert data.count(old) == 1
        data = data.replace(old, property_bytes(pid, encoded(Unsigned(value))))
    compiler = MoiTerminalCopies(data)
    assert compiler.inspect()["unassigned_slots"] == list(range(2, slots + 1))
    output, _ = compiler.compile(**proposal(compiler, destination_slot=slots))
    assert (
        next(p for p in MoiTerminalCopies(output).inspect()["inputs"] if p["movable"])["slot"]
        == slots
    )


def transform(data, fn):
    rows = [(w, fn(body)) for w, body in frames(data)]
    return packed(data[:14], rows)


def selected_edit(data, pid, raw):
    app = MoiIdentity(data)
    selected = next(
        r for r in app.records if r["class_id"] == 240 and app.reader.scalar(r, 31) == "UI IN1"
    )
    old = selected["properties"].get(pid)
    before = (
        property_bytes(pid, app.data[old["value_start_offset"] : old["value_end_offset"] - 1])
        if old
        else None
    )

    def change(body):
        if b"UI IN1" not in body:
            return body
        if before is not None:
            assert body.count(before) == 1
            return body.replace(before, property_bytes(pid, raw))
        return body[:-1] + property_bytes(pid, raw) + body[-1:]

    return transform(data, change)


@pytest.mark.parametrize(
    "key,value",
    [
        ("source_sha256", "0" * 64),
        ("record_sha256", "0" * 64),
        ("slot_property_sha256", "0" * 64),
        ("device_type_property_sha256", "0" * 64),
        ("ref", "controller/missing"),
        ("ref", "controller/0_1094"),
        ("old_slot", 2),
        ("old_slot", True),
        ("old_slot", 1.0),
        ("destination_slot", True),
        ("destination_slot", 3.0),
        ("destination_slot", 0),
        ("destination_slot", 4),
        ("destination_slot", 16),
    ],
)
def test_stale_guards_fixed_dpt_and_non_strict_or_unavailable_slots_refuse(key, value):
    compiler = MoiTerminalCopies(authored()[3])
    with pytest.raises(ValueError):
        compiler.compile(**proposal(compiler, **{key: value}))


@pytest.mark.parametrize(
    "pid,raw",
    [
        (2577, b"\x21\x00"),
        (3645, b"\x00"),
        (519, b"\x91\x01"),
        (519, b"\x21\x01\x21\x02"),
        (519, b"\x25\x05\x00\x00\x00\x00\x01"),
        (31, encoded(CharacterString("BI IN1"))),
        (31, encoded(CharacterString("UI IN9"))),
        (31, encoded(Unsigned(1))),
        (32527, encoded(CharacterString("controller/module/0_101"))),
        (75, encoded(ObjectIdentifier((3, 101)))),
    ],
)
def test_unknown_or_nonlocal_terminal_encodings_refuse(pid, raw):
    with pytest.raises(ValueError):
        MoiTerminalCopies(selected_edit(authored()[3], pid, raw))


@pytest.mark.parametrize("model", ["UNKNOWN", "FX-PCX3721-0", "MS-IOM4711-0"])
def test_unknown_and_expansion_root_capacity_never_invented(model):
    with pytest.raises(ValueError):
        MoiTerminalCopies(authored(model=model)[3])


@pytest.mark.parametrize("cid", [598, 910, 243, 671, 673, 999])
def test_unknown_hardware_or_sa_records_cannot_hide_occupancy(cid):
    data = authored()[3]
    extra = native_record(
        cid,
        300,
        [(32527, encoded(CharacterString("controller/module"))), (519, encoded(Unsigned(2)))],
    )
    header = bytearray(data[:14])
    struct.pack_into("<I", header, 10, len(frames(data)) + 1)
    candidate = packed(bytes(header), frames(data) + [(2, extra)])
    with pytest.raises(ValueError):
        MoiTerminalCopies(candidate)


def test_occupied_universal_slot_is_not_an_available_destination():
    data = authored()[3]
    extra = native_record(
        242,
        202,
        [
            (32527, encoded(CharacterString("controller/3_202"))),
            (75, encoded(ObjectIdentifier((3, 202)))),
            (31, encoded(CharacterString("UI IN3"))),
            (519, encoded(Unsigned(3))),
        ],
    )
    header = bytearray(data[:14])
    struct.pack_into("<I", header, 10, len(frames(data)) + 1)
    compiler = MoiTerminalCopies(packed(bytes(header), frames(data) + [(6, extra)]))
    assert compiler.inspect()["unassigned_slots"] == [2]
    with pytest.raises(ValueError, match="already has"):
        compiler.compile(**proposal(compiler))


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate-slot",
        "duplicate-object",
        "untyped-object",
        "header-id",
        "unknown-version",
        "no-external",
        "pcg-internal",
        "gzip-trailing",
    ],
)
def test_ambiguous_inventory_or_container_never_yields_a_terminal_copy(fault):
    data = authored()[3]
    if fault == "duplicate-slot":
        data = selected_edit(data, 519, encoded(Unsigned(4)))
    elif fault == "duplicate-object":
        data = selected_edit(data, 75, encoded(ObjectIdentifier((0, 1094))))
    elif fault == "untyped-object":
        data = selected_edit(data, 75, encoded(Unsigned(101)))
    elif fault == "header-id":

        def change(body):
            if b"UI IN1" in body:
                body = body[:6] + ((240 << 22) | 102).to_bytes(4, "big") + body[10:]
            return body

        data = transform(data, change)
    elif fault == "unknown-version":
        data = data.replace(
            property_bytes(4128, encoded(Unsigned(62))), property_bytes(4128, encoded(Unsigned(99)))
        )
    elif fault == "no-external":
        data = source()[3]
    elif fault == "pcg-internal":
        data = authored(model="FX-PCG2611-0")[3]
    else:
        data = gzip.compress(data, mtime=123) + b"unowned tail"
    with pytest.raises(ValueError):
        MoiTerminalCopies(data)


def test_another_device_root_class_and_opaque_diagram_records_survive_literal_move():
    data = authored()[3]
    rows = []
    for width, body in frames(data):
        if int.from_bytes(body[:2], "little") == 470:
            body = (
                (194).to_bytes(2, "little")
                + body[2:6]
                + ((194 << 22) | 5136).to_bytes(4, "big")
                + body[10:]
            )
        rows.append((width, body))
    rows.append(
        (
            6,
            native_record(
                575,
                700,
                [
                    (32527, encoded(CharacterString("controller/diagram"))),
                    (3383, encoded(CharacterString("opaque coordinates"))),
                    (3384, b"\x3e\x11\x75\x02\x00x\x3f"),
                ],
            ),
        )
    )
    header = bytearray(data[:14])
    struct.pack_into("<H", header, 6, 194)
    struct.pack_into("<I", header, 10, len(rows))
    data = packed(bytes(header), rows)
    compiler = MoiTerminalCopies(data)
    output, _ = compiler.compile(**proposal(compiler))
    assert MoiIdentity(output).data == literal_move(data)
    assert MoiIdentity(output).summary()["root_class"] == 194
