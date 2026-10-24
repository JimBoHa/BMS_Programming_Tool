"""Real UDP responses at the cancelled/completed owned-future cleanup window."""

import asyncio
import json

import pytest
from bacpypes3.apdu import ErrorRejectAbortNack, ReadPropertyRequest
from bacpypes3.pdu import IPv4Address
from bms_tool.bacnet_exchange import _OwnedResponseFuture, confirmed_exchange
from bms_tool.bacnet_read import close_application

from .test_connections import application, free_udp, point


@pytest.mark.parametrize("response", ["ack", "error"])
@pytest.mark.parametrize("window", ["cancelled", "completed"])
async def test_actual_udp_completion_cannot_change_retired_owned_future(
    tmp_path, monkeypatch, response, window
):
    server = application(free_udp(), 4190590)
    client = application(free_udp(), 4190591)
    server.add_object(point())
    other_point = point()
    other_point.objectIdentifier = "analog-value,2"
    other_point.objectName = "Unrelated pending value"
    server.add_object(other_point)
    target = IPv4Address(str(server.nsap.local_adapter.adapterAddr))
    entered, release, delivered = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_read = server.do_ReadPropertyRequest
    reads, invalid_completions = [], []
    original_confirmation = client.confirmation
    owned_request = ReadPropertyRequest(
        objectIdentifier="analog-value,1" if response == "ack" else "analog-value,9999",
        propertyIdentifier="present-value",
        destination=target,
    )
    other_request = ReadPropertyRequest(
        objectIdentifier="analog-value,2", propertyIdentifier="present-value", destination=target
    )
    observed = {}
    task = other = None

    async def held_read(request):
        reads.append(str(request.objectIdentifier))
        if str(request.objectIdentifier) == "analog-value,2":
            entered.set()
            await release.wait()
        return await original_read(request)

    async def cleanup_window(apdu):
        if apdu.apduInvokeID != owned_request.apduInvokeID:
            return await original_confirmation(apdu)
        future = next(
            future for request, future in client._requests[target] if request is owned_request
        )
        observed.update(native_response=type(apdu).__name__, future_type=type(future).__name__)
        try:
            if window == "cancelled":
                # No yield: the real native response arrives before the
                # scheduled done callback/helper finally removes this entry.
                future.cancel()
                observed["cancelled_before_native_completion"] = future.cancelled()
            else:
                # A duplicate completion in the same cleanup window must not
                # replace the first actual native result or native error.
                await original_confirmation(apdu)
                observed["completed_before_duplicate"] = future.done()
            await original_confirmation(apdu)
        except asyncio.InvalidStateError as exc:
            invalid_completions.append(str(exc))
            raise
        finally:
            delivered.set()

    monkeypatch.setattr(server, "do_ReadPropertyRequest", held_read)
    monkeypatch.setattr(client, "confirmation", cleanup_window)
    try:
        other = client.request(other_request)
        assert type(other) is asyncio.Future  # The SDK's unrelated future is unchanged.
        await asyncio.wait_for(entered.wait(), 2)
        task = asyncio.create_task(confirmed_exchange(client, owned_request))
        await asyncio.wait_for(delivered.wait(), 2)
        if window == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await task
        elif response == "error":
            with pytest.raises(ErrorRejectAbortNack):
                await task
        else:
            result = await task
            assert result.objectIdentifier == owned_request.objectIdentifier
        await asyncio.sleep(0)
        assert not other.done()
        assert [(request, future) for request, future in client._requests[target]] == [
            (other_request, other)
        ]
        assert all(
            transaction.invokeID != owned_request.apduInvokeID
            for transaction in client.asap.clientTransactions
        )
        release.set()
        result = await asyncio.wait_for(other, 2)
        assert result.objectIdentifier == other_request.objectIdentifier
        with pytest.raises(asyncio.InvalidStateError):
            other.set_result(result)  # No global SDK/asyncio setter relaxation.
        await asyncio.sleep(0)
        assert not client._requests and not client.asap.clientTransactions
        assert reads.count(str(owned_request.objectIdentifier)) == 1
        proof = {
            **observed,
            "window": window,
            "invalid_completions": invalid_completions,
            "owned_calls": reads.count(str(owned_request.objectIdentifier)),
            "unrelated_sdk_future_preserved": True,
        }
        (tmp_path / "late-response-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
        assert not invalid_completions, proof
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if other is not None and not other.done():
            other.cancel()
        close_application(client)
        close_application(server)
        await asyncio.sleep(0.01)


async def test_cancelled_owned_preparation_does_not_dispatch_after_release(monkeypatch):
    server = application(free_udp(), 4190592)
    client = application(free_udp(), 4190593)
    server.add_object(point())
    entered, release = asyncio.Event(), asyncio.Event()
    reads = []
    original_read = server.do_ReadPropertyRequest
    original_cache = client.asap.device_info_cache.get_device_info

    async def held_cache(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original_cache(*args, **kwargs)

    async def counted(request):
        reads.append(request.apduInvokeID)
        return await original_read(request)

    monkeypatch.setattr(client.asap.device_info_cache, "get_device_info", held_cache)
    monkeypatch.setattr(server, "do_ReadPropertyRequest", counted)
    request = ReadPropertyRequest(
        objectIdentifier="analog-value,1",
        propertyIdentifier="present-value",
        destination=IPv4Address(str(server.nsap.local_adapter.adapterAddr)),
    )
    task = asyncio.create_task(confirmed_exchange(client, request))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await asyncio.sleep(0.03)
        assert reads == []
        assert not client._requests and not client.asap.clientTransactions
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        close_application(client)
        close_application(server)


@pytest.mark.parametrize("first", ["result", "exception", "cancel"])
async def test_first_outcome_survives_opposite_and_duplicate_completions(first):
    loop = asyncio.get_running_loop()
    future = _OwnedResponseFuture(loop=loop)
    assert future.get_loop() is loop
    result, initial_error = object(), ValueError("first native error")
    if first == "result":
        future.set_result(result)
    elif first == "exception":
        future.set_exception(initial_error)
    else:
        future.cancel()
    future.set_exception(RuntimeError("late native error"))
    future.set_result(object())
    future.set_exception(RuntimeError("duplicate native error"))
    if first == "result":
        assert future.result() is result
    elif first == "exception":
        with pytest.raises(ValueError) as caught:
            future.result()
        assert caught.value is initial_error
    else:
        assert future.cancelled()
        with pytest.raises(asyncio.CancelledError):
            future.result()


async def test_actual_udp_interface_close_retires_future_before_late_delivery(monkeypatch):
    server = application(free_udp(), 4190594)
    client = application(free_udp(), 4190595)
    server.add_object(point())
    original = client.confirmation
    delivered = asyncio.Event()

    async def close_at_delivery(apdu):
        close_application(client)
        try:
            return await original(apdu)
        finally:
            delivered.set()

    monkeypatch.setattr(client, "confirmation", close_at_delivery)
    request = ReadPropertyRequest(
        objectIdentifier="analog-value,1",
        propertyIdentifier="present-value",
        destination=IPv4Address(str(server.nsap.local_adapter.adapterAddr)),
    )
    task = asyncio.create_task(confirmed_exchange(client, request))
    try:
        await asyncio.wait_for(delivered.wait(), 2)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not client._requests and not client.asap.clientTransactions
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        close_application(client)
        close_application(server)
