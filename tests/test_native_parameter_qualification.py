"""Unknown omitted fields stay local until their application datatype is qualified."""

import struct

import pytest
from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Real, Unsigned
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_parameter_qualification import qualify_parameter_additions

from .test_controller_application import encoded, native_record
from .test_moi_parameters import binary_saved_state, parameters_source
from .test_native_applications import native_link as native_link  # noqa: F401


def moved_property(pid, *, slot=0, cid=470):
    archive, static, dynamic = parameters_source(cid=cid)
    static = bytearray(static)
    static[slot * 16 + 6 : slot * 16 + 8] = pid.to_bytes(2, "big")
    return archive, bytes(static), dynamic


def test_storage_valid_unknown_omitted_property_is_not_transfer_qualification():
    files = moved_property(65002)
    output, report = ParameterApplication(*files).compile()
    assert any(p.get("added") for p in report["changed_parameters"])
    with pytest.raises(ValueError, match="Unqualified omitted application property"):
        qualify_parameter_additions(output, report)


@pytest.mark.parametrize("cid", [194, 470, 777])
def test_root_application_type_is_qualified_without_a_model_inventory(cid):
    output, report = ParameterApplication(*moved_property(119, slot=4, cid=cid)).compile()
    qualification = qualify_parameter_additions(output, report)
    assert qualification["qualified_fields"] == 1
    assert qualification["model_inventory_used"] is False


def test_known_attribute_with_wrong_storage_derived_application_type_is_rejected():
    output, report = ParameterApplication(*moved_property(119)).compile()
    with pytest.raises(ValueError, match="qualified application datatype"):
        qualify_parameter_additions(output, report)


@pytest.mark.parametrize(
    "pid,value,accepted",
    [
        (813, Unsigned(1), True),
        (813, Unsigned(255), True),
        (813, Unsigned(256), False),
        (813, Enumerated(1), False),
        (3164, Real(900), True),
        (3164, Unsigned(900), False),
    ],
)
def test_saved_analog_input_defaults_require_their_actual_application_types(pid, value, accepted):
    root, _, _ = parameters_source(compressed=False)
    record = native_record(
        240, 101, [(32527, encoded(CharacterString("controller/input"))), (pid, encoded(value))]
    )
    data = bytearray(root)
    struct.pack_into("<I", data, 10, struct.unpack_from("<I", data, 10)[0] + 1)
    data.extend(struct.pack("<H", len(record) + 2) + record)
    report = {
        "changed_parameters": [{"class": 240, "instance": 101, "property": pid, "added": True}]
    }
    if accepted:
        assert qualify_parameter_additions(bytes(data), report)["qualified_fields"] == 1
    else:
        with pytest.raises(ValueError, match="qualified application datatype"):
            qualify_parameter_additions(bytes(data), report)


@pytest.mark.parametrize("versions", [(60, 60), (62, 62), (66, 65), (66, 66), (102, 102), (60, 62)])
@pytest.mark.parametrize("pid,value", [(813, Unsigned(1)), (3164, Real(900))])
def test_saved_analog_defaults_do_not_qualify_an_undeclared_data_model(versions, pid, value):
    root = native_record(
        194,
        5136,
        [
            (32527, encoded(CharacterString("controller"))),
            (75, encoded(ObjectIdentifier((8, 5136)))),
            (2390, encoded(CharacterString("Authored controller"))),
            (70, encoded(CharacterString("UNLISTED-MODEL"))),
            (4128, encoded(Unsigned(versions[0]))),
            (4129, encoded(Unsigned(versions[1]))),
        ],
    )
    ai = native_record(
        240, 101, [(32527, encoded(CharacterString("controller/input"))), (pid, encoded(value))]
    )
    application = struct.pack("<6sHHI", b"\x02\x00MOI\x00", 194, 1, 2)
    application += b"".join(struct.pack("<H", len(r) + 2) + r for r in (root, ai))
    report = {
        "changed_parameters": [{"class": 240, "instance": 101, "property": pid, "added": True}]
    }
    if versions in {(60, 60), (62, 62), (66, 65)}:
        assert qualify_parameter_additions(application, report)["qualified_fields"] == 1
    else:
        with pytest.raises(ValueError, match="Unqualified omitted application property"):
            qualify_parameter_additions(application, report)


@pytest.mark.parametrize("external,cid", [(3, 242), (4, 239), (5, 168)])
def test_counter_defaults_are_qualified_but_runtime_timestamps_are_not_injected(external, cid):
    output, report = ParameterApplication(*binary_saved_state(external=external, cid=cid)).compile()
    assert qualify_parameter_additions(output, report)["qualified_fields"] == 2
    assert len(report["retained_runtime_parameters"]) == 1


def actuator_parameters(acs, dmcs):
    root = native_record(
        194,
        5136,
        [
            (32527, encoded(CharacterString("controller"))),
            (75, encoded(ObjectIdentifier((8, 5136)))),
            (2390, encoded(CharacterString("Authored controller"))),
            (70, encoded(CharacterString("UNLISTED-MODEL"))),
            (4128, encoded(Unsigned(acs))),
            (4129, encoded(Unsigned(dmcs))),
        ],
    )
    actuator = native_record(
        251,
        2131,
        [(32527, encoded(CharacterString("controller/actuator")))],
    )
    archive = struct.pack("<6sHHI", b"\x02\x00MOI\x00", 194, 1, 2)
    archive += b"".join(struct.pack("<H", len(r) + 2) + r for r in (root, actuator))
    payload = (123456).to_bytes(4, "big")
    selector = ((1 << 22) | 2131).to_bytes(4, "big")
    body = selector + (978).to_bytes(2, "big") + b"\x6f\x02\x00\xfb\x00\x00\x12\x34"
    static = (len(body) + 2).to_bytes(2, "big") + body
    return archive, static, payload + bytes([header_crc(payload) ^ 255])


@pytest.mark.parametrize("acs,dmcs", [(60, 60), (62, 62), (102, 102), (60, 62)])
def test_legacy_actuator_application_field_is_limited_to_its_qualified_data_model(acs, dmcs):
    output, report = ParameterApplication(*actuator_parameters(acs, dmcs)).compile()
    if (acs, dmcs) == (60, 60):
        assert qualify_parameter_additions(output, report)["qualified_fields"] == 1
    else:
        with pytest.raises(ValueError, match="Unqualified omitted application property"):
            qualify_parameter_additions(output, report)


async def test_capture_and_preview_both_block_an_unqualified_field_before_any_restore(native_link):
    peer, _, _, service, target = native_link
    peer.files = dict(zip((3, 11, 12), moved_property(65002), strict=True))
    capture = await service.capture(**target, operation_id="unqualified-source-capture")
    assert capture["source_identity_matches"] and not capture["instance_edit_supported"]
    assert "Unqualified omitted" in capture["compiler_error"]
    with pytest.raises(ValueError, match="Unqualified omitted"):
        await service.preview(
            **target,
            operation_id="unqualified-field-review",
            capture_id=capture["id"],
            new_instance=5336,
        )
    assert not any(e[0] == "write" or (e[0] == "state" and "restore" in e[1]) for e in peer.events)
    assert not service.storage.receipts()
