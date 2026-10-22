"""Actual UDP regressions for the pinned Windows shared-protocol contract.

Alias emulation exercises exactly the library's Windows metadata condition on
other hosts; it is not physical Windows acceptance or an IP-destination capture.
"""

import asyncio
import copy

import pytest
from bacpypes3.npdu import NPDU
from bacpypes3.pdu import PDU, IPv4Address, LocalBroadcast
from bms_tool.ipv4_ingress import close_ipv4_ingress, npdu_ingress, raw_ingress
from bms_tool.point_status import PointStatus

from . import test_bacnet_cov as cov
from . import test_bacnet_cov_routed as routed_cov_tests
from . import test_bbmd_admin as admin_tests
from . import test_bbmd_tables as tables
from . import test_event_reception as events
from . import test_schedule_inventory as schedules
from .test_bacnet_cov import network as network
from .test_bacnet_cov_routed import routed_cov as routed_cov
from .test_bbmd_admin import admin_wire as admin_wire
from .test_foreign_bacnet import bvlc, wait_until
from .test_point_status import make_point_peer
from .test_point_status import options as point_options

schedule_link = schedules.link
event_wire = events.wire
table_wire = tables.wire


def shared_socket(client):
    server = client.app.nsap.local_adapter.clientPeer.server
    # Native Windows uses one transport/protocol for both roles. Retire the
    # separate POSIX broadcast transport before creating that exact condition.
    if (
        server.broadcast_transport is not None
        and server.broadcast_transport is not server.local_transport
    ):
        server.broadcast_transport.close()
    server.broadcast_transport = server.local_transport
    server.broadcast_protocol = server.local_protocol
    server.local_protocol.destination = LocalBroadcast()
    return server


@pytest.mark.parametrize("routed", [False, True])
async def test_shared_socket_readonly_schedule_and_point_identity_remain_exact(
    schedule_link, routed
):
    _, client, service = schedule_link
    server = shared_socket(client)
    schedule = await schedules.make_peer(routed=routed)
    point = await make_point_peer(routed=routed)
    inspector = PointStatus(client, client.store, timeout=0.08, operation_timeout=3, request_gap=0)
    try:
        report = await service.read(**schedules.options(schedule))
        assert report["complete"], report
        assert report["ignored_transport_candidates"] == 0
        evidence = report["objects"][0]["properties"]["object-name"]["transport_evidence"]
        assert evidence["receive_provenance"]["bvlc_function"] == 10
        assert evidence["receive_provenance"]["physical_ip_destination"] is None
        assert "shared IPv4 socket" in evidence["receive_provenance"]["basis"]
        point_report = await inspector.read(**point_options(point, include_commandable=True))
        assert point_report["complete"], point_report
        assert isinstance(server.local_protocol.destination, LocalBroadcast)
        schedules.verify_hash(report)
        schedules.verify_hash(point_report)
    finally:
        await inspector.close()
        schedule.close()
        point.close()


@pytest.mark.parametrize("confirmed", [True, False])
async def test_shared_socket_direct_cov_original_lifecycle(network, confirmed):
    shared_socket(network[2])
    await cov.test_real_udp_start_receive_change_renew_and_cancel_without_point_writes(
        network, confirmed
    )
    row = network[3].status()["jobs"][0]["events"][0]
    assert row["receive_provenance"]["physical_ip_destination"] is None
    assert row["receive_provenance"]["bvlc_function"] == 10


@pytest.mark.parametrize("confirmed", [True, False])
async def test_shared_socket_routed_cov_original_lifecycle(routed_cov, confirmed):
    shared_socket(routed_cov[3])
    await routed_cov_tests.test_real_router_start_notifications_renew_cancel_and_route_evidence(
        routed_cov, confirmed
    )


async def test_shared_socket_events_original_ack_and_poisoned_route(event_wire):
    shared_socket(event_wire[2])
    await events.test_wire_confirmed_unconfirmed_timestamp_native_values_and_pinned_ack(event_wire)
    job = next(iter(event_wire[3].jobs.values()))
    assert job["events"][0]["receive_provenance"]["bvlc_function"] == 10


async def test_shared_socket_table_inspection_and_admin_original_wire_contract(
    table_wire, admin_wire
):
    shared_socket(table_wire[2])
    shared_socket(admin_wire[2])
    await tables.test_exact_wire_tables_preserve_masks_and_leases_pacing_and_immutable_evidence(
        table_wire
    )
    await admin_tests.test_exact_reviewed_payload_durable_backup_intent_one_use_and_observed_not_proven(
        admin_wire
    )


async def test_shared_socket_cannot_accept_broadcast_forwarded_or_wrong_peer_notifications(
    event_wire,
):
    peer, rogue, client, service, options = event_wire
    shared_socket(client)
    started = await service.start(**options)
    payload = events.npdu(events.notification(), source=(2001, 4) if peer.routed else None)
    for frame in (bvlc(11, payload), bvlc(4, b"\x7f\0\0\x01\xba\xc0" + payload)):
        peer.transport.sendto(frame, peer.client)
    rogue.sendto(bvlc(10, payload), peer.client)
    await asyncio.sleep(0.05)
    assert not peer.acks and service.detail(started["id"])["received"] == 0
    peer.send()
    await wait_until(lambda: service.detail(started["id"])["received"] == 1 and len(peer.acks) == 1)


async def test_shared_context_exact_frame_concurrency_and_owned_hook_retirement(table_wire):
    peer, rogue, client, _ = table_wire
    server = shared_socket(client)
    layer = client.app.nsap.local_adapter.clientPeer
    original = layer.multiplexer.confirmation
    seen, waiting, release = [], asyncio.Event(), asyncio.Event()
    local = server.local_transport.get_extra_info("sockname")
    first = bvlc(10, b"\x01\0\x10\x08")
    second = bvlc(10, b"\x01\0\x10\x09")

    async def observe(packet):
        before = raw_ingress(layer, packet)
        assert before is not None
        if bytes(packet.pduData) == first:
            waiting.set()
            await release.wait()
        after = raw_ingress(layer, packet)
        assert before == after
        forged = copy.copy(packet)
        forged.pduData = bytearray(bvlc(10, b"\x01\0\x10\x0a"))
        assert raw_ingress(layer, forged) is None
        forged = copy.copy(packet)
        forged.pduSource = IPv4Address(("127.0.0.1", 1))
        assert raw_ingress(layer, forged) is None
        native = NPDU.decode(PDU(bytes(packet.pduData)[4:]))
        native.pduSource, native.pduDestination = packet.pduSource, packet.pduDestination
        assert npdu_ingress(layer, native) is not None
        native.pduExpectingReply = not native.pduExpectingReply
        assert npdu_ingress(layer, native) is None
        seen.append(before["next_hop"])

    layer.multiplexer.confirmation = observe
    try:
        peer.transport.sendto(first, local)
        await asyncio.wait_for(waiting.wait(), 1)
        rogue.sendto(second, local)
        await wait_until(lambda: len(seen) == 1)
        release.set()
        await wait_until(lambda: len(seen) == 2)
        assert len(set(seen)) == 2
        # A fabricated packet outside a real callback cannot claim provenance.
        fake = PDU(first, source=IPv4Address(peer.address), destination=LocalBroadcast())
        assert raw_ingress(layer, fake) is None
        saved = server.local_protocol.datagram_received
        server.local_protocol.datagram_received = lambda data, address: saved(data, address)
        rejected = []

        async def reject(packet):
            rejected.append(raw_ingress(layer, packet))

        layer.multiplexer.confirmation = reject
        peer.transport.sendto(first, local)
        await wait_until(lambda: len(rejected) == 1)
        assert rejected == [None]
        server.local_protocol.datagram_received = saved
        close_ipv4_ingress(client.app)
        peer.transport.sendto(first, local)
        await wait_until(lambda: len(rejected) == 2)
        assert rejected == [None, None]
    finally:
        release.set()
        layer.multiplexer.confirmation = original


async def test_shared_socket_malformed_management_length_stays_malformed_evidence(table_wire):
    peer, _, client, service = table_wire
    shared_socket(client)
    peer.responses[2] = b"\x81\x03\x00\x04x"
    result = await tables.complete(service, service.start(endpoint=tables.endpoint(peer.address)))
    row = result["tables"]["bdt"]
    assert row["state"] == "malformed" and not row["rows"]
    assert not row["response"]["receive_provenance"]["bvlc_length_valid"]
    assert row["response"]["raw_hex"] == peer.responses[2].hex()
    assert result["tables"]["fdt"]["state"] == "ok"


async def test_inflight_context_rejects_socket_replacement_and_retirement(table_wire):
    peer, _, client, _ = table_wire
    server = shared_socket(client)
    layer = client.app.nsap.local_adapter.clientPeer
    original = layer.multiplexer.confirmation
    entered, release, done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    wire = bvlc(10, b"\x01\0\x10\x08")

    class Replacement:
        def is_closing(self):
            return False

        def get_extra_info(self, name):
            return transport.get_extra_info(name)

    transport = server.local_transport

    async def observe(packet):
        assert raw_ingress(layer, packet) is not None
        server.local_transport = Replacement()
        try:
            assert raw_ingress(layer, packet) is None
        finally:
            server.local_transport = transport
        assert raw_ingress(layer, packet) is not None
        entered.set()
        await release.wait()
        assert raw_ingress(layer, packet) is None
        assert packet.pduUserData is None
        done.set()

    layer.multiplexer.confirmation = observe
    try:
        peer.transport.sendto(wire, transport.get_extra_info("sockname"))
        await asyncio.wait_for(entered.wait(), 1)
        close_ipv4_ingress(client.app)
        release.set()
        await asyncio.wait_for(done.wait(), 1)
        assert "datagram_received" not in server.local_protocol.__dict__
    finally:
        release.set()
        layer.multiplexer.confirmation = original
