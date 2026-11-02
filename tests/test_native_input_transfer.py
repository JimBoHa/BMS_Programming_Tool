"""Native input transfers through an authored BACnet UDP controller."""

import copy
import types

import pytest
from bacpypes3.apdu import ReadPropertyACK
from bacpypes3.constructeddata import Any
from bacpypes3.errors import ExecutionError
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import ObjectIdentifier, TagList, Unsigned
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_inputs import NativeInputCompiler, raw_property

from .test_native_applications import native_link as native_link
from .test_native_inputs import allocation, config, initialized_input_files, source


def install_input_peer(link, *, initialize=True):
    peer, _, _, service, _ = link
    peer.files = source()
    peer.metadata["model-name"] = "M4-CVM03050-0"
    peer.next_input = 3000002
    peer.input_fault = ""
    original = peer.do_ReadPropertyRequest

    async def read(self, request):
        obj, pid = request.objectIdentifier, int(request.propertyIdentifier)
        if obj[0] == 8 and pid == 787:
            value = Any(Unsigned(self.next_input))
        elif obj[0] == 0:
            app = MoiIdentity(
                ParameterApplication(self.files[3], self.files[11], self.files[12]).compile()[0]
            )
            record = next((r for r in app.records if app.reader.scalar(r, 75) == str(obj)), None)
            if record is None:
                if self.input_fault == "silent-absence":
                    return
                if self.input_fault == "unknown-property":
                    raise ExecutionError(errorClass="property", errorCode="unknown-property")
                raise ExecutionError(errorClass="object", errorCode="unknown-object")
            if pid == 75:
                value = Any(ObjectIdentifier(obj))
            elif (
                pid == 118
                and app.reader.scalar(record, 3407) == 2
                and app.reader.scalar(record, 3164) is not None
            ):
                value = Any(Unsigned(3000))
            else:
                raw = raw_property(app, record, 2390 if pid == 77 else pid)
                if raw is None:
                    raise ExecutionError(errorClass="property", errorCode="unknown-property")
                value = Any(TagList.decode(PDUData(raw[:-1])))
            if self.input_fault == "wrong-mode" and pid == 518:
                from bacpypes3.primitivedata import Enumerated

                value = Any(Enumerated(7))
            if self.input_fault == "wrong-interval" and pid == 118:
                value = Any(Unsigned(2999))
        else:
            return await original(request)
        await self.response(
            ReadPropertyACK(
                context=request,
                objectIdentifier=obj,
                propertyIdentifier=request.propertyIdentifier,
                propertyValue=value,
            )
        )

    peer.do_ReadPropertyRequest = types.MethodType(read, peer)
    original_restore = peer.do_ReinitializeDeviceRequest
    originals = copy.deepcopy(peer.files)

    async def restore(self, request):
        await original_restore(request)
        if initialize and str(request.reinitializedStateOfDevice) == "end-restore":
            self.files[11], self.files[12] = originals[11], originals[12]
            if any(
                r["class_id"] == 240
                and int.from_bytes(
                    MoiIdentity(self.files[3]).data[r["offset"] + 6 : r["offset"] + 10], "big"
                )
                & 4194303
                >= 3000000
                for r in MoiIdentity(self.files[3]).records
            ):
                compiler = NativeInputCompiler(self.files)
                instance = int(compiler.source()["inputs"][0]["object_id"].split(",")[1])
                self.files = initialized_input_files(self.files, instance)

    peer.do_ReinitializeDeviceRequest = types.MethodType(restore, peer)
    return peer, service


async def preview(link, edit, suffix="first"):
    _, _, _, service, target = link
    capture = await service.capture(**target, operation_id="capture-input-" + suffix)
    options = {
        **target,
        "capture_id": capture["id"],
        "snapshot_sha256": capture["snapshot_evidence_sha256"],
    }
    support = await service.input_support(**options, operation_id="support-input-" + suffix)
    assert support["next_available_instance"] == 3000002
    plan = await service.preview_input(**options, edit=edit, operation_id="review-input-" + suffix)
    return capture, plan


def apply(plan, suffix="first"):
    return {
        "operation_id": "apply-input-" + suffix,
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        "physical_wiring_confirmed": True,
        "input_change_confirmed": True,
        "application_transfer_confirmed": True,
    }


@pytest.mark.parametrize("initialize", [False, True])
async def test_allocate_mode_round_trip_and_remove_with_durable_origin(native_link, initialize):
    peer, service = install_input_peer(native_link, initialize=initialize)
    original = copy.deepcopy(peer.files)
    _, plan = await preview(native_link, allocation())
    result = await service.apply_input(**apply(plan))
    assert result["result"]["status"] == "verified", result
    assert result["result"]["published_input"]["present"]
    if initialize:
        assert len(result["result"]["preservation"]["initialized_input_parameters"]) == 3
    else:
        assert peer.files[11] == original[11] and peer.files[12] == original[12]
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_input(**apply(plan))
    origin = result["intent"]["id"]
    for mode in ("resistance", "voltage"):
        point = NativeInputCompiler(peer.files).source()["inputs"][0]
        edit = {
            "action": "mode",
            "object_instance": 3000010,
            "slot": 1,
            "configuration_sha256": point["configuration_sha256"],
            "configuration": config(mode),
        }
        _, plan = await preview(native_link, edit, mode)
        result = await service.apply_input(**apply(plan, mode))
        assert result["result"]["status"] == "verified", result
    point = NativeInputCompiler(peer.files).source()["inputs"][0]
    edit = {
        "action": "remove-allocated",
        "object_instance": 3000010,
        "slot": 1,
        "configuration_sha256": point["configuration_sha256"],
        "allocation_receipt": origin,
    }
    _, plan = await preview(native_link, edit, "remove")
    result = await service.apply_input(**apply(plan, "remove"))
    assert result["result"]["status"] == "verified", result
    assert not result["result"]["published_input"]["present"]
    assert NativeInputCompiler(peer.files).app.data == NativeInputCompiler(original).app.data
    assert len([e for e in peer.events if e == ("state", "start-restore")]) == 4


@pytest.mark.parametrize("fault", ["silent-absence", "unknown-property"])
async def test_timeout_or_property_error_cannot_prove_input_absence(native_link, fault):
    peer, service = install_input_peer(native_link)
    peer.input_fault = fault
    with pytest.raises(ValueError, match="presence/absence"):
        await preview(native_link, allocation())
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


async def test_next_available_identifier_is_rechecked_before_restore(native_link):
    peer, service = install_input_peer(native_link)
    _, plan = await preview(native_link, allocation())
    peer.next_input = 3000011
    result = await service.apply_input(**apply(plan))
    assert result["result"]["status"] == "not_sent"
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


@pytest.mark.parametrize("fault", ["wrong-mode", "wrong-interval"])
async def test_published_mode_mismatch_is_not_verified_and_readback_does_not_replay(
    native_link, fault
):
    peer, service = install_input_peer(native_link)
    _, plan = await preview(native_link, allocation())
    peer.input_fault = fault
    result = await service.apply_input(**apply(plan))
    assert result["result"]["status"] != "verified", result
    writes = len([e for e in peer.events if e[0] == "write"])
    peer.input_fault = ""
    readback = await service.reconcile(
        operation_id="input-readback", receipt_id=result["intent"]["id"]
    )
    assert readback["events"][-1]["detail"]["status"] == "verified", readback
    assert writes == len([e for e in peer.events if e[0] == "write"])


async def test_unrelated_receipt_cannot_authorize_removing_an_input(native_link):
    peer, service = install_input_peer(native_link)
    _, plan = await preview(native_link, allocation())
    result = await service.apply_input(**apply(plan))
    point = NativeInputCompiler(peer.files).source()["inputs"][0]
    origin = service.storage.receipt(result["intent"]["id"])
    origin["intent"]["input_edit"]["slot"] = 2
    original_receipt = service.storage.receipt
    service.storage.receipt = lambda _, **kwargs: origin
    with pytest.raises(ValueError, match="exact controller"):
        await preview(
            native_link,
            {
                "action": "remove-allocated",
                "object_instance": 3000010,
                "slot": 1,
                "configuration_sha256": point["configuration_sha256"],
                "allocation_receipt": result["intent"]["id"],
            },
            "wrong-origin",
        )
    service.storage.receipt = original_receipt
