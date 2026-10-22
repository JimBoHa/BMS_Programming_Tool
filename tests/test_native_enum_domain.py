"""Real independent UDP state metadata; native labels never imply portable codes."""

import asyncio
import struct

import pytest
from bms_tool.connections import Bacnet
from bms_tool.point_status import PointStatus
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_point_status import PointPeer, options
from .test_schedule_inventory import retired, verify_hash


def label_text(value):
    data = b"\x00" + value.encode()
    return (
        b"\x75\xfe" + struct.pack(">H", len(data)) + data
        if len(data) >= 254
        else b"\x75" + bytes([len(data)]) + data
        if len(data) >= 5
        else bytes([0x70 | len(data)]) + data
    )


def wire_unsigned(value):
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    return (bytes([0x20 | len(raw)]) if len(raw) < 5 else b"\x25" + bytes([len(raw)])) + raw


@pytest.fixture
async def link(tmp_path):
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = PointStatus(client, client.store, timeout=0.08, operation_timeout=3, request_gap=0)
    try:
        yield None, client, service
    finally:
        await service.close()
        client.close()
        await asyncio.sleep(0.03)


async def make_enum_peer(*, routed=False, **changes):
    peer = PointPeer(routed=routed)
    original = peer.value
    peer.states = 3
    peer.text_count = 3
    peer.code = 1
    peer.binary_code = 1
    peer.polarity = 1
    peer.labels = {1: "Stop", 2: "Run", 3: "Hold"}
    peer.inactive_text = "On"
    peer.active_text = "Off"
    peer.__dict__.update(changes)

    def value(obj, prop, index):
        if prop == "inactive-text":
            return label_text(peer.inactive_text)
        if prop == "active-text":
            return label_text(peer.active_text)
        if prop == "polarity":
            return b"\x91" + bytes([peer.polarity])
        if prop == "number-of-states":
            return wire_unsigned(peer.states)
        if prop == "state-text":
            return (
                wire_unsigned(peer.text_count)
                if index == 0
                else label_text(peer.labels.get(index, f"State {index}"))
            )
        if prop == "present-value" and int(obj[0]) in (3, 4, 5):
            return b"\x91" + bytes([peer.binary_code])
        if prop == "present-value" and int(obj[0]) in (13, 14, 19):
            return wire_unsigned(peer.code)
        return original(obj, prop, index)

    peer.value = value
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    return peer


@pytest.mark.asyncio
@pytest.mark.parametrize("routed", [False, True])
async def test_binary_native_code_label_and_reverse_polarity_stay_distinct(link, routed):
    old, client, service = link
    peer = await make_enum_peer(routed=routed)
    try:
        report = await service.read(
            **options(
                peer, object_ids=["binary-input,1", "binary-value,2"], include_enum_metadata=True
            )
        )
        assert report["complete"], report
        bi, bv = report["objects"]
        domain = bi["enum_domain"]
        assert [(s["code"], s["label"]) for s in domain["states"]] == [(0, "On"), (1, "Off")]
        assert (
            domain["value_validation"]["code"] == 1
            and bi["properties"]["present-value"]["value"]["value"] == 1
        )
        assert bi["properties"]["polarity"]["value"]["value"] == 1 and domain["code_range"] == {
            "minimum": 0,
            "maximum": 1,
        }
        assert bv["enum_domain"]["polarity"]["status"] == "not_applicable"
        assert not any(
            obj == "binary-value,2" and prop == "polarity" for obj, prop, _ in peer.requests
        )
        assert not peer.errors
        verify_hash(report)
        retired(client)
    finally:
        peer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [0, 4])
async def test_multistate_outside_one_through_native_count_remains_invalid_evidence(link, code):
    old, client, service = link
    peer = await make_enum_peer(code=code)
    try:
        report = await service.read(
            **options(peer, object_ids=["multi-state-value,1"], include_enum_metadata=True)
        )
        domain = report["objects"][0]["enum_domain"]
        assert domain["status"] == "invalid_value" and not report["complete"]
        assert domain["number_of_states"] == 3 and domain["value_validation"]["code"] == code
        assert [s["label"] for s in domain["states"]] == ["Stop", "Run", "Hold"]
        assert domain["value_validation"]["status"] == "outside_observed_numeric_range"
        retired(client)
    finally:
        peer.close()


@pytest.mark.asyncio
async def test_unknown_binarypv_is_not_truthy_or_coerced_to_zero_one(link):
    old, client, service = link
    peer = await make_enum_peer(binary_code=2)
    try:
        report = await service.read(
            **options(peer, object_ids=["binary-output,1"], include_enum_metadata=True)
        )
        domain = report["objects"][0]["enum_domain"]
        assert domain["status"] == "invalid_value"
        assert domain["value_validation"]["code"] == 2 and not report["complete"]
        assert report["objects"][0]["properties"]["present-value"]["value"]["value"] == 2
        retired(client)
    finally:
        peer.close()


@pytest.mark.asyncio
async def test_unknown_native_polarity_does_not_change_valid_binary_codes(link):
    _, client, service = link
    peer = await make_enum_peer(polarity=3)
    try:
        report = await service.read(
            **options(peer, object_ids=["binary-input,1"], include_enum_metadata=True)
        )
        item = report["objects"][0]
        assert not item["enum_domain"]["polarity"]["known"]
        assert not item["enum_domain"]["complete"] and not report["complete"]
        assert item["properties"]["polarity"]["value"]["value"] == 3
        assert item["enum_domain"]["value_validation"]["code"] == 1
        assert [s["code"] for s in item["enum_domain"]["states"]] == [0, 1]
        retired(client)
    finally:
        peer.close()


@pytest.mark.asyncio
async def test_malformed_present_value_stays_unknown_in_numeric_domain_validation(link):
    _, client, service = link
    peer = await make_enum_peer(behavior="trailing", corrupt_property="present-value")
    try:
        report = await service.read(
            **options(peer, object_ids=["multi-state-value,1"], include_enum_metadata=True)
        )
        item = report["objects"][0]
        assert item["properties"]["present-value"]["status"] == "decode_error"
        assert item["enum_domain"]["value_validation"]["status"] == "unknown"
        assert not item["enum_domain"]["complete"] and not report["complete"]
        assert item["enum_domain"]["states"][0]["code"] == 1
        retired(client)
    finally:
        peer.close()


@pytest.mark.asyncio
async def test_decoder_oversize_unsigned_codes_keep_typed_evidence_without_browser_rounding(link):
    _, client, service = link
    code = 2**60 + 1
    peer = await make_enum_peer(code=code, text_count=2**40)
    try:
        report = await service.read(
            **options(peer, object_ids=["multi-state-value,1"], include_enum_metadata=True)
        )
        item = report["objects"][0]
        check = item["enum_domain"]["value_validation"]
        assert check["status"] == "outside_native_unsigned32_profile" and check["code"] is None
        assert check["native_code_evidence"] == {
            "type": "integer",
            "encoding": "decimal",
            "value": str(code),
        }
        assert item["enum_domain"]["observed_state_text_count"] is None
        assert item["properties"]["state-text"]["status"] == "outside_count_profile"
        assert not item["properties"]["state-text"]["elements"]
        assert not report["complete"]
        verify_hash(report)
        retired(client)
    finally:
        peer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,limit,expected",
    [
        ({"text_count": 4}, 32, "state_text_count_mismatch"),
        ({"states": 100, "text_count": 100}, 2, "state_text_limited"),
        ({"states": 0}, 32, "number_of_states_unresolved_or_outside_profile"),
    ],
)
async def test_count_mismatch_limit_and_unknown_range_are_distinct(link, changes, limit, expected):
    old, client, service = link
    peer = await make_enum_peer(**changes)
    try:
        report = await service.read(
            **options(
                peer,
                object_ids=["multi-state-input,1"],
                include_enum_metadata=True,
                state_text_limit=limit,
            )
        )
        domain = report["objects"][0]["enum_domain"]
        assert not domain["complete"] and expected in [f["code"] for f in domain["findings"]]
        assert len(domain["states"]) <= limit and not report["complete"]
        retired(client)
    finally:
        peer.close()


@pytest.mark.asyncio
async def test_optional_state_metadata_native_rejection_keeps_numeric_value_and_unknown_labels(
    link,
):
    old, client, service = link
    peer = await make_enum_peer()
    peer.behavior = "native_error"
    peer.corrupt_property = "active-text"
    try:
        report = await service.read(
            **options(peer, object_ids=["binary-input,1"], include_enum_metadata=True)
        )
        item = report["objects"][0]
        assert item["properties"]["active-text"]["availability"] == "unsupported_property"
        assert (
            item["enum_domain"]["states"][1]["label"] is None
            and not item["enum_domain"]["labels_complete"]
        )
        assert item["enum_domain"]["value_validation"]["status"] == "within_standard_domain"
        assert not report["complete"]
        retired(client)
    finally:
        peer.close()


@pytest.mark.asyncio
async def test_label_duplicates_blank_and_large_text_do_not_change_codes(link):
    old, client, service = link
    peer = await make_enum_peer(labels={1: "", 2: "Same", 3: "Same"})
    try:
        report = await service.read(
            **options(peer, object_ids=["multi-state-output,1"], include_enum_metadata=True)
        )
        d = report["objects"][0]["enum_domain"]
        assert [s["code"] for s in d["states"]] == [1, 2, 3] and [
            f["code"] for f in d["findings"]
        ] == ["blank_native_label", "duplicate_native_label"]
        assert d["value_validation"]["code"] == 1
        peer.active_text = "x" * 300
        another = await service.read(
            **options(
                peer,
                object_ids=["binary-value,1"],
                include_enum_metadata=True,
                operation_id="large_label_read",
            )
        )
        item = another["objects"][0]
        assert item["properties"]["active-text"]["value"] == "x" * 300
        assert (
            item["enum_domain"]["states"][1]["label"] is None
            and item["enum_domain"]["states"][1]["label_status"] == "outside_metadata_label_profile"
        )
        retired(client)
    finally:
        peer.close()


@pytest.mark.asyncio
async def test_state_metadata_is_opt_in_and_partial_indexes_survive_cancel(link):
    old, client, service = link
    peer = await make_enum_peer(routed=True)
    original = peer.value

    def stop_after_one(obj, prop, index):
        val = original(obj, prop, index)
        if prop == "state-text" and index == 1:
            peer.hold_property = "state-text"
        return val

    try:
        first = await service.read(**options(peer, object_ids=["multi-state-value,1"]))
        assert "enum_domain" not in first["objects"][0] and not any(
            prop in ("state-text", "number-of-states") for _, prop, _ in peer.requests
        )
        peer.value = stop_after_one
        pending = asyncio.create_task(
            service.read(
                **options(
                    peer,
                    object_ids=["multi-state-value,1"],
                    include_enum_metadata=True,
                    operation_id="cancel_enum_metadata",
                )
            )
        )
        await peer.entered.wait()
        service.cancel("cancel_enum_metadata")
        report = await pending
        item = report["objects"][0]
        assert report["status"] == "cancelled" and item["enum_domain"]["status"] == "cancelled"
        assert (
            len(item["properties"]["state-text"]["elements"]) == 1
            and len(item["enum_domain"]["states"]) == 1
        )
        assert item["enum_domain"]["states"][0]["code"] == 1 and not item["enum_domain"]["complete"]
        verify_hash(report)
        retired(client)
    finally:
        peer.close()
