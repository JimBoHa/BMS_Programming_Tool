"""Explicit retained-image review using the common one-attempt native writer."""

import copy
from datetime import UTC, datetime, timedelta

from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field, StrictBool

from .application_store import PROFILE as APPLICATION_PROFILE
from .application_store import utc
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_identity import sha
from .native_snapshot_restore import (
    PROFILE,
    SCOPE,
    Hash,
    RestoreSource,
    compile_restore,
    source,
    validate_evidence,
)
from .property_evidence import PropertyEvidence


class RestorePreview(RestoreSource, DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class RestoreApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: Hash
    historical_application_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


class NativeSnapshotRestoreOperations:
    def restore_source(self, body):
        return source(self.storage, body)

    @staticmethod
    def restore_scope():
        return {
            "scope": "Retained application at its matching recorded station identity",
            "devices": [],
            "checked_at": utc(),
            "limitation": "No Device instance is allocated or changed; physical acceptance remains separate.",
        }

    async def preview_snapshot_restore(self, **arguments):
        from .native_applications import PLAN_SECONDS, backup_effects

        options = RestorePreview(**arguments)
        request = options.model_dump(include=set(RestoreSource.model_fields))
        _, desired = self.restore_source(request)
        expected_target = {**self.target(options), "device": options.device}
        if desired["target"] != expected_target:
            raise ValueError("Select the retained source's original controller route and Device.")
        async with self.operation(options.operation_id, "review-retained-application-restore"):
            self.available(options)
            config, app = copy.deepcopy(self.bacnet.config), self.bacnet.require()
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                actual, _ = await self.identity(session, options.device)
                if actual != desired["identity"]:
                    raise ValueError(
                        "Current identity/firmware differs from the retained restore source."
                    )
                current, files, _ = await self.capture_session(options, session, identity=actual)
            output, reloaded, compilation = compile_restore(
                self.storage,
                request,
                {"capture_id": current["id"], "snapshot_sha256": current["evidence_sha256"]},
                files,
            )
            if reloaded != desired:
                raise ValueError("The retained restore source changed during current capture.")
            body = {
                "profile": APPLICATION_PROFILE,
                "operation_profile": PROFILE,
                "target": self.target(options),
                "identity": actual,
                "old_instance": ObjectIdentifier(options.device)[1],
                "new_instance": ObjectIdentifier(options.device)[1],
                "old_name": actual["object-name"],
                "new_name": actual["object-name"],
                "change_kind": "application-restore",
                "capture_id": current["id"],
                "snapshot_sha256": current["evidence_sha256"],
                "application_sha256": sha(files[3]),
                "static_parameters_sha256": sha(files[11]),
                "restore_source": desired,
                "compilation": compilation,
                "payload_sha256": sha(output),
                "collision_check": self.restore_scope(),
                "parameter_policy": "Restore the selected historical saved application values. Fresh current configuration must still match this review, except qualified advancing counters. Non-application runtime slots are not restored.",
                "backup_effects": backup_effects(),
                "scope": SCOPE,
                "vendor_runtime_required": False,
                "can_apply": True,
                "connector_config": config,
                "created_at": utc(),
                "expires_at": (datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)).isoformat(),
            }
            validate_evidence(body)
            return self.retain_plan(body, options, app, config)

    @staticmethod
    def validate_restore_plan(body, options):
        validate_evidence(body)
        if body["restore_source"]["request"] != options.model_dump(
            include=set(RestoreSource.model_fields)
        ):
            raise ValueError("The retained restore request differs from its exact review.")

    async def apply_snapshot_restore(self, **arguments):
        return await self.apply_reviewed(
            RestoreApply(**arguments), default_edit=False, snapshot_restore=True
        )
