"""Authored local sensor references, including incomplete and redirected links."""

import struct

import pytest
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import TagList
from bms_tool.connections import Bacnet
from bms_tool.controller_workspace import ControllerPropertiesRequest, ControllerWorkspace
from bms_tool.network_sensor_reference import temperature_reference
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_point_status import make_point_peer
from .test_schedule_inventory import oid, text, unsigned


def wire(*, device=42, child=17, path=None):
    source = path or f"8-1/307_1.627_7.0_{child}"
    return (
        text(source)
        + b"\x4e\x4f\x00\xc4"
        + oid(0, child)
        + unsigned(1)
        + b"\x63\x03\x00\x07\xc4"
        + oid(8, device)
    )


@pytest.mark.parametrize(
    "data", [wire()[:-1], wire() + b"\x00", wire(path="8-1/627_9.0_7"), wire(child=4194303)]
)
def test_ambiguous_or_malformed_sensor_references_do_not_resolve(data):
    with pytest.raises((ValueError, IndexError)):
        temperature_reference(list(TagList.decode(PDU(b"\x3e" + data + b"\x3f"))), "627,7")


@pytest.mark.parametrize(
    "mode",
    [
        "verified",
        "offline",
        "flagged",
        "other-device",
        "other-vendor",
        "changed-link",
        "wrong-child-path",
        "reference-only",
    ],
)
async def test_exact_linked_input_and_quality_are_read_on_the_selected_peer(tmp_path, mode):
    peer = await make_point_peer(routed=True)
    previous = peer.value
    source_reads = 0
    child_reads = []

    def value(obj, prop, index):
        nonlocal source_reads
        if prop == "vendor-identifier":
            return unsigned(23 if mode == "other-vendor" else 5)
        if prop == "941":
            source_reads += 1
            return wire(
                device=43 if mode == "other-device" else 42,
                child=22 if mode == "changed-link" and source_reads > 1 else 17,
            )
        if prop == "913":
            return b"\x11" if mode == "offline" else b"\x10"
        if int(obj[0]) == 0:
            child_reads.append(str(obj))
            if prop == "32527":
                return text("8-1/307_1.627_7.0_" + ("22" if mode == "wrong-child-path" else "17"))
            if prop == "present-value":
                return b"\x44" + struct.pack(">f", 22.125)
            if prop == "units":
                return b"\x91\x3e"
            if prop == "status-flags":
                return b"\x82\x04\x20" if mode == "flagged" else b"\x82\x04\x00"
            if prop == "out-of-service":
                return b"\x10"
            if prop == "reliability":
                return b"\x91\x00"
        return previous(obj, prop, index)

    peer.value = value
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    try:
        report = await ControllerWorkspace(client, client.store).properties(
            address="3001:7",
            device="device,42",
            router=peer.endpoint,
            dnet=3001,
            object_ids=["627,7"],
            properties=["913", "941"],
            read_linked_zone_temperature=mode != "reference-only",
        )
        assert report["identity_verified"] and report["objects"][0]["identity_verified"]
        ref = report["objects"][0]["properties"]["941"]
        assert ref["encoded_value"]["complete"]
        if mode == "reference-only":
            assert (
                ref["datatype"] == "NetworkSensorInputReference"
                and not child_reads
                and "linked_zone_temperature" not in report
            )
            return
        result = report["linked_zone_temperature"]
        if mode in ("verified", "offline", "flagged"):
            assert result["status"] == "observed"
            assert result["quality"] == ("good" if mode == "verified" else "flagged")
            assert result["properties"]["present-value"]["value"] == 22.125
        else:
            assert result["status"] == "unconfirmed" and "properties" not in result
        if mode in ("other-device", "other-vendor"):
            assert not child_reads
        assert set(child_reads) <= {"analog-input,17"}
    finally:
        client.close()
        peer.close()


def test_link_requests_are_limited_to_one_sensor_and_its_reference():
    with pytest.raises(ValueError, match="Select one network sensor"):
        ControllerPropertiesRequest(
            address="127.0.0.1",
            device="device,42",
            object_ids=["627,7", "627,8"],
            properties=["941"],
            read_linked_zone_temperature=True,
        )
