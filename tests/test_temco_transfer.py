"""Real loopback UDP program transfers; no field addresses or point-write stand-in."""

import asyncio
import base64
import json
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from bacpypes3.apdu import (
    ConfirmedPrivateTransferACK,
    ConfirmedPrivateTransferRequest,
    UnconfirmedPrivateTransferRequest,
)
from bacpypes3.app import Application
from bacpypes3.appservice import COMPLETED
from bacpypes3.constructeddata import Any
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.primitivedata import Null, OctetString
from bacpypes3.vlan import VirtualNetwork
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.models import Edge, Node, Program
from bms_tool.storage import Store
from bms_tool.temco import _toolchain, compile_source, export_source
from bms_tool.temco_transfer import TemcoTransfer, metadata, packet, response_body

SOURCE = "10 OUT1 = 42\r\n20 END\r\n"
ORIGINAL_SOURCE = "10 OUT1 = 12\r\n20 END\r\n"
INSTANCE = 4190050
MODEL = "T3-ESP32"
FIRMWARE = "5.4-fixture"
IDENTITY = {"expected_model": MODEL, "expected_firmware": FIRMWARE}


def free_udp():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stream:
        stream.bind(("127.0.0.1", 0))
        return stream.getsockname()[1]


class Controller(Application):
    """Independent firmware layout/handlers; shares no packet codec with adapter."""

    def setup(self, *, confirmed=False):
        self.confirmed = confirmed
        self.images = [bytearray(2000) for _ in range(16)]
        self.images[3][:] = compile_source(ORIGINAL_SOURCE).ljust(2000, b"\0")
        self.descriptors = [bytearray(37) for _ in range(16)]
        self.descriptors[3][:] = (
            b"Original VAV".ljust(21, b"\0")
            + b"VAV3".ljust(9, b"\0")
            + self.images[3][:2]
            + bytes([1, 0, 0xA5, 0x55, 0xAA])
        )
        self.requests = []
        self.writes = []
        self.fail_package = None
        self.fail_once = True
        self.drop_all = False
        self.corrupt_reply = False
        self.before_write = None

    async def do_ConfirmedPrivateTransferRequest(self, request):
        try:
            await self._temco_request(request)
        finally:
            if not self.confirmed:
                # The real firmware dispatches directly without a BACpypes
                # ServerSSM waiting for a standard confirmed-service ACK. Drop
                # that emulator-only state, including deliberately lost replies.
                for transaction in list(self.asap.serverTransactions):
                    if (
                        transaction.pdu_address == request.pduSource
                        and transaction.invokeID == request.apduInvokeID
                    ):
                        transaction.set_state(COMPLETED)

    async def _temco_request(self, request):
        raw = bytes(request.serviceParameters.cast_out(OctetString))
        length, command, start, end, entity = struct.unpack("<HBBBH", raw[:7])
        size, package = entity & 511, entity >> 9
        assert int(request.vendorID) == 260 and int(request.serviceNumber) == 1
        assert start == end and 0 <= start < 16
        assert size == (400 if command in (16, 116) else 37)
        self.requests.append((command, start, package))
        if self.drop_all:
            return
        if command > 100:
            assert length == len(raw) == 7 + size
            if self.before_write:
                self.before_write(command, start, package)
            self.writes.append((command, start, package, raw[7:]))
            if command == 116 and package == self.fail_package:
                if self.fail_once:
                    self.fail_package = None
                return  # lost before write; client must probe and recover
            if command == 107:
                self.descriptors[start][:] = raw[7:]
            else:
                assert command == 116 and package < 5 and self.descriptors[start][32] == 0
                self.images[start][400 * package : 400 * (package + 1)] = raw[7:]
                self.descriptors[start][30:32] = self.images[start][:2]
                self.descriptors[start][35:37] = (
                    (int.from_bytes(self.images[start][:2], "little") // 400 + 1) * 400
                ).to_bytes(2, "little")
            # The pinned ESP32 write branch sets status, leaves data_value zero,
            # and therefore returns an unconfirmed application NULL.
            value = Null(())
        else:
            assert length == 7 and len(raw) == 7
            if command == 7:
                body = bytes(self.descriptors[start])
            else:
                assert command == 16 and package < 5
                body = bytes(self.images[start][400 * package : 400 * (package + 1)])
            header = struct.pack("<HBBBH", size, command, start, end, entity)
            if self.corrupt_reply:
                header = header[:3] + bytes([(start + 1) % 16]) + header[4:]
            value = OctetString(header + body)
        if self.confirmed:
            await self.response(
                ConfirmedPrivateTransferACK(
                    vendorID=260, serviceNumber=1, resultBlock=Any(value), context=request
                )
            )
        else:
            await self.request(
                UnconfirmedPrivateTransferRequest(
                    vendorID=260,
                    serviceNumber=1,
                    serviceParameters=Any(value),
                    destination=request.pduSource,
                )
            )


@pytest.fixture
async def link(tmp_path):
    port = free_udp()
    server = Controller.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", INSTANCE),
                objectName="Temco isolated emulator",
                vendorIdentifier=148,
                modelName=MODEL,
                firmwareRevision=FIRMWARE,
            ),
            NetworkPortObject(
                f"127.0.0.1:{port}", objectIdentifier=("network-port", 1), objectName="IP port"
            ),
        ]
    )
    server.setup()
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    adapter = TemcoTransfer(client, timeout=0.1)
    try:
        yield server, client, adapter, f"127.0.0.1:{port}"
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.02)


def test_real_manufacturer_header_layout_and_bounds():
    assert packet(16, 3, 4).hex() == "07001003039009"
    assert packet(7, 3).hex() == "07000703032500"
    encoded = packet(116, 3, 4, bytes(400))
    assert len(encoded) == 407 and encoded[:7].hex() == "97017403039009"
    for args in ((16, -1), (16, 16), (16, True), (16, 3, 5), (7, 3, 1), (116, 3, 0), (99, 3)):
        with pytest.raises(ValueError):
            packet(*args)
    for length in (400, 407):
        payload = struct.pack("<HBBBH", length, 16, 3, 3, 400 | 4 << 9) + bytes(400)
        assert response_body(payload, 16, 3, 4) == bytes(400)
    with pytest.raises(ValueError, match="mismatch"):
        response_body(payload, 16, 4, 4)


def test_production_bacpypes_wire_encoding_matches_actual_pinned_manufacturer_c():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/temco_private_transfer.json").read_text()
    )
    assert fixture["source_commit"] == "ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b"
    assert fixture["source_sha256"]["BacNetDllforVc/Src/ptransfer.c"]
    assert fixture["cpp_layout"] == {
        "header_bytes": 7,
        "descriptor_bytes": 37,
        "descriptor_code_length_offset": 30,
        "descriptor_run_state_offset": 32,
        "read_code_header_hex": packet(16, 3, 4).hex(),
    }
    frames = fixture["frames"]
    payload = bytes(i & 255 for i in range(400))
    for name, body in (
        ("request0", packet(7, 3)),
        ("request1", packet(16, 3, 4)),
        ("request2", packet(116, 3, 4, payload)),
    ):
        request = ConfirmedPrivateTransferRequest(
            vendorID=260, serviceNumber=1, serviceParameters=Any(OctetString(body))
        )
        request.apduInvokeID = 42
        request.apduMaxResp = 5
        request.apduMaxSegs = 0
        request.apduSeg = request.apduMor = request.apduSA = False
        assert bytes(request.encode().encode().pduData).hex() == frames[name]
    response = struct.pack("<HBBBH", 400, 16, 3, 3, 400 | 4 << 9) + payload
    for name, value in (
        ("unconfirmed_read", OctetString(response)),
        ("unconfirmed_write_null", Null(())),
    ):
        reply = UnconfirmedPrivateTransferRequest(
            vendorID=260, serviceNumber=1, serviceParameters=Any(value)
        )
        assert bytes(reply.encode().encode().pduData).hex() == frames[name]
    ack = ConfirmedPrivateTransferACK(
        vendorID=260, serviceNumber=1, resultBlock=Any(OctetString(response))
    )
    ack.apduInvokeID = 42
    ack.apduSeg = ack.apduMor = False
    assert bytes(ack.encode().encode().pduData).hex() == frames["ack_read"]


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [False, True])
async def test_native_compile_backup_replace_and_restore_over_actual_udp(link, confirmed, tmp_path):
    server, client, adapter, address = link
    server.confirmed = confirmed
    original = bytes(server.images[3])
    plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)
    assert plan["compiled_bytes"] == len(compile_source(SOURCE))
    assert plan["program_budget_bytes"] == len(compile_source(SOURCE))
    assert not server.writes
    saved = adapter.backup(plan["backup_id"])
    assert base64.b64decode(saved["image_base64"]) == original
    assert (
        adapter.directory / ("backup-" + plan["backup_id"] + ".json")
    ).stat().st_mode & 0o777 == 0o600

    def durable_intent(command, slot, package):
        journal = json.loads(adapter.journal.read_text())
        assert journal and next(iter(journal.values()))["backup_id"] == plan["backup_id"]
        assert adapter.backup(plan["backup_id"])["generation"] == plan["generation"]

    server.before_write = durable_intent
    result = await adapter.apply(plan["token"])
    assert result["ok"] and result["readback_verified"] and result["running"]
    assert bytes(server.images[3]) == compile_source(SOURCE).ljust(2000, b"\0")
    received = tmp_path / "received-native.bin"
    received.write_bytes(bytes(server.images[3])[: plan["compiled_bytes"]])
    home, _ = _toolchain()
    executed = subprocess.run(
        [home / "temco-vm", received, "1"], capture_output=True, text=True, check=True
    )
    assert "OUT1\t42.000000" in executed.stdout
    assert server.descriptors[3][32] == 1 and server.descriptors[3][34] == 0xA5
    assert [row[2] for row in server.writes if row[0] == 116] == [0, 1, 2, 3, 4]
    assert not client.app.asap.clientTransactions
    with pytest.raises(ValueError, match="consumed"):
        await adapter.apply(plan["token"])
    server.before_write = None
    restore = await adapter.plan_restore(plan["backup_id"], address, INSTANCE, 3, **IDENTITY)
    assert (await adapter.apply(restore["token"]))["ok"]
    assert bytes(server.images[3]) == original and server.descriptors[3][32] == 1
    assert adapter.status()["uncertain"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["image", "run", "model", "firmware", "vendor", "connection", "expiry"]
)
async def test_pinned_target_generation_and_session_refuse_stale_plans_before_writes(link, change):
    server, client, adapter, address = link
    plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)
    if change == "image":
        server.images[3][1500] = 1
    elif change == "run":
        server.descriptors[3][32] = 0
    elif change in ("model", "firmware", "vendor"):
        setattr(
            server.device_object,
            {"model": "modelName", "firmware": "firmwareRevision", "vendor": "vendorIdentifier"}[
                change
            ],
            5 if change == "vendor" else "changed",
        )
    elif change == "connection":
        client.config = {**client.config, "instance": 4190051}
    else:
        adapter.plans[plan["token"]]["created"] = time.monotonic() - 301
    with pytest.raises(ValueError):
        await adapter.apply(plan["token"])
    assert not server.writes


@pytest.mark.asyncio
async def test_partial_transfer_timeout_restores_original_and_persists_recovery(link):
    server, client, adapter, address = link
    original = bytes(server.images[3])
    plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)
    server.fail_package = 2
    result = await adapter.apply(plan["token"])
    assert result["ok"] is False and "timed out" in result["error"]
    assert result["recovery"]["restored"] and bytes(server.images[3]) == original
    assert server.descriptors[3][32] == 1
    restarted = TemcoTransfer(client)
    assert restarted.status()["uncertain"] == []
    assert restarted.operations[result["operation"]]["state"] == "restored"
    assert not client.app.asap.clientTransactions


@pytest.mark.asyncio
async def test_unrecoverable_network_failure_remains_durable_for_manual_restore(link):
    server, client, adapter, address = link
    plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)

    def disappear(command, slot, package):
        if command == 116:
            server.drop_all = True

    server.before_write = disappear
    result = await adapter.apply(plan["token"])
    assert not result["ok"] and not result["recovery"]["restored"]
    restarted = TemcoTransfer(client)
    assert result["operation"] in restarted.status()["uncertain"]
    assert restarted.backup(plan["backup_id"])["image_sha256"] == plan["before_sha256"]
    assert not client.app.asap.clientTransactions


@pytest.mark.asyncio
async def test_mismatched_unconfirmed_read_cannot_satisfy_request(link):
    server, client, adapter, address = link
    server.corrupt_reply = True
    with pytest.raises(TimeoutError, match="timed out"):
        await adapter.inspect(address, INSTANCE, 3, **IDENTITY)
    assert not server.writes and not client.app.asap.clientTransactions


@pytest.mark.asyncio
async def test_more_than_256_exchanges_reuse_invoke_ids_without_stale_server_transactions(link):
    server, client, adapter, address = link
    for _ in range(24):
        result = await adapter.inspect(address, INSTANCE, 3, **IDENTITY)
        assert result["metadata"]["running"] is True
    assert len(server.requests) == 24 * 12 > 256
    assert not client.app.asap.clientTransactions and not server.asap.serverTransactions
    assert not client.app._requests and not server.writes


@pytest.mark.asyncio
async def test_recovery_rejects_unrelated_external_program_bytes(link):
    server, client, adapter, address = link
    plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)

    def change_while_writing(command, slot, package):
        if command == 116 and package == 1:
            server.images[3][1999] = 0x5A

    server.before_write = change_while_writing
    result = await adapter.apply(plan["token"])
    assert not result["ok"] and not result["recovery"]["restored"]
    assert "Unrelated" in result["recovery"]["error"]
    assert server.images[3][1999] == 0x5A and server.descriptors[3][32] == 0


@pytest.mark.asyncio
async def test_stop_state_rechecked_between_chunks_before_writing_live_slot(link):
    server, client, adapter, address = link
    original = bytes(server.images[3])
    plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)

    def start_after_first_chunk(command, slot, package):
        if command == 116 and package == 0:
            # Trigger after current handler finishes its first chunk.
            asyncio.get_running_loop().call_soon(server.descriptors[3].__setitem__, 32, 1)
            server.before_write = None

    server.before_write = start_after_first_chunk
    result = await adapter.apply(plan["token"])
    assert not result["ok"] and "resumed" in result["error"]
    assert result["recovery"]["restored"] and bytes(server.images[3]) == original
    assert server.descriptors[3][32] == 1


def test_backup_integrity_and_traversal_rejected(tmp_path):
    client = Bacnet(Store(tmp_path))
    adapter = TemcoTransfer(client)
    for value in ("../operations", "0" * 31, "G" * 32):
        with pytest.raises(ValueError, match="identifier"):
            adapter.backup(value)
    with pytest.raises(ValueError, match="state"):
        metadata(bytes(32) + b"\2" + bytes(4))


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["plan", "apply"])
async def test_global_code_resource_budget_checked_before_any_write(link, phase):
    server, client, adapter, address = link
    if phase == "apply":
        plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)
    for slot in range(16):
        if slot != 3:
            server.descriptors[slot][30:32] = (1000).to_bytes(2, "little")
    with pytest.raises(ValueError, match="10,000-byte"):
        if phase == "plan":
            await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)
        else:
            await adapter.apply(plan["token"])
    assert not server.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["target", "descriptor", "image"])
async def test_durable_backup_seal_covers_target_image_and_unknown_descriptor_bytes(link, field):
    server, client, adapter, address = link
    plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)
    path = adapter.directory / ("backup-" + plan["backup_id"] + ".json")
    saved = json.loads(path.read_text())
    if field == "target":
        saved["target"]["slot"] = 4
    else:
        key = field + "_base64"
        raw = base64.b64decode(saved[key])
        saved[key] = base64.b64encode(raw[:-1] + bytes([raw[-1] ^ 1])).decode()
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="integrity"):
        await adapter.apply(plan["token"])
    assert not server.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("permanent", [False, True])
async def test_journal_failure_after_stop_still_restores_and_retains_primary_error(
    link, monkeypatch, permanent
):
    server, client, adapter, address = link
    original = bytes(server.images[3])
    plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)
    record = adapter._record

    def failing_record(operation, state, **detail):
        if state == "stopped" or permanent and state != "intent":
            raise OSError("fixture journal unavailable after stop")
        return record(operation, state, **detail)

    monkeypatch.setattr(adapter, "_record", failing_record)
    result = await adapter.apply(plan["token"])
    assert not result["ok"] and "journal unavailable" in result["error"]
    assert result["recovery"]["restored"] and bytes(server.images[3]) == original
    assert server.descriptors[3][32] == 1
    if permanent:
        assert "journal_error" in result and "journal_error" in result["recovery"]
        restarted = TemcoTransfer(client)
        assert result["operation"] in restarted.status()["uncertain"]


@pytest.mark.asyncio
async def test_cancellation_keeps_lock_through_verified_original_restore(link, monkeypatch):
    server, client, adapter, address = link
    original = bytes(server.images[3])
    plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)
    recover = adapter._recover

    async def delayed_recover(*args):
        await asyncio.sleep(0.1)
        return await recover(*args)

    monkeypatch.setattr(adapter, "_recover", delayed_recover)
    task = asyncio.create_task(adapter.apply(plan["token"]))

    def cancel(command, slot, package):
        if command == 116 and package == 1:
            assert client.lock.locked()
            task.cancel()
            asyncio.get_running_loop().call_later(0.02, task.cancel)
            asyncio.get_running_loop().call_later(0.04, task.cancel)
            server.before_write = None

    server.before_write = cancel
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bytes(server.images[3]) == original and server.descriptors[3][32] == 1
    assert not client.lock.locked() and not adapter.status()["uncertain"]


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_handler", [False, True])
async def test_bacpypes_dispatch_admission_failure_restores_receive_handler(
    link, monkeypatch, existing_handler
):
    server, client, adapter, address = link
    app = client.app
    name = "do_UnconfirmedPrivateTransferRequest"

    async def prior(apdu):
        raise AssertionError("No packet should be admitted during this test")

    if existing_handler:
        setattr(app, name, prior)
    original = getattr(app, name, None)

    async def reject(app, request):
        raise ValueError("fixture synchronous admission failure")

    monkeypatch.setattr("bms_tool.bacnet_exchange.ApplicationServiceElement.request", reject)
    with pytest.raises(ValueError, match="admission failure"):
        await adapter._exchange(address, 7, 3)
    assert getattr(app, name, None) is original
    assert (name in app.__dict__) is existing_handler
    assert not app._requests and not app.asap.clientTransactions and not server.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [7, 107])
async def test_private_transfer_cancel_before_invoke_cannot_dispatch_later(
    link, monkeypatch, command
):
    server, client, adapter, address = link
    adapter.timeout = 1.0
    app = client.app
    name = "do_UnconfirmedPrivateTransferRequest"
    original_handler = getattr(app, name, None)
    entered, release = asyncio.Event(), asyncio.Event()
    lookup = app.device_info_cache.get_device_info

    async def held(address):
        entered.set()
        await release.wait()
        return await lookup(address)

    monkeypatch.setattr(app.device_info_cache, "get_device_info", held)
    body = bytes(server.descriptors[3]) if command == 107 else b""
    task = asyncio.create_task(adapter._exchange(address, command, 3, body=body))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        [transaction] = app.asap.clientTransactions
        assert transaction.invokeID is None
        assert transaction.segmentAPDU.apduInvokeID is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not app._requests and not app.asap.clientTransactions
        assert getattr(app, name, None) is original_handler and name not in app.__dict__
        release.set()
        await asyncio.sleep(0.15)
        assert not server.requests and not server.writes
    finally:
        release.set()
        if not task.done():
            task.cancel()


@pytest.mark.asyncio
async def test_unconfirmed_private_result_joins_preinvoke_dispatch_before_return(link, monkeypatch):
    server, client, adapter, address = link
    adapter.timeout = 1.0
    app = client.app
    entered, release = asyncio.Event(), asyncio.Event()
    lookup = app.device_info_cache.get_device_info

    async def held(address):
        entered.set()
        await release.wait()
        return await lookup(address)

    monkeypatch.setattr(app.device_info_cache, "get_device_info", held)
    task = asyncio.create_task(
        adapter._exchange(address, 107, 3, body=bytes(server.descriptors[3]))
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        [transaction] = app.asap.clientTransactions
        assert transaction.invokeID is None
        # An actual peer UDP NULL result wins while our confirmed dispatch is
        # held before sending. Regardless of that legacy response's origin,
        # _exchange must not let the abandoned request write after returning.
        await server.request(
            UnconfirmedPrivateTransferRequest(
                vendorID=260,
                serviceNumber=1,
                serviceParameters=Any(Null(())),
                destination=client.target_address(client.config["local_address"]),
            )
        )
        assert await asyncio.wait_for(task, 2) == b""
        assert not app._requests and not app.asap.clientTransactions
        assert "do_UnconfirmedPrivateTransferRequest" not in app.__dict__
        release.set()
        await asyncio.sleep(0.15)
        assert not server.requests and not server.writes
    finally:
        release.set()
        if not task.done():
            task.cancel()


def test_cancelled_recovery_child_exits_with_durable_manual_recovery_under_external_watchdog(
    tmp_path,
):
    # A loop spinning on an already-cancelled task cannot run asyncio timeouts.
    # Use a separate process with an OS-side watchdog so this regression can
    # detect the original hang without freezing the full test runner.
    code = r"""
import asyncio, json, sys
from tests.test_temco_transfer import Controller, free_udp, INSTANCE, MODEL, FIRMWARE, IDENTITY, SOURCE
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bms_tool.connections import Bacnet
from bms_tool.storage import Store
from bms_tool.temco_transfer import TemcoTransfer
async def main():
    port=free_udp()
    server=Controller.from_object_list([
        DeviceObject(objectIdentifier=('device',INSTANCE),objectName='Cancelled recovery emulator',vendorIdentifier=148,modelName=MODEL,firmwareRevision=FIRMWARE),
        NetworkPortObject(f'127.0.0.1:{port}',objectIdentifier=('network-port',1),objectName='IP')])
    server.setup()
    client=Bacnet(Store(sys.argv[1]))
    await client.connect(f'127.0.0.1:{free_udp()}')
    adapter=TemcoTransfer(client,timeout=0.05)
    try:
        plan=await adapter.plan_replace(f'127.0.0.1:{port}',INSTANCE,3,SOURCE,**IDENTITY)
        async def cancelled_recovery(*args):
            raise asyncio.CancelledError
        adapter._recover=cancelled_recovery
        server.fail_package=0
        result=await adapter.apply(plan['token'])
        assert not result['ok'] and result['recovery']['manual_recovery_required']
        assert not client.lock.locked()
        restarted=TemcoTransfer(client)
        assert result['operation'] in restarted.status()['uncertain']
        await asyncio.sleep(0)
        print(json.dumps(result))
    finally:
        client.close();server.close()
        await asyncio.sleep(0.01)
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "cancelled-child")],
        capture_output=True,
        text=True,
        timeout=8,
        check=True,
    )
    recovered = json.loads(result.stdout)["recovery"]
    assert not recovered["restored"] and "cancelled" in recovered["error"]


@pytest.mark.asyncio
async def test_transfer_status_uses_failed_serial_link_health(link):
    server, client, adapter, address = link
    client.app.mstp_link = SimpleNamespace(status=lambda: {"connected": False})
    try:
        assert adapter.status()["connected"] is False
        with pytest.raises(ValueError, match="MS/TP link stopped"):
            await adapter.inspect(address, INSTANCE, 3, **IDENTITY)
        assert not server.requests
    finally:
        del client.app.mstp_link


@pytest.mark.asyncio
async def test_native_compile_failure_precedes_any_private_protocol_request(link):
    server, client, adapter, address = link
    with pytest.raises(ValueError):
        await adapter.plan_replace(address, INSTANCE, 3, "this is not BAS", **IDENTITY)
    assert not server.requests and not server.writes


@pytest.mark.asyncio
async def test_physical_variable_and_uncommissioned_calendar_limits_precede_network(link):
    server, client, adapter, address = link
    with pytest.raises(ValueError, match="VAR1..128"):
        await adapter.plan_replace(address, INSTANCE, 3, "10 VAR129 = 42\r\n20 END\r\n", **IDENTITY)
    schedule = Program(
        nodes=[
            Node(id="clock", kind="Schedule"),
            Node(id="out", kind="Output", value_type="boolean"),
        ],
        edges=[Edge(id="e", source="clock", target="out")],
    )
    with pytest.raises(ValueError, match="commissioned calendar"):
        await adapter.plan_replace(address, INSTANCE, 3, export_source(schedule), **IDENTITY)
    wrapped = Program(
        nodes=[
            Node(
                id="instance", kind="Macro", value_type="boolean", params={"definition": "calendar"}
            ),
            Node(id="out", kind="Output", value_type="boolean"),
        ],
        edges=[Edge(id="e", source="instance", target="out")],
        metadata={
            "macros": {
                "version": 1,
                "definitions": [
                    {
                        "id": "calendar",
                        "name": "Calendar macro",
                        "program": schedule.model_dump(mode="json"),
                    }
                ],
            }
        },
    )
    with pytest.raises(ValueError, match="commissioned calendar"):
        await adapter.plan_replace(address, INSTANCE, 3, export_source(wrapped), **IDENTITY)
    assert not server.requests and not server.writes


@pytest.mark.asyncio
async def test_target_too_small_for_manufacturer_private_blocks_is_rejected_before_transfer(link):
    server, client, adapter, address = link
    server.device_object.maxApduLengthAccepted = 206
    with pytest.raises(ValueError, match="at least 480"):
        await adapter.plan_replace(address, INSTANCE, 3, SOURCE, **IDENTITY)
    assert not server.requests and not server.writes


@pytest.mark.asyncio
async def test_restore_requires_exact_original_target_and_resume_false_stays_stopped(link):
    server, client, adapter, address = link
    plan = await adapter.plan_replace(address, INSTANCE, 3, SOURCE, resume=False, **IDENTITY)
    assert (await adapter.apply(plan["token"]))["running"] is False
    assert server.descriptors[3][32] == 0
    with pytest.raises(ValueError, match="different device"):
        await adapter.plan_restore(plan["backup_id"], address, INSTANCE, 4, **IDENTITY)
    assert not any(row[1] != 3 for row in server.writes)
    restore = await adapter.plan_restore(plan["backup_id"], address, INSTANCE, 3, **IDENTITY)
    assert restore["final_running"] is True
    assert (await adapter.apply(restore["token"]))["running"] is True


@pytest.mark.parametrize("resume", [0, 1, "false", None])
async def test_resume_never_coerces_a_nonboolean_into_a_running_program(link, resume):
    server, _, adapter, address = link
    with pytest.raises(ValueError, match="explicit Boolean"):
        await adapter.plan_replace(address, INSTANCE, 3, SOURCE, resume=resume, **IDENTITY)
    assert not server.requests and not server.writes
    assert server.descriptors[3][32] == 1


@pytest.mark.asyncio
async def test_real_routed_program_transfer_through_udp_router_and_virtual_field_link(tmp_path):
    # Real BACnet DNET/DADR forwarding; virtual data link replaces electrical
    # MS/TP token timing. This is not a claim that a USB serial link was tested.
    name = "temco-route-" + str(free_udp())
    VirtualNetwork(name)
    router_port = free_udp()
    router = Application.from_object_list(
        [
            DeviceObject(objectIdentifier=("device", INSTANCE + 1), objectName="Isolated router"),
            NetworkPortObject(
                f"127.0.0.1:{router_port}",
                objectIdentifier=("network-port", 1),
                objectName="IP port",
                networkNumber=100,
                networkNumberQuality="configured",
            ),
            NetworkPortObject(
                objectIdentifier=("network-port", 2),
                objectName="Virtual field port",
                macAddress=b"\2",
                networkType="virtual",
                networkInterfaceName=name,
                networkNumber=2201,
                networkNumberQuality="configured",
                protocolLevel="bacnet-application",
            ),
        ]
    )
    field = Controller.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", INSTANCE),
                objectName="Isolated Temco field emulator",
                vendorIdentifier=148,
                modelName=MODEL,
                firmwareRevision=FIRMWARE,
            ),
            NetworkPortObject(
                objectIdentifier=("network-port", 1),
                objectName="Virtual field link",
                macAddress=b"\4",
                networkType="virtual",
                networkInterfaceName=name,
                protocolLevel="bacnet-application",
            ),
        ]
    )
    field.setup()
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(
            f"127.0.0.1:{free_udp()}", router=f"127.0.0.1:{router_port}", dnet=2201
        )
        adapter = TemcoTransfer(client, timeout=0.2)
        plan = await adapter.plan_replace("2201:4", INSTANCE, 3, SOURCE, **IDENTITY)
        result = await adapter.apply(plan["token"])
        assert result["ok"] and result["target"]["address"] == "2201:4"
        assert bytes(field.images[3]) == compile_source(SOURCE).ljust(2000, b"\0")
        assert any(row[0] == 116 for row in field.writes)
        assert not client.app.asap.clientTransactions
    finally:
        client.close()
        field.close()
        router.close()
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_production_http_program_lifecycle_uses_real_bacpypes_emulator(link, tmp_path):
    server, unused_client, unused_adapter, address = link
    original = bytes(server.images[3])
    app = create_app(tmp_path / "http-state")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            session = (await client.get("/api/session")).json()
            headers = {"X-Studio-Token": session["token"]}
            assert session["field_network_open"] is False
            assert (await client.get("/api/temco/transfer/status")).json()["connected"] is False
            assert not server.requests and not server.writes
            target = {"address": address, "device_instance": INSTANCE, "slot": 3, **IDENTITY}
            disconnected = await client.post(
                "/api/temco/transfer/inspect", json=target, headers=headers
            )
            assert disconnected.status_code == 422 and not server.requests
            connected = await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            assert connected.status_code == 200, connected.text
            inspected = await client.post(
                "/api/temco/transfer/inspect", json=target, headers=headers
            )
            assert inspected.status_code == 200, inspected.text
            response = await client.post(
                "/api/temco/transfer/plan", headers=headers, json={**target, "source": SOURCE}
            )
            assert response.status_code == 200, response.text
            plan = response.json()
            assert not server.writes
            backup = (await client.get("/api/temco/transfer/backups/" + plan["backup_id"])).json()
            assert base64.b64decode(backup["image_base64"]) == original
            applied = await client.post(
                "/api/temco/transfer/apply", headers=headers, json={"token": plan["token"]}
            )
            assert applied.status_code == 200, applied.text
            assert applied.json()["ok"] and applied.json()["readback_verified"]
            assert bytes(server.images[3]) == compile_source(SOURCE).ljust(2000, b"\0")
            restored = await client.post(
                "/api/temco/transfer/restore-plan",
                headers=headers,
                json={**target, "backup_id": plan["backup_id"]},
            )
            assert restored.status_code == 200, restored.text
            applied = await client.post(
                "/api/temco/transfer/apply",
                headers=headers,
                json={"token": restored.json()["token"]},
            )
            assert applied.status_code == 200 and applied.json()["ok"]
            assert bytes(server.images[3]) == original
            assert (await client.get("/api/temco/transfer/status")).json()["uncertain"] == []
            assert len((await client.get("/api/temco/transfer/backups")).json()) == 2
