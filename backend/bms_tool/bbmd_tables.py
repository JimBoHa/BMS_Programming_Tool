"""Explicit bounded read-only BVLC BDT/FDT snapshots on the existing UDP link."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import ipaddress
import secrets
import time
import weakref
from datetime import UTC, datetime
from typing import Literal

from bacpypes3.ipv4.bvll import ReadBroadcastDistributionTable, ReadForeignDeviceTable
from bacpypes3.ipv4.service import BIPForeign, BIPNormal
from bacpypes3.pdu import IPv4Address
from pydantic import Field, field_validator

from .ip_discovery import _bound_network, _ip
from .ipv4_ingress import raw_ingress
from .models import StrictModel
from .scoped_hooks import ScopedAttribute

PROFILE = "read-only-bbmd-tables/1"
MAX_ENTRIES = 256
MAX_JOBS = 16
MAX_RAW_BYTES = 4096
MAX_RESULTS = 8
LOCK_WAIT = 3.0
OPERATION_SECONDS = 14.0
SEND_GAP = 0.1
TABLES = {"bdt": (2, 3, 0x0020), "fdt": (6, 7, 0x0040)}
SCOPE = (
    "Read-BDT/Read-FDT snapshots only. Tables are not a live-device inventory. "
    "BDT and FDT are read separately, without atomicity, source clocks or BVLC transaction IDs; "
    "late replies from the same endpoint cannot be distinguished from current replies. "
    "NACK does not distinguish unsupported service from policy denial. "
    "No table writes/deletions, BBMD hosting, registration changes or BACnet/SC."
)


def _utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _endpoint(value):
    if not isinstance(value, str) or value.strip() != value or value.count(":") > 1:
        raise ValueError("Enter one literal unicast IPv4 BBMD endpoint and optional UDP port.")
    parts = value.split(":")
    host = str(_ip(parts[0]))
    if len(parts) == 2 and (not parts[1].isascii() or not parts[1].isdigit()):
        raise ValueError("BBMD UDP port must be an integer1..65535.")
    port = 47808 if len(parts) == 1 else int(parts[1])
    if not 1 <= port <= 65535:
        raise ValueError("BBMD UDP port must be an integer1..65535.")
    return f"{host}:{port}"


class BbmdInspection(StrictModel):
    endpoint: str = Field(min_length=7, max_length=32)
    tables: list[Literal["bdt", "fdt"]] = Field(
        default_factory=lambda: ["bdt", "fdt"], min_length=1, max_length=2
    )
    timeout_seconds: float = Field(default=2.0, ge=0.1, le=5.0, strict=True)

    @field_validator("endpoint")
    @classmethod
    def literal_endpoint(cls, value):
        return _endpoint(value)

    @field_validator("tables")
    @classmethod
    def distinct_tables(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Request each table at most once per inspection.")
        return value


class BbmdCancel(StrictModel):
    id: str = Field(min_length=1, max_length=64)


def _raw(packet, peer):
    data = bytes(packet)
    return {
        "received_at": _utc(),
        "peer": peer,
        "wire_bytes": len(data),
        "raw_hex": data[:MAX_RAW_BYTES].hex(),
        "raw_complete": len(data) <= MAX_RAW_BYTES,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def decode_table(data, table):
    """Preserve all four native BDT mask bytes; native prefix conversion is lossy."""
    request, acknowledgement, nack = TABLES[table]
    if len(data) < 4 or data[0] != 0x81 or int.from_bytes(data[2:4], "big") != len(data):
        raise ValueError("BVLC type/declared length differs from the complete UDP datagram.")
    if data[1] != acknowledgement:
        raise ValueError("Response is not this table's native acknowledgement function.")
    if (len(data) - 4) % 10:
        raise ValueError("Table ACK payload must contain complete ten-byte entries.")
    count = (len(data) - 4) // 10
    if count > MAX_ENTRIES:
        raise OverflowError(
            f"Table has {count} entries; limit is {MAX_ENTRIES}. No partial table accepted."
        )
    rows = []
    for offset in range(4, len(data), 10):
        entry = data[offset : offset + 10]
        host = str(ipaddress.IPv4Address(entry[:4]))
        port = int.from_bytes(entry[4:6], "big")
        row = {"index": len(rows), "ip": host, "port": port, "address": f"{host}:{port}"}
        if table == "bdt":
            mask = str(ipaddress.IPv4Address(entry[6:10]))
            bits = int.from_bytes(entry[6:10], "big")
            inverted = bits ^ 0xFFFFFFFF
            contiguous = inverted & (inverted + 1) == 0
            prefix = bits.bit_count() if contiguous else None
            row.update(
                mask=mask,
                mask_hex=entry[6:10].hex(),
                mask_contiguous=prefix is not None,
                mask_prefix_length=prefix,
            )
        else:
            row.update(
                ttl_seconds=int.from_bytes(entry[6:8], "big"),
                remaining_seconds=int.from_bytes(entry[8:10], "big"),
            )
        rows.append(row)
    return rows


class BbmdTables:
    def __init__(self, bacnet, store=None):
        self.bacnet, self.store = bacnet, store
        self.jobs = {}
        self.closed = False
        self.evicted = 0
        self.last_send = 0.0
        self.interface_ids = weakref.WeakKeyDictionary()

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
            raise ValueError("BBMD inspection requires an already opened BACnet/IPv4 interface.")
        layer = adapter.clientPeer
        if not isinstance(layer, (BIPNormal, BIPForeign)):
            raise ValueError("BBMD inspection requires a normal or managed foreign IPv4 link.")
        self._guard(app, config, layer)
        return app, config, layer

    def _guard(self, app, config, layer, binding=None):
        if self.bacnet.require() is not app or self.bacnet.config != config:
            raise ValueError("BACnet interface changed; repeat the inspection explicitly.")
        adapter = app.nsap.local_adapter
        if adapter is None or adapter.clientPeer is not layer:
            raise ValueError("BACnet link binding changed during inspection.")
        if binding is not None and (
            adapter is not binding[0]
            or layer.server.local_transport is not binding[1]
            or layer.server.local_transport.get_extra_info("sockname") != binding[2]
        ):
            raise ValueError("BACnet UDP socket identity changed during inspection.")
        native = layer.serviceElement
        if native is not None and any(
            getattr(native, name, None) is not None
            for name in ("read_bdt_future", "read_fdt_future")
        ):
            raise ValueError(
                "A native BVLC table request is pending; snapshot ownership is ambiguous."
            )
        transport = layer.server.local_transport
        if (
            transport is None
            or transport.is_closing()
            or any(not task.done() for task in layer.server._transport_tasks)
        ):
            raise ValueError("BACnet UDP interface is stopped or still starting.")

    def start(self, **arguments):
        options = BbmdInspection(**arguments)
        if self.closed:
            raise ValueError("BBMD inspection service is closed.")
        if any(job["active"] for job in self.jobs.values()):
            raise ValueError("A BBMD inspection is already running; cancel or finish it first.")
        app, config, layer = self._interface()
        target = IPv4Address(options.endpoint)
        if target.addrTuple == layer.server.local_transport.get_extra_info("sockname"):
            raise ValueError("Select a remote BBMD endpoint, not this client's own socket.")
        try:
            network, _ = _bound_network(app.nsap.local_adapter.adapterAddr, strict_prefix=False)
        except ValueError:
            network = None
        if (
            network is not None
            and network.prefixlen < 31
            and ipaddress.IPv4Address(target.addrTuple[0])
            in (network.network_address, network.broadcast_address)
        ):
            raise ValueError("The BBMD endpoint is a known local network/broadcast address.")
        while len(self.jobs) >= MAX_JOBS:
            del self.jobs[next(iter(self.jobs))]
            self.evicted += 1
        local = layer.server.local_transport.get_extra_info("sockname")
        binding = (app.nsap.local_adapter, layer.server.local_transport, local)
        job = {
            "interface_id": self.interface_ids.setdefault(app, secrets.token_hex(12)),
            "local_endpoint": f"{local[0]}:{local[1]}",
            "id": "bbmd-" + secrets.token_hex(12),
            "profile": PROFILE,
            "scope": SCOPE,
            "endpoint": options.endpoint,
            "config": config,
            "options": options.model_dump(),
            "created_at": _utc(),
            "finished_at": None,
            "active": True,
            "state": "queued",
            "reason": "",
            "ignored_peers": 0,
            "unattributed_results": [],
            "unattributed_results_omitted": 0,
            "tables": {
                name: {
                    "state": "not_requested" if name not in options.tables else "queued",
                    "rows": [],
                }
                for name in TABLES
            },
        }
        self.jobs[job["id"]] = job
        job["task"] = asyncio.create_task(
            self._run(job, app, config, layer, options, target, binding),
            name="bbmd-tables-" + job["id"],
        )
        return self._view(job)

    def _view(self, job):
        return copy.deepcopy({key: value for key, value in job.items() if key != "task"})

    def detail(self, identifier):
        if identifier not in self.jobs:
            raise ValueError(
                "BBMD inspection not found; snapshots are retained only in this process."
            )
        return self._view(self.jobs[identifier])

    def status(self):
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "auto_query": False,
            "maximum_entries_per_table": MAX_ENTRIES,
            "maximum_jobs": MAX_JOBS,
            "maximum_raw_bytes": MAX_RAW_BYTES,
            "operation_seconds": OPERATION_SECONDS,
            "lock_wait_seconds": LOCK_WAIT,
            "minimum_send_gap_seconds": SEND_GAP,
            "evicted_jobs": self.evicted,
            "jobs": [self._view(job) for job in self.jobs.values()],
        }

    async def _run(self, job, app, config, layer, options, target, binding):
        locked = False
        hook = None
        pending = None
        current = None
        listening = False
        try:
            await asyncio.wait_for(self.bacnet.lock.acquire(), LOCK_WAIT)
            locked = True
            self._guard(app, config, layer, binding)
            original = layer.multiplexer.confirmation

            async def observe(packet):
                data = bytes(packet.pduData)
                if not listening or len(data) < 2 or data[0] != 0x81 or data[1] not in (0, 3, 7):
                    return await original(packet)
                peer = packet.pduSource
                if not isinstance(peer, IPv4Address) or peer.addrTuple != target.addrTuple:
                    job["ignored_peers"] += 1
                    return await original(packet)
                provenance = raw_ingress(layer, packet)
                if provenance is None:
                    job["ignored_peers"] += 1
                    return await original(packet)
                if current is None or pending is None or pending.done():
                    return await original(packet)
                try:
                    self._guard(app, config, layer, binding)
                except ValueError as exc:
                    # Preserve the loss of ownership even if the native handler
                    # finishes and clears its future before our next loop tick.
                    pending.set_result({"state": "ownership_conflict", "reason": str(exc)})
                    return await original(packet)
                request, acknowledgement, nack = TABLES[current]
                if data[1] == 0:
                    evidence = _raw(data, options.endpoint) | {"receive_provenance": provenance}
                    valid = len(data) == 6 and int.from_bytes(data[2:4], "big") == 6
                    code = int.from_bytes(data[4:6], "big") if valid else None
                    if valid and code == nack:
                        pending.set_result(
                            {
                                "state": "nack",
                                "result_code": code,
                                "result_hex": f"0x{code:04x}",
                                "reason": "Native read-table NACK: unsupported service or policy denial cannot be distinguished.",
                                "response": evidence,
                                "rows": [],
                            }
                        )
                        return
                    if len(job["unattributed_results"]) < MAX_RESULTS:
                        job["unattributed_results"].append(
                            evidence
                            | {
                                "result_code": code,
                                "reason": "Result has no read transaction identifier; not accepted as a table ACK.",
                            }
                        )
                    else:
                        job["unattributed_results_omitted"] += 1
                    return await original(packet)
                if data[1] != acknowledgement:
                    return await original(packet)
                try:
                    self._guard(app, config, layer, binding)
                    rows = decode_table(data, current)
                    result = {"state": "ok", "rows": rows}
                except OverflowError as exc:
                    result = {"state": "bounds_exceeded", "reason": str(exc), "rows": []}
                except ValueError as exc:
                    result = {"state": "malformed", "reason": str(exc), "rows": []}
                pending.set_result(
                    result
                    | {
                        "response": _raw(data, options.endpoint)
                        | {"receive_provenance": provenance}
                    }
                )

            hook = ScopedAttribute(layer.multiplexer, "confirmation", observe)
            job["state"] = "reading"
            async with asyncio.timeout(OPERATION_SECONDS):
                for table in options.tables:
                    self._guard(app, config, layer, binding)
                    await asyncio.sleep(max(0, SEND_GAP - (time.monotonic() - self.last_send)))
                    self._guard(app, config, layer, binding)
                    current = table
                    pending = asyncio.get_running_loop().create_future()
                    row = job["tables"][table]
                    row.update(
                        state="waiting", sent_at=_utc(), request_hex=f"81{TABLES[table][0]:02x}0004"
                    )
                    listening = True
                    self.last_send = time.monotonic()
                    request_type = (
                        ReadBroadcastDistributionTable if table == "bdt" else ReadForeignDeviceTable
                    )
                    await layer.request(request_type(destination=target))
                    deadline = time.monotonic() + options.timeout_seconds
                    while not pending.done() and time.monotonic() < deadline:
                        self._guard(app, config, layer, binding)
                        await asyncio.wait(
                            {pending}, timeout=min(0.05, max(0, deadline - time.monotonic()))
                        )
                    self._guard(app, config, layer, binding)
                    if pending.done() and pending.result().get("state") == "ownership_conflict":
                        raise ValueError(pending.result()["reason"])
                    row.update(
                        pending.result()
                        if pending.done()
                        else {
                            "state": "timeout",
                            "reason": "No attributable ACK/NACK before the response deadline; support and table contents remain unknown.",
                        }
                    )
                    listening = False
                    if not pending.done():
                        pending.cancel()
            job["state"] = "complete"
        except asyncio.CancelledError:
            job.update(
                state="cancelled",
                reason="Inspection cancelled; transmitted reads are not rolled back.",
            )
            raise
        except TimeoutError:
            job.update(
                state="deadline",
                reason="Whole-operation deadline exceeded."
                if locked
                else "Interface lock wait exceeded; no inspection request was sent.",
            )
        except Exception as exc:
            job.update(state="failed", reason=str(exc)[:1000])
        finally:
            listening = False
            if pending is not None and not pending.done():
                pending.cancel()
            if hook is not None:
                hook.close()
            if locked:
                self.bacnet.lock.release()
            for row in job["tables"].values():
                if row["state"] in {"queued", "waiting"}:
                    row.update(state=job["state"], reason=job["reason"])
            job.update(active=False, finished_at=_utc())
            if self.store is not None:
                try:
                    self.store.record(
                        "bacnet.bbmd-tables",
                        {
                            "id": job["id"],
                            "endpoint": job["endpoint"],
                            "state": job["state"],
                            "tables": {name: row["state"] for name, row in job["tables"].items()},
                        },
                    )
                except Exception as exc:
                    job["audit_error"] = str(exc)[:500]

    async def cancel(self, identifier):
        if identifier not in self.jobs:
            raise ValueError("BBMD inspection not found.")
        job = self.jobs[identifier]
        if job["active"]:
            job["task"].cancel()
            await asyncio.gather(job["task"], return_exceptions=True)
            # A task cancelled before its first instruction has no finally block.
            if job["active"]:
                job.update(
                    active=False,
                    state="cancelled",
                    reason="Cancelled before inspection began.",
                    finished_at=_utc(),
                )
                for row in job["tables"].values():
                    if row["state"] == "queued":
                        row["state"] = "cancelled"
        return self._view(job)

    async def close(self):
        self.closed = True
        for identifier in list(self.jobs):
            await self.cancel(identifier)
