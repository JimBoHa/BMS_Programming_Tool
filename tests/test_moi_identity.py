"""Authored native applications with variable models, expansion records and peers."""

import gzip
import hashlib
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, OctetString, Unsigned
from bms_tool.moi_identity import MoiIdentity

from .test_controller_application import encoded, native_record


def source(
    *,
    model="UNLISTED-CONTROLLER",
    cid=194,
    modules=0,
    compressed=False,
    extended=False,
    name="Authored controller",
    name_encoding=0,
):
    old = 5136
    root = native_record(
        cid,
        old,
        [
            (32527, encoded(CharacterString("controller"))),
            (75, encoded(ObjectIdentifier((8, old)))),
            (2390, encoded(CharacterString(name, _encoding=name_encoding))),
            (70, encoded(CharacterString(model))),
            (4128, encoded(Unsigned(62))),
            (4129, encoded(Unsigned(62))),
            (65000, encoded(OctetString(b"untouched\xc4\x02\x00\x14\x10 5136"))),
        ],
    )
    records = [root]
    for index in range(modules):
        records.append(
            native_record(
                200 + index,
                40 + index,
                [
                    (32527, encoded(CharacterString(f"controller/{200 + index}_{40 + index}"))),
                    (75, encoded(ObjectIdentifier((8, 900 + index)))),
                    (70, encoded(CharacterString(f"Unlisted expansion {index}"))),
                ],
            )
        )
    # Metadata records without an engineering ref are part of the binary too.
    records.append(native_record(127, 1, [(65001, encoded(OctetString(b"opaque metadata")))]))
    body = bytearray(struct.pack("<6sHHI", b"\x02\x00MOI\x00", cid, 1, len(records)))
    for index, record in enumerate(records):
        body.extend(
            b"\x00\x00" + struct.pack("<I", len(record) + 6)
            if extended or index == len(records) - 1
            else struct.pack("<H", len(record) + 2)
        )
        body.extend(record)
    result = bytes(body)
    return gzip.compress(result, mtime=0) if compressed else result


def request(editor, new=5336):
    return dict(source_sha256=editor.source_sha256, expected_instance=5136, new_instance=new)


@pytest.mark.parametrize(
    "model,cid,modules",
    [
        ("UNKNOWN-A", 194, 0),
        ("UNKNOWN-B", 470, 5),
        ("UNKNOWN-C", 777, 12),
    ],
)
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
def test_changes_only_two_typed_identities_in_actual_native_records(
    model, cid, modules, compressed, extended
):
    original = source(
        model=model, cid=cid, modules=modules, compressed=compressed, extended=extended
    )
    editor = MoiIdentity(original)
    plan = editor.preview(**request(editor))
    output, report = editor.export(**request(editor), plan_sha256=plan["plan_sha256"])
    parsed = MoiIdentity(output)
    assert parsed.instance == 5336 and len(parsed.records) == modules + 2
    expected = bytearray(editor.data)
    for edit in plan["edits"]:
        start = edit["native_byte_offset"]
        expected[start : start + 4] = bytes.fromhex(edit["after"])
    assert parsed.data == bytes(expected)
    assert sum(a != b for a, b in zip(editor.data, parsed.data, strict=True)) == 2
    assert parsed.reader.scalar(parsed.root, 70) == model
    assert parsed.reader.scalar(parsed.root, 2390) == "Authored controller"
    for before, after in zip(editor.records[1:], parsed.records[1:], strict=True):
        assert before == after
    assert original == editor.source
    assert report["output_sha256"] == hashlib.sha256(output).hexdigest()
    assert not report["controller_write"] and not report["vendor_runtime_required"]
    if compressed:
        assert output[:10] == original[:10]
        assert gzip.decompress(output) == parsed.data


@pytest.mark.parametrize("new", [0, 4194302, 4194])
def test_different_decimal_width_still_has_fixed_width_binary_identity(new):
    editor = MoiIdentity(source())
    plan = editor.preview(**request(editor, new))
    output, _ = editor.export(**request(editor, new), plan_sha256=plan["plan_sha256"])
    assert MoiIdentity(output).instance == new and len(output) == len(editor.source)


def test_noop_is_byte_exact_and_stale_or_altered_reviews_fail():
    editor = MoiIdentity(source(compressed=True))
    q = request(editor, 5136)
    plan = editor.preview(**q)
    assert editor.export(**q, plan_sha256=plan["plan_sha256"])[0] == editor.source
    with pytest.raises(ValueError, match="source or Device"):
        editor.preview(**{**q, "source_sha256": "0" * 64})
    with pytest.raises(ValueError, match="source or Device"):
        editor.preview(**{**q, "expected_instance": 500})
    with pytest.raises(ValueError, match="review changed"):
        editor.export(**request(editor), plan_sha256=plan["plan_sha256"])


@pytest.mark.parametrize("new", [True, -1, 4194303, "5336", 5336.0])
def test_rejects_non_instances(new):
    editor = MoiIdentity(source())
    with pytest.raises(ValueError, match="actual Device instance"):
        editor.preview(**request(editor, new))


@pytest.mark.parametrize(
    "mutation",
    [
        "record_size",
        "count",
        "trailing",
        "header_class",
        "inconsistent_identity",
        "truncated_extended",
    ],
)
def test_malformed_or_ambiguous_sources_never_get_a_write_plan(mutation):
    data = bytearray(source())
    if mutation == "record_size":
        data[14:16] = b"\xff\xff"
    elif mutation == "count":
        data[10:14] = struct.pack("<I", 20001)
    elif mutation == "trailing":
        data.extend(b"not a record")
    elif mutation == "header_class":
        data[6:8] = b"\x01\x00"
    elif mutation == "inconsistent_identity":
        data[25] ^= 1
    elif mutation == "truncated_extended":
        end = MoiIdentity(bytes(data)).records[0]["end_offset"]
        data = data[: end + 3]
    with pytest.raises(ValueError):
        MoiIdentity(bytes(data))
