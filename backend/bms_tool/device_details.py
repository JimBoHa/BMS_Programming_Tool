"""Bounded read-only Device metadata and genuinely exposed Program names.

An explicit routed read can use a different destination from the engineering
connection without changing its configuration or command journal.
The selected IPv4 next hop and remote source are pinned for this operation.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
from contextlib import asynccontextmanager, nullcontext
from datetime import UTC, datetime

from bacpypes3.npdu import NPDU
from bacpypes3.pdu import PCI, Address, IPv4Address
from bacpypes3.primitivedata import Null, ObjectIdentifier
from pydantic import Field, field_validator, model_validator

from .bacnet_read import read_property
from .bacnet_values import json_value
from .models import StrictModel
from .routed_discovery import ROUTED_HOP_COUNT, _router
from .scoped_hooks import restore_attribute

PROFILE = "bacnet-device-details/1"
SCOPE = (
    "Read-only standard Device metadata and exposed Program objects. Program names are never "
    "inferred from firmware, application software version or descriptions; this does not read "
    "or upload a native controller application."
)
MAX_OBJECTS = 512
MAX_PROGRAMS = 16
MAX_TEXT_BYTES = 4096
_MISSING = object()
PROPERTIES = (
    "object-identifier",
    "object-name",
    "description",
    "vendor-identifier",
    "vendor-name",
    "model-name",
    "firmware-revision",
    "application-software-version",
    "protocol-revision",
    "segmentation-supported",
    "max-apdu-length-accepted",
    "system-status",
    "location",
)


def _utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _status():
    return {"status": "not_read", "error": None, "received_at": None}


class DeviceDetailsRequest(StrictModel):
    address: str = Field(min_length=1, max_length=80)
    device: str = Field(min_length=1, max_length=80)
    router: str | None = Field(default=None, min_length=1, max_length=64)
    dnet: int | None = Field(default=None, ge=1, le=65534, strict=True)

    @field_validator("device")
    @classmethod
    def device_identifier(cls, value):
        try:
            obj = ObjectIdentifier(value)
        except (ValueError, TypeError) as exc:
            raise ValueError("An actual explicit Device object identifier is required.") from exc
        if int(obj[0]) != 8 or not 0 <= obj[1] <= 4194302:
            raise ValueError("Device details require an actual Device instance, not a wildcard.")
        return str(obj)

    @field_validator("router")
    @classmethod
    def literal_router(cls, value):
        return str(_router(value)) if value is not None else None

    @model_validator(mode="after")
    def exact_destination(self):
        if (self.router is None) != (self.dnet is None):
            raise ValueError("Routed details require both the explicit router and DNET.")
        if self.router is None:
            self.address = str(_router(self.address))
            return self
        try:
            target = Address(self.address)
        except (ValueError, TypeError) as exc:
            raise ValueError("Routed details require an explicit DNET:MAC address.") from exc
        if (
            target.addrType != Address.remoteStationAddr
            or target.addrNet != self.dnet
            or not 1 <= target.addrLen <= 8
            or (target.addrLen == 1 and target.addrAddr[0] == 255)
            or getattr(target, "addrRoute", None) is not None
        ):
            raise ValueError("Select an exact unicast DNET:MAC matching the supplied router/DNET.")
        self.address = str(target)
        return self


class _InterfaceChanged(ValueError):
    pass


class DeviceDetails:
    def __init__(self, bacnet, store, *, timeout=1.5, operation_timeout=15.0, request_gap=0.05):
        for value, minimum, maximum in (
            (timeout, 0.05, 1.5),
            (operation_timeout, timeout, 15.0),
            (request_gap, 0.0, 0.1),
        ):
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not minimum <= value <= maximum
            ):
                raise ValueError("Device-details timing exceeds its bounded profile.")
        self.bacnet, self.store = bacnet, store
        self.timeout, self.operation_timeout, self.request_gap = (
            timeout,
            operation_timeout,
            request_gap,
        )

    def status(self):
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "connected": self.bacnet.status()["connected"],
            "read_only": True,
            "auto_poll": False,
            "limits": {
                "request_seconds": self.timeout,
                "operation_seconds": self.operation_timeout,
                "request_gap_seconds": self.request_gap,
                "object_list": MAX_OBJECTS,
                "program_objects": MAX_PROGRAMS,
                "text_bytes": MAX_TEXT_BYTES,
            },
        }

    def _guard(self, session):
        try:
            if (
                self.bacnet.require() is not session["app"]
                or self.bacnet.config != session["config"]
            ):
                raise ValueError("BACnet application/configuration changed.")
            for layer in session["app"].link_layers.values():
                server = getattr(layer, "server", None)
                if server is not None and (
                    server.local_transport is None or server.local_transport.is_closing()
                ):
                    raise ValueError("BACnet UDP socket closed.")
        except ValueError as exc:
            raise _InterfaceChanged("Device-details interface changed; repeat explicitly.") from exc

    @asynccontextmanager
    async def _path(self, options, *, lock_held=False, preserve_packet=None):
        # A composite operation may already own the same connection lock.
        # Default callers continue to acquire it here.
        async with nullcontext() if lock_held else self.bacnet.lock:
            app = self.bacnet.require()
            config = copy.deepcopy(self.bacnet.config)
            adapter = app.nsap.local_adapter
            if (
                config is None
                or config.get("transport") == "mstp"
                or adapter is None
                or not isinstance(adapter.adapterAddr, IPv4Address)
            ):
                raise ValueError(
                    "Device details require an already connected BACnet/IPv4 interface."
                )
            target = Address(options.address)
            session = {"app": app, "config": config, "target": target, "last_request": 0.0}
            self._guard(session)
            if options.router is None:
                yield session
                return
            router = _router(options.router)
            if router == adapter.adapterAddr:
                raise ValueError("Select a remote router, not this interface's own address.")
            nsap = app.nsap
            original_source, original_send = nsap.process_npdu, nsap.indication
            previous_source = nsap.__dict__.get("process_npdu", _MISSING)
            previous_send = nsap.__dict__.get("indication", _MISSING)
            observing = True
            session["ignored_router_packets"] = 0

            async def source_filter(incoming_adapter, packet):
                if (
                    observing
                    and incoming_adapter is adapter
                    and packet.npduSADR == target
                    and packet.pduSource != router
                    and not (preserve_packet and preserve_packet(incoming_adapter, packet))
                ):
                    session["ignored_router_packets"] += 1
                    return
                await original_source(incoming_adapter, packet)

            async def directed(packet):
                if observing and packet.pduDestination == target:
                    self._guard(session)
                    outgoing = NPDU(bytes(packet.pduData))
                    PCI.update(outgoing, packet)
                    outgoing.pduDestination = router
                    outgoing.npduDADR = target
                    outgoing.npduHopCount = ROUTED_HOP_COUNT
                    await adapter.process_npdu(outgoing)
                else:
                    await original_send(packet)

            nsap.process_npdu, nsap.indication = source_filter, directed
            try:
                yield session
            finally:
                observing = False
                for name, temporary, previous in (
                    ("process_npdu", source_filter, previous_source),
                    ("indication", directed, previous_send),
                ):
                    if nsap.__dict__.get(name) is temporary:
                        restore_attribute(nsap, name, previous, _MISSING)

    async def _read(self, session, obj, prop, index=None):
        self._guard(session)
        delay = self.request_gap - (asyncio.get_running_loop().time() - session["last_request"])
        if delay > 0:
            await asyncio.sleep(delay)
        self._guard(session)
        session["last_request"] = asyncio.get_running_loop().time()
        value = await asyncio.wait_for(
            read_property(session["app"], session["target"], obj, prop, index), self.timeout
        )
        self._guard(session)
        return value

    def _error(self, result, obj, prop, exc):
        text = str(exc) or "Property read timed out."
        status = (
            "unsupported" if "unknown-property" in text or "unknownProperty" in text else "error"
        )
        result["errors"].append({"object": obj, "property": prop, "status": status, "error": text})
        return {"status": status, "error": text, "received_at": _utc()}

    async def _field(self, session, result, obj, prop, properties, statuses):
        try:
            value = await self._read(session, obj, prop)
            if isinstance(value, Null):
                raise ValueError("Device metadata returned NULL instead of its declared datatype.")
            encoded = str(value) if isinstance(value, ObjectIdentifier) else json_value(value)
            if type(encoded) not in (str, int):
                raise ValueError(
                    "Device metadata is outside the standard text/integer scalar profile."
                )
            if isinstance(encoded, str) and len(encoded.encode("utf-8")) > MAX_TEXT_BYTES:
                raise ValueError("Device metadata text exceeds the 4096-byte field budget.")
            properties[prop] = encoded
            statuses[prop] = {"status": "ok", "error": None, "received_at": _utc()}
            return value
        except _InterfaceChanged:
            raise
        except (ValueError, TimeoutError) as exc:
            statuses[prop] = self._error(result, obj, prop, exc)
            return None

    async def _programs(self, session, options, result):
        inventory = result["object_list"]
        try:
            raw_count = await self._read(session, options.device, "object-list", 0)
            if not isinstance(raw_count, int) or not 0 <= raw_count <= 4294967295:
                raise ValueError("Device object-list count is not a standard Unsigned32.")
            count = int(raw_count)
            inventory["total"] = count
            if not 0 <= count <= MAX_OBJECTS:
                result["programs_status"] = "limit_exceeded"
                raise ValueError("Device object-list exceeds the 512-object details profile.")
            remote_maximum = result["properties"]["max-apdu-length-accepted"]
            local_maximum = int(session["app"].device_object.maxApduLengthAccepted)
            # Each standard ObjectIdentifier occupies exactly five application
            # tag/data bytes; reserve 32 bytes for confirmed ACK/property framing.
            array_limit = (
                min(85, max(0, (min(local_maximum, remote_maximum) - 32) // 5))
                if type(remote_maximum) is int and remote_maximum >= 50
                else 0
            )
            values = []
            if count <= array_limit:
                inventory["method"] = "whole_array"
                values = list(await self._read(session, options.device, "object-list"))
                inventory["read_count"] = len(values)
                if len(values) != count:
                    raise ValueError("Device object-list array length changed.")
            else:
                inventory["method"] = "indexed"
                for index in range(1, count + 1):
                    values.append(await self._read(session, options.device, "object-list", index))
                    inventory["read_count"] = len(values)
            identifiers = [str(value) for value in values]
            if len(set(identifiers)) != count or any(
                not 0 <= value[1] <= 4194302 for value in values
            ):
                raise ValueError("Device object-list contains duplicate or invalid identities.")
            if options.device not in identifiers:
                raise ValueError("Device object-list omits its own verified Device identity.")
            if int(await self._read(session, options.device, "object-list", 0)) != count:
                raise ValueError("Device object-list count changed during details collection.")
            inventory["complete"] = True
            inventory["sha256"] = hashlib.sha256(
                json.dumps(identifiers, separators=(",", ":")).encode()
            ).hexdigest()
            programs = [str(value) for value in values if int(value[0]) == 16]
            result["programs_total"] = len(programs)
            result["programs_truncated"] = len(programs) > MAX_PROGRAMS
            result["programs_status"] = (
                "limit_exceeded"
                if len(programs) > MAX_PROGRAMS
                else "exposed"
                if programs
                else "not_exposed"
            )
            for obj in programs[:MAX_PROGRAMS]:
                props = {name: None for name in ("object-name", "description", "program-state")}
                statuses = {name: _status() for name in props}
                row = {
                    "object": obj,
                    "name": None,
                    "description": None,
                    "state": None,
                    "property_status": statuses,
                }
                result["programs"].append(row)
                for prop, key in (
                    ("object-name", "name"),
                    ("description", "description"),
                    ("program-state", "state"),
                ):
                    await self._field(session, result, obj, prop, props, statuses)
                    row[key] = props[prop]
                    if key == "name" and row["name"] is not None:
                        result["program_names"].append(row["name"])
                if (
                    any(entry["status"] != "ok" for entry in statuses.values())
                    and not result["programs_truncated"]
                ):
                    result["programs_status"] = "partial"
        except _InterfaceChanged:
            raise
        except (ValueError, TimeoutError) as exc:
            self._error(result, options.device, "object-list", exc)
            if result["programs_status"] != "limit_exceeded":
                result["programs_status"] = "partial" if result["programs"] else "unavailable"

    async def read(self, **arguments):
        options = DeviceDetailsRequest(**arguments)
        self.bacnet.require()  # A closed interface is an admission error, not a silent probe.
        result = {
            "profile": PROFILE,
            "scope": SCOPE,
            "read_only": True,
            "address": options.address,
            "device": options.device,
            "device_instance": int(ObjectIdentifier(options.device)[1]),
            "router": options.router,
            "dnet": options.dnet,
            "identity_verified": False,
            "properties": {name: None for name in PROPERTIES},
            "property_status": {name: _status() for name in PROPERTIES},
            "programs": [],
            "program_names": [],
            "programs_status": "not_read",
            "programs_total": None,
            "programs_truncated": False,
            "object_list": {
                "total": None,
                "read_count": 0,
                "complete": False,
                "method": None,
                "sha256": None,
            },
            "errors": [],
            "complete": False,
            "started_at": _utc(),
            "finished_at": None,
            "connector_config": None,
            "ignored_router_packets": 0,
        }
        session = None
        try:
            async with asyncio.timeout(self.operation_timeout):
                async with self._path(options) as session:
                    result["connector_config"] = session["config"]
                    identity = await self._field(
                        session,
                        result,
                        options.device,
                        "object-identifier",
                        result["properties"],
                        result["property_status"],
                    )
                    if identity is not None:
                        if identity != ObjectIdentifier(options.device):
                            raise ValueError(
                                "Device identity differs from the explicitly selected object."
                            )
                        result["identity_verified"] = True
                        for name in PROPERTIES[1:]:
                            await self._field(
                                session,
                                result,
                                options.device,
                                name,
                                result["properties"],
                                result["property_status"],
                            )
                        await self._programs(session, options, result)
        except (TimeoutError, _InterfaceChanged) as exc:
            self._error(
                result,
                options.device,
                "operation",
                exc
                if str(exc)
                else ValueError(
                    "Device-details operation deadline reached; completed fields retained."
                ),
            )
            if result["identity_verified"] and result["programs_status"] in ("not_read", "exposed"):
                result["programs_status"] = "partial"
        if session is not None:
            result["ignored_router_packets"] = session.get("ignored_router_packets", 0)
        result["complete"] = (
            result["identity_verified"]
            and not result["errors"]
            and result["object_list"]["complete"]
            and not result["programs_truncated"]
        )
        result["finished_at"] = _utc()
        try:
            self.store.record("bacnet.device.details", result)
        except Exception:
            result["audit_error"] = (
                "Device details completed, but the local audit could not be saved."
            )
        return result
