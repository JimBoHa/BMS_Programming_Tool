"""Reviewed NetSensor trials through the existing native file transport and journal."""

import asyncio
import copy
import math
import secrets
import sqlite3
import time
from typing import Literal

from bacpypes3.basetypes import StatusFlags
from bacpypes3.object import Object
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    Unsigned,
)
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field, StrictBool, model_validator

from .application_store import private_write, read_private, utc
from .device_details import DeviceDetailsRequest
from .device_instance import InstanceCancel, station_key
from .models import StrictModel
from .moi_identity import MoiIdentity, seal, sha
from .native_sensor_trial import (
    HASH,
    PROFILE,
    SCOPE,
    TrialEdit,
    compile_trial,
    compile_trial_restore,
    sensor_sources,
    source_app,
    verify_trial,
)
from .property_evidence import PropertyEvidence, ReadBudget


class SensorSource(StrictModel):
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    snapshot_sha256: str = Field(pattern=HASH)


class SensorPreview(DeviceDetailsRequest, SensorSource):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    action: Literal["install", "restore"]
    edit: TrialEdit | None = None
    trial_receipt: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @model_validator(mode="after")
    def shape(self):
        if (self.action == "install" and (self.edit is None or self.trial_receipt is not None)) or (
            self.action == "restore" and (self.edit is not None or self.trial_receipt is None)
        ):
            raise ValueError(
                "Install requires an edit; Restore requires its exact original trial receipt."
            )
        return self


class SensorSupport(DeviceDetailsRequest, SensorSource):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class SensorCopy(SensorSource):
    edit: TrialEdit
    expected_review_sha256: str | None = Field(default=None, pattern=HASH)


class SensorApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    review_sha256: str = Field(pattern=HASH)
    sensor_trial_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


class SensorReceipt(DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    receipt_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class SensorTrials:
    def __init__(self, native, *, activity_guard=None):
        self.native = native
        self.plans = {}
        self.activity_guard = activity_guard or (lambda _own: native.instances.activity_guard())
        native.sensor_trials = self

    def cancel(self, operation_id):
        self.plans = {
            k: p
            for k, p in self.plans.items()
            if p["body"]["request"]["operation_id"] != operation_id
        }

    def available(self, options, *, own=None):
        native = self.native
        native.instances._endpoint(options, native.bacnet.require())
        if native.bacnet.commands:
            raise ValueError("Release owned point commands before a sensor-definition transfer.")
        self.activity_guard(own)
        for receipt in native.storage.receipts(include_events=False):
            if receipt["pending"] and receipt["intent"]["id"] != own:
                raise ValueError(
                    "Read back the unresolved native transfer before another sensor change."
                )
        for entry in native.instances.journal.entries():
            if native.instances.pending(entry) and station_key(
                entry["attempt"]["target"]
            ) == station_key(native.target(options)):
                raise ValueError(
                    "Resolve the station's retained instance change before a sensor trial."
                )

    def load_source(self, request):
        capture, files = self.native.storage.load(request.capture_id)
        if (
            not capture.get("source_identity_matches")
            or capture["evidence_sha256"] != request.snapshot_sha256
        ):
            raise ValueError("Select a complete identity-matched native capture.")
        return capture, files

    def source(self, request):
        capture, files = self.load_source(request)
        return {
            "profile": PROFILE,
            "capture_id": capture["id"],
            "snapshot_sha256": capture["evidence_sha256"],
            "captured_at": capture["captured_at"],
            "identity": capture["identity"],
            "target": capture["target"],
            "sensors": sensor_sources(files),
            "scope": SCOPE,
            "controller_queries": False,
            "controller_writes": False,
        }

    def copy(self, request):
        capture, files = self.load_source(request)
        output, compilation = compile_trial(files, request.edit)
        body = {
            "profile": PROFILE,
            "capture_id": capture["id"],
            "snapshot_sha256": capture["evidence_sha256"],
            "edit": request.edit.model_dump(),
            "target": capture["target"],
            "identity": capture["identity"],
            "compilation": compilation,
            "output_sha256": sha(output),
            "controller_queries": False,
            "controller_writes": False,
            "can_apply": False,
        }
        body["review_sha256"] = seal(body)
        if (
            request.expected_review_sha256 is not None
            and request.expected_review_sha256 != body["review_sha256"]
        ):
            raise ValueError("The local sensor application copy changed; review it again.")
        return output, body

    def status(self):
        return {
            "profile": PROFILE,
            "controller_queries": False,
            "receipts": [
                self.receipt(r["intent"]["id"])
                for r in self.native.storage.receipts()
                if r["intent"].get("operation_profile") == PROFILE
            ],
        }

    def receipt(self, receipt_id):
        result = self.native.storage.receipt(receipt_id)
        result["latest_readback"] = next(
            (
                event["detail"]
                for event in reversed(result["events"])
                if event["stage"] == "readback"
            ),
            None,
        )
        return result

    def record_restoration(self, intent, result):
        if intent["sensor_action"] != "restore" or result["status"] != "verified":
            return
        parent = self.native.storage.receipt(intent["trial_receipt"])
        if not any(
            event["stage"] == "sensor-trial-restored"
            and event["detail"].get("receipt_id") == intent["id"]
            for event in parent["events"]
        ):
            self.native.storage.event(
                intent["trial_receipt"],
                "sensor-trial-restored",
                {
                    "receipt_id": intent["id"],
                    "restored_at": utc(),
                    "verification_capture_id": result["verification_capture_id"],
                },
            )

    async def support(self, options):
        native = self.native
        capture, _ = self.load_source(options)
        async with native.operation(options.operation_id, "sensor-definition-identity"):
            self.available(options)
            if (
                capture["target"] != native.target(options)
                or capture["device"] != options.device
                or capture["connector_config"] != native.bacnet.config
            ):
                raise ValueError("Select this capture's original controller and interface.")
            async with native.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                actual, _ = await native.identity(session, options.device)
                if actual != capture["identity"]:
                    raise ValueError(
                        "The selected controller differs from the retained sensor source."
                    )
                next_id = int(await native.input_atomic(session, options.device, 787, Unsigned))
                if not 1 <= next_id <= 4194287:
                    raise ValueError(
                        "The controller has insufficient identifiers for this trial profile."
                    )
                return {
                    "profile": PROFILE,
                    "identity": actual,
                    "target": native.target(options),
                    "capture_id": capture["id"],
                    "next_available_instance": next_id,
                    "read_only": True,
                }

    def origin(self, receipt_id, options):
        receipt = self.receipt(receipt_id)
        intent = receipt["intent"]
        if (
            intent.get("operation_profile") != PROFILE
            or intent.get("sensor_action") != "install"
            or intent["target"] != self.native.target(options)
            or intent["identity"]["device"] != options.device
        ):
            raise ValueError("This is not the original NetSensor trial on the selected controller.")
        return receipt

    def compile(self, options, files):
        if options.action == "install":
            return compile_trial(files, options.edit)
        receipt = self.origin(options.trial_receipt, options)
        _, original = self.native.storage.load(receipt["intent"]["backup_id"])
        return compile_trial_restore(files, original, receipt["intent"]["edit"])

    async def presence(self, session, obj):
        native = self.native
        _, proof = await PropertyEvidence(native.path).read(
            session,
            ReadBudget(max_requests=1, max_bytes=4096),
            obj,
            75,
            Object,
            timeout=native.files.timeout,
        )
        if proof["status"] == "ok":
            actual = await native.input_atomic(session, obj, 75, ObjectIdentifier)
            if actual == ObjectIdentifier(obj):
                return True
        error = proof.get("native_error", {})
        if (
            proof["status"] == "native_error"
            and error.get("errorClass", {}).get("value") == 1
            and error.get("errorCode", {}).get("value") == 31
            and proof.get("transport_evidence")
        ):
            return False
        raise ValueError("A timeout or property rejection cannot establish object absence.")

    async def live_guard(self, session, options, compilation):
        native = self.native
        if int(await native.path._read(session, options.device, "system-status")) != 0:
            raise ValueError(
                "The controller is not operational; do not start a sensor trial transfer."
            )
        if await native.input_atomic(session, "307,2", 75, ObjectIdentifier) != ObjectIdentifier(
            (307, 2)
        ):
            raise ValueError("The selected SA port identity changed.")
        if (
            not bool(await native.input_atomic(session, "307,2", 673, Boolean))
            or bool(await native.input_atomic(session, "307,2", 81, Boolean))
            or int(await native.input_atomic(session, "307,2", 1036, Unsigned)) != 0
        ):
            raise ValueError(
                "The SA port is disabled, out of service or owned by another communication test."
            )
        selected = compilation["original_sensor"]
        obj = selected["object_id"]
        if await native.input_atomic(session, obj, 75, ObjectIdentifier) != ObjectIdentifier(obj):
            raise ValueError("The selected sensor integration identity changed.")
        enabled = bool(await native.input_atomic(session, obj, 673, Boolean))
        mac = int(await native.input_atomic(session, obj, 2858, Unsigned))
        if enabled != (options.action == "install") or mac != selected["address"]:
            raise ValueError("The selected sensor integration enable/address changed.")
        if options.action == "install":
            if not bool(await native.input_atomic(session, obj, 913, Boolean)):
                raise ValueError(
                    "The existing NS8000 is online; do not interrupt a working sensor for this trial."
                )
            next_id = int(await native.input_atomic(session, options.device, 787, Unsigned))
            if options.edit.first_instance < next_id:
                raise ValueError(
                    "Trial identities precede the controller's next available identifier."
                )
        for row in compilation["trial_points"]:
            for key in ("device_object", "temperature_object"):
                if await self.presence(session, row[key]) != (options.action == "restore"):
                    raise ValueError("A trial identity is occupied or no longer present.")

    async def preview(self, options):
        native = self.native
        capture, files = self.load_source(options)
        own = options.trial_receipt
        if options.action == "restore":
            origin = self.origin(own, options)
            if origin["pending"]:
                raise ValueError(
                    "Read back the uncertain trial before reviewing restoration; no download is repeated."
                )
        async with native.operation(options.operation_id, "sensor-definition-review"):
            self.available(options)
            if (
                capture["target"] != native.target(options)
                or capture["device"] != options.device
                or capture["connector_config"] != native.bacnet.config
            ):
                raise ValueError("Select the capture's exact controller and original interface.")
            output, compilation = self.compile(options, files)
            async with native.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                actual, _ = await native.identity(session, options.device)
                if actual != capture["identity"]:
                    raise ValueError("Controller identity/firmware changed since capture.")
                await self.live_guard(session, options, compilation)
            self.plans = {k: p for k, p in self.plans.items() if p["expires"] > time.monotonic()}
            if len(self.plans) >= 32:
                raise ValueError(
                    "Sensor review capacity is full; cancel or finish an earlier review."
                )
            body = {
                "profile": PROFILE,
                "request": options.model_dump(),
                "identity": actual,
                "compilation": compilation,
                "original_files": {str(k): sha(v) for k, v in files.items()},
                "connector_config": copy.deepcopy(native.bacnet.config),
                "scope": SCOPE,
                "created_at": utc(),
                "expires_seconds": 900,
                "backup_effects": {
                    "writes_application": False,
                    "sends_backup_state_commands": True,
                },
                "controller_writes": False,
                "can_apply": True,
            }
            token, digest = secrets.token_hex(16), seal(body)
            self.plans[token] = {
                "body": body,
                "digest": digest,
                "expires": time.monotonic() + 900,
                "app": native.bacnet.require(),
                "credentials": seal(native.credentials.get()),
            }
            return {**body, "token": token, "review_sha256": digest}

    def checked_receipt(self, options):
        receipt = self.receipt(options.receipt_id)
        intent = receipt["intent"]
        if (
            intent.get("operation_profile") != PROFILE
            or intent["target"] != self.native.target(options)
            or intent["identity"]["device"] != options.device
        ):
            raise ValueError("This sensor receipt belongs to another controller or operation.")
        if self.native.bacnet.config != intent["connector_config"]:
            raise ValueError("Reconnect the receipt's original interface before readback.")
        return receipt

    async def verify(self, session, options, intent, *, allow_original=False):
        native = self.native
        actual, _ = await native.identity(session, options.device)
        if actual != intent["identity"]:
            raise ValueError("Controller identity/firmware changed during the sensor transfer.")
        if int(await native.path._read(session, options.device, "system-status")) != 0:
            raise ValueError(
                "Controller operation has not recovered; retain the transfer for readback."
            )
        capture, files, _ = await native.capture_session(options, session, identity=actual)
        folder = native.storage.capture_folder(intent["backup_id"])
        output = read_private(folder / intent["payload_filename"], 2 * 1024 * 1024)
        if sha(output) != intent["payload_sha256"]:
            raise ValueError("The retained sensor payload failed its integrity check.")
        if allow_original and sha(MoiIdentity(files[3]).data) != intent["native_payload_sha256"]:
            _, before = native.storage.load(intent["backup_id"])
            from .native_sensor_trial import effective_guard

            original, _ = source_app(before)
            current, _ = source_app(files)
            if MoiIdentity(files[3]).data == MoiIdentity(before[3]).data and effective_guard(
                current
            ) == effective_guard(original):
                return {
                    "status": "recovered_original",
                    "operational": True,
                    "identity": actual,
                    "verification_capture_id": capture["id"],
                    "original_configuration_verified": True,
                    "sensor_action": intent["sensor_action"],
                    "trial_still_installed": intent["sensor_action"] == "restore",
                    "application_download_replayed": False,
                    "may_have_applied": True,
                }
        proof = verify_trial(files, output, expected_native_sha256=intent["native_payload_sha256"])
        selected = intent["compilation"]["original_sensor"]
        enabled = bool(await native.input_atomic(session, selected["object_id"], 673, Boolean))
        if enabled != (intent["sensor_action"] == "restore"):
            raise ValueError(
                "The original sensor enable state differs from the reviewed operation."
            )
        for row in intent["compilation"]["trial_points"]:
            for key in ("device_object", "temperature_object"):
                if await self.presence(session, row[key]) != (intent["sensor_action"] == "install"):
                    raise ValueError(
                        "Independent trial object membership differs from the reviewed image."
                    )
        result = {
            "status": "verified",
            "operational": True,
            "identity": actual,
            "verification_capture_id": capture["id"],
            "sensor_action": intent["sensor_action"],
            "existing_points_and_wires_preserved": True,
            "sensor_communication_verified": False,
            **proof,
            "may_have_applied": True,
        }
        self.record_restoration(intent, result)
        return result

    async def apply(self, confirmation):
        if (
            not confirmation.sensor_trial_confirmed
            or not confirmation.application_transfer_confirmed
        ):
            raise ValueError("Confirm the sensor trial and application transfer before Apply.")
        plan = self.plans.pop(confirmation.token, None)
        if (
            plan is None
            or plan["digest"] != confirmation.review_sha256
            or plan["expires"] <= time.monotonic()
            or seal(plan["body"]) != plan["digest"]
        ):
            raise ValueError("The sensor review is absent, changed, expired or already consumed.")
        native, body = self.native, plan["body"]
        options = SensorPreview.model_validate(body["request"])
        intent, dispatched = None, False
        result = {"status": "not_sent", "may_have_applied": False, "errors": []}
        try:
            async with native.operation(confirmation.operation_id, "sensor-definition-apply"):
                self.available(options)
                native.storage.require_capture_capacity(2)
                if (
                    native.bacnet.require() is not plan["app"]
                    or native.bacnet.config != body["connector_config"]
                    or seal(native.credentials.get()) != plan["credentials"]
                ):
                    raise ValueError("The reviewed interface or credentials changed.")
                async with native.path._path(options) as session:
                    PropertyEvidence.pin(session, options.router)
                    actual, _ = await native.identity(session, options.device)
                    if actual != body["identity"]:
                        raise ValueError("Controller identity/firmware changed after review.")
                    await self.live_guard(session, options, body["compilation"])
                    backup, files, chunk = await native.capture_session(
                        options, session, identity=actual
                    )
                    if any(sha(files[k]) != body["original_files"][str(k)] for k in (3, 11)):
                        raise ValueError(
                            "Application or parameter directory changed; capture and review again."
                        )
                    output, compilation = self.compile(options, files)
                    if (
                        compilation["configuration_guard"]
                        != body["compilation"]["configuration_guard"]
                        or time.monotonic() >= plan["expires"]
                    ):
                        raise ValueError(
                            "Saved configuration changed or the sensor review expired."
                        )
                    await self.live_guard(session, options, compilation)
                    capacity = int(await native.input_atomic(session, "file,3", 3380, Unsigned))
                    if not len(output) <= capacity <= 2 * 1024 * 1024:
                        raise ValueError("The sensor trial exceeds verified application capacity.")
                    receipt_id = secrets.token_hex(16)
                    filename = receipt_id + "-sensor-application.bin"
                    private_write(native.storage.capture_folder(backup["id"]) / filename, output)
                    intent = native.storage.intent(
                        {
                            "id": receipt_id,
                            "operation_id": confirmation.operation_id,
                            "operation_profile": PROFILE,
                            "change_kind": "sensor-definition",
                            "sensor_action": options.action,
                            "target": native.target(options),
                            "identity": actual,
                            "connector_config": body["connector_config"],
                            "old_instance": ObjectIdentifier(options.device)[1],
                            "new_instance": ObjectIdentifier(options.device)[1],
                            "old_name": actual["object-name"],
                            "new_name": actual["object-name"],
                            "backup_id": backup["id"],
                            "review_sha256": plan["digest"],
                            "trial_receipt": options.trial_receipt,
                            "edit": options.edit.model_dump()
                            if options.edit is not None
                            else self.origin(options.trial_receipt, options)["intent"]["edit"],
                            "compilation": compilation,
                            "payload_filename": filename,
                            "payload_sha256": sha(output),
                            "native_payload_sha256": sha(MoiIdentity(output).data),
                        }
                    )

                    def before(stage, detail):
                        def dispatch(packet):
                            nonlocal dispatched
                            PropertyEvidence(native.path).guard(session)
                            if (
                                stage == "dispatch-start-restore"
                                and time.monotonic() >= plan["expires"]
                            ):
                                raise ValueError(
                                    "The sensor review expired before restore dispatch."
                                )
                            native.storage.event(
                                intent["id"], stage, {**detail, "invoke_id": packet.apduInvokeID}
                            )
                            dispatched = True

                        return dispatch

                    from .native_applications import RESTORE_PREPARATION_SECONDS

                    native.phase("starting reviewed sensor application restore")
                    await native.files.state(
                        session,
                        "start-restore",
                        password=native.credentials.get()["restore"],
                        before_send=before("dispatch-start-restore", {}),
                    )
                    await asyncio.sleep(RESTORE_PREPARATION_SECONDS)
                    native.phase("transferring reviewed sensor application")
                    await native.files.write(
                        session,
                        3,
                        output,
                        chunk=chunk,
                        before_send=lambda detail, packet: before("dispatch-block", detail)(packet),
                    )
                    await native.files.state(
                        session, "end-restore", before_send=before("dispatch-end-restore", {})
                    )
                    if not (await native.wait_for_restore_readiness(session, intent))["ready"]:
                        raise ValueError(
                            "The sensor application has not recovered operation; read back its receipt."
                        )
                    result.update(await self.verify(session, options, intent))
        except (ValueError, OSError, TimeoutError, sqlite3.Error, asyncio.CancelledError) as exc:
            result["errors"].append((str(exc) or type(exc).__name__)[:512])
        result["may_have_applied"] = dispatched
        if result["status"] != "verified":
            result["status"] = "unknown" if dispatched else "not_sent"
        if intent is None:
            return {"intent": None, "result": result, "pending": False, "events": []}
        return native.storage.finish(
            intent["id"], {**result, "intent_sha256": intent["evidence_sha256"]}
        )

    async def readback(self, options):
        receipt = self.checked_receipt(options)
        native, intent = self.native, receipt["intent"]
        async with native.operation(options.operation_id, "sensor-definition-readback"):
            native.instances._endpoint(options, native.bacnet.require())
            async with native.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                result = await self.verify(session, options, intent, allow_original=True)
        return native.storage.resolve(intent["id"], result)

    async def observe(self, options):
        receipt = self.checked_receipt(options)
        intent, native = receipt["intent"], self.native
        if receipt["pending"] or intent["sensor_action"] != "install":
            raise ValueError("Read back a completed installed trial before observing its sensors.")
        if any(e["stage"] == "sensor-trial-restored" for e in receipt["events"]):
            raise ValueError("This NetSensor trial has already been restored.")
        async with native.operation(options.operation_id, "sensor-definition-observe"):
            async with native.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                native.phase("reading controller identity before sensor observation")
                actual, _ = await native.identity(session, options.device)
                if actual != intent["identity"]:
                    raise ValueError("The controller identity/firmware differs from the trial.")
                readings = []
                for row in intent["compilation"]["trial_points"]:
                    native.phase(f"reading NetSensor trial at SA address {row['address']}")
                    reading = {**row, "observed_at": utc(), "status": "unconfirmed", "errors": []}
                    try:
                        for pid, dtype, name in [
                            (2858, Unsigned, "address"),
                            (673, Boolean, "enabled"),
                            (913, Boolean, "offline"),
                        ]:
                            value = await native.input_atomic(
                                session, row["device_object"], pid, dtype
                            )
                            reading[name] = bool(value) if dtype is Boolean else int(value)
                        for pid, dtype, name in [
                            (75, ObjectIdentifier, "object_id"),
                            (77, CharacterString, "name"),
                            (85, Real, "temperature"),
                            (103, Enumerated, "reliability"),
                            (81, Boolean, "out_of_service"),
                            (117, Enumerated, "units"),
                            (32527, CharacterString, "item_reference"),
                        ]:
                            value = await native.input_atomic(
                                session, row["temperature_object"], pid, dtype
                            )
                            reading[name] = (
                                str(value)
                                if dtype in (ObjectIdentifier, CharacterString)
                                else bool(value)
                                if dtype is Boolean
                                else float(value)
                                if dtype is Real
                                else int(value)
                            )
                        identity_ok = (
                            reading["object_id"] == row["temperature_object"]
                            and reading["name"] == row["temperature_name"]
                            and reading["address"] == row["address"]
                            and reading["units"] == row["units"]
                            and reading["item_reference"] == row["temperature_ref"]
                        )
                        if not identity_ok:
                            raise ValueError(
                                "Independent sensor/point identity differs from the owned trial."
                            )
                        flags = list(
                            await native.input_atomic(
                                session, row["temperature_object"], 111, StatusFlags
                            )
                        )
                        reading["status_flags"] = flags
                        reading["status"] = (
                            "live"
                            if reading["enabled"]
                            and not reading["offline"]
                            and reading["reliability"] == 0
                            and not reading["out_of_service"]
                            and len(flags) == 4
                            and not any(flags[1:])
                            and math.isfinite(reading["temperature"])
                            else "unreliable"
                        )
                    except (ValueError, OSError, TimeoutError) as exc:
                        reading["errors"].append((str(exc) or type(exc).__name__)[:256])
                    readings.append(reading)
                result = {
                    "profile": PROFILE,
                    "receipt_id": intent["id"],
                    "read_only": True,
                    "target": intent["target"],
                    "identity": actual,
                    "readings": readings,
                    "observed_at": utc(),
                    "physical_behavior_verified": False,
                }
                native.storage.event(intent["id"], "sensor-trial-observation", result)
                return result


def sensor_trial_router(service):
    router = APIRouter(prefix="/api/bacnet/controller/native-application/sensor-trial")

    @router.get("/status")
    def status():
        return service.status()

    @router.post("/source")
    def source(body: SensorSource):
        return service.source(body)

    @router.post("/support")
    async def support(body: SensorSupport):
        return await service.support(body)

    @router.post("/copy-review")
    def copy_review(body: SensorCopy):
        return service.copy(body)[1]

    @router.post("/copy-export")
    def copy_export(body: SensorCopy):
        if body.expected_review_sha256 is None:
            raise ValueError("Review this exact local sensor copy before exporting it.")
        output, review = service.copy(body)
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="netsensor-trial-copy.moz"',
                "X-Content-SHA256": review["output_sha256"],
            },
        )

    @router.post("/preview")
    async def preview(body: SensorPreview):
        return await service.preview(body)

    @router.post("/apply")
    async def apply(body: SensorApply):
        return await service.apply(body)

    @router.post("/readback")
    async def readback(body: SensorReceipt):
        return await service.readback(body)

    @router.post("/observe")
    async def observe(body: SensorReceipt):
        return await service.observe(body)

    @router.post("/cancel")
    async def cancel(body: InstanceCancel):
        service.cancel(body.operation_id)
        return service.native.cancel(body.operation_id)

    return router
