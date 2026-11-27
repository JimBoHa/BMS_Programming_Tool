"""Exercise matching-image downloads with independent on-wire device timestamps."""

from types import MethodType

import pytest
from bacpypes3.apdu import ReadPropertyACK
from bacpypes3.basetypes import DateTime, TimeStamp
from bacpypes3.constructeddata import Any
from bms_tool.moi_identity import MoiIdentity

from .test_moi_parameters import parameters_source
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_snapshot_restore import apply_request, saved_request


@pytest.mark.parametrize("model", ["MS-VMA1630-0", "FX-PCV1630-0"])
@pytest.mark.parametrize("change", ["advances", "unchanged", "backwards", "unsupported", "first"])
async def test_matching_program_requires_new_controller_restore_time(native_link, model, change):
    peer, _, _, native, target = native_link
    peer.metadata.update({"model-name": model, "firmware-revision": "6.2.0.1054"})
    peer.files = dict(zip((3, 11, 12), parameters_source(model=model, cid=194), strict=True))
    old_read = peer.do_ReadPropertyRequest
    hour = 6

    async def read(self, request):
        if str(request.propertyIdentifier) != "last-restore-time" or change == "unsupported":
            return await old_read(request)
        empty = (255, 255, 255, 255)
        value = TimeStamp(
            dateTime=(
                DateTime(date=empty, time=empty)
                if change == "first" and hour == 6
                else DateTime(date=(125, 1, 6, 1), time=(hour, 0, 0, 0))
            )
        )
        await self.response(
            ReadPropertyACK(
                context=request,
                objectIdentifier=request.objectIdentifier,
                propertyIdentifier=request.propertyIdentifier,
                propertyValue=Any(value),
            )
        )

    old_state = peer.do_ReinitializeDeviceRequest

    async def state(self, request):
        nonlocal hour
        if str(request.reinitializedStateOfDevice) == "end-restore":
            hour += {"advances": 1, "unchanged": 0, "backwards": -1, "unsupported": 0, "first": 1}[
                change
            ]
        await old_state(request)

    peer.do_ReadPropertyRequest = MethodType(read, peer)
    peer.do_ReinitializeDeviceRequest = MethodType(state, peer)
    capture = await native.capture(**target, operation_id="capture-witness")
    capture, _ = native.storage.load(capture["id"])
    plan = await native.preview_snapshot_restore(
        **target,
        **saved_request(capture),
        reinstall_matching_image=True,
        operation_id="review-witness",
    )
    receipt = await native.apply_snapshot_restore(
        **apply_request(plan, reinstall_matching_image_confirmed=True)
    )
    result = receipt["result"]
    assert result["protocol_accepted"]
    assert result["native_sha256"] == plan["compilation"]["compiled_native_sha256"]
    assert result["restore_time_witness"]["advanced"] is (change in ("advances", "first"))
    if change == "unsupported":
        assert result["restore_time_witness"]["before"] == {"state": "unsupported"}
    pending = change in ("unchanged", "backwards")
    assert result["status"] == ("unknown" if pending else "verified")
    assert receipt["pending"] == pending
    if receipt["pending"]:
        hour = 8
        resolved = await native.reconcile(
            operation_id="read-new-witness", receipt_id=receipt["intent"]["id"]
        )
        assert not resolved["pending"] and resolved["latest_readback"]["status"] == "verified"
    assert peer.events.count(("state", "start-restore")) == 1
    assert MoiIdentity(peer.files[3]).summary()["model"] == model
