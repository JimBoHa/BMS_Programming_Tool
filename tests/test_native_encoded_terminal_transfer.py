"""Owned direct/routed UDP analog profile-four transfers and durable readback, never site writes."""

import asyncio
import copy

import pytest
from bms_tool.moi_identity import seal
from bms_tool.native_inputs import NativeInputCompiler

from .test_native_applications import native_link as native_link
from .test_native_default_transfer import NativeRouter
from .test_native_encoded_terminal_input import edit, nonlinear
from .test_native_input_transfer import apply, install_input_peer, preview
from .test_native_terminal_labels import observed_shape


def peer_for(link, missing=False):
    peer, service = install_input_peer(link, initialize=False)
    peer.files = observed_shape(binary=False, compressed=True)
    if missing:
        peer.files = nonlinear(peer.files)
    return peer, service


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("routed", [False, True])
async def test_full_image_published_readback_and_route_stay_bound(native_link, missing, routed):
    peer, service = peer_for(native_link, missing)
    original = copy.deepcopy(peer.files)
    transport = proxy = None
    link = native_link
    if routed:
        host, port = native_link[-1]["address"].split(":")
        transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
        )
        target = native_link[-1] | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
        link = (*native_link[:-1], target)
    try:
        _, plan = await preview(link, edit(NativeInputCompiler(peer.files)), "encoded-analog")
        assert plan["operation_profile"] == "native-local-universal-input-transfer/4"
        result = await service.apply_input(**apply(plan, "encoded-analog"))
        assert result["result"]["status"] == "verified", result
        assert result["intent"]["operation_profile"] == plan["operation_profile"]
        assert result["result"]["preservation"]["profile"] == plan["operation_profile"]
        props = {
            row["property"]: row["actual"]
            for row in result["result"]["published_input"]["properties"]
        }
        assert props[31] == "UI IN3" and props[519] == 3
        assert (
            (1295 not in props and 1296 not in props)
            if missing
            else (1295 in props and 1296 in props)
        )
        assert peer.files[11] == original[11] and peer.files[12] == original[12]
        writes = [e for e in peer.events if e[0] == "write"]
        receipt = await service.reconcile(
            operation_id="encoded-analog-readback", receipt_id=result["intent"]["id"]
        )
        assert receipt["events"][-1]["detail"]["status"] == "verified", receipt
        assert [e for e in peer.events if e[0] == "write"] == writes
        if routed:
            assert result["intent"]["target"] == {
                k: link[-1][k] for k in ("address", "router", "dnet")
            }
            assert (
                any(x["type"] == "AtomicWriteFileRequest" for x in proxy.requests)
                and not proxy.errors
            )
    finally:
        if transport:
            transport.close()
            await asyncio.sleep(0.02)


@pytest.mark.parametrize(
    "fault",
    ["profile", "compiler", "body", "options", "option-float", "config", "presence", "inner"],
)
async def test_changed_or_downgraded_review_never_dispatches(native_link, fault):
    peer, service = peer_for(native_link)
    _, plan = await preview(
        native_link, edit(NativeInputCompiler(peer.files)), "encoded-substitute"
    )
    retained = service.plans[plan["token"]]
    if fault == "profile":
        retained["body"]["operation_profile"] = "native-local-universal-input-transfer/2"
    if fault == "compiler":
        retained["body"]["compilation"]["profile"] = "native-local-universal-input-transfer/2"
    if fault == "body":
        retained["body"]["input_edit"]["slot"] = 2
    if fault == "options":
        retained["options"].edit.slot = 2
    if fault == "option-float":
        retained["options"].edit.slot = 3.0
    if fault == "config":
        retained["body"]["compilation"]["stored_configuration"]["minimum"] = False
    if fault == "presence":
        retained["body"]["compilation"]["configuration_storage"]["present_properties"] = [True]
    if fault == "inner":
        retained["body"]["compilation"]["terminal_compilation"]["profile"] = (
            "tagged-moi-local-terminal-copy/2"
        )
    if fault in ("profile", "compiler", "config", "presence", "inner"):
        retained["digest"] = plan["review_sha256"] = seal(retained["body"])
    with pytest.raises(ValueError):
        await service.apply_input(**apply(plan, "encoded-substitute"))
    assert not service.storage.receipts() and not any(e[0] == "write" for e in peer.events)


@pytest.mark.parametrize(
    "confirmation",
    ["physical_wiring_confirmed", "input_change_confirmed", "application_transfer_confirmed"],
)
async def test_every_confirmation_is_still_required(native_link, confirmation):
    peer, service = peer_for(native_link)
    _, plan = await preview(native_link, edit(NativeInputCompiler(peer.files)), "encoded-confirm")
    with pytest.raises(ValueError):
        await service.apply_input(**(apply(plan, "encoded-confirm") | {confirmation: False}))
    assert not service.storage.receipts() and not any(e[0] == "write" for e in peer.events)


async def test_mismatched_published_configuration_refuses_preflight(native_link):
    peer, service = peer_for(native_link)
    peer.input_fault = "wrong-mode"
    with pytest.raises(ValueError, match="Published input property 518"):
        await preview(native_link, edit(NativeInputCompiler(peer.files)), "encoded-mismatch")
    assert (
        not service.plans
        and not service.storage.receipts()
        and not any(e[0] == "write" for e in peer.events)
    )


async def test_lost_ack_retains_unknown_and_reconciles_without_replay(native_link):
    peer, service = peer_for(native_link, True)
    _, plan = await preview(native_link, edit(NativeInputCompiler(peer.files)), "encoded-unknown")
    peer.mode = "drop-end"
    service.files.timeout = 0.1
    result = await service.apply_input(**apply(plan, "encoded-unknown"))
    assert result["pending"] and result["result"]["may_have_applied"]
    writes = [e for e in peer.events if e[0] == "write"]
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_input(**apply(plan, "encoded-unknown"))
    peer.mode = "normal"
    result = await service.reconcile(
        operation_id="encoded-unknown-readback", receipt_id=result["intent"]["id"]
    )
    assert result["events"][-1]["detail"]["status"] == "verified", result
    assert [e for e in peer.events if e[0] == "write"] == writes
