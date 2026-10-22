"""Owned finite SubscribeCOV monitoring on direct or explicitly routed BACnet/IPv4.

No automatic renewal, reconnection, discovery, point writes, or native program
services. Notifications are evidence of receipt, not independent sensor quality.
"""

from __future__ import annotations

import asyncio
import copy
import json
import secrets
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from bacpypes3.apdu import (
    APDU,
    ErrorRejectAbortNack,
    SimpleAckPDU,
    SubscribeCOVRequest,
)
from bacpypes3.constructeddata import Array
from bacpypes3.errors import ServicesError
from bacpypes3.pdu import PDU, Address
from bacpypes3.primitivedata import Atomic, ObjectIdentifier, Unsigned
from pydantic import Field, field_validator, model_validator

from .bacnet_exchange import confirmed_exchange
from .bacnet_read import read_property
from .bacnet_values import json_value
from .connections import _unicast
from .cov_route import CovRouteEvidence, CovRouteHooks, remote_source
from .device_details import DeviceDetails, DeviceDetailsRequest
from .models import StrictModel

PROFILE = "explicit-ip-routed-object-cov/2"
SCOPE = (
    "Direct BACnet/IPv4 or explicit IPv4-router/DNET:MAC object-level SubscribeCOV. "
    "Routed notifications must be unsegmented. Existing connected IPv4 interface; "
    "no BBMD, serial, BTCVT, automatic renewal or reconnection. "
    "No point values or controller programs are changed. Physical JCI acceptance is unverified."
)
MAX_ACTIVE = 8
MAX_JOBS = 32
MAX_EVENTS = 100
MAX_EVENT_BYTES = 16384
_MISSING = object()


@dataclass(frozen=True)
class _Transport:
    owner: object
    direct_unicast: bool
    previous_user_data: object
    route: CovRouteEvidence | None = None


def _utc():
    return datetime.now(UTC).isoformat()


class CovStart(StrictModel):
    address: str = Field(min_length=1, max_length=100)
    device: str = Field(min_length=1, max_length=100)
    object_id: str = Field(min_length=1, max_length=100)
    lifetime: int = Field(default=60, ge=5, le=3600, strict=True)
    confirmed: bool = Field(default=True, strict=True)
    router: str | None = Field(default=None, min_length=1, max_length=64)
    dnet: int | None = Field(default=None, ge=1, le=65534, strict=True)
    record_observations: bool = Field(default=False, strict=True)

    @field_validator("device", "object_id")
    @classmethod
    def identifier(cls, value):
        obj = ObjectIdentifier(value)
        if not 0 <= obj[1] <= 4194302:
            raise ValueError(
                "Select an explicit object instance; wildcard identity is unsupported."
            )
        return str(obj)

    @field_validator("device")
    @classmethod
    def device_identifier(cls, value):
        if int(ObjectIdentifier(value)[0]) != 8:
            raise ValueError("Expected Device identity must be a Device object.")
        return value

    @model_validator(mode="after")
    def exact_path(self):
        path = DeviceDetailsRequest(
            address=self.address, device=self.device, router=self.router, dnet=self.dnet
        )
        if path.router is not None and Address(path.address).addrLen != 1:
            raise ValueError("The routed COV profile requires a one-byte MS/TP MAC.")
        self.address, self.router, self.dnet = path.address, path.router, path.dnet
        return self


class CovAction(StrictModel):
    id: str = Field(min_length=1, max_length=80)


class BacnetCov:
    def __init__(self, bacnet, store=None, *, timeout=3.0, clock=None, recorder=None):
        if type(timeout) not in (int, float) or not 0.01 <= timeout <= 6:
            raise ValueError("COV exchange timeout must be 0.01..6 seconds.")
        self.bacnet, self.store, self.timeout = bacnet, store, timeout
        self.clock = clock or (lambda: asyncio.get_running_loop().time())
        self.jobs = {}
        self._lock = asyncio.Lock()
        self._hooks = {}
        self._transport_hooks = {}
        self._route_hooks = {}
        self._provenance_owner = object()
        self._closed = False
        self._evicted = 0
        self.recorder = recorder

    def _discard(self, job, reason):
        job["ignored"] += 1
        job["last_ignored"] = str(reason)[:500]
        if self.recorder is not None:
            self.recorder.discarded(job.get("recording"), reason)

    def _guard(self, job):
        status = self.bacnet.status()
        if (
            not status["connected"]
            or self.bacnet.app is not job["app"]
            or status["config"] != job["connector_config"]
        ):
            raise ValueError("BACnet interface changed or closed; monitoring will not reconnect.")
        self.bacnet.require()

    def _audit(self, action, job):
        if self.recorder is not None and action in {"started", "renewed"}:
            self.recorder.submit(
                job.get("recording"),
                action,
                {
                    "received_at": _utc(),
                    "state": job["state"],
                    "remote_outcome": job["remote_outcome"],
                },
            )
        if self.store is not None:
            try:
                detail = self._view(job, limit=0)
                del detail["events"]
                self.store.record("bacnet.cov." + action, detail)
            except Exception as exc:
                job["audit_error"] = str(exc)[:500]

    def _install(self, app):
        if app in self._hooks:
            return
        hooks = {}
        for confirmed, name in (
            (True, "do_ConfirmedCOVNotificationRequest"),
            (False, "do_UnconfirmedCOVNotificationRequest"),
        ):
            previous = app.__dict__.get(name, _MISSING)
            original = getattr(app, name)

            async def receive(apdu, *, mode=confirmed, fallback=original):
                provenance = apdu.pduUserData
                direct = (
                    isinstance(provenance, _Transport)
                    and provenance.owner is self._provenance_owner
                )
                if direct:
                    apdu.pduUserData = provenance.previous_user_data
                    direct = provenance.direct_unicast
                own = next(
                    (
                        job
                        for job in self.jobs.values()
                        if job["app"] is app
                        and job["process_id"] == apdu.subscriberProcessIdentifier
                        and job["active"]
                    ),
                    None,
                )
                if own is None:
                    return await fallback(apdu)
                await self._receive(
                    own,
                    apdu,
                    mode,
                    direct=direct,
                    route=provenance.route if isinstance(provenance, _Transport) else None,
                )

            hooks[name] = (previous, receive)
            setattr(app, name, receive)
        self._hooks[app] = hooks
        # ServerSSM clears a confirmed request's destination before invoking
        # the application. Carry only the direct-unicast transport provenance
        # through its existing user-data channel, restoring the prior value
        # before either our handler or another subscription sees the APDU.
        service = app.asap
        previous = service.__dict__.get("confirmation", _MISSING)
        original = service.confirmation
        enabled = {"value": True}

        async def transport(packet):
            if enabled["value"]:
                try:
                    header = APDU.decode(PDU(bytes(packet.pduData)))
                    cov = (header.apduType, header.apduService) in {(0, 1), (1, 2)}
                except Exception:
                    cov = False
                if cov:
                    path = packet.pduUserData
                    route = (
                        path
                        if isinstance(path, CovRouteEvidence)
                        and path.owner is self._provenance_owner
                        else None
                    )
                    packet.pduUserData = _Transport(
                        self._provenance_owner,
                        route.direct_unicast
                        if route
                        else getattr(packet.pduDestination, "addrType", None)
                        == Address.localStationAddr,
                        route.previous_user_data if route else packet.pduUserData,
                        route,
                    )
            await original(packet)

        service.confirmation = transport
        self._transport_hooks[app] = (service, previous, transport, enabled)
        self._route_hooks[app] = CovRouteHooks(
            app, self._provenance_owner, lambda: self.jobs.values(), self._guard, self._discard
        )

    def _restore(self, app):
        if any(job["active"] and job["app"] is app for job in self.jobs.values()):
            return
        for name, (previous, wrapper) in self._hooks.pop(app, {}).items():
            if app.__dict__.get(name) is wrapper:
                if previous is _MISSING:
                    delattr(app, name)
                else:
                    setattr(app, name, previous)
        hook = self._transport_hooks.pop(app, None)
        if hook is not None:
            service, previous, wrapper, enabled = hook
            enabled["value"] = False
            if service.__dict__.get("confirmation") is wrapper:
                if previous is _MISSING:
                    delattr(service, "confirmation")
                else:
                    service.confirmation = previous
        route = self._route_hooks.pop(app, None)
        if route is not None:
            route.close()

    def _decode(self, job, item):
        prop = item.propertyIdentifier
        raw = json_value(item.value)
        datatype = job["object_class"].get_property_type(prop) if job["object_class"] else None
        row = {
            "property": str(prop),
            "property_id": int(prop),
            "array_index": int(item.propertyArrayIndex)
            if item.propertyArrayIndex is not None
            else None,
            "priority": int(item.priority) if item.priority is not None else None,
            "encoded_value": raw,
            "value": raw,
            "decode_status": "opaque",
        }
        if datatype is not None:
            try:
                if issubclass(datatype, Array) and item.propertyArrayIndex is not None:
                    datatype = Unsigned if item.propertyArrayIndex == 0 else datatype._subtype
                value = item.value.cast_out(datatype, null=issubclass(datatype, Atomic))
                row.update(
                    value=json_value(value),
                    decode_status="decoded",
                    native_datatype=datatype.__name__,
                )
            except Exception as exc:
                row.update(decode_status="decode_error", decode_error=str(exc)[:500])
        return row

    async def _receive(self, job, apdu, confirmed, *, direct=None, route=None):
        try:
            self._guard(job)
            if direct is None:
                direct = getattr(apdu.pduDestination, "addrType", None) == Address.localStationAddr
            if job["config"].router is not None and (
                route is None
                or route.next_hop != job["config"].router
                or route.remote_source != job["config"].address
                or route.segmented
            ):
                raise ValueError(
                    "Routed notification provenance differs from the pinned router/DNET:MAC."
                )
            if (
                not job["active"]
                or self.clock() >= job["expires"]
                or apdu.subscriberProcessIdentifier != job["process_id"]
                or (
                    remote_source(apdu.pduSource) != job["config"].address
                    if job["config"].router
                    else apdu.pduSource != job["target"]
                )
                or not direct
                or apdu.initiatingDeviceIdentifier != ObjectIdentifier(job["config"].device)
                or apdu.monitoredObjectIdentifier != ObjectIdentifier(job["config"].object_id)
                or confirmed != job["config"].confirmed
                or not 0 <= apdu.timeRemaining <= 3600
            ):
                raise ValueError("Notification identity, confirmation mode, or lease mismatch.")
            if not 1 <= len(apdu.listOfValues) <= 32:
                raise ValueError("Notification must contain 1..32 properties.")
            row = {
                "sequence": job["received"] + 1,
                "received_at": _utc(),
                "source": str(apdu.pduSource),
                "device": str(apdu.initiatingDeviceIdentifier),
                "object": str(apdu.monitoredObjectIdentifier),
                "process_id": int(apdu.subscriberProcessIdentifier),
                "confirmed": confirmed,
                "route": {
                    "router": job["config"].router,
                    "dnet": job["config"].dnet,
                    "next_hop": route.next_hop if route else str(apdu.pduSource),
                    "source": route.remote_source if route else None,
                },
                "receive_provenance": route.receive_provenance if route else None,
                "time_remaining": int(apdu.timeRemaining),
                "quality": "Not independently assessed; inspect received status-flags/reliability.",
                "values": [self._decode(job, value) for value in apdu.listOfValues],
            }
            if len(json.dumps(row, allow_nan=False).encode()) > MAX_EVENT_BYTES:
                raise ValueError("Notification exceeds the 16 KiB evidence budget.")
            job["received"] += 1
            if len(job["events"]) == MAX_EVENTS:
                job["dropped"] += 1
            job["events"].append(row)
            if self.recorder is not None:
                self.recorder.submit(job.get("recording"), "notification", row)
        except Exception as exc:
            self._discard(job, exc)
            if confirmed:
                raise ServicesError(errorCode="unknownSubscription") from exc
            return
        if confirmed:
            await job["app"].response(SimpleAckPDU(context=apdu))

    def _path(self, config):
        app = self.bacnet.require()
        route = self._route_hooks.get(app)
        options = DeviceDetailsRequest(
            address=config.address, device=config.device, router=config.router, dnet=config.dnet
        )
        return DeviceDetails(self.bacnet, self.store)._path(
            options, lock_held=True, preserve_packet=route.owns if route else None
        )

    async def _exchange(self, job, cancel=False):
        async with self._path(job["config"]):
            return await self._pinned_exchange(job, cancel)

    async def _pinned_exchange(self, job, cancel=False):
        self._guard(job)
        fields = (
            {}
            if cancel
            else {
                "issueConfirmedNotifications": job["config"].confirmed,
                "lifetime": job["config"].lifetime,
            }
        )
        request = SubscribeCOVRequest(
            subscriberProcessIdentifier=job["process_id"],
            monitoredObjectIdentifier=ObjectIdentifier(job["config"].object_id),
            destination=job["target"],
            **fields,
        )
        try:
            reply = await asyncio.wait_for(confirmed_exchange(job["app"], request), self.timeout)
        except ErrorRejectAbortNack as exc:
            raise ValueError("COV service rejected: " + str(exc)) from exc
        self._guard(job)
        if isinstance(reply, ErrorRejectAbortNack):
            raise ValueError("COV service rejected: " + str(reply))
        if (
            not isinstance(reply, SimpleAckPDU)
            or reply.pduSource != job["target"]
            or reply.apduService != SubscribeCOVRequest.service_choice
        ):
            raise ValueError("COV acknowledgement source/service mismatch.")

    def _finish(self, job, state, reason, outcome):
        job.update(
            active=False, state=state, reason=reason, remote_outcome=outcome, ended_at=_utc()
        )
        task = job.get("task")
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        self._restore(job["app"])
        if self.recorder is not None:
            self.recorder.end(
                job.get("recording"),
                {
                    "received_at": _utc(),
                    "state": state,
                    "reason": reason,
                    "remote_outcome": outcome,
                    "notifications_received": job["received"],
                    "notifications_ignored": job["ignored"],
                },
            )
        self._audit(state, job)

    async def _watch(self, job):
        try:
            while job["active"]:
                # An explicit renewal owns the lifecycle lock through its ACK
                # or timeout. Do not retire a lease halfway through that action.
                async with self._lock:
                    if not job["active"]:
                        return
                    self._guard(job)
                    if self.clock() >= job["expires"]:
                        self._finish(
                            job,
                            "expired",
                            "Finite lease elapsed; renewal requires an explicit action.",
                            "Lease elapsed locally; remote expiration is not independently read back.",
                        )
                        return
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self._finish(
                job,
                "interface_changed",
                str(exc),
                "Not cancelled remotely; finite lease may remain.",
            )

    async def start(self, **arguments):
        config = CovStart(**arguments)
        async with self._lock, self.bacnet.lock:
            if self._closed:
                raise ValueError("COV manager is closed.")
            if config.record_observations and self.recorder is None:
                raise ValueError("Durable COV recording is unavailable in this service.")
            if sum(job["active"] for job in self.jobs.values()) >= MAX_ACTIVE:
                raise ValueError("At most eight active COV monitors are supported.")
            app = self.bacnet.require()
            interface = copy.deepcopy(self.bacnet.status()["config"])
            if interface.get("transport") == "mstp" or interface.get("bbmd_address") is not None:
                raise ValueError(
                    "This COV profile requires BACnet/IPv4 without BBMD or direct serial."
                )
            job = {
                "id": "cov-" + secrets.token_hex(12),
                "config": config,
                "app": app,
                "connector_config": interface,
                "target": _unicast(config.address),
                "active": False,
                "state": "verifying",
                "received": 0,
                "ignored": 0,
                "dropped": 0,
                "events": deque(maxlen=MAX_EVENTS),
                "started_at": _utc(),
                "remote_outcome": "No subscription requested.",
                "reason": "",
                "expires": 0,
            }
            self._install(app)
            try:
                async with self._path(config):
                    for identifier in (config.device, config.object_id):
                        self._guard(job)
                        identity = await asyncio.wait_for(
                            read_property(app, job["target"], identifier, "object-identifier"),
                            self.timeout,
                        )
                        self._guard(job)
                        if identity != ObjectIdentifier(identifier):
                            raise ValueError(
                                "Selected Device or monitored object identity differs from its readback."
                            )
                    vendor = await asyncio.wait_for(
                        app.get_vendor_info(device_address=job["target"]), self.timeout
                    )
                    job["object_class"] = vendor.get_object_class(
                        ObjectIdentifier(config.object_id)[0]
                    )
            except BaseException:
                self._restore(app)
                raise
            used = {value["process_id"] for value in self.jobs.values()}
            used.update(key[1] for key in app._cov_contexts)
            process = secrets.randbelow(2**32 - 1) + 1
            while process in used:
                process = (process + 1) % 2**32
            job.update(
                process_id=process,
                active=True,
                state="subscribing",
                expires=self.clock() + config.lifetime,
            )
            while len(self.jobs) >= MAX_JOBS:
                retired = next(
                    (key for key, value in self.jobs.items() if not value["active"]), None
                )
                if retired is None:
                    raise ValueError("COV history capacity is full.")
                del self.jobs[retired]
                self._evicted += 1
            self.jobs[job["id"]] = job
            self._install(app)
            try:
                if config.record_observations:
                    job["recording"] = await self.recorder.begin(job)
                await self._exchange(job)
                job.update(
                    state="active",
                    expires=self.clock() + config.lifetime,
                    remote_outcome="SubscribeCOV acknowledged.",
                )
                job["task"] = asyncio.create_task(self._watch(job), name="bms-cov-" + job["id"])
            except BaseException as exc:
                self._finish(
                    job,
                    "failed",
                    str(exc) or type(exc).__name__,
                    "Subscription outcome uncertain; requested finite lease bounds remote retention.",
                )
                raise
            self._audit("started", job)
            return self._view(job)

    def _job(self, identifier):
        if identifier not in self.jobs:
            raise ValueError("COV monitor not found; monitors never resume after restart.")
        return self.jobs[identifier]

    async def renew(self, identifier):
        async with self._lock, self.bacnet.lock:
            job = self._job(identifier)
            if not job["active"] or self.clock() >= job["expires"]:
                raise ValueError("COV lease is inactive or expired; start a new verified monitor.")
            try:
                await self._exchange(job)
                job.update(
                    expires=self.clock() + job["config"].lifetime,
                    remote_outcome="Explicit renewal acknowledged.",
                )
            except BaseException as exc:
                self._finish(
                    job,
                    "failed",
                    str(exc) or type(exc).__name__,
                    "Renewal outcome uncertain; a finite remote lease may remain.",
                )
                raise
            self._audit("renewed", job)
            return self._view(job)

    async def stop(self, identifier):
        async with self._lock, self.bacnet.lock:
            job = self._job(identifier)
            if job["active"]:
                try:
                    await self._exchange(job, cancel=True)
                    self._finish(
                        job, "stopped", "Stopped explicitly.", "Cancellation acknowledged."
                    )
                except (Exception, asyncio.CancelledError) as exc:
                    self._finish(
                        job,
                        "stopped_uncertain",
                        str(exc) or type(exc).__name__,
                        "Local capture stopped; remote cancellation unconfirmed, finite lease may remain.",
                    )
                    if isinstance(exc, asyncio.CancelledError):
                        raise
            task = job.get("task")
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            return self._view(job)

    def _view(self, job, limit=None):
        events = list(job["events"])
        if limit is not None:
            events = events[-limit:] if limit else []
        return {
            key: copy.deepcopy(value)
            for key, value in job.items()
            if key not in {"app", "target", "task", "events", "object_class", "expires", "config"}
        } | {
            "config": job["config"].model_dump(),
            "lease_seconds_remaining": max(0, round(job["expires"] - self.clock(), 2))
            if job["active"]
            else 0,
            "events_retained": len(job["events"]),
            "events": copy.deepcopy(events),
        }

    def status(self):
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "auto_renew": False,
            "auto_reconnect": False,
            "maximum_active": MAX_ACTIVE,
            "maximum_retained_jobs": MAX_JOBS,
            "maximum_events_per_job": MAX_EVENTS,
            "maximum_event_bytes": MAX_EVENT_BYTES,
            "retired_jobs_evicted": self._evicted,
            "jobs": [self._view(job, limit=3) for job in self.jobs.values()],
        }

    def detail(self, identifier):
        return self._view(self._job(identifier))

    async def close(self):
        async with self._lock:
            self._closed = True
            identifiers = list(self.jobs)
        for identifier in identifiers:
            await self.stop(identifier)
        if self.recorder is not None:
            await self.recorder.close()
