"""Exercise the interlock workflow with a loopback controller and authored native records."""

import struct

import pytest
from bacpypes3.apdu import ReadPropertyACK
from bacpypes3.basetypes import PriorityArray, PriorityValue
from bacpypes3.constructeddata import Any
from bacpypes3.errors import ExecutionError
from bacpypes3.primitivedata import Boolean, CharacterString, Enumerated, Real, Unsigned
from bms_tool.moi_identity import MoiIdentity
from bms_tool.mstp import header_crc
from bms_tool.native_inline_heat_transfer import InlineApply, InlineReview, preview

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import mutations
from .test_native_inline_heat import OPTIONS, evaluate, fixture
from .test_native_signal_compiler import slot


async def station(link):
    peer, _, _, native, target = link
    target = {**target, "device": "device,321"}
    peer.instance = 321
    peer.metadata.update(
        {"object-name": "Lab", "model-name": "M4-CVM03050-0", "firmware-revision": "10.0.0.2125"}
    )
    saved = struct.pack(">f", 0)
    peer.files = {
        3: fixture(),
        11: slot((2 << 22) | 54, 527, 3113, 4, 0),
        12: saved + bytes([header_crc(saved) ^ 255]),
    }
    original = peer.do_ReadPropertyRequest
    peer.flow = 0.0
    peer.hold = False
    peer.occupied = False
    peer.fault = False

    async def read(request):
        obj = str(request.objectIdentifier)
        pid = int(request.propertyIdentifier)
        applied = any(e == ("state", "end-restore") for e in peer.events)
        if obj == "device,321" and pid == 32527:
            v = CharacterString("8-321")
        elif obj == "device,321" and pid == 787:
            v = Unsigned(15000)
        elif obj == "multi-state-value,1000":
            v = {
                77: CharacterString("8-321/Preloaded App Loader.App Selector"),
                85: Unsigned(1),
                110: CharacterString("Custom Application"),
            }[pid]
        elif obj in ("analog-input,45", "analog-output,51", "analog-value,54"):
            actual = 100.0
            if applied:
                _, value = evaluate(
                    peer.files[3],
                    enabled=True,
                    cfm=peer.flow,
                    pressure_reliable=True,
                    flow_reliable=True,
                    demand=100.0,
                )
                actual = 100.0 if peer.hold else value[0]
            if pid == 87:
                v = PriorityArray(
                    [PriorityValue(null=()) for _ in range(15)] + [PriorityValue(real=actual)]
                )
            else:
                v = {
                    81: Boolean(False),
                    103: Enumerated(int(peer.fault)),
                    990: Unsigned(4),
                    117: Enumerated(98),
                    85: Real(actual if obj == "analog-output,51" else peer.flow),
                }[pid]
        elif int(request.objectIdentifier[1]) >= 15000:
            if not applied:
                if not peer.occupied:
                    raise ExecutionError(errorClass="object", errorCode="unknownObject")
                v = request.objectIdentifier
            else:
                if pid == 103:
                    v = Enumerated(0)
                else:
                    model = MoiIdentity(peer.files[3])
                    (rec,) = [r for r in model.records if model.reader.scalar(r, 75) == obj]
                    v = Real(0.0) if rec["class_id"] == 562 else Boolean(False)
        else:
            return await original(request)
        await peer.response(
            ReadPropertyACK(
                context=request,
                objectIdentifier=request.objectIdentifier,
                propertyIdentifier=request.propertyIdentifier,
                propertyArrayIndex=request.propertyArrayIndex,
                propertyValue=Any(v),
            )
        )

    peer.do_ReadPropertyRequest = read
    cap = await native.capture(**target, operation_id="bench-heat-capture")
    args = InlineReview(
        **target,
        operation_id="bench-heat-review",
        capture_id=cap["id"],
        snapshot_sha256=cap["snapshot_evidence_sha256"],
        edit={**OPTIONS, "first_instance": 16000},
    )
    return peer, native, args


def confirmation(plan):
    return InlineApply(
        operation_id="bench-heat-apply",
        token=plan["token"],
        review_sha256=plan["review_sha256"],
        inline_heat_confirmed=True,
        application_transfer_confirmed=True,
    )


async def test_field_profile_installs_and_proves_cold_valve_without_an_override(native_link):
    peer, native, request = await station(native_link)
    plan = await preview(native, request)
    result = await native.apply_reviewed(confirmation(plan), default_edit=False, inline_edit=True)
    assert result["result"]["status"] == "verified", result["result"]
    assert result["result"]["inline_operating_state"]["valve"] == 0
    assert result["result"]["preservation"]["new_records"] == 29
    assert mutations(peer).count(("state", "start-restore")) == 1
    with pytest.raises(ValueError, match="consumed"):
        await native.apply_reviewed(confirmation(plan), default_edit=False, inline_edit=True)


@pytest.mark.parametrize("fault", ["occupied", "fault", "flow"])
async def test_preflight_rechecks_changed_station_without_restore(native_link, fault):
    peer, native, request = await station(native_link)
    plan = await preview(native, request)
    setattr(peer, fault, 80.0 if fault == "flow" else True)
    result = await native.apply_reviewed(confirmation(plan), default_edit=False, inline_edit=True)
    assert result["result"]["status"] == "not_sent" and not mutations(peer)


async def test_exact_image_and_ack_are_insufficient_when_output_stays_open(native_link):
    peer, native, request = await station(native_link)
    plan = await preview(native, request)
    peer.hold = True
    result = await native.apply_reviewed(confirmation(plan), default_edit=False, inline_edit=True)
    assert result["result"]["status"] == "unknown" and result["pending"], result["result"]
    before = mutations(peer)
    peer.hold = False
    readback = await native.reconcile(
        receipt_id=result["intent"]["id"], operation_id="bench-heat-reconcile"
    )
    assert readback["result"]["status"] == "unknown" and not readback["pending"]
    assert readback["latest_readback"]["status"] == "verified" and mutations(peer) == before
