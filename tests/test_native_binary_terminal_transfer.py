"""Owned UDP binary input publication and native field transfer; no site access."""

import asyncio
import types

import pytest
from bacpypes3.apdu import ReadPropertyACK
from bacpypes3.constructeddata import Any
from bacpypes3.errors import ExecutionError
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import ObjectIdentifier, TagList, Unsigned
from bms_tool.moi_identity import MoiIdentity, seal
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_inputs import raw_property

from .test_native_applications import native_link as native_link
from .test_native_binary_terminal import compiler, edit
from .test_native_default_transfer import NativeRouter
from .test_native_input_transfer import apply, install_input_peer, preview
from .test_native_signal_compiler import slot
from .test_native_terminal_labels import observed_shape


def with_counter(files, value=77):
    dynamic = bytearray(files[12])
    offset = len(dynamic)
    payload = value.to_bytes(4, "big")
    dynamic.extend(payload + bytes([header_crc(payload) ^ 255]))
    return {
        3: files[3],
        11: files[11] + slot((3 << 22) | 101, 242, 15, 2, offset),
        12: bytes(dynamic),
    }, offset


def tick(peer, offset, value):
    data = bytearray(peer.files[12])
    payload = value.to_bytes(4, "big")
    data[offset : offset + 5] = payload + bytes([header_crc(payload) ^ 255])
    peer.files = {**peer.files, 12: bytes(data)}


def test_saved_terminal_override_is_rejected_before_a_field_review():
    files = observed_shape()
    payload = (1).to_bytes(4, "big")
    candidate = {
        3: files[3],
        11: files[11] + slot((3 << 22) | 101, 242, 519, 2, len(files[12])),
        12: files[12] + payload + bytes([header_crc(payload) ^ 255]),
    }
    c = compiler(candidate)
    with pytest.raises(ValueError, match="saved settings would override"):
        c.compile(edit(c))


def binary_peer(link):
    peer, service = install_input_peer(link, initialize=False)
    peer.files = observed_shape(compressed=True)
    original = peer.do_ReadPropertyRequest

    async def read(self, request):
        obj, pid = request.objectIdentifier, int(request.propertyIdentifier)
        if obj[0] != 3:
            return await original(request)
        app = MoiIdentity(
            ParameterApplication(self.files[3], self.files[11], self.files[12]).compile()[0]
        )
        record = next((r for r in app.records if app.reader.scalar(r, 75) == str(obj)), None)
        if record is None:
            raise ExecutionError(errorClass="object", errorCode="unknown-object")
        if pid == 75:
            value = Any(ObjectIdentifier(obj))
        else:
            raw = raw_property(app, record, 2390 if pid == 77 else pid)
            if raw is None:
                raise ExecutionError(errorClass="property", errorCode="unknown-property")
            value = Any(TagList.decode(PDUData(raw[:-1])))
        if self.input_fault == "wrong-binary-slot" and pid == 519:
            value = Any(Unsigned(2))
        await self.response(
            ReadPropertyACK(
                context=request,
                objectIdentifier=obj,
                propertyIdentifier=request.propertyIdentifier,
                propertyValue=value,
            )
        )

    peer.do_ReadPropertyRequest = types.MethodType(read, peer)
    return peer, service


async def test_binary_terminal_transfer_and_reconcile_verify_full_image_and_published_configuration(
    native_link,
):
    peer, service = binary_peer(native_link)
    _, plan = await preview(native_link, edit(compiler(peer.files)), "binary")
    assert (
        plan["operation_profile"].endswith("/3")
        and plan["compilation"]["object_id"] == "binary-input,101"
    )
    result = await service.apply_input(**apply(plan, "binary"))
    assert result["result"]["status"] == "verified", result
    published = result["result"]["published_input"]
    assert (
        published["object_id"] == "binary-input,101"
        and not published["runtime_counter_values_compared"]
    )
    properties = {x["property"]: x["actual"] for x in published["properties"]}
    assert (
        properties[31] == "UI IN3"
        and properties[519] == 3
        and properties[4] == "Closed"
        and properties[931] == 14
    )
    assert compiler(peer.files).source()["inputs"][0]["slot"] == 3
    writes = [e for e in peer.events if e[0] == "write"]
    reconciled = await service.reconcile(
        operation_id="binary-readback", receipt_id=result["intent"]["id"]
    )
    assert reconciled["events"][-1]["detail"]["status"] == "verified", reconciled
    assert [e for e in peer.events if e[0] == "write"] == writes


@pytest.mark.parametrize(
    "confirmation",
    ["physical_wiring_confirmed", "input_change_confirmed", "application_transfer_confirmed"],
)
async def test_binary_transfer_requires_every_confirmation_without_creating_an_intent(
    native_link, confirmation
):
    peer, service = binary_peer(native_link)
    _, plan = await preview(native_link, edit(compiler(peer.files)), "binary-confirm")
    with pytest.raises(ValueError, match="Confirm"):
        await service.apply_input(**(apply(plan, "binary-confirm") | {confirmation: False}))
    assert not service.storage.receipts() and not any(e[0] == "write" for e in peer.events)


@pytest.mark.parametrize("fault", ["profile", "compiler", "body", "options", "option-float"])
async def test_binary_profile_cannot_be_demoted_or_rebound_before_dispatch(native_link, fault):
    peer, service = binary_peer(native_link)
    _, plan = await preview(native_link, edit(compiler(peer.files)), "binary-substitute")
    retained = service.plans[plan["token"]]
    if fault == "profile":
        retained["body"]["operation_profile"] = "native-local-universal-input-transfer/1"
    if fault == "compiler":
        retained["body"]["compilation"]["profile"] = "native-local-universal-input-transfer/2"
    if fault == "body":
        retained["body"]["input_edit"]["slot"] = 2
    if fault == "options":
        retained["options"].edit.slot = 2
    if fault == "option-float":
        retained["options"].edit.slot = 3.0
    if fault in ("profile", "compiler"):
        retained["digest"] = plan["review_sha256"] = seal(retained["body"])
    with pytest.raises(ValueError):
        await service.apply_input(**apply(plan, "binary-substitute"))
    assert not service.storage.receipts() and not any(e[0] == "write" for e in peer.events)


async def test_binary_published_slot_mismatch_refuses_review_before_any_intent(native_link):
    peer, service = binary_peer(native_link)
    peer.input_fault = "wrong-binary-slot"
    with pytest.raises(ValueError, match="Published binary input property 519"):
        await preview(native_link, edit(compiler(peer.files)), "binary-mismatch")
    assert not service.storage.receipts() and not any(e[0] == "write" for e in peer.events)


async def test_binary_lost_ack_retains_unknown_and_readback_never_replays_the_download(native_link):
    peer, service = binary_peer(native_link)
    _, plan = await preview(native_link, edit(compiler(peer.files)), "binary-unknown")
    peer.mode = "drop-end"
    service.files.timeout = 0.1
    result = await service.apply_input(**apply(plan, "binary-unknown"))
    assert result["pending"] and result["result"]["may_have_applied"]
    writes = [e for e in peer.events if e[0] == "write"]
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_input(**apply(plan, "binary-unknown"))
    peer.mode = "normal"
    receipt = await service.reconcile(
        operation_id="binary-unknown-readback", receipt_id=result["intent"]["id"]
    )
    assert receipt["events"][-1]["detail"]["status"] == "verified", receipt
    assert [e for e in peer.events if e[0] == "write"] == writes


async def test_routed_binary_transfer_keeps_router_network_and_station(native_link):
    peer, service = binary_peer(native_link)
    host, port = native_link[-1]["address"].split(":")
    transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
    )
    target = native_link[-1] | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
    try:
        _, plan = await preview(
            (*native_link[:-1], target), edit(compiler(peer.files)), "binary-routed"
        )
        result = await service.apply_input(**apply(plan, "binary-routed"))
        assert result["result"]["status"] == "verified", result
        assert result["intent"]["target"] == {k: target[k] for k in ("address", "router", "dnet")}
        assert (
            any(r["type"] == "AtomicWriteFileRequest" for r in proxy.requests) and not proxy.errors
        )
    finally:
        transport.close()
        await asyncio.sleep(0.02)


async def test_binary_transfer_merges_fresh_counters_and_classifies_post_transfer_ticks(
    native_link,
):
    peer, service = binary_peer(native_link)
    peer.files, offset = with_counter(peer.files)
    _, plan = await preview(native_link, edit(compiler(peer.files)), "binary-counters")
    tick(peer, offset, 999999)
    original = peer.do_ReinitializeDeviceRequest

    async def restore(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) == "end-restore":
            tick(self, offset, 1000001)

    peer.do_ReinitializeDeviceRequest = types.MethodType(restore, peer)
    result = await service.apply_input(**apply(plan, "binary-counters"))
    assert result["result"]["status"] == "verified", result
    assert result["intent"]["compilation"]["captured_counter_values"]["15"] == 999999
    runtime = result["result"]["preservation"]["runtime_counter_changes"]
    assert any(
        r["property"] == 15
        and r["application_value"] == 999999
        and r["current_saved_value"] == 1000001
        for r in runtime
    )
    assert result["result"]["preservation"]["profile"].endswith("/3")


async def test_binary_published_mismatch_after_download_keeps_uncertain_receipt(native_link):
    peer, service = binary_peer(native_link)
    _, plan = await preview(native_link, edit(compiler(peer.files)), "binary-after")
    original = peer.do_ReinitializeDeviceRequest

    async def restore(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) == "end-restore":
            self.input_fault = "wrong-binary-slot"

    peer.do_ReinitializeDeviceRequest = types.MethodType(restore, peer)
    result = await service.apply_input(**apply(plan, "binary-after"))
    assert result["result"]["status"] != "verified" and result["pending"], result
    assert result["intent"]["operation_profile"].endswith("/3")
