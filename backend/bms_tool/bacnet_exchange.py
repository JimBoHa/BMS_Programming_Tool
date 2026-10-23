"""Owned confirmed-service dispatch for the pinned BACpypes3 application.

Application.request creates an independent dispatch task. Cancelling its returned
future does not stop that task or retire the native ClientSSM. Keep dispatch in
the caller's task and track the exact peer/invoke ID through every exit path.
"""

import asyncio
import math

from bacpypes3.apdu import ConfirmedRequestPDU
from bacpypes3.appservice import COMPLETED, ClientSSM
from bacpypes3.basetypes import Segmentation
from bacpypes3.comm import ApplicationServiceElement


async def confirmed_exchange(
    app, request, *, single_attempt=False, before_send=None, response_timeout=None
):
    # This opt-in budget measures the reply interval, not synchronous durable
    # preparation. Its caller must retain a finite overall operation deadline.
    if response_timeout is not None:
        if not single_attempt or type(response_timeout) not in (int, float):
            raise ValueError(
                "A response timeout requires single_attempt and a finite positive number."
            )
        try:
            response_timeout = float(response_timeout)
        except OverflowError as exc:
            raise ValueError("Response timeout must be finite and positive.") from exc
        if not math.isfinite(response_timeout) or response_timeout <= 0:
            raise ValueError("Response timeout must be finite and positive.")
    target = request.pduDestination
    # Mirror BACpypes3 0.0.110 Application.request registration, with a bounded
    # identifier search and no detached create_task to transmit after return.
    used = {pdu.apduInvokeID for pdu, _ in app._requests.get(target, ())}
    for _ in range(256):
        invoke_id = app.next_invoke_id
        app.next_invoke_id = (invoke_id + 1) % 256
        if invoke_id not in used:
            request.apduInvokeID = invoke_id
            break
    else:
        raise ValueError("BACnet destination has no available transaction identifiers.")
    serial_layer = getattr(app, "mstp_link", None)
    serial_owner = serial_layer.own_confirmed_request(request) if serial_layer is not None else None
    future = asyncio.get_running_loop().create_future()
    owner = asyncio.current_task()
    retiring = False

    def done(result):
        app._request_done(request, result)
        # Interface shutdown may cancel the application future while dispatch
        # is awaiting a native cache lookup, before it reaches `await future`.
        if (
            not retiring
            and result.cancelled()
            and owner is not None
            and not owner.done()
            and not owner.cancelling()
        ):
            owner.cancel()

    app._requests.setdefault(target, []).append((request, future))
    future.add_done_callback(done)
    try:
        async with asyncio.timeout(None) as response_clock:
            if single_attempt:
                # Pin retries/segmentation on this transaction before its first
                # dispatch. Mutating Device/SAP defaults would affect other callers.
                # This mirrors the pinned ASAP's confirmed-request branch only.
                if app.asap.dccEnableDisable != "enable":
                    raise ValueError(
                        "Single-attempt BACnet dispatch requires enabled communication."
                    )
                encoded = request.encode()
                if not isinstance(encoded, ConfirmedRequestPDU):
                    raise ValueError("Single-attempt dispatch requires a confirmed request.")
                transaction = ClientSSM(app.asap, target)
                transaction.numberOfApduRetries = 0
                transaction.segmentationSupported = Segmentation.noSegmentation
                original_send = transaction.request
                sent = False

                async def once(packet):
                    nonlocal sent
                    if isinstance(packet, ConfirmedRequestPDU):
                        if sent:
                            raise ValueError("Single-attempt transaction refused a repeated send.")
                        if response_timeout is not None:
                            # ClientSSM starts this owned response timer before it
                            # calls us. Durable before_send work is pre-dispatch.
                            transaction.stop_timer()
                        if before_send is not None:
                            before_send(packet)
                        if response_timeout is not None:
                            transaction.start_timer(transaction.apduTimeout)
                            response_clock.reschedule(
                                asyncio.get_running_loop().time() + response_timeout
                            )
                        sent = True
                    await original_send(packet)

                transaction.request = once
                app.asap.clientTransactions.append(transaction)
                await transaction.indication(encoded)
            else:
                await ApplicationServiceElement.request(app, request)
            return await future
    finally:
        retiring = True
        if serial_owner is not None:
            serial_layer.retire_confirmed_request(request, serial_owner)
        for transaction in list(app.asap.clientTransactions):
            context = getattr(transaction, "segmentAPDU", None)
            # ClientSSM sets its own invokeID after an asynchronous cache
            # lookup. The encoded request context already has the assigned ID.
            if transaction.pdu_address == target and (
                transaction.invokeID == request.apduInvokeID
                or (context is not None and context.apduInvokeID == request.apduInvokeID)
            ):
                transaction.set_state(COMPLETED)
        future.cancel()
        app._request_done(request, future)
        if future.done() and not future.cancelled():
            future.exception()
