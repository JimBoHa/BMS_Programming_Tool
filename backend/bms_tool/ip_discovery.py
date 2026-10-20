"""Explicit, bounded BACnet/IPv4 Who-Is discovery on an existing interface."""

from __future__ import annotations

import asyncio
import copy
import ipaddress
from datetime import UTC, datetime
from typing import Literal

import ifaddr
from bacpypes3.apdu import APDU, IAmRequest, WhoIsRequest
from bacpypes3.ipv4.bvll import (
    DistributeBroadcastToNetwork,
    ForwardedNPDU,
    OriginalBroadcastNPDU,
    OriginalUnicastNPDU,
)
from bacpypes3.ipv4.service import BIPForeign, BIPNormal
from bacpypes3.npdu import NPDU
from bacpypes3.pdu import PDU, IPv4Address
from bacpypes3.primitivedata import TagClass, TagList
from pydantic import Field, field_validator, model_validator

from .models import StrictModel

PROFILE = "bacnet-ip-discovery/1"
SCOPE = (
    "Read-only Who-Is evidence from the explicit IPv4 scope. Completion does not prove an "
    "exhaustive device inventory; silence remains unknown. No routed/global Who-Is is sent."
)
PAGE_HOSTS = 256
MAX_RANGE_HOSTS = 65536
MAX_OBSERVATIONS = 4096
MAX_PACKET_BYTES = 2048
SEND_GAP_SECONDS = 0.05
LOCK_TIMEOUT_SECONDS = 5.0
OPERATION_SECONDS = 30.0
_MISSING = object()


def _utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _ip(value):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("Enter a literal unicast IPv4 address without a port or prefix.")
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError as exc:
        raise ValueError(
            "Enter a literal IPv4 address; hostnames and prefixes are not resolved."
        ) from exc
    if address.is_multicast or address.is_unspecified or int(address) == 0xFFFFFFFF:
        raise ValueError("Multicast, unspecified and limited-broadcast targets are not allowed.")
    return address


class IpScanRequest(StrictModel):
    mode: Literal["local", "single", "range"]
    ip: str | None = Field(default=None, min_length=1, max_length=15)
    start_ip: str | None = Field(default=None, min_length=1, max_length=15)
    end_ip: str | None = Field(default=None, min_length=1, max_length=15)
    cursor_ip: str | None = Field(default=None, min_length=1, max_length=15)
    udp_port: int = Field(default=47808, ge=1, le=65535, strict=True)
    low: int = Field(default=0, ge=0, le=4194302, strict=True)
    high: int = Field(default=4194302, ge=0, le=4194302, strict=True)
    timeout_seconds: float = Field(default=3.0, ge=1, le=10, strict=True)
    max_devices: int = Field(default=256, ge=1, le=256, strict=True)

    @field_validator("ip", "start_ip", "end_ip", "cursor_ip")
    @classmethod
    def literal_ip(cls, value):
        return None if value is None else str(_ip(value))

    @model_validator(mode="after")
    def explicit_scope(self):
        if self.low > self.high:
            raise ValueError("Device instance low limit must not exceed the high limit.")
        if self.mode == "local":
            if any((self.ip, self.start_ip, self.end_ip, self.cursor_ip)):
                raise ValueError("Local discovery cannot include single/range target fields.")
        elif self.mode == "single":
            if self.ip is None or any((self.start_ip, self.end_ip, self.cursor_ip)):
                raise ValueError("Single-IP discovery requires only ip as its target field.")
        else:
            if self.ip is not None or self.start_ip is None or self.end_ip is None:
                raise ValueError("Range discovery requires start_ip and end_ip, without ip.")
            first, last = int(_ip(self.start_ip)), int(_ip(self.end_ip))
            if not 0 <= last - first < MAX_RANGE_HOSTS:
                raise ValueError("An IP range must increase and contain at most 65,536 addresses.")
            # A range cannot cross an invalid non-unicast address block.
            if first <= 0xEFFFFFFF and last >= 0xE0000000:
                raise ValueError("An IP range cannot include multicast addresses.")
            if self.cursor_ip is not None and not first <= int(_ip(self.cursor_ip)) <= last:
                raise ValueError("cursor_ip must stay within the original explicit IP range.")
        return self


def _bound_network(local, *, strict_prefix=True):
    """Resolve the real interface prefix; never guess a classful or /24 mask."""
    address = ipaddress.IPv4Address(local.addrTuple[0])
    matches = set()
    for adapter in ifaddr.get_adapters():
        for entry in adapter.ips:
            if isinstance(entry.ip, str) and entry.ip == str(address):
                matches.add(ipaddress.IPv4Network((address, entry.network_prefix), strict=False))
    configured = local.network
    if len(matches) > 1:
        raise ValueError("The bound IPv4 address has ambiguous interface prefixes.")
    observed = next(iter(matches), None)
    if observed is not None:
        if strict_prefix and configured.prefixlen < 32 and configured != observed:
            raise ValueError("The configured IPv4 prefix differs from the actual interface subnet.")
        return observed, "operating-system-interface"
    if configured.prefixlen < 32:
        return configured, "explicit-connection-prefix"
    raise ValueError(
        "No interface subnet is known for this bind address; use single-IP or range mode."
    )


class _Collector:
    def __init__(self, options, network, foreign, own_endpoint):
        self.options, self.network, self.foreign = options, network, foreign
        self.own_endpoint = own_endpoint
        self.allowed = set()
        self.devices = {}
        self.observations = self.responses = self.ignored = self.invalid = 0
        self.ignored_self = 0
        self.truncated = self.conflicting = False
        self.done = asyncio.Event()

    def receive(self, packet):
        if self.done.is_set() or not isinstance(
            packet, (OriginalUnicastNPDU, OriginalBroadcastNPDU, ForwardedNPDU)
        ):
            return
        self.observations += 1
        if self.observations > MAX_OBSERVATIONS:
            self.truncated = True
            self.done.set()
            return
        outer = packet.pduSource
        if not isinstance(outer, IPv4Address):
            self.ignored += 1
            return
        via = None
        if isinstance(packet, ForwardedNPDU):
            if self.foreign is None or outer != self.foreign.bbmdAddress:
                self.ignored += 1
                return
            endpoint = packet.bvlciAddress
            via = str(outer)
        else:
            endpoint = outer
        if not isinstance(endpoint, IPv4Address):
            self.invalid += 1
            return
        if endpoint.addrTuple == self.own_endpoint:
            self.ignored_self += 1
            return
        host, port = endpoint.addrTuple
        try:
            ip = _ip(host)
        except ValueError:
            self.invalid += 1
            return
        if not 1 <= port <= 65535 or port != self.options.udp_port:
            self.ignored += 1
            return
        if self.options.mode == "local":
            if via is None and (
                self.network is None
                or ip not in self.network
                or (
                    self.network.prefixlen < 31
                    and ip in (self.network.network_address, self.network.broadcast_address)
                )
            ):
                self.ignored += 1
                return
        elif endpoint.addrTuple not in self.allowed:
            self.ignored += 1
            return
        if len(packet.pduData) > MAX_PACKET_BYTES:
            self.invalid += 1
            return
        try:
            npdu = NPDU.decode(PDU(bytes(packet.pduData)))
            if npdu.npduNetMessage is not None or npdu.npduSADR is not None:
                self.ignored += 1
                return
            apdu = APDU.decode(PDU(bytes(npdu.pduData)))
            if apdu.apduType != 1 or apdu.apduService != 0:
                return
            tags = TagList.decode(PDU(bytes(apdu.pduData)))
            if len(tags) != 4 or any(
                tag.tag_class != TagClass.application or tag.tag_number != number
                for tag, number in zip(tags, (12, 2, 9, 2), strict=True)
            ):
                raise ValueError("I-Am must contain exactly its four application fields.")
            iam = IAmRequest.decode(apdu)
            kind, instance = iam.iAmDeviceIdentifier
            vendor, maximum = int(iam.vendorID), int(iam.maxAPDULengthAccepted)
            segmentation = int(iam.segmentationSupported)
            if (
                int(kind) != 8
                or not 0 <= instance <= 4194302
                or not 0 <= vendor <= 65535
                or maximum not in {50, 128, 206, 480, 1024, 1476}
                or segmentation not in {0, 1, 2, 3}
            ):
                raise ValueError("Invalid I-Am identity or advertised capabilities.")
        except Exception:
            self.invalid += 1
            return
        if not self.options.low <= instance <= self.options.high:
            return
        self.responses += 1
        key = (endpoint.addrTuple, int(instance))
        received_at = _utc()
        if key in self.devices:
            row = self.devices[key]
            row["responses"] += 1
            row["last_received_at"] = received_at
            path = {"source_scope": "bbmd-forwarded" if via else "direct-ip", "via_bbmd": via}
            if path not in row["source_paths"]:
                row["source_paths"].append(path)
            if (row["vendor"], row["max_apdu"], row["segmentation"]) != (
                vendor,
                maximum,
                str(iam.segmentationSupported),
            ):
                row["conflicting_announcements"] = self.conflicting = True
            return
        if len(self.devices) >= self.options.max_devices:
            self.truncated = True
            return
        self.devices[key] = {
            "address": str(endpoint),
            "ip": host,
            "udp_port": port,
            "device": str(iam.iAmDeviceIdentifier),
            "device_instance": int(instance),
            "vendor": vendor,
            "max_apdu": maximum,
            "segmentation": str(iam.segmentationSupported),
            "first_received_at": received_at,
            "last_received_at": received_at,
            "responses": 1,
            "source_scope": "bbmd-forwarded" if via else "direct-ip",
            "via_bbmd": via,
            "source_paths": [
                {"source_scope": "bbmd-forwarded" if via else "direct-ip", "via_bbmd": via}
            ],
            "conflicting_announcements": False,
        }


class IpDiscovery:
    def __init__(self, bacnet, store=None):
        self.bacnet = bacnet
        self.store = store if store is not None else bacnet.store

    def _interface(self):
        app = self.bacnet.require()
        config = copy.deepcopy(self.bacnet.config)
        adapter = app.nsap.local_adapter
        if (
            config is None
            or config.get("transport") == "mstp"
            or adapter is None
            or not isinstance(adapter.adapterAddr, IPv4Address)
        ):
            raise ValueError("IP discovery requires an already opened BACnet/IPv4 interface.")
        layer = adapter.clientPeer
        if not isinstance(layer, (BIPNormal, BIPForeign)):
            raise ValueError("IP discovery requires a supported IPv4 link layer.")
        self._check(app, config, layer)
        return app, config, adapter, layer

    def _check(self, app, config, layer):
        if self.bacnet.require() is not app or self.bacnet.config != config:
            raise ValueError("BACnet interface changed during IP discovery; repeat explicitly.")
        server = layer.server
        if server.local_transport is None or server.local_transport.is_closing():
            raise ValueError("BACnet UDP interface stopped; reconnect explicitly.")
        if any(not task.done() for task in server._transport_tasks):
            raise ValueError("BACnet IPv4 interface is still starting; retry after it is ready.")

    def status(self):
        value = {
            "profile": PROFILE,
            "scope": SCOPE,
            "connected": False,
            "auto_connect": False,
            "limits": {
                "range_hosts": MAX_RANGE_HOSTS,
                "hosts_per_page": PAGE_HOSTS,
                "devices": 256,
                "observations": MAX_OBSERVATIONS,
                "maximum_packets_per_second": 20,
                "operation_seconds": OPERATION_SECONDS,
                "lock_wait_seconds": LOCK_TIMEOUT_SECONDS,
            },
        }
        try:
            _, _, adapter, layer = self._interface()
            value["connected"] = True
            if isinstance(layer, BIPForeign):
                value["local_broadcast"] = {
                    "available": True,
                    "broadcast_scope": "bbmd-network",
                    "bbmd_address": str(layer.bbmdAddress),
                }
            else:
                network, provenance = _bound_network(adapter.adapterAddr)
                value["local_broadcast"] = {
                    "available": network.prefixlen < 31,
                    "broadcast_scope": "local-subnet",
                    "network": str(network),
                    "prefix_source": provenance,
                    "reason": None
                    if network.prefixlen < 31
                    else "Point-to-point subnets require single-IP or range discovery.",
                }
        except ValueError as exc:
            value["local_broadcast"] = {"available": False, "reason": str(exc)}
        return value

    async def scan(self, **arguments):
        options = IpScanRequest(**arguments)
        try:
            await asyncio.wait_for(self.bacnet.lock.acquire(), LOCK_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise ValueError("BACnet interface is busy; IP discovery did not transmit.") from exc
        layer = observer = previous = None
        observing = False
        try:
            app, config, adapter, layer = self._interface()
            foreign = layer if isinstance(layer, BIPForeign) else None
            network = prefix_source = None
            try:
                network, prefix_source = _bound_network(
                    adapter.adapterAddr,
                    strict_prefix=options.mode == "local" and foreign is None,
                )
            except ValueError:
                if options.mode == "local" and foreign is None:
                    raise
            if options.mode == "local":
                if foreign is not None:
                    if options.udp_port != foreign.bbmdAddress.addrTuple[1]:
                        raise ValueError(
                            "BBMD-network discovery UDP port must match the registered BBMD port."
                        )
                    targets = [foreign.bbmdAddress]
                    broadcast_scope = "bbmd-network"
                else:
                    if network.prefixlen >= 31:
                        raise ValueError(
                            "Point-to-point subnets have no local broadcast; use single-IP or range discovery."
                        )
                    targets = [IPv4Address((str(network.broadcast_address), options.udp_port))]
                    broadcast_scope = "local-subnet"
                total, final_ip = 1, None
            elif options.mode == "single":
                targets = [IPv4Address((options.ip, options.udp_port))]
                total, final_ip, broadcast_scope = 1, None, None
            else:
                first, final_ip = int(_ip(options.start_ip)), int(_ip(options.end_ip))
                cursor = int(_ip(options.cursor_ip)) if options.cursor_ip else first
                targets = [
                    IPv4Address((str(ipaddress.IPv4Address(number)), options.udp_port))
                    for number in range(cursor, min(final_ip + 1, cursor + PAGE_HOSTS))
                ]
                total, broadcast_scope = final_ip - first + 1, None
            if (
                options.mode == "single"
                and network is not None
                and network.prefixlen < 31
                and any(
                    ipaddress.IPv4Address(target.addrTuple[0])
                    in (network.network_address, network.broadcast_address)
                    for target in targets
                )
            ):
                raise ValueError(
                    "The selected page includes the known local subnet network/broadcast address; choose explicit host bounds."
                )
            own_endpoint = layer.server.local_transport.get_extra_info("sockname")
            if options.mode == "single" and any(
                target.addrTuple == layer.server.local_transport.get_extra_info("sockname")
                for target in targets
            ):
                raise ValueError(
                    "Select a remote BACnet endpoint, not this client's own IPv4 socket."
                )
            collector = _Collector(options, network, foreign, own_endpoint)
            previous = layer.__dict__.get("confirmation", _MISSING)
            original = layer.confirmation
            observing = True

            async def observer(packet):
                if observing:
                    collector.receive(packet)
                await original(packet)

            layer.confirmation = observer
            apdu = (
                WhoIsRequest(
                    deviceInstanceRangeLowLimit=options.low,
                    deviceInstanceRangeHighLimit=options.high,
                )
                .encode()
                .encode()
            )
            payload = bytes(NPDU(bytes(apdu.pduData)).encode().pduData)
            started_at = _utc()
            sent, skipped, processed, last_send = [], [], 0, None
            window_complete = timed_out = False
            try:
                async with asyncio.timeout(OPERATION_SECONDS):
                    for target in targets:
                        if collector.done.is_set():
                            break
                        self._check(app, config, layer)
                        if options.mode == "range":
                            address = ipaddress.IPv4Address(target.addrTuple[0])
                            reason = None
                            if target.addrTuple == own_endpoint:
                                reason = "own-engineering-endpoint"
                            elif (
                                network is not None
                                and network.prefixlen < 31
                                and address in (network.network_address, network.broadcast_address)
                            ):
                                reason = "known-local-network-or-broadcast-address"
                            if reason:
                                skipped.append({"ip": str(address), "reason": reason})
                                processed += 1
                                continue
                        if last_send is not None:
                            gap = SEND_GAP_SECONDS - (asyncio.get_running_loop().time() - last_send)
                            if gap > 0:
                                await asyncio.sleep(gap)
                        self._check(app, config, layer)
                        collector.allowed.add(target.addrTuple)
                        if options.mode == "local":
                            packet_class = (
                                DistributeBroadcastToNetwork if foreign else OriginalBroadcastNPDU
                            )
                        else:
                            packet_class = OriginalUnicastNPDU
                        await layer.request(packet_class(payload, destination=target))
                        sent.append(str(target))
                        processed += 1
                        last_send = asyncio.get_running_loop().time()
                    deadline = asyncio.get_running_loop().time() + options.timeout_seconds
                    while not collector.done.is_set():
                        self._check(app, config, layer)
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            window_complete = True
                            break
                        try:
                            await asyncio.wait_for(collector.done.wait(), min(0.1, remaining))
                        except TimeoutError:
                            pass
                    self._check(app, config, layer)
            except TimeoutError:
                timed_out = True
            next_ip = None
            if options.mode == "range":
                cursor = int(_ip(options.cursor_ip or options.start_ip)) + processed
                if cursor <= final_ip:
                    next_ip = str(ipaddress.IPv4Address(cursor))
            warnings = []
            if not collector.devices:
                warnings.append("No matching I-Am arrived; absent responses remain unknown.")
            if next_ip is not None:
                warnings.append(
                    "More of the original IP range remains; continue explicitly at next_ip."
                )
            if collector.truncated or timed_out:
                warnings.append(
                    "Discovery reached a bounded result, packet or operation limit; retained evidence may be partial."
                )
            if collector.invalid:
                warnings.append("Malformed or out-of-profile I-Am evidence was ignored.")
            if collector.conflicting:
                warnings.append(
                    "Conflicting capabilities were observed for an endpoint/Device identity; first values are retained."
                )
            devices = sorted(
                collector.devices.values(),
                key=lambda row: (int(_ip(row["ip"])), row["udp_port"], row["device_instance"]),
            )
            if len({row["device_instance"] for row in devices}) != len(devices):
                warnings.append(
                    "Duplicate Device identifiers exist at distinct endpoints; select by endpoint and Device together."
                )
            result = {
                "profile": PROFILE,
                "scope": SCOPE,
                "mode": options.mode,
                "request": options.model_dump(),
                "connector_config": config,
                "broadcast_scope": broadcast_scope,
                "bind_network": str(network) if network else None,
                "prefix_source": prefix_source,
                "targets_requested": total,
                "page_targets_requested": len(targets),
                "page_targets_processed": processed,
                "targets_sent": sent,
                "skipped_targets": skipped,
                "next_ip": next_ip,
                "devices": devices,
                "started_at": started_at,
                "finished_at": _utc(),
                "response_window_complete": window_complete,
                "complete": window_complete
                and processed == len(targets)
                and next_ip is None
                and not collector.truncated
                and not timed_out,
                "truncated": collector.truncated or timed_out or next_ip is not None,
                "responses": collector.responses,
                "ignored_source_packets": collector.ignored,
                "ignored_self_packets": collector.ignored_self,
                "invalid_responses": collector.invalid,
                "warnings": warnings,
            }
            try:
                self.store.record("bacnet.ip.discovery", result)
            except Exception:
                result["audit_error"] = (
                    "Discovery completed, but its local audit record could not be saved."
                )
            return result
        finally:
            observing = False
            if layer is not None and layer.__dict__.get("confirmation") is observer:
                if previous is _MISSING:
                    del layer.confirmation
                else:
                    layer.confirmation = previous
            self.bacnet.lock.release()
