"""Owned confirmed-service dispatch for the pinned BACpypes3 application.

Application.request creates an independent dispatch task. Cancelling its returned
future does not stop that task or retire the native ClientSSM. Keep dispatch in
the caller's task and track the exact peer/invoke ID through every exit path.
"""

import asyncio

from bacpypes3.appservice import COMPLETED
from bacpypes3.comm import ApplicationServiceElement


async def confirmed_exchange(app, request):
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
