"""Exact terminal-version pairing, current binding guards and uncertainty without replay."""

import asyncio
import copy
import types

import pytest
from bacpypes3.apdu import ReadPropertyACK
from bacpypes3.constructeddata import Any
from bacpypes3.primitivedata import CharacterString, Unsigned
from bms_tool.moi_identity import MoiIdentity, seal
from bms_tool.native_inputs import NativeInputCompiler

from .test_moi_terminal_output_namespace import with_output
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import NativeRouter
from .test_native_input_transfer import apply, install_input_peer, preview
from .test_native_inputs import allocation, source
from .test_native_terminal_input import terminal_edit


def configured_peer(link):
    peer, service = install_input_peer(link, initialize=False)
    peer.files = source(existing=True)
    return peer, service


async def test_terminal_transfer_preserves_a_slot_bearing_output_record_exactly(native_link):
    peer, service = configured_peer(native_link)
    peer.files = with_output(peer.files)
    before = MoiIdentity(peer.files[3])
    output = next(r for r in before.records if r["class_id"] == 241)
    original = before.data[output["offset"] : output["end_offset"]]
    _, plan = await preview(native_link, terminal_edit(NativeInputCompiler(peer.files)), "outputs")
    assert (
        plan["compilation"]["terminal_compilation"]["profile"] == "tagged-moi-local-terminal-copy/2"
    )
    result = await service.apply_input(**apply(plan, "outputs"))
    assert result["result"]["status"] == "verified", result
    after = MoiIdentity(peer.files[3])
    output = next(r for r in after.records if r["class_id"] == 241)
    assert after.data[output["offset"] : output["end_offset"]] == original


async def test_routed_terminal_apply_verifies_the_original_router_network_and_station(native_link):
    peer, service = configured_peer(native_link)
    host, port = native_link[-1]["address"].split(":")
    transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
    )
    target = native_link[-1] | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
    try:
        _, plan = await preview(
            (*native_link[:-1], target),
            terminal_edit(NativeInputCompiler(peer.files)),
            "direct-routed",
        )
        result = await service.apply_input(**apply(plan, "direct-routed"))
        assert result["result"]["status"] == "verified", result
        assert result["intent"]["target"] == {k: target[k] for k in ("address", "router", "dnet")}
        assert any(r["type"] == "AtomicWriteFileRequest" for r in proxy.requests)
        assert (
            not proxy.errors and not proxy.clients and len(proxy.requests) == len(proxy.responses)
        )
    finally:
        transport.close()
        await asyncio.sleep(0.02)


async def test_lost_restore_ack_keeps_unknown_intent_and_reconciles_without_a_second_download(
    native_link,
):
    peer, service = configured_peer(native_link)
    _, plan = await preview(native_link, terminal_edit(NativeInputCompiler(peer.files)), "lost-ack")
    peer.mode = "drop-end"
    # Fault injection uses a short request timeout; production bounds are unchanged.
    service.files.timeout = 0.1
    result = await service.apply_input(**apply(plan, "lost-ack"))
    assert result["result"]["status"] != "verified", result
    assert result["result"]["may_have_applied"], result
    assert result["pending"]
    writes = [e for e in peer.events if e[0] == "write"]
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_input(**apply(plan, "lost-ack"))
    peer.mode = "normal"
    receipt = await service.reconcile(
        operation_id="terminal-lost-ack-readback", receipt_id=result["intent"]["id"]
    )
    assert receipt["events"][-1]["detail"]["status"] == "verified", receipt
    assert [e for e in peer.events if e[0] == "write"] == writes


async def test_changed_unselected_saved_values_are_not_verified_after_terminal_download(
    native_link,
):
    peer, service = configured_peer(native_link)
    _, plan = await preview(
        native_link, terminal_edit(NativeInputCompiler(peer.files)), "saved-fault"
    )
    peer.mode = "changed-saved-setting"
    result = await service.apply_input(**apply(plan, "saved-fault"))
    assert result["result"]["status"] != "verified", result
    assert result["intent"]["operation_profile"] == "native-local-universal-input-transfer/2"
    assert result["pending"]


@pytest.mark.parametrize("fault", ["profile", "compiler", "body", "options"])
async def test_a_substituted_terminal_review_never_creates_a_transfer_intent(native_link, fault):
    peer, service = configured_peer(native_link)
    _, plan = await preview(
        native_link, terminal_edit(NativeInputCompiler(peer.files)), "substituted"
    )
    retained = service.plans[plan["token"]]
    if fault == "profile":
        retained["body"]["operation_profile"] = "native-local-universal-input-transfer/1"
    elif fault == "compiler":
        retained["body"]["compilation"]["profile"] = "native-local-universal-input-transfer/1"
    elif fault == "body":
        retained["body"]["input_edit"]["slot"] = 2
    else:
        retained["options"].edit.slot = 2
    if fault in ("profile", "compiler"):
        retained["digest"] = plan["review_sha256"] = seal(retained["body"])
    with pytest.raises(ValueError):
        await service.apply_input(**apply(plan, "substituted"))
    assert not service.storage.receipts()
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


async def test_version_two_cannot_promote_an_old_allocation_action(native_link):
    peer, service = install_input_peer(native_link, initialize=False)
    _, plan = await preview(native_link, allocation(), "old-action")
    retained = service.plans[plan["token"]]
    retained["body"]["operation_profile"] = "native-local-universal-input-transfer/2"
    retained["digest"] = plan["review_sha256"] = seal(retained["body"])
    with pytest.raises(ValueError, match="evidence version"):
        await service.apply_input(**apply(plan, "old-action"))
    assert not service.storage.receipts()
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


@pytest.mark.parametrize(
    "confirmation",
    ["physical_wiring_confirmed", "input_change_confirmed", "application_transfer_confirmed"],
)
async def test_every_typed_operator_confirmation_is_required_for_terminal_transfer(
    native_link, confirmation
):
    peer, service = configured_peer(native_link)
    _, plan = await preview(native_link, terminal_edit(NativeInputCompiler(peer.files)), "confirm")
    with pytest.raises(ValueError, match="Confirm"):
        await service.apply_input(**(apply(plan, "confirm") | {confirmation: False}))
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


@pytest.mark.parametrize("fault", ["mode", "source", "capacity"])
async def test_fresh_input_source_published_configuration_and_capacity_are_rechecked(
    native_link, fault
):
    peer, service = configured_peer(native_link)
    _, plan = await preview(native_link, terminal_edit(NativeInputCompiler(peer.files)), "fresh")
    if fault == "mode":
        peer.input_fault = "wrong-mode"
    elif fault == "source":
        peer.files = source(existing=True, model="MS-VMA1630-0")
    else:
        peer.application_capacity = 1
    result = await service.apply_input(**apply(plan, "fresh"))
    assert result["result"]["status"] == "not_sent", result
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("property_id", [31, 519])
async def test_wrong_published_binding_is_unknown_until_explicit_reconciliation(
    native_link, routed, property_id
):
    peer, service = configured_peer(native_link)
    original = peer.do_ReadPropertyRequest
    peer.terminal_fault = True

    async def read(self, request):
        app = MoiIdentity(self.files[3])
        moved = any(r["class_id"] == 240 and app.reader.scalar(r, 519) == 3 for r in app.records)
        if (
            self.terminal_fault
            and moved
            and int(request.objectIdentifier[0]) == 0
            and int(request.propertyIdentifier) == property_id
        ):
            await self.response(
                ReadPropertyACK(
                    context=request,
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=request.propertyIdentifier,
                    propertyValue=Any(
                        CharacterString("UI IN1") if property_id == 31 else Unsigned(1)
                    ),
                )
            )
        else:
            await original(request)

    peer.do_ReadPropertyRequest = types.MethodType(read, peer)
    transport = None
    link = native_link
    if routed:
        host, port = native_link[-1]["address"].split(":")
        transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
        )
        link = (
            *native_link[:-1],
            native_link[-1] | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001},
        )
    try:
        _, plan = await preview(link, terminal_edit(NativeInputCompiler(peer.files)), "binding")
        result = await service.apply_input(**apply(plan, "binding"))
        assert result["result"]["status"] != "verified", result
        assert result["intent"]["operation_profile"] == "native-local-universal-input-transfer/2"
        writes = [e for e in peer.events if e[0] == "write"]
        peer.terminal_fault = False
        receipt = await service.reconcile(
            operation_id="terminal-binding-readback", receipt_id=result["intent"]["id"]
        )
        assert receipt["events"][-1]["detail"]["status"] == "verified", receipt
        assert [e for e in peer.events if e[0] == "write"] == writes
        if routed:
            assert (
                not proxy.errors
                and not proxy.clients
                and len(proxy.requests) == len(proxy.responses)
            )
            assert result["intent"]["target"] == {
                k: link[-1][k] for k in ("address", "router", "dnet")
            }
    finally:
        if transport is not None:
            transport.close()
            await asyncio.sleep(0.02)


@pytest.mark.parametrize("fault", ["profile", "compiler"])
async def test_readback_refuses_a_downlevel_or_wrong_compiler_receipt_without_replay(
    native_link, monkeypatch, fault
):
    peer, service = configured_peer(native_link)
    _, plan = await preview(native_link, terminal_edit(NativeInputCompiler(peer.files)), "receipt")
    result = await service.apply_input(**apply(plan, "receipt"))
    receipt = service.storage.receipt(result["intent"]["id"])
    if fault == "profile":
        receipt["intent"]["operation_profile"] = "native-local-universal-input-transfer/1"
    else:
        receipt["intent"]["compilation"]["profile"] = "native-local-universal-input-transfer/1"
    monkeypatch.setattr(service.storage, "receipt", lambda *a, **kw: copy.deepcopy(receipt))
    events = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        await service.reconcile(
            operation_id="bad-terminal-readback", receipt_id=result["intent"]["id"]
        )
    assert peer.events == events
