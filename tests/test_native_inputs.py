"""Authored native input records and format-family boundaries, without site files."""

import gzip
import struct

import pytest
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    OctetString,
    Real,
    Unsigned,
)
from bms_tool.moi_identity import MoiIdentity
from bms_tool.mstp import header_crc
from bms_tool.native_inputs import (
    InputConfiguration,
    NativeInputCompiler,
    archive,
    configuration_guard,
    replace_properties,
    verify_input_preservation,
)

from .test_controller_application import encoded, native_record
from .test_moi_parameters import parameters_source


def source(*, compressed=False, model="M4-CVM03050-0", existing=False, binary=False, internal=True):
    data, directory, dynamic = parameters_source(model=model, compressed=False)
    # Retain authored saved settings on an otherwise unrelated Device class.
    records = []
    if internal:
        records.append(
            native_record(
                240,
                1094,
                [
                    (32527, encoded(CharacterString("controller/0_1094"))),
                    (75, encoded(ObjectIdentifier((0, 1094)))),
                    (31, encoded(CharacterString("AI1-Int"))),
                    (519, encoded(Unsigned(4))),
                    (518, encoded(Enumerated(9))),
                    (2390, encoded(CharacterString("Integral input"))),
                ],
            )
        )
    if existing or binary:
        cid, kind = (242, 3) if binary else (240, 0)
        records.append(
            native_record(
                cid,
                101,
                [
                    (32527, encoded(CharacterString(f"controller/{kind}_101"))),
                    (75, encoded(ObjectIdentifier((kind, 101)))),
                    (31, encoded(CharacterString("UI IN1"))),
                    (519, encoded(Unsigned(1))),
                    # Deliberately non-sorted property order, including opaque tags.
                    (65001, encoded(CharacterString("keep raw property order and unknown values"))),
                    (518, encoded(Enumerated(1))),
                    (2180, encoded(Enumerated(5))),
                    (1293, encoded(Real(0))),
                    (1294, encoded(Real(10))),
                    (1295, encoded(Real(0))),
                    (1296, encoded(Real(100))),
                    (117, encoded(Enumerated(98))),
                    (69, encoded(Real(0))),
                    (65, encoded(Real(100))),
                    (2390, encoded(CharacterString("Authored input"))),
                ],
            )
        )
    raw = bytearray(data)
    struct.pack_into("<I", raw, 10, struct.unpack_from("<I", raw, 10)[0] + len(records))
    raw.extend(b"".join(struct.pack("<H", len(r) + 2) + r for r in records))
    return {
        3: gzip.compress(raw, mtime=0) if compressed else bytes(raw),
        11: directory,
        12: dynamic,
    }


def config(mode="voltage"):
    return {
        "mode": mode,
        "input_low": 0,
        "input_high": 10 if mode == "voltage" else 1000,
        "output_low": 0,
        "output_high": 100,
        "units": 98,
        "minimum": 0,
        "maximum": 100,
    }


def allocation(slot=1, instance=3000010):
    return {
        "action": "allocate",
        "object_instance": instance,
        "slot": slot,
        "name": "Authored new input",
        "configuration": config(),
    }


def initialized_input_files(files, instance=3000010, fields=None):
    static, dynamic = bytearray(files[11]), bytearray(files[12])
    for pid, datatype, payload in fields or [
        (3164, 4, struct.pack(">f", 900)),
        (813, 16, b"\x01"),
        (1302, 1, b"\x01"),
    ]:
        offset = len(dynamic)
        dynamic.extend(payload + bytes([header_crc(payload) ^ 255]))
        body = (
            instance.to_bytes(4, "big")
            + pid.to_bytes(2, "big")
            + bytes([0x6F, datatype])
            + (240).to_bytes(2, "big")
            + offset.to_bytes(2, "big")
            + b"\x12\x34"
        )
        static.extend((len(body) + 2).to_bytes(2, "big") + body)
    return {3: files[3], 11: bytes(static), 12: bytes(dynamic)}


def test_new_input_firmware_initialization_is_explicit_and_remains_source_bound():
    before = source()
    output, _ = NativeInputCompiler(before).compile(allocation())
    after = initialized_input_files({**before, 3: output})
    result = verify_input_preservation(before, after, allocation())
    assert {r["property"] for r in result["initialized_input_parameters"]} == {813, 3164, 1302}
    assert NativeInputCompiler(after).source()["inputs"][0]["slot"] == 1
    assert result["other_configuration_preserved"]
    unknown = initialized_input_files({**before, 3: output}, fields=[(65001, 16, b"\x01")])
    with pytest.raises(ValueError, match="beyond documented"):
        verify_input_preservation(before, unknown, allocation())
    bad = initialized_input_files({**before, 3: output}, fields=[(3164, 4, struct.pack(">f", -1))])
    with pytest.raises(ValueError, match="unqualified initialized"):
        verify_input_preservation(before, bad, allocation())


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize(
    "model,slots", [("M4-CVM03050-0", 3), ("MS-VMA1630-0", 3), ("FX-PCG2611-0", 6)]
)
def test_allocate_reads_actual_occupancy_preserves_program_and_all_saved_values(
    compressed, model, slots
):
    before = source(compressed=compressed, model=model)
    compiler = NativeInputCompiler(before)
    assert compiler.source()["available_slots"] == list(range(1, slots + 1))
    assert compiler.source()["inputs"] == []  # Integral hardware is not an external input.
    output, report = compiler.compile(allocation())
    actual = NativeInputCompiler({**before, 3: output})
    added = actual.source()["inputs"][0]
    assert added["object_id"] == "analog-input,3000010" and added["slot"] == 1
    assert added["configuration"]["setup"] == 1 and added["configuration"]["field_units"] == 5
    assert actual.app.instance == compiler.app.instance
    assert actual.source()["available_slots"] == list(range(2, slots + 1))
    old = {r["sha256"] for r in compiler.app.records}
    assert old <= {r["sha256"] for r in actual.app.records}
    proof = verify_input_preservation(before, {**before, 3: output}, allocation())
    assert (
        proof["other_configuration_preserved"]
        and proof["saved_application_parameters_verified"] == 7
    )
    assert report["native_record_count"] == report["original_native_record_count"] + 1


def test_analog_and_binary_records_both_reserve_their_physical_terminal():
    for binary in (False, True):
        compiler = NativeInputCompiler(source(existing=not binary, binary=binary))
        assert compiler.source()["available_slots"] == [2, 3]
        with pytest.raises(ValueError, match="already configured"):
            compiler.compile(allocation())


def test_mode_edit_keeps_all_non_selected_property_bytes_and_record_order():
    before = source(existing=True)
    compiler = NativeInputCompiler(before)
    selected = compiler.source()["inputs"][0]
    edit = {
        "action": "mode",
        "object_instance": 101,
        "slot": 1,
        "configuration_sha256": selected["configuration_sha256"],
        "configuration": config("resistance"),
    }
    output, _ = compiler.compile(edit)
    after = NativeInputCompiler({**before, 3: output})
    record, changed = compiler.inputs["analog-input,101"], after.inputs["analog-input,101"]
    assert list(record["properties"]) == list(changed["properties"])
    for pid in set(record["properties"]) - {518, 2180, 1294}:
        a, b = record["properties"][pid], changed["properties"][pid]
        assert (
            compiler.app.data[a["value_start_offset"] : a["value_end_offset"]]
            == after.app.data[b["value_start_offset"] : b["value_end_offset"]]
        )
    assert (
        after.source()["inputs"][0]["configuration"]["setup"] == 0
    )  # Ohms is native code 0, not volts.
    assert verify_input_preservation(before, {**before, 3: output}, edit)[
        "other_configuration_preserved"
    ]


def test_removal_requires_original_allocation_and_restores_the_inventory():
    before = source()
    out, origin = NativeInputCompiler(before).compile(allocation())
    allocated = {**before, 3: out}
    compiler = NativeInputCompiler(allocated)
    point = compiler.source()["inputs"][0]
    edit = {
        "action": "remove-allocated",
        "object_instance": 3000010,
        "slot": 1,
        "configuration_sha256": point["configuration_sha256"],
        "allocation_receipt": "a" * 32,
    }
    with pytest.raises(ValueError, match="verified original allocation"):
        compiler.compile(edit)
    removed, _ = compiler.compile(edit, allocation_origin=origin)
    result = NativeInputCompiler({**before, 3: removed})
    assert not result.source()["inputs"] and result.source()["available_slots"] == [1, 2, 3]
    assert result.app.data == NativeInputCompiler(before).app.data


@pytest.mark.parametrize("reference", [False, True])
def test_removal_qualifies_saved_presence_but_rejects_opaque_native_references(reference):
    before = source()
    output, origin = NativeInputCompiler(before).compile(allocation())
    compiler = NativeInputCompiler({**before, 3: output})
    app = compiler.app
    selected = compiler.inputs["analog-input,3000010"]
    rows = [
        replace_properties(app, r, {1302: encoded(Boolean(True))})
        if r is selected
        else app.data[r["offset"] : r["end_offset"]]
        for r in app.records
    ]
    if reference:
        rows.append(
            native_record(
                555,
                301,
                [(65002, encoded(OctetString(((240 << 22) | 3000010).to_bytes(4, "big"))))],
            )
        )
    compiled = NativeInputCompiler({**before, 3: archive(app, rows)})
    origin["initialized_input_parameters"] = [
        {"class": 240, "instance": 3000010, "property": 1302, "encoded_hex": "112f"}
    ]
    point = compiled.source()["inputs"][0]
    edit = {
        "action": "remove-allocated",
        "object_instance": 3000010,
        "slot": 1,
        "configuration_sha256": point["configuration_sha256"],
        "allocation_receipt": "a" * 32,
    }
    if reference:
        with pytest.raises(ValueError, match="referenced"):
            compiled.compile(edit, allocation_origin=origin)
    else:
        removed, _ = compiled.compile(edit, allocation_origin=origin)
        assert (
            NativeInputCompiler({**before, 3: removed}).app.data
            == NativeInputCompiler(before).app.data
        )


def test_integral_input_cannot_be_edited_or_repurposed():
    compiler = NativeInputCompiler(source())
    r = next(
        r for r in compiler.app.records if compiler.app.reader.scalar(r, 75) == "analog-input,1094"
    )
    with pytest.raises(ValueError):
        compiler.compile(
            {
                "action": "mode",
                "object_instance": 1094,
                "slot": 4,
                "configuration_sha256": configuration_guard(compiler.app, r),
                "configuration": config(),
            }
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_low", True),
        ("input_high", "10"),
        ("output_high", float("inf")),
        ("output_low", float("nan")),
        ("output_high", 1e40),
    ],
)
def test_configuration_rejects_coercion_and_non_finite_or_unrepresentable_values(field, value):
    with pytest.raises(ValueError):
        InputConfiguration(**{**config(), field: value})


def test_real32_rounding_cannot_collapse_a_scaling_interval():
    with pytest.raises(ValueError, match="rounding collapses"):
        InputConfiguration(**{**config(), "input_low": 1.0, "input_high": 1.000000001})


def test_unsupported_current_mode_is_not_exposed_on_a_cvm():
    c = NativeInputCompiler(source())
    assert "current" not in c.source()["hardware"]["modes"]
    with pytest.raises(ValueError, match="electrical mode/range"):
        c.compile(
            {
                **allocation(),
                "configuration": {**config(), "mode": "current", "input_low": 4, "input_high": 20},
            }
        )


def test_inverse_linear_scaling_has_ordered_electrical_range_and_bounded_engineering_limits():
    before = source()
    edit = {**allocation(), "configuration": {**config(), "output_low": 100, "output_high": 0}}
    output, report = NativeInputCompiler(before).compile(edit)
    assert report["stored_configuration"]["output_low"] == 100
    assert report["stored_configuration"]["output_high"] == 0
    assert verify_input_preservation(before, {**before, 3: output}, edit)[
        "other_configuration_preserved"
    ]
    with pytest.raises(ValueError, match="limits must contain"):
        InputConfiguration(**{**edit["configuration"], "minimum": 1})


@pytest.mark.parametrize(
    "versions,accepted", [((60, 60), True), ((62, 62), True), ((66, 65), True), ((67, 66), False)]
)
def test_input_profile_qualifies_format_pairs_independently_of_model_inventory(versions, accepted):
    files = source()
    app = MoiIdentity(files[3])
    records = [
        replace_properties(
            app, r, {4128: encoded(Unsigned(versions[0])), 4129: encoded(Unsigned(versions[1]))}
        )
        if r is app.root
        else app.data[r["offset"] : r["end_offset"]]
        for r in app.records
    ]
    dynamic = bytearray(files[12])
    for offset, value in zip([0, 2], versions, strict=True):
        raw = bytes([value])
        dynamic[offset : offset + 2] = raw + bytes([header_crc(raw) ^ 255])
    files = {**files, 3: archive(app, records), 12: bytes(dynamic)}
    if accepted:
        output, _ = NativeInputCompiler(files).compile(allocation())
        assert NativeInputCompiler({**files, 3: output}).source()["format_versions"] == dict(
            zip(["acs", "dmcs"], versions, strict=True)
        )
    else:
        with pytest.raises(ValueError, match="application/data-model pair"):
            NativeInputCompiler(files)


def test_changed_current_configuration_and_changed_readback_fail_closed():
    before = source(existing=True)
    c = NativeInputCompiler(before)
    with pytest.raises(ValueError, match="changed; capture again"):
        c.compile(
            {
                "action": "mode",
                "object_instance": 101,
                "slot": 1,
                "configuration_sha256": "0" * 64,
                "configuration": config("resistance"),
            }
        )
    output, _ = c.compile(allocation(slot=2))
    with pytest.raises(ValueError, match="complete application"):
        verify_input_preservation(
            before,
            {**before, 3: output.replace(b"opaque footer", b"unsafe footer")},
            allocation(slot=2),
        )
