"""Reviewed, single-attempt Device.Object_Identifier commissioning.

The station (IPv4 endpoint or router/DNET/MAC) is the target, never a device-ID
cache lookup. No priority, reset, vendor-private command, retry or rollback is
part of this profile. A journalled intent without a result remains uncertain.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import secrets
import sqlite3
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from bacpypes3.apdu import (
    ErrorPDU,
    ErrorRejectAbortNack,
    RejectPDU,
    SimpleAckPDU,
    WritePropertyRequest,
)
from bacpypes3.pdu import Address, IPv4Address
from bacpypes3.primitivedata import ObjectIdentifier
from fastapi import APIRouter
from pydantic import Field, StrictBool

from .bacnet_exchange import confirmed_exchange
from .device_details import DeviceDetails, DeviceDetailsRequest
from .ip_discovery import IpDiscovery
from .models import StrictModel
from .routed_discovery import RoutedDiscovery

PROFILE = "bacnet-device-instance-commissioning/1"
PLAN_SECONDS = 60
MAX_RECORDS = 1024
RECORD_BYTES = 32768
IDENTITY_FIELDS = (
    "object-name",
    "vendor-identifier",
    "model-name",
    "firmware-revision",
    "application-software-version",
)
SCOPE = (
    "Standard BACnet WriteProperty of the selected controller's Device.object-identifier. "
    "Requires controller support; a read-only property requires the manufacturer's commissioning tool. "
    "Does not change the client instance, MAC, DNET, application, or supervisor references."
)


def utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def seal(value):
    value = copy.deepcopy(value)
    value.pop("evidence_sha256", None)
    return {**value, "evidence_sha256": sha(value)}


def station_key(target):
    """Conservative BACnet station identity, independent of a routed next hop.

    Receipts retain their exact router. Ambiguous reused network numbers remain
    blocked until the original uncertain attempt is explicitly resolved.
    """
    if type(target) is not dict or set(target) != {"address", "router", "dnet"}:
        raise ValueError("Invalid retained device-instance target.")
    options = DeviceDetailsRequest(**target, device="device,0")
    address = Address(options.address)
    if options.router is not None:
        return ("routed", options.dnet, bytes(address.addrAddr).hex())
    return ("ipv4", *IPv4Address(options.address).addrTuple)


class InstancePreview(DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    new_instance: int = Field(ge=0, le=4194302, strict=True)


class InstanceApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    allocation_confirmed: StrictBool


class InstanceCancel(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class InstanceReconcile(InstanceCancel):
    receipt_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class InstanceJournal:
    """Immutable intent/result and append-only readbacks, retained across restarts."""

    def __init__(self, store):
        self.store = store
        with store.connect(timeout=0.25) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS device_instance_changes("
                "id TEXT PRIMARY KEY, intent BLOB, result BLOB, created TEXT NOT NULL, "
                "station_key TEXT NOT NULL, unresolved INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS device_instance_station_pending "
                "ON device_instance_changes(station_key) WHERE unresolved=1"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS device_instance_readbacks("
                "sequence INTEGER PRIMARY KEY, receipt_id TEXT NOT NULL, body BLOB NOT NULL)"
            )

    @staticmethod
    def _raw(value):
        raw = encoded(seal(value))
        if len(raw) > RECORD_BYTES:
            raise ValueError("Device-instance evidence exceeds its record budget.")
        return raw

    @staticmethod
    def _checked(raw):
        if not raw or len(raw) > RECORD_BYTES:
            raise ValueError("Invalid device-instance journal record size.")
        value = json.loads(raw)
        digest = value.pop("evidence_sha256", None)
        if digest != sha(value) or value.get("profile") != PROFILE:
            raise ValueError("Device-instance journal integrity check failed.")
        return {**value, "evidence_sha256": digest}

    def intent(self, receipt):
        raw = self._raw(
            {
                **receipt,
                "status": "unknown",
                "may_have_applied": True,
                "dispatch_started": None,
                "journal_state": "intent_only",
            }
        )
        with self.store.connect(timeout=0.25) as db:
            db.execute("BEGIN IMMEDIATE")
            key = station_key(receipt["target"])
            for previous in db.execute(
                "SELECT intent,result FROM device_instance_changes WHERE unresolved=1"
            ):
                raw = previous[1] if previous[1] is not None else previous[0]
                if station_key(self._checked(raw)["target"]) == key:
                    raise sqlite3.IntegrityError(
                        "This BACnet station has an unresolved instance change through another or the same route."
                    )
            if (
                db.execute("SELECT COUNT(*) FROM device_instance_changes").fetchone()[0]
                >= MAX_RECORDS
            ):
                raise ValueError(
                    "Device-instance journal is full; export and archive its database."
                )
            db.execute(
                "INSERT INTO device_instance_changes VALUES(?,?,NULL,?,?,1)",
                (receipt["id"], raw, utc(), encoded(receipt["target"]).decode()),
            )
        return hashlib.sha256(raw).hexdigest()

    def result(self, receipt):
        raw = self._raw(receipt)
        unresolved = int(
            receipt["may_have_applied"] and receipt["readback"]["status"] != "verified_new"
        )
        with self.store.connect(timeout=0.25) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT intent,result FROM device_instance_changes WHERE id=?", (receipt["id"],)
            ).fetchone()
            if row and row[1] is not None:
                raise ValueError("A completed device-instance receipt is immutable.")
            if row and row[0] is not None:
                self._checked(row[0])
                if receipt.get("intent_sha256") != hashlib.sha256(row[0]).hexdigest():
                    raise ValueError("Device-instance result does not bind its durable intent.")
                db.execute(
                    "UPDATE device_instance_changes SET result=?,unresolved=? WHERE id=?",
                    (raw, unresolved, receipt["id"]),
                )
            else:
                if (
                    db.execute("SELECT COUNT(*) FROM device_instance_changes").fetchone()[0]
                    >= MAX_RECORDS
                ):
                    raise ValueError("Device-instance journal is full.")
                db.execute(
                    "INSERT INTO device_instance_changes VALUES(?,NULL,?,?,?,?)",
                    (receipt["id"], raw, utc(), encoded(receipt["target"]).decode(), unresolved),
                )
        return self._checked(raw)

    def readback(self, receipt_id, value):
        raw = self._raw(value)
        with self.store.connect(timeout=0.25) as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute("SELECT COUNT(*) FROM device_instance_readbacks").fetchone()[0]
                >= MAX_RECORDS * 4
            ):
                raise ValueError("Device-instance readback journal is full.")
            db.execute(
                "INSERT INTO device_instance_readbacks(receipt_id,body) VALUES(?,?)",
                (receipt_id, raw),
            )
            if value["readback"]["status"] == "verified_new":
                db.execute(
                    "UPDATE device_instance_changes SET unresolved=0 WHERE id=?", (receipt_id,)
                )
        return self._checked(raw)

    def receipt(self, identifier):
        InstanceReconcile(operation_id="receipt-read", receipt_id=identifier)
        with self.store.connect(timeout=0.25) as db:
            row = db.execute(
                "SELECT intent,result FROM device_instance_changes WHERE id=?", (identifier,)
            ).fetchone()
            reads = db.execute(
                "SELECT body FROM device_instance_readbacks WHERE receipt_id=? ORDER BY sequence",
                (identifier,),
            ).fetchall()
        if row is None:
            raise ValueError("Device-instance receipt is unavailable.")
        intent = self._checked(row[0]) if row[0] is not None else None
        result = self._checked(row[1]) if row[1] is not None else None
        if result and intent and result.get("intent_sha256") != hashlib.sha256(row[0]).hexdigest():
            raise ValueError("Device-instance intent/result binding failed.")
        return {
            "attempt": result or intent,
            "intent": intent,
            "readbacks": [self._checked(r[0]) for r in reads],
        }

    def entries(self):
        with self.store.connect(timeout=0.25) as db:
            ids = [
                r[0]
                for r in db.execute("SELECT id FROM device_instance_changes ORDER BY created DESC")
            ]
        return [self.receipt(identifier) for identifier in ids]


class DeviceInstances:
    def __init__(
        self,
        bacnet,
        store,
        *,
        timeout=1.5,
        operation_timeout=30,
        request_gap=0.05,
        activity_guard=None,
    ):
        self.bacnet, self.store = bacnet, store
        self.path = DeviceDetails(bacnet, store, timeout=timeout, request_gap=request_gap)
        self.timeout, self.operation_timeout = timeout, operation_timeout
        self.routed, self.ip = RoutedDiscovery(bacnet, store), IpDiscovery(bacnet, store)
        self.journal = InstanceJournal(store)
        self.activity_guard = activity_guard or (lambda: None)
        self._plans, self._cancelled = OrderedDict(), OrderedDict()
        self._active = None

    @staticmethod
    def pending(entry):
        attempt = entry["attempt"]
        resolved = attempt.get("readback", {}).get("status") == "verified_new" or any(
            value["readback"]["status"] == "verified_new" for value in entry["readbacks"]
        )
        return bool(attempt["may_have_applied"] and not resolved)

    def status(self):
        entries = self.journal.entries()
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "automatic_retries": False,
            "plan_seconds": PLAN_SECONDS,
            "active_operation": self._active["operation_id"] if self._active else None,
            "receipts": [
                {
                    **{
                        key: entry["attempt"][key]
                        for key in ("id", "target", "new_instance", "status", "created_at")
                    },
                    "pending": self.pending(entry),
                }
                for entry in entries
            ],
        }

    def _available(self, target):
        if self.bacnet.commands:
            raise ValueError("Release owned point commands before device-instance commissioning.")
        self.activity_guard()
        key = station_key(target)
        for entry in self.journal.entries():
            if self.pending(entry) and station_key(entry["attempt"]["target"]) == key:
                raise ValueError(
                    "This station has an unresolved instance change. Read back its receipt; do not retry the write."
                )

    def cancel(self, operation_id):
        InstanceCancel(operation_id=operation_id)
        self._cancelled[operation_id] = True
        while len(self._cancelled) > 64:
            self._cancelled.popitem(last=False)
        active = self._active
        found = active is not None and active["operation_id"] == operation_id
        if found:
            active["task"].cancel()
        return {
            "cancel_requested": found,
            "note": "Cancellation cannot undo a transmitted instance change.",
        }

    async def close(self):
        self._plans.clear()
        active = self._active
        if active:
            self.cancel(active["operation_id"])
            if active["task"] is not asyncio.current_task():
                await asyncio.gather(active["task"], return_exceptions=True)

    @asynccontextmanager
    async def _operation(self, operation_id):
        if self._active or operation_id in self._cancelled:
            raise ValueError("Instance operation is busy or cancelled; use a fresh operation ID.")
        self._active = {
            "operation_id": operation_id,
            "task": asyncio.current_task(),
            "deadline": time.monotonic() + self.operation_timeout,
        }
        try:
            async with asyncio.timeout(self.operation_timeout):
                yield
        except asyncio.CancelledError as exc:
            raise ValueError(
                "Device-instance operation cancelled; consult retained receipts for any transmitted write."
            ) from exc
        except TimeoutError as exc:
            raise ValueError(
                "Device-instance operation exceeded its time budget; consult retained receipts."
            ) from exc
        finally:
            self._active = None

    @staticmethod
    def _target(options):
        return {key: getattr(options, key) for key in ("address", "router", "dnet")}

    def _guard(self, app, config):
        self.path._guard({"app": app, "config": config})
        if time.monotonic() >= self._active["deadline"]:
            raise TimeoutError("Device-instance operation expired.")

    def _endpoint(self, options, app):
        config = self.bacnet.config or {}
        if config.get("transport") == "mstp" or config.get("bbmd_address"):
            raise ValueError("Instance commissioning requires a plain BACnet/IPv4 interface.")
        if (
            options.router is None
            and Address(options.address) == app.nsap.local_adapter.adapterAddr
        ):
            raise ValueError("Select a controller endpoint, not the engineering client itself.")

    async def _identity(self, session, device):
        identifier = await self.path._read(session, device, "object-identifier")
        if (
            not isinstance(identifier, ObjectIdentifier)
            or int(identifier[0]) != 8
            or not 0 <= identifier[1] <= 4194302
        ):
            raise ValueError("Controller did not return an actual Device identifier.")
        if device != "device,4194303" and str(identifier) != device:
            raise ValueError("Controller instance differs from the selected Device.")
        result = {"device": str(identifier)}
        for prop in IDENTITY_FIELDS:
            value = await self.path._read(session, str(identifier), prop)
            if prop == "vendor-identifier":
                if not isinstance(value, int) or not 0 <= value <= 65535:
                    raise ValueError("Invalid controller vendor identifier.")
                result[prop] = int(value)
            else:
                if (
                    not isinstance(value, str)
                    or len(value.encode()) > 512
                    or (prop == "object-name" and not value)
                ):
                    raise ValueError("Controller identity requires bounded text for " + prop + ".")
                result[prop] = str(value)
        return result

    async def _collision(self, options):
        if options.router:
            evidence = await self.routed.scan(
                router=options.router,
                dnet=options.dnet,
                low=options.new_instance,
                high=options.new_instance,
                timeout_seconds=1.0,
                max_devices=16,
            )
            scope = f"Selected router {options.router}, network {options.dnet}"
        else:
            port = IPv4Address(options.address).addrTuple[1]
            evidence = await self.ip.scan(
                mode="local",
                udp_port=port,
                low=options.new_instance,
                high=options.new_instance,
                timeout_seconds=1.0,
                max_devices=16,
            )
            scope = "Bound IPv4 local subnet"
        if not evidence["complete"] or evidence["truncated"] or evidence["invalid_responses"]:
            raise ValueError("New-instance collision check was incomplete; no write is available.")
        return {
            "scope": scope,
            "devices": evidence["devices"],
            "checked_at": utc(),
            "evidence_sha256": sha(evidence),
            "limitation": "Silence is not proof of an unused number. Reserve the new instance across the entire BACnet internetwork, including offline devices.",
        }

    async def preview(self, **arguments):
        options = InstancePreview(**arguments)
        target = self._target(options)
        if ObjectIdentifier(options.device)[1] == options.new_instance:
            raise ValueError("The new instance must differ from the current instance.")
        async with self._operation(options.operation_id):
            app, config = self.bacnet.require(), copy.deepcopy(self.bacnet.config)
            self._endpoint(options, app)
            if options.new_instance == config["instance"]:
                raise ValueError("The new instance collides with this engineering client.")
            self._available(target)
            collision = await self._collision(options)
            self._guard(app, config)
            async with self.path._path(options) as session:
                self._guard(app, config)
                identity = await self._identity(session, options.device)
            self._available(target)
            body = {
                "profile": PROFILE,
                "target": target,
                "identity": identity,
                "old_instance": ObjectIdentifier(options.device)[1],
                "new_instance": options.new_instance,
                "connector_config": config,
                "collision_check": collision,
                "created_at": utc(),
                "expires_at": (datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)).isoformat(),
                "can_apply": not collision["devices"],
                "scope": SCOPE,
            }
            digest = sha(body)
            token = secrets.token_urlsafe(24)
            # A newer preview for the same station supersedes every older one.
            self._plans = OrderedDict(
                (key, value)
                for key, value in self._plans.items()
                if value["body"]["target"] != target and value["expires"] > time.monotonic()
            )
            self._plans[token] = {
                "body": body,
                "sha": digest,
                "app": app,
                "config": config,
                "options": options,
                "expires": time.monotonic() + PLAN_SECONDS,
            }
            while len(self._plans) > 16:
                self._plans.popitem(last=False)
            return {**body, "token": token, "review_sha256": digest}

    async def _observe(self, session, attempt):
        errors = []
        for device in (
            f"device,{attempt['new_instance']}",
            attempt["identity"]["device"],
            "device,4194303",
        ):
            try:
                identity = await self._identity(session, device)
                matches = all(
                    identity[prop] == attempt["identity"][prop] for prop in IDENTITY_FIELDS
                )
                state = (
                    (
                        "verified_new"
                        if identity["device"] == f"device,{attempt['new_instance']}"
                        else "verified_old"
                        if identity["device"] == attempt["identity"]["device"]
                        else "different_instance"
                    )
                    if matches
                    else "identity_mismatch"
                )
                return {
                    "status": state,
                    "identity": identity,
                    "observed_at": utc(),
                    "errors": errors,
                }
            except (ValueError, TimeoutError) as exc:
                errors.append((str(exc) or "Read timed out")[:512])
        return {"status": "unknown", "observed_at": utc(), "errors": errors}

    async def apply(self, **arguments):
        request = InstanceApply(**arguments)
        plan = self._plans.pop(request.token, None)
        if not plan or request.review_sha256 != plan["sha"] or not plan["body"]["can_apply"]:
            raise ValueError(
                "Instance review is unavailable, changed, blocked or already consumed; preview again."
            )
        if not request.allocation_confirmed:
            raise ValueError(
                "Confirm that the new instance is reserved across the BACnet internetwork."
            )
        body, options = plan["body"], plan["options"]
        receipt = {
            "profile": PROFILE,
            "id": secrets.token_hex(16),
            "operation_id": request.operation_id,
            "target": body["target"],
            "identity": body["identity"],
            "old_instance": body["old_instance"],
            "new_instance": body["new_instance"],
            "connector_config": plan["config"],
            "review_sha256": plan["sha"],
            "allocation_confirmed": True,
            "created_at": utc(),
            "status": "not_sent",
            "dispatch_started": False,
            "may_have_applied": False,
            "protocol_accepted": False,
            "readback": {"status": "not_read"},
            "errors": [],
        }
        write = None
        try:
            async with self._operation(request.operation_id):
                self._guard(plan["app"], plan["config"])
                if time.monotonic() >= plan["expires"]:
                    raise ValueError("Instance review expired; preview again.")
                self._available(body["target"])
                collision = receipt["collision_check"] = await self._collision(options)
                if collision["devices"]:
                    raise ValueError(
                        "The new instance answered the fresh collision query; no write was sent."
                    )
                async with self.path._path(options) as session:
                    self._guard(plan["app"], plan["config"])
                    fresh = await self._identity(session, options.device)
                    if fresh != body["identity"]:
                        raise ValueError("Controller identity changed after review; preview again.")
                    self._available(body["target"])
                    write = WritePropertyRequest(
                        objectIdentifier=ObjectIdentifier(options.device),
                        propertyIdentifier="object-identifier",
                        propertyValue=ObjectIdentifier(("device", options.new_instance)),
                        destination=session["target"],
                    )

                    def before_send(packet):
                        self._guard(plan["app"], plan["config"])
                        if time.monotonic() >= plan["expires"]:
                            raise ValueError("Instance review expired before dispatch.")
                        self._available(body["target"])
                        receipt["request_apdu_sha256"] = hashlib.sha256(
                            bytes(packet.encode().pduData)
                        ).hexdigest()
                        receipt["intent_sha256"] = self.journal.intent(receipt)
                        self._guard(plan["app"], plan["config"])
                        receipt.update(dispatch_started=True, may_have_applied=True)

                    try:
                        reply = await confirmed_exchange(
                            session["app"],
                            write,
                            single_attempt=True,
                            before_send=before_send,
                            response_timeout=self.timeout,
                        )
                        self.path._guard(session)
                        if (
                            not isinstance(reply, SimpleAckPDU)
                            or reply.pduSource != session["target"]
                            or reply.apduInvokeID != write.apduInvokeID
                            or reply.apduService != write.apduService
                        ):
                            raise ValueError(
                                "Write acknowledgement source/invoke/service/type mismatch."
                            )
                        receipt.update(protocol_accepted=True, status="pending_readback")
                    except ErrorRejectAbortNack as exc:
                        rejected = (
                            isinstance(exc, (ErrorPDU, RejectPDU))
                            and exc.pduSource == session["target"]
                            and exc.apduInvokeID == write.apduInvokeID
                            and (
                                not isinstance(exc, ErrorPDU)
                                or exc.apduService == write.apduService
                            )
                        )
                        receipt.update(
                            status="rejected" if rejected else "unknown",
                            may_have_applied=not rejected,
                        )
                        receipt["errors"].append((str(exc) or type(exc).__name__)[:512])
                    except (ValueError, TimeoutError) as exc:
                        receipt["status"] = "unknown" if receipt["dispatch_started"] else "not_sent"
                        receipt["errors"].append((str(exc) or "Write response timed out")[:512])
                    if receipt["dispatch_started"] and receipt["status"] != "rejected":
                        receipt["readback"] = await self._observe(session, receipt)
                        receipt["status"] = (
                            "verified"
                            if receipt["readback"]["status"] == "verified_new"
                            else "unknown"
                        )
                        if receipt["status"] == "verified":
                            self._forget_old_address(session)
        except (ValueError, TimeoutError, OSError, sqlite3.Error, asyncio.CancelledError) as exc:
            receipt["status"] = "unknown" if receipt["dispatch_started"] else "not_sent"
            receipt["errors"].append((str(exc) or "Operation cancelled or deadline expired")[:512])
        receipt["finished_at"] = utc()
        try:
            receipt = self.journal.result(receipt)
        except (ValueError, OSError, sqlite3.Error) as exc:
            receipt["errors"].append("Result journal unavailable: " + str(exc)[:512])
            receipt = seal(receipt)
        return receipt

    @staticmethod
    def _forget_old_address(session):
        # Duplicate instance IDs may belong to another station. Remove an
        # instance mapping only when it is the very same address-cache object.
        cache = session["app"].device_info_cache
        old = cache.address_cache.pop(session["target"], None)
        if old is not None and cache.instance_cache.get(old.device_instance) is old:
            del cache.instance_cache[old.device_instance]

    async def reconcile(self, **arguments):
        request = InstanceReconcile(**arguments)
        attempt = self.journal.receipt(request.receipt_id)["attempt"]
        options = DeviceDetailsRequest(**attempt["target"], device=attempt["identity"]["device"])
        async with self._operation(request.operation_id):
            app = self.bacnet.require()
            config = self.bacnet.config or {}
            if config.get("local_address") != attempt["connector_config"].get("local_address"):
                raise ValueError(
                    "Reconnect the receipt's original local IPv4 interface before readback."
                )
            self._endpoint(options, app)
            async with self.path._path(options) as session:
                readback = await self._observe(session, attempt)
                if readback["status"] == "verified_new":
                    self._forget_old_address(session)
            result = {
                "profile": PROFILE,
                "receipt_id": request.receipt_id,
                "attempt_sha256": attempt["evidence_sha256"],
                "readback": readback,
                "read_only": True,
                "created_at": utc(),
            }
            return self.journal.readback(request.receipt_id, result)


def device_instance_router(service):
    router = APIRouter(prefix="/api/bacnet/device-instance")

    @router.get("/status")
    def status():
        return service.status()

    @router.post("/preview")
    async def preview(body: InstancePreview):
        return await service.preview(**body.model_dump())

    @router.post("/apply")
    async def apply(body: InstanceApply):
        return await service.apply(**body.model_dump())

    @router.post("/cancel")
    async def cancel(body: InstanceCancel):
        return service.cancel(body.operation_id)

    @router.post("/readback")
    async def readback(body: InstanceReconcile):
        return await service.reconcile(**body.model_dump())

    @router.get("/receipts/{identifier}")
    def receipt(identifier: str):
        return service.journal.receipt(identifier)

    return router
