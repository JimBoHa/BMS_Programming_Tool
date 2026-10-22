"""Owned raw-datagram provenance for BACpypes3's shared Windows IPv4 socket.

The pinned stack aliases its local/broadcast protocol on Windows and labels all
received PDUs LocalBroadcast. Never relabel these packets. A scoped receive
context can establish the bound socket and advertised BVLC function, not the
physical IP destination (which this native callback does not provide).
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass

from bacpypes3.ipv4 import IPv4DatagramProtocol
from bacpypes3.npdu import NPDU
from bacpypes3.pdu import PDU, IPv4Address, LocalBroadcast

from .scoped_hooks import ScopedAttribute

_CURRENT = contextvars.ContextVar("bms-owned-ipv4-datagram", default=None)
MAX_DATAGRAM = 65507


@dataclass(frozen=True)
class _Frame:
    owner: object
    peer: tuple
    data: bytes


class _Capture:
    def __init__(self, layer):
        self.layer, self.server = layer, layer.server
        self.protocol, self.transport = self.server.local_protocol, self.server.local_transport
        self.endpoint = self.transport.get_extra_info("sockname")
        self.socket = self.transport.get_extra_info("socket")
        self.active = True
        original = self.protocol.datagram_received

        def receive(data, peer):
            # Native datagram_received creates an async dispatch task. Its
            # context inherits this one frame; concurrent datagrams stay apart.
            frame = None
            if self.valid() and isinstance(data, bytes) and 4 <= len(data) <= MAX_DATAGRAM:
                frame = _Frame(self, tuple(peer), data)
            token = _CURRENT.set(frame)
            try:
                return original(data, peer)
            finally:
                _CURRENT.reset(token)

        self.hook = ScopedAttribute(self.protocol, "datagram_received", receive)

    def valid(self):
        return (
            self.active
            and self.layer.server is self.server
            and self.server.local_protocol is self.protocol
            and self.server.local_transport is self.transport
            and self.protocol.server is self.server
            and self.protocol.__dict__.get("datagram_received") is self.hook.replacement
            and self.socket is not None
            and self.transport.get_extra_info("socket") is self.socket
            and not self.transport.is_closing()
            and self.transport.get_extra_info("sockname") == self.endpoint
        )

    def close(self):
        self.active = False
        self.hook.close()


def install_ipv4_ingress(app):
    """Install once on an owned, ready native IPv4 connector; no global patch."""
    close_ipv4_ingress(app)
    hooks = []
    try:
        for layer in app.link_layers.values():
            server = getattr(layer, "server", None)
            if server is not None and isinstance(
                getattr(server, "local_protocol", None), IPv4DatagramProtocol
            ):
                hooks.append(_Capture(layer))
    except BaseException:
        for hook in hooks:
            hook.close()
        raise
    app._bms_ipv4_ingress_hooks = hooks


def close_ipv4_ingress(app):
    for hook in app.__dict__.pop("_bms_ipv4_ingress_hooks", ()):
        hook.close()


def _local(layer, packet, *, raw):
    server = layer.server
    transport = server.local_transport
    if transport is None or transport.is_closing():
        return None
    endpoint = transport.get_extra_info("sockname")
    destination = packet.pduDestination
    if isinstance(destination, IPv4Address) and destination.addrTuple == endpoint:
        return {
            "basis": "native-stack local endpoint metadata",
            "local_endpoint": list(endpoint),
            "physical_ip_destination": None,
        }
    frame = _CURRENT.get()
    if not isinstance(frame, _Frame):
        return None
    capture = frame.owner
    if (
        not isinstance(capture, _Capture)
        or capture.layer is not layer
        or not capture.valid()
        or not isinstance(destination, LocalBroadcast)
        or not isinstance(capture.protocol.destination, LocalBroadcast)
        or server.broadcast_protocol is not capture.protocol
        or server.broadcast_transport is not capture.transport
        or not isinstance(packet.pduSource, IPv4Address)
        or packet.pduSource.addrTuple != frame.peer
    ):
        return None
    data = frame.data
    if data[0] != 0x81:
        return None
    valid_length = int.from_bytes(data[2:4], "big") == len(data)
    if raw:
        # Malformed management replies remain attributable *as malformed*
        # evidence; the consumer still performs exact function/count decoding.
        if data[1] not in (0, 3, 7, 10) or bytes(packet.pduData) != data:
            return None
        if data[1] == 10 and not valid_length:
            return None
    else:
        if data[1] != 10 or not valid_length:
            return None
        try:
            native = NPDU.decode(PDU(data[4:]))
            if bytes(native.pduData) != bytes(packet.pduData) or any(
                getattr(native, name, None) != getattr(packet, name, None)
                for name in (
                    "npduVersion",
                    "npduNetMessage",
                    "npduVendorID",
                    "npduHopCount",
                    "pduNetworkPriority",
                    "pduExpectingReply",
                )
            ):
                return None
            for name in ("npduSADR", "npduDADR"):
                a, b = getattr(native, name, None), getattr(packet, name, None)
                if (str(a) if a is not None else None) != (str(b) if b is not None else None):
                    return None
        except Exception:
            return None
    return {
        "basis": "owned shared IPv4 socket and raw BVLC frame; physical IP destination unavailable",
        "local_endpoint": list(endpoint),
        "next_hop": str(IPv4Address(frame.peer)),
        "bvlc_function": data[1],
        "bvlc_length_valid": valid_length,
        "udp_payload_bytes": len(data),
        "physical_ip_destination": None,
        "native_destination": str(destination),
    }


def npdu_ingress(layer, packet):
    """Exact native endpoint or owned shared-socket Original-Unicast NPDU."""
    return _local(layer, packet, raw=False)


def raw_ingress(layer, packet):
    """Exact native endpoint or owned shared-socket exact BVLC receive frame."""
    return _local(layer, packet, raw=True)
