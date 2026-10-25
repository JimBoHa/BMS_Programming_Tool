"""Owned BACnet backup/restore and stream File transfers.

No vendor executable is launched. The adapter supplies its negotiated File IDs
and credentials; this layer handles routing, bounded chunks and single dispatch.
Firmware and boot Files are outside the application-transfer File allowlist.
"""

import asyncio
import hashlib
import time

from bacpypes3.apdu import (
    AtomicReadFileACK,
    AtomicReadFileRequest,
    AtomicWriteFileACK,
    AtomicWriteFileRequest,
    ErrorRejectAbortNack,
    ReinitializeDeviceRequest,
    SimpleAckPDU,
)
from bacpypes3.basetypes import (
    AtomicReadFileRequestAccessMethodChoice,
    AtomicReadFileRequestAccessMethodChoiceStreamAccess,
    AtomicWriteFileRequestAccessMethodChoice,
    AtomicWriteFileRequestAccessMethodChoiceStreamAccess,
)

from .application_wire import ApplicationWire
from .bacnet_exchange import confirmed_exchange

MAX_FILE_BYTES = 2 * 1024 * 1024
STATES = frozenset({"start-backup", "end-backup", "start-restore", "end-restore"})


class ApplicationFiles:
    def __init__(self, path, *, writable_files, timeout=4, gap=0.02):
        self.path = path
        self.writable_files = frozenset(writable_files)
        if not self.writable_files or not self.writable_files <= {3, 11, 12}:
            raise ValueError("Application profile cannot admit firmware or boot File objects.")
        self.timeout, self.gap = timeout, gap
        self.wire = ApplicationWire(path)

    async def exchange(self, session, request, expected, *, before_send=None):
        self.path._guard(session)
        delay = self.gap - (time.monotonic() - session.get("last_file_request", 0))
        if delay > 0:
            await asyncio.sleep(delay)
        request.pduDestination = session["target"]
        session["last_file_request"] = time.monotonic()
        try:
            async with self.wire.receive(session, request) as proof:
                reply = await asyncio.wait_for(
                    confirmed_exchange(
                        session["app"],
                        request,
                        single_attempt=True,
                        before_send=before_send,
                        response_timeout=self.timeout,
                    ),
                    self.timeout + 2,
                )
            session["last_application_wire"] = self.wire.validate(reply, session, request, proof)
        except ErrorRejectAbortNack as exc:
            raise ValueError("Application File operation rejected: " + str(exc)) from exc
        self.path._guard(session)
        if isinstance(reply, ErrorRejectAbortNack):
            raise ValueError("Application File operation rejected: " + str(reply))
        if (
            not isinstance(reply, expected)
            or reply.pduSource != session["target"]
            or reply.apduInvokeID != request.apduInvokeID
            or reply.apduService != request.apduService
        ):
            raise ValueError(
                "Application reply does not match its station, service or transaction."
            )
        return reply

    async def state(self, session, state, *, password=None, before_send=None):
        if state not in STATES:
            raise ValueError("Only backup/restore lifecycle states are supported.")
        request = ReinitializeDeviceRequest(
            reinitializedStateOfDevice=state,
            **({"password": password} if password is not None else {}),
        )
        await self.exchange(session, request, SimpleAckPDU, before_send=before_send)

    async def read(self, session, file_id, *, chunk=416):
        if type(file_id) is not int or not 1 <= file_id <= 4194302:
            raise ValueError("Select an actual File identifier.")
        if type(chunk) is not int or not 32 <= chunk <= 416:
            raise ValueError("Application File chunk exceeds the unsegmented profile.")
        result = bytearray()
        for _ in range(8192):
            offset = len(result)
            request = AtomicReadFileRequest(
                fileIdentifier=(10, file_id),
                accessMethod=AtomicReadFileRequestAccessMethodChoice(
                    streamAccess=AtomicReadFileRequestAccessMethodChoiceStreamAccess(
                        fileStartPosition=offset,
                        requestedOctetCount=chunk,
                    )
                ),
            )
            reply = await self.exchange(session, request, AtomicReadFileACK)
            access = reply.accessMethod.streamAccess
            if access is None or int(access.fileStartPosition) != offset:
                raise ValueError("Application File reply has an unexpected stream position.")
            data = bytes(access.fileData)
            if len(data) > chunk or len(result) + len(data) > MAX_FILE_BYTES:
                raise ValueError("Application File exceeds its bounded capture profile.")
            result.extend(data)
            if reply.endOfFile:
                if not result:
                    raise ValueError("Application backup File is empty.")
                return bytes(result)
            if not data:
                raise ValueError("Application File made no progress before EOF.")
        raise ValueError("Application File exceeded its chunk budget.")

    async def write(self, session, file_id, data, *, before_send, chunk=384):
        if file_id not in self.writable_files:
            raise ValueError("File is outside the reviewed application scope.")
        if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_FILE_BYTES:
            raise ValueError("Application payload exceeds the File transfer profile.")
        if type(chunk) is not int or not 32 <= chunk <= 384:
            raise ValueError("Application write chunk exceeds its unsegmented profile.")
        for offset in range(0, len(data), chunk):
            payload = data[offset : offset + chunk]
            request = AtomicWriteFileRequest(
                fileIdentifier=(10, file_id),
                accessMethod=AtomicWriteFileRequestAccessMethodChoice(
                    streamAccess=AtomicWriteFileRequestAccessMethodChoiceStreamAccess(
                        fileStartPosition=offset,
                        fileData=payload,
                    )
                ),
            )

            def dispatch(packet, offset=offset, payload=payload):
                before_send(
                    {
                        "file": file_id,
                        "offset": offset,
                        "bytes": len(payload),
                        "payload_sha256": hashlib.sha256(payload).hexdigest(),
                    },
                    packet,
                )

            reply = await self.exchange(session, request, AtomicWriteFileACK, before_send=dispatch)
            if reply.fileStartRecord is not None or reply.fileStartPosition != offset:
                raise ValueError("Application write ACK does not confirm its reviewed offset.")
        return {"file": file_id, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
