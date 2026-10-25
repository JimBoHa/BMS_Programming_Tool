"""Independent authored native storage, including changed widths and opaque records."""

import gzip
import struct

import pytest
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Integer,
    ObjectIdentifier,
    Real,
    Unsigned,
)
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc

from .test_controller_application import encoded, native_record


def parameters_source(*, model="UNLISTED-MODEL", cid=470, modules=5, compressed=True):
    records = [
        native_record(
            cid,
            5136,
            [
                (32527, encoded(CharacterString("controller"))),
                (75, encoded(ObjectIdentifier((8, 5136)))),
                (2390, encoded(CharacterString("Authored controller"))),
                (70, encoded(CharacterString(model))),
                (4128, encoded(Unsigned(62))),
                (4129, encoded(Unsigned(62))),
                (900, encoded(Real(1.25))),
                (901, encoded(Unsigned(1))),
                (902, encoded(Integer(-1))),
                (903, encoded(Boolean(False))),
                (904, encoded(CharacterString("draft"))),
            ],
        )
    ]
    for index in range(modules):
        records.append(
            native_record(
                200 + index,
                40 + index,
                [
                    (32527, encoded(CharacterString(f"controller/module-{index}"))),
                    (
                        65000,
                        encoded(CharacterString("Preserve unknown expansion properties exactly")),
                    ),
                ],
            )
        )
    records.append(native_record(127, 1, [(65001, encoded(CharacterString("opaque footer")))]))
    archive = struct.pack("<6sHHI", b"\x02\x00MOI\x00", cid, 1, len(records))
    archive += b"".join(struct.pack("<H", len(r) + 2) + r for r in records)
    static, dynamic = bytearray(), bytearray()
    for pid, kind, payload in [
        (4128, 16, b"\x3e"),
        (4129, 16, b"\x3e"),
        (900, 4, struct.pack(">f", 3.5)),
        (901, 2, (70000).to_bytes(4, "big")),
        (902, 17, (-300).to_bytes(2, "big", signed=True)),
        (903, 1, b"\x01"),
    ]:
        offset = len(dynamic)
        dynamic.extend(payload + bytes([header_crc(payload) ^ 255]))
        body = (
            ((8 << 22) | 5136).to_bytes(4, "big")
            + pid.to_bytes(2, "big")
            + bytes([0x6F, kind])
            + cid.to_bytes(2, "big")
            + offset.to_bytes(2, "big")
            + b"\x12\x34"
        )
        static.extend((len(body) + 2).to_bytes(2, "big") + body)
    inline = b"\x1e" + encoded(CharacterString("saved")) + b"\x1f" + b"\x00" * 5
    body = (
        ((8 << 22) | 5136).to_bytes(4, "big")
        + (904).to_bytes(2, "big")
        + b"\x4f\x07"
        + cid.to_bytes(2, "big")
        + inline
        + b"\x56\x78"
    )
    static.extend((len(body) + 2).to_bytes(2, "big") + body)
    return (
        (gzip.compress(archive, mtime=0) if compressed else archive),
        bytes(static),
        bytes(dynamic),
    )


@pytest.mark.parametrize(
    "model,cid,modules", [("NEW-A", 194, 0), ("NEW-B", 470, 5), ("NEW-C", 777, 12)]
)
@pytest.mark.parametrize("compressed", [True, False])
def test_generic_merge_preserves_objects_and_values_without_model_inventories(
    model, cid, modules, compressed
):
    files = parameters_source(model=model, cid=cid, modules=modules, compressed=compressed)
    original = MoiIdentity(files[0])
    output, report = ParameterApplication(*files).compile()
    actual = MoiIdentity(output)
    assert actual.instance == 5136 and len(actual.records) == modules + 2
    assert actual.reader.scalar(actual.root, 900) == 3.5
    assert actual.reader.scalar(actual.root, 901) == 70000
    assert actual.reader.scalar(actual.root, 903) is True
    assert actual.reader.scalar(actual.root, 904) == "saved"
    assert report["matched_parameters"] == 7 and len(report["changed_parameters"]) == 5
    for before, after in zip(original.records[1:], actual.records[1:], strict=True):
        assert (
            original.data[before["offset"] : before["end_offset"]]
            == actual.data[after["offset"] : after["end_offset"]]
        )
    assert len(actual.data) > len(
        original.data
    )  # Unsigned/Signed values grow; record framing follows.
    q = dict(source_sha256=actual.source_sha256, expected_instance=5136, new_instance=5336)
    plan = actual.preview(**q)
    changed, _ = actual.export(**q, plan_sha256=plan["plan_sha256"])
    assert MoiIdentity(changed).instance == 5336
    assert MoiIdentity(changed).reader.scalar(MoiIdentity(changed).root, 901) == 70000


@pytest.mark.parametrize(
    "mutation",
    [
        "crc",
        "offset",
        "trailing",
        "overlap",
        "type",
        "flags",
        "truncated",
        "boolean",
        "nonfinite",
        "inline",
    ],
)
def test_unsupported_or_corrupt_parameters_cannot_compile(mutation):
    archive, static, dynamic = parameters_source()
    s, d = bytearray(static), bytearray(dynamic)
    if mutation == "crc":
        d[0] ^= 1
    elif mutation == "offset":
        s[12:14] = b"\xff\xff"
    elif mutation == "trailing":
        d.extend(b"\x00")
    elif mutation == "overlap":
        s[28:30] = b"\x00\x00"
    elif mutation == "type":
        s[9] = 255
    elif mutation == "flags":
        s[8] = 0
    elif mutation == "truncated":
        s = s[:-1]
    elif mutation == "boolean":
        d[-2:] = bytes([2, header_crc(bytes([2])) ^ 255])
    elif mutation == "nonfinite":
        d[4:9] = bytes.fromhex("7f800000") + bytes([header_crc(bytes.fromhex("7f800000")) ^ 255])
    elif mutation == "inline":
        s[-3] = 1
    with pytest.raises(ValueError):
        ParameterApplication(archive, bytes(s), bytes(d)).compile()
