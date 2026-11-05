"""One prototype-matched connection through the durable native restore path."""

import copy
from datetime import UTC, datetime, timedelta
from typing import Literal

from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field, StrictBool

from .application_preservation import runtime_parameter_changes
from .application_store import PROFILE as APPLICATION_PROFILE
from .application_store import utc
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_connection_copies import MoiConnectionCopies
from .moi_effective_connection import EffectiveConnectionCompiler
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .native_connection_compiler import EffectiveConnectionPreview
from .native_connection_copies import Hash, Reference, UInt
from .native_parameter_qualification import qualify_parameter_additions

PROFILE = "native-effective-matching-connection-transfer/1"
GUARD_PROFILE = "native-matching-connection-configuration-guard/1"
PRESERVATION_PROFILE = "native-effective-matching-connection-preservation/1"
SCOPE = (
    "Transfer one prototype-matched connection between existing native members. Require "
    "an observed output pin, unused matching input, execution order, cycle and size guards. "
    "Preserve controller identity, original graph members/order/layout/continuation and all "
    "other fresh merged settings. Capture/readback can enter/end backup mode; one application "
    "restore can interrupt control. No new blocks/I/O, automatic inverse deletion, general "
    "compiler/resource/package/runtime or CCT/physical acceptance."
)


class ConnectionTransferPreview(EffectiveConnectionPreview, DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class ConnectionTransferApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: Hash
    connection_change_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


class ConnectionConfigurationGuard(StrictModel):
    profile: Literal[GUARD_PROFILE]
    diagram_ref: Reference
    prototype_index: int = Field(ge=0, le=4095, strict=True)
    prototype_old: list[UInt] = Field(min_length=4, max_length=4)
    connection_count: int = Field(ge=1, le=4095, strict=True)
    source_ref: Reference
    target_ref: Reference
    property_sha256: Hash
    metadata_property_sha256: Hash | None
    configuration_sha256: Hash


def validate_connection_evidence(edit, guard):
    options = EffectiveConnectionPreview.model_validate(edit)
    checked = ConnectionConfigurationGuard.model_validate(guard)
    if (
        options.prototype_index >= options.connection_count
        or options.source_ref == options.target_ref
        or any(
            getattr(options, key) != getattr(checked, key)
            for key in (
                "diagram_ref",
                "prototype_index",
                "prototype_old",
                "connection_count",
                "source_ref",
                "target_ref",
                "property_sha256",
                "metadata_property_sha256",
            )
        )
    ):
        raise ValueError("The recorded native connection proposal and guard disagree.")


def compile_connection(files, edit, *, fresh=False, expected_guard=None):
    options = EffectiveConnectionPreview.model_validate(edit)
    compiler = EffectiveConnectionCompiler(files)
    record = compiler.archive.wire.reader.records.get(options.diagram_ref)
    if (
        options.source_sha256 != sha(files[3])
        or record is None
        or record["sha256"] != options.record_sha256
    ):
        raise ValueError("The original native connection archive/record changed; review again.")
    selected = compiler.effective.inspect(
        options.diagram_ref, options.prototype_index, options.source_ref
    )
    prototype = selected["prototype"]
    if prototype is None:
        raise ValueError("Select an actual recorded native connection prototype.")
    refs = {
        options.diagram_ref,
        prototype["source_ref"],
        prototype["target_ref"],
        options.source_ref,
        options.target_ref,
    }
    signatures = compiler.effective.wire.signatures
    if not refs <= signatures.keys():
        raise ValueError("A selected native connection source/target is no longer present.")
    guard = {
        "profile": GUARD_PROFILE,
        "diagram_ref": options.diagram_ref,
        "prototype_index": options.prototype_index,
        "prototype_old": prototype["old"],
        "connection_count": selected["connection_count"],
        "source_ref": options.source_ref,
        "target_ref": options.target_ref,
        "property_sha256": selected["property_sha256"],
        "metadata_property_sha256": selected["metadata_property_sha256"],
        "configuration_sha256": seal({ref: signatures[ref] for ref in sorted(refs)}),
    }
    validate_connection_evidence(edit, guard)
    if fresh and expected_guard is None:
        raise ValueError("Fresh connection compilation requires its reviewed configuration guard.")
    if expected_guard is not None:
        validate_connection_evidence(edit, expected_guard)
        if guard != ConnectionConfigurationGuard.model_validate(expected_guard).model_dump():
            raise ValueError("The selected native connection configuration changed after review.")
    output, compilation = compiler.compile(
        effective_sha256=compiler.effective.editor.source_sha256
        if fresh
        else options.effective_sha256,
        effective_record_sha256=selected["record_sha256"]
        if fresh
        else options.effective_record_sha256,
        **options.model_dump(
            include={
                "diagram_ref",
                "property_sha256",
                "metadata_property_sha256",
                "prototype_index",
                "prototype_old",
                "connection_count",
                "source_ref",
                "target_ref",
            }
        ),
    )
    report = {
        **compilation,
        "connection_guard": guard,
        "parameter_transfer_qualification": qualify_parameter_additions(
            output, compilation["parameter_merge"]
        ),
    }
    return output, {**report, "connection_compilation_sha256": seal(report)}


def verify_connection_preservation(before, after, edit, guard):
    if set(after) != {3, 11, 12}:
        raise ValueError("Connection verification requires a complete native readback snapshot.")
    expected, compilation = compile_connection(before, edit, fresh=True, expected_guard=guard)
    expected_native, observed = MoiIdentity(expected), MoiIdentity(after[3])
    if observed.data != expected_native.data:
        raise ValueError("Native application bytes differ from the one reviewed connection.")
    parameters = ParameterApplication(after[3], after[11], after[12])
    current, counters, calculated = runtime_parameter_changes(observed, parameters)
    effective, _ = parameters.compile()
    selection = MoiConnectionCopies(effective).inspect(
        edit["diagram_ref"], edit["prototype_index"], edit["source_ref"]
    )
    wanted = compilation["connection_edit"]
    index = wanted["connection_count_before"]
    if selection["connection_count"] != wanted["connection_count_after"]:
        raise ValueError("The effective saved connection count differs from the reviewed append.")
    actual = selection["wires"][index]
    if (
        actual["old"] != wanted["new"]
        or actual["source_ref"] != wanted["source_ref"]
        or actual["target_ref"] != wanted["target_ref"]
    ):
        raise ValueError("The effective saved connection differs from the reviewed append.")
    previous, identity = MoiIdentity(before[3]).summary(), observed.summary()
    return {
        "profile": PRESERVATION_PROFILE,
        "application_matches_reviewed_connection_and_fresh_settings": True,
        "other_merged_application_bytes_preserved": True,
        "identity_unchanged": all(
            identity[key] == previous[key] for key in ("instance", "name", "model", "root_class")
        ),
        "selected_connection": {
            "diagram_ref": edit["diagram_ref"],
            "prototype_index": edit["prototype_index"],
            "prototype_old": wanted["prototype_old"],
            "index": index,
            "new": wanted["new"],
            "source_ref": actual["source_ref"],
            "target_ref": actual["target_ref"],
            "connection_count_before": index,
            "connection_count_after": wanted["connection_count_after"],
            "continuation_prototype_sha256": wanted["continuation_prototype_sha256"],
            "effective_connection_verified": True,
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


class NativeConnectionOperations:
    @staticmethod
    def connection_scope():
        return {
            "scope": "One matching connection between existing members at the selected station",
            "devices": [],
            "checked_at": utc(),
            "limitation": "Device and native object identities are retained; no number is allocated.",
        }

    async def preview_connection(self, **arguments):
        from . import native_applications

        options = ConnectionTransferPreview(**arguments)
        async with self.operation(options.operation_id, "review-connection"):
            self.available(options)
            if (self.storage.directory / options.capture_id).is_symlink():
                raise ValueError("Native connection sources must stay in their original folder.")
            captured, files = self.check_capture(options)
            if captured["evidence_sha256"] != options.snapshot_sha256:
                raise ValueError("The native snapshot changed; reopen and review again.")
            edit = options.model_dump(include=set(EffectiveConnectionPreview.model_fields))
            output, compilation = compile_connection(files, edit)
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
                "change_kind": "connection",
                "old_name": actual["object-name"],
                "new_name": actual["object-name"],
                "capture_id": options.capture_id,
                "snapshot_sha256": captured["evidence_sha256"],
                "application_sha256": sha(files[3]),
                "static_parameters_sha256": sha(files[11]),
                "connection_edit": edit,
                "connection_guard": compilation["connection_guard"],
                "compilation": compilation,
                "payload_sha256": sha(output),
                "collision_check": self.connection_scope(),
                "parameter_policy": (
                    "Capture fresh application/settings before restore. Application, saved "
                    "directory and selected graph/prototype/source/target configuration must "
                    "match. Merge other fresh saved values; the final payload may differ from "
                    "preview. Verify the full application, appended effective connection and "
                    "all saved settings. No automatic inverse deletion."
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
            }
            return self.retain_plan(body, options, app, config)

    async def apply_connection(self, **arguments):
        return await self.apply_reviewed(
            ConnectionTransferApply(**arguments), default_edit=False, connection_edit=True
        )
