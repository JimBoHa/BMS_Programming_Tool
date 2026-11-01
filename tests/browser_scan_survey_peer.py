"""Mutable, loopback-only fixture using the existing controller-workspace peer.

Random identity and values prevent a saved inventory from supplying this test.
All incoming services are recorded before dispatch. Only read-only requests run.
"""

import asyncio
import json
import secrets
import signal
import sys

from bacpypes3.apdu import (
    IAmRequest,
    ReadPropertyMultipleRequest,
    ReadPropertyRequest,
    WhoIsRequest,
)
from bacpypes3.primitivedata import ObjectIdentifier

from .test_connections import free_udp
from .test_controller_workspace import workspace_device


async def main():
    port, client_port = free_udp(), free_udp()
    while port == client_port:
        client_port = free_udp()
    instance = 3000000 + secrets.randbelow(100000)
    nonce = secrets.token_hex(4)
    first, second = 61.25 + secrets.randbelow(16) / 8, 72.5 + secrets.randbelow(16) / 8
    app = workspace_device(
        port, model="Unlisted scan fixture " + nonce, modules=0, instance=instance
    )
    app.device_object.objectName = "Browser survey " + nonce
    point = app.get_object_id(ObjectIdentifier("analog-input,1"))
    point.objectName = "Changing sensor " + nonce
    point.deviceType = "UI IN1"
    point.presentValue = first
    requests, errors = [], []
    release_name = asyncio.Event()
    hold_name, name_entered = False, False
    original = app.indication

    async def observe(apdu):
        nonlocal hold_name, name_entered
        requests.append(
            {
                "service": type(apdu).__name__,
                "object": str(getattr(apdu, "objectIdentifier", "")),
                "property": str(getattr(apdu, "propertyIdentifier", "")),
            }
        )
        if not isinstance(
            apdu, (WhoIsRequest, IAmRequest, ReadPropertyRequest, ReadPropertyMultipleRequest)
        ):
            errors.append(type(apdu).__name__)
            raise AssertionError("Unexpected service at the read-only loopback peer.")
        if (
            hold_name
            and isinstance(apdu, ReadPropertyRequest)
            and str(apdu.objectIdentifier) == f"device,{instance}"
            and str(apdu.propertyIdentifier) == "object-name"
        ):
            hold_name, name_entered = False, True
            await release_name.wait()
        await original(apdu)

    app.indication = observe
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)
    reader = asyncio.StreamReader()
    transport, _ = await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
    )

    def emit(data):
        print(json.dumps(data), flush=True)

    emit(
        {
            "event": "ready",
            "port": port,
            "client_port": client_port,
            "instance": instance,
            "name": str(app.device_object.objectName),
            "sensor": str(point.objectName),
            "first": first,
            "second": second,
        }
    )
    try:
        while line := await reader.readline():
            command = json.loads(line)
            if command.get("operation") == "stop":
                break
            if "value" in command:
                point.presentValue = float(command["value"])
            if command.get("operation") == "hold-name":
                hold_name, name_entered = True, False
                release_name.clear()
            if command.get("operation") == "release-name":
                release_name.set()
            emit(
                {
                    "event": "state",
                    "requests": requests,
                    "errors": errors,
                    "name_entered": name_entered,
                    "value": float(point.presentValue),
                }
            )
    except asyncio.CancelledError:
        pass
    finally:
        release_name.set()
        app.close()
        transport.close()
        await asyncio.sleep(0.05)
        emit({"event": "stopped", "requests": requests, "errors": errors})


if __name__ == "__main__":
    asyncio.run(main())
