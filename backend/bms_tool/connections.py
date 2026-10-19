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
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import Null
from serial.tools import list_ports


def json_value(value):
    if isinstance(value, Null):
        return None
    choice = getattr(value, "_choice", None)
    if choice:
        return {"type": choice, "value": json_value(getattr(value, choice))}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


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
    if type(actual) in (float, int) and type(expected) in (float, int):
        return math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-7)
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

    async def connect(self, local_address, instance=4190001, router=None, dnet=None):
        async with self.lock:
            requested = {
                "local_address": local_address,
                "instance": instance,
                "router": router,
                "dnet": dnet,
            }
            if self.commands and requested != self.config:
                raise ValueError(
                    "Relinquish owned BACnet commands before changing the connection. Reopen the saved interface to recover commands after restart."
                )
            if self.app and requested == self.config:
                return self.config
            if not 0 <= instance <= 4194302:
                raise ValueError("BACnet device instance outside allowed range.")
            local = _unicast(local_address)
            if not hasattr(local, "addrTuple"):
                raise ValueError("Local BACnet interface requires an IPv4 bind address.")
            if bool(router) != (dnet is not None):
                raise ValueError(
                    "Router address and destination network must be supplied together."
                )
            if dnet is not None and not 1 <= dnet <= 65534:
                raise ValueError("Destination network must be 1..65534.")
            if self.app:
                self.app.close()
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
                    await app.nsap.update_router_references(None, _unicast(router), [dnet])
            except BaseException:
                app.close()
                raise
            self.app = app
            self.config = {
                "local_address": local_address,
                "instance": instance,
                "router": router,
                "dnet": dnet,
            }
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
                self.app.close()
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

    async def _read(self, address, object_id, property_id="present-value", array_index=None):
        try:
            value = await asyncio.wait_for(
                self.require().read_property(
                    self.target_address(address), object_id, property_id, array_index
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

    async def objects(self, address, device):
        length = int(await self._read(address, device, "object-list", 0))
        if length > 20000:
            raise ValueError("Object list exceeds 20,000 item limit.")
        rows = []
        # Sequential, bounded reads avoid saturating an MS/TP trunk.
        for index in range(1, min(length, 500) + 1):
            obj = await self._read(address, device, "object-list", index)
            rows.append({"object": str(obj)})
        return {"objects": rows, "total": length, "truncated": length > 500}

    async def plan_write(self, address, object_id, value, priority=16):
        if not 8 <= priority <= 16:
            raise ValueError("Engineering commands use priorities 8..16.")
        if type(value) not in (float, int, bool, str) or (
            type(value) in (float, int) and not math.isfinite(value)
        ):
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
                    self.require().write_property(
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
                self.require().write_property(
                    self.target_address(address), obj, "present-value", Null(()), priority=priority
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
                self.app.close()
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
        return {
            "connected": self.app is not None and (link is None or link["connected"]),
            "serial_link": link,
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
        if self.commands:
            self.store.record("bacnet.shutdown.pending_commands", self.status()["commands"])
        if self.app:
            self.app.close()
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
