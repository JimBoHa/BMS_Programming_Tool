"""Bounded discovery through one explicitly selected BACnet/IPv4 router.

The wire destination is always that router, even when the requested NPDU has a
remote-network broadcast destination. No automatic router search, global
broadcast, field connection, subscription or controller write is performed.
"""

from __future__ import annotations

import asyncio
import copy
import ipaddress
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from bacpypes3.apdu import (
    APDU,
    ErrorRejectAbortNack,
    IAmRequest,
    ReadPropertyACK,
    ReadPropertyRequest,
    WhoIsRequest,
)
from bacpypes3.basetypes import ListOfAddressBinding
from bacpypes3.errors import DecodingError, InvalidTag
from bacpypes3.npdu import NPDU, IAmRouterToNetwork, WhoIsRouterToNetwork
from bacpypes3.pdu import PCI, PDU, Address, IPv4Address, RemoteBroadcast, RemoteStation
from bacpypes3.primitivedata import ObjectIdentifier, TagClass, TagList
from pydantic import Field, field_validator, model_validator

from .bacnet_exchange import confirmed_exchange
from .bacnet_read import read_property
from .bacnet_values import json_value
from .models import StrictModel
from .scoped_hooks import restore_attribute

PROFILE = "bacnet-explicit-router-discovery/1"
SCOPE = (
    "Read-only discovery through the selected IPv4 router. Completion means the requested "
    "response window finished; it does not prove an exhaustive controller inventory or MS/TP bus type."
)
MAX_OBSERVATIONS = 4096
MAX_NPDU_BYTES = 4096
LOCK_TIMEOUT_SECONDS = 5.0
# Match the native NSAP allowance. A selected engine can contain additional
# logical forwarding stages even when its IP endpoint is the only next hop.
ROUTED_HOP_COUNT = 255
_MISSING = object()


def _router(value):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("Router requires a literal unicast IPv4 address with optional UDP port.")
    host, separator, port = value.partition(":")
    try:
        ip = ipaddress.IPv4Address(host)
        if separator and (not port.isascii() or not port.isdecimal()):
            raise ValueError("Invalid UDP port.")
        number = int(port) if separator else 47808
        if (
            ip.is_multicast
            or ip.is_unspecified
            or int(ip) == 0xFFFFFFFF
            or not 1 <= number <= 65535
        ):
            raise ValueError("Invalid unicast endpoint.")
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "Router requires a literal unicast IPv4 address and UDP port1..65535."
        ) from exc
    return IPv4Address((str(ip), number))


def _utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


class RouterNetworksRequest(StrictModel):
    router: str = Field(min_length=1, max_length=64)
    timeout_seconds: float = Field(default=2.0, ge=1, le=5, strict=True)
    max_networks: int = Field(default=64, ge=1, le=128, strict=True)

    @field_validator("router")
    @classmethod
    def literal_router(cls, value):
        return str(_router(value))


class RoutedScanRequest(StrictModel):
    router: str = Field(min_length=1, max_length=64)
    dnet: int = Field(ge=1, le=65534, strict=True)
    low: int = Field(default=0, ge=0, le=4194302, strict=True)
    high: int = Field(default=4194302, ge=0, le=4194302, strict=True)
    timeout_seconds: float = Field(default=3.0, ge=1, le=10, strict=True)
    max_devices: int = Field(default=128, ge=1, le=256, strict=True)

    @field_validator("router")
    @classmethod
    def literal_router(cls, value):
        return str(_router(value))

    @model_validator(mode="after")
    def increasing_range(self):
        if self.low > self.high:
            raise ValueError("Device instance low limit must not exceed the high limit.")
        return self


class RouterBindingsRequest(StrictModel):
    router: str = Field(min_length=1, max_length=64)
    device: int | None = Field(default=None, ge=0, le=4194302, strict=True)
    max_bindings: int = Field(default=2048, ge=1, le=4096, strict=True)

    @field_validator("router")
    @classmethod
    def literal_router(cls, value):
        return str(_router(value))


class RouterProbeRequest(StrictModel):
    router: str = Field(min_length=1, max_length=64)
    dnet: int = Field(ge=1, le=65534, strict=True)
    mac: int = Field(ge=0, le=254, strict=True)

    @field_validator("router")
    @classmethod
    def literal_router(cls, value):
        return str(_router(value))


class ProbeTrunkRequest(StrictModel):
    router: str = Field(min_length=1, max_length=64)
    dnet: int = Field(ge=1, le=65534, strict=True)
    mac_low: int = Field(ge=0, le=254, strict=True)
    mac_high: int = Field(ge=0, le=254, strict=True)
    per_mac_timeout_seconds: float = Field(default=0.75, ge=0.5, le=2.0, strict=True)
    spacing_seconds: float = Field(default=0.1, ge=0.1, le=1.0, strict=True)
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=30.0, strict=True)

    @field_validator("router")
    @classmethod
    def literal_router(cls, value):
        return str(_router(value))

    @model_validator(mode="after")
    def bounded_page(self):
        if not 0 <= self.mac_high - self.mac_low <= 31:
            raise ValueError(
                "A MAC probe page requires an increasing range of at most 32 addresses."
            )
        return self


class _Observation:
    """One bounded collector; observes decoded packets before normal processing."""

    def __init__(self, router, options, *, scanning):
        self.router, self.options, self.scanning = router, options, scanning
        self.done = asyncio.Event()
        self.networks = set()
        self.devices = {}
        self.responses = 0
        self.observations = 0
        self.ignored_sources = 0
        self.invalid = 0
        self.truncated = False
        self.received_at = None

    def receive(self, packet):
        if self.done.is_set():
            return
        if packet.pduSource != self.router:
            self.ignored_sources += 1
            return
        self.observations += 1
        if self.observations > MAX_OBSERVATIONS:
            self.truncated = True
            self.done.set()
            return
        if len(packet.pduData) > MAX_NPDU_BYTES:
            self.invalid += 1
            return
        try:
            if self.scanning:
                self._device(packet)
            else:
                self._networks(packet)
        except Exception:
            # Malformed discovery evidence must not break other point traffic.
            self.invalid += 1

    def _networks(self, packet):
        if not isinstance(packet, IAmRouterToNetwork) or packet.npduSADR is not None:
            return
        self.responses += 1
        self.received_at = _utc()
        for number in packet.iartnNetworkList:
            if type(number) is not int or not 1 <= number <= 65534:
                self.invalid += 1
                continue
            if number in self.networks:
                continue
            if len(self.networks) == self.options.max_networks:
                self.truncated = True
                continue
            self.networks.add(number)

    def _device(self, packet):
        source = packet.npduSADR
        if (
            packet.npduNetMessage is not None
            or source is None
            or source.addrType != Address.remoteStationAddr
            or source.addrNet != self.options.dnet
            or not 1 <= source.addrLen <= 8
        ):
            return
        apdu = APDU.decode(PDU(bytes(packet.pduData)))
        if apdu.apduType != 1 or apdu.apduService != 0:
            return
        tags = TagList.decode(PDU(bytes(apdu.pduData)))
        if len(tags) != 4 or any(
            tag.tag_class != TagClass.application or tag.tag_number != number
            for tag, number in zip(tags, (12, 2, 9, 2), strict=True)
        ):
            self.invalid += 1
            return
        iam = IAmRequest.decode(apdu)
        object_type, instance = iam.iAmDeviceIdentifier
        vendor, maximum = int(iam.vendorID), int(iam.maxAPDULengthAccepted)
        segmentation = int(iam.segmentationSupported)
        if (
            int(object_type) != 8
            or not 0 <= instance <= 4194302
            or not 0 <= vendor <= 65535
            or maximum not in {50, 128, 206, 480, 1024, 1476}
            or segmentation not in {0, 1, 2, 3}
        ):
            self.invalid += 1
            return
        if not self.options.low <= instance <= self.options.high:
            return
        if source.addrLen == 1 and source.addrAddr[0] == 255:
            self.invalid += 1
            return
        self.responses += 1
        self.received_at = _utc()
        key = (int(instance), bytes(source.addrAddr))
        if key in self.devices:
            self.devices[key]["responses"] += 1
            self.devices[key]["last_received_at"] = self.received_at
            return
        if len(self.devices) == self.options.max_devices:
            self.truncated = True
            return
        self.devices[key] = {
            "address": str(source),
            "device": str(iam.iAmDeviceIdentifier),
            "device_instance": int(instance),
            "vendor": vendor,
            "max_apdu": maximum,
            "segmentation": str(iam.segmentationSupported),
            "router": str(self.router),
            "dnet": self.options.dnet,
            "mac_hex": source.addrAddr.hex(),
            "mstp_mac": source.addrAddr[0] if source.addrLen == 1 else None,
            "responses": 1,
            "first_received_at": self.received_at,
            "last_received_at": self.received_at,
        }


class RoutedDiscovery:
    def __init__(self, bacnet, audit_store=None):
        self.bacnet = bacnet
        self.audit_store = audit_store if audit_store is not None else bacnet.store

    def status(self):
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "connected": self.bacnet.status()["connected"],
            "limits": {
                "networks": 128,
                "devices": 256,
                "observations": MAX_OBSERVATIONS,
                "response_window_seconds": 10,
                "lock_wait_seconds": LOCK_TIMEOUT_SECONDS,
                "macs_per_probe_page": 32,
                "single_probe_response_budget_seconds": 20,
                "probe_page_response_budget_seconds": 30,
                "minimum_probe_gap_seconds": 0.1,
            },
        }

    def _check(self, app, config):
        if self.bacnet.require() is not app or self.bacnet.config != config:
            raise ValueError("BACnet interface changed during routed discovery; repeat explicitly.")
        for layer in app.link_layers.values():
            server = getattr(layer, "server", None)
            if server is not None and (
                server.local_transport is None or server.local_transport.is_closing()
            ):
                raise ValueError(
                    "BACnet UDP interface stopped during routed discovery; reconnect explicitly."
                )

    def _interface(self):
        app = self.bacnet.require()
        config = copy.deepcopy(self.bacnet.config)
        if config is None or config.get("transport") == "mstp":
            raise ValueError(
                "Routed discovery requires an already connected BACnet/IPv4 interface."
            )
        adapter = app.nsap.local_adapter
        if adapter is None or not isinstance(adapter.adapterAddr, IPv4Address):
            raise ValueError("Routed discovery requires one local BACnet/IPv4 adapter.")
        return app, config, adapter

    async def networks(self, **arguments):
        options = RouterNetworksRequest(**arguments)
        return await self._run(options, scanning=False)

    async def scan(self, **arguments):
        options = RoutedScanRequest(**arguments)
        return await self._run(options, scanning=True)

    @asynccontextmanager
    async def _probe_path(self, options, macs):
        router = _router(options.router)
        try:
            await asyncio.wait_for(self.bacnet.lock.acquire(), LOCK_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise ValueError(
                "BACnet interface is busy; controller probe did not transmit."
            ) from exc
        nsap = source_filter = directed = previous_source = previous_send = None
        observing = False
        try:
            app, config, adapter = self._interface()
            if (
                config.get("router") is None
                or _router(config["router"]) != router
                or config.get("dnet") != options.dnet
            ):
                raise ValueError(
                    "Open the selected router and destination network before probing a controller."
                )
            macs = frozenset(macs)
            for mac in macs:
                self.bacnet.target_address(f"{options.dnet}:{mac}")

            def selected(address):
                return (
                    address is not None
                    and address.addrType == Address.remoteStationAddr
                    and address.addrNet == options.dnet
                    and address.addrLen == 1
                    and address.addrAddr[0] in macs
                )

            nsap = app.nsap
            previous_source = nsap.__dict__.get("process_npdu", _MISSING)
            previous_send = nsap.__dict__.get("indication", _MISSING)
            original_source, original_send = nsap.process_npdu, nsap.indication
            counters = {"ignored_router_packets": 0}
            observing = True

            async def source_filter(incoming_adapter, packet):
                if (
                    observing
                    and incoming_adapter is adapter
                    and selected(packet.npduSADR)
                    and packet.pduSource != router
                ):
                    counters["ignored_router_packets"] += 1
                    return
                await original_source(incoming_adapter, packet)

            async def directed(packet):
                if observing and selected(packet.pduDestination):
                    self._check(app, config)
                    outgoing = NPDU(bytes(packet.pduData))
                    PCI.update(outgoing, packet)
                    outgoing.pduDestination = router
                    outgoing.npduDADR = packet.pduDestination
                    outgoing.npduHopCount = ROUTED_HOP_COUNT
                    await adapter.process_npdu(outgoing)
                else:
                    await original_send(packet)

            nsap.process_npdu, nsap.indication = source_filter, directed
            yield app, config, counters
        finally:
            observing = False
            if nsap is not None:
                for name, temporary, previous in (
                    ("process_npdu", source_filter, previous_source),
                    ("indication", directed, previous_send),
                ):
                    if nsap.__dict__.get(name) is temporary:
                        restore_attribute(nsap, name, previous, _MISSING)
            self.bacnet.lock.release()

    async def probe(self, **arguments):
        """Identify one selected MS/TP MAC without I-Am or a guessed Device ID."""
        options = RouterProbeRequest(**arguments)
        router = _router(options.router)
        async with self._probe_path(options, [options.mac]) as (app, config, counters):
            target = self.bacnet.target_address(f"{options.dnet}:{options.mac}")
            started_at = _utc()
            deadline = asyncio.get_running_loop().time() + 20
            self._check(app, config)
            identifier = await asyncio.wait_for(
                read_property(app, target, "device,4194303", "object-identifier"), 6.0
            )
            self._check(app, config)
            kind, instance = identifier
            if int(kind) != 8 or not 0 <= instance <= 4194302:
                raise ValueError("Controller probe did not return an actual Device identifier.")
            device = ObjectIdentifier(("device", int(instance)))
            properties, errors = {}, []
            for name in (
                "object-name",
                "vendor-identifier",
                "model-name",
                "firmware-revision",
                "application-software-version",
            ):
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    errors.append(
                        {
                            "property": name,
                            "error": "Probe deadline reached; remaining properties were not read.",
                        }
                    )
                    break
                self._check(app, config)
                try:
                    value = await asyncio.wait_for(
                        read_property(app, target, device, name), min(3.0, remaining)
                    )
                    properties[name] = json_value(value)
                except (ValueError, TimeoutError) as exc:
                    errors.append(
                        {"property": name, "error": str(exc) or "Property read timed out."}
                    )
                self._check(app, config)
            result = {
                "profile": PROFILE,
                "scope": "Read-only identity and metadata from one explicitly selected routed MAC. This does not upload its native controller program.",
                "router": str(router),
                "dnet": options.dnet,
                "mac": options.mac,
                "address": str(target),
                "device": str(device),
                "device_instance": int(instance),
                "live_verified": True,
                "properties": properties,
                "errors": errors,
                "complete": not errors,
                "started_at": started_at,
                "finished_at": _utc(),
                "ignored_router_packets": counters["ignored_router_packets"],
                "connector_config": config,
            }
            self._audit("bacnet.controller.probe", result)
            return result

    async def probe_range(self, **arguments):
        """Read only wildcard Device identifiers, sequentially, on one MAC page."""
        options = ProbeTrunkRequest(**arguments)
        router = _router(options.router)
        macs = range(options.mac_low, options.mac_high + 1)
        async with self._probe_path(options, macs) as (app, config, counters):
            started_at = _utc()
            loop = asyncio.get_running_loop()
            deadline = loop.time() + options.timeout_seconds
            devices, attempts, errors, no_response = [], [], [], []
            next_mac = options.mac_low
            for mac in macs:
                self._check(app, config)
                remaining = deadline - loop.time()
                if remaining < options.per_mac_timeout_seconds:
                    break
                target = self.bacnet.target_address(f"{options.dnet}:{mac}")
                window = options.per_mac_timeout_seconds
                attempt = {"mac": mac, "address": str(target), "window_seconds": window}
                try:
                    identifier = await asyncio.wait_for(
                        read_property(app, target, "device,4194303", "object-identifier"),
                        window,
                    )
                    kind, instance = identifier
                    if int(kind) != 8 or not 0 <= instance <= 4194302:
                        raise ValueError("Target did not return an actual Device identifier.")
                    devices.append(
                        {
                            "router": str(router),
                            "dnet": options.dnet,
                            "mac": mac,
                            "address": str(target),
                            "device": str(ObjectIdentifier(("device", int(instance)))),
                            "device_instance": int(instance),
                            "live_verified": True,
                            "received_at": _utc(),
                        }
                    )
                    attempt["outcome"] = "identified"
                except TimeoutError:
                    attempt["outcome"] = "timeout"
                    no_response.append({**attempt})
                except ValueError as exc:
                    attempt.update(outcome="error", error=str(exc))
                    errors.append({**attempt})
                self._check(app, config)
                attempts.append(attempt)
                next_mac = mac + 1
                if next_mac <= options.mac_high:
                    remaining = deadline - loop.time()
                    if remaining < options.spacing_seconds:
                        break
                    await asyncio.sleep(options.spacing_seconds)
            self._check(app, config)
            next_mac = next_mac if next_mac <= options.mac_high else None
            warnings = [
                "A completed page means the requested MACs were attempted, not an exhaustive physical controller inventory.",
                "A timed-out MAC remains unknown; silence does not prove that no controller is present.",
            ]
            if next_mac is not None:
                warnings.append(
                    "The operation deadline ended this page; resume explicitly at next_mac."
                )
            if len({row["device_instance"] for row in devices}) != len(devices):
                warnings.append(
                    "Duplicate Device identifiers were observed; retain router, network and MAC when selecting a controller."
                )
            result = {
                "profile": PROFILE,
                "scope": "Read-only sequential wildcard Device identifier probes on one explicitly selected routed MAC page. Timeouts remain unknown and no native programs are uploaded.",
                "router": str(router),
                "dnet": options.dnet,
                "request": {
                    name: getattr(options, name)
                    for name in (
                        "mac_low",
                        "mac_high",
                        "per_mac_timeout_seconds",
                        "spacing_seconds",
                        "timeout_seconds",
                    )
                },
                "devices": devices,
                "attempts": attempts,
                "errors": errors,
                "no_response": no_response,
                "warnings": warnings,
                "complete": next_mac is None,
                "truncated": next_mac is not None,
                "next_mac": next_mac,
                "started_at": started_at,
                "finished_at": _utc(),
                "ignored_router_packets": counters["ignored_router_packets"],
                "connector_config": config,
            }
            self._audit("bacnet.controller.probe-range", result)
            return result

    async def _router_identity(self, app, config, router, device):
        """Obtain actual identity/capabilities before a potentially segmented read.

        Local segmented receive already works without a remote cache entry.
        Some deployed routers require prior directed discovery before returning
        their large cache; retain the exact observed capabilities rather than
        guessing them or depending on a previous UI discovery action.
        """
        future = app.who_is(
            0 if device is None else device,
            4194302 if device is None else device,
            address=router,
            timeout=2,
        )
        try:
            async with asyncio.timeout(2.25):
                while not future.done():
                    self._check(app, config)
                    await asyncio.wait((future,), timeout=0.1)
                replies = future.result()
            self._check(app, config)
            if len(replies) != 1:
                raise ValueError(
                    "Router identity preflight received no matching I-Am; binding read did not transmit."
                )
            reply = replies[0]
            if (
                not isinstance(reply, IAmRequest)
                or reply.pduSource != router
                or int(reply.iAmDeviceIdentifier[0]) != 8
                or not 0 <= reply.iAmDeviceIdentifier[1] <= 4194302
                or (
                    device is not None
                    and reply.iAmDeviceIdentifier != ObjectIdentifier(("device", device))
                )
                or int(reply.maxAPDULengthAccepted) not in {50, 128, 206, 480, 1024, 1476}
                or int(reply.segmentationSupported) not in {0, 1, 2, 3}
                or not 0 <= int(reply.vendorID) <= 65535
            ):
                raise ValueError(
                    "Router identity preflight returned invalid identity/capabilities."
                )
            # WhoIsFuture normally schedules this update. Await it explicitly
            # so the subsequent confirmed service cannot race that task.
            await app.device_info_cache.set_device_info(reply)
            return {
                "address": str(router),
                "device_instance": reply.iAmDeviceIdentifier[1],
                "max_apdu": int(reply.maxAPDULengthAccepted),
                "segmentation": str(reply.segmentationSupported),
                "vendor": int(reply.vendorID),
                "received_at": _utc(),
            }
        finally:
            future.cancel()

    async def bindings(self, **arguments):
        options = RouterBindingsRequest(**arguments)
        router = _router(options.router)
        try:
            await asyncio.wait_for(self.bacnet.lock.acquire(), LOCK_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise ValueError("BACnet interface is busy; binding read did not transmit.") from exc
        try:
            app, config, adapter = self._interface()
            if router == adapter.adapterAddr:
                raise ValueError("Select a remote router, not this client's own IPv4 endpoint.")
            started_at = _utc()
            identity = await self._router_identity(app, config, router, options.device)
            device = identity["device_instance"]
            request = ReadPropertyRequest(
                objectIdentifier=("device", device),
                propertyIdentifier="device-address-binding",
                destination=router,
            )
            self._check(app, config)
            reply = await asyncio.wait_for(confirmed_exchange(app, request), 6.0)
            self._check(app, config)
            if isinstance(reply, ErrorRejectAbortNack):
                raise ValueError("Router binding read rejected: " + str(reply))
            if (
                not isinstance(reply, ReadPropertyACK)
                or reply.pduSource != router
                or reply.apduInvokeID != request.apduInvokeID
                or reply.objectIdentifier != ObjectIdentifier(("device", device))
                or str(reply.propertyIdentifier) != "device-address-binding"
                or reply.propertyArrayIndex is not None
            ):
                raise ValueError("Router binding acknowledgment identity/property mismatch.")
            encoded = reply.propertyValue.tagList.encode().pduData
            if len(encoded) > 65536:
                raise ValueError("Router binding evidence exceeds the64KiB profile.")
            values = reply.propertyValue.cast_out(ListOfAddressBinding)
            truncated = len(values) > options.max_bindings
            rows, networks, invalid, ignored = [], set(), 0, 0
            for value in values[: options.max_bindings]:
                kind, instance = value.deviceObjectIdentifier
                dnet = int(value.deviceAddress.networkNumber)
                mac = bytes(value.deviceAddress.macAddress)
                if (
                    int(kind) != 8
                    or not 0 <= instance <= 4194303
                    or not 0 <= dnet <= 65534
                    or not 1 <= len(mac) <= 8
                    or (len(mac) == 1 and mac[0] == 255)
                ):
                    invalid += 1
                    continue
                if dnet == 0:
                    # A local-network cache entry is not a routable trunk.
                    ignored += 1
                    continue
                known = int(instance) if instance != 4194303 else None
                networks.add(dnet)
                rows.append(
                    {
                        "address": str(RemoteStation(dnet, mac)),
                        "dnet": dnet,
                        "mac_hex": mac.hex(),
                        "mstp_mac": mac[0] if len(mac) == 1 else None,
                        "device_instance": known,
                        "device": str(ObjectIdentifier(("device", known)))
                        if known is not None
                        else None,
                        "cached": True,
                        "live_verified": False,
                    }
                )
            warnings = [
                "Device address bindings are cached hints, not proof of current liveness, a physical MS/TP trunk, or routing support.",
                "Device instance4194303 is an unknown cache identity; it cannot identify a target device.",
            ]
            if truncated:
                warnings.append("Binding result limit reached; some cached entries were omitted.")
            if invalid:
                warnings.append("Malformed or out-of-profile cache entries were ignored.")
            result = {
                "profile": PROFILE,
                "scope": SCOPE,
                "router": str(router),
                "device": device,
                "router_identity": identity,
                "started_at": started_at,
                "received_at": _utc(),
                "complete": not truncated,
                "truncated": truncated,
                "warnings": warnings,
                "networks": sorted(networks),
                "bindings": rows,
                "total_bindings": len(values),
                "invalid_bindings": invalid,
                "ignored_local_bindings": ignored,
                "connector_config": config,
            }
            self._audit("bacnet.router.bindings", result)
            return result
        except ErrorRejectAbortNack as exc:
            raise ValueError("Router binding read rejected: " + str(exc)) from exc
        except (DecodingError, InvalidTag, TypeError, AttributeError) as exc:
            raise ValueError("Malformed BACnet router binding response.") from exc
        finally:
            self.bacnet.lock.release()

    def _audit(self, kind, result):
        try:
            self.audit_store.record(kind, result)
        except Exception:
            result["audit_error"] = (
                "Discovery completed, but its local audit record could not be saved."
            )

    async def _run(self, options, *, scanning):
        router = _router(options.router)
        try:
            await asyncio.wait_for(self.bacnet.lock.acquire(), LOCK_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise ValueError(
                "BACnet interface is busy; routed discovery did not transmit."
            ) from exc
        nsap = observer = previous = None
        try:
            app, config, adapter = self._interface()
            if router == adapter.adapterAddr:
                raise ValueError("Select a remote router, not this client's own IPv4 endpoint.")
            observation = _Observation(router, options, scanning=scanning)
            nsap = app.nsap
            previous = nsap.__dict__.get("process_npdu", _MISSING)
            original = nsap.process_npdu
            observing = True

            async def observer(incoming_adapter, packet):
                if observing and incoming_adapter is adapter:
                    observation.receive(packet)
                await original(incoming_adapter, packet)

            nsap.process_npdu = observer
            started_at = _utc()
            # Directly address the selected adapter/router. Going through the
            # generic remote-destination path could automatically broadcast a
            # router search, or choose a cached router other than this one.
            if scanning:
                request = (
                    WhoIsRequest(
                        deviceInstanceRangeLowLimit=options.low,
                        deviceInstanceRangeHighLimit=options.high,
                    )
                    .encode()
                    .encode()
                )
                outgoing = NPDU(bytes(request.pduData), destination=router)
                outgoing.npduDADR = RemoteBroadcast(options.dnet)
                outgoing.npduHopCount = ROUTED_HOP_COUNT
            else:
                outgoing = WhoIsRouterToNetwork(destination=router)
            self._check(app, config)
            async with asyncio.timeout(options.timeout_seconds + 1):
                await adapter.process_npdu(outgoing)
                deadline = asyncio.get_running_loop().time() + options.timeout_seconds
                while not observation.done.is_set():
                    self._check(app, config)
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        await asyncio.wait_for(observation.done.wait(), min(remaining, 0.1))
                    except TimeoutError:
                        pass
                self._check(app, config)
            warnings = []
            if observation.responses == 0:
                warnings.append("No matching response arrived during the requested window.")
            if observation.truncated:
                warnings.append(
                    "Discovery reached a bounded result/observation limit; narrow the request."
                )
            if observation.invalid:
                warnings.append("Malformed or out-of-profile discovery evidence was ignored.")
            result = {
                "profile": PROFILE,
                "scope": SCOPE,
                "router": str(router),
                "started_at": started_at,
                "received_at": observation.received_at,
                "finished_at": _utc(),
                "complete": not observation.done.is_set(),
                "truncated": observation.truncated,
                "warnings": warnings,
                "responses": observation.responses,
                "ignored_source_packets": observation.ignored_sources,
                "invalid_responses": observation.invalid,
                "connector_config": config,
            }
            if scanning:
                devices = sorted(
                    observation.devices.values(),
                    key=lambda row: (row["device_instance"], row["mac_hex"]),
                )
                instances = [row["device_instance"] for row in devices]
                addresses = [row["address"] for row in devices]
                if len(set(instances)) != len(instances) or len(set(addresses)) != len(addresses):
                    warnings.append(
                        "Conflicting device instances or source addresses were observed; inspect each row."
                    )
                result.update(dnet=options.dnet, range=[options.low, options.high], devices=devices)
            else:
                result["networks"] = sorted(observation.networks)
            self._audit("bacnet.routed.scan" if scanning else "bacnet.router.networks", result)
            return result
        finally:
            observing = False
            if nsap is not None and nsap.__dict__.get("process_npdu") is observer:
                restore_attribute(nsap, "process_npdu", previous, _MISSING)
            self.bacnet.lock.release()
