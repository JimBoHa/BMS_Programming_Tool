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


def parameters_source(
    *, model="UNLISTED-MODEL", cid=470, modules=5, compressed=True, root_ref="controller"
):
    records = [
        native_record(
            cid,
            5136,
            [
                (32527, encoded(CharacterString(root_ref))),
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


@pytest.mark.parametrize("checksum", [0, 51, 204, 255])
def test_unsaved_non_application_slot_does_not_decode_or_validate_old_payload(checksum):
    archive, static, dynamic = parameters_source()
    expected, _ = ParameterApplication(archive, static, dynamic).compile()
    position = len(dynamic)
    # An unreferenced runtime object, explicitly marked as having no saved value.
    body = ((19 << 22) | 321).to_bytes(4, "big") + (85).to_bytes(2, "big")
    body += b"\x67\x09" + (141).to_bytes(2, "big")
    body += position.to_bytes(2, "big") + b"\x12\x34"
    static += (len(body) + 2).to_bytes(2, "big") + body
    dynamic += b"\xff\xff" + bytes([checksum])
    actual, report = ParameterApplication(archive, static, dynamic).compile()
    assert MoiIdentity(actual).data == MoiIdentity(expected).data
    assert report["matched_parameters"] == 7


def test_unsaved_slot_resolving_to_an_application_setting_is_still_rejected():
    archive, static, dynamic = parameters_source()
    invalid = bytearray(static)
    invalid[8] = 0x67
    with pytest.raises(ValueError, match="no valid saved value"):
        ParameterApplication(archive, bytes(invalid), dynamic).compile()


@pytest.mark.parametrize("flags", [0x6F, 0xEF])
def test_valid_non_application_slot_still_requires_its_crc(flags):
    archive, static, dynamic = parameters_source()
    position = len(dynamic)
    body = ((19 << 22) | 321).to_bytes(4, "big") + (85).to_bytes(2, "big")
    body += bytes([flags, 9]) + (141).to_bytes(2, "big")
    body += position.to_bytes(2, "big") + b"\x12\x34"
    static += (len(body) + 2).to_bytes(2, "big") + body
    payload = b"\x01\x02"
    dynamic += payload + bytes([header_crc(payload)])  # Wrong for a valid slot.
    with pytest.raises(ValueError, match="checksum"):
        ParameterApplication(archive, static, dynamic).compile()


def test_unsaved_unused_slot_must_still_own_a_bounded_nonoverlapping_range():
    archive, static, dynamic = parameters_source()
    body = ((19 << 22) | 321).to_bytes(4, "big") + (85).to_bytes(2, "big")
    body += b"\x67\x09" + (141).to_bytes(2, "big") + b"\x00\x00\x12\x34"
    static += (len(body) + 2).to_bytes(2, "big") + body
    with pytest.raises(ValueError, match="overlap"):
        ParameterApplication(archive, static, dynamic).compile()


def runtime_slot(*, position, flags=0x27, instance=321, pid=85, cid=141, datatype=4):
    body = ((19 << 22) | instance).to_bytes(4, "big") + pid.to_bytes(2, "big")
    body += bytes([flags, datatype]) + cid.to_bytes(2, "big")
    body += position.to_bytes(2, "big") + b"\x12\x34"
    return (len(body) + 2).to_bytes(2, "big") + body


@pytest.mark.parametrize("compressed", [True, False])
def test_repeated_unsaved_runtime_slots_reserve_storage_without_merging_old_values(compressed):
    archive, static, dynamic = parameters_source(compressed=compressed)
    expected, _ = ParameterApplication(archive, static, dynamic).compile()
    # Different retired priority slots may retain arbitrary old Float/CRC bytes.
    # Neither is a saved application value, even when the selectors repeat.
    for payload in (bytes.fromhex("7fc0000000"), bytes.fromhex("80000000ff")):
        static += runtime_slot(position=len(dynamic))
        dynamic += payload
    output, report = ParameterApplication(archive, static, dynamic).compile()
    assert MoiIdentity(output).data == MoiIdentity(expected).data
    assert report["matched_parameters"] == 7


@pytest.mark.parametrize("mutation", ["overlap", "bounds", "type", "mixed", "class"])
def test_unsaved_runtime_repetition_cannot_bypass_storage_or_selector_checks(mutation):
    archive, static, dynamic = parameters_source()
    first = len(dynamic)
    static += runtime_slot(position=first)
    dynamic += b"\x00" * 5
    options = {"position": len(dynamic)}
    if mutation == "overlap":
        options["position"] = first
    elif mutation == "bounds":
        options["position"] += 100
    elif mutation == "type":
        options["datatype"] = 255
    elif mutation == "mixed":
        options["flags"] = 0x6F
    elif mutation == "class":
        options["cid"] = 142
    static += runtime_slot(**options)
    dynamic += b"\x00" * 5
    with pytest.raises(ValueError):
        ParameterApplication(archive, static, dynamic).compile()


def test_unsaved_runtime_slot_cannot_replace_a_serialized_application_property():
    archive, static, dynamic = parameters_source()
    invalid = bytearray(static)
    invalid[8] = 0x27
    with pytest.raises(ValueError, match="no valid saved value"):
        ParameterApplication(archive, bytes(invalid), dynamic).compile()


@pytest.mark.parametrize("compressed", [True, False])
def test_valid_setting_on_an_existing_object_is_preserved_when_archive_omitted_it(compressed):
    archive, static, dynamic = parameters_source(compressed=compressed)
    invalid = bytearray(static)
    # A new saved property on the existing root, absent from the archive.
    invalid[6:8] = (65002).to_bytes(2, "big")
    output, report = ParameterApplication(archive, bytes(invalid), dynamic).compile()
    merged = MoiIdentity(output)
    assert merged.reader.scalar(merged.root, 65002) == 62
    assert merged.reader.scalar(merged.root, 4128) == 62
    assert {
        "class": 470,
        "instance": 5136,
        "property": 65002,
        "changed": True,
        "added": True,
    } in report["changed_parameters"]
    again, second = ParameterApplication(output, bytes(invalid), dynamic).compile()
    assert MoiIdentity(again).data == merged.data
    assert not second["changed_parameters"]


@pytest.mark.parametrize(
    "datatype,payload,expected",
    [
        (1, b"\x01", True),
        (4, bytes.fromhex("80000000"), -0.0),
        (17, (-700).to_bytes(2, "big", signed=True), -700),
        (18, (65530).to_bytes(2, "big"), 65530),
    ],
)
def test_omitted_saved_property_uses_original_native_datatype_bits_and_record(
    datatype, payload, expected
):
    archive, static, dynamic = parameters_source(modules=12)
    original = MoiIdentity(archive)
    body = ((8 << 22) | 5136).to_bytes(4, "big") + (65003).to_bytes(2, "big")
    body += bytes([0xEF, datatype]) + (470).to_bytes(2, "big")
    body += len(dynamic).to_bytes(2, "big") + b"\x12\x34"
    static += (len(body) + 2).to_bytes(2, "big") + body
    dynamic += payload + bytes([header_crc(payload) ^ 255])
    output, _ = ParameterApplication(archive, static, dynamic).compile()
    actual = MoiIdentity(output)
    assert actual.reader.scalar(actual.root, 65003) == expected
    if datatype == 4:
        p = actual.root["properties"][65003]
        assert (
            actual.data[p["value_start_offset"] : p["value_end_offset"]]
            == b"\x44" + payload + b"\x2f"
        )
    for before, after in zip(original.records[1:], actual.records[1:], strict=True):
        assert (
            original.data[before["offset"] : before["end_offset"]]
            == actual.data[after["offset"] : after["end_offset"]]
        )


def test_omitted_inline_string_is_preserved_with_its_source_encoding():
    archive, static, dynamic = parameters_source()
    directory = bytearray(static)
    offset = 0
    while offset + int.from_bytes(directory[offset : offset + 2], "big") < len(directory):
        offset += int.from_bytes(directory[offset : offset + 2], "big")
    directory[offset + 6 : offset + 8] = (65004).to_bytes(2, "big")
    output, _ = ParameterApplication(archive, bytes(directory), dynamic).compile()
    actual = MoiIdentity(output)
    assert actual.reader.scalar(actual.root, 65004) == "saved"
    assert actual.reader.scalar(actual.root, 904) == "draft"


def test_omitted_property_reframes_a_record_that_outgrows_its_short_length():
    archive, static, dynamic = parameters_source(compressed=False)
    source = MoiIdentity(archive)
    root = source.root
    raw = archive[root["offset"] : root["end_offset"]]
    # The author-selected opaque property leaves the original short record at
    # its exact maximum size. Adding the saved field requires extended framing.
    prefix = bytes.fromhex("0afde82e")
    pad = 65533 - len(raw) - len(prefix) - 6
    extra = prefix + encoded(CharacterString("z" * pad)) + b"\x2f"
    widened = raw[:-1] + extra + raw[-1:]
    assert len(widened) == 65533
    archive = archive[:14] + struct.pack("<H", 65535) + widened + archive[root["end_offset"] :]
    directory = bytearray(static)
    directory[6:8] = (65002).to_bytes(2, "big")
    output, _ = ParameterApplication(archive, bytes(directory), dynamic).compile()
    actual = MoiIdentity(output)
    assert output[14:16] == b"\x00\x00"
    assert actual.reader.scalar(actual.root, 65002) == 62
    assert (
        actual.root["properties"][65000]["encoded_sha256"]
        == MoiIdentity(archive).root["properties"][65000]["encoded_sha256"]
    )


def rebase_selectors(static, instance):
    output = bytearray(static)
    offset = 0
    while offset < len(output):
        length = int.from_bytes(output[offset : offset + 2], "big")
        output[offset + 2 : offset + 6] = ((8 << 22) | instance).to_bytes(4, "big")
        offset += length
    return bytes(output)


@pytest.mark.parametrize("cid", [194, 777])
@pytest.mark.parametrize("logical_instance", [1, 41])
@pytest.mark.parametrize("compressed", [True, False])
def test_saved_root_selectors_follow_the_exact_declared_reference(
    cid, logical_instance, compressed
):
    archive, static, dynamic = parameters_source(
        cid=cid, compressed=compressed, root_ref=f"8-{logical_instance}"
    )
    static = rebase_selectors(static, logical_instance)
    merge = ParameterApplication(archive, static, dynamic)
    output, report = merge.compile()
    actual = MoiIdentity(output)
    assert actual.instance == 5136
    assert actual.reader.scalar(actual.root, 900) == 3.5
    assert report["matched_parameters"] == 7
    assert {p["instance"] for p in merge.parameters} == {5136}
    q = dict(source_sha256=actual.source_sha256, expected_instance=5136, new_instance=5336)
    plan = actual.preview(**q)
    changed, _ = actual.export(**q, plan_sha256=plan["plan_sha256"])
    again, after = ParameterApplication(changed, static, dynamic).compile()
    assert MoiIdentity(again).data == MoiIdentity(changed).data
    assert after["matched_parameters"] == 7
    assert not after["changed_parameters"]


def test_same_numeric_root_selector_without_reference_proof_is_not_guessed():
    archive, static, dynamic = parameters_source(root_ref="other-root")
    output, report = ParameterApplication(archive, rebase_selectors(static, 1), dynamic).compile()
    assert MoiIdentity(output).data == MoiIdentity(archive).data
    assert report["matched_parameters"] == 0


def test_logical_root_selector_cannot_shadow_an_existing_native_object():
    archive, static, dynamic = parameters_source(compressed=False, root_ref="8-1")
    extra = native_record(
        470,
        1,
        [
            (32527, encoded(CharacterString("8-1/conflict"))),
            (70, encoded(CharacterString("other"))),
        ],
    )
    data = bytearray(archive)
    struct.pack_into("<I", data, 10, struct.unpack_from("<I", data, 10)[0] + 1)
    data.extend(struct.pack("<H", len(extra) + 2) + extra)
    with pytest.raises(ValueError, match="conflicts"):
        ParameterApplication(bytes(data), rebase_selectors(static, 1), dynamic).compile()


def test_saved_root_aliases_cannot_write_the_same_omitted_property_twice():
    archive, static, dynamic = parameters_source(root_ref="8-1")
    directory = bytearray(rebase_selectors(static, 1))
    directory[6:8] = (65002).to_bytes(2, "big")
    duplicate = bytearray(directory[:16])
    duplicate[2:6] = ((8 << 22) | 5136).to_bytes(4, "big")
    duplicate[12:14] = len(dynamic).to_bytes(2, "big")
    directory.extend(duplicate)
    dynamic += bytes([62, header_crc(bytes([62])) ^ 255])
    with pytest.raises(ValueError, match="Multiple saved selectors"):
        ParameterApplication(archive, bytes(directory), dynamic).compile()


def binary_saved_state(*, external=3, cid=242, existing_timestamp=False):
    archive, static, dynamic = parameters_source(compressed=False)
    props = [
        (32527, encoded(CharacterString("controller/binary"))),
        (75, encoded(ObjectIdentifier((external, 73)))),
    ]
    if existing_timestamp:
        props.append((16, encoded(Unsigned(0))))
    record = native_record(cid, 73, props)
    data = bytearray(archive)
    struct.pack_into("<I", data, 10, struct.unpack_from("<I", data, 10)[0] + 1)
    data.extend(struct.pack("<H", len(record) + 2) + record)
    for pid, value in [(15, 1234), (16, 1700000000), (33, 5678)]:
        payload = value.to_bytes(4, "big")
        position = len(dynamic)
        dynamic += payload + bytes([header_crc(payload) ^ 255])
        body = (
            ((external << 22) | 73).to_bytes(4, "big")
            + pid.to_bytes(2, "big")
            + b"\x6f\x02"
            + cid.to_bytes(2, "big")
            + position.to_bytes(2, "big")
            + b"\x12\x34"
        )
        static += (len(body) + 2).to_bytes(2, "big") + body
    return bytes(data), static, dynamic


@pytest.mark.parametrize("external,cid", [(3, 242), (4, 239), (5, 168)])
def test_binary_runtime_timestamp_is_not_fabricated_as_an_unsigned_application_default(
    external, cid
):
    files = binary_saved_state(external=external, cid=cid)
    output, report = ParameterApplication(*files).compile()
    app = MoiIdentity(output)
    record = next(
        r
        for r in app.records
        if r["class_id"] == cid and app.reader.scalar(r, 32527) == "controller/binary"
    )
    assert 16 not in record["properties"]
    assert app.reader.scalar(record, 15) == 1234 and app.reader.scalar(record, 33) == 5678
    assert report["matched_parameters"] == 9
    runtime = report["retained_runtime_parameters"]
    assert len(runtime) == 1 and runtime[0]["stored_epoch_seconds"] == 1700000000
    assert runtime[0]["role"] == "binary-change-of-state-time"
    assert files == binary_saved_state(external=external, cid=cid)
    again, _ = ParameterApplication(output, files[1], files[2]).compile()
    assert MoiIdentity(again).data == app.data


def test_timestamp_exception_does_not_bypass_crc_checks():
    archive, static, dynamic = binary_saved_state()
    corrupt = bytearray(dynamic)
    corrupt[-6] ^= 1
    with pytest.raises(ValueError, match="checksum"):
        ParameterApplication(archive, static, bytes(corrupt)).compile()


def test_existing_unqualified_binary_timestamp_encoding_is_rejected():
    with pytest.raises(ValueError, match="timestamp application encoding"):
        ParameterApplication(*binary_saved_state(existing_timestamp=True)).compile()
