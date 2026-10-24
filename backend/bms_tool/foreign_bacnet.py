"""Managed BACnet/IPv4 foreign-device registration and existing BACpypes data link.

Registration is explicit. Renewals run only while this connection is open;
point commands and controller programming are separate services.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from bacpypes3.app import Application
from bacpypes3.comm import bind
from bacpypes3.ipv4 import IPv4DatagramServer
from bacpypes3.ipv4.bvll import BVLLCodec, RegisterForeignDevice, Result
from bacpypes3.ipv4.service import BIPForeign, UDPMultiplexer
from bacpypes3.local.device import DeviceObject

REGISTRATION_TIMEOUT = 3.0
LEASE_GRACE_SECONDS = 30


class _ForeignDatagramServer(IPv4DatagramServer):
    """Cancel the pinned library's pending bind retries when this link closes."""

    def __init__(self, address):
        self.closing = False
        super().__init__(address, no_broadcast=True)

    def set_local_transport_protocol(self, address, task):
        if task.cancelled():
            return
        if self.closing:
            try:
                transport, _ = task.result()
                transport.close()
            except Exception:
                pass
            return
        super().set_local_transport_protocol(address, task)

    def close(self):
        self.closing = True
        for task in self._transport_tasks:
            if not task.done():
                task.cancel()
            elif not task.cancelled():
                try:
                    transport, _ = task.result()
                    transport.close()
                except Exception:
                    pass
        super().close()


class ManagedForeignLink(BIPForeign):
    def __init__(self, local_address, bbmd_address, ttl, *, ack_timeout=REGISTRATION_TIMEOUT):
        if (
            type(ttl) is not int
            or not 1 <= ttl <= 65535
            or type(ack_timeout) not in (int, float)
            or not 0.05 <= ack_timeout <= 3
        ):
            raise ValueError(
                "Foreign registration requires TTL1..65535 and ACK timeout0.05..3 seconds."
            )
        super().__init__()
        self.codec = BVLLCodec()
        self.multiplexer = UDPMultiplexer()
        self.server = _ForeignDatagramServer(local_address)
        bind(self, self.codec, self.multiplexer.annexJ)
        bind(self.multiplexer, self.server)
        self.bbmdAddress, self.bbmdTimeToLive = bbmd_address, ttl
        self.bbmdRegistrationStatus = -1
        self.ack_timeout = ack_timeout
        self._ack = asyncio.Event()
        self._initial = asyncio.Event()
        self._pending = False
        self._worker = None
        self.closed = False
        self.error = None
        self.deregistration_error = None
        self.last_ack = None
        self.last_ack_utc = None
        self._sent_at = None
        self.last_sent_utc = None
        self.lease_expires = None
        self.attempts = 0
        self.acknowledgements = 0
        self.ignored_results = 0

    def start(self):
        if self._worker is not None or self.closed:
            raise ValueError("Foreign-device registration worker already started or closed.")
        self._worker = asyncio.create_task(self._renew(), name="bacnet-foreign-registration")

    async def confirmation(self, packet):
        if isinstance(packet, Result):
            # Read-table NACKs and other BVLC management results cannot be
            # registration outcomes, even during a pending renewal.
            if int(packet.bvlciResultCode) not in (0, 0x0030):
                self.ignored_results += 1
                if self.serviceElement is not None:
                    await self.sap_response(packet)
                return
            if (
                self.closed
                or not self._pending
                or packet.pduSource != self.bbmdAddress
                or packet.bvlciLength != 6
            ):
                self.ignored_results += 1
                return
            self.bbmdRegistrationStatus = int(packet.bvlciResultCode)
            self._pending = False
            if self.bbmdRegistrationStatus == 0:
                self.last_ack = time.monotonic()
                self.last_ack_utc = datetime.now(UTC).isoformat()
                self.lease_expires = self._sent_at + min(
                    self.bbmdTimeToLive + LEASE_GRACE_SECONDS, 65535
                )
                self.acknowledgements += 1
                self._registration_event.set()
            else:
                self.error = f"BBMD rejected foreign-device registration (0x{self.bbmdRegistrationStatus:04x})."
                self._registration_event.clear()
            self._ack.set()
            self._initial.set()
            return
        await super().confirmation(packet)

    def lease_remaining(self):
        return (
            0.0 if self.lease_expires is None else max(0.0, self.lease_expires - time.monotonic())
        )

    async def _renew(self):
        try:
            while not self.closed:
                if self.last_ack is not None and self.lease_remaining() <= 0:
                    self.error = "BBMD foreign-device registration expired; reconnect explicitly."
                    break
                self._ack.clear()
                self._pending = True
                self.attempts += 1
                self._sent_at = time.monotonic()
                self.last_sent_utc = datetime.now(UTC).isoformat()
                await self.request(
                    RegisterForeignDevice(self.bbmdTimeToLive, destination=self.bbmdAddress)
                )
                wait = (
                    self.ack_timeout
                    if self.last_ack is None
                    else min(self.ack_timeout, self.lease_remaining())
                )
                try:
                    await asyncio.wait_for(self._ack.wait(), wait)
                except TimeoutError:
                    self._pending = False
                    if self.last_ack is None:
                        self.error = "BBMD did not acknowledge foreign-device registration."
                        break
                    await asyncio.sleep(min(1.0, self.lease_remaining()))
                    continue
                if self.bbmdRegistrationStatus != 0:
                    break
                await asyncio.sleep(max(0.05, self.bbmdTimeToLive * 0.8))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = f"Foreign-device registration worker failed: {type(exc).__name__}: {exc}"
        finally:
            self._pending = False
            if not self.closed:
                if self.bbmdRegistrationStatus <= 0:
                    self.bbmdRegistrationStatus = -2
                self._registration_event.clear()
            self._initial.set()

    def status(self):
        alive = self._worker is not None and not self._worker.done()
        udp_ready = (
            self.server.local_transport is not None and not self.server.local_transport.is_closing()
        )
        registered = (
            not self.closed
            and udp_ready
            and alive
            and self.bbmdRegistrationStatus == 0
            and self._registration_event.is_set()
            and self.lease_remaining() > 0
        )
        return {
            "connected": registered,
            "registered": registered,
            "bbmd_address": str(self.bbmdAddress),
            "ttl": self.bbmdTimeToLive,
            "status_code": self.bbmdRegistrationStatus,
            "last_acknowledged_at": self.last_ack_utc,
            "last_registration_sent_at": self.last_sent_utc,
            "lease_remaining_seconds": round(self.lease_remaining(), 3),
            "lease_grace_seconds": LEASE_GRACE_SECONDS,
            "lease_duration_seconds": min(self.bbmdTimeToLive + LEASE_GRACE_SECONDS, 65535),
            "attempts": self.attempts,
            "acknowledgements": self.acknowledgements,
            "ignored_results": self.ignored_results,
            "error": self.error,
            "deregistration_error": self.deregistration_error,
            "closed": self.closed,
            "worker_alive": alive,
            "udp_ready": udp_ready,
        }

    def close(self):
        if self.closed:
            return
        self.closed = True
        self._registration_event.clear()
        self.bbmdRegistrationStatus = -2
        if self._worker is not None:
            self._worker.cancel()
        # Send standard six-byte TTL=0 before closing the existing UDP socket.
        # This is best effort, without claiming a remote acknowledgement.
        transport = self.server.local_transport
        if transport is not None and not transport.is_closing():
            try:
                transport.sendto(b"\x81\x05\x00\x06\x00\x00", self.bbmdAddress.addrTuple)
            except (OSError, RuntimeError) as exc:
                self.deregistration_error = str(exc)
        self._stop_tracking_registration()
        self.server.close()


async def create_foreign_application(local, bbmd, ttl, *, instance=4190001):
    app = Application.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", instance),
                objectName="BMS Studio foreign-device engineering client",
                vendorIdentifier=999,
            )
        ]
    )
    layer = ManagedForeignLink(local, bbmd, ttl)
    app.foreign_link = layer
    app.nsap.bind(layer, address=local)
    app.link_layers["foreign"] = layer
    try:
        await asyncio.sleep(0.2)
        if layer.server.local_transport is None:
            raise ValueError("Could not bind the foreign-device BACnet UDP socket.")
        layer.start()
        await asyncio.wait_for(layer._initial.wait(), REGISTRATION_TIMEOUT + 0.5)
        if not layer.status()["connected"]:
            raise ValueError(layer.error or "Foreign-device registration did not become active.")
    except BaseException:
        app.close()
        # UDP transport closure completes on the next event-loop turn. Let it
        # release the bound port before an immediate explicit retry can probe it.
        await asyncio.sleep(0)
        raise
    return app
