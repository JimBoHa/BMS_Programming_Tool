"""Scoped route provenance and responses for owned, unsegmented COV traffic.

Other services and other consumers retain their native routing and user data.
The adapter check also composes with temporary explicit-read routing wrappers.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass

from bacpypes3.apdu import APDU
from bacpypes3.npdu import NPDU
from bacpypes3.pdu import PCI, PDU, Address, RemoteStation

from .routed_discovery import ROUTED_HOP_COUNT
from .scoped_hooks import ScopedAttribute

_REPLY = contextvars.ContextVar("bms-owned-cov-reply", default=None)


@dataclass(frozen=True)
class CovRouteEvidence:
    owner: object
    next_hop: str
    remote_source: str | None
    direct_unicast: bool
    segmented: bool
    previous_user_data: object


def remote_source(address):
    if address is None:
        return None
    if address.addrType != Address.remoteStationAddr:
        return "unsupported-source"
    return str(RemoteStation(address.addrNet, address.addrAddr))


def cov_header(packet):
    try:
        header = APDU.decode(PDU(bytes(packet.pduData)))
        if (header.apduType, header.apduService) not in {(0, 1), (1, 2)}:
            return None, None
        # SubscriberProcessIdentifier is the first context Unsigned32. The
        # routed profile accepts only its bounded standard 1..4-byte form.
        data = bytes(header.pduData)
        length = data[0] - 8 if data and 9 <= data[0] <= 12 else 0
        process = (
            int.from_bytes(data[1 : 1 + length], "big")
            if length and len(data) >= length + 1
            else None
        )
        return header, process
    except Exception:
        return None, None


class CovRouteHooks:
    def __init__(self, app, owner, jobs, guard):
        self.app, self.owner, self.jobs, self.guard = app, owner, jobs, guard
        self.adapter = app.nsap.local_adapter
        self.enabled = True
        self.saved = []
        nsap = app.nsap
        old_receive, old_send = nsap.process_npdu, nsap.indication
        old_adapter_send = self.adapter.process_npdu

        def reply(packet):
            context = _REPLY.get()
            if self.enabled and context is not None and context[0] is self:
                job = context[1]
                target = job["target"]
                if packet.pduDestination == target or getattr(packet, "npduDADR", None) == target:
                    self.guard(job)
                    outgoing = NPDU(bytes(packet.pduData))
                    PCI.update(outgoing, packet)
                    outgoing.pduDestination = Address(job["config"].router)
                    outgoing.npduDADR = target
                    outgoing.npduHopCount = ROUTED_HOP_COUNT
                    return outgoing
            return None

        async def adapter_send(packet):
            # Last boundary wins only within the current owned response task;
            # a temporary read-path wrapper may already have chosen a router.
            await old_adapter_send(reply(packet) or packet)

        async def send(packet):
            outgoing = reply(packet)
            if outgoing is not None:
                await self.adapter.process_npdu(outgoing)
            else:
                await old_send(packet)

        async def receive(adapter, packet):
            if not self.enabled or packet.npduNetMessage is not None:
                return await old_receive(adapter, packet)
            header, process = cov_header(packet)
            if header is None:
                return await old_receive(adapter, packet)
            source = remote_source(packet.npduSADR)
            direct = (
                adapter is self.adapter
                and getattr(packet.pduDestination, "addrType", None) == Address.localStationAddr
            )
            evidence = CovRouteEvidence(
                self.owner,
                str(packet.pduSource),
                source,
                direct,
                bool(getattr(header, "apduSeg", False)),
                packet.pduUserData,
            )
            own = next(
                (
                    job
                    for job in self.jobs()
                    if job["app"] is app and job["active"] and job["process_id"] == process
                ),
                None,
            )
            if own is not None and own["config"].router is not None:
                if (
                    not direct
                    or str(packet.pduSource) != own["config"].router
                    or source != own["config"].address
                    or evidence.segmented
                ):
                    own["ignored"] += 1
                    own["last_ignored"] = (
                        "Routed COV next-hop/source mismatch or unsupported segmented notification."
                    )
                    return
            packet.pduUserData = evidence
            token = (
                _REPLY.set((self, own))
                if own is not None and own["config"].router is not None
                else None
            )
            try:
                await old_receive(adapter, packet)
            finally:
                if token is not None:
                    _REPLY.reset(token)

        for obj, name, replacement in (
            (nsap, "process_npdu", receive),
            (nsap, "indication", send),
            (self.adapter, "process_npdu", adapter_send),
        ):
            self.saved.append(ScopedAttribute(obj, name, replacement))

    def owns(self, adapter, packet):
        """Allow only a separately pinned observer through a scoped read filter."""
        header, process = cov_header(packet)
        if (
            not self.enabled
            or adapter is not self.adapter
            or getattr(packet.pduDestination, "addrType", None) != Address.localStationAddr
            or header is None
            or getattr(header, "apduSeg", False)
        ):
            return False
        return any(
            job["app"] is self.app
            and job["active"]
            and job["process_id"] == process
            and job["config"].router == str(packet.pduSource)
            and job["config"].address == remote_source(packet.npduSADR)
            for job in self.jobs()
        )

    def close(self):
        self.enabled = False
        for hook in reversed(self.saved):
            hook.close()
