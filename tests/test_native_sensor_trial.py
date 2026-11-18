"""Authored sensor definitions, saved settings and byte-preserving trial copies."""

import copy
import struct

import pytest
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    ClosingTag,
    Enumerated,
    ObjectIdentifier,
    OpeningTag,
    Real,
    TagList,
    Unsigned,
)
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.mstp import header_crc
from bms_tool.native_inputs import archive, encoded, native_record, raw_property, replace_properties
from bms_tool.native_sensor_trial import (
    TrialEdit,
    compile_trial,
    compile_trial_restore,
    sensor_sources,
    source_app,
    verify_trial,
)

from .test_moi_parameters import parameters_source


def sensor_source(*, compressed=True, enabled=None, version=(66, 65), extra=()):
    data, static, dynamic = parameters_source(
        model="UNLISTED-MODEL", cid=194, root_ref="8-1", compressed=compressed
    )
    app = MoiIdentity(data)
    records = [app.data[r["offset"] : r["end_offset"]] for r in app.records]
    records[0] = replace_properties(
        app, app.root, {4128: encoded(Unsigned(version[0])), 4129: encoded(Unsigned(version[1]))}
    )
    # Independent saved version bytes and CRCs, rather than editing expected output.
    dynamic = bytearray(dynamic)
    for offset, value in ((0, version[0]), (2, version[1])):
        dynamic[offset] = value
        dynamic[offset + 1] = header_crc(bytes([value])) ^ 255
    info = bytes(
        TagList(
            [
                *Enumerated(1).encode(),
                *Unsigned(0).encode(),
                *Enumerated(1).encode(),
                *CharacterString("").encode(),
                *Enumerated(0).encode(),
                *CharacterString("").encode(),
                *CharacterString("").encode(),
                *Enumerated(0).encode(),
                *Enumerated(0).encode(),
                *Unsigned(5).encode(),
                OpeningTag(3),
                *ObjectIdentifier((127, 0)).encode(),
                *Enumerated(85).encode(),
                *Unsigned(65535).encode(),
                *ObjectIdentifier((8, 4194303)).encode(),
                ClosingTag(3),
                *CharacterString("NS8000").encode(),
                *Unsigned(0).encode(),
                *CharacterString("ZN-").encode(),
            ]
        )
        .encode()
        .pduData
    )
    props = [
        (32527, encoded(CharacterString("8-1/307_2.910_77"))),
        (75, encoded(ObjectIdentifier((910, 77)))),
        (2390, encoded(CharacterString("Authored NS8000"))),
        (2858, encoded(Unsigned(201))),
        (4872, info),
        (65001, encoded(CharacterString("opaque definition metadata"))),
    ]
    if enabled is not None:
        props.append((673, encoded(Boolean(enabled))))
    records += [
        native_record(910, 77, props),
        native_record(
            165,
            101,
            [
                (32527, encoded(CharacterString("8-1/307_2.910_77.2_101"))),
                (75, encoded(ObjectIdentifier((2, 101)))),
                (2390, encoded(CharacterString("Room temperature"))),
                (117, encoded(Enumerated(64))),
                (104, encoded(Real(71.5))),
            ],
        ),
        native_record(
            556,
            101,
            [
                (32527, encoded(CharacterString("8-1/556_101"))),
                (3399, encoded(CharacterString("8-1/307_2.910_77.2_101"))),
                (65002, encoded(CharacterString("retain exact control source and unknown fields"))),
            ],
        ),
        *extra,
    ]
    return {3: archive(app, records), 11: static, 12: bytes(dynamic)}


def edit_for(files, addresses=None):
    sensor = sensor_sources(files)[0]
    return {
        "sensor_ref": sensor["sensor_ref"],
        "sensor_sha256": sensor["sensor_sha256"],
        "addresses": addresses or [201],
        "first_instance": 3000010,
        "units": 64,
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("enabled", [None, True])
@pytest.mark.parametrize("addresses", [[201], list(range(199, 207))])
def test_trial_and_restore_preserve_existing_public_objects_logic_and_all_saved_settings(
    compressed, enabled, addresses
):
    files = sensor_source(compressed=compressed, enabled=enabled)
    before, _ = source_app(files)
    edit = edit_for(files, addresses)
    output, report = compile_trial(files, edit)
    observed = MoiIdentity(output)
    assert len(observed.records) == len(before.records) + len(addresses) * 2
    by_ref = {observed.reader.scalar(r, 32527): r for r in observed.records}
    for record in before.records:
        ref = before.reader.scalar(record, 32527)
        other = (
            by_ref[ref]
            if ref
            else next(r for r in observed.records if r["class_id"] == record["class_id"])
        )
        if ref == edit["sensor_ref"]:
            assert observed.reader.scalar(other, 673) is False
            for pid in record["properties"]:
                if pid != 673:
                    assert raw_property(before, record, pid) == raw_property(observed, other, pid)
        else:
            assert (
                before.data[record["offset"] : record["end_offset"]]
                == observed.data[other["offset"] : other["end_offset"]]
            )
    for row in report["trial_points"]:
        point = by_ref[row["temperature_ref"]]
        assert point["class_id"] == 628 and observed.reader.scalar(point, 117) == 64
        assert all(
            observed.reader.scalar(r, 3399) != row["temperature_ref"] for r in observed.records
        )
    after = {**files, 3: output}
    assert verify_trial(after, output, expected_native_sha256=sha(observed.data))[
        "native_image_matches"
    ]
    restored, proof = compile_trial_restore(after, files, edit)
    assert proof["removed_native_records"] == 2 * len(addresses)
    assert MoiIdentity(restored).data == before.data


@pytest.mark.parametrize(
    "addresses", [[198], [207], [201, 201], [True], [202, 201], list(range(199, 208))]
)
def test_address_page_rejects_outside_duplicate_boolean_or_unordered_addresses(addresses):
    with pytest.raises(ValueError):
        TrialEdit(**{**edit_for(sensor_source()), "addresses": addresses})


def test_disabled_sensor_or_unknown_format_does_not_acquire_migration_support():
    assert not sensor_sources(sensor_source(enabled=False))
    with pytest.raises(ValueError, match="data-model"):
        sensor_sources(sensor_source(version=(62, 62)))


def test_stale_selected_definition_and_occupied_identity_or_bus_address_are_rejected():
    files = sensor_source()
    edit = edit_for(files)
    with pytest.raises(ValueError, match="changed"):
        compile_trial(files, {**edit, "sensor_sha256": "0" * 64})
    occupied = native_record(
        627,
        3000010,
        [
            (32527, encoded(CharacterString("8-1/307_2.627_3000010"))),
            (75, encoded(ObjectIdentifier((627, 3000010)))),
        ],
    )
    files = sensor_source(extra=[occupied])
    with pytest.raises(ValueError, match="occupied"):
        compile_trial(files, edit_for(files))
    other_mac = native_record(
        627,
        88,
        [
            (32527, encoded(CharacterString("8-1/307_2.627_88"))),
            (75, encoded(ObjectIdentifier((627, 88)))),
            (2858, encoded(Unsigned(201))),
        ],
    )
    files = sensor_source(extra=[other_mac])
    with pytest.raises(ValueError, match="owns a trial address"):
        compile_trial(files, edit_for(files))


@pytest.mark.parametrize("link", [False, True])
def test_restore_refuses_new_program_links_and_unrelated_setting_changes(link):
    original = sensor_source()
    edit = edit_for(original)
    output, compilation = compile_trial(original, edit)
    app = MoiIdentity(output)
    records = [app.data[r["offset"] : r["end_offset"]] for r in app.records]
    if link:
        record = next(r for r in app.records if r["class_id"] == 556)
        index = app.records.index(record)
        records[index] = replace_properties(
            app,
            record,
            {3399: encoded(CharacterString(compilation["trial_points"][0]["temperature_ref"]))},
        )
    else:
        records[0] = replace_properties(app, app.root, {900: encoded(Real(999))})
    changed = {**original, 3: archive(app, records)}
    if not link:
        # A real saved-value change must accompany an edited archive default.
        dynamic = bytearray(changed[12])
        payload = struct.pack(">f", 999)
        dynamic[4:8] = payload
        dynamic[8] = header_crc(payload) ^ 255
        changed[12] = bytes(dynamic)
    with pytest.raises(ValueError, match="references a trial|changed during"):
        compile_trial_restore(changed, original, edit)


def test_native_image_or_existing_saved_parameter_mismatch_cannot_verify():
    files = sensor_source()
    output, proof = compile_trial(files, edit_for(files))
    with pytest.raises(ValueError, match="exact reviewed"):
        verify_trial(files, output, expected_native_sha256=proof["native_payload_sha256"])
    after = copy.deepcopy({**files, 3: output})
    dynamic = bytearray(after[12])
    payload = struct.pack(">f", 123)
    dynamic[4:8] = payload
    dynamic[8] = header_crc(payload) ^ 255
    after[12] = bytes(dynamic)
    with pytest.raises(ValueError, match="saved|parameter"):
        verify_trial(after, output, expected_native_sha256=proof["native_payload_sha256"])
