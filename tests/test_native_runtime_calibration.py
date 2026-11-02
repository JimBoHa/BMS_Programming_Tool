"""Actual runtime calibration can differ while stored application bytes still match."""

import gzip
import struct
import types

import pytest
from bacpypes3.apdu import ReadPropertyACK, ReadPropertyRequest
from bacpypes3.constructeddata import Any
from bacpypes3.primitivedata import CharacterString, Double, ObjectIdentifier, Real
from bms_tool.native_runtime_calibration import read_runtime_calibration

from .test_controller_application import encoded, native_record
from .test_moi_parameters import parameters_source
from .test_native_applications import apply_request, review
from .test_native_applications import native_link as native_link  # noqa: F401


def flow_source(*, value=3.5, count=1, include_value=True):
    archive, static, dynamic = parameters_source(compressed=False)
    records = []
    for index in range(count):
        props = [
            (32527, encoded(CharacterString(f"controller/flow-{index}"))),
            (75, encoded(ObjectIdentifier((570, 73 + index)))),
        ]
        if include_value:
            props.append((3506, encoded(Real(value))))
        records.append(native_record(570, 73 + index, props))
    data = bytearray(archive)
    struct.pack_into("<I", data, 10, struct.unpack_from("<I", data, 10)[0] + len(records))
    data.extend(b"".join(struct.pack("<H", len(r) + 2) + r for r in records))
    return {3: gzip.compress(bytes(data), mtime=0), 11: static, 12: dynamic}


async def observed(files, *, value=0.25, failure=None, mutate=None, **kwargs):
    requests = []

    async def exchange(session, request, expected):
        assert type(request) is ReadPropertyRequest and expected is ReadPropertyACK
        assert int(request.propertyIdentifier) == 3506 and request.propertyArrayIndex is None
        requests.append(request)
        if failure:
            raise failure
        reply = ReadPropertyACK(
            objectIdentifier=request.objectIdentifier,
            propertyIdentifier=3506,
            propertyValue=Any(value if isinstance(value, Double) else Real(value)),
        )
        if mutate:
            mutate(reply)
        return reply

    result = await read_runtime_calibration(files[3], exchange, {}, **kwargs)
    return result, requests


async def test_stored_image_and_real_runtime_are_separate_observations():
    report, requests = await observed(flow_source())
    assert len(requests) == 1 and str(requests[0].objectIdentifier) == "570,73"
    assert report["complete"] and report["read_only"] and not report["field_writes"]
    row = report["changed"][0]
    assert row["application_value"] == 3.5 and row["live_value"] == 0.25


async def test_no_flow_record_never_queries_a_fabricated_model_inventory():
    files = flow_source(count=0)
    report, requests = await observed(files)
    assert report["not_applicable"] and report["complete"] and not requests


async def test_absent_captured_value_is_explicit_and_does_not_claim_equality():
    report, _ = await observed(flow_source(include_value=False))
    assert report["fields"][0]["application_value"] is None
    assert report["fields"][0]["live_value"] == 0.25 and not report["changed"]


@pytest.mark.parametrize(
    "failure", [TimeoutError(), ValueError("unknown-property"), OSError("network unavailable")]
)
async def test_unavailable_live_value_cannot_be_reported_as_unchanged(failure):
    report, _ = await observed(flow_source(), failure=failure)
    assert not report["complete"] and report["fields"][0]["status"] == "unavailable"
    assert "live_value" not in report["fields"][0] and report["fields"][0]["error"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: setattr(r, "objectIdentifier", ObjectIdentifier((570, 74))),
        lambda r: setattr(r, "propertyIdentifier", 3505),
        lambda r: setattr(r, "propertyArrayIndex", 1),
    ],
)
async def test_echo_mismatch_is_a_verification_error(mutate):
    with pytest.raises(ValueError, match="does not match"):
        await observed(flow_source(), mutate=mutate)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Double(0.25)])
async def test_nonfinite_or_wrong_native_type_is_not_calibration_acceptance(value):
    with pytest.raises(ValueError, match="nonfinite|native Real"):
        await observed(flow_source(), value=value)


async def test_runtime_read_budget_is_explicit():
    report, requests = await observed(flow_source(count=2), limit=1)
    assert len(requests) == 1 and report["total"] == 2 and report["limit"] == 1
    assert not report["complete"]


async def test_native_transfer_reports_live_calibration_even_when_post_saved_files_are_unchanged(
    native_link,
):
    peer, _, _, service, _ = native_link
    peer.files = flow_source()
    original = peer.do_ReadPropertyRequest

    async def current(self, request):
        if (
            request.objectIdentifier == ObjectIdentifier((570, 73))
            and int(request.propertyIdentifier) == 3506
        ):
            await self.response(
                ReadPropertyACK(
                    context=request,
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=3506,
                    propertyValue=Any(Real(0.25)),
                )
            )
        else:
            await original(request)

    peer.do_ReadPropertyRequest = types.MethodType(current, peer)
    _, plan = await review(native_link)
    result = await service.apply(**apply_request(plan))
    assert result["result"]["status"] == "verified", result
    assert result["result"]["preservation"]["device_calculated_changes"] == []
    live = result["result"]["runtime_calibration"]
    assert live["complete"] and live["changed"][0]["application_value"] == 3.5
    assert live["changed"][0]["live_value"] == 0.25
    assert peer.events.count(("state", "start-restore")) == 1
