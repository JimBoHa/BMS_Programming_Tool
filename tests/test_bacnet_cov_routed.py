"""Actual UDP router and virtual downstream data link; no MS/TP timing claim."""

import asyncio
import socket
import struct
from functools import partial
from uuid import uuid4

import pytest
from bacpypes3.apdu import APDU
from bacpypes3.app import Application
from bacpypes3.ipv4 import IPv4DatagramServer
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import PDU, Address
from bacpypes3.vlan import VirtualNetwork
from bms_tool.bacnet_cov import BacnetCov, CovStart
from bms_tool.bacnet_read import close_application
from bms_tool.connections import Bacnet
from bms_tool.device_details import DeviceDetails, DeviceDetailsRequest
from bms_tool.storage import Store

from .test_bacnet_cov import notification, wait_for
from .test_connections import free_udp, point


async def retire_pending_fixture_endpoints(application):
    tasks = []
    for layer in application.link_layers.values():
        server = getattr(layer, "server", None)
        if not isinstance(server, IPv4DatagramServer):
            continue
        for task in server._transport_tasks:
            if not task.done():
                # Pinned SDK callbacks call task.result() unconditionally.
                # Remove only this server's result callbacks before cancelling
                # its owned pending bind; unrelated observers remain installed.
                for callback, _ in tuple(task._callbacks or ()):
                    if isinstance(callback, partial) and callback.func in (
                        server.set_local_transport_protocol,
                        server.set_broadcast_transport_protocol,
                    ):
                        task.remove_done_callback(callback)
                task.cancel()
            tasks.append(task)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def routed_pair(instance=4190012):
    # VirtualNetwork names live in a process-wide registry, independently of
    # UDP port lifetime. A released ephemeral port is not a fixture identity.
    name = "routed-cov-" + uuid4().hex
    network = VirtualNetwork(name)
    port = free_udp()
    router = Application.from_object_list(
        [
            DeviceObject(objectIdentifier=("device", instance - 1), objectName="COV UDP router"),
            NetworkPortObject(
                f"127.0.0.1:{port}",
                objectIdentifier=("network-port", 1),
                objectName="IP port",
                networkNumber=100,
                networkNumberQuality="configured",
            ),
            NetworkPortObject(
                objectIdentifier=("network-port", 2),
                objectName="Virtual field port",
                macAddress=b"\x02",
                networkType="virtual",
                networkInterfaceName=name,
                networkNumber=2001,
                networkNumberQuality="configured",
                protocolLevel="bacnet-application",
            ),
        ]
    )
    router._routed_cov_network = network
    analog = point()
    analog.covIncrement = 0.1
    field = Application.from_object_list(
        [
            DeviceObject(objectIdentifier=("device", instance), objectName="Virtual VAV"),
            NetworkPortObject(
                objectIdentifier=("network-port", 1),
                objectName="Virtual field link",
                macAddress=b"\x04",
                networkType="virtual",
                networkInterfaceName=name,
                protocolLevel="bacnet-application",
            ),
            analog,
        ]
    )
    config = {
        "router": f"127.0.0.1:{port}",
        "dnet": 2001,
        "address": "2001:4",
        "device": f"device,{instance}",
        "object_id": "analog-value,1",
        "lifetime": 10,
    }
    frames = []
    original = router.nsap.process_npdu

    async def observe(adapter, packet):
        if packet.npduNetMessage is None:
            frames.append(
                (
                    adapter.adapterNet,
                    str(packet.pduSource),
                    str(packet.npduDADR),
                    bytes(packet.pduData),
                )
            )
        await original(adapter, packet)

    router.nsap.process_npdu = observe
    try:
        servers = [
            layer.server
            for layer in router.link_layers.values()
            if isinstance(getattr(layer, "server", None), IPv4DatagramServer)
        ]
        assert len(servers) == 1
        server = servers[0]
        # The SDK schedules endpoint creation. Until its callback confirms the
        # real bind, another free-port probe can select this same UDP address.
        await asyncio.wait_for(server._local_transport_ready.wait(), 1)
        assert server.local_transport.get_extra_info("sockname") == ("127.0.0.1", port)
        assert not server.local_transport.is_closing()
    except BaseException:
        try:
            await retire_pending_fixture_endpoints(router)
        finally:
            close_routed_pair(router, field)
        raise
    return router, field, analog, config, frames


def close_routed_pair(router, field):
    network = router._routed_cov_network
    nodes = [
        layer.node
        for application in (field, router)
        for layer in application.link_layers.values()
        if hasattr(layer, "node") and layer.node.lan is network
    ]
    for detection in list(field._cov_detections.values()):
        for subscription in list(detection.cov_subscriptions):
            field.cancel_subscription(subscription)
    close_application(field)
    close_application(router)
    # Pinned VirtualLinkLayer.close() does not detach its nodes or unregister
    # its network. Retire only this pair's nodes and exact empty mapping.
    for node in nodes:
        if node.lan is network and node in network.nodes:
            network.remove_node(node)
    if not network.nodes and VirtualNetwork._networks.get(network.name) is network:
        del VirtualNetwork._networks[network.name]


@pytest.fixture
async def routed_cov(tmp_path):
    router, field, analog, config, frames = await routed_pair()
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = BacnetCov(client, timeout=0.3)
    try:
        yield router, field, analog, client, service, config, frames
    finally:
        await service.close()
        client.close()
        close_routed_pair(router, field)
        await asyncio.sleep(0.02)


@pytest.mark.parametrize("confirmed", [True, False])
async def test_real_router_start_notifications_renew_cancel_and_route_evidence(
    routed_cov, confirmed
):
    _, field, analog, client, service, config, frames = routed_cov
    started = await service.start(**config, confirmed=confirmed)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["received"] >= 1)
    event = service.detail(started["id"])["events"][0]
    assert event["values"][0]["value"] == 12.5
    assert event["route"] == {
        "router": config["router"],
        "dnet": 2001,
        "next_hop": config["router"],
        "source": "2001:4",
    }
    analog.presentValue = 22.5
    await wait_for(lambda: job["received"] >= 2)
    assert (await service.renew(started["id"]))["active"]
    assert (await service.stop(started["id"]))["remote_outcome"] == "Cancellation acknowledged."
    assert not field._cov_detections and not client.commands
    assert not service._hooks and not service._transport_hooks and not service._route_hooks
    assert any(frame[0] == 100 and frame[2] == "2001:4" for frame in frames)


async def test_confirmed_acks_ignore_poisoned_cache_and_keep_original_invoke_identity(routed_cov):
    _, field, analog, client, service, config, frames = routed_cov
    original = service._receive

    async def poisoned(job, apdu, mode, **metadata):
        await client.app.nsap.update_router_references(None, Address("127.0.0.1:49998"), [2001])
        await original(job, apdu, mode, **metadata)

    service._receive = poisoned
    started = await service.start(**config)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["received"] >= 1 and not field.asap.clientTransactions)
    analog.presentValue = 30
    await wait_for(lambda: job["received"] >= 2 and not field.asap.clientTransactions)
    notifications = [APDU.decode(PDU(frame[3])) for frame in frames if frame[0] == 2001]
    notifications = [p for p in notifications if p.apduType == 0 and p.apduService == 1]
    acknowledgements = [APDU.decode(PDU(frame[3])) for frame in frames if frame[0] == 100]
    acknowledgements = [p for p in acknowledgements if p.apduType == 2 and p.apduService == 1]
    assert [p.apduInvokeID for p in notifications] == [p.apduInvokeID for p in acknowledgements]
    assert (await service.renew(started["id"]))["active"]


async def test_same_dnet_mac_on_another_router_survives_scoped_read_filter_and_ack_redirect(
    routed_cov,
):
    _, field1, _, client, service, config1, _ = routed_cov
    router2, field2, analog2, config2, frames2 = await routed_pair(4190022)
    try:
        first = await service.start(**config1)
        second = await service.start(**config2)
        job2 = service.jobs[second["id"]]
        await wait_for(lambda: job2["received"] >= 1 and not field2.asap.clientTransactions)
        entered, release = asyncio.Event(), asyncio.Event()
        original = field1.do_SubscribeCOVRequest

        async def held(apdu):
            entered.set()
            await release.wait()
            await original(apdu)

        field1.do_SubscribeCOVRequest = held
        renewing = asyncio.create_task(service.renew(first["id"]))
        await entered.wait()
        previous = job2["received"]
        analog2.presentValue = 40
        await wait_for(lambda: job2["received"] > previous and not field2.asap.clientTransactions)
        assert service.detail(second["id"])["events"][-1]["route"]["next_hop"] == config2["router"]
        release.set()
        assert (await renewing)["active"]
        assert any(frame[0] == 100 and frame[3][0] == 0x20 for frame in frames2)
        await service.stop(second["id"])
    finally:
        close_routed_pair(router2, field2)


def routed_frame(job, *, dnet=2001, mac=4, **changes):
    packet = notification(
        job, False, **({"initiatingDeviceIdentifier": ("device", 4190012)} | changes)
    )
    payload = (
        b"\x01\x08"
        + struct.pack(">H", dnet)
        + bytes([1, mac])
        + bytes(packet.encode().encode().pduData)
    )
    return b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload


async def test_wrong_next_hop_dnet_mac_device_object_and_process_never_become_values(routed_cov):
    router, _, _, client, service, config, _ = routed_cov
    started = await service.start(**config, confirmed=False)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["received"] >= 1)
    accepted = job["received"]
    target = Address(client.config["local_address"]).addrTuple
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rogue:
        rogue.sendto(routed_frame(job), target)
    await wait_for(lambda: job["ignored"] >= 1)
    udp = next(
        layer.server.local_transport
        for layer in router.link_layers.values()
        if getattr(layer, "server", None)
    )
    for frame in [
        routed_frame(job, mac=5),
        routed_frame(job, dnet=2002),
        routed_frame(job, initiatingDeviceIdentifier=("device", 4190099)),
        routed_frame(job, monitoredObjectIdentifier=("analog-value", 2)),
    ]:
        udp.sendto(frame, target)
    await wait_for(lambda: job["ignored"] >= 5)
    udp.sendto(
        routed_frame(job, subscriberProcessIdentifier=(job["process_id"] + 1) % 2**32), target
    )
    await asyncio.sleep(0.02)
    assert job["received"] == accepted


async def test_wrong_subscribe_ack_invoke_times_out_and_retires_all_owned_hooks(routed_cov):
    router, _, _, client, service, config, _ = routed_cov
    ip = next(adapter for adapter in router.nsap.adapters.values() if adapter.adapterNet == 100)
    original = ip.process_npdu

    async def wrong_invoke(packet):
        if packet.npduSADR is not None and packet.pduData and packet.pduData[0] == 0x20:
            packet.pduData[1] = (packet.pduData[1] + 1) % 256
        await original(packet)

    ip.process_npdu = wrong_invoke
    with pytest.raises(TimeoutError):
        await service.start(**config)
    assert not service._hooks and not service._route_hooks and not service._transport_hooks
    assert not client.app._requests and not client.app.asap.clientTransactions


async def test_segmented_routed_notification_is_refused_before_native_server_state(routed_cov):
    router, _, _, client, service, config, _ = routed_cov
    started = await service.start(**config)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["received"] >= 1)
    accepted = job["received"]
    packet = notification(job, True, initiatingDeviceIdentifier=("device", 4190012)).encode()
    packet.apduInvokeID = 213
    packet.apduSeg = packet.apduMor = True
    packet.apduSA = False
    packet.apduSeq = 0
    packet.apduWin = 1
    packet.apduMaxSegs = 0
    packet.apduMaxResp = 3
    body = b"\x01\x0c" + struct.pack(">H", 2001) + b"\x01\x04" + bytes(packet.encode().pduData)
    frame = b"\x81\x0a" + struct.pack(">H", len(body) + 4) + body
    udp = next(
        layer.server.local_transport
        for layer in router.link_layers.values()
        if getattr(layer, "server", None)
    )
    udp.sendto(frame, Address(client.config["local_address"]).addrTuple)
    await wait_for(lambda: job["ignored"] > 0)
    assert job["received"] == accepted
    assert not any(t.invokeID == 213 for t in client.app.asap.serverTransactions)


async def test_routed_finite_expiry_and_interface_close_do_not_reconnect(routed_cov):
    _, _, _, client, service, config, _ = routed_cov
    now = [100.0]
    service.clock = lambda: now[0]
    first = await service.start(**config, confirmed=False)
    now[0] += 11
    await wait_for(lambda: not service.jobs[first["id"]]["active"])
    assert service.detail(first["id"])["state"] == "expired"
    second = await service.start(**config, confirmed=False)
    await client.disconnect()
    await wait_for(lambda: not service.jobs[second["id"]]["active"])
    assert service.detail(second["id"])["state"] == "interface_changed"
    assert not service._hooks and not service._route_hooks


async def test_final_expiry_inside_held_details_path_unwraps_retired_hooks_before_reinstall(
    routed_cov,
):
    _, _, _, client, service, config, _ = routed_cov
    now = [100.0]
    service.clock = lambda: now[0]
    nsap = client.app.nsap

    async def unrelated(adapter, packet):
        await original(adapter, packet)

    original = nsap.process_npdu
    nsap.process_npdu = unrelated
    before_source = nsap.__dict__["process_npdu"]
    before_send = nsap.__dict__.get("indication")
    options = DeviceDetailsRequest(
        **{key: config[key] for key in ("address", "device", "router", "dnet")}
    )
    for _ in range(3):
        started = await service.start(**config, confirmed=False)
        async with DeviceDetails(client, None)._path(options):
            now[0] += 11
            await wait_for(lambda identifier=started["id"]: not service.jobs[identifier]["active"])
            assert not service._route_hooks
        assert nsap.__dict__["process_npdu"] is before_source
        assert nsap.__dict__.get("indication") is before_send


async def test_routed_cancel_timeout_is_uncertain_and_shutdown_cancels_remaining_monitor(
    routed_cov,
):
    _, field, _, client, service, config, _ = routed_cov
    first = await service.start(**config)
    original = field.do_SubscribeCOVRequest

    async def ignore(apdu):
        return

    field.do_SubscribeCOVRequest = ignore
    stopped = await service.stop(first["id"])
    assert stopped["state"] == "stopped_uncertain" and not service._route_hooks
    assert not client.app._requests and not client.app.asap.clientTransactions
    field.do_SubscribeCOVRequest = original
    second = await service.start(**config)
    await service.close()
    assert service.detail(second["id"])["remote_outcome"] == "Cancellation acknowledged."


@pytest.mark.parametrize(
    "change",
    [
        {"router": None},
        {"dnet": None},
        {"dnet": 2002},
        {"address": "2001:255"},
        {"address": "2001:0x1234"},
        {"router": "224.1.1.1"},
    ],
)
def test_route_model_rejects_missing_mismatched_broadcast_or_non_mstp_sources(change):
    with pytest.raises(ValueError):
        CovStart(
            **(
                {
                    "router": "127.0.0.1:47808",
                    "dnet": 2001,
                    "address": "2001:4",
                    "device": "device,4190012",
                    "object_id": "analog-value,1",
                }
                | change
            )
        )
