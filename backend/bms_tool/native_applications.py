"""Connected native application identity commissioning, without a vendor runtime."""

import asyncio
import copy
import secrets
import sqlite3
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from bacpypes3.apdu import ReadPropertyACK, ReadPropertyRequest
from bacpypes3.primitivedata import ObjectIdentifier, Unsigned
from fastapi import APIRouter, Response
from pydantic import Field, SecretStr, StrictBool

from .application_files import ApplicationFiles
from .application_store import (
    PROFILE,
    ApplicationCredentials,
    ApplicationStore,
    evidence,
    private_write,
    utc,
)
from .device_details import DeviceDetailsRequest
from .device_instance import InstanceApply, InstanceCancel, InstancePreview, InstanceReconcile
from .mce_wire import VENDOR, MceWire, controller_info
from .models import StrictModel
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .property_evidence import PropertyEvidence

PLAN_SECONDS = 180
# Objects-only restore acknowledges before application storage is ready.
RESTORE_PREPARATION_SECONDS = 5.0
SCOPE = (
    "Edit the connected controller application Device identity. Capture the original application "
    "and parameter files; merge fresh saved parameters; transfer only the application File; "
    "then verify the Device identity and application readback at the same physical station."
)


class NativeCapture(DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class NativePreview(InstancePreview):
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class NativeApply(InstanceApply):
    application_transfer_confirmed: StrictBool


class NativeCredentials(StrictModel):
    backup: SecretStr
    restore: SecretStr


class NativeApplications:
    id = "mce-native-application"

    def __init__(
        self, bacnet, store, instances, *, operation_timeout=300, request_timeout=4, gap=0.02
    ):
        self.bacnet, self.store, self.instances = bacnet, store, instances
        self.path = instances.path
        self.files = ApplicationFiles(
            self.path, writable_files={3}, timeout=request_timeout, gap=gap
        )
        self.wire = MceWire(self.path)
        self.wire.transport.timeout = request_timeout
        self.storage = ApplicationStore(store)
        self.credentials = ApplicationCredentials(store.directory)
        self.operation_timeout = operation_timeout
        self.active, self.plans, self.cancelled = None, OrderedDict(), set()

    def status(self):
        receipts = self.storage.receipts(include_events=False)
        return {
            "profile": PROFILE,
            "connected": self.bacnet.status()["connected"],
            "credentials_configured": self.credentials.configured(),
            "vendor_runtime_required": False,
            "scope": SCOPE,
            "active": (
                {k: v for k, v in self.active.items() if k != "task"} if self.active else None
            ),
            "receipts": [
                {
                    "id": r["intent"]["id"],
                    "target": r["intent"]["target"],
                    "old_instance": r["intent"]["old_instance"],
                    "new_instance": r["intent"]["new_instance"],
                    "status": (r.get("latest_readback") or r["result"] or r["intent"])["status"],
                    "pending": r["pending"],
                    "created_at": r["intent"]["created_at"],
                }
                for r in receipts
            ],
        }

    def has_pending(self):
        with self.store.connect() as db:
            return bool(
                db.execute("SELECT 1 FROM application_transfers WHERE pending=1 LIMIT 1").fetchone()
            )

    def cancel(self, operation_id):
        InstanceCancel(operation_id=operation_id)
        self.cancelled.add(operation_id)
        if len(self.cancelled) > 128:
            self.cancelled.pop()
        self.plans = OrderedDict(
            (k, p) for k, p in self.plans.items() if p["operation_id"] != operation_id
        )
        active = self.active is not None and self.active["operation_id"] == operation_id
        if active:
            self.active["task"].cancel()
        return {
            "cancel_requested": active,
            "note": "Cancellation cannot undo a dispatched application transfer.",
        }

    async def close(self):
        self.plans.clear()
        if self.active:
            task = self.active["task"]
            self.cancel(self.active["operation_id"])
            if task is not asyncio.current_task():
                await asyncio.gather(task, return_exceptions=True)

    @asynccontextmanager
    async def operation(self, operation_id, kind):
        if self.active or operation_id in self.cancelled:
            raise ValueError(
                "Native application operation is busy or cancelled; use a fresh operation ID."
            )
        self.active = {
            "operation_id": operation_id,
            "kind": kind,
            "phase": "preflight",
            "task": asyncio.current_task(),
        }
        try:
            async with asyncio.timeout(self.operation_timeout):
                yield
        except asyncio.CancelledError as exc:
            raise ValueError(
                "Native operation cancelled. Consult retained transfer receipts before any further write."
            ) from exc
        except TimeoutError as exc:
            raise ValueError(
                "Native operation timed out. Consult retained transfer receipts before any further write."
            ) from exc
        finally:
            self.active = None

    @staticmethod
    def target(options):
        return options.model_dump(include={"address", "router", "dnet"})

    def available(self, options):
        target = self.target(options)
        self.instances._available(target)
        self.storage.available(target)
        self.instances._endpoint(options, self.bacnet.require())

    def phase(self, phase):
        if self.active:
            self.active["phase"] = phase

    async def identity(self, session, device):
        identity = await self.instances._identity(session, device)
        if identity["vendor-identifier"] != VENDOR:
            raise ValueError(
                "This station does not expose the installed native application protocol family."
            )
        info = await controller_info(self.wire, session, device)
        if info["name"] != identity["object-name"]:
            raise ValueError("Native and standard controller identities disagree.")
        return identity, info

    async def capture_session(self, options, session, *, identity=None):
        self.phase("capturing original application and saved parameters")
        if identity is None:
            identity, info = await self.identity(session, options.device)
        else:
            info = await controller_info(self.wire, session, options.device)
        max_apdu = int(await self.path._read(session, options.device, "max-apdu-length-accepted"))
        if not 128 <= max_apdu <= 65535:
            raise ValueError("Unsupported application transfer APDU size.")
        chunk = min(416, max_apdu - 64)
        if str(await self.path._read(session, "file,3", "file-type")).lower() not in (
            ".moi",
            ".moz",
        ):
            raise ValueError("The native application File has an unsupported format.")
        secrets_config = self.credentials.get()
        files, started, cleanup_error = {}, False, None
        try:
            await self.files.state(session, "start-backup", password=secrets_config["backup"])
            started = True
            for file_id in (11, 12, 3):
                self.phase(f"capturing backup File {file_id}")
                files[file_id] = await self.files.read(session, file_id, chunk=chunk)
        finally:
            if started:
                try:
                    await self.files.state(session, "end-backup")
                except (
                    ValueError,
                    TimeoutError,
                    OSError,
                    sqlite3.Error,
                    asyncio.CancelledError,
                ) as exc:
                    cleanup_error = str(exc) or "Backup completion was not confirmed."
        if cleanup_error:
            raise ValueError(
                "Original files read, but ending the backup session was not confirmed: "
                + cleanup_error
            )
        application, source_error = {}, None
        try:
            editor = MoiIdentity(files[3])
            application = editor.summary()
            if editor.instance != ObjectIdentifier(options.device)[1]:
                raise ValueError(
                    "Captured application identity differs from the responding controller."
                )
            if (
                application["model"] != identity["model-name"]
                or application["name"] != identity["object-name"]
            ):
                raise ValueError(
                    "Captured application model or name differs from the responding controller. An instance edit must not replace those settings."
                )
        except ValueError as exc:
            source_error = str(exc)
        if await self.instances._identity(session, options.device) != identity:
            raise ValueError("Controller identity changed during native backup.")
        # Retain original bytes before attempting any compiler interpretation.
        receipt = self.storage.save(
            {
                "target": self.target(options),
                "device": options.device,
                "identity": identity,
                "native_info": info,
                "connector_config": session["config"],
                "application": application,
                "source_identity_matches": source_error is None,
                "source_identity_error": source_error,
                "read_only": True,
                "vendor_runtime_required": False,
            },
            files,
        )
        return receipt, files, min(384, max_apdu - 64)

    async def capture(self, **arguments):
        options = NativeCapture(**arguments)
        async with self.operation(options.operation_id, "capture"):
            self.available(options)
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                receipt, files, _ = await self.capture_session(options, session)
            try:
                if not receipt["source_identity_matches"]:
                    raise ValueError(receipt["source_identity_error"])
                _, receipt["parameter_merge"] = ParameterApplication(
                    files[3], files[11], files[12]
                ).compile()
                receipt["instance_edit_supported"] = True
            except ValueError as exc:
                receipt.update(instance_edit_supported=False, compiler_error=str(exc))
            source_digest = receipt.pop("evidence_sha256")
            return evidence({**receipt, "snapshot_evidence_sha256": source_digest})

    def check_capture(self, options):
        receipt, files = self.storage.load(options.capture_id)
        if (
            receipt["target"] != self.target(options)
            or receipt["device"] != options.device
            or receipt["connector_config"] != self.bacnet.config
        ):
            raise ValueError(
                "Select a backup captured from this exact controller route and interface."
            )
        if not receipt.get("source_identity_matches"):
            raise ValueError(
                receipt.get("source_identity_error")
                or "Capture this controller again before reviewing its application."
            )
        return receipt, files

    @staticmethod
    def compile(files, new_instance):
        merged, parameters = ParameterApplication(files[3], files[11], files[12]).compile()
        editor = MoiIdentity(merged)
        q = {
            "source_sha256": editor.source_sha256,
            "expected_instance": editor.instance,
            "new_instance": new_instance,
        }
        edit = editor.preview(**q)
        output, edits = editor.export(**q, plan_sha256=edit["plan_sha256"])
        return output, {"parameters": parameters, "identity_edit": edits}

    async def preview(self, **arguments):
        options = NativePreview(**arguments)
        if ObjectIdentifier(options.device)[1] == options.new_instance:
            raise ValueError("Choose a different reserved Device instance.")
        async with self.operation(options.operation_id, "review"):
            self.available(options)
            captured, files = self.check_capture(options)
            output, compilation = self.compile(files, options.new_instance)
            config, app = copy.deepcopy(self.bacnet.config), self.bacnet.require()
            if options.new_instance == config["instance"]:
                raise ValueError("The proposed instance belongs to this engineering client.")
            collision = await self.instances._collision(options)
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                actual, _ = await self.identity(session, options.device)
            if actual != captured["identity"]:
                raise ValueError("Controller identity changed after backup; capture again.")
            body = {
                "profile": PROFILE,
                "target": self.target(options),
                "identity": actual,
                "old_instance": ObjectIdentifier(options.device)[1],
                "new_instance": options.new_instance,
                "capture_id": options.capture_id,
                "snapshot_sha256": captured["evidence_sha256"],
                "application_sha256": sha(files[3]),
                "static_parameters_sha256": sha(files[11]),
                "compilation": compilation,
                "payload_sha256": sha(output),
                "collision_check": collision,
                "parameter_policy": "Immediately before transfer, capture and merge fresh saved parameters. The application and parameter directory must still match this review.",
                "scope": SCOPE,
                "vendor_runtime_required": False,
                "can_apply": not collision["devices"],
                "connector_config": config,
                "created_at": utc(),
                "expires_at": (datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)).isoformat(),
            }
            token, digest = secrets.token_urlsafe(24), seal(body)
            self.plans = OrderedDict(
                (k, p)
                for k, p in self.plans.items()
                if p["body"]["target"] != body["target"] and p["expires"] > time.monotonic()
            )
            self.plans[token] = {
                "body": body,
                "options": options,
                "app": app,
                "config": config,
                "expires": time.monotonic() + PLAN_SECONDS,
                "digest": digest,
                "credentials_digest": seal(self.credentials.get()),
                "operation_id": options.operation_id,
            }
            while len(self.plans) > 16:
                self.plans.popitem(last=False)
            return {**body, "token": token, "review_sha256": digest}

    async def verify(self, session, intent):
        self.phase("reading back the physical station")
        observed = await self.instances._observe(session, intent)
        result = {
            "status": "unknown",
            "readback": observed,
            "read_only": True,
            "observed_at": utc(),
        }
        identity = observed.get("identity")
        if identity is not None:
            try:
                status = int(await self.path._read(session, identity["device"], "system-status"))
                result.update(system_status=status, operational=status == 0)
            except (ValueError, TimeoutError, OSError) as exc:
                result["error"] = (
                    "Controller operational status could not be read: " + str(exc)[:256]
                )
                return result
        if observed["status"] != "verified_new":
            return result
        if not result.get("operational"):
            result["error"] = "The new identity responds, but the controller is not operational."
            return result
        options = DeviceDetailsRequest(
            **intent["target"], device=f"device,{intent['new_instance']}"
        )
        try:
            backup, files, _ = await self.capture_session(
                options, session, identity=observed["identity"]
            )
            digest = sha(MoiIdentity(files[3]).data)
            result.update(
                verification_capture_id=backup["id"],
                native_sha256=digest,
                expected_native_sha256=intent["native_payload_sha256"],
            )
            if digest == intent["native_payload_sha256"]:
                status = int(await self.path._read(session, options.device, "system-status"))
                result.update(system_status=status, operational=status == 0)
                if status == 0:
                    result["status"] = "verified"
                    self.instances._forget_old_address(session)
                else:
                    result["error"] = (
                        "Application bytes match, but the controller is not operational."
                    )
            else:
                result["error"] = (
                    "Device identity changed, but application bytes do not match the transmitted application."
                )
        except (ValueError, TimeoutError, OSError) as exc:
            result["error"] = (str(exc) or "Application readback timed out.")[:512]
        return result

    async def apply(self, **arguments):
        request = NativeApply(**arguments)
        plan = self.plans.pop(request.token, None)
        if not plan or plan["digest"] != request.review_sha256 or not plan["body"]["can_apply"]:
            raise ValueError(
                "Native application review is changed, blocked, expired or already consumed."
            )
        if not request.allocation_confirmed or not request.application_transfer_confirmed:
            raise ValueError("Confirm the reserved number and reviewed application transfer.")
        body, options = plan["body"], plan["options"]
        receipt_id, intent, dispatched = secrets.token_hex(16), None, False
        result = {
            "status": "not_sent",
            "may_have_applied": False,
            "protocol_accepted": False,
            "errors": [],
        }
        try:
            async with self.operation(request.operation_id, "apply"):
                self.available(options)
                if (
                    self.bacnet.require() is not plan["app"]
                    or self.bacnet.config != plan["config"]
                    or time.monotonic() >= plan["expires"]
                ):
                    raise ValueError("Interface or review changed; review again.")
                if seal(self.credentials.get()) != plan["credentials_digest"]:
                    raise ValueError("Transfer credentials changed; review again.")
                collision = await self.instances._collision(options)
                if collision["devices"]:
                    raise ValueError(
                        "The proposed number answered the fresh collision query. No transfer was sent."
                    )
                async with self.path._path(options) as session:
                    PropertyEvidence.pin(session, options.router)
                    actual, _ = await self.identity(session, options.device)
                    if actual != body["identity"]:
                        raise ValueError("Controller identity changed after review.")
                    backup, files, chunk = await self.capture_session(
                        options, session, identity=actual
                    )
                    if (
                        sha(files[3]) != body["application_sha256"]
                        or sha(files[11]) != body["static_parameters_sha256"]
                    ):
                        raise ValueError(
                            "Application or saved parameter directory changed after review. Capture and review again."
                        )
                    output, compilation = self.compile(files, options.new_instance)
                    capacity_request = ReadPropertyRequest(
                        objectIdentifier=(10, 3), propertyIdentifier=3380
                    )
                    capacity_reply = await self.files.exchange(
                        session, capacity_request, ReadPropertyACK
                    )
                    if (
                        capacity_reply.objectIdentifier != capacity_request.objectIdentifier
                        or capacity_reply.propertyIdentifier != capacity_request.propertyIdentifier
                        or capacity_reply.propertyArrayIndex is not None
                    ):
                        raise ValueError("Application capacity reply does not match its request.")
                    capacity = int(capacity_reply.propertyValue.cast_out(Unsigned))
                    if capacity <= 0 or len(output) > capacity:
                        raise ValueError(
                            "Compiled application exceeds the controller-reported application capacity."
                        )
                    # Durable payload and original backup exist before the first restore request.
                    private_folder = self.storage.directory / backup["id"]
                    private_write(private_folder / "reviewed-application.bin", output)
                    self.available(options)
                    if (
                        self.bacnet.require() is not plan["app"]
                        or self.bacnet.config != plan["config"]
                        or time.monotonic() >= plan["expires"]
                        or seal(self.credentials.get()) != plan["credentials_digest"]
                    ):
                        raise ValueError(
                            "Native application review or credentials changed during preflight. Review again."
                        )
                    intent = self.storage.intent(
                        {
                            **{
                                k: body[k]
                                for k in (
                                    "target",
                                    "identity",
                                    "old_instance",
                                    "new_instance",
                                    "connector_config",
                                )
                            },
                            "id": receipt_id,
                            "operation_id": request.operation_id,
                            "review_sha256": request.review_sha256,
                            "review_capture_id": body["capture_id"],
                            "backup_id": backup["id"],
                            "payload_sha256": sha(output),
                            "native_payload_sha256": sha(MoiIdentity(output).data),
                            "compilation": compilation,
                            "collision_check": collision,
                            "allocation_confirmed": True,
                            "application_transfer_confirmed": True,
                        }
                    )

                    def before(stage, detail):
                        def dispatch(packet):
                            nonlocal dispatched
                            PropertyEvidence(self.path).guard(session)
                            self.storage.event(
                                receipt_id,
                                stage,
                                {
                                    **detail,
                                    "invoke_id": packet.apduInvokeID,
                                    "service": packet.apduService,
                                },
                            )
                            dispatched = True

                        return dispatch

                    self.phase("starting reviewed application restore")
                    await self.files.state(
                        session,
                        "start-restore",
                        password=self.credentials.get()["restore"],
                        before_send=before("dispatch-start-restore", {}),
                    )
                    self.storage.event(
                        receipt_id, "ack-start-restore", session["last_application_wire"]
                    )
                    self.phase("preparing controller application storage")
                    self.storage.event(
                        receipt_id,
                        "restore-preparation-start",
                        {"wait_seconds": RESTORE_PREPARATION_SECONDS},
                    )
                    await asyncio.sleep(RESTORE_PREPARATION_SECONDS)
                    self.path._guard(session)
                    self.storage.event(receipt_id, "restore-preparation-finished", {})
                    self.phase("transferring reviewed application")

                    def block(detail, packet):
                        before("dispatch-application-block", detail)(packet)

                    transfer = await self.files.write(
                        session, 3, output, before_send=block, chunk=chunk
                    )
                    self.storage.event(receipt_id, "application-file-acknowledged", transfer)
                    self.phase("committing reviewed application")
                    await self.files.state(
                        session, "end-restore", before_send=before("dispatch-end-restore", {})
                    )
                    self.storage.event(
                        receipt_id, "ack-end-restore", session["last_application_wire"]
                    )
                    result.update(protocol_accepted=True, may_have_applied=True)
                    await asyncio.sleep(1)
                    verified = await self.verify(session, intent)
                    result.update(verified)
        except (ValueError, TimeoutError, OSError, sqlite3.Error, asyncio.CancelledError) as exc:
            result["errors"].append((str(exc) or "Native operation cancelled or timed out.")[:512])
        result["may_have_applied"] = dispatched
        if result["status"] != "verified":
            result["status"] = "unknown" if dispatched else "not_sent"
        if intent is None:
            return {
                "intent": None,
                "result": {**result, "finished_at": utc()},
                "pending": False,
                "events": [],
            }
        result["intent_sha256"] = intent["evidence_sha256"]
        try:
            return self.storage.finish(receipt_id, result)
        except (ValueError, OSError, sqlite3.Error) as exc:
            result["errors"].append("Final receipt could not be saved: " + str(exc)[:256])
            return {"intent": intent, "result": result, "pending": True, "events": []}

    async def reconcile(self, **arguments):
        request = InstanceReconcile(**arguments)
        receipt = self.storage.receipt(request.receipt_id)
        intent = receipt["intent"]
        options = DeviceDetailsRequest(**intent["target"], device=intent["identity"]["device"])
        async with self.operation(request.operation_id, "readback"):
            self.instances._endpoint(options, self.bacnet.require())
            if self.bacnet.config.get("local_address") != intent["connector_config"].get(
                "local_address"
            ):
                raise ValueError("Reconnect the receipt original local interface for readback.")
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                result = await self.verify(session, intent)
            return self.storage.resolve(request.receipt_id, result)


def native_application_router(service):
    router = APIRouter(prefix="/api/bacnet/controller/native-application")

    @router.get("/status")
    def status():
        return service.status()

    @router.post("/credentials")
    async def credentials(body: NativeCredentials):
        if service.active:
            raise ValueError("Finish the active native operation before changing credentials.")
        service.plans.clear()
        return service.credentials.set(
            body.backup.get_secret_value(), body.restore.get_secret_value()
        )

    @router.post("/capture")
    async def capture(body: NativeCapture):
        return await service.capture(**body.model_dump())

    @router.post("/preview")
    async def preview(body: NativePreview):
        return await service.preview(**body.model_dump())

    @router.post("/apply")
    async def apply(body: NativeApply):
        return await service.apply(**body.model_dump())

    @router.post("/cancel")
    async def cancel(body: InstanceCancel):
        return service.cancel(body.operation_id)

    @router.post("/readback")
    async def readback(body: InstanceReconcile):
        return await service.reconcile(**body.model_dump())

    @router.get("/receipts/{identifier}")
    def receipt(identifier: str):
        return service.storage.receipt(identifier)

    @router.get("/backups/{identifier}")
    def backup(identifier: str):
        return Response(
            service.storage.export(identifier),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="native-backup-{identifier}.zip"'
            },
        )

    return router
