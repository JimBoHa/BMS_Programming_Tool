"""Scoped native VAV configuration properties, separately from image transfer.

Uses typed BACnet properties with a pinned station, one-use review, retained
old values and independent readback. No application/File rewrite is admitted.
Unknown native saved-parameter formats remain blocked by their existing guards.
"""

import copy
import hashlib
import math
import secrets
import struct
import time
from pathlib import Path

from bacpypes3.apdu import (
    ErrorRejectAbortNack,
    ReadPropertyACK,
    ReadPropertyRequest,
    SimpleAckPDU,
    WritePropertyRequest,
)
from bacpypes3.constructeddata import Any
from bacpypes3.errors import InvalidTag
from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Real
from fastapi import APIRouter
from pydantic import Field

from .application_files import ApplicationFiles
from .application_store import encoded, private_write, read_private, utc
from .device_details import DeviceDetails, DeviceDetailsRequest
from .models import StrictModel
from .property_evidence import PropertyEvidence

PROFILE = "native-vav-property-configuration/1"
# Actual native VAV Balancer attributes, not output overrides or model inventories.
FIELDS = {
    "area": (3887, Real),
    "cool_max": (3891, Real),
    "occupied_min": (3889, Real),
    "pickup_gain": (3893, Real),
    # Native loader identity is distinct from the standard Device.object-name.
    "name": (2390, CharacterString),
    "instance": (75, ObjectIdentifier),
}


class VavTarget(DeviceDetailsRequest):
    balancer: str = Field(min_length=1, max_length=80)


class VavReview(VavTarget):
    field: str
    expected: object
    value: object
    point: str | None = None


class VavApply(StrictModel):
    token: str = Field(pattern=r"^[0-9a-f]{32}$")
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_change_confirmed: bool = Field(strict=True)


def canonical(field, value):
    if field not in FIELDS:
        raise ValueError("Select a supported native configuration field.")
    if field == "name":
        if (
            type(value) is not str
            or not 1 <= len(value.encode()) <= 64
            or value.strip() != value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Use a bounded controller name without control characters.")
        return value
    if field == "instance":
        if type(value) is not int or not 1 <= value <= 4194302:
            raise ValueError("Use a specific BACnet Device instance.")
        return value
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Use one finite numeric configuration value.")
    low, high = {
        "area": (0.001, 100),
        "cool_max": (1, 100000),
        "occupied_min": (0, 100000),
        "pickup_gain": (0.001, 100000),
    }[field]
    if not low <= value <= high:
        raise ValueError("Native VAV value exceeds this configuration profile.")
    return struct.unpack("!f", struct.pack("!f", value))[0]


class NativeVavConfiguration:
    def __init__(self, bacnet, store, *, activity_guard=lambda: None):
        self.bacnet = bacnet
        self.path = DeviceDetails(bacnet, store)
        self.wire = ApplicationFiles(self.path, writable_files={3}, timeout=4)
        self.directory = Path(store.directory) / "native-vav-configuration"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.plans = {}
        self.activity_guard = activity_guard

    def _save(self, row):
        private_write(self.directory / (row["id"] + ".json"), encoded(row))

    def _available(self, target):
        import json

        for path in self.directory.glob("*.json"):
            row = json.loads(read_private(path, 1024 * 1024))
            old_target = row["source"]["target"]
            same_station = all(
                old_target.get(key) == getattr(target, key) for key in ("address", "router", "dnet")
            )
            if same_station and row["status"] in (
                "intent",
                "sent",
                "uncertain",
            ):
                raise ValueError(
                    "Reconcile the earlier uncertain native setting before another change."
                )

    async def _read(self, session, obj, pid, datatype):
        request = ReadPropertyRequest(objectIdentifier=obj, propertyIdentifier=pid)
        reply = await self.wire.exchange(session, request, ReadPropertyACK)
        if (
            reply.objectIdentifier != request.objectIdentifier
            or reply.propertyIdentifier != request.propertyIdentifier
            or reply.propertyArrayIndex is not None
        ):
            raise ValueError("Native property read differs from the requested field.")
        try:
            value = reply.propertyValue.cast_out(datatype)
        except (InvalidTag, TypeError, AttributeError) as exc:
            raise ValueError("Native property has an unsupported scalar datatype.") from exc
        if datatype is ObjectIdentifier:
            return str(value)
        if datatype is CharacterString:
            return str(value)
        if not math.isfinite(float(value)):
            raise ValueError("Native VAV property is nonfinite.")
        return float(value)

    async def _source(self, target, session):
        if (
            target.router is None
            or target.dnet is None
            or self.bacnet.config.get("router") != target.router
            or self.bacnet.config.get("dnet") != target.dnet
        ):
            raise ValueError("Open the selected exact router and trunk first.")
        balancer = ObjectIdentifier(target.balancer)
        if int(balancer[0]) != 631 or not 1 <= balancer[1] <= 4194302:
            raise ValueError(
                "Select the VAV Balancer discovered in this application's native records."
            )
        PropertyEvidence.pin(session, target.router)
        identity = {}
        for prop in (
            "object-identifier",
            "object-name",
            "vendor-identifier",
            "model-name",
            "firmware-revision",
            "application-software-version",
            "system-status",
        ):
            value = await self.path._read(session, target.device, prop)
            identity[prop] = str(value) if isinstance(value, ObjectIdentifier) else value
        if (
            identity["object-identifier"] != target.device
            or identity["vendor-identifier"] != 5
            or not str(identity["model-name"]).startswith(("M4-CVM", "F4-CVM"))
            or identity["system-status"] != 0
        ):
            raise ValueError("A verified, operational CVM native VAV target is required.")
        values = {"instance": ObjectIdentifier(target.device)[1]}
        errors = {}
        for field, (pid, datatype) in FIELDS.items():
            if field in values:
                continue
            try:
                owner = target.device if field == "name" else balancer
                values[field] = await self._read(session, owner, pid, datatype)
            except (ValueError, TimeoutError, OSError) as exc:
                errors[field] = type(exc).__name__
        return {
            "profile": PROFILE,
            "target": target.model_dump(),
            "interface": copy.deepcopy(session["config"]),
            "identity": identity,
            "values": values,
            "unavailable": errors,
            "native_image_backup": False,
            "editable_fields": ["name"],
            "read_only_fields": ["area", "cool_max", "occupied_min", "pickup_gain"],
        }

    async def source(self, arguments):
        target = VavTarget.model_validate(arguments)
        async with self.path._path(target) as session:
            return await self._source(target, session)

    @staticmethod
    def _preserved(before, after, field):
        for key, old in before["identity"].items():
            if field == "name" and key == "object-name":
                continue
            if after["identity"].get(key) != old:
                raise ValueError("Native identity changed; uncertainty remains.")
        if any(
            after["values"].get(key) != value
            for key, value in before["values"].items()
            if key != field
        ):
            raise ValueError("Another native setting changed during this operation.")

    async def _binding(self, target, session, field, point, expected):
        if point is None:
            raise ValueError(
                "Select the exposed configuration point discovered in the native application."
            )
        obj = ObjectIdentifier(point)
        if field == "name":
            if int(obj[0]) != 40:
                raise ValueError("The native loader name must be an exposed CharacterString Value.")
            root = await self._read(session, target.device, 32527, CharacterString)
            label = await self._read(session, obj, 77, CharacterString)
            if label != root + "/Preloaded App Loader.Device Name":
                raise ValueError(
                    "This is not the selected native loader's Device Name configuration point."
                )
            binding = {"object": str(obj), "property": 85, "reference": label}
        else:
            if int(obj[0]) != 2:
                raise ValueError("VAV configuration requires its exposed Analog Value point.")
            parent = await self._read(session, target.balancer, 32527, CharacterString)
            reference = await self._read(session, obj, 32527, CharacterString)
            attribute = await self._read(session, obj, 3365, Enumerated)
            if reference.rsplit(".", 1)[0] != parent or attribute != FIELDS[field][0]:
                raise ValueError(
                    "Configuration point does not bind the selected native balancer attribute."
                )
            binding = {
                "object": str(obj),
                "property": 85,
                "reference": reference,
                "attribute": int(attribute),
            }
        # These are noncommandable configuration points. An output override is
        # a different operation and cannot supply persistent-setting evidence.
        request = ReadPropertyRequest(objectIdentifier=obj, propertyIdentifier="priority-array")
        try:
            await self.wire.exchange(session, request, ReadPropertyACK)
        except ValueError as exc:
            cause = exc.__cause__
            if (
                not isinstance(cause, ErrorRejectAbortNack)
                or str(getattr(cause, "errorClass", "")) != "property"
                or str(getattr(cause, "errorCode", "")) != "unknown-property"
            ):
                raise ValueError(
                    "Noncommandable configuration-point semantics were not verified."
                ) from exc
        else:
            raise ValueError("This point exposes a priority array; use the owned-command workflow.")
        actual = await self._read(session, obj, 85, FIELDS[field][1])
        if actual != expected:
            raise ValueError(
                "Exposed configuration point differs from the native owner's current setting."
            )
        return binding

    async def preview(self, arguments):
        request = VavReview.model_validate(arguments)
        proposed, expected = (
            canonical(request.field, request.value),
            canonical(request.field, request.expected),
        )
        if request.field != "name":
            raise ValueError(
                "Only the verified native loader name is editable in this profile. "
                "Flow settings require a separately qualified native balancing method; "
                "instance changes use the existing identity commissioning workflow. "
                "No write was sent."
            )
        target = VavTarget.model_validate(request.model_dump(include=set(VavTarget.model_fields)))
        self.activity_guard()
        self._available(target)
        async with self.path._path(target) as session:
            self._available(target)
            source = await self._source(target, session)
            binding = (
                await self._binding(target, session, request.field, request.point, expected)
                if request.field != "instance"
                else None
            )
        if source["values"].get(request.field) != expected:
            raise ValueError("The expected current configuration does not match live readback.")
        if proposed == expected:
            raise ValueError("The proposed native setting is unchanged.")
        row = {
            "id": secrets.token_hex(16),
            "source": source,
            "field": request.field,
            "before": expected,
            "value": proposed,
            "write_target": binding,
            "effects": "One native loader name configuration write, without a priority override. The observed VAV scalar settings are checked before and after. No application files, firmware, alarm/trend records or other fields are written. This is not a complete configuration backup.",
        }
        digest = hashlib.sha256(encoded(row)).hexdigest()
        self.plans = {k: v for k, v in self.plans.items() if v[0] > time.monotonic()}
        if len(self.plans) >= 32:
            raise ValueError("Native configuration review capacity reached.")
        token = secrets.token_hex(16)
        self.plans[token] = (time.monotonic() + 120, copy.deepcopy(row), digest)
        return {**row, "token": token, "review_sha256": digest, "expires_in": 120}

    async def apply(self, arguments):
        request = VavApply.model_validate(arguments)
        if request.configuration_change_confirmed is not True:
            raise ValueError("Review the native configuration change explicitly first.")
        plan = self.plans.pop(request.token, None)
        if (
            plan is None
            or plan[0] < time.monotonic()
            or not secrets.compare_digest(plan[2], request.review_sha256)
        ):
            raise ValueError("Native configuration review expired, changed or was already used.")
        row = plan[1]
        if row["field"] != "name":
            raise ValueError("This profile admits only a reviewed native loader name change.")
        target = VavTarget.model_validate(row["source"]["target"])
        self.activity_guard()
        self._available(target)
        async with self.path._path(target) as session:
            self._available(target)
            if await self._source(target, session) != row["source"]:
                raise ValueError("Native identity, interface or settings changed after review.")
            field = row["field"]
            if (
                await self._binding(
                    target, session, field, row["write_target"]["object"], row["before"]
                )
                != row["write_target"]
            ):
                raise ValueError("Native configuration binding changed after review.")
            _, datatype = FIELDS[field]
            obj = row["write_target"]["object"]
            pid = 85
            value = datatype(row["value"])
            operation = WritePropertyRequest(
                objectIdentifier=obj, propertyIdentifier=pid, propertyValue=Any(value)
            )
            row.update(status="intent", started_at=utc(), review_sha256=plan[2])
            self._save(row)

            def sent(_packet):
                row.update(status="sent")
                self._save(row)

            try:
                await self.wire.exchange(session, operation, SimpleAckPDU, before_send=sent)
                row["write_wire"] = copy.deepcopy(session.get("last_application_wire"))
                actual = await self._read(session, obj, pid, datatype)
                readback_wire = copy.deepcopy(session.get("last_application_wire"))
                if actual != row["value"]:
                    raise ValueError(
                        "Native setting acknowledgement did not produce matching readback."
                    )
                after = await self._source(target, session)
                if after["values"].get(field) != row["value"]:
                    raise ValueError("The native owner did not confirm the exposed setting change.")
                self._preserved(row["source"], after, field)
                row.update(
                    status="verified",
                    readback=actual,
                    readback_wire=readback_wire,
                )
            except BaseException as exc:
                rejected = isinstance(exc, ErrorRejectAbortNack) or isinstance(
                    exc.__cause__, ErrorRejectAbortNack
                )
                row.update(
                    status="rejected" if rejected else "uncertain", error_type=type(exc).__name__
                )
                self._save(row)
                raise
            finally:
                row["finished_at"] = utc()
                self._save(row)
            self._save(row)
        return row

    async def reconcile(self, target, identifier):
        import json

        if len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
            raise ValueError("Use the retained native operation identifier.")
        row = json.loads(read_private(self.directory / (identifier + ".json"), 1024 * 1024))
        options = VavTarget.model_validate(target)
        if row["source"]["target"] != options.model_dump():
            raise ValueError("Reconciliation target differs from the original station.")
        field = row["field"]
        async with self.path._path(options) as session:
            current = await self._source(options, session)
            binding = await self._binding(
                options,
                session,
                field,
                row["write_target"]["object"],
                current["values"].get(field),
            )
        if binding != row["write_target"]:
            raise ValueError("Native configuration binding changed; uncertainty remains.")
        value = current["values"].get(field)
        if value not in (row["value"], row["before"]):
            raise ValueError(
                "The current setting matches neither reviewed value; uncertainty remains."
            )
        self._preserved(row["source"], current, field)
        row.update(
            status="verified_by_readback" if value == row["value"] else "not_applied_readback",
            reconciled_at=utc(),
            reconciled_value=value,
            write_acknowledgement_inferred=False,
        )
        self._save(row)
        return row


def router(bacnet, store, *, activity_guard):
    service = NativeVavConfiguration(bacnet, store, activity_guard=activity_guard)
    api = APIRouter(prefix="/api/bacnet/controller/native-vav")

    @api.post("/source")
    async def source(body: VavTarget):
        return await service.source(body.model_dump())

    @api.post("/preview")
    async def preview(body: VavReview):
        return await service.preview(body.model_dump())

    @api.post("/apply")
    async def apply(body: VavApply):
        return await service.apply(body.model_dump())

    @api.post("/reconcile/{identifier}")
    async def reconcile(identifier: str, body: VavTarget):
        return await service.reconcile(body.model_dump(), identifier)

    return api
