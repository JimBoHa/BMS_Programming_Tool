"""Execution-order edits through the existing durable native restore transaction."""

import copy
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field, StrictBool, model_validator

from .application_preservation import runtime_parameter_changes
from .application_store import PROFILE as APPLICATION_PROFILE
from .application_store import utc
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_execution_order import MoiExecutionOrder
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .native_backup_records import NativeBackupRecords
from .native_execution_order import (
    EffectiveOrderCompiler,
    Hash,
    Index,
    NativeExecutionOrder,
    OrderPreview,
)
from .native_parameter_qualification import qualify_parameter_additions

PROFILE = "native-effective-execution-order-transfer/1"
GUARD_PROFILE = "native-execution-order-configuration-guard/1"
PRESERVATION_PROFILE = "native-effective-execution-order-preservation/1"
SCOPE = (
    "Transfer a permutation of existing native members, preserving every recorded wire's "
    "execution phase and original Unsigned width. Require fresh selected configuration, "
    "merge saved settings and verify the complete application and effective order. Capture "
    "can enter/end backup mode; one restore can interrupt control. No new blocks/I/O, "
    "automatic inverse, general compiler/resources/runtime or CCT/physical acceptance."
)


class OrderTransferPreview(OrderPreview, DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    recovery_parent_receipt: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    recovery_origin_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def recovery_binding(self):
        if (self.recovery_parent_receipt is None) != (self.recovery_origin_sha256 is None):
            raise ValueError("Provide both the original order receipt and prepared origin hash.")
        return self


class OrderTransferApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: Hash
    order_change_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


class OrderConfigurationGuard(StrictModel):
    profile: Literal[GUARD_PROFILE]
    diagram_ref: str = Field(strict=True, min_length=1, max_length=512)
    original_order: list[Index] = Field(min_length=1, max_length=512)
    payload_widths: list[Annotated[int, Field(strict=True, ge=1, le=4)]] = Field(
        min_length=1, max_length=512
    )
    property_sha256: Hash
    edge_relationships_sha256: Hash
    configuration_sha256: Hash


def validate_order_evidence(edit, guard):
    options = OrderPreview.model_validate(edit)
    checked = OrderConfigurationGuard.model_validate(guard)
    count = len(checked.original_order)
    if (
        checked.diagram_ref != options.diagram_ref
        or sorted(checked.original_order) != list(range(count))
        or sorted(options.proposed_order) != list(range(count))
        or options.proposed_order == checked.original_order
        or len(checked.payload_widths) != count
        or any(type(v) is not int or not 1 <= v <= 4 for v in checked.payload_widths)
        or any(
            value >= 1 << (width * 8)
            for value, width in zip(options.proposed_order, checked.payload_widths, strict=True)
        )
    ):
        raise ValueError("The recorded native execution-order proposal and guard disagree.")


def compile_order(files, edit, *, fresh=False, expected_guard=None):
    options = OrderPreview.model_validate(edit)
    compiler = EffectiveOrderCompiler.from_files(files)
    archive = compiler.archive.inspect(options.diagram_ref)
    if options.source_sha256 != sha(files[3]) or options.record_sha256 != archive["record_sha256"]:
        raise ValueError("The original native order archive/record changed; review again.")
    selected = compiler.effective.inspect(options.diagram_ref)
    refs = {options.diagram_ref, *(m["ref"] for m in selected["members"])}
    signatures = compiler.effective.wire.signatures
    if not refs <= signatures.keys():
        raise ValueError("A selected native execution-order member is no longer present.")
    guard = {
        "profile": GUARD_PROFILE,
        "diagram_ref": options.diagram_ref,
        "original_order": selected["original_order"],
        "payload_widths": [slot["payload_bytes"] for slot in selected["slots"]],
        "property_sha256": selected["property_sha256"],
        "edge_relationships_sha256": seal(selected["edge_relationships"]),
        "configuration_sha256": seal({ref: signatures[ref] for ref in sorted(refs)}),
    }
    validate_order_evidence(edit, guard)
    if fresh and expected_guard is None:
        raise ValueError("Fresh order compilation requires its reviewed configuration guard.")
    if expected_guard is not None:
        validate_order_evidence(edit, expected_guard)
        if guard != OrderConfigurationGuard.model_validate(expected_guard).model_dump():
            raise ValueError("The selected native order configuration changed after review.")
    if not fresh and (
        options.effective_sha256 != selected["source_sha256"]
        or options.effective_record_sha256 != selected["record_sha256"]
        or options.selection_sha256 != selected["selection_sha256"]
    ):
        raise ValueError("The effective native order changed; inspect and review again.")
    output, compilation = compiler.compile(
        diagram_ref=options.diagram_ref,
        selection_sha256=selected["selection_sha256"],
        proposed_order=options.proposed_order,
    )
    report = {
        **compilation,
        "order_guard": guard,
        "parameter_transfer_qualification": qualify_parameter_additions(
            output, compilation["parameter_merge"]
        ),
    }
    return output, {**report, "order_compilation_sha256": seal(report)}


def verify_order_preservation(before, after, edit, guard):
    if set(after) != {3, 11, 12}:
        raise ValueError("Order verification requires a complete native readback snapshot.")
    expected, compilation = compile_order(before, edit, fresh=True, expected_guard=guard)
    expected_native, observed = MoiIdentity(expected), MoiIdentity(after[3])
    if observed.data != expected_native.data:
        raise ValueError("Native application bytes differ from the reviewed execution order.")
    parameters = ParameterApplication(after[3], after[11], after[12])
    current, counters, calculated = runtime_parameter_changes(observed, parameters)
    effective, _ = parameters.compile()
    selected = MoiExecutionOrder(effective).inspect(edit["diagram_ref"])
    if (
        selected["original_order"] != edit["proposed_order"]
        or seal(selected["edge_relationships"]) != guard["edge_relationships_sha256"]
        or [slot["payload_bytes"] for slot in selected["slots"]] != guard["payload_widths"]
    ):
        raise ValueError("The effective saved order differs from the reviewed permutation.")
    previous, identity = MoiIdentity(before[3]).summary(), observed.summary()
    return {
        "profile": PRESERVATION_PROFILE,
        "application_matches_reviewed_order_and_fresh_settings": True,
        "other_merged_application_bytes_preserved": True,
        "identity_unchanged": all(
            identity[key] == previous[key] for key in ("instance", "name", "model", "root_class")
        ),
        "selected_order": {
            "diagram_ref": edit["diagram_ref"],
            "before": guard["original_order"],
            "after": selected["original_order"],
            "payload_widths": guard["payload_widths"],
            "edge_relationships_sha256": guard["edge_relationships_sha256"],
            "effective_order_verified": True,
        },
        "saved_application_parameters_verified": compilation["parameter_merge"][
            "matched_parameters"
        ],
        "post_saved_parameters": current["matched_parameters"],
        "runtime_counter_changes": counters,
        "device_calculated_changes": calculated,
        "source_application_sha256": sha(before[3]),
        "source_saved_parameters_sha256": sha(before[11] + before[12]),
        "verified_application_sha256": sha(after[3]),
        "preserved_native_sha256": sha(expected_native.data),
        "controller_writes": False,
    }


class NativeOrderOperations:
    @staticmethod
    def order_scope():
        return {
            "scope": "One execution-order permutation at the selected station",
            "devices": [],
            "checked_at": utc(),
            "limitation": "Device and native object identities are retained; no number is allocated.",
        }

    async def preview_order(self, **arguments):
        from . import native_applications

        options = OrderTransferPreview(**arguments)
        async with self.operation(options.operation_id, "review-execution-order"):
            self.available(options)
            if (self.storage.directory / options.capture_id).is_symlink():
                raise ValueError("Native order sources must stay in their original folder.")
            captured, files = self.check_capture(options)
            if captured["evidence_sha256"] != options.snapshot_sha256:
                raise ValueError("The native snapshot changed; reopen and review again.")
            edit = options.model_dump(include=set(OrderPreview.model_fields))
            _, local_review = NativeExecutionOrder(NativeBackupRecords(self.storage)).preview(edit)
            output, compilation = compile_order(files, edit)
            from .native_order_recovery_transfer import recovery_origin

            recovery = recovery_origin(self, options, compilation)
            config, app = copy.deepcopy(self.bacnet.config), self.bacnet.require()
            async with self.path._path(options) as session:
                from .property_evidence import PropertyEvidence

                PropertyEvidence.pin(session, options.router)
                actual, _ = await self.identity(session, options.device)
            if actual != captured["identity"]:
                raise ValueError("Controller identity changed after backup; capture again.")
            body = {
                "profile": APPLICATION_PROFILE,
                "operation_profile": PROFILE,
                "target": self.target(options),
                "identity": actual,
                "old_instance": ObjectIdentifier(options.device)[1],
                "new_instance": ObjectIdentifier(options.device)[1],
                "change_kind": "execution-order",
                "old_name": actual["object-name"],
                "new_name": actual["object-name"],
                "capture_id": options.capture_id,
                "snapshot_sha256": captured["evidence_sha256"],
                "application_sha256": sha(files[3]),
                "static_parameters_sha256": sha(files[11]),
                "order_edit": edit,
                "order_guard": compilation["order_guard"],
                "local_review": local_review,
                "compilation": compilation,
                "payload_sha256": sha(output),
                "collision_check": self.order_scope(),
                "parameter_policy": (
                    "Capture fresh application/settings before restore. Application, saved "
                    "directory and selected member configuration must match. Merge fresh saved "
                    "values; the final payload may differ from preview. Verify the full "
                    "application, effective order and all saved settings. No automatic inverse."
                ),
                "backup_effects": native_applications.backup_effects(),
                "scope": SCOPE,
                "vendor_runtime_required": False,
                "can_apply": True,
                "connector_config": config,
                "created_at": utc(),
                "expires_at": (
                    datetime.now(UTC) + timedelta(seconds=native_applications.PLAN_SECONDS)
                ).isoformat(),
                **recovery,
            }
            return self.retain_plan(body, options, app, config)

    async def apply_order(self, **arguments):
        return await self.apply_reviewed(
            OrderTransferApply(**arguments), default_edit=False, order_edit=True
        )
