"""Reviewed BBMD writes against independently authored raw UDP devices only."""

import asyncio
import socket
import sqlite3
import struct
import threading

import pytest
from bms_tool.bbmd_admin import BbmdAdmin
from bms_tool.bbmd_tables import BbmdTables
from bms_tool.connections import Bacnet
from bms_tool.storage import Store

from .test_bbmd_tables import BDT, FDT, endpoint, entry
from .test_connections import free_udp
from .test_foreign_bacnet import bvlc, wait_until


class RawAdmin(asyncio.DatagramProtocol):
    def __init__(self):
        self.bdt, self.fdt = BDT[4:], FDT[4:]
        self.frames, self.errors, self.handles = [], [], []
        self.code = 0
        self.accept_write = True
        self.drop_result = False
        self.drop_reads = False
        self.before_write = None
        self.after_write = None
        self.before_reply = None

    def connection_made(self, transport):
        self.transport = transport
        self.address = transport.get_extra_info("sockname")

    def datagram_received(self, data, source):
        try:
            assert data[:1] == b"\x81" and int.from_bytes(data[2:4], "big") == len(data)
            function = data[1]
            self.frames.append(data)
            if self.before_reply is not None:
                self.before_reply(function, source)
            if function == 5:
                if data[4:] != b"\0\0":
                    self.transport.sendto(bvlc(0, b"\0\0"), source)
                return
            if function in (2, 6):
                assert len(data) == 4
                if not self.drop_reads:
                    self.transport.sendto(
                        bvlc(3 if function == 2 else 7, self.bdt if function == 2 else self.fdt),
                        source,
                    )
                return
            assert function in (1, 8)
            if self.before_write is not None:
                self.before_write(data)
            if function == 1:
                assert (len(data) - 4) % 10 == 0 and len(data) <= 2564
                if self.accept_write:
                    self.bdt = data[4:]
            else:
                assert len(data) == 10
                if self.accept_write:
                    self.fdt = b"".join(
                        self.fdt[i : i + 10]
                        for i in range(0, len(self.fdt), 10)
                        if self.fdt[i : i + 6] != data[4:]
                    )
            if self.after_write is not None:
                self.after_write(data)
            if not self.drop_result:
                self.transport.sendto(bvlc(0, struct.pack(">H", self.code)), source)
        except Exception as exc:
            self.errors.append(exc)

    def writes(self):
        return [data for data in self.frames if data[1] in (1, 8)]


@pytest.fixture
async def admin_wire(tmp_path):
    loop = asyncio.get_running_loop()
    transport, peer = await loop.create_datagram_endpoint(RawAdmin, local_addr=("127.0.0.1", 0))
    rogue, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    client = Bacnet(Store(tmp_path / "client"))
    await client.connect(f"127.0.0.1:{free_udp()}")
    network = BbmdTables(client)
    admin = BbmdAdmin(client, network, tmp_path)
    try:
        yield peer, rogue, client, network, admin
    finally:
        await admin.close()
        await network.close()
        client.close()
        transport.close()
        rogue.close()
        await asyncio.sleep(0.02)
        assert not peer.errors


def body(preview):
    return {
        "id": preview["id"],
        "apply_token": preview["apply_token"],
        "review_hash": preview["review_hash"],
        "acknowledge_limits": True,
    }


async def desired(admin, peer, **options):
    return await admin.preview(
        endpoint=endpoint(peer.address),
        operation="write-bdt",
        rows=[{"ip": "10.22.33.44", "port": 47809, "mask": "255.0.255.0"}],
        timeout_seconds=0.1,
        **options,
    )


async def finished(admin, identifier):
    await wait_until(lambda: admin.tasks[identifier].done(), 3)
    return admin.detail(identifier)


async def test_exact_reviewed_payload_durable_backup_intent_one_use_and_observed_not_proven(
    admin_wire,
):
    peer, _, client, _, admin = admin_wire
    assert admin.history() == [] and peer.frames == []
    preview = await desired(admin, peer)
    assert not peer.writes() and len(peer.frames) == 1
    assert "apply_token" not in admin.journal.get(preview["id"])
    layer = client.app.nsap.local_adapter.clientPeer
    original = layer.multiplexer.confirmation
    seen = []

    def intent(data):
        receipt = admin.journal.get(preview["id"])
        assert receipt["state"] == "intent-durable" and receipt["dispatch_possible"]
        assert receipt["before"]["response"]["raw_hex"] == BDT.hex()
        assert receipt["preapply"]["response"]["raw_hex"] == BDT.hex()
        assert receipt["write_wire_hex"] == data.hex()
        seen.append(receipt)

    peer.before_write = intent
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    expected = bvlc(1, entry("10.22.33.44", 47809, socket.inet_aton("255.0.255.0")))
    assert peer.writes() == [expected] and seen
    assert [data[1] for data in peer.frames] == [2, 2, 1, 2]
    assert result["outcome"] == "desired-state-observed" and result["write_outcome"] == "unknown"
    assert result["authorship_proven"] is False and result["atomic_cas"] is False
    assert result["write_result"]["result_code"] == 0
    assert result["postapply"]["rows"][0]["mask"] == "255.0.255.0"
    assert result["durable"] and not result["apply_available"]
    with pytest.raises(ValueError, match="absent, used"):
        await admin.apply(**body(preview))
    assert len(peer.writes()) == 1 and layer.multiplexer.confirmation == original
    assert not client.lock.locked() and not client.commands


async def test_no_change_only_reads_and_restore_is_a_new_explicit_review(admin_wire):
    peer, _, _, _, admin = admin_wire
    clone = await admin.preview(endpoint=endpoint(peer.address), operation="write-bdt")
    assert clone["state"] == "no-change" and not clone["apply_available"]
    assert "apply_token" not in clone and peer.writes() == []
    preview = await desired(admin, peer)
    await admin.apply(**body(preview))
    await finished(admin, preview["id"])
    restore = await admin.restore_preview(preview["id"], timeout_seconds=0.1)
    assert restore["id"] != preview["id"] and restore["restored_from"] == preview["id"]
    assert len(peer.writes()) == 1
    peer.before_write = None
    await admin.apply(**body(restore))
    result = await finished(admin, restore["id"])
    assert result["outcome"] == "desired-state-observed" and peer.bdt == BDT[4:]
    assert peer.writes()[-1] == bvlc(1, BDT[4:])


async def test_stale_exact_bdt_baseline_and_tampered_review_never_send_writes(admin_wire):
    peer, _, _, _, admin = admin_wire
    stale = await desired(admin, peer)
    peer.bdt = b""
    await admin.apply(**body(stale))
    result = await finished(admin, stale["id"])
    assert result["outcome"] == "not-dispatched" and "Baseline changed" in result["reason"]
    assert peer.writes() == []
    tampered = await desired(admin, peer)
    saved = admin.journal.get(tampered["id"])
    saved["write_wire_hex"] = bvlc(1, b"").hex()
    admin.journal.save(saved)
    with pytest.raises(ValueError, match="reviewed hash"):
        await admin.apply(**body(tampered))
    assert peer.writes() == []


async def test_fdt_remaining_lease_changes_are_evidence_not_generation_cas(admin_wire):
    peer, _, _, _, admin = admin_wire
    target = "10.4.5.6:47900"
    preview = await admin.preview(
        endpoint=endpoint(peer.address),
        operation="delete-fdt",
        delete_target=target,
        timeout_seconds=0.1,
    )
    peer.fdt = peer.fdt[:-2] + struct.pack(">H", 88)
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert peer.writes() == [bvlc(8, socket.inet_aton("10.4.5.6") + struct.pack(">H", 47900))]
    assert result["target_before"]["remaining_seconds"] == 89
    assert result["preapply"]["rows"][0]["remaining_seconds"] == 88
    assert result["lease_generation_proven"] is False and result["postapply"]["rows"] == []
    assert result["outcome"] == "desired-state-observed" and result["write_outcome"] == "unknown"
    with pytest.raises(ValueError, match="registration recreation"):
        await admin.restore_preview(preview["id"])


@pytest.mark.parametrize("edit", ["membership", "ttl", "absent", "duplicate"])
async def test_fdt_changed_membership_ttl_or_ambiguous_target_refuses_delete(admin_wire, edit):
    peer, _, _, _, admin = admin_wire
    config = dict(
        endpoint=endpoint(peer.address),
        operation="delete-fdt",
        delete_target="10.4.5.6:47900",
        timeout_seconds=0.1,
    )
    if edit in ("absent", "duplicate"):
        peer.fdt = b"" if edit == "absent" else FDT[4:] * 2
        with pytest.raises(ValueError, match="exactly one"):
            await admin.preview(**config)
    else:
        preview = await admin.preview(**config)
        peer.fdt = (
            peer.fdt + entry("10.8.8.8", 47808, struct.pack(">HH", 60, 80))
            if edit == "membership"
            else peer.fdt[:6] + struct.pack(">HH", 61, 80)
        )
        await admin.apply(**body(preview))
        result = await finished(admin, preview["id"])
        assert result["outcome"] == "not-dispatched"
    assert not peer.writes()


@pytest.mark.parametrize("code,accept", [(0, False), (0x10, False), (0x1234, True)])
async def test_generic_success_nack_and_unknown_result_do_not_prove_authorship_or_skip_readback(
    admin_wire, code, accept
):
    peer, _, _, _, admin = admin_wire
    peer.code, peer.accept_write = code, accept
    preview = await desired(admin, peer)
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert len(peer.writes()) == 1 and result["write_outcome"] == "unknown"
    assert result["desired_state_observed"] == accept and not result["authorship_proven"]
    if code == 0x1234:
        assert result["write_result"]["state"] == "timeout" and result["unattributed_results"]
    else:
        assert result["write_result"]["result_code"] == code


async def test_result_timeout_can_observe_state_but_never_retries_or_claims_write_acceptance(
    admin_wire,
):
    peer, _, _, _, admin = admin_wire
    peer.drop_result = True
    preview = await desired(admin, peer)
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert result["write_result"]["state"] == "timeout"
    assert result["desired_state_observed"] is True and result["write_outcome"] == "unknown"
    assert len(peer.writes()) == 1


async def test_rogue_result_and_table_packets_cannot_change_source_or_override_native_nack(
    admin_wire,
):
    peer, rogue, _, _, admin = admin_wire
    peer.code, peer.accept_write = 0x10, False

    def inject(function, destination):
        if function == 1:
            rogue.sendto(bvlc(0, b"\0\0"), destination)
        if function == 2:
            rogue.sendto(bvlc(3, b""), destination)

    peer.before_reply = inject
    preview = await desired(admin, peer)
    assert len(preview["before"]["rows"]) == 3
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert result["write_result"]["result_code"] == 0x10 and not result["desired_state_observed"]
    assert result["ignored_peers"] >= 3 and len(peer.writes()) == 1


async def test_foreign_registration_and_bound_native_owner_are_refused_without_changes(admin_wire):
    from bacpypes3.comm import bind

    from .test_bbmd_tables import NativeManagement

    peer, _, client, _, admin = admin_wire
    native = NativeManagement()
    bind(native, client.app.nsap.local_adapter.clientPeer)
    with pytest.raises(ValueError, match="native BVLC owner"):
        await desired(admin, peer)
    assert not peer.frames
    client.app.nsap.local_adapter.clientPeer.serviceElement = None
    await client.connect(
        client.config["local_address"], bbmd_address=endpoint(peer.address), foreign_ttl=1
    )
    before = client.status()["foreign_device"]
    with pytest.raises(ValueError, match="plain IPv4"):
        await desired(admin, peer)
    after = client.status()["foreign_device"]
    assert after["registered"] and after["ttl"] == before["ttl"]
    assert all(frame[1] == 5 for frame in peer.frames)


@pytest.mark.parametrize("on_layer", [False, True])
async def test_preexisting_management_observer_is_preserved_and_refused(admin_wire, on_layer):
    from bms_tool.scoped_hooks import ScopedAttribute

    from .test_foreign_bacnet import RawPoint

    peer, _, client, _, admin = admin_wire
    layer = client.app.nsap.local_adapter.clientPeer
    target = layer if on_layer else layer.multiplexer
    original = target.confirmation
    observed = []

    async def custom(packet):
        observed.append(bytes(packet.pduData))
        return await original(packet)

    hook = ScopedAttribute(target, "confirmation", custom)
    transport, point = await asyncio.get_running_loop().create_datagram_endpoint(
        RawPoint, local_addr=("127.0.0.1", 0)
    )
    try:
        with pytest.raises(ValueError, match="custom BVLC management observer"):
            await desired(admin, peer)
        assert target.confirmation is custom and not peer.frames
        value = await client.read(endpoint(point.address), "analog-input,1")
        assert value["value"] == 12.5 and observed and not point.errors
        assert target.confirmation is custom and not peer.frames
    finally:
        hook.close()
        transport.close()
    assert target.confirmation == original


async def test_competing_observer_after_dispatch_is_preserved_and_retired_chain_unwraps(
    admin_wire,
):
    from bms_tool.scoped_hooks import ScopedAttribute

    from .test_foreign_bacnet import RawPoint

    peer, _, client, _, admin = admin_wire
    layer = client.app.nsap.local_adapter.clientPeer
    original = layer.multiplexer.confirmation
    outer, observed = [], []

    def install(wire):
        inner = layer.multiplexer.confirmation

        async def competing(packet):
            observed.append(bytes(packet.pduData))
            return await inner(packet)

        outer.append(ScopedAttribute(layer.multiplexer, "confirmation", competing))

    preview = await desired(admin, peer)
    peer.after_write = install
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert result["outcome"] == "unknown" and result["write_outcome"] == "unknown"
    assert "custom BVLC management observer" in result["reason"]
    assert len(peer.writes()) == 1 and len(peer.frames) == 3
    assert layer.multiplexer.confirmation is outer[0].replacement
    counts = dict(result["result_counts"])
    peer.transport.sendto(
        bvlc(0, b"\0\x10"), layer.server.local_transport.get_extra_info("sockname")
    )
    transport, point = await asyncio.get_running_loop().create_datagram_endpoint(
        RawPoint, local_addr=("127.0.0.1", 0)
    )
    try:
        value = await client.read(endpoint(point.address), "analog-input,1")
        assert value["value"] == 12.5 and observed and not point.errors
        assert admin.detail(preview["id"])["result_counts"] == counts
        with pytest.raises(ValueError, match="custom BVLC management observer"):
            await desired(admin, peer)
    finally:
        outer[0].close()
        transport.close()
    assert layer.multiplexer.confirmation == original
    assert "confirmation" not in layer.multiplexer.__dict__
    peer.after_write = None
    assert (await desired(admin, peer))["state"] == "no-change"


async def test_cancel_and_interface_loss_after_dispatch_are_unknown_and_stop_verification(
    admin_wire,
):
    peer, _, client, _, admin = admin_wire
    peer.drop_result = True
    preview = await desired(admin, peer)
    await admin.apply(**body(preview))
    await wait_until(lambda: bool(peer.writes()))
    result = await admin.cancel(preview["id"])
    assert result["outcome"] == "unknown" and result["write_outcome"] == "unknown"
    assert [frame[1] for frame in peer.frames] == [2, 2, 1]
    # A second explicit review is necessary even though the first effect is unknown.
    next_review = await admin.preview(
        endpoint=endpoint(peer.address), operation="write-bdt", rows=[], timeout_seconds=0.2
    )
    await admin.apply(**body(next_review))
    await wait_until(lambda: len(peer.writes()) == 2)
    client.close()
    changed = await finished(admin, next_review["id"])
    assert changed["outcome"] == "unknown" and changed["state"] == "stopped"
    assert [frame[1] for frame in peer.frames][-1] == 1 and not client.lock.locked()


async def test_cancellation_during_durable_intent_joins_disk_and_never_dispatches(
    admin_wire, monkeypatch
):
    peer, _, _, _, admin = admin_wire
    preview = await desired(admin, peer)
    entered, release = threading.Event(), threading.Event()
    original = admin.journal.save

    def hold(row):
        if row["state"] == "intent-durable":
            entered.set()
            assert release.wait(2)
        return original(row)

    monkeypatch.setattr(admin.journal, "save", hold)
    await admin.apply(**body(preview))
    assert await asyncio.to_thread(entered.wait, 1)
    cancelling = asyncio.create_task(admin.cancel(preview["id"]))
    await asyncio.sleep(0.02)
    assert not cancelling.done() and not peer.writes()
    release.set()
    result = await cancelling
    assert result["outcome"] == "not-dispatched" and not peer.writes()
    assert admin.journal.get(preview["id"])["state"] == "cancelled"


@pytest.mark.parametrize("stage", ["apply-queued", "intent-durable"])
async def test_storage_failure_before_dispatch_never_sends_write(admin_wire, monkeypatch, stage):
    peer, _, _, _, admin = admin_wire
    preview = await desired(admin, peer)
    original = admin.journal.save

    def broken(row):
        if row["state"] == stage:
            raise sqlite3.OperationalError("authored pre-dispatch storage failure")
        return original(row)

    monkeypatch.setattr(admin.journal, "save", broken)
    if stage == "apply-queued":
        with pytest.raises(ValueError, match="storage failed"):
            await admin.apply(**body(preview))
        result = admin.detail(preview["id"])
    else:
        await admin.apply(**body(preview))
        result = await finished(admin, preview["id"])
    assert result["outcome"] == "not-dispatched" and not result["active"] and not peer.writes()


async def test_failed_final_storage_restart_keeps_unknown_intent_no_replay_and_live_reader_cannot_interrupt(
    admin_wire, tmp_path, monkeypatch
):
    peer, _, client, network, admin = admin_wire
    preview = await desired(admin, peer)
    original = admin.journal.save

    def broken(row):
        if row["state"] == "complete":
            raise sqlite3.OperationalError("authored final storage failure")
        return original(row)

    monkeypatch.setattr(admin.journal, "save", broken)
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert not result["durable"] and result["storage_error"]
    assert admin.journal.get(preview["id"])["active"]
    reader = BbmdAdmin(client, network, tmp_path)
    try:
        assert reader.journal.get(preview["id"])["active"]  # live owner's receipt untouched
        with pytest.raises(ValueError, match="writer unavailable"):
            await reader.preview(endpoint=endpoint(peer.address), operation="write-bdt")
        await admin.close()
        await reader.close()
        reopened = BbmdAdmin(client, network, tmp_path)
        try:
            saved = reopened.detail(preview["id"])
            assert saved["state"] == "interrupted" and saved["outcome"] == "unknown"
            assert reopened.plans == {} and reopened.tasks == {} and len(peer.writes()) == 1
            with pytest.raises(ValueError, match="earlier process"):
                await reopened.apply(**body(preview))
        finally:
            await reopened.close()
    finally:
        await reader.close()


async def test_expiring_review_and_concurrent_read_write_race_are_not_cas(admin_wire):
    peer, _, _, _, admin = admin_wire
    now = [0.0]
    admin.clock = lambda: now[0]
    expired = await desired(admin, peer)
    now[0] = 61
    with pytest.raises(ValueError, match="invalid or expired"):
        await admin.apply(**body(expired))
    assert not peer.writes()
    preview = await desired(admin, peer)
    peer.before_write = lambda data: setattr(
        peer, "bdt", b""
    )  # unseen concurrent edit between check/send
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert result["desired_state_observed"] and result["atomic_cas"] is False
    assert "race" in result["scope"] and len(peer.writes()) == 1


async def test_renewal_can_recreate_deleted_fdt_entry_without_permanent_removal_promise(admin_wire):
    peer, _, _, _, admin = admin_wire
    preview = await admin.preview(
        endpoint=endpoint(peer.address),
        operation="delete-fdt",
        delete_target="10.4.5.6:47900",
        timeout_seconds=0.1,
    )
    peer.after_write = lambda data: setattr(peer, "fdt", FDT[4:])
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert not result["desired_state_observed"] and result["lease_generation_proven"] is False
    assert len(peer.writes()) == 1


async def test_native_port_zero_delete_and_maximum_bdt_payload_keep_exact_bits(admin_wire):
    peer, _, _, _, admin = admin_wire
    peer.fdt = entry("0.0.0.0", 0, struct.pack(">HH", 1, 1))
    preview = await admin.preview(
        endpoint=endpoint(peer.address),
        operation="delete-fdt",
        delete_target="0.0.0.0:0",
        timeout_seconds=0.1,
    )
    await admin.apply(**body(preview))
    await finished(admin, preview["id"])
    assert peer.writes()[-1] == bytes.fromhex("8108000a000000000000")
    rows = [
        {"ip": f"10.1.{index // 256}.{index % 256}", "port": index, "mask": "255.0.255.0"}
        for index in range(256)
    ]
    proposal = await admin.preview(
        endpoint=endpoint(peer.address), operation="write-bdt", rows=rows, timeout_seconds=0.1
    )
    await admin.apply(**body(proposal))
    result = await finished(admin, proposal["id"])
    assert len(peer.writes()[-1]) == 2564
    assert result["desired_state_observed"] and len(result["postapply"]["rows"]) == 256
    assert result["postapply"]["rows"][0]["port"] == 0


async def test_expiry_during_intent_and_immediate_cancel_never_enter_send(admin_wire, monkeypatch):
    peer, _, _, _, admin = admin_wire
    now = [0.0]
    admin.clock = lambda: now[0]
    preview = await desired(admin, peer)
    original = admin.journal.save

    def expire(row):
        if row["state"] == "intent-durable":
            now[0] = 61.0
        return original(row)

    monkeypatch.setattr(admin.journal, "save", expire)
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert result["outcome"] == "not-dispatched" and not peer.writes()
    monkeypatch.setattr(admin.journal, "save", original)
    new = await desired(admin, peer)
    count = len(peer.frames)
    await admin.apply(**body(new))
    cancelled = await admin.cancel(new["id"])
    assert cancelled["outcome"] == "not-dispatched" and len(peer.frames) == count


async def test_shutdown_cancels_inflight_preview_and_retires_its_receive_hook(
    admin_wire, monkeypatch
):
    peer, _, client, _, admin = admin_wire
    peer.drop_reads = True
    layer = client.app.nsap.local_adapter.clientPeer
    original_handler = layer.multiplexer.confirmation
    operation = asyncio.create_task(desired(admin, peer))
    await wait_until(lambda: bool(peer.frames))
    await admin.close()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert not admin.operations and not client.lock.locked()
    assert layer.multiplexer.confirmation == original_handler and not peer.writes()


async def test_same_peer_stale_success_does_not_hide_later_native_rejection(admin_wire):
    peer, _, _, _, admin = admin_wire
    peer.accept_write = False
    peer.code = 0x10
    peer.before_reply = lambda function, source: (
        peer.transport.sendto(bvlc(0, b"\0\0"), source) if function == 1 else None
    )
    preview = await desired(admin, peer)
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert result["write_result"]["result_code"] == 0
    assert {item["result_code"] for item in result["results_observed"]} == {0, 0x10}
    assert not result["desired_state_observed"] and result["write_outcome"] == "unknown"


async def test_result_capacity_cannot_hide_late_native_nack_or_counters(admin_wire):
    peer, _, _, _, admin = admin_wire
    peer.accept_write, peer.code = False, 0x10

    def stale_successes(function, source):
        if function == 1:
            for _ in range(12):
                peer.transport.sendto(bvlc(0, b"\0\0"), source)

    peer.before_reply = stale_successes
    preview = await desired(admin, peer)
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert result["write_result"]["result_code"] == 0
    assert len(result["results_observed"]) == 8 and result["results_omitted"] == 5
    assert {row["result_code"] for row in result["results_observed"]} == {0}
    assert result["result_counts"]["success"] == 12
    assert result["result_counts"]["write_bdt_nack"] == 1
    assert result["last_native_admin_nack"]["result_code"] == 0x10
    assert result["last_native_admin_nack"]["authorship_proven"] is False
    assert result["native_admin_nack_observed"] and not result["desired_state_observed"]
    assert result["write_outcome"] == "unknown" and len(peer.writes()) == 1


async def test_post_dispatch_readback_loss_retains_unknown_and_failed_read_evidence(admin_wire):
    peer, _, _, _, admin = admin_wire
    peer.after_write = lambda wire: setattr(peer, "drop_reads", True)
    preview = await desired(admin, peer)
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert result["outcome"] == "unknown" and len(peer.writes()) == 1
    assert result["read_failures"][-1]["state"] == "timeout"
    assert "postapply" not in result


async def test_repeated_cancel_cannot_abandon_intent_writer_or_release_network_lock_early(
    admin_wire, monkeypatch
):
    peer, _, client, _, admin = admin_wire
    preview = await desired(admin, peer)
    original = admin.journal.save
    entered, release = threading.Event(), threading.Event()

    def hold(row):
        if row["state"] == "intent-durable":
            entered.set()
            assert release.wait(2)
        return original(row)

    monkeypatch.setattr(admin.journal, "save", hold)
    await admin.apply(**body(preview))
    assert await asyncio.to_thread(entered.wait, 1)
    first = asyncio.create_task(admin.cancel(preview["id"]))
    await asyncio.sleep(0.02)
    second = asyncio.create_task(admin.cancel(preview["id"]))
    await asyncio.sleep(0.02)
    assert not first.done() and not second.done() and client.lock.locked() and not peer.writes()
    release.set()
    results = await asyncio.gather(first, second)
    assert all(result["outcome"] == "not-dispatched" for result in results)
    assert not client.lock.locked() and not peer.writes()
    assert not any(task.get_name() == "bbmd-evidence-writer" for task in asyncio.all_tasks())


@pytest.mark.parametrize(
    "changes",
    [
        {"endpoint": "bbmd.example"},
        {"endpoint": "127.0.0.1:0"},
        {"rows": [{"ip": "10.2.3.4", "port": True, "mask": "255.255.255.0"}]},
        {"rows": [{"ip": "10.2.3.4", "port": 65536, "mask": "255.255.255.0"}]},
        {"rows": [{"ip": "10.2.3.4/24", "port": 47808, "mask": "255.255.255.0"}]},
        {"rows": [{"ip": "10.2.3.4", "port": 47808, "mask": "24"}]},
        {"rows": [{"ip": "10.2.3.4", "port": 47808, "mask": "255.255.255.0"}] * 257},
        {"operation": "write-bdt", "delete_target": "10.2.3.4:47808"},
        {"operation": "delete-fdt", "delete_target": "10.2.3.4:47808"},
        {"operation": "delete-fdt", "delete_target": "10.2.3.4", "rows": None},
        {"operation": "delete-fdt", "delete_target": "10.2.3.4:65536", "rows": None},
        {"timeout_seconds": True},
        {"timeout_seconds": 3.1},
        {"operation": "register-foreign"},
    ],
)
def test_invalid_or_unbounded_admin_requests_never_form_wire_payloads(changes):
    from bms_tool.bbmd_admin import BbmdAdminPreview
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BbmdAdminPreview(
            **({"endpoint": "127.0.0.1:47808", "operation": "write-bdt", "rows": []} | changes)
        )


async def test_whole_apply_deadline_before_dispatch_has_no_retry_and_receipt_integrity_fails_closed(
    admin_wire, monkeypatch
):
    import bms_tool.bbmd_admin as module

    peer, _, _, _, admin = admin_wire
    preview = await desired(admin, peer)
    monkeypatch.setattr(module, "APPLY_SECONDS", 0.001)
    await admin.apply(**body(preview))
    result = await finished(admin, preview["id"])
    assert result["outcome"] == "not-dispatched" and not peer.writes()
    assert "deadline" in result["reason"]
    with admin.journal.connect() as db:
        db.execute("UPDATE receipts SET body=body||' ' WHERE id=?", (preview["id"],))
    with pytest.raises(ValueError, match="integrity"):
        admin.journal.get(preview["id"])


async def test_pending_review_and_durable_capacity_refuse_more_changes_without_losing_first(
    admin_wire, monkeypatch
):
    import bms_tool.bbmd_admin as module
    import bms_tool.bbmd_admin_store as store_module

    peer, _, _, _, admin = admin_wire
    monkeypatch.setattr(module, "MAX_PLANS", 1)
    first = await desired(admin, peer)
    count = len(peer.frames)
    with pytest.raises(ValueError, match="reviews may be pending"):
        await desired(admin, peer)
    assert len(peer.frames) == count and not peer.writes()
    monkeypatch.setattr(module, "MAX_PLANS", 16)
    monkeypatch.setattr(store_module, "MAX_RECORDS", 1)
    with pytest.raises(ValueError, match="receipt capacity"):
        await desired(admin, peer)
    assert admin.journal.ids() == [first["id"]] and not peer.writes()
    await admin.apply(**body(first))
    receipt = await finished(admin, first["id"])
    assert receipt["outcome"] == "desired-state-observed" and receipt["durable"]
    assert len(peer.writes()) == 1
