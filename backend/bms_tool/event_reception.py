"""Finite, source-pinned standard event reception; no recipient/device writes.

Unsegmented notifications are intercepted before native ServerSSM dispatch, so
wrong-source requests cannot receive this receiver's ACK. ACKs use the exact
received/verified router directly, independently of mutable route caches.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import secrets
import time
from collections import deque
from contextlib import closing
from datetime import UTC, datetime
from typing import Literal

from bacpypes3.apdu import APDU, ConfirmedEventNotificationRequest
from bacpypes3.constructeddata import Any, Sequence
from bacpypes3.npdu import NPDU
from bacpypes3.pdu import PDU, Address, IPv4Address
from bacpypes3.primitivedata import ObjectIdentifier, Tag, TagList
from pydantic import Field, field_validator, model_validator

from .bacnet_event_log import _enum
from .bacnet_read import read_property
from .bacnet_values import json_value
from .cov_route import remote_source
from .device_details import DeviceDetails, DeviceDetailsRequest
from .models import StrictModel
from .scoped_hooks import ScopedAttribute

PROFILE = "finite-ip-routed-event-reception/1"
SCOPE = (
    "Explicit finite reception of unsegmented confirmed/unconfirmed standard EventNotification. "
    "Plain IPv4 or explicit IPv4-router/DNET:MAC; source Device is read back before listening. "
    "No subscription, recipient-list or controller writes. Protocol ACK means reception only, "
    "not operator AcknowledgeAlarm, human receipt, resolution or delivery guarantee. "
    "No BBMD/serial/BTCVT or physical manufacturer acceptance."
)
MAX_ACTIVE, MAX_JOBS, MAX_EVENTS = 8, 32, 100
MAX_APDU, MAX_EVENT_BYTES = 4096, 16384
MAX_CALLBACKS = 16
MAX_SNAPSHOTS, MAX_SNAPSHOT_BYTES = 32, 2 * 1024 * 1024

# Keep the pinned native envelope fields, but retain an unknown nested choice as
# opaque BACnet tags. This does not add a decoder to the global native registry.
_Envelope = type(
    "_EventEnvelope",
    (Sequence,),
    {
        **ConfirmedEventNotificationRequest._elements,
        "_order": ConfirmedEventNotificationRequest._order,
        "eventValues": Any(_context=12, _optional=True),
    },
)


def _utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


class EventListenStart(StrictModel):
    address: str = Field(min_length=1, max_length=100)
    device: str = Field(min_length=1, max_length=100)
    object_id: str | None = Field(default=None, min_length=1, max_length=100)
    router: str | None = Field(default=None, min_length=1, max_length=64)
    dnet: int | None = Field(default=None, ge=1, le=65534, strict=True)
    process_identifier: int = Field(ge=0, le=2**32 - 1, strict=True)
    mode: Literal["confirmed", "unconfirmed", "both"]
    duration_seconds: int = Field(default=60, ge=5, le=3600, strict=True)

    @field_validator("object_id")
    @classmethod
    def identifier(cls, value):
        if value is None:
            return None
        obj = ObjectIdentifier(value)
        if not 0 <= obj[1] <= 4194302:
            raise ValueError("Wildcard object filters are unsupported.")
        return str(obj)

    @model_validator(mode="after")
    def exact_path(self):
        path = DeviceDetailsRequest(
            address=self.address, device=self.device, router=self.router, dnet=self.dnet
        )
        if path.router and Address(path.address).addrLen != 1:
            raise ValueError("Routed reception requires one explicit MS/TP MAC byte.")
        self.address, self.device = path.address, path.device
        self.router, self.dnet = path.router, path.dnet
        return self


class EventListenAction(StrictModel):
    id: str = Field(min_length=1, max_length=80)


def _header(packet):
    try:
        header = APDU.decode(PDU(bytes(packet.pduData)))
        if (header.apduType, header.apduService) not in {(0, 2), (1, 3)}:
            return None, None, None
        data = PDU(bytes(header.pduData))
        first = Tag.decode(data)
        process = (
            int.from_bytes(first.tag_data, "big")
            if (first.tag_class == 1 and first.tag_number == 0 and 1 <= len(first.tag_data) <= 4)
            else None
        )
        second = Tag.decode(data)
        device = (
            int.from_bytes(second.tag_data, "big")
            if (second.tag_class == 1 and second.tag_number == 1 and len(second.tag_data) == 4)
            else None
        )
        return header, process, device
    except Exception:
        return None, None, None


def _decode(header):
    data = bytes(header.pduData)
    tags = TagList.decode(PDU(data))
    if len(tags) > 512:
        raise ValueError("Notification exceeds the 512-tag profile.")
    stack = []
    for tag in tags:
        if tag.tag_class == 2:
            stack.append(tag.tag_number)
            if len(stack) > 16:
                raise ValueError("Notification exceeds the 16-level tag profile.")
        elif tag.tag_class == 3:
            if not stack or stack.pop() != tag.tag_number:
                raise ValueError("Mismatched constructed notification tags.")
    if stack:
        raise ValueError("Unclosed constructed notification tags.")
    value = Sequence.decode(tags, class_=_Envelope)
    if len(tags):
        raise ValueError("Trailing unmatched event-notification tags.")
    if not 0 <= value.priority <= 255 or not 0 <= value.notificationClass <= 2**32 - 1:
        raise ValueError("Priority or notification-class exceeds the standard profile.")
    # Native decoding is attempted independently; unknown nested choices remain
    # raw evidence rather than fabricated named values. Trailing tags are checked.
    native = None
    decode_error = None
    try:
        native_tags = TagList.decode(PDU(data))
        native = Sequence.decode(native_tags, class_=ConfirmedEventNotificationRequest)
        if len(native_tags):
            raise ValueError("Unmatched native notification tags.")
    except Exception as exc:
        decode_error = str(exc)[:500] or type(exc).__name__
    return value, native, decode_error


class EventReception:
    def __init__(self, bacnet, store=None, *, timeout=2.0, clock=None):
        self.bacnet, self.store = bacnet, store
        self.timeout = timeout
        self.clock = clock or time.monotonic
        self.jobs, self.hooks = {}, {}
        self.lock = asyncio.Lock()
        self.operations = set()
        self.closed, self.evicted = False, 0
        if store is not None:
            with closing(store.connect(timeout=0.2)) as db, db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS event_reception_snapshots(id TEXT PRIMARY KEY,created TEXT NOT NULL,body TEXT NOT NULL,sha256 TEXT NOT NULL)"
                )

    def _guard(self, job):
        app = self.bacnet.require()
        adapter = app.nsap.local_adapter
        layer = adapter.clientPeer
        transport = getattr(getattr(layer, "server", None), "local_transport", None)
        if (
            self.closed
            or app is not job["app"]
            or self.bacnet.config != job["connector_config"]
            or adapter is not job["adapter"]
            or transport is not job["transport"]
            or transport is None
            or transport.is_closing()
            or transport.get_extra_info("sockname") != job["local_endpoint"]
        ):
            raise ValueError("Reception interface changed or closed; explicitly start again.")
        self._native_owner(app)

    @staticmethod
    def _native_owner(app):
        if any(
            getattr(app, name, None) is not None
            for name in (
                "do_ConfirmedEventNotificationRequest",
                "do_UnconfirmedEventNotificationRequest",
            )
        ):
            raise ValueError(
                "A native event-recipient handler owns this application; finite reception is refused without replacing it."
            )

    def _discard(self, job, reason, raw=None, packet=None):
        job["ignored"] += 1
        job["last_ignored"] = str(reason)[:500]
        if raw is not None:
            job["last_rejected"] = {
                "received_at": _utc(),
                "apdu_bytes": len(raw),
                "apdu_sha256": hashlib.sha256(raw).hexdigest(),
                "apdu_hex": raw[:MAX_APDU].hex(),
                "raw_complete": len(raw) <= MAX_APDU,
                "reason": str(reason)[:500],
                "next_hop": str(packet.pduSource) if packet else None,
                "npdu_source": remote_source(packet.npduSADR) if packet else None,
                "destination": str(packet.pduDestination) if packet else None,
            }

    def _install(self, app):
        if app in self.hooks:
            return
        original = app.nsap.process_npdu
        alive = {"value": True}

        async def receive(adapter, packet):
            if not alive["value"] or packet.npduNetMessage is not None:
                return await original(adapter, packet)
            header, process, device = _header(packet)
            if header is None:
                return await original(adapter, packet)
            candidates = [
                job
                for job in self.jobs.values()
                if job["active"]
                and job["app"] is app
                and job["config"].process_identifier == process
                and (
                    device is None
                    or device == ((8 << 22) | ObjectIdentifier(job["config"].device)[1])
                )
            ]
            if not candidates:
                return await original(adapter, packet)
            # Start forbids duplicate Device/process receivers; one owns this
            # identity without suppressing other native processes or Devices.
            job = candidates[0]
            if len(job["callbacks"]) >= MAX_CALLBACKS:
                self._discard(job, "Bounded callback capacity exceeded; no ACK sent.")
                return
            task = asyncio.current_task()
            job["callbacks"].add(task)
            try:
                return await self._receive(job, adapter, packet, header)
            finally:
                job["callbacks"].discard(task)

        previous_receiver = getattr(app.nsap, "_bms_event_receiver", None)

        def preserve(adapter, packet):
            return (
                alive["value"]
                and self._owns(app, adapter, packet)
                or bool(previous_receiver and previous_receiver(adapter, packet))
            )

        hook = ScopedAttribute(app.nsap, "process_npdu", receive)
        receiver = ScopedAttribute(app.nsap, "_bms_event_receiver", preserve)
        self.hooks[app] = (hook, receiver, alive)

    def _owns(self, app, adapter, packet):
        header, process, device = _header(packet)
        if header is None or getattr(header, "apduSeg", False):
            return False
        for job in self.jobs.values():
            config = job["config"]
            if (
                job["app"] is app
                and job["active"]
                and adapter is job["adapter"]
                and config.router is not None
                and config.process_identifier == process
                and device == ((8 << 22) | ObjectIdentifier(config.device)[1])
                and config.router == str(packet.pduSource)
                and config.address == remote_source(packet.npduSADR)
            ):
                try:
                    self._guard(job)
                except ValueError:
                    return False
                return True
        return False

    def _retire(self, app):
        if any(j["active"] and j["app"] is app for j in self.jobs.values()):
            return
        saved = self.hooks.pop(app, None)
        if saved:
            hook, receiver, alive = saved
            alive["value"] = False
            receiver.close()
            hook.close()

    async def _receive(self, job, adapter, packet, header):
        raw = bytes(packet.pduData)
        config = job["config"]
        try:
            self._guard(job)
            direct = (
                adapter is job["adapter"]
                and isinstance(packet.pduDestination, IPv4Address)
                and packet.pduDestination.addrTuple == job["local_endpoint"]
            )
            source = remote_source(packet.npduSADR)
            expected_peer = config.router or config.address
            if (
                not job["active"]
                or self.clock() >= job["expires"]
                or not direct
                or packet.npduDADR is not None
                or str(packet.pduSource) != expected_peer
                or (source != config.address if config.router else packet.npduSADR is not None)
                or getattr(header, "apduSeg", False)
                or getattr(header, "apduMor", False)
                or len(raw) > MAX_APDU
                or config.mode != "both"
                and (header.apduType == 0) != (config.mode == "confirmed")
            ):
                raise ValueError("Notification route/source/mode/finite-session profile mismatch.")
            value, native, decode_error = _decode(header)
            if (
                value.initiatingDeviceIdentifier != ObjectIdentifier(config.device)
                or value.processIdentifier != config.process_identifier
                or config.object_id is not None
                and value.eventObjectIdentifier != ObjectIdentifier(config.object_id)
            ):
                raise ValueError("Notification Device/process/object filter mismatch.")
            row = {
                "sequence": job["received"] + 1,
                "received_at": _utc(),
                "source_clock_utc": None,
                "source_clock_status": "Raw event TimeStamp; source timezone/clock and sequence meaning unresolved.",
                "source": config.address,
                "next_hop": str(packet.pduSource),
                "router": config.router,
                "dnet": config.dnet,
                "local_endpoint": list(job["local_endpoint"]),
                "npdu_source": source,
                "network_priority": int(packet.pduNetworkPriority),
                "process_identifier": int(value.processIdentifier),
                "device": str(value.initiatingDeviceIdentifier),
                "event_object": str(value.eventObjectIdentifier),
                "timestamp": json_value(value.timeStamp),
                "notification_class": int(value.notificationClass),
                "priority": int(value.priority),
                "event_type": _enum(value.eventType),
                "notify_type": _enum(value.notifyType),
                "from_state": _enum(value.fromState),
                "to_state": _enum(value.toState),
                "ack_required": None if value.ackRequired is None else bool(value.ackRequired),
                "message_text": None if value.messageText is None else str(value.messageText),
                "confirmed": header.apduType == 0,
                "invoke_id": getattr(header, "apduInvokeID", None),
                "event_values": json_value(native.eventValues)
                if native is not None
                else json_value(value.eventValues),
                "event_values_decode_status": "decoded" if native is not None else "opaque",
                "event_values_decode_error": decode_error,
                "quality": "unknown",
                "protocol_ack": "not-applicable" if header.apduType == 1 else "not-sent",
                "operator_acknowledged": None,
                "apdu_hex": raw.hex(),
                "apdu_bytes": len(raw),
                "apdu_sha256": hashlib.sha256(raw).hexdigest(),
                "raw_complete": True,
                "possible_duplicate": any(
                    event["apdu_sha256"] == hashlib.sha256(raw).hexdigest()
                    for event in job["events"]
                ),
            }
            if len(json.dumps(row, allow_nan=False).encode()) > MAX_EVENT_BYTES:
                raise ValueError("Notification exceeds the 16 KiB retained-event budget.")
            if len(job["events"]) == MAX_EVENTS:
                job["evicted"] += 1
            job["received"] += 1
            job["events"].append(row)
        except Exception as exc:
            self._discard(job, exc, raw, packet)
            return
        if header.apduType == 0:
            # The APDU invoke ID is echoed only after accepted receipt. Dispatch
            # straight to the verified local adapter, with explicit DADR/next hop;
            # route-cache changes or other tasks' scoped paths cannot redirect it.
            outgoing = NPDU(
                bytes((0x20, header.apduInvokeID, 2)), destination=Address(expected_peer)
            )
            outgoing.pduNetworkPriority = packet.pduNetworkPriority
            if config.router:
                outgoing.npduDADR = Address(config.address)
                outgoing.npduHopCount = 255
            try:
                self._guard(job)
                await asyncio.wait_for(job["adapter"].process_npdu(outgoing), 0.5)
                row["protocol_ack"] = "dispatch-returned-reception-only"
            except (Exception, asyncio.CancelledError) as exc:
                row["protocol_ack"] = "unknown"
                row["protocol_ack_error"] = str(exc)[:500] or type(exc).__name__
                job["ack_failures"] += 1
                if isinstance(exc, asyncio.CancelledError):
                    raise

    def _finish(self, job, state, reason):
        job.update(active=False, state=state, reason=str(reason)[:500], ended_at=_utc())
        self._retire(job["app"])
        for callback in job["callbacks"]:
            if callback is not asyncio.current_task():
                callback.cancel()

    async def _join_callbacks(self, job):
        await asyncio.gather(
            *(callback for callback in job["callbacks"] if callback is not asyncio.current_task()),
            return_exceptions=True,
        )

    async def _watch(self, job):
        try:
            while job["active"]:
                self._guard(job)
                if self.clock() >= job["expires"]:
                    self._finish(
                        job, "expired", "Finite listen window elapsed; no automatic restart."
                    )
                    await self._join_callbacks(job)
                    return
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self._finish(job, "interface_changed", exc)
            await self._join_callbacks(job)

    async def start(self, **arguments):
        operation = asyncio.current_task()
        self.operations.add(operation)
        try:
            config = EventListenStart(**arguments)
            async with self.lock:
                if self.closed:
                    raise ValueError("Event reception is closed.")
                if sum(j["active"] for j in self.jobs.values()) >= MAX_ACTIVE:
                    raise ValueError("At most eight active event listeners are supported.")
                if any(
                    j["active"]
                    and j["config"].device == config.device
                    and j["config"].process_identifier == config.process_identifier
                    for j in self.jobs.values()
                ):
                    raise ValueError(
                        "Device/process already has an active receiver; stop it first."
                    )
                await asyncio.wait_for(self.bacnet.lock.acquire(), 3)
                try:
                    app = self.bacnet.require()
                    self._native_owner(app)
                    connector = copy.deepcopy(self.bacnet.config)
                    adapter = app.nsap.local_adapter
                    if connector.get("transport") == "mstp" or connector.get("bbmd_address"):
                        raise ValueError(
                            "Event reception requires plain IPv4, without BBMD or serial."
                        )
                    layer = adapter.clientPeer
                    transport = layer.server.local_transport
                    job = {
                        "id": "listen-" + secrets.token_hex(12),
                        "config": config,
                        "connector_config": connector,
                        "app": app,
                        "adapter": adapter,
                        "transport": transport,
                        "local_endpoint": transport.get_extra_info("sockname"),
                        "active": False,
                        "received": 0,
                        "ignored": 0,
                        "evicted": 0,
                        "ack_failures": 0,
                        "events": deque(maxlen=MAX_EVENTS),
                        "callbacks": set(),
                        "started_at": _utc(),
                        "identity_verification": [],
                    }
                    async with asyncio.timeout(10):
                        async with DeviceDetails(self.bacnet, self.store)._path(
                            DeviceDetailsRequest(
                                address=config.address,
                                device=config.device,
                                router=config.router,
                                dnet=config.dnet,
                            ),
                            lock_held=True,
                        ) as path:
                            for identifier in (config.device, config.object_id):
                                if identifier is None:
                                    continue
                                self._guard(job)
                                actual = await asyncio.wait_for(
                                    read_property(
                                        app, path["target"], identifier, "object-identifier"
                                    ),
                                    self.timeout,
                                )
                                self._guard(job)
                                if actual != ObjectIdentifier(identifier):
                                    raise ValueError(
                                        "Selected Device/object identity differs from readback."
                                    )
                                job["identity_verification"].append(
                                    {
                                        "requested": identifier,
                                        "readback": str(actual),
                                        "received_at": _utc(),
                                        "status": "verified",
                                    }
                                )
                    while len(self.jobs) >= MAX_JOBS:
                        retired = next(
                            (key for key, old in self.jobs.items() if not old["active"]), None
                        )
                        if retired is None:
                            raise ValueError("Event listener history capacity is full.")
                        del self.jobs[retired]
                        self.evicted += 1
                    job.update(
                        active=True,
                        state="listening",
                        expires=self.clock() + config.duration_seconds,
                    )
                    self.jobs[job["id"]] = job
                    self._install(app)
                    job["task"] = asyncio.create_task(
                        self._watch(job), name="bms-event-" + job["id"]
                    )
                    return self.detail(job["id"])
                finally:
                    self.bacnet.lock.release()
        finally:
            self.operations.discard(operation)

    def detail(self, identifier, limit=None):
        if identifier not in self.jobs:
            raise ValueError("Event listen session not found; export before restart or eviction.")
        job = self.jobs[identifier]
        hidden = {"app", "adapter", "transport", "task", "config", "events", "expires", "callbacks"}
        events = list(job["events"])
        return {key: copy.deepcopy(value) for key, value in job.items() if key not in hidden} | {
            "profile": PROFILE,
            "config": job["config"].model_dump(),
            "seconds_remaining": max(0, round(job["expires"] - self.clock(), 2))
            if job["active"]
            else 0,
            "events_retained": len(events),
            "pending_callbacks": len(job["callbacks"]),
            "events": copy.deepcopy(events if limit is None else events[-limit:] if limit else []),
            "scope": SCOPE,
        }

    def status(self):
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "auto_listen": False,
            "auto_subscribe": False,
            "maximum_active": MAX_ACTIVE,
            "maximum_sessions": MAX_JOBS,
            "maximum_events": MAX_EVENTS,
            "maximum_apdu_bytes": MAX_APDU,
            "maximum_event_bytes": MAX_EVENT_BYTES,
            "maximum_callbacks_per_session": MAX_CALLBACKS,
            "sessions_evicted": self.evicted,
            "sessions": [self.detail(key, limit=3) for key in self.jobs],
        }

    async def stop(self, identifier):
        async with self.lock:
            if identifier not in self.jobs:
                raise ValueError("Event listen session not found.")
            job = self.jobs[identifier]
            if job["active"]:
                self._finish(
                    job, "stopped", "Stopped explicitly; no recipient/device state was changed."
                )
            job["task"].cancel()
            await asyncio.gather(job["task"], return_exceptions=True)
            await self._join_callbacks(job)
            return self.detail(identifier)

    def _saved(self, identifier):
        if self.store is None:
            raise ValueError("Saved event-reception evidence is unavailable.")
        with closing(self.store.connect(timeout=0.2)) as db:
            row = db.execute(
                "SELECT created,sha256,CASE WHEN length(CAST(body AS BLOB))<=? THEN body ELSE NULL END AS body FROM event_reception_snapshots WHERE id=?",
                (MAX_SNAPSHOT_BYTES, identifier),
            ).fetchone()
        if row is None:
            raise ValueError("Saved event listen snapshot not found.")
        if row["body"] is None or hashlib.sha256(row["body"].encode()).hexdigest() != row["sha256"]:
            raise ValueError("Saved event snapshot exceeds bounds or fails its integrity check.")
        report = json.loads(row["body"])
        if (
            report.get("id") != identifier
            or report.get("active") is not False
            or report.get("profile") != PROFILE
        ):
            raise ValueError("Saved event snapshot identity/state is invalid.")
        return report | {
            "saved_sha256": row["sha256"],
            "saved_at": row["created"],
            "auto_resume": False,
        }

    def snapshots(self):
        if self.store is None:
            return []
        with closing(self.store.connect(timeout=0.2)) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,created,sha256,length(CAST(body AS BLOB)) AS bytes FROM event_reception_snapshots ORDER BY created DESC LIMIT ?",
                    (MAX_SNAPSHOTS,),
                )
            ]

    def saved(self, identifier):
        return self._saved(identifier)

    def _save(self, report):
        body = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(body.encode()) > MAX_SNAPSHOT_BYTES:
            raise ValueError("Event listen snapshot exceeds its 2 MiB profile.")
        with closing(self.store.connect(timeout=0.2)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM event_reception_snapshots WHERE id=?", (report["id"],)
            ).fetchone():
                return self._saved(report["id"])
            if (
                db.execute("SELECT COUNT(*) FROM event_reception_snapshots").fetchone()[0]
                >= MAX_SNAPSHOTS
            ):
                raise ValueError(
                    "Saved event snapshot capacity reached; no existing evidence deleted."
                )
            db.execute(
                "INSERT INTO event_reception_snapshots(id,created,body,sha256) VALUES(?,?,?,?)",
                (report["id"], _utc(), body, hashlib.sha256(body.encode()).hexdigest()),
            )
        return self._saved(report["id"])

    async def save(self, identifier):
        if self.closed or self.store is None:
            raise ValueError("Saved event-reception evidence is unavailable or closed.")
        operation = asyncio.current_task()
        self.operations.add(operation)
        try:
            report = self.detail(identifier)
            if report["active"] or report["pending_callbacks"]:
                raise ValueError(
                    "Stop the listener and join callbacks before saving its final snapshot."
                )
            writer = asyncio.create_task(
                asyncio.to_thread(self._save, report), name="event-snapshot-writer"
            )
            cancelled = False
            while True:
                try:
                    await asyncio.shield(writer)
                    break
                except asyncio.CancelledError:
                    cancelled = True
                    if writer.done():
                        break
                except Exception:
                    if not cancelled:
                        raise
                    break
            if cancelled:
                if not writer.cancelled():
                    writer.exception()
                raise asyncio.CancelledError
            return writer.result()
        finally:
            self.operations.discard(operation)

    async def close(self):
        self.closed = True
        pending = [task for task in self.operations if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for key in list(self.jobs):
            await self.stop(key)
