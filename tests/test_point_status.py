"""Native point status over independent literal BACnet UDP replies."""

import asyncio
import math
import struct

import pytest
from bacpypes3.basetypes import EngineeringUnits
from bms_tool.connections import Bacnet
from bms_tool.point_status import PointStatus, PointStatusRequest
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_schedule_inventory import SchedulePeer, oid, retired, text, unsigned, verify_hash


class PointPeer(SchedulePeer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.flags, self.reliability, self.service_state = 0, 0, False
        self.priority_count = 16
        self.unit_code = int(EngineeringUnits("degrees-fahrenheit"))
        self.wrong_point = False

    def value(self, obj, prop, index):
        kind = int(obj[0])
        if prop == "object-identifier":
            return b"\xc4" + oid(kind, 99 if self.wrong_point and kind != 8 else obj[1])
        if prop == "object-name":
            return text(f"Native {obj}")
        if prop == "description":
            return text("Native point fixture")
        if prop == "present-value":
            return (
                b"\x44" + struct.pack(">f", 12.5)
                if kind in (0, 1, 2)
                else b"\x91\x01"
                if kind in (3, 4, 5)
                else unsigned(3 if kind != 23 else 900)
            )
        if prop == "units":
            return b"\x92" + struct.pack(">H", self.unit_code)
        if prop == "status-flags":
            return b"\x82\x04" + bytes([self.flags])
        if prop == "reliability":
            return b"\x92" + struct.pack(">H", self.reliability)
        if prop == "out-of-service":
            return b"\x11" if self.service_state else b"\x10"
        if prop == "priority-array":
            if index == 0:
                return unsigned(self.priority_count)
            return b"\x44" + struct.pack(">f", -0.0) if index == 2 else b"\x00"
        if prop == "relinquish-default":
            return (
                b"\x44" + struct.pack(">f", 2.0)
                if kind in (1, 2)
                else b"\x91\x01"
                if kind in (4, 5)
                else unsigned(3)
            )
        raise ValueError(prop)


async def make_point_peer(**kwargs):
    peer = PointPeer(**kwargs)
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    return peer


def options(peer, **kwargs):
    return (
        dict(
            address="3001:7" if peer.routed else peer.endpoint,
            device="device,42",
            router=peer.endpoint if peer.routed else None,
            dnet=3001 if peer.routed else None,
            operation_id="point_status_operation",
            object_ids=["analog-input,1", "analog-output,2"],
        )
        | kwargs
    )


@pytest.fixture
async def link(tmp_path):
    peer = await make_point_peer()
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = PointStatus(client, client.store, timeout=0.08, operation_timeout=3, request_gap=0)
    try:
        yield peer, client, service
    finally:
        await service.close()
        client.close()
        peer.close()
        await asyncio.sleep(0.03)


@pytest.mark.asyncio
@pytest.mark.parametrize("routed", [False, True])
async def test_native_values_units_quality_and_priority_are_separate_raw_evidence(link, routed):
    old, client, service = link
    peer = await make_point_peer(routed=routed)
    try:
        peer.flags = 0xF0
        peer.reliability = 1
        peer.service_state = True
        report = await service.read(**options(peer, include_commandable=True))
        assert report["complete"], report
        ai, ao = report["objects"]
        props = ai["properties"]
        output = ao["properties"]
        assert (
            props["present-value"]["value"] == 12.5 and props["present-value"]["datatype"] == "Real"
        )
        assert (
            props["units"]["value"]["value"] == peer.unit_code
            and props["units"]["value"]["name"] == "degrees-fahrenheit"
        )
        assert (
            props["reliability"]["value"]["value"] == 1 and props["reliability"]["value"]["known"]
        )
        assert (
            props["status-flags"]["value"] == [1, 1, 1, 1]
            and props["out-of-service"]["value"] is True
        )
        assert ai["health_assessment"] == "Not established" and "good" not in report
        assert props["priority-array"]["status"] == "not_applicable"
        assert (
            output["priority-array"]["count_read"]["value"] == 16
            and len(output["priority-array"]["elements"]) == 16
        )
        assert output["priority-array"]["elements"][0]["value"] == {"type": "null", "value": None}
        value = output["priority-array"]["elements"][1]["value"]
        assert value["type"] == "real" and math.copysign(1, value["value"]) == -1
        assert output["relinquish-default"]["value"] == 2.0
        assert output["present-value"]["transport_evidence"]["next_hop"] == peer.endpoint
        assert all(prop != "object-list" for _, prop, _ in peer.requests)
        assert not peer.errors
        verify_hash(report)
        retired(client)
    finally:
        peer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identifier,datatype,value",
    [
        ("analog-value,1", "Real", 12.5),
        ("binary-input,1", "BinaryPV", 1),
        ("binary-output,1", "BinaryPV", 1),
        ("binary-value,1", "BinaryPV", 1),
        ("multi-state-input,1", "Unsigned", 3),
        ("multi-state-output,1", "Unsigned", 3),
        ("multi-state-value,1", "Unsigned", 3),
        ("accumulator,1", "Unsigned", 900),
    ],
)
async def test_standard_point_native_types_not_scaled_or_coerced(link, identifier, datatype, value):
    peer, client, service = link
    report = await service.read(**options(peer, object_ids=[identifier]))
    assert report["complete"], report
    props = report["objects"][0]["properties"]
    pv = props["present-value"]
    assert pv["datatype"] == datatype
    assert (pv["value"]["value"] if datatype == "BinaryPV" else pv["value"]) == value
    if identifier.startswith(("binary", "multi-state")):
        assert props["units"]["status"] == "not_applicable"
    assert not any(prop in ("priority-array", "relinquish-default") for _, prop, _ in peer.requests)
    verify_hash(report)
    retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "behavior,status,availability",
    [
        ("native_error", "native_error", "unsupported_property"),
        ("timeout", "timeout", "unknown"),
        ("trailing", "decode_error", "unknown"),
        ("wrong_property", "protocol_error", "unknown"),
    ],
)
async def test_missing_native_quality_is_not_bad_or_good_health(
    link, behavior, status, availability
):
    peer, client, service = link
    peer.behavior = behavior
    peer.corrupt_property = "reliability"
    report = await service.read(**options(peer, object_ids=["analog-input,1"]))
    props = report["objects"][0]["properties"]
    assert (
        props["reliability"]["status"] == status
        and props["reliability"]["availability"] == availability
    )
    assert report["status"] == "partial" and not report["complete"]
    assert props["present-value"]["value"] == 12.5 and props["status-flags"]["status"] == "ok"
    assert report["objects"][0]["health_assessment"] == "Not established"
    retired(client)


@pytest.mark.asyncio
async def test_unknown_units_and_reliability_codes_preserved_and_no_inferred_sensor_state(link):
    peer, client, service = link
    peer.unit_code = 60000
    peer.reliability = 999
    report = await service.read(**options(peer, object_ids=["analog-input,1"]))
    props = report["objects"][0]["properties"]
    assert props["units"]["value"]["value"] == 60000 and not props["units"]["value"]["known"]
    assert (
        props["reliability"]["value"]["value"] == 999 and not props["reliability"]["value"]["known"]
    )
    assert "operator" not in props["units"] and "healthy" not in report["health_assessment"]
    verify_hash(report)
    retired(client)


@pytest.mark.asyncio
async def test_wrong_point_identity_stops_its_fields_but_keeps_verified_device(link):
    peer, client, service = link
    peer.wrong_point = True
    report = await service.read(**options(peer, object_ids=["analog-input,1"]))
    assert report["identity_verified"] and not report["complete"]
    assert len(peer.requests) == 2 and not report["objects"][0]["identity_verified"]
    retired(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "close", "interface", "deadline"])
async def test_owned_read_retirement(link, action):
    peer, client, service = link
    peer.behavior = "hold"
    app = client.app
    if action == "deadline":
        service.operation_timeout = 0.05
    task = asyncio.create_task(service.read(**options(peer)))
    await peer.entered.wait()
    if action == "cancel":
        service.cancel("point_status_operation")
    elif action == "close":
        await service.close()
    elif action == "interface":
        client.close()
    report = await task
    assert (
        report["status"]
        == {
            "cancel": "cancelled",
            "close": "cancelled",
            "interface": "interface_changed",
            "deadline": "timeout",
        }[action]
    )
    assert not app._requests and not app.asap.clientTransactions and not client.lock.locked()
    assert "confirmation" not in app.nsap.local_adapter.clientPeer.multiplexer.__dict__
    verify_hash(report)


@pytest.mark.asyncio
async def test_priority_count_is_exact_and_partial_slots_survive_cancel(link):
    peer, client, service = link
    original = peer.value

    def intercept(obj, prop, index):
        value = original(obj, prop, index)
        if prop == "priority-array" and index == 2:
            peer.hold_property = "priority-array"
        return value

    peer.value = intercept
    task = asyncio.create_task(
        service.read(**options(peer, object_ids=["analog-output,2"], include_commandable=True))
    )
    await peer.entered.wait()
    service.cancel("point_status_operation")
    report = await task
    slots = report["objects"][0]["properties"]["priority-array"]
    assert slots["status"] == "cancelled" and len(slots["elements"]) == 2 and not slots["complete"]
    retired(client)


@pytest.mark.parametrize(
    "identifiers",
    [
        ["device,42"],
        ["analog-input," + "1" * 80],
        ["calendar,1"],
        ["analog-input,4194303"],
        ["analog-input,1", "analog-input,1"],
    ],
)
def test_invalid_selection_refused(identifiers):
    with pytest.raises(ValueError):
        PointStatusRequest(
            address="127.0.0.1",
            device="device,42",
            operation_id="valid_point_read",
            object_ids=identifiers,
        )


@pytest.mark.asyncio
async def test_malformed_flag_count_is_unknown_raw_evidence_not_a_health_result(link):
    peer, client, service = link
    original = peer.value

    def invalid(obj, prop, index):
        return b"\x82\x05\x00" if prop == "status-flags" else original(obj, prop, index)

    peer.value = invalid
    report = await service.read(**options(peer, object_ids=["analog-input,1"]))
    row = report["objects"][0]["properties"]["status-flags"]
    assert row["status"] == "invalid_native_value" and row["availability"] == "unknown"
    assert (
        row["raw_status_flag_bits"] == [0, 0, 0]
        and "value" not in row
        and row["encoded_value"]["hex"]
    )
    assert not report["complete"]
    retired(client)


@pytest.mark.asyncio
async def test_noncanonical_boolean_is_not_silently_normalized_to_in_service_state(link):
    peer, client, service = link
    original = peer.value

    def invalid(obj, prop, index):
        return b"\x12" if prop == "out-of-service" else original(obj, prop, index)

    peer.value = invalid
    report = await service.read(**options(peer, object_ids=["analog-input,1"]))
    row = report["objects"][0]["properties"]["out-of-service"]
    assert row["status"] == "invalid_native_value" and row["availability"] == "unknown"
    assert "value" not in row and row["encoded_value"]["hex"] == "3e123f"
    assert not report["complete"]
    retired(client)


@pytest.mark.asyncio
async def test_unverified_device_blocks_all_point_reads_and_reports_are_immutable(link):
    peer, client, service = link
    original = peer.value

    def wrong(obj, prop, index):
        return (
            b"\xc4" + oid(8, 99)
            if int(obj[0]) == 8 and prop == "object-identifier"
            else original(obj, prop, index)
        )

    peer.value = wrong
    report = await service.read(**options(peer))
    assert not report["identity_verified"] and len(peer.requests) == 1 and not report["objects"]
    saved = service.detail(report["id"])
    report["errors"].clear()
    assert service.detail(report["id"]) == saved
    restarted = PointStatus(client, client.store)
    assert not restarted.status()["reports"] and not restarted.status()["active_operation"]
    await restarted.close()
    retired(client)


@pytest.mark.asyncio
async def test_cancel_before_admission_and_duplicate_active_operation_never_dispatch_extra_reads(
    link,
):
    peer, client, service = link
    service.cancel("cancel_before_admission")
    with pytest.raises(ValueError, match="before admission"):
        await service.read(**options(peer, operation_id="cancel_before_admission"))
    assert not peer.requests
    peer.behavior = "hold"
    pending = asyncio.create_task(service.read(**options(peer)))
    await peer.entered.wait()
    with pytest.raises(ValueError, match="another read"):
        await service.read(**options(peer, operation_id="other_point_operation"))
    assert len(peer.requests) == 1
    service.cancel("point_status_operation")
    assert (await pending)["status"] == "cancelled"
    retired(client)


@pytest.mark.asyncio
async def test_routed_cancel_retires_hooks_and_preserves_completed_native_quality(link):
    original_peer, client, service = link
    peer = await make_point_peer(routed=True)
    peer.hold_property = "reliability"
    task = asyncio.create_task(service.read(**options(peer, object_ids=["analog-input,1"])))
    try:
        await asyncio.wait_for(peer.entered.wait(), 1)
        service.cancel("point_status_operation")
        report = await task
        assert report["status"] == "cancelled"
        props = report["objects"][0]["properties"]
        assert props["status-flags"]["value"] == [0, 0, 0, 0]
        assert props["status-flags"]["transport_evidence"]["npdu_source"] == "3001:7"
        assert "reliability" not in props and not report["complete"]
        assert (
            "process_npdu" not in client.app.nsap.__dict__
            and "indication" not in client.app.nsap.__dict__
        )
        retired(client)
    finally:
        peer.close()
