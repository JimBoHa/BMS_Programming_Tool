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
from pydantic import Field, SecretStr, StrictBool, field_validator

from .application_files import ApplicationFiles
from .application_preservation import verify_preservation
from .application_store import (
    PROFILE,
    ApplicationCredentials,
    ApplicationStore,
    evidence,
    native_storage_profile,
    private_write,
    utc,
)
from .device_details import DeviceDetailsRequest
from .device_instance import InstanceApply, InstanceCancel, InstancePreview, InstanceReconcile
from .mce_wire import VENDOR, MceWire, controller_info
from .models import StrictModel
from .moi_identity import MoiIdentity, controller_name, seal, sha
from .moi_parameters import ParameterApplication
from .native_backup_records import BackupInspectionSource, NativeBackupRecords
from .native_boolean_recovery import PROFILE as BOOLEAN_RECOVERY_PROFILE
from .native_boolean_recovery import NativeBooleanRecovery
from .native_boolean_transfer import PROFILE as BOOLEAN_DEFAULT_PROFILE
from .native_boolean_transfer import SCOPE as BOOLEAN_DEFAULT_SCOPE
from .native_boolean_transfer import (
    BooleanTransferPreview,
    compile_boolean_default,
    verify_boolean_preservation,
)
from .native_connection_transfer import PROFILE as CONNECTION_PROFILE
from .native_connection_transfer import SCOPE as CONNECTION_SCOPE
from .native_connection_transfer import (
    ConnectionTransferApply,
    ConnectionTransferPreview,
    NativeConnectionOperations,
    compile_connection,
    validate_connection_evidence,
    verify_connection_preservation,
)
from .native_default_recovery import PROFILE as RECOVERY_PROFILE
from .native_default_recovery import DefaultRecoveryPrepare, NativeDefaultRecovery
from .native_default_transfer import (
    PROFILE as DEFAULT_PROFILE,
)
from .native_default_transfer import (
    SCOPE as DEFAULT_SCOPE,
)
from .native_default_transfer import (
    DefaultTransferApply,
    DefaultTransferPreview,
    compile_default,
    verify_default_preservation,
)
from .native_enum_recovery import PROFILE as ENUM_RECOVERY_PROFILE
from .native_enum_recovery import NativeEnumRecovery
from .native_enum_transfer import PROFILE as ENUM_DEFAULT_PROFILE
from .native_enum_transfer import SCOPE as ENUM_DEFAULT_SCOPE
from .native_enum_transfer import (
    EnumTransferPreview,
    compile_enum_default,
    verify_enum_preservation,
)
from .native_historical_wire_recovery import PROFILE as HISTORICAL_WIRE_RECOVERY_PROFILE
from .native_historical_wire_recovery import NativeHistoricalWireRecovery
from .native_input_transfer import NativeInputOperations
from .native_inputs import (
    TERMINAL_PROFILE,
    InputApply,
    InputCopy,
    InputLocalSource,
    InputPreview,
    InputSupport,
    compile_input,
    input_operation_profile,
    verify_input_preservation,
)
from .native_instance_recovery import PROFILE as INSTANCE_RECOVERY_PROFILE
from .native_instance_recovery import NativeInstanceRecovery
from .native_name_recovery import PROFILE as NAME_RECOVERY_PROFILE
from .native_name_recovery import NativeNameRecovery
from .native_parameter_qualification import qualify_parameter_additions
from .native_point_name_recovery import PROFILE as POINT_NAME_RECOVERY_PROFILE
from .native_point_name_recovery import NativePointNameRecovery
from .native_point_names import PROFILE as POINT_NAME_PROFILE
from .native_point_names import SCOPE as POINT_NAME_SCOPE
from .native_point_names import (
    PointNameApply,
    PointNameCompiler,
    PointNameEdit,
    PointNamePreview,
    PointNameSource,
    compile_point_name,
    verify_point_name_preservation,
)
from .native_runtime_calibration import read_runtime_calibration
from .native_terminal_recovery import NativeTerminalRecovery
from .native_terminal_recovery_transfer import TerminalRecoveryPreview
from .native_terminal_recovery_transfer import recovery_origin as terminal_recovery_origin
from .native_terminal_recovery_transfer import validate_plan as validate_terminal_recovery_plan
from .native_wire_compiler import EffectiveWirePreview
from .native_wire_recovery import PROFILE as WIRE_RECOVERY_PROFILE
from .native_wire_transfer import PROFILE as WIRE_PROFILE
from .native_wire_transfer import SCOPE as WIRE_SCOPE
from .native_wire_transfer import (
    WireTransferApply,
    WireTransferPreview,
    compile_wire,
    validate_wire_evidence,
    verify_wire_preservation,
)
from .property_evidence import PropertyEvidence

# A routed native backup consists of many separately acknowledged File chunks.
# Allow a fresh backup to finish inside the review window on slower trunks, and
# reserve a separate operation budget for backup + transfer + verified readback.
# Per-request deadlines, single dispatch and the pre-restore expiry guard remain.
PLAN_SECONDS = 15 * 60
OPERATION_SECONDS = 30 * 60
# Objects-only restore acknowledges before application storage is ready.
RESTORE_PREPARATION_SECONDS = 5.0
# End-restore acknowledges storage before a controller necessarily answers
# property reads. Poll only reads; never repeat a restore or application block.
RESTORE_READINESS_SECONDS = 60.0
RESTORE_READINESS_INTERVAL = 2.0
SCOPE = (
    "Edit the connected controller application Device identity. Capture the original application "
    "and parameter files; merge fresh saved parameters; transfer only the application File; "
    "then verify the Device identity and application readback at the same physical station. "
    "Backup capture and application readback enter and end controller backup mode."
)


def backup_effects():
    """Declare possible services for backup phases, not actual dispatch evidence."""
    return {
        "profile": "jci-native-backup-effects/1",
        "scope": "application capture and readback backup phase",
        "declaration": "possible-services",
        "state_service": "ReinitializeDevice",
        "possible_state_commands": ["start-backup", "end-backup"],
        "file_reads": [11, 12, 3],
        "writes_application": False,
    }


class NativeCapture(DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class NativePreview(InstancePreview):
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    new_name: str | None = Field(default=None, strict=True, max_length=128)

    @field_validator("new_name")
    @classmethod
    def valid_name(cls, value):
        return controller_name(value) if value is not None else None


class NativeApply(InstanceApply):
    application_transfer_confirmed: StrictBool
    name_change_confirmed: StrictBool = False


class NativeNameRecoveryPreview(NativePreview):
    new_name: str = Field(strict=True, max_length=128)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recovery_parent_receipt: str = Field(pattern=r"^[0-9a-f]{32}$")
    recovery_origin_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class NativeInstanceRecoveryPreview(NativePreview):
    new_name: None = None
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recovery_parent_receipt: str = Field(pattern=r"^[0-9a-f]{32}$")
    recovery_origin_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class NativeCredentials(StrictModel):
    backup: SecretStr
    restore: SecretStr


class NativeApplications(NativeConnectionOperations, NativeInputOperations):
    id = "mce-native-application"

    def __init__(
        self,
        bacnet,
        store,
        instances,
        *,
        operation_timeout=OPERATION_SECONDS,
        request_timeout=4,
        gap=0.02,
    ):
        self.bacnet, self.store, self.instances = bacnet, store, instances
        self.path = instances.path
        self.files = ApplicationFiles(
            self.path, writable_files={3}, timeout=request_timeout, gap=gap
        )
        self.wire = MceWire(self.path)
        self.wire.transport.timeout = request_timeout
        self.storage = ApplicationStore(store)
        self.default_recovery = NativeDefaultRecovery(NativeBackupRecords(self.storage))
        self.boolean_recovery = NativeBooleanRecovery(NativeBackupRecords(self.storage))
        self.enum_recovery = NativeEnumRecovery(NativeBackupRecords(self.storage))
        self.wire_recovery = NativeHistoricalWireRecovery(NativeBackupRecords(self.storage))
        self.name_recovery = NativeNameRecovery(NativeBackupRecords(self.storage), self.compile)
        self.point_name_recovery = NativePointNameRecovery(NativeBackupRecords(self.storage))
        self.instance_recovery = NativeInstanceRecovery(
            NativeBackupRecords(self.storage), self.compile
        )
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
            "point_name_transfer_profile": POINT_NAME_PROFILE,
            "point_name_transfer_scope": POINT_NAME_SCOPE,
            "default_transfer_profile": DEFAULT_PROFILE,
            "default_transfer_scope": DEFAULT_SCOPE,
            "real_default_recovery_profile": RECOVERY_PROFILE,
            "boolean_default_recovery_profile": BOOLEAN_RECOVERY_PROFILE,
            "enum_default_recovery_profile": ENUM_RECOVERY_PROFILE,
            "wire_source_recovery_profile": WIRE_RECOVERY_PROFILE,
            "historical_wire_pin_recovery_profile": HISTORICAL_WIRE_RECOVERY_PROFILE,
            "controller_name_recovery_profile": NAME_RECOVERY_PROFILE,
            "point_name_recovery_profile": POINT_NAME_RECOVERY_PROFILE,
            "controller_instance_recovery_profile": INSTANCE_RECOVERY_PROFILE,
            "boolean_default_transfer_profile": BOOLEAN_DEFAULT_PROFILE,
            "boolean_default_transfer_scope": BOOLEAN_DEFAULT_SCOPE,
            "enum_default_transfer_profile": ENUM_DEFAULT_PROFILE,
            "enum_default_transfer_scope": ENUM_DEFAULT_SCOPE,
            "wire_source_transfer_profile": WIRE_PROFILE,
            "wire_source_transfer_scope": WIRE_SCOPE,
            "matching_connection_transfer_profile": CONNECTION_PROFILE,
            "matching_connection_transfer_scope": CONNECTION_SCOPE,
            "backup_effects": backup_effects(),
            "storage": native_storage_profile(),
            "limits": {
                "operation_seconds": self.operation_timeout,
                "review_seconds": PLAN_SECONDS,
                "request_seconds": self.files.timeout,
                "restore_readiness_seconds": RESTORE_READINESS_SECONDS,
                "restore_readiness_interval_seconds": RESTORE_READINESS_INTERVAL,
            },
            "active": (
                {k: v for k, v in self.active.items() if k != "task"} if self.active else None
            ),
            "receipts": [
                {
                    "id": r["intent"]["id"],
                    "target": r["intent"]["target"],
                    "old_instance": r["intent"]["old_instance"],
                    "new_instance": r["intent"]["new_instance"],
                    "change_kind": r["intent"].get("change_kind", "instance"),
                    "point_object_id": r["intent"].get("point_name_edit", {}).get("object_id"),
                    "old_name": r["intent"].get("old_name"),
                    "new_name": r["intent"].get("new_name"),
                    "default_edit": r["intent"].get("default_edit"),
                    **(
                        {
                            "input_edit": r["intent"]["input_edit"],
                            "operation_profile": r["intent"].get("operation_profile"),
                            "identity": r["intent"]["identity"],
                        }
                        if r["intent"].get("change_kind") == "input"
                        else {}
                    ),
                    **(
                        {"wire_edit": r["intent"].get("wire_edit")}
                        if r["intent"].get("change_kind") == "wire-source"
                        else {}
                    ),
                    **(
                        {
                            "connection_edit": r["intent"].get("connection_edit"),
                            "operation_profile": r["intent"].get("operation_profile"),
                        }
                        if r["intent"].get("change_kind") == "connection"
                        else {}
                    ),
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
        deadline = None
        try:
            deadline = asyncio.timeout(self.operation_timeout)
            async with deadline:
                yield
        except asyncio.CancelledError as exc:
            raise ValueError(
                "Native operation cancelled. Consult retained transfer receipts before any further write."
                + (" " + str(exc) if str(exc) else "")
            ) from exc
        except TimeoutError as exc:
            detail = str(exc)
            if not detail and isinstance(exc.__cause__, asyncio.CancelledError):
                detail = str(exc.__cause__)
            raise ValueError(
                f"Native operation timed out. Last reported phase: {self.active['phase']}. "
                + (
                    "The overall operation time limit expired. "
                    if deadline is not None and deadline.expired()
                    else "The overall operation time limit did not expire. "
                )
                + "Consult retained transfer receipts before any further write."
                + (" " + detail if detail else "")
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
        self.storage.require_capture_capacity()
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
        files, started, cleanup_error, capture_error = {}, False, None, None
        try:
            await self.files.state(session, "start-backup", password=secrets_config["backup"])
            started = True
            for file_id in (11, 12, 3):
                self.phase(f"capturing backup File {file_id}")
                files[file_id] = await self.files.read(session, file_id, chunk=chunk)
        except (ValueError, TimeoutError, OSError, sqlite3.Error, asyncio.CancelledError) as exc:
            capture_error = exc
            raise
        finally:
            if started:
                self.phase("ending backup session")
                try:
                    await self.files.state(session, "end-backup")
                except (
                    ValueError,
                    TimeoutError,
                    OSError,
                    sqlite3.Error,
                    asyncio.CancelledError,
                ) as exc:
                    cleanup_error = str(exc) or "No backup completion reply"
                    if capture_error is not None:
                        message = (
                            "Native backup capture failed: "
                            + (str(capture_error) or type(capture_error).__name__)
                            + ". Ending the backup session was also not confirmed: "
                            + cleanup_error
                            + ". Check controller status and retained transfer receipts before another operation."
                        )
                        if isinstance(capture_error, asyncio.CancelledError):
                            raise asyncio.CancelledError(message) from capture_error
                        raise ValueError(message) from capture_error
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
                "read_only": False,
                "backup_effects": backup_effects(),
                "vendor_runtime_required": False,
            },
            files,
        )
        return receipt, files, min(384, max_apdu - 64)

    async def capture(self, **arguments):
        options = NativeCapture(**arguments)
        async with self.operation(options.operation_id, "capture"):
            self.available(options)
            self.storage.require_capture_capacity()
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                receipt, files, _ = await self.capture_session(options, session)
            try:
                if not receipt["source_identity_matches"]:
                    raise ValueError(receipt["source_identity_error"])
                merged, receipt["parameter_merge"] = ParameterApplication(
                    files[3], files[11], files[12]
                ).compile()
                receipt["parameter_transfer_qualification"] = qualify_parameter_additions(
                    merged, receipt["parameter_merge"]
                )
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
    def compile(files, new_instance, new_name=None):
        merged, parameters = ParameterApplication(files[3], files[11], files[12]).compile()
        qualification = qualify_parameter_additions(merged, parameters)
        editor = MoiIdentity(merged)
        q = {
            "source_sha256": editor.source_sha256,
            "expected_instance": editor.instance,
            "new_instance": new_instance,
        }
        if new_name is not None:
            q.update(expected_name=editor.summary()["name"], new_name=new_name)
        edit = editor.preview(**q)
        output, edits = editor.export(**q, plan_sha256=edit["plan_sha256"])
        return output, {
            "parameters": parameters,
            "identity_edit": edits,
            "parameter_transfer_qualification": qualification,
        }

    async def preview(self, **arguments):
        options = NativePreview(**arguments)
        return await self.preview_identity(options)

    async def preview_name_recovery(self, **arguments):
        options = NativeNameRecoveryPreview(**arguments)
        return await self.preview_identity(options)

    async def preview_instance_recovery(self, **arguments):
        options = NativeInstanceRecoveryPreview(**arguments)
        return await self.preview_identity(options)

    async def preview_identity(self, options):
        renaming = options.new_name is not None
        old_instance = ObjectIdentifier(options.device)[1]
        if renaming and options.new_instance != old_instance:
            raise ValueError("A name-only review must preserve the current instance.")
        if not renaming and old_instance == options.new_instance:
            raise ValueError("Choose a different reserved Device instance.")
        async with self.operation(options.operation_id, "review"):
            self.available(options)
            captured, files = self.check_capture(options)
            if renaming and options.new_name == captured["identity"]["object-name"]:
                raise ValueError("Choose a different controller name.")
            output, compilation = self.compile(files, options.new_instance, options.new_name)
            recovery = self.identity_recovery_origin(options, compilation, files)
            config, app = copy.deepcopy(self.bacnet.config), self.bacnet.require()
            if options.new_instance == config["instance"]:
                raise ValueError("The proposed instance belongs to this engineering client.")
            collision = self.name_scope() if renaming else await self.instances._collision(options)
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
                "change_kind": "name" if renaming else "instance",
                "old_name": actual["object-name"],
                "new_name": options.new_name if renaming else actual["object-name"],
                "capture_id": options.capture_id,
                "snapshot_sha256": captured["evidence_sha256"],
                "application_sha256": sha(files[3]),
                "static_parameters_sha256": sha(files[11]),
                "compilation": compilation,
                "payload_sha256": sha(output),
                "collision_check": collision,
                "parameter_policy": "Immediately before transfer, capture and merge fresh saved parameters. The application and parameter directory must still match this review.",
                "backup_effects": backup_effects(),
                "scope": SCOPE,
                "vendor_runtime_required": False,
                "can_apply": not collision["devices"],
                "connector_config": config,
                "created_at": utc(),
                "expires_at": (datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)).isoformat(),
                **recovery,
            }
            return self.retain_plan(body, options, app, config)

    def identity_recovery_origin(self, options, compilation, files):
        if not isinstance(options, NativeInstanceRecoveryPreview):
            return self.name_recovery_origin(options, compilation)
        prepared = self.instance_recovery.prepare(
            {
                "receipt_id": options.recovery_parent_receipt,
                "capture_id": options.capture_id,
                "snapshot_sha256": options.snapshot_sha256,
            }
        )
        proposal = prepared["proposal"]
        selected = compilation["identity_edit"]
        if (
            proposal is None
            or prepared["origin_sha256"] != options.recovery_origin_sha256
            or any(
                proposal[key] != getattr(options, key)
                for key in (
                    "capture_id",
                    "snapshot_sha256",
                    "new_instance",
                    "recovery_parent_receipt",
                )
            )
            or selected.get("change_kind") is not None
            or selected.get("old_instance") != prepared["current_instance"]
            or selected.get("new_instance") != prepared["previous_instance"]
            or selected.get("name") != prepared["unchanged_name"]
            or selected.get("root_ref") != prepared["origin"]["root_ref"]
            or selected.get("root_class") != prepared["origin"]["root_class"]
        ):
            raise ValueError("The previous-instance proposal changed; prepare and review it again.")
        _, expected, _ = self.instance_recovery.qualified_inverse(files, options.new_instance)
        if seal(compilation) != seal(expected):
            raise ValueError(
                "The fresh instance compilation differs from its qualified destination."
            )
        return {
            "recovery_origin": prepared["origin"],
            "recovery_origin_sha256": prepared["origin_sha256"],
        }

    def name_recovery_origin(self, options, compilation):
        if not isinstance(options, NativeNameRecoveryPreview):
            return {}
        prepared = self.name_recovery.prepare(
            {
                "receipt_id": options.recovery_parent_receipt,
                "capture_id": options.capture_id,
                "snapshot_sha256": options.snapshot_sha256,
            }
        )
        proposal = prepared["proposal"]
        selected = compilation["identity_edit"]
        if (
            proposal is None
            or prepared["origin_sha256"] != options.recovery_origin_sha256
            or any(
                proposal[key] != getattr(options, key)
                for key in (
                    "capture_id",
                    "snapshot_sha256",
                    "new_instance",
                    "new_name",
                    "recovery_parent_receipt",
                )
            )
            or selected.get("change_kind") != "name"
            or selected.get("old_name") != prepared["current_name"]
            or selected.get("new_name") != prepared["previous_name"]
            or selected.get("old_instance") != selected.get("new_instance")
            or selected.get("old_instance") != prepared["origin"]["instance"]
            or selected.get("root_ref") != prepared["origin"]["root_ref"]
            or selected.get("root_class") != prepared["origin"]["root_class"]
        ):
            raise ValueError("The previous-name proposal changed; prepare and review it again.")
        return {
            "recovery_origin": prepared["origin"],
            "recovery_origin_sha256": prepared["origin_sha256"],
        }

    def retain_plan(self, body, options, app, config):
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

    async def preview_default(self, **arguments):
        options = DefaultTransferPreview(**arguments)
        return await self.preview_typed_default(options, boolean=False)

    def point_name_source(self, **arguments):
        options = PointNameSource(**arguments)
        if (self.storage.directory / options.capture_id).is_symlink():
            raise ValueError("Native name sources must stay in their original folder.")
        captured, files = self.check_capture(options)
        if captured["evidence_sha256"] != options.snapshot_sha256:
            raise ValueError("The selected native snapshot changed; open it again.")
        return {
            "profile": POINT_NAME_PROFILE,
            "scope": POINT_NAME_SCOPE,
            "capture_id": captured["id"],
            "snapshot_sha256": captured["evidence_sha256"],
            "target": self.target(options),
            "device": options.device,
            "points": PointNameCompiler(files).fields(),
            "controller_queries": False,
            "controller_writes": False,
        }

    async def preview_point_name(self, **arguments):
        options = PointNamePreview(**arguments)
        async with self.operation(options.operation_id, "review-point-name"):
            self.available(options)
            self.point_name_source(**options.model_dump(include=set(PointNameSource.model_fields)))
            captured, files = self.check_capture(options)
            edit = options.model_dump(include=set(PointNameEdit.model_fields))
            output, compilation = compile_point_name(files, edit)
            recovery = self.point_name_recovery_origin(options, compilation)
            if not compilation["selected_edit"]["changed"]:
                raise ValueError("Choose a different point name before transfer.")
            config, app = copy.deepcopy(self.bacnet.config), self.bacnet.require()
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                actual, _ = await self.identity(session, options.device)
                published = await self.path._read(session, options.object_id, "object-name")
            if (
                actual != captured["identity"]
                or published != compilation["selected_edit"]["before"]
            ):
                raise ValueError("Controller or published point name changed; capture again.")
            body = {
                "profile": PROFILE,
                "operation_profile": POINT_NAME_PROFILE,
                "operation_id": options.operation_id,
                "target": self.target(options),
                "identity": actual,
                "old_instance": ObjectIdentifier(options.device)[1],
                "new_instance": ObjectIdentifier(options.device)[1],
                "change_kind": "point-name",
                "old_name": actual["object-name"],
                "new_name": actual["object-name"],
                "capture_id": options.capture_id,
                "snapshot_sha256": captured["evidence_sha256"],
                "application_sha256": sha(files[3]),
                "static_parameters_sha256": sha(files[11]),
                "point_name_edit": edit,
                "compilation": compilation,
                "payload_sha256": sha(output),
                "collision_check": self.name_scope(),
                "parameter_policy": "Merge fresh saved settings; retain this point reference/name and all other application bytes. Verify the complete application and published point name.",
                "backup_effects": backup_effects(),
                "scope": POINT_NAME_SCOPE,
                "vendor_runtime_required": False,
                "can_apply": True,
                "connector_config": config,
                "created_at": utc(),
                "expires_at": (datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)).isoformat(),
                **recovery,
            }
            return self.retain_plan(body, options, app, config)

    def point_name_recovery_origin(self, options, compilation):
        if options.recovery_parent_receipt is None:
            return {}
        prepared = self.point_name_recovery.prepare(
            {
                "receipt_id": options.recovery_parent_receipt,
                "capture_id": options.capture_id,
                "snapshot_sha256": options.snapshot_sha256,
            }
        )
        proposal = prepared["proposal"]
        selected = compilation.get("selected_edit", {})
        edit = options.model_dump(include=set(PointNameEdit.model_fields))
        if (
            proposal is None
            or prepared["already_recorded"]
            or prepared["origin_sha256"] != options.recovery_origin_sha256
            or any(proposal.get(k) != v for k, v in edit.items())
            or selected.get("before") != prepared["current_name"]
            or selected.get("after") != prepared["previous_name"]
            or selected.get("character_encoding") != prepared["origin"]["character_encoding"]
        ):
            raise ValueError("Previous point-name proposal changed; prepare and review it again.")
        return {
            "recovery_origin": prepared["origin"],
            "recovery_origin_sha256": prepared["origin_sha256"],
        }

    async def preview_boolean_default(self, **arguments):
        options = BooleanTransferPreview(**arguments)
        return await self.preview_typed_default(options, boolean=True)

    async def preview_enum_default(self, **arguments):
        options = EnumTransferPreview(**arguments)
        return await self.preview_typed_default(options, boolean=False, enumerated=True)

    async def preview_wire(self, **arguments):
        options = WireTransferPreview(**arguments)
        async with self.operation(options.operation_id, "review-wire"):
            self.available(options)
            if (self.storage.directory / options.capture_id).is_symlink():
                raise ValueError("Native wire sources must stay in their original folder.")
            captured, files = self.check_capture(options)
            if captured["evidence_sha256"] != options.snapshot_sha256:
                raise ValueError("The native snapshot changed; reopen and review again.")
            edit = options.model_dump(include=set(EffectiveWirePreview.model_fields))
            output, compilation = compile_wire(
                files, edit, _compiler=self.wire_recovery.reviewed_compiler(options, files)
            )
            if not compilation["wire_edit"]["changed"]:
                raise ValueError("Choose a different existing native wire source before transfer.")
            recovery = self.wire_recovery_origin(options, compilation)
            config, app = copy.deepcopy(self.bacnet.config), self.bacnet.require()
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                actual, _ = await self.identity(session, options.device)
            if actual != captured["identity"]:
                raise ValueError("Controller identity changed after backup; capture again.")
            body = {
                "profile": PROFILE,
                "operation_profile": WIRE_PROFILE,
                "target": self.target(options),
                "identity": actual,
                "old_instance": ObjectIdentifier(options.device)[1],
                "new_instance": ObjectIdentifier(options.device)[1],
                "change_kind": "wire-source",
                "old_name": actual["object-name"],
                "new_name": actual["object-name"],
                "capture_id": options.capture_id,
                "snapshot_sha256": captured["evidence_sha256"],
                "application_sha256": sha(files[3]),
                "static_parameters_sha256": sha(files[11]),
                "wire_edit": edit,
                "wire_guard": compilation["wire_guard"],
                "compilation": compilation,
                "payload_sha256": sha(output),
                "collision_check": self.wire_scope(),
                "parameter_policy": (
                    "Capture fresh application/settings before restore. Application, saved "
                    "directory and selected graph/source/target configuration must match. "
                    "Merge other fresh saved values; the final payload may differ from preview. "
                    "Verify the full native application, effective wire and saved settings."
                ),
                "backup_effects": backup_effects(),
                "scope": WIRE_SCOPE,
                "vendor_runtime_required": False,
                "can_apply": True,
                "connector_config": config,
                "created_at": utc(),
                "expires_at": (datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)).isoformat(),
                **recovery,
            }
            return self.retain_plan(body, options, app, config)

    async def preview_typed_default(self, options, *, boolean, enumerated=False):
        if boolean and enumerated:
            raise ValueError("Choose one native default datatype.")
        compiler = (
            compile_enum_default
            if enumerated
            else compile_boolean_default
            if boolean
            else compile_default
        )
        profile = (
            ENUM_DEFAULT_PROFILE
            if enumerated
            else BOOLEAN_DEFAULT_PROFILE
            if boolean
            else DEFAULT_PROFILE
        )
        scope = (
            ENUM_DEFAULT_SCOPE
            if enumerated
            else BOOLEAN_DEFAULT_SCOPE
            if boolean
            else DEFAULT_SCOPE
        )
        async with self.operation(options.operation_id, "review-default"):
            self.available(options)
            if (self.storage.directory / options.capture_id).is_symlink():
                raise ValueError("Native default sources must stay in their original folder.")
            captured, files = self.check_capture(options)
            if captured["evidence_sha256"] != options.snapshot_sha256:
                raise ValueError("The native snapshot changed; reopen and review again.")
            if (boolean or enumerated) and options.source_sha256 != sha(files[3]):
                datatype = "Enum" if enumerated else "Boolean"
                raise ValueError(f"The native {datatype} archive changed; reopen and review again.")
            edit = options.model_dump(
                include={
                    "record_ref",
                    "encoded_sha256",
                    "value" if boolean or enumerated else "value_text",
                }
            )
            output, compilation = compiler(files, edit)
            if not compilation["selected_edit"]["changed"]:
                raise ValueError("Choose a different effective native default before transfer.")
            recovery = self.recovery_origin(
                options, compilation, boolean=boolean, enumerated=enumerated
            )
            config, app = copy.deepcopy(self.bacnet.config), self.bacnet.require()
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                actual, _ = await self.identity(session, options.device)
            if actual != captured["identity"]:
                raise ValueError("Controller identity changed after backup; capture again.")
            body = {
                "profile": PROFILE,
                "operation_profile": profile,
                "target": self.target(options),
                "identity": actual,
                "old_instance": ObjectIdentifier(options.device)[1],
                "new_instance": ObjectIdentifier(options.device)[1],
                "change_kind": "enum-default"
                if enumerated
                else "boolean-default"
                if boolean
                else "signal-default",
                "old_name": actual["object-name"],
                "new_name": actual["object-name"],
                "capture_id": options.capture_id,
                "snapshot_sha256": captured["evidence_sha256"],
                "application_sha256": sha(files[3]),
                "static_parameters_sha256": sha(files[11]),
                "default_edit": edit,
                "compilation": compilation,
                "payload_sha256": sha(output),
                "collision_check": self.default_scope(),
                "parameter_policy": (
                    "Capture fresh application/settings before restore. Application and saved "
                    "directory must match; the selected effective prior value must still match. "
                    "Merge other fresh saved values, so the final payload may differ from the "
                    "preview. Verify both full native application and effective settings."
                ),
                "backup_effects": backup_effects(),
                "scope": scope,
                **({"enum_semantics_verified": False} if enumerated else {}),
                "vendor_runtime_required": False,
                "can_apply": True,
                "connector_config": config,
                "created_at": utc(),
                "expires_at": (datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)).isoformat(),
                **recovery,
            }
            return self.retain_plan(body, options, app, config)

    def recovery_origin(self, options, compilation, *, boolean=False, enumerated=False):
        """Reconstruct local lineage; a caller-supplied parent is never write authority."""
        if options.recovery_parent_receipt is None:
            return {}
        service = (
            self.enum_recovery
            if enumerated
            else self.boolean_recovery
            if boolean
            else self.default_recovery
        )
        prepared = service.prepare(
            {
                "receipt_id": options.recovery_parent_receipt,
                "capture_id": options.capture_id,
                "snapshot_sha256": options.snapshot_sha256,
            }
        )
        proposal = prepared["proposal"]
        selected = compilation["selected_edit"]
        matches_value = (
            type(selected.get("after_value")) is int
            and selected["after_value"] == prepared["origin"]["previous_effective_value"]
            and compilation["states_text_encoded_sha256"]
            == prepared["origin"]["states_text_encoded_sha256"]
            if enumerated
            else type(selected.get("after_value")) is bool
            and selected["after_value"] is prepared["origin"]["previous_effective_value"]
            if boolean
            else selected["after_bits"] == prepared["origin"]["previous_effective_bits"]
        )
        if (
            proposal is None
            or prepared["origin_sha256"] != options.recovery_origin_sha256
            or proposal["record_ref"] != options.record_ref
            or proposal["encoded_sha256"] != options.encoded_sha256
            or not matches_value
        ):
            raise ValueError("The previous-value proposal changed; prepare and review it again.")
        return {
            "recovery_origin": prepared["origin"],
            "recovery_origin_sha256": prepared["origin_sha256"],
        }

    def wire_recovery_origin(self, options, compilation):
        """Recheck an exact local wire proposal; a parent receipt is not write authority."""
        if options.recovery_parent_receipt is None:
            return {}
        prepared = self.wire_recovery.prepare(
            {
                "receipt_id": options.recovery_parent_receipt,
                "capture_id": options.capture_id,
                "snapshot_sha256": options.snapshot_sha256,
            }
        )
        proposal = prepared["proposal"]
        if (
            proposal is None
            or prepared["origin_sha256"] != options.recovery_origin_sha256
            or seal({key: proposal[key] for key in EffectiveWirePreview.model_fields})
            != seal(options.model_dump(include=set(EffectiveWirePreview.model_fields)))
            or seal(compilation["wire_edit"]["new"]) != seal(prepared["origin"]["previous_tuple"])
            or compilation["wire_edit"]["source_ref"] != prepared["origin"]["previous_source_ref"]
        ):
            raise ValueError("The previous wire proposal changed; prepare and review it again.")
        return {
            "recovery_origin": prepared["origin"],
            "recovery_origin_sha256": prepared["origin_sha256"],
        }

    @staticmethod
    def default_scope():
        return {
            "scope": "One default edit at the selected physical station",
            "devices": [],
            "checked_at": utc(),
            "limitation": "Device instance and name are unchanged; no number is allocated.",
        }

    @staticmethod
    def wire_scope():
        return {
            "scope": "One existing wire-source edit at the selected physical station",
            "devices": [],
            "checked_at": utc(),
            "limitation": "Device and native object identities are retained; no number is allocated.",
        }

    @staticmethod
    def name_scope():
        return {
            "scope": "Name-only edit at the selected physical station",
            "devices": [],
            "checked_at": utc(),
            "limitation": "The existing instance is retained; no new number is allocated.",
        }

    async def observe_name(self, session, intent):
        try:
            actual = await self.instances._identity(session, intent["identity"]["device"])
            expected = {**intent["identity"], "object-name": intent["new_name"]}
            state = (
                "verified_new"
                if actual == expected
                else "verified_old"
                if actual == intent["identity"]
                else "identity_mismatch"
            )
            return {"status": state, "identity": actual, "errors": []}
        except (ValueError, TimeoutError, OSError) as exc:
            return {
                "status": "unconfirmed",
                "identity": None,
                "errors": [(str(exc) or "Identity read timed out.")[:256]],
            }

    async def restore_readiness_probe(self, session, intent):
        observation = (
            await self.observe_name(session, intent)
            if intent.get("change_kind") == "name"
            else await self.instances._observe(session, intent)
        )
        attempt = {
            "observed_at": utc(),
            "identity_status": observation["status"],
            "errors": observation.get("errors", []),
        }
        identity = observation.get("identity")
        if observation["status"] == "verified_new" and identity is not None:
            try:
                attempt["system_status"] = int(
                    await self.path._read(session, identity["device"], "system-status")
                )
            except (ValueError, TimeoutError, OSError) as exc:
                attempt["errors"] = [
                    *attempt["errors"],
                    (str(exc) or "Controller status read timed out.")[:256],
                ]
        return observation, attempt

    async def wait_for_restore_readiness(self, session, intent):
        """Wait for the reviewed station using reads, before entering backup mode."""
        self.phase("waiting for controller after application restore")
        deadline = time.monotonic() + RESTORE_READINESS_SECONDS
        attempts = []
        while True:
            self.path._guard(session)
            try:
                observation, attempt = await asyncio.wait_for(
                    self.restore_readiness_probe(session, intent),
                    timeout=max(0.001, deadline - time.monotonic()),
                )
            except TimeoutError:
                observation = {"status": "unconfirmed", "errors": ["Readiness deadline reached."]}
                attempt = {
                    "observed_at": utc(),
                    "identity_status": observation["status"],
                    "errors": observation["errors"],
                }
            attempts.append(attempt)
            self.storage.event(intent["id"], "restore-readiness-read", attempt)
            ready = attempt.get("system_status") == 0
            # A different identity is evidence to stop, rather than to wait out.
            mismatch = observation["status"] in ("identity_mismatch", "different_instance")
            if ready or mismatch or time.monotonic() >= deadline:
                return {
                    "ready": ready,
                    "read_only": True,
                    "observation": observation,
                    "attempts": attempts,
                }
            await asyncio.sleep(
                max(0, min(RESTORE_READINESS_INTERVAL, deadline - time.monotonic()))
            )

    async def verify(self, session, intent):
        self.phase("reading back the physical station")
        change_kind = intent.get("change_kind", "instance")
        if change_kind not in (
            "instance",
            "name",
            "signal-default",
            "boolean-default",
            "enum-default",
            "wire-source",
            "connection",
            "point-name",
            "input",
        ):
            raise ValueError("Unrecognized native transfer operation; retain its evidence.")
        boolean_edit = change_kind == "boolean-default"
        enum_edit = change_kind == "enum-default"
        default_edit = change_kind in ("signal-default", "boolean-default", "enum-default")
        wire_edit = change_kind == "wire-source"
        connection_edit = change_kind == "connection"
        point_name_edit = change_kind == "point-name"
        input_edit = change_kind == "input"
        program_edit = default_edit or wire_edit or point_name_edit or input_edit or connection_edit
        if connection_edit:
            if intent.get("operation_profile") != CONNECTION_PROFILE:
                raise ValueError("Unsupported native connection evidence version; retain it.")
            validate_connection_evidence(
                intent.get("connection_edit"), intent.get("connection_guard")
            )
        if input_edit and intent.get("operation_profile") != input_operation_profile(
            intent.get("input_edit")
        ):
            raise ValueError("Unsupported native input evidence version; retain it.")
        if (
            input_edit
            and intent.get("operation_profile") == TERMINAL_PROFILE
            and intent.get("compilation", {}).get("profile") != TERMINAL_PROFILE
        ):
            raise ValueError("Terminal transfer evidence requires its exact compiler profile.")
        if input_edit:
            from .native_binary_terminal import validate_evidence

            validate_evidence(intent)
            from .native_encoded_terminal_input import validate_evidence as validate_encoded_analog

            validate_encoded_analog(intent)
        if point_name_edit and intent.get("operation_profile") != POINT_NAME_PROFILE:
            raise ValueError("Unsupported native point-name evidence version; retain it.")
        expected_profile = (
            ENUM_DEFAULT_PROFILE
            if enum_edit
            else BOOLEAN_DEFAULT_PROFILE
            if boolean_edit
            else DEFAULT_PROFILE
        )
        if default_edit and intent.get("operation_profile") != expected_profile:
            raise ValueError("Unsupported native default transfer evidence version; retain it.")
        if wire_edit and intent.get("operation_profile") != WIRE_PROFILE:
            raise ValueError("Unsupported native wire transfer evidence version; retain it.")
        if wire_edit:
            validate_wire_evidence(intent.get("wire_edit"), intent.get("wire_guard"))
        renaming = intent.get("change_kind") == "name"
        observed = (
            await self.observe_name(session, intent)
            if renaming
            else await self.instances._observe(session, intent)
        )
        result = {
            "status": "unknown",
            "readback": observed,
            "read_only": False,
            "backup_effects": backup_effects(),
            "observed_at": utc(),
        }
        identity = observed.get("identity")
        if program_edit and identity is not None and identity != intent["identity"]:
            result["error"] = "Controller identity changed during the native application transfer."
            return result
        if identity is not None:
            try:
                status = int(await self.path._read(session, identity["device"], "system-status"))
                result.update(system_status=status, operational=status == 0)
            except (ValueError, TimeoutError, OSError) as exc:
                result["error"] = (
                    "Controller operational status could not be read: " + str(exc)[:256]
                )
                return result
        if observed["status"] not in ("verified_new", "verified_old"):
            return result
        if not result.get("operational"):
            result["error"] = "The new identity responds, but the controller is not operational."
            return result
        options = DeviceDetailsRequest(**intent["target"], device=identity["device"])
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
            _, original_files = self.storage.load(intent["backup_id"])
            if identity == intent["identity"] and digest != intent["native_payload_sha256"]:
                original, _ = ParameterApplication(
                    original_files[3], original_files[11], original_files[12]
                ).compile()
                original_digest = sha(MoiIdentity(original).data)
                if digest == original_digest and backup.get("source_identity_matches"):
                    result["preservation"] = verify_preservation(
                        original_files,
                        files,
                        old_instance=intent["old_instance"],
                        new_instance=intent["old_instance"],
                    )
                    if point_name_edit:
                        edit = PointNameEdit(**intent["point_name_edit"])
                        name = await self.path._read(session, edit.object_id, "object-name")
                        if name != intent["compilation"]["selected_edit"]["before"]:
                            raise ValueError("The original published point name is not recovered.")
                        result["published_point_name"] = name
                    if input_edit:
                        result["published_input"] = await self.verify_published_input(
                            session, files, intent["input_edit"]
                        )
                    result["runtime_calibration"] = await read_runtime_calibration(
                        files[3], self.files.exchange, session
                    )
                    status = int(await self.path._read(session, options.device, "system-status"))
                    result.update(
                        system_status=status,
                        operational=status == 0,
                        expected_native_sha256=original_digest,
                        proposed_change_verified=False,
                        recovery={
                            "profile": "native-original-application-readback/1",
                            "original_backup_id": intent["backup_id"],
                            "original_reviewed_native_sha256": intent["native_payload_sha256"],
                            "scope": "Original identity, complete application and saved application settings recovered. The proposed change is not verified. Readback did not restore or replay an application.",
                        },
                    )
                    if status == 0:
                        result["status"] = "recovered_original"
                        self.instances._forget_old_address(session)
                    else:
                        result["error"] = (
                            "Original application matches, but the controller is not operational."
                        )
                    return result
            if observed["status"] != "verified_new":
                result["error"] = (
                    "Original identity responds, but its complete application/settings recovery is not verified."
                )
                return result
            if digest == intent["native_payload_sha256"]:
                name_policy = (
                    {"old_name": intent["old_name"], "new_name": intent["new_name"]}
                    if renaming
                    else {}
                )
                result["preservation"] = (
                    verify_input_preservation(
                        original_files,
                        files,
                        intent["input_edit"],
                        allocation_origin=intent.get("allocation_origin"),
                    )
                    if input_edit
                    else verify_point_name_preservation(
                        original_files, files, intent["point_name_edit"]
                    )
                    if point_name_edit
                    else verify_connection_preservation(
                        original_files,
                        files,
                        intent["connection_edit"],
                        intent["connection_guard"],
                    )
                    if connection_edit
                    else verify_wire_preservation(
                        original_files,
                        files,
                        intent["wire_edit"],
                        intent["wire_guard"],
                        _compiler=self.wire_recovery.recorded_compiler(intent, original_files),
                    )
                    if wire_edit
                    else (
                        (
                            verify_enum_preservation
                            if enum_edit
                            else verify_boolean_preservation
                            if boolean_edit
                            else verify_default_preservation
                        )(original_files, files, intent["default_edit"])
                        if default_edit
                        else verify_preservation(
                            original_files,
                            files,
                            old_instance=intent["old_instance"],
                            new_instance=intent["new_instance"],
                            **name_policy,
                        )
                    )
                )
                if point_name_edit:
                    edit = PointNameEdit(**intent["point_name_edit"])
                    name = await self.path._read(session, edit.object_id, "object-name")
                    result["published_point_name"] = name
                    if name != edit.new_name:
                        result["error"] = "The published point name differs from the reviewed name."
                        return result
                if input_edit:
                    result["published_input"] = await self.verify_published_input(
                        session, files, intent["input_edit"]
                    )
                result["runtime_calibration"] = await read_runtime_calibration(
                    files[3], self.files.exchange, session
                )
                status = int(await self.path._read(session, options.device, "system-status"))
                result.update(system_status=status, operational=status == 0)
                if status == 0:
                    result["status"] = "verified"
                    if not program_edit:
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
        return await self.apply_reviewed(request, default_edit=False)

    async def apply_default(self, **arguments):
        request = DefaultTransferApply(**arguments)
        return await self.apply_reviewed(request, default_edit=True)

    async def apply_boolean_default(self, **arguments):
        request = DefaultTransferApply(**arguments)
        return await self.apply_reviewed(request, default_edit=True, boolean_edit=True)

    async def apply_enum_default(self, **arguments):
        request = DefaultTransferApply(**arguments)
        return await self.apply_reviewed(request, default_edit=True, enum_edit=True)

    async def apply_wire(self, **arguments):
        request = WireTransferApply(**arguments)
        return await self.apply_reviewed(request, default_edit=False, wire_edit=True)

    async def apply_point_name(self, **arguments):
        request = PointNameApply(**arguments)
        return await self.apply_reviewed(request, default_edit=False, point_name_edit=True)

    async def apply_input(self, **arguments):
        return await self.apply_reviewed(
            InputApply(**arguments), default_edit=False, input_edit=True
        )

    async def apply_reviewed(
        self,
        request,
        *,
        default_edit,
        boolean_edit=False,
        enum_edit=False,
        wire_edit=False,
        point_name_edit=False,
        input_edit=False,
        connection_edit=False,
    ):
        if (
            sum(
                (
                    bool(default_edit),
                    bool(wire_edit),
                    bool(point_name_edit),
                    bool(input_edit),
                    bool(connection_edit),
                )
            )
            > 1
            or ((boolean_edit or enum_edit) and not default_edit)
            or (boolean_edit and enum_edit)
        ):
            raise ValueError("Choose one native transfer operation.")
        program_edit = default_edit or wire_edit or point_name_edit or input_edit or connection_edit
        plan = self.plans.pop(request.token, None)
        if not plan or plan["digest"] != request.review_sha256 or not plan["body"]["can_apply"]:
            raise ValueError(
                "Native application review is changed, blocked, expired or already consumed."
            )
        renaming = plan["body"].get("change_kind") == "name"
        kind = plan["body"].get("change_kind", "instance")
        expected_kind = (
            "input"
            if input_edit
            else "point-name"
            if point_name_edit
            else "connection"
            if connection_edit
            else "wire-source"
            if wire_edit
            else "enum-default"
            if enum_edit
            else "boolean-default"
            if boolean_edit
            else "signal-default"
        )
        if kind not in ((expected_kind,) if program_edit else ("instance", "name")):
            raise ValueError("This review belongs to a different native transfer operation.")
        if default_edit and plan["body"].get("operation_profile") != (
            ENUM_DEFAULT_PROFILE
            if enum_edit
            else BOOLEAN_DEFAULT_PROFILE
            if boolean_edit
            else DEFAULT_PROFILE
        ):
            raise ValueError("Unsupported native default transfer evidence version; retain it.")
        if wire_edit and plan["body"].get("operation_profile") != WIRE_PROFILE:
            raise ValueError("Unsupported native wire transfer evidence version; retain it.")
        if connection_edit and plan["body"].get("operation_profile") != CONNECTION_PROFILE:
            raise ValueError("Unsupported native connection evidence version; retain it.")
        if connection_edit and seal(plan["body"]) != plan["digest"]:
            raise ValueError("The retained native connection review changed; review again.")
        if point_name_edit and plan["body"].get("operation_profile") != POINT_NAME_PROFILE:
            raise ValueError("Unsupported native point-name evidence version; retain it.")
        if input_edit and plan["body"].get("operation_profile") != input_operation_profile(
            plan["body"].get("input_edit")
        ):
            raise ValueError("Unsupported native input evidence version; retain it.")
        if (
            input_edit
            and plan["body"].get("operation_profile") == TERMINAL_PROFILE
            and (
                seal(plan["body"]) != plan["digest"]
                or plan["body"].get("compilation", {}).get("profile") != TERMINAL_PROFILE
                or plan["body"]["input_edit"] != plan["options"].edit.model_dump()
            )
        ):
            raise ValueError("The exact terminal transfer review changed; review again.")
        if input_edit:
            from .native_binary_terminal import PROFILE as BINARY_TERMINAL_PROFILE
            from .native_binary_terminal import validate_evidence

            validate_evidence(plan["body"])
            from .native_encoded_terminal_input import PROFILE as ENCODED_ANALOG_PROFILE
            from .native_encoded_terminal_input import validate_evidence as validate_encoded_analog

            validate_encoded_analog(plan["body"])
            if plan["body"].get("operation_profile") == ENCODED_ANALOG_PROFILE and (
                seal(plan["body"]) != plan["digest"]
                or seal(plan["body"]["input_edit"]) != seal(plan["options"].edit.model_dump())
            ):
                raise ValueError("The exact encoded analog terminal review changed; review again.")
            if plan["body"].get("operation_profile") == BINARY_TERMINAL_PROFILE and (
                seal(plan["body"]) != plan["digest"]
                or seal(plan["body"]["input_edit"]) != seal(plan["options"].edit.model_dump())
            ):
                raise ValueError("The exact binary terminal review changed; review again.")
            validate_terminal_recovery_plan(plan["body"], plan["options"])
        if (
            not request.application_transfer_confirmed
            or (wire_edit and not request.wire_change_confirmed)
            or (connection_edit and not request.connection_change_confirmed)
            or (default_edit and not request.default_change_confirmed)
            or (point_name_edit and not request.point_name_confirmed)
            or (
                input_edit
                and not (request.input_change_confirmed and request.physical_wiring_confirmed)
            )
            or (not program_edit and renaming and not request.name_change_confirmed)
            or (not program_edit and not renaming and not request.allocation_confirmed)
        ):
            raise ValueError("Confirm the reviewed change and application transfer.")
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
                self.storage.require_capture_capacity(2)
                if (
                    self.bacnet.require() is not plan["app"]
                    or self.bacnet.config != plan["config"]
                    or time.monotonic() >= plan["expires"]
                ):
                    raise ValueError("Interface or review changed; review again.")
                if seal(self.credentials.get()) != plan["credentials_digest"]:
                    raise ValueError("Transfer credentials changed; review again.")
                collision = (
                    self.connection_scope()
                    if connection_edit
                    else self.wire_scope()
                    if wire_edit
                    else self.default_scope()
                    if default_edit
                    else self.name_scope()
                    if renaming or point_name_edit or input_edit
                    else await self.instances._collision(options)
                )
                if collision["devices"]:
                    raise ValueError(
                        "The proposed number answered the fresh collision query. No transfer was sent."
                    )
                async with self.path._path(options) as session:
                    PropertyEvidence.pin(session, options.router)
                    actual, _ = await self.identity(session, options.device)
                    if actual != body["identity"]:
                        raise ValueError("Controller identity changed after review.")
                    if point_name_edit:
                        name = await self.path._read(session, options.object_id, "object-name")
                        if name != body["compilation"]["selected_edit"]["before"]:
                            raise ValueError("The published point name changed after review.")
                    if input_edit:
                        _, reviewed_files = self.storage.load(body["capture_id"])
                        await self.input_live_guard(
                            session, options, body["compilation"], reviewed_files
                        )
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
                    output, compilation = (
                        compile_input(
                            files,
                            body["input_edit"],
                            allocation_origin=body.get("allocation_origin"),
                        )
                        if input_edit
                        else compile_point_name(files, body["point_name_edit"])
                        if point_name_edit
                        else compile_connection(
                            files,
                            body["connection_edit"],
                            fresh=True,
                            expected_guard=body["connection_guard"],
                        )
                        if connection_edit
                        else compile_wire(
                            files,
                            body["wire_edit"],
                            fresh=True,
                            expected_guard=body["wire_guard"],
                            _compiler=self.wire_recovery.reviewed_compiler(options, files),
                        )
                        if wire_edit
                        else (
                            (
                                compile_enum_default
                                if enum_edit
                                else compile_boolean_default
                                if boolean_edit
                                else compile_default
                            )(
                                files,
                                body["default_edit"],
                                **(
                                    {
                                        "expected_prior_value": body["compilation"][
                                            "selected_edit"
                                        ]["before_value"]
                                    }
                                    if boolean_edit or enum_edit
                                    else {
                                        "expected_prior_bits": body["compilation"]["selected_edit"][
                                            "before_bits"
                                        ]
                                    }
                                ),
                                **(
                                    {
                                        "expected_states_text_sha256": body["compilation"][
                                            "states_text_encoded_sha256"
                                        ]
                                    }
                                    if enum_edit
                                    else {}
                                ),
                            )
                            if default_edit
                            else self.compile(files, options.new_instance, options.new_name)
                        )
                    )
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
                    if input_edit:
                        await self.input_live_guard(session, options, compilation, files)
                    # A concurrent import can use the space observed before the fresh backup.
                    self.storage.require_capture_capacity()
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
                    recovery = (
                        terminal_recovery_origin(self, options, compilation)
                        if input_edit
                        else {}
                        if connection_edit
                        else self.point_name_recovery_origin(options, compilation)
                        if point_name_edit
                        else self.wire_recovery_origin(options, compilation)
                        if wire_edit
                        else self.recovery_origin(
                            options, compilation, boolean=boolean_edit, enumerated=enum_edit
                        )
                        if default_edit
                        else self.identity_recovery_origin(options, compilation, files)
                    )
                    if recovery and any(body.get(key) != value for key, value in recovery.items()):
                        raise ValueError("The recovery origin changed after review. Prepare again.")
                    intent = self.storage.intent(
                        {
                            **{
                                k: body[k]
                                for k in (
                                    "target",
                                    "identity",
                                    "old_instance",
                                    "new_instance",
                                    "change_kind",
                                    "old_name",
                                    "new_name",
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
                            **(
                                {
                                    "input_edit": body["input_edit"],
                                    "allocation_origin": body.get("allocation_origin"),
                                    "operation_profile": input_operation_profile(
                                        body["input_edit"]
                                    ),
                                    "input_change_confirmed": request.input_change_confirmed,
                                    "physical_wiring_confirmed": request.physical_wiring_confirmed,
                                }
                                if input_edit
                                else {}
                            ),
                            **(
                                {
                                    "point_name_edit": body["point_name_edit"],
                                    "operation_profile": POINT_NAME_PROFILE,
                                    "point_name_confirmed": request.point_name_confirmed,
                                }
                                if point_name_edit
                                else {}
                            ),
                            **(
                                {
                                    "connection_edit": body["connection_edit"],
                                    "connection_guard": body["connection_guard"],
                                    "operation_profile": CONNECTION_PROFILE,
                                    "connection_change_confirmed": request.connection_change_confirmed,
                                }
                                if connection_edit
                                else {}
                            ),
                            **(
                                {
                                    "wire_edit": body["wire_edit"],
                                    "wire_guard": body["wire_guard"],
                                    "operation_profile": WIRE_PROFILE,
                                    "wire_change_confirmed": request.wire_change_confirmed,
                                }
                                if wire_edit
                                else {}
                            ),
                            **(
                                {
                                    "default_edit": body["default_edit"],
                                    "operation_profile": ENUM_DEFAULT_PROFILE
                                    if enum_edit
                                    else BOOLEAN_DEFAULT_PROFILE
                                    if boolean_edit
                                    else DEFAULT_PROFILE,
                                    "default_change_confirmed": request.default_change_confirmed,
                                    **(
                                        {"review_snapshot_sha256": body["snapshot_sha256"]}
                                        if enum_edit and recovery
                                        else {}
                                    ),
                                    **({"enum_semantics_verified": False} if enum_edit else {}),
                                }
                                if default_edit
                                else {}
                            ),
                            "allocation_confirmed": getattr(request, "allocation_confirmed", False),
                            "name_change_confirmed": getattr(
                                request, "name_change_confirmed", False
                            ),
                            "application_transfer_confirmed": True,
                            **recovery,
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
                    readiness = await self.wait_for_restore_readiness(session, intent)
                    result["restore_readiness"] = readiness
                    if readiness["ready"]:
                        result.update(await self.verify(session, intent))
                    else:
                        result["readback"] = readiness["observation"]
                        latest = next(
                            (a for a in reversed(readiness["attempts"]) if "system_status" in a),
                            {},
                        )
                        if "system_status" in latest:
                            result.update(system_status=latest["system_status"], operational=False)
                            result["error"] = "The controller is not operational after restore."
                        result["errors"].append(
                            "The reviewed controller did not become ready for verification. "
                            "No transfer was repeated; use the retained receipt for readback."
                        )
        except (ValueError, TimeoutError, OSError, sqlite3.Error, asyncio.CancelledError) as exc:
            result["errors"].append((str(exc) or "Native operation cancelled or timed out.")[:512])
        result["may_have_applied"] = dispatched
        if result["status"] not in ("verified", "recovered_original"):
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
            self.storage.require_capture_capacity()
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                result = await self.verify(session, intent)
            return self.storage.resolve(request.receipt_id, result)


def native_application_router(service):
    from .native_backup_integrity import (
        BackupIntegrityCheck,
        BackupStorageQuery,
        NativeBackupIntegrity,
    )
    from .native_backup_lifecycle import (
        BackupLibraryQuery,
        BackupLifecycleChange,
        NativeBackupLifecycle,
    )

    router = APIRouter(prefix="/api/bacnet/controller/native-application")
    library = NativeBackupLifecycle(service.storage)
    integrity = NativeBackupIntegrity(service.storage)

    @router.post("/backup-library/storage-inventory")
    def inspect_backup_storage(body: BackupStorageQuery):
        return integrity.inventory(body.model_dump())

    @router.post("/backup-library/check-originals")
    def check_backup_originals(body: BackupIntegrityCheck):
        return integrity.check(body.model_dump())

    @router.post("/backup-library/list")
    def list_backups(body: BackupLibraryQuery):
        return library.list(body.model_dump())

    @router.post("/backup-library/change")
    async def change_backup(body: BackupLifecycleChange):
        if service.active:
            raise ValueError("Finish the active native operation before managing retained backups.")
        return library.change(body.model_dump())

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

    @router.post("/point-name/source")
    async def point_name_source(body: PointNameSource):
        return service.point_name_source(**body.model_dump())

    @router.get("/input/sources")
    def input_sources():
        return service.input_sources()

    @router.post("/input/source")
    def input_source(body: InputLocalSource):
        return service.input_source(**body.model_dump())

    @router.post("/input/encoded-terminal/source")
    def encoded_analog_input_source(body: InputLocalSource):
        return service.encoded_analog_input_source(**body.model_dump())

    @router.post("/input/binary-terminal/source")
    def binary_input_source(body: InputLocalSource):
        return service.binary_input_source(**body.model_dump())

    @router.post("/input/support")
    async def input_support(body: InputSupport):
        return await service.input_support(**body.model_dump())

    @router.post("/input/copy/preview")
    def preview_input_copy(body: InputCopy):
        return service.input_copy(**body.model_dump())[1]

    @router.post("/input/copy/export")
    def export_input_copy(body: InputCopy):
        if body.expected_review_sha256 is None:
            raise ValueError("Review the local input copy before export.")
        data, _ = service.input_copy(**body.model_dump())
        return Response(
            data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": "attachment; filename=native-input-copy.moi"},
        )

    @router.post("/input/preview")
    async def preview_input(body: InputPreview):
        return await service.preview_input(**body.model_dump())

    @router.post("/input/terminal-recovery/prepare")
    def prepare_terminal_recovery(body: DefaultRecoveryPrepare):
        return NativeTerminalRecovery(NativeBackupRecords(service.storage)).prepare(
            body.model_dump()
        )

    @router.post("/input/terminal-recovery/preview")
    async def preview_terminal_recovery(body: TerminalRecoveryPreview):
        return await service.preview_terminal_recovery(**body.model_dump())

    @router.post("/input/apply")
    async def apply_input(body: InputApply):
        return await service.apply_input(**body.model_dump())

    @router.post("/point-name/preview")
    async def preview_point_name(body: PointNamePreview):
        return await service.preview_point_name(**body.model_dump())

    @router.post("/point-name/apply")
    async def apply_point_name(body: PointNameApply):
        return await service.apply_point_name(**body.model_dump())

    @router.post("/apply")
    async def apply(body: NativeApply):
        return await service.apply(**body.model_dump())

    @router.post("/name/recovery/prepare")
    def prepare_name_recovery(body: DefaultRecoveryPrepare):
        return service.name_recovery.prepare(body.model_dump())

    @router.post("/point-name/recovery/prepare")
    def prepare_point_name_recovery(body: DefaultRecoveryPrepare):
        return service.point_name_recovery.prepare(body.model_dump())

    @router.post("/name/recovery/source")
    def name_recovery_source(body: BackupInspectionSource):
        return service.name_recovery.source(body.model_dump())

    @router.post("/name/recovery/preview")
    async def preview_name_recovery(body: NativeNameRecoveryPreview):
        return await service.preview_name_recovery(**body.model_dump())

    @router.post("/instance/recovery/source")
    def instance_recovery_source(body: BackupInspectionSource):
        return service.instance_recovery.source(body.model_dump())

    @router.post("/instance/recovery/prepare")
    def prepare_instance_recovery(body: DefaultRecoveryPrepare):
        return service.instance_recovery.prepare(body.model_dump())

    @router.post("/instance/recovery/preview")
    async def preview_instance_recovery(body: NativeInstanceRecoveryPreview):
        return await service.preview_instance_recovery(**body.model_dump())

    @router.post("/signal-default/transfer/preview")
    async def preview_default(body: DefaultTransferPreview):
        return await service.preview_default(**body.model_dump())

    @router.post("/signal-default/recovery/prepare")
    def prepare_default_recovery(body: DefaultRecoveryPrepare):
        return service.default_recovery.prepare(body.model_dump())

    @router.post("/signal-default/transfer/apply")
    async def apply_default(body: DefaultTransferApply):
        return await service.apply_default(**body.model_dump())

    @router.post("/boolean-default/transfer/preview")
    async def preview_boolean_default(body: BooleanTransferPreview):
        return await service.preview_boolean_default(**body.model_dump())

    @router.post("/boolean-default/recovery/prepare")
    def prepare_boolean_recovery(body: DefaultRecoveryPrepare):
        return service.boolean_recovery.prepare(body.model_dump())

    @router.post("/boolean-default/transfer/apply")
    async def apply_boolean_default(body: DefaultTransferApply):
        return await service.apply_boolean_default(**body.model_dump())

    @router.post("/enum-default/transfer/preview")
    async def preview_enum_default(body: EnumTransferPreview):
        return await service.preview_enum_default(**body.model_dump())

    @router.post("/enum-default/transfer/apply")
    async def apply_enum_default(body: DefaultTransferApply):
        return await service.apply_enum_default(**body.model_dump())

    @router.post("/enum-default/recovery/prepare")
    def prepare_enum_recovery(body: DefaultRecoveryPrepare):
        return service.enum_recovery.prepare(body.model_dump())

    @router.post("/wire-source/transfer/preview")
    async def preview_wire(body: WireTransferPreview):
        return await service.preview_wire(**body.model_dump())

    @router.post("/matching-connection/transfer/preview")
    async def preview_connection(body: ConnectionTransferPreview):
        return await service.preview_connection(**body.model_dump())

    @router.post("/matching-connection/transfer/apply")
    async def apply_connection(body: ConnectionTransferApply):
        return await service.apply_connection(**body.model_dump())

    @router.post("/wire-source/recovery/prepare")
    def prepare_wire_recovery(body: DefaultRecoveryPrepare):
        return service.wire_recovery.prepare(body.model_dump())

    @router.post("/wire-source/transfer/apply")
    async def apply_wire(body: WireTransferApply):
        return await service.apply_wire(**body.model_dump())

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
