"""BACnet/IP (including explicit router paths) and Modbus TCP/RTU.

These are point-service connections. They do not compile or install proprietary
controller programs. Raw serial/Bluetooth ports are not automatically MS/TP masters.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import os
import secrets
import socket
import sqlite3
import struct
import time
from argparse import Namespace

import serial
from bacpypes3.apdu import ErrorRejectAbortNack
from bacpypes3.app import Application
from bacpypes3.basetypes import BinaryPV
from bacpypes3.pdu import Address, LocalBroadcast
from bacpypes3.primitivedata import Double, Null, Real, Unsigned
from serial.tools import list_ports

from .bacnet_read import close_application, read_property
from .bacnet_values import json_value
from .bacnet_write import write_property
from .ipv4_ingress import install_ipv4_ingress

MAX_FOREIGN_DEVICES = 1000


def _unicast(address):
    addr = Address(address)
    if addr.addrType not in (Address.localStationAddr, Address.remoteStationAddr):
        raise ValueError(
            "Select a unicast device/router address; broadcasts are not issued by this interface."
        )
    if hasattr(addr, "addrTuple"):
        ip = ipaddress.ip_address(addr.addrTuple[0])
        if ip.is_multicast or ip.is_unspecified or str(ip) == "255.255.255.255":
            raise ValueError("Select a unicast IP address.")
    return addr


def _slot_matches(slot, expected):
    if not isinstance(slot, dict) or slot.get("type") == "null":
        return False
    actual = slot.get("value")
    # Preflight stores the exact native-wire number. Even one adjacent Real
    # represents a changed command, not rounding that we can claim as our own.
    return actual == expected


class Bacnet:
    def __init__(self, store):
        self.store = store
        self.app = None
        self.config = None
        self.plans = {}
        self.commands = {}
        self.lock = asyncio.Lock()
        self.journal = store.directory / "bacnet-owned-commands.json"
        if self.journal.exists():
            saved = json.loads(self.journal.read_text())
            self.commands = saved["commands"]
            self.config = saved["config"]

    def _persist(self):
        temporary = self.journal.with_suffix(".tmp")
        with temporary.open("w") as stream:
            stream.write(
                json.dumps(
                    {"commands": self.commands, "config": self.config},
                    indent=2,
                    allow_nan=False,
                )
            )
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, self.journal)

    async def connect(
        self,
        local_address,
        instance=4190001,
        router=None,
        dnet=None,
        bbmd_address=None,
        foreign_ttl=60,
    ):
        if type(instance) is not int or not 0 <= instance <= 4194302:
            raise ValueError("BACnet device instance outside allowed range.")
        local = _unicast(local_address)
        if not hasattr(local, "addrTuple") or ipaddress.ip_address(local.addrTuple[0]).version != 4:
            raise ValueError("Local BACnet interface requires an IPv4 bind address.")
        if bool(router) != (dnet is not None):
            raise ValueError("Router address and destination network must be supplied together.")
        if dnet is not None and (type(dnet) is not int or not 1 <= dnet <= 65534):
            raise ValueError("Destination network must be1..65534.")
        router_target = None if router is None else _unicast(router)
        if router_target is not None and (
            not hasattr(router_target, "addrTuple")
            or ipaddress.ip_address(router_target.addrTuple[0]).version != 4
        ):
            raise ValueError("BACnet/IP router requires a unicast IPv4 address.")
        bbmd = None
        if bbmd_address is not None:
            bbmd = _unicast(bbmd_address)
            if (
                not hasattr(bbmd, "addrTuple")
                or ipaddress.ip_address(bbmd.addrTuple[0]).version != 4
                or bbmd.addrTuple[1] == 0
            ):
                raise ValueError(
                    "BBMD registration requires a unicast IPv4 address and nonzero UDP port."
                )
            if type(foreign_ttl) is not int or not 1 <= foreign_ttl <= 65535:
                raise ValueError("Foreign-device TTL must be an integer1..65535 seconds.")
            if bbmd.addrTuple == local.addrTuple:
                raise ValueError("BBMD must be a separate IPv4 endpoint from the local client.")
        elif type(foreign_ttl) is not int or foreign_ttl != 60:
            raise ValueError("Foreign-device TTL requires a BBMD address.")
        async with self.lock:
            requested = {
                "local_address": local_address,
                "instance": instance,
                "router": router,
                "dnet": dnet,
            }
            if bbmd is not None:
                requested.update(bbmd_address=str(bbmd), foreign_ttl=foreign_ttl)
            if self.commands and requested != self.config:
                raise ValueError(
                    "Relinquish owned BACnet commands before changing the connection. Reopen the saved interface to recover commands after restart."
                )
            if self.app and requested == self.config and self.status()["connected"]:
                return self.config
            self.store.record("bacnet.connect.requested", requested)
            if self.app:
                close_application(self.app)
                self.app = None
                await asyncio.sleep(0)
            # Detect invalid/unavailable interfaces before BACpypes starts a
            # background endpoint retry. This also gives immediate bind errors.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.bind(local.addrTuple)
            args = Namespace(
                address=local_address,
                instance=instance,
                name="BMS Studio engineering client",
                vendoridentifier=999,
                network=0,
                foreign=None,
                ttl=30,
                bbmd=None,
            )
            if bbmd is not None:
                from .foreign_bacnet import create_foreign_application

                app = await create_foreign_application(local, bbmd, foreign_ttl, instance=instance)
            else:
                app = Application.from_args(args)
            try:
                # BACpypes creates datagram endpoints in scheduled tasks.
                await asyncio.sleep(0.2)
                for layer in app.link_layers.values():
                    server = getattr(layer, "server", None)
                    if server is not None and getattr(server, "local_transport", None) is None:
                        raise ValueError(
                            "Could not bind the BACnet UDP socket. Check the local IP/port and other BACnet applications."
                        )
                if router:
                    await app.nsap.update_router_references(None, router_target, [dnet])
                install_ipv4_ingress(app)
            except BaseException:
                close_application(app)
                raise
            self.app = app
            self.config = requested
            self._persist()
            self.plans.clear()
            self.store.record("bacnet.connect", self.config)
            return self.config

    def require(self):
        if self.app is None:
            raise ValueError("Connect a BACnet interface first.")
        layer = getattr(self.app, "mstp_link", None)
        if layer is not None and not layer.status()["connected"]:
            raise ValueError(
                "MS/TP link stopped. Inspect the link error and reconnect before requesting point services."
            )
        foreign = getattr(self.app, "foreign_link", None)
        if foreign is not None and not foreign.status()["connected"]:
            raise ValueError(
                foreign.error
                or "BBMD foreign-device registration is unavailable; reconnect explicitly."
            )
        return self.app

    async def connect_mstp(
        self, port, mac, instance=4190001, baudrate=38400, max_master=127, max_info_frames=1
    ):
        from .mstp import MstpMaster
        from .mstp_bacnet import create_mstp_application

        if type(instance) is not int or not 0 <= instance <= 4194302:
            raise ValueError("BACnet device instance outside allowed range.")
        # Validate the complete link policy before closing a working interface.
        MstpMaster(mac, baudrate=baudrate, max_master=max_master, max_info_frames=max_info_frames)
        requested = {
            "transport": "mstp",
            "port": port,
            "mac": mac,
            "instance": instance,
            "baudrate": baudrate,
            "max_master": max_master,
            "max_info_frames": max_info_frames,
        }
        async with self.lock:
            if self.commands and requested != self.config:
                raise ValueError(
                    "Relinquish owned BACnet commands before changing the connection. Reopen the saved interface to recover commands after restart."
                )
            if port not in {p["device"] for p in ports()}:
                raise ValueError(
                    "Choose an enumerated serial device; arbitrary files cannot be opened as an MS/TP port."
                )
            if self.app and requested == self.config and self.status()["connected"]:
                return self.config
            self.store.record("bacnet.mstp.connect.requested", requested)
            if self.app:
                close_application(self.app)
                self.app = None
                await asyncio.sleep(0)
            app = await create_mstp_application(
                **{key: value for key, value in requested.items() if key != "transport"}
            )
            self.app, self.config = app, requested
            self._persist()
            self.plans.clear()
            self.store.record("bacnet.mstp.connect", requested)
            return self.config

    def target_address(self, address):
        target = _unicast(address)
        if self.config and self.config.get("transport") == "mstp":
            if (
                target.addrType != Address.localStationAddr
                or target.addrLen != 1
                or target.addrAddr[0] > 254
            ):
                raise ValueError(
                    "Direct MS/TP targets use a decimal one-octet MAC address, for example 5."
                )
            if target.addrAddr[0] == self.config["mac"]:
                raise ValueError("Select a remote MS/TP MAC, not this client's own address.")
        elif target.addrType == Address.remoteStationAddr:
            if (
                not self.config
                or not self.config.get("router")
                or self.config.get("dnet") != target.addrNet
            ):
                raise ValueError(
                    "Routed targets require the selected router and destination network to be opened first."
                )
            route = getattr(target, "addrRoute", None)
            if route is not None and route != Address(self.config["router"]):
                raise ValueError("Target route differs from the explicitly opened BACnet router.")
        return target

    async def discover(self, address, low=0, high=4194302):
        if not 0 <= low <= high <= 4194302:
            raise ValueError("Invalid device instance range.")
        app = self.require()
        target = self.target_address(address)
        responses = await asyncio.wait_for(app.who_is(low, high, address=target, timeout=2), 4)
        rows = [
            {
                "address": str(r.pduSource),
                "device": str(r.iAmDeviceIdentifier),
                "vendor": int(r.vendorID),
                "max_apdu": int(r.maxAPDULengthAccepted),
            }
            for r in responses
        ]
        self.store.record(
            "bacnet.discovery",
            {"target": address, "range": [low, high], "devices": rows},
        )
        return rows

    async def discover_foreign(self, low=0, high=4194302):
        if type(low) is not int or type(high) is not int or not 0 <= low <= high <= 4194302:
            raise ValueError("Invalid device instance range.")
        async with asyncio.timeout(6):
            async with self.lock:
                app = self.require()
                if getattr(app, "foreign_link", None) is None:
                    raise ValueError(
                        "Explicit BBMD discovery requires a registered foreign-device connection."
                    )
                future = app.who_is(low, high, address=LocalBroadcast(), timeout=2)
                # The pinned helper otherwise retains every unique I-Am until
                # timeout. Bound the new broadcast service without changing
                # concurrent unicast collectors or the application's handlers.
                collector = next(item for item in app._who_is_futures if item.future is future)
                original_match = collector.match

                def bounded_match(reply):
                    if future.done():
                        return
                    original_match(reply)
                    if not future.done() and len(collector.i_ams) >= MAX_FOREIGN_DEVICES:
                        future.set_exception(
                            ValueError(
                                "BBMD discovery result limit reached; narrow the device instance range."
                            )
                        )

                collector.match = bounded_match
                replies = await future
                self.require()
                rows = [
                    {
                        "address": str(reply.pduSource),
                        "device": str(reply.iAmDeviceIdentifier),
                        "vendor": int(reply.vendorID),
                        "max_apdu": int(reply.maxAPDULengthAccepted),
                    }
                    for reply in replies
                ]
                self.store.record(
                    "bacnet.foreign.discovery",
                    {
                        "range": [low, high],
                        "bbmd_address": self.config["bbmd_address"],
                        "devices": rows,
                    },
                )
                return rows

    async def _read(self, address, object_id, property_id="present-value", array_index=None):
        try:
            value = await asyncio.wait_for(
                read_property(
                    self.require(),
                    self.target_address(address),
                    object_id,
                    property_id,
                    array_index,
                ),
                6,
            )
        except ErrorRejectAbortNack as exc:
            raise ValueError("BACnet read rejected: " + str(exc)) from exc
        if isinstance(value, ErrorRejectAbortNack) or (
            isinstance(value, str) and value.startswith("-no ")
        ):
            raise ValueError("BACnet read rejected: " + str(value))
        return value

    async def read(self, address, object_id, property_id="present-value", array_index=None):
        return {
            "address": address,
            "object": object_id,
            "property": property_id,
            "array_index": array_index,
            "value": json_value(await self._read(address, object_id, property_id, array_index)),
        }

    async def objects(self, address, device, offset=0, limit=100, timeout_seconds=15.0):
        if type(offset) is not int or not 0 <= offset <= 20000:
            raise ValueError("Object-list offset must be0..20000.")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Object-list page size must be1..200.")
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or not 1 <= timeout_seconds <= 30
        ):
            raise ValueError("Object-list operation deadline must be1..30 seconds.")
        self.target_address(address)
        rows, length, error = [], None, None
        # The deadline includes lock acquisition, rather than extending behind
        # another operation. Completed entries survive a later read failure.
        try:
            async with asyncio.timeout(timeout_seconds):
                async with self.lock:
                    app, config = self.require(), dict(self.config)
                    raw_length = await self._read(address, device, "object-list", 0)
                    if not isinstance(raw_length, int) or not 0 <= raw_length <= 20000:
                        raise ValueError("Object list exceeds its integer0..20000 profile.")
                    length = int(raw_length)
                    if offset > length:
                        raise ValueError("Object-list offset exceeds the device's list length.")
                    for index in range(offset + 1, min(length, offset + limit) + 1):
                        if self.require() is not app or self.config != config:
                            raise ValueError(
                                "BACnet interface changed during object-list retrieval."
                            )
                        obj = await self._read(address, device, "object-list", index)
                        rows.append({"object": str(obj), "index": index})
                        if index < min(length, offset + limit):
                            await asyncio.sleep(0.05)
                    if self.require() is not app or self.config != config:
                        raise ValueError("BACnet interface changed during object-list retrieval.")
                    if int(await self._read(address, device, "object-list", 0)) != length:
                        raise ValueError("Device object-list length changed during this page.")
        except TimeoutError:
            error = "Object-list operation timed out; completed entries are retained."
        except ValueError as exc:
            if length is None or not rows:
                raise
            error = str(exc)
        next_offset = offset + len(rows)
        more = length is not None and next_offset < length
        result = {
            "address": address,
            "device": device,
            "objects": rows,
            "total": length,
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset if more else None,
            "truncated": more,
            "complete": error is None,
            "error": error,
            "scope": "One read-only object-list page; complete does not imply a stable application backup.",
        }
        self.store.record(
            "bacnet.objects",
            {
                "address": address,
                "device": device,
                "offset": offset,
                "received": len(rows),
                "error": error,
            },
        )
        return result

    async def plan_write(self, address, object_id, value, priority=16):
        if not 8 <= priority <= 16:
            raise ValueError("Engineering commands use priorities 8..16.")
        if type(value) not in (float, int, bool, str):
            raise ValueError("Command must be a finite scalar.")
        self.target_address(address)
        obj = await self.require().parse_object_identifier(object_id)
        if str(obj[0]) not in (
            "analog-output",
            "analog-value",
            "binary-output",
            "binary-value",
            "multi-state-output",
            "multi-state-value",
        ):
            raise ValueError(
                "Only commandable output/value objects are supported. Creating/configuring a physical input requires a native application adapter."
            )
        requested_value = value
        vendor = await self.require().get_vendor_info(device_address=self.target_address(address))
        object_class = vendor.get_object_class(obj[0])
        datatype = object_class.get_property_type("present-value") if object_class else None
        if str(obj[0]) in ("binary-output", "binary-value"):
            if datatype is None or not issubclass(datatype, BinaryPV):
                raise ValueError("Binary command requires a known BinaryPV present-value datatype.")
            # BACnet BinaryPV is an enum, not truthiness. Persist the exact
            # numeric value transmitted/read back so restart ownership works.
            if type(value) is str and value in ("inactive", "active"):
                value = int(value == "active")
            elif type(value) in (bool, int, float) and value in (0, 1):
                value = int(value)
            else:
                raise ValueError("BinaryPV command must be active, inactive, 0, 1, or a boolean.")
        elif str(obj[0]) in ("analog-output", "analog-value"):
            if datatype is None or not issubclass(datatype, Real):
                raise ValueError("Analog command requires a known Real or Double datatype.")
            if type(value) not in (int, float):
                raise ValueError(
                    "Analog command must be a finite integer or float; no strings or booleans."
                )
            from .executable_numbers import require_number

            require_number(value, "Analog command")
            try:
                # Double derives from Real; check it first. Persist exactly the
                # number that survives BACnet's native IEEE wire encoding, so
                # accepted-but-unacknowledged commands retain provable ownership.
                wire_format = "!d" if issubclass(datatype, Double) else "!f"
                value = struct.unpack(wire_format, struct.pack(wire_format, value))[0]
            except (OverflowError, struct.error) as exc:
                raise ValueError("Analog command is outside the finite native wire range.") from exc
            if not math.isfinite(value):
                raise ValueError("Analog command must remain finite in its native wire datatype.")
        else:
            if datatype is None or not issubclass(datatype, Unsigned):
                raise ValueError("Multistate command requires a known Unsigned datatype.")
            if type(value) is not int or value < 1:
                raise ValueError(
                    "Multistate command must be a positive integer; no strings, floats or booleans."
                )
            states = await self._read(address, object_id, "number-of-states")
            if not isinstance(states, int) or states < 1:
                raise ValueError("Multistate object has an invalid number-of-states.")
            if value > states:
                raise ValueError("Multistate command exceeds the object's number-of-states.")
        slot = json_value(await self._read(address, object_id, "priority-array", priority))
        if slot != {"type": "null", "value": None}:
            raise ValueError(
                "Selected priority is already occupied. Choose an unused slot; existing commands will not be overwritten."
            )
        before = json_value(await self._read(address, object_id))
        name = str(await self._read(address, object_id, "object-name"))
        token = secrets.token_urlsafe(24)
        plan = {
            "address": address,
            "object_id": object_id,
            "value": value,
            "requested_value": requested_value,
            "priority": priority,
            "before": before,
            "name": name,
            "config": dict(self.config),
            "expires": time.monotonic() + 300,
        }
        self.plans[token] = plan
        self.plans = {k: v for k, v in self.plans.items() if v["expires"] > time.monotonic()}
        return {
            "token": token,
            "address": address,
            "object": object_id,
            "name": name,
            "priority": priority,
            "before": before,
            "value": value,
            "requested_value": requested_value,
            "expires_in": 300,
            "operation": "BACnet present-value command; not a controller program modification",
        }

    async def apply_write(self, token):
        async with self.lock:
            plan = self.plans.pop(token, None)
            if not plan or plan["expires"] < time.monotonic() or plan["config"] != self.config:
                raise ValueError("Write plan expired or connection changed.")
            address, obj, priority = (
                plan["address"],
                plan["object_id"],
                plan["priority"],
            )
            slot = json_value(await self._read(address, obj, "priority-array", priority))
            if slot != {"type": "null", "value": None}:
                raise ValueError("Priority slot changed since preflight; command canceled.")
            if str(await self._read(address, obj, "object-name")) != plan["name"]:
                raise ValueError("Object identity changed since preflight.")
            self.store.record(
                "bacnet.write.intent",
                {k: v for k, v in plan.items() if k not in ("expires", "config")},
            )
            command = secrets.token_hex(12)
            # Register ownership before transmission: a network timeout may occur
            # after a controller accepted the command. Retain a release path.
            self.commands[command] = {**plan, "status": "pending-verification"}
            self._persist()
            try:
                response = await asyncio.wait_for(
                    write_property(
                        self.require(),
                        self.target_address(address),
                        obj,
                        "present-value",
                        plan["value"],
                        priority=priority,
                    ),
                    6,
                )
                if isinstance(response, ErrorRejectAbortNack):
                    raise ValueError("BACnet write rejected: " + str(response))
                slot = json_value(await self._read(address, obj, "priority-array", priority))
                if not _slot_matches(slot, plan["value"]):
                    raise ValueError(
                        "Priority-slot readback differs from the requested command. The command remains uncertain; inspect before relinquishing."
                    )
                self.commands[command]["slot"] = slot
                self.commands[command]["status"] = "active"
                self._persist()
                result = {
                    "command": command,
                    "slot": slot,
                    "present_value": json_value(await self._read(address, obj)),
                    "release_required": True,
                }
                self.store.record("bacnet.write.verified", result)
                return result
            except BaseException:
                self.store.record(
                    "bacnet.write.uncertain",
                    {
                        "command": command,
                        "address": address,
                        "object": obj,
                        "priority": priority,
                    },
                )
                raise

    async def release(self, command):
        async with self.lock:
            plan = self.commands.get(command)
            if not plan:
                raise ValueError("Owned command not found.")
            address, obj, priority = (
                plan["address"],
                plan["object_id"],
                plan["priority"],
            )
            slot = json_value(await self._read(address, obj, "priority-array", priority))
            if slot != {"type": "null", "value": None} and plan.get("slot") is None:
                current = slot.get("value") if isinstance(slot, dict) else slot
                if current != plan["value"]:
                    raise ValueError(
                        "The uncertain command does not match the priority slot. Inspect with the vendor tool; automatic release cannot establish ownership."
                    )
            if (
                plan.get("slot") is not None
                and slot != plan["slot"]
                and slot != {"type": "null", "value": None}
            ):
                raise ValueError(
                    "Priority slot was changed by another client. Inspect it before releasing."
                )
            response = await asyncio.wait_for(
                write_property(
                    self.require(),
                    self.target_address(address),
                    obj,
                    "present-value",
                    Null(()),
                    priority=priority,
                ),
                6,
            )
            if isinstance(response, ErrorRejectAbortNack):
                raise ValueError(str(response))
            slot = json_value(await self._read(address, obj, "priority-array", priority))
            if slot != {"type": "null", "value": None}:
                raise ValueError("Relinquish did not clear the selected priority slot.")
            del self.commands[command]
            self._persist()
            result = {
                "command": command,
                "released": True,
                "present_value": json_value(await self._read(address, obj)),
            }
            self.store.record("bacnet.release", result)
            return result

    async def disconnect(self):
        async with self.lock:
            if self.commands:
                raise ValueError("Relinquish owned BACnet commands before closing the interface.")
            self.store.record("bacnet.disconnect.requested", {"config": self.config})
            if self.app:
                close_application(self.app)
                self.app = None
            self.plans.clear()
            result = self.status()
            try:
                self.store.record("bacnet.disconnected", {"config": self.config})
            except (OSError, sqlite3.Error) as exc:
                result["audit_error"] = f"Interface closed; audit completion failed: {exc}"
            return result

    def status(self):
        layer = getattr(self.app, "mstp_link", None)
        link = layer.status() if layer is not None else None
        foreign = getattr(self.app, "foreign_link", None)
        registration = foreign.status() if foreign is not None else None
        return {
            "connected": self.app is not None
            and (link is None or link["connected"])
            and (registration is None or registration["connected"]),
            "serial_link": link,
            "foreign_device": registration,
            "config": self.config,
            "commands": [
                {
                    "id": k,
                    "address": v["address"],
                    "object": v["object_id"],
                    "priority": v["priority"],
                    "status": v["status"],
                }
                for k, v in self.commands.items()
            ],
        }

    def close(self):
        # Do not silently relinquish field commands during process shutdown.
        try:
            if self.commands:
                self.store.record("bacnet.shutdown.pending_commands", self.status()["commands"])
        finally:
            if self.app:
                close_application(self.app)
                self.app = None


def ports():
    return [
        {
            "device": p.device,
            "description": p.description,
            "manufacturer": p.manufacturer,
        }
        for p in list_ports.comports()
    ]


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def modbus_read(
    transport,
    address,
    unit=1,
    register=0,
    count=1,
    table="holding",
    port=502,
    baud=38400,
    parity="N",
):
    if table not in ("holding", "input", "coils", "discrete"):
        raise ValueError("Unknown Modbus table.")
    if (
        not 1 <= unit <= 247
        or not 0 <= register <= 65535
        or not 1 <= count <= 125
        or register + count > 65536
    ):
        raise ValueError("Invalid Modbus unit, zero-based register, or count (1..125).")
    function = {"holding": 3, "input": 4, "coils": 1, "discrete": 2}[table]
    request = struct.pack(">BHH", function, register, count)
    if transport == "tcp":
        if not 1 <= port <= 65535:
            raise ValueError("Invalid TCP port.")
        transaction = secrets.randbelow(65536)
        frame = struct.pack(">HHHB", transaction, 0, len(request) + 1, unit) + request

        def recv_exact(sock, length):
            b = b""
            while len(b) < length:
                chunk = sock.recv(length - len(b))
                if not chunk:
                    raise ValueError("Truncated Modbus response.")
                b += chunk
            return b

        with socket.create_connection((address, port), timeout=3) as sock:
            sock.sendall(frame)
            header = recv_exact(sock, 7)
            tx, protocol, length, returned_unit = struct.unpack(">HHHB", header)
            if (
                tx != transaction
                or protocol != 0
                or returned_unit != unit
                or not 2 <= length <= 254
            ):
                raise ValueError("Invalid Modbus TCP response header.")
            response = recv_exact(sock, length - 1)
    elif transport == "rtu":
        if address not in {p["device"] for p in ports()}:
            raise ValueError("Select a currently enumerated serial port.")
        if baud not in (9600, 19200, 38400, 57600, 76800, 115200) or parity not in (
            "N",
            "E",
            "O",
        ):
            raise ValueError("Unsupported serial framing.")
        frame = bytes([unit]) + request
        frame += struct.pack("<H", crc16(frame))
        with serial.Serial(
            address,
            baudrate=baud,
            parity=parity,
            stopbits=2 if parity == "N" else 1,
            timeout=2,
        ) as stream:
            stream.reset_input_buffer()
            stream.write(frame)
            stream.flush()
            header = stream.read(3)
            if len(header) != 3:
                raise ValueError("Serial response timed out.")
            length = 2 if header[1] & 0x80 else header[2] + 2
            packet = header + stream.read(length)
            if (
                len(packet) != 3 + length
                or packet[0] != unit
                or crc16(packet[:-2]) != struct.unpack("<H", packet[-2:])[0]
            ):
                raise ValueError("Truncated/invalid Modbus RTU response or CRC.")
            response = packet[1:-2]
    else:
        raise ValueError(
            "Transport must be tcp or rtu. BTCVT and BACnet MS/TP require their own verified protocol adapter."
        )
    if response[0] == function | 0x80:
        raise ValueError(f"Modbus exception {response[1]}")
    if response[0] != function or len(response) < 2 or len(response) != response[1] + 2:
        raise ValueError("Invalid Modbus function or payload length.")
    payload = response[2:]
    expected = count * 2 if function in (3, 4) else (count + 7) // 8
    if len(payload) != expected:
        raise ValueError("Unexpected register payload size.")
    values = (
        list(struct.unpack(">" + "H" * count, payload))
        if function in (3, 4)
        else [bool(payload[i // 8] & (1 << (i % 8))) for i in range(count)]
    )
    return {
        "transport": transport,
        "address": address,
        "unit": unit,
        "register": register,
        "table": table,
        "values": values,
        "raw": response.hex(),
    }
