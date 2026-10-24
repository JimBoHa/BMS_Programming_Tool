"""Hand-calculated integer cases and literal direct/routed native properties."""

import asyncio
import json
import struct

import pytest
from bms_tool.accumulator_prescale import (
    PROFILE,
    UINT32,
    Configuration,
    PrescaleReviews,
    ReviewKey,
    ReviewRequest,
    calculate,
    canonical,
    digest,
    strict_json,
)
from bms_tool.connections import Bacnet
from bms_tool.point_status import ACCUMULATOR_PROPERTIES, PointStatus
from bms_tool.storage import Store
from pydantic import ValidationError

from .test_connections import free_udp
from .test_point_status import PointPeer, options
from .test_schedule_inventory import retired, unsigned, verify_hash


def configuration(**changes):
    return (
        dict(
            multiplier="3",
            modulo_divide="2",
            initial_pv="0",
            initial_remainder="0",
            max_pv=str(UINT32),
            batches=[{"pulses": "1"}] * 4,
        )
        | changes
    )


class MeterPeer(PointPeer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prescale = b"\x09\x03\x19\x02"
        self.scale = b"\x0c" + struct.pack(">f", -0.0)
        self.maximum = UINT32

    def value(self, obj, prop, index):
        if prop == "prescale":
            return self.prescale
        if prop == "scale":
            return self.scale
        if prop in (
            "max-pres-value",
            "pulse-rate",
            "limit-monitoring-interval",
            "value-before-change",
        ):
            return unsigned(self.maximum if prop == "max-pres-value" else 9)
        if prop == "value-change-time":
            return b"\xa4\x7e\x0a\x15\x03\xb4\x0d\x18\x06\x63"
        return super().value(obj, prop, index)


async def make_meter_peer(**kwargs):
    peer = MeterPeer(**kwargs)
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    return peer


@pytest.fixture
async def link(tmp_path):
    peer = await make_meter_peer()
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


def test_exact_carried_remainders_match_independent_finite_matrix():
    # Four independent 3/2 pulses: first batch cannot round up; second consumes carry.
    result = calculate(configuration())
    assert [
        (r["increment"], r["retained_pv"], r["retained_remainder"]) for r in result["rows"]
    ] == [("1", "1", "1"), ("2", "3", "0"), ("1", "4", "1"), ("2", "6", "0")]
    assert [r["numerator"] for r in result["rows"]] == ["3", "4", "3", "4"]
    cases = [
        (0, 3, 1, [4, 0, 9], [0, 0, 0], [1, 1, 1]),
        (2, 5, 4, [0, 1, 2], [0, 1, 1], [4, 1, 0]),
        (5, 2, 1, [2, 3, 0], [5, 8, 0], [1, 0, 0]),
    ]
    for multiplier, divisor, remainder, pulses, increments, remainders in cases:
        result = calculate(
            configuration(
                multiplier=str(multiplier),
                modulo_divide=str(divisor),
                initial_remainder=str(remainder),
                batches=[{"pulses": str(v)} for v in pulses],
            )
        )
        assert [int(r["increment"]) for r in result["rows"]] == increments
        assert [int(r["retained_remainder"]) for r in result["rows"]] == remainders
    # Partitioning preserves the carried integer result, even far above binary64 precision.
    large = configuration(
        multiplier=str(UINT32), modulo_divide=str(UINT32), batches=[{"pulses": str(UINT32)}]
    )
    row = calculate(large)["rows"][0]
    assert row["numerator"] == "18446744065119617025" and row["retained_pv"] == str(UINT32)
    assert row["retained_remainder"] == "0"
    partitioned = configuration(
        multiplier=str(UINT32 - 1),
        modulo_divide=str(UINT32),
        batches=[{"pulses": "2147483647"}, {"pulses": "2147483648"}],
    )
    whole = calculate(
        configuration(
            multiplier=str(UINT32 - 1), modulo_divide=str(UINT32), batches=[{"pulses": str(UINT32)}]
        )
    )
    split = calculate(partitioned)
    assert (
        (split["final_pv"], split["final_remainder"])
        == (str(UINT32 - 1), "0")
        == (whole["final_pv"], whole["final_remainder"])
    )
    assert split["rows"][0]["retained_remainder"] == "2147483648"


def test_limit_stops_before_batch_without_wrapping_or_committing_its_remainder():
    result = calculate(configuration(initial_pv="8", max_pv="10"))
    assert result["status"] == "stopped_at_limit" and not result["complete"]
    assert [r["status"] for r in result["rows"]] == [
        "accepted",
        "declared_limit_exceeded",
        "not_evaluated_after_limit",
        "not_evaluated_after_limit",
    ]
    assert result["rows"][1]["candidate_pv"] == "11"
    assert result["final_pv"] == "9" and result["final_remainder"] == "1"
    assert "increment" not in result["rows"][2]


@pytest.mark.parametrize(
    "changes",
    [
        {"multiplier": True},
        {"multiplier": 1},
        {"multiplier": "1.0"},
        {"multiplier": "01"},
        {"multiplier": "+1"},
        {"multiplier": "-1"},
        {"multiplier": str(UINT32 + 1)},
        {"multiplier": "١"},
        {"modulo_divide": "0"},
        {"initial_remainder": "2"},
        {"initial_pv": "11", "max_pv": "10"},
        {"batches": []},
        {"batches": [{"pulses": "1"}] * 257},
        {"batches": [{"pulses": 1.0}]},
        {"batches": [{"pulses": str(UINT32 + 1)}]},
        {"unknown": "1"},
    ],
    ids=[
        "bool",
        "number",
        "float-text",
        "leading-zero",
        "plus",
        "negative",
        "range",
        "unicode",
        "zero-divisor",
        "remainder",
        "initial-limit",
        "empty",
        "batch-cap",
        "float-batch",
        "batch-range",
        "unknown",
    ],
)
def test_strict_integer_strings_and_unsigned_bounds(changes):
    with pytest.raises(ValidationError):
        Configuration(**configuration(**changes))


@pytest.mark.parametrize("routed", [False, True])
async def test_explicit_real_udp_metering_and_separate_native_scale(link, routed):
    old, client, service = link
    peer = await make_meter_peer(routed=routed)
    try:
        # Existing reads keep exact old query shape unless explicitly opted in.
        unchanged = await service.read(**options(peer, object_ids=["accumulator,1"]))
        assert unchanged["complete"] and not any(
            p in ACCUMULATOR_PROPERTIES for _, p, _ in peer.requests
        )
        peer.requests.clear()
        report = await service.read(
            **options(
                peer,
                object_ids=["accumulator,1", "analog-input,2"],
                include_accumulator_metadata=True,
            )
        )
        assert report["complete"], report
        item, other = report["objects"]
        assert item["accumulator_metering"]["prescale_usable_for_offline_review"]
        props = item["properties"]
        assert props["prescale"]["value"] == {"multiplier": 3, "moduloDivide": 2}
        assert props["prescale"]["encoded_value"]["hex"] == "3e090319023f"
        assert props["scale"]["value"] == {"type": "floatScale", "value": -0.0}
        assert props["scale"]["encoded_value"]["hex"] == "3e0c800000003f"
        assert props["value-change-time"]["value"]["time"]["fields"] == [13, 24, 6, 99]
        assert item["accumulator_metering"]["raw_pulse_count"] is None
        assert other["accumulator_metering"]["status"] == "not_applicable"
        assert all(
            obj == "accumulator,1"
            for obj, prop, _ in peer.requests
            if prop in ACCUMULATOR_PROPERTIES
        )
        assert all(
            props[prop]["transport_evidence"]["next_hop"] == peer.endpoint
            for prop in ACCUMULATOR_PROPERTIES
        )
        reviews = PrescaleReviews(service)
        count = len(peer.requests)
        review = reviews.review(
            ReviewRequest(
                profile_sha256=PROFILE["sha256"],
                configuration=configuration(),
                source={"report_id": report["id"], "object_id": "accumulator,1"},
            )
        )
        assert review["native_source"]["report_evidence_sha256"] == report["evidence_sha256"]
        assert review["native_source"]["properties"]["present-value"]["value"] == 900
        assert (
            review["simulation"]["final_pv"] == "6"
        )  # NativePV900 is not raw count nor initial state.
        assert len(peer.requests) == count
        verify_hash(report)
        retired(client)
        assert not peer.errors
    finally:
        peer.close()


@pytest.mark.parametrize(
    "behavior,status",
    [
        ("native_error", "native_error"),
        ("timeout", "timeout"),
        ("trailing", "decode_error"),
        ("wrong_property", "protocol_error"),
    ],
)
async def test_unsupported_timeout_and_corrupt_metering_do_not_invent_coefficients(
    link, behavior, status
):
    peer, client, service = link
    peer.behavior, peer.corrupt_property = behavior, "prescale"
    report = await service.read(
        **options(peer, object_ids=["accumulator,1"], include_accumulator_metadata=True)
    )
    item = report["objects"][0]
    assert not report["complete"]
    assert item["properties"]["prescale"]["status"] == status
    assert not item["accumulator_metering"]["prescale_usable_for_offline_review"]
    assert "prescale" not in item["accumulator_metering"]
    verify_hash(report)
    retired(client)


@pytest.mark.parametrize("value", [b"\x09\x03\x19\x00", b"\x0d\x05\x01\x00\x00\x00\x00\x19\x02"])
async def test_zero_divisor_or_large_native_unsigned_remains_unresolved(link, value):
    peer, client, service = link
    peer.prescale = value
    report = await service.read(
        **options(peer, object_ids=["accumulator,1"], include_accumulator_metadata=True)
    )
    item = report["objects"][0]
    assert not item["accumulator_metering"]["prescale_usable_for_offline_review"]
    assert item["properties"]["prescale"]["encoded_value"]["complete"]
    retired(client)


async def test_unknown_scale_choice_is_opaque_native_evidence_not_applied(link):
    peer, client, service = link
    peer.scale = b"\x29\x07"  # Context2 is outside the pinned standard Scale choice.
    report = await service.read(
        **options(peer, object_ids=["accumulator,1"], include_accumulator_metadata=True)
    )
    prop = report["objects"][0]["properties"]["scale"]
    assert prop["status"] == "decode_error" and prop["encoded_value"]["hex"] == "3e29073f"
    assert "value" not in prop
    retired(client)


@pytest.mark.parametrize("routed", [False, True])
async def test_cancellation_and_source_spoof_keep_completed_rows_owned(link, routed):
    peer, client, service = link
    peer.routed = routed
    rogue = asyncio.DatagramProtocol()
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: rogue, local_addr=("127.0.0.1", 0)
    )
    peer.rogue = transport
    peer.hold_property = "scale"
    task = asyncio.create_task(
        service.read(
            **options(peer, object_ids=["accumulator,1"], include_accumulator_metadata=True)
        )
    )
    try:
        await peer.entered.wait()
        service.cancel("point_status_operation")
        report = await task
        item = report["objects"][0]
        assert (
            report["status"] == "cancelled"
            and item["properties"]["prescale"]["value"]["multiplier"] == 3
        )
        if routed:
            assert report["read_budget"]["ignored_transport_candidates"] > 0
        assert all(
            row["transport_evidence"]["next_hop"] == peer.endpoint
            for row in item["properties"].values()
        )
        assert "scale" not in item["properties"]
        retired(client)
    finally:
        transport.close()


def test_session_eviction_stale_key_and_import_recompute_without_native_reuse():
    class NoPoints:
        def detail(self, _):
            raise AssertionError("Offline operation cannot query even a retained native report")

    service = PrescaleReviews(NoPoints())
    request = ReviewRequest(profile_sha256=PROFILE["sha256"], configuration=configuration())
    first = service.review(request)
    key = ReviewKey(id=first["id"], content_sha256=first["content_sha256"])
    raw, _ = service.get(key)
    assert strict_json(raw)["simulation"]["final_pv"] == "6"
    restored = service.import_configuration(raw)
    assert (
        restored["configuration"] == configuration() and restored["native_source_reused"] is False
    )
    mutated = json.loads(raw)
    mutated["simulation"]["final_pv"] = "7"
    mutated["content_sha256"] = digest({k: v for k, v in mutated.items() if k != "content_sha256"})
    with pytest.raises(ValueError, match="arithmetic/source"):
        service.import_configuration(canonical(mutated))
    with pytest.raises(ValueError, match="source differs"):
        service.get(ReviewKey(id=first["id"], content_sha256="0" * 64))
    for _ in range(8):
        service.review(request)
    with pytest.raises(ValueError, match="expired"):
        service.get(key)
    assert len(service.reviews) == 8
    changed = request.model_copy(update={"profile_sha256": "0" * 64})
    with pytest.raises(ValueError, match="profile changed"):
        service.review(changed)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b"\xff",
        b"[" * 10000,
        b" " * (256 * 1024 + 1),
    ],
    ids=["duplicate", "nan", "infinity", "utf8", "depth", "bytes"],
)
def test_bounded_strict_import_json(raw):
    with pytest.raises(ValueError):
        strict_json(raw)


async def test_wrong_point_identity_blocks_metering_and_baseline_binding(link):
    peer, client, service = link
    peer.wrong_point = True
    report = await service.read(
        **options(peer, object_ids=["accumulator,1"], include_accumulator_metadata=True)
    )
    assert not report["objects"][0]["identity_verified"]
    assert not any(prop in ACCUMULATOR_PROPERTIES for _, prop, _ in peer.requests)
    reviews = PrescaleReviews(service)
    with pytest.raises(ValueError, match="identity-verified"):
        reviews.review(
            ReviewRequest(
                profile_sha256=PROFILE["sha256"],
                configuration=configuration(),
                source={"report_id": report["id"], "object_id": "accumulator,1"},
            )
        )
    assert not reviews.reviews
    retired(client)
