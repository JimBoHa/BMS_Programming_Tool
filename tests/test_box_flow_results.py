"""Independent storage and BACnet fixtures for historical box flow results."""

import hashlib
import struct

import pytest
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import CharacterString, TagList, Unsigned
from bms_tool.box_flow_results import flow_samples, result_bits
from bms_tool.connections import Bacnet
from bms_tool.controller_workspace import ControllerWorkspace
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_parameter_qualification import qualify_parameter_additions
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_controller_application import encoded, native_record
from .test_moi_parameters import parameters_source
from .test_native_applications import native_link as native_link
from .test_point_status import make_point_peer
from .test_schedule_inventory import unsigned


def pair(context, flow, position):
    return bytes([context * 16 + 14, 0x44]) + struct.pack(
        ">fBfB", flow, 0x44, position, context * 16 + 15
    )


def static_row(pid, datatype, contents):
    group = b"\x1e" + contents + b"\x1f\x00\x00"
    body = struct.pack(">IHBBH", (612 << 22) | 81, pid, 0x4F, datatype, 612)
    return struct.pack(">H", len(body) + len(group) + 4) + body + group + b"\x00\x00"


def source(version):
    raw, static, dynamic = parameters_source(compressed=False)
    archived = MoiIdentity(raw)
    # Both root version properties and their saved byte slots describe the same format.
    data = bytearray(raw)
    for pid in (4128, 4129):
        offset = archived.root["properties"][pid]["value_start_offset"]
        data[offset : offset + 2] = encoded(Unsigned(version))
    dynamic = bytearray(dynamic)
    for slot in (0, 2):
        dynamic[slot : slot + 2] = bytes([version, header_crc(bytes([version])) ^ 255])
    record = native_record(612, 81, [(32527, encoded(CharacterString("controller/flow-test")))])
    struct.pack_into("<I", data, 10, len(archived.records) + 1)
    data.extend(struct.pack("<H", len(record) + 2) + record)
    return bytes(data), static, bytes(dynamic)


def test_local_review_preserves_results_without_creating_application_defaults():
    archive, static, dynamic = source(60)
    values = pair(2, 21.5, 48) + pair(2, -0.0, 10)
    original, _ = ParameterApplication(archive, static, dynamic).compile()
    static += static_row(3668, 8, b"\x82\x00\x80") + static_row(3669, 22, values)
    editor = ParameterApplication(archive, static, dynamic)
    inspected, report = editor.compile(inspection_only=True)
    assert inspected == original
    flags, samples = report["box_flow_results"]
    assert flags["value"] == [1, 0, 0, 0, 0, 0, 0, 0]
    assert samples["value"] == [
        {"flow": 21.5, "damper_position_percent": 48.0},
        {"flow": -0.0, "damper_position_percent": 10.0},
    ]
    assert samples["encoded_sha256"] == hashlib.sha256(values).hexdigest()
    assert all(entry["instance"] == 81 for entry in (flags, samples))
    with pytest.raises(ValueError, match="historical box flow test results"):
        editor.compile()
    with pytest.raises(ValueError, match="preservation"):
        qualify_parameter_additions(inspected, report)


@pytest.mark.parametrize("version,pid,datatype", [(62, 3668, 8), (60, 3668, 22), (60, 3669, 8)])
def test_other_release_or_unknown_storage_does_not_receive_a_decoder(version, pid, datatype):
    archive, static, dynamic = source(version)
    with pytest.raises(ValueError, match="(Unsupported inline|Unqualified native)"):
        ParameterApplication(archive, static + static_row(pid, datatype, b"\x82\x00\x80"), dynamic)


@pytest.mark.parametrize(
    "raw", [b"\x4e\x4f", pair(2, 1, 2), pair(4, float("nan"), 2), b"\x4e\x21\x01\x21\x02\x4f"]
)
def test_shape_and_finite_values_required(raw):
    with pytest.raises(ValueError):
        flow_samples(list(TagList.decode(PDU(raw))), 4)


def test_empty_sample_list_and_incorrect_bit_width():
    assert flow_samples([], 4) == []
    with pytest.raises(ValueError):
        result_bits(list(TagList.decode(PDU(b"\x82\x01\x00"))))


async def test_backup_exposes_history_with_the_original_files_and_rejects_a_transfer(native_link):
    peer, _, _, service, target = native_link
    archive, static, dynamic = source(60)
    static += static_row(3669, 22, pair(2, 8.0, 16.0))
    peer.files = {3: archive, 11: static, 12: dynamic}
    receipt = await service.capture(**target, operation_id="capture-flow-history")
    assert receipt["source_identity_matches"] and not receipt["instance_edit_supported"]
    assert receipt["parameter_merge"]["box_flow_results"][0]["value"] == [
        {"flow": 8.0, "damper_position_percent": 16.0}
    ]
    assert service.storage.load(receipt["id"])[1] == peer.files
    with pytest.raises(ValueError, match="historical box flow test results"):
        await service.preview(
            **target,
            operation_id="review-flow-history",
            capture_id=receipt["id"],
            new_instance=5137,
        )
    assert not peer.restore and not peer.stage


@pytest.mark.parametrize(
    "vendor,cls,context,valid",
    [(5, 612, 4, True), (5, 612, 2, False), (9, 612, 4, False), (5, 611, 4, False)],
)
async def test_workspace_decodes_only_the_selected_vendor_class_and_wire_shape(
    tmp_path, vendor, cls, context, valid
):
    peer = await make_point_peer(routed=True)
    original = peer.value
    data = pair(context, 17.5, 42)

    def values(obj, prop, index):
        if prop == "vendor-identifier":
            return unsigned(vendor)
        if prop == "3669":
            return data
        return original(obj, prop, index)

    peer.value = values
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    try:
        report = await ControllerWorkspace(client, client.store).properties(
            address="3001:7",
            device="device,42",
            router=peer.endpoint,
            dnet=3001,
            object_ids=[f"{cls},81"],
            properties=["3669"],
        )
        assert report["identity_verified"] and report["objects"][0]["identity_verified"]
        row = report["objects"][0]["properties"]["3669"]
        assert row["encoded_value"]["complete"]
        assert row["encoded_value"]["hex"] == (b"\x3e" + data + b"\x3f").hex()
        if valid:
            assert row["status"] == "ok" and row["datatype"] == "BoxFlowTestSamples"
            assert row["value"] == [{"flow": 17.5, "damper_position_percent": 42.0}]
        else:
            assert row["status"] == "decode_error" and "value" not in row
    finally:
        client.close()
        peer.close()
