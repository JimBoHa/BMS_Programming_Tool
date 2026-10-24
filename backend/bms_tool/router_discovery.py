"""One explicit local-subnet Who-Is-Router-To-Network response window."""

from __future__ import annotations

import asyncio
import ipaddress

from bacpypes3.ipv4.bvll import OriginalBroadcastNPDU
from bacpypes3.ipv4.service import BIPNormal
from bacpypes3.npdu import IAmRouterToNetwork, WhoIsRouterToNetwork
from bacpypes3.pdu import IPv4Address
from pydantic import Field

from .ip_discovery import IpDiscovery, _bound_network
from .models import StrictModel
from .routed_discovery import LOCK_TIMEOUT_SECONDS, MAX_OBSERVATIONS, _utc
from .scoped_hooks import restore_attribute

PROFILE = "bacnet-local-router-discovery/1"
SCOPE = (
    "Read-only local-subnet router advertisements. Advertised BACnet networks are routing "
    "destinations, not verified physical trunk names or bus types. Silent routers may be absent."
)
_MISSING = object()


class RouterDiscoveryRequest(StrictModel):
    udp_port: int = Field(default=47808, ge=1, le=65535, strict=True)
    timeout_seconds: float = Field(default=2.0, ge=1, le=5, strict=True)
    max_routers: int = Field(default=64, ge=1, le=128, strict=True)
    max_networks: int = Field(default=128, ge=1, le=128, strict=True)


class _Routers:
    def __init__(self, options, network, own):
        self.options, self.network, self.own = options, network, own
        self.routers = {}
        self.observations = self.invalid = self.ignored = 0
        self.truncated = False
        self.done = asyncio.Event()

    def receive(self, packet):
        if self.done.is_set() or not isinstance(packet, IAmRouterToNetwork):
            return
        self.observations += 1
        if self.observations > MAX_OBSERVATIONS:
            self.truncated = True
            self.done.set()
            return
        source = packet.pduSource
        if not isinstance(source, IPv4Address):
            self.ignored += 1
            return
        host, port = source.addrTuple
        ip = ipaddress.IPv4Address(host)
        if (
            source.addrTuple == self.own
            or port != self.options.udp_port
            or ip not in self.network
            or ip in (self.network.network_address, self.network.broadcast_address)
            or packet.npduSADR is not None
            or packet.npduDADR is not None
        ):
            self.ignored += 1
            return
        networks = packet.iartnNetworkList
        oversized = len(networks) > 128
        if oversized:
            networks = networks[:128]
            self.truncated = True
        if any(type(value) is not int or not 1 <= value <= 65534 for value in networks):
            self.invalid += 1
            return
        key = str(source)
        if key not in self.routers:
            if len(self.routers) >= self.options.max_routers:
                self.truncated = True
                self.done.set()
                return
            self.routers[key] = {
                "router": key,
                "networks": [],
                "responses": 0,
                "first_received_at": _utc(),
                "truncated": False,
            }
        row = self.routers[key]
        combined = sorted(set(row["networks"]) | set(networks))
        if oversized or len(combined) > self.options.max_networks:
            row["truncated"] = self.truncated = True
        row.update(
            networks=combined[: self.options.max_networks],
            responses=row["responses"] + 1,
            last_received_at=_utc(),
        )


class RouterDiscovery:
    def __init__(self, bacnet, store):
        self.bacnet, self.store = bacnet, store
        self.ip = IpDiscovery(bacnet, store)

    async def discover(self, **arguments):
        options = RouterDiscoveryRequest(**arguments)
        try:
            await asyncio.wait_for(self.bacnet.lock.acquire(), LOCK_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise ValueError(
                "BACnet interface is busy; router discovery did not transmit."
            ) from exc
        nsap = observer = previous = None
        observing = False
        try:
            app, config, adapter, layer = self.ip._interface()
            if not isinstance(layer, BIPNormal):
                raise ValueError(
                    "Local router discovery requires a plain BACnet/IPv4 interface; enter a router address for a remote network."
                )
            network, provenance = _bound_network(adapter.adapterAddr)
            if network.prefixlen >= 31:
                raise ValueError(
                    "This interface has no local broadcast subnet; enter the router address directly."
                )
            own = layer.server.local_transport.get_extra_info("sockname")
            collector = _Routers(options, network, own)
            nsap = app.nsap
            original = nsap.process_npdu
            previous = nsap.__dict__.get("process_npdu", _MISSING)
            observing = True

            async def observer(incoming_adapter, packet):
                if observing and incoming_adapter is adapter:
                    collector.receive(packet)
                await original(incoming_adapter, packet)

            nsap.process_npdu = observer
            target = IPv4Address((str(network.broadcast_address), options.udp_port))
            payload = bytes(WhoIsRouterToNetwork().encode().pduData)
            started = _utc()
            self.ip._check(app, config, layer)
            async with asyncio.timeout(options.timeout_seconds + 1):
                # A local BVLC broadcast only: no global/remote NPDU destination,
                # router search across networks, interface reopen or controller write.
                await layer.request(OriginalBroadcastNPDU(payload, destination=target))
                deadline = asyncio.get_running_loop().time() + options.timeout_seconds
                while not collector.done.is_set():
                    self.ip._check(app, config, layer)
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        await asyncio.wait_for(collector.done.wait(), min(remaining, 0.1))
                    except TimeoutError:
                        pass
                self.ip._check(app, config, layer)
            warnings = []
            if not collector.routers:
                warnings.append(
                    "No router advertisements arrived. Enter a known router address to query it directly."
                )
            if collector.truncated:
                warnings.append("Router discovery reached a result limit; the list is partial.")
            result = {
                "profile": PROFILE,
                "scope": SCOPE,
                "started_at": started,
                "finished_at": _utc(),
                "network": str(network),
                "prefix_source": provenance,
                "udp_port": options.udp_port,
                "destination": str(target),
                "connector_config": config,
                "complete": not collector.done.is_set(),
                "truncated": collector.truncated,
                "routers": sorted(
                    collector.routers.values(), key=lambda row: IPv4Address(row["router"]).addrTuple
                ),
                "invalid_responses": collector.invalid,
                "ignored_sources": collector.ignored,
                "warnings": warnings,
            }
            try:
                self.store.record("bacnet.routers.discover", result)
            except Exception:
                result["audit_error"] = (
                    "Router discovery completed, but its local audit could not be saved."
                )
            return result
        finally:
            observing = False
            if nsap is not None and nsap.__dict__.get("process_npdu") is observer:
                restore_attribute(nsap, "process_npdu", previous, _MISSING)
            self.bacnet.lock.release()
