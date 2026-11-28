"""Synthetic expansion identity, saved storage and historical restore checks."""

import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_parameter_qualification import qualify_parameter_additions
from bms_tool.native_snapshot_restore import verify_expansion_bindings

from .test_controller_application import encoded, native_record
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_snapshot_restore import apply_request, saved_request


def expansion_files(
    *,
    release=(67, 65),
    cid=598,
    instance=201,
    declared=201,
    value=903,
    address=5,
    model="Example module",
    reference="controller/expansion",
    explicit=False,
    marker=0,
    storage_type=2,
):
    root = native_record(
        194,
        5136,
        [
            (32527, encoded(CharacterString("controller"))),
            (75, encoded(ObjectIdentifier((8, 5136)))),
            (2390, encoded(CharacterString("Authored controller"))),
            (70, encoded(CharacterString("UNLISTED-MODEL"))),
            (4128, encoded(Unsigned(release[0]))),
            (4129, encoded(Unsigned(release[1]))),
            (65000, encoded(Unsigned(marker))),
        ],
    )
    fields = [
        (32527, encoded(CharacterString(reference))),
        (75, encoded(ObjectIdentifier((cid, declared)))),
        (2858, encoded(Unsigned(address))),
        (3675, encoded(Unsigned(5))),
        (3676, encoded(CharacterString(model))),
    ]
    if explicit:
        fields.append((3590, encoded(Unsigned(value))))
    module = native_record(cid, instance, fields)
    archive = struct.pack("<6sHHI", b"\x02\x00MOI\x00", 194, 1, 2) + b"".join(
        struct.pack("<H", len(row) + 2) + row for row in (root, module)
    )
    data = value.to_bytes(4, "big")
    static = struct.pack(">HIHBBHHH", 16, cid << 22 | instance, 3590, 0x6F, storage_type, cid, 0, 0)
    return {3: archive, 11: static, 12: data + bytes([header_crc(data) ^ 255])}


def compiled(files):
    output, merge = ParameterApplication(*(files[i] for i in (3, 11, 12))).compile()
    qualify_parameter_additions(output, merge)
    return MoiIdentity(output)


@pytest.mark.parametrize("value", [0, 257, 0xFFFFFFFF])
def test_reconstructs_one_saved_startup_id_with_full_unsigned_range(value):
    image = compiled(expansion_files(value=value))
    prop = image.records[1]["properties"][3590]["scalar"]
    assert prop == {"datatype": "Unsigned", "value": value}


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"release": (66, 65)}, "Unqualified"),
        ({"release": (67, 66)}, "Unqualified"),
        ({"cid": 597}, "Unqualified"),
        ({"declared": 202}, "declared object"),
        ({"storage_type": 4}, "UnsignedLong"),
    ],
)
def test_omitted_expansion_identifier_rejects_other_schemas(overrides, reason):
    with pytest.raises(ValueError, match=reason):
        compiled(expansion_files(**overrides))


@pytest.mark.parametrize(
    "difference",
    [
        {"value": 904},
        {"address": 6},
        {"instance": 202, "declared": 202},
        {"model": "Replacement module"},
        {"reference": "controller/replacement"},
    ],
)
@pytest.mark.parametrize("explicit_current", [False, True])
def test_restore_cannot_replay_a_changed_module_or_its_startup_id(difference, explicit_current):
    old = expansion_files()
    current = expansion_files(**difference, explicit=explicit_current)
    with pytest.raises(ValueError, match="expansion module"):
        verify_expansion_bindings(old[3], compiled(old), current[3], compiled(current))


def test_matching_settings_accept_explicit_or_omitted_current_value():
    old = expansion_files()
    for explicit in (True, False):
        current = expansion_files(explicit=explicit, marker=1)
        verify_expansion_bindings(old[3], compiled(old), current[3], compiled(current))


async def test_authored_peer_review_qualifies_the_original_and_refuses_a_changed_module(
    native_link,
):
    peer, _, _, native, target = native_link
    peer.files = expansion_files()
    capture = await native.capture(**target, operation_id="capture-expansion-origin")
    capture, _ = native.storage.load(capture["id"])
    source, evidence = native.restore_source(saved_request(capture))
    assert evidence["compilation"]["omitted_field_qualification"]["qualified_fields"] == 1
    assert MoiIdentity(source).reader.scalar(MoiIdentity(source).records[1], 3590) == 903
    peer.files = expansion_files(marker=1)
    plan = await native.preview_snapshot_restore(
        **target, **saved_request(capture), operation_id="review-matching-expansion"
    )
    assert plan["can_apply"]
    peer.files = expansion_files(marker=1, value=904)
    with pytest.raises(ValueError, match="expansion module"):
        await native.preview_snapshot_restore(
            **target, **saved_request(capture), operation_id="review-replaced-expansion"
        )
    assert not any(event[0] == "write" for event in peer.events)


async def test_matching_expansion_is_preserved_across_a_verified_restore(native_link):
    peer, _, _, native, target = native_link
    peer.files = expansion_files()
    cap = await native.capture(**target, operation_id="capture-matched-expansion")
    cap, originals = native.storage.load(cap["id"])
    peer.files = expansion_files(marker=1)
    plan = await native.preview_snapshot_restore(
        **target, **saved_request(cap), operation_id="review-matched-expansion"
    )
    result = await native.apply_snapshot_restore(**apply_request(plan))
    assert not result["pending"] and result["result"]["status"] == "verified"
    assert MoiIdentity(peer.files[3]).data == compiled(originals).data
    assert native.storage.load(cap["id"])[1] == originals
