"""Actual loopback UDP subscriptions and bounded ownership/lifecycle checks."""

import asyncio
import socket
import struct

import pytest
from bacpypes3.apdu import (
    ConfirmedCOVNotificationRequest,
    ErrorRejectAbortNack,
    SimpleAckPDU,
    UnconfirmedCOVNotificationRequest,
)
from bacpypes3.basetypes import PriorityValue, PropertyValue
from bacpypes3.comm import ApplicationServiceElement
from bacpypes3.constructeddata import Any
from bacpypes3.errors import ExecutionError
from bacpypes3.pdu import PDU, Address
from bacpypes3.primitivedata import Boolean, OctetString, Real
from bms_tool.bacnet_cov import BacnetCov, CovStart
from bms_tool.bacnet_exchange import confirmed_exchange
from bms_tool.bacnet_read import close_application
from bms_tool.connections import Bacnet
from bms_tool.storage import Store
from pydantic import ValidationError

from .test_connections import application, free_udp, point


async def wait_for(predicate):
    async def until():
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(until(), 2)


@pytest.fixture
async def network(tmp_path):
    server_port = free_udp()
    server = application(server_port, 4190010)
    analog = point()
    analog.covIncrement = 0.1
    server.add_object(analog)
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = BacnetCov(client, timeout=0.2)
    config = {
        "address": f"127.0.0.1:{server_port}",
        "device": "device,4190010",
        "object_id": "analog-value,1",
        "lifetime": 10,
    }
    try:
        yield server, analog, client, service, config
    finally:
        await service.close()
        for detection in list(server._cov_detections.values()):
            for subscription in list(detection.cov_subscriptions):
                server.cancel_subscription(subscription)
        client.close()
        close_application(server)
        await asyncio.sleep(0.02)


@pytest.mark.parametrize("confirmed", [True, False])
async def test_real_udp_start_receive_change_renew_and_cancel_without_point_writes(
    network, confirmed
):
    server, analog, client, service, config = network
    started = await service.start(**config, confirmed=confirmed)
    owned = service.jobs[started["id"]]
    await wait_for(lambda: owned["received"] >= 1)
    first = service.status()["jobs"][0]["events"][0]
    assert first["confirmed"] == confirmed and first["device"] == "device,4190010"
    assert first["values"][0]["value"] == 12.5
    assert first["values"][0]["encoded_value"]["type"] == "bacnet-opaque"
    analog.presentValue = 17.5
    await wait_for(lambda: owned["received"] >= 2)
    renewed = await service.renew(started["id"])
    assert renewed["active"] and renewed["remote_outcome"] == "Explicit renewal acknowledged."
    stopped = await service.stop(started["id"])
    assert (
        stopped["state"] == "stopped" and stopped["remote_outcome"] == "Cancellation acknowledged."
    )
    assert not server._cov_detections and not service._hooks and not service._transport_hooks
    assert not client.app._requests and not client.app.asap.clientTransactions
    assert analog.presentValue == 17.5 and not client.commands
    assert not client.app._cov_contexts


def notification(job, confirmed=False, **changes):
    values = [PropertyValue(propertyIdentifier="present-value", value=Any(Real(42.5)), priority=8)]
    fields = {
        "subscriberProcessIdentifier": job["process_id"],
        "initiatingDeviceIdentifier": ("device", 4190010),
        "monitoredObjectIdentifier": ("analog-value", 1),
        "timeRemaining": 5,
        "listOfValues": values,
        "destination": Address(job["connector_config"]["local_address"]),
    }
    fields.update(changes)
    cls = ConfirmedCOVNotificationRequest if confirmed else UnconfirmedCOVNotificationRequest
    return cls(**fields)


async def send(server, apdu, confirmed=False):
    if confirmed:
        return await asyncio.wait_for(confirmed_exchange(server, apdu), 0.5)
    await ApplicationServiceElement.request(server, apdu)


@pytest.mark.parametrize("confirmed", [True, False])
async def test_identity_source_object_process_and_mode_filtering_over_udp(network, confirmed):
    server, _, client, service, config = network
    started = await service.start(**config, confirmed=confirmed)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["received"] >= 1)
    initial = job["received"]
    for changes in [
        {"initiatingDeviceIdentifier": ("device", 4190011)},
        {"monitoredObjectIdentifier": ("analog-value", 2)},
    ]:
        if confirmed:
            with pytest.raises(ErrorRejectAbortNack):
                await send(server, notification(job, confirmed, **changes), True)
        else:
            await send(server, notification(job, False, **changes))
    await wait_for(lambda: job["ignored"] >= 2)
    attacker = application(free_udp(), 4190020)
    await asyncio.sleep(0.05)
    try:
        if confirmed:
            with pytest.raises(ErrorRejectAbortNack):
                await send(attacker, notification(job, True), True)
        else:
            await send(attacker, notification(job, False))
        await wait_for(lambda: job["ignored"] >= 3)
        if not confirmed:
            with pytest.raises(ErrorRejectAbortNack):
                await send(server, notification(job, True), True)
        else:
            await send(server, notification(job, False))
        await wait_for(lambda: job["ignored"] >= 4)
        await send(
            server, notification(job, False, subscriberProcessIdentifier=job["process_id"] + 1)
        )
        await asyncio.sleep(0.02)
        assert job["received"] == initial
        assert not client.commands
    finally:
        close_application(attacker)


async def test_array_index_priority_quality_nonfinite_unknown_and_malformed_evidence(network):
    server, _, _, service, config = network
    started = await service.start(**config, confirmed=False)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["received"] >= 1)
    values = [
        PropertyValue(
            propertyIdentifier="priority-array",
            propertyArrayIndex=2,
            value=Any(PriorityValue(real=5.5)),
            priority=8,
        ),
        PropertyValue(propertyIdentifier="present-value", value=Any(Real(float("nan")))),
        PropertyValue(
            propertyIdentifier=512,
            propertyArrayIndex=4,
            value=Any(OctetString(b"\x01\x00")),
            priority=16,
        ),
        PropertyValue(propertyIdentifier="present-value", value=Any(Boolean(True))),
    ]
    sequence = job["received"]
    await send(server, notification(job, listOfValues=values))
    await wait_for(lambda: job["received"] > sequence)
    rows = list(job["events"])[-1]["values"]
    assert rows[0]["array_index"] == 2 and rows[0]["priority"] == 8
    assert rows[0]["value"] == {"type": "real", "value": 5.5}
    assert rows[1]["value"] == {"type": "nonfinite-number", "value": "NaN"}
    assert rows[2]["decode_status"] == "opaque" and rows[2]["priority"] == 16
    assert rows[2]["array_index"] == 4 and rows[2]["value"]["type"] == "bacnet-opaque"
    assert rows[3]["decode_status"] == "decode_error"
    assert "Not independently assessed" in list(job["events"])[-1]["quality"]


async def test_device_object_verification_rejection_and_timeout_retire_owned_transactions(network):
    server, _, client, service, config = network
    with pytest.raises(ValueError):
        await service.start(**(config | {"device": "device,4190020"}))
    assert service.status()["jobs"] == []
    with pytest.raises(ValueError):
        await service.start(**(config | {"object_id": "analog-value,2"}))
    assert service.status()["jobs"] == []

    async def reject(apdu):
        raise ExecutionError(errorClass="services", errorCode="covSubscriptionFailed")

    server.do_SubscribeCOVRequest = reject
    with pytest.raises(ValueError, match="COV service rejected"):
        await service.start(**config)
    assert service.status()["jobs"][-1]["state"] == "failed" and not service._hooks

    async def ignore(apdu):
        return

    server.do_SubscribeCOVRequest = ignore
    with pytest.raises(TimeoutError):
        await service.start(**config)
    assert (
        not service._hooks and not client.app._requests and not client.app.asap.clientTransactions
    )


async def test_bounded_retention_finite_expiry_no_automatic_renewal_and_interface_change(network):
    server, _, client, service, config = network
    now = [100.0]
    service.clock = lambda: now[0]
    started = await service.start(**config, confirmed=False)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["received"] >= 1)
    # Exercise the same bounded receive path; wire behavior is tested above.
    packet = notification(job)
    packet.pduSource = Address(config["address"])
    for _ in range(150):
        await service._receive(job, packet, False)
    assert len(job["events"]) == 100 and job["dropped"] == job["received"] - 100
    assert len(service.status()["jobs"][0]["events"]) == 3
    assert len(service.detail(started["id"])["events"]) == 100
    now[0] += 11
    await wait_for(lambda: not job["active"])
    assert job["state"] == "expired" and not service._hooks
    with pytest.raises(ValueError, match="inactive or expired"):
        await service.renew(started["id"])
    resumed = await service.start(**config, confirmed=False)
    next_job = service.jobs[resumed["id"]]
    client.config = client.config | {"instance": 4190999}
    await wait_for(lambda: not next_job["active"])
    assert next_job["state"] == "interface_changed" and not service._hooks
    assert not service.status()["auto_renew"] and not service.status()["auto_reconnect"]


async def test_cancel_timeout_stops_local_capture_and_disconnect_shutdown_restore_handlers(network):
    server, _, client, service, config = network
    started = await service.start(**config)

    async def ignore(apdu):
        return

    server.do_SubscribeCOVRequest = ignore
    stopped = await service.stop(started["id"])
    assert stopped["state"] == "stopped_uncertain" and not stopped["active"]
    assert (
        not service._hooks and not client.app._requests and not client.app.asap.clientTransactions
    )
    # Restore normal server behavior for another monitor and close the interface.
    del server.do_SubscribeCOVRequest
    started = await service.start(**config)
    old_app = client.app
    await client.disconnect()
    await wait_for(lambda: not service.jobs[started["id"]]["active"])
    assert not service._hooks and not old_app._requests and not old_app.asap.clientTransactions
    await service.close()
    assert all(not job["active"] for job in service.jobs.values())


async def test_pending_owned_dispatch_is_cancelled_without_late_network_send(network, monkeypatch):
    server, _, client, service, config = network
    original = service._exchange
    entered = asyncio.Event()
    release = asyncio.Event()
    cache = client.app.device_info_cache
    real_lookup = cache.get_device_info

    async def held_lookup(address):
        entered.set()
        await release.wait()
        return await real_lookup(address)

    async def held_exchange(job, cancel=False):
        monkeypatch.setattr(cache, "get_device_info", held_lookup)
        return await original(job, cancel)

    monkeypatch.setattr(service, "_exchange", held_exchange)
    pending = asyncio.create_task(service.start(**config))
    await asyncio.wait_for(entered.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    release.set()
    await asyncio.sleep(0.05)
    assert not server._cov_detections and not service._hooks
    assert not client.app._requests and not client.app.asap.clientTransactions
    assert service.status()["jobs"][0]["state"] == "failed"


async def test_active_and_history_capacity_and_shutdown_acknowledges_cancellation(network):
    server, _, client, service, config = network
    identifiers = [(await service.start(**config, confirmed=False))["id"] for _ in range(8)]
    with pytest.raises(ValueError, match="eight active"):
        await service.start(**config)
    for identifier in identifiers:
        await service.stop(identifier)
    for _ in range(26):
        started = await service.start(**config, confirmed=False)
        await service.stop(started["id"])
    assert len(service.status()["jobs"]) == 32
    assert service.status()["retired_jobs_evicted"] == 2
    started = await service.start(**config)
    await service.close()
    assert service.detail(started["id"])["remote_outcome"] == "Cancellation acknowledged."
    assert not service._hooks and not client.app._requests and not server._cov_detections


async def test_interface_replacement_stops_old_capture_without_opening_new_monitor(network):
    _, _, client, service, config = network
    started = await service.start(**config, confirmed=False)
    previous = client.app
    await client.connect(f"127.0.0.1:{free_udp()}")
    await wait_for(lambda: not service.jobs[started["id"]]["active"])
    assert service.detail(started["id"])["state"] == "interface_changed"
    assert not service._hooks and not previous._requests and not client.app._cov_contexts


async def test_routed_mstp_and_bbmd_configurations_refused_before_traffic(network):
    _, _, client, service, config = network
    original = client.config
    for changes in (
        {"router": "127.0.0.1:47808", "dnet": 2001},
        {"bbmd_address": "127.0.0.1:47808"},
        {"transport": "mstp"},
    ):
        client.config = original | changes
        with pytest.raises(ValueError, match="direct BACnet/IPv4"):
            await service.start(**config)
    client.config = original
    assert service.status()["jobs"] == []


async def test_explicit_renewal_ack_crossing_old_expiry_keeps_owned_monitor_active(network):
    server, _, _, service, config = network
    now = [100.0]
    service.clock = lambda: now[0]
    started = await service.start(**config)
    original = server.do_SubscribeCOVRequest
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(apdu):
        entered.set()
        await release.wait()
        await original(apdu)

    server.do_SubscribeCOVRequest = delayed
    renewal = asyncio.create_task(service.renew(started["id"]))
    await entered.wait()
    now[0] += 11
    await asyncio.sleep(0.02)
    release.set()
    renewed = await renewal
    assert renewed["active"] and renewed["lease_seconds_remaining"] == 10
    assert service.jobs[started["id"]]["task"] is not None


async def test_shutdown_waits_for_inflight_start_then_cancels_its_subscription(network):
    server, _, _, service, config = network
    original = server.do_ReadPropertyRequest
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(apdu):
        entered.set()
        await release.wait()
        await original(apdu)

    server.do_ReadPropertyRequest = delayed
    start = asyncio.create_task(service.start(**config))
    await entered.wait()
    closing = asyncio.create_task(service.close())
    await asyncio.sleep(0.02)
    release.set()
    identifier = (await start)["id"]
    await closing
    assert not service.detail(identifier)["active"]
    assert not server._cov_detections and not service._hooks


async def test_wrong_service_ack_and_rejected_renewal_have_explicit_failed_outcomes(network):
    server, _, client, service, config = network
    started = await service.start(**config)

    async def wrong_ack(apdu):
        response = SimpleAckPDU(context=apdu)
        response.apduService = 12
        await server.response(response)

    server.do_SubscribeCOVRequest = wrong_ack
    with pytest.raises(ValueError, match="source/service mismatch"):
        await service.renew(started["id"])
    assert not service.detail(started["id"])["active"] and not service._hooks
    assert not client.app._requests and not client.app.asap.clientTransactions
    del server.do_SubscribeCOVRequest
    started = await service.start(**config)

    async def reject(apdu):
        raise ExecutionError(errorClass="services", errorCode="covSubscriptionFailed")

    server.do_SubscribeCOVRequest = reject
    with pytest.raises(ValueError, match="COV service rejected"):
        await service.renew(started["id"])
    assert service.detail(started["id"])["state"] == "failed" and not service._hooks


async def test_notification_resource_limits_reject_without_growing_evidence(network):
    _, _, _, service, config = network
    started = await service.start(**config, confirmed=False)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["received"] >= 1)
    count = job["received"]
    for values in (
        [],
        [PropertyValue(propertyIdentifier="present-value", value=Any(Real(1)))] * 33,
        [PropertyValue(propertyIdentifier=512, value=Any(OctetString(b"x" * 8192)))] * 16,
    ):
        packet = notification(job, listOfValues=values)
        packet.pduSource = Address(config["address"])
        await service._receive(job, packet, False)
    assert job["ignored"] == 3 and job["received"] == count
    assert "16 KiB" in job["last_ignored"]


async def test_forwarded_bvlc_cannot_impersonate_direct_notification_source(network):
    _, _, client, service, config = network
    started = await service.start(**config, confirmed=False)
    job = service.jobs[started["id"]]
    await wait_for(lambda: job["received"] >= 1)
    accepted = job["received"]
    packet = notification(job)
    payload = b"\x01\x00" + bytes(packet.encode().encode().pduData)
    original = socket.inet_aton("127.0.0.1") + struct.pack(
        ">H", Address(config["address"]).addrTuple[1]
    )
    frame = b"\x81\x04" + struct.pack(">H", 4 + len(original) + len(payload)) + original + payload
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rogue:
        rogue.sendto(frame, Address(client.config["local_address"]).addrTuple)
    await wait_for(lambda: job["ignored"] > 0)
    assert job["received"] == accepted


async def test_other_notification_handlers_and_transport_user_data_are_preserved(network):
    _, _, client, service, config = network
    previous_transport = client.app.asap.__dict__.get("confirmation")
    seen = []

    async def previous_handler(apdu):
        seen.append(apdu.pduUserData)

    client.app.do_UnconfirmedCOVNotificationRequest = previous_handler
    started = await service.start(**config, confirmed=False)
    job = service.jobs[started["id"]]
    packet = notification(job, subscriberProcessIdentifier=(job["process_id"] + 1) % 2**32)
    user_data = {"trace": "existing owner"}
    incoming = PDU(
        bytes(packet.encode().encode().pduData),
        source=Address(config["address"]),
        destination=Address(client.config["local_address"]),
        user_data=user_data,
    )
    await client.app.asap.confirmation(incoming)
    assert seen == [user_data]
    await service.stop(started["id"])
    assert client.app.do_UnconfirmedCOVNotificationRequest is previous_handler
    assert client.app.asap.__dict__.get("confirmation") is previous_transport
    assert not service._hooks and not service._transport_hooks


@pytest.mark.parametrize(
    "changes",
    [
        {"lifetime": 0},
        {"lifetime": True},
        {"confirmed": 1},
        {"device": "analog-value,1"},
        {"object_id": "analog-value,4194303"},
        {"address": "200:1"},
        {"address": "255.255.255.255"},
    ],
)
def test_unbounded_leases_and_unsupported_addresses_are_rejected(changes):
    with pytest.raises((ValueError, ValidationError)):
        CovStart(
            **(
                {"address": "127.0.0.1:47808", "device": "device,1", "object_id": "analog-value,1"}
                | changes
            )
        )
