"""One existing wire-source edit through the shared durable native restore path."""

from typing import Literal

from pydantic import Field, StrictBool, model_validator

from .application_preservation import runtime_parameter_changes
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_effective_wire import EffectiveWireCompiler
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .moi_wire_sources import MoiWireSources
from .native_wire_compiler import EffectiveWirePreview
from .native_wire_copies import UInt

PROFILE = "native-effective-wire-source-transfer/1"
SCOPE = (
    "Transfer one existing native wire source while retaining Device identity and all "
    "other fresh merged settings. Guard the selected graph/source/target configuration "
    "and observed pin, order, cycle and original width. Capture/readback can enter/end "
    "backup mode; Apply can interrupt control through one application restore. No new "
    "blocks/connections/I/O, general compiler, resource/package or physical acceptance."
)


class WireTransferPreview(EffectiveWirePreview, DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    recovery_parent_receipt: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    recovery_origin_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def recovery_binding(self):
        if (self.recovery_parent_receipt is None) != (self.recovery_origin_sha256 is None):
            raise ValueError("Provide both the wire recovery parent and prepared origin hash.")
        return self


class WireTransferApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    wire_change_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


class WireConfigurationGuard(StrictModel):
    profile: Literal["native-wire-source-configuration-guard/1"]
    diagram_ref: str = Field(min_length=1, max_length=512, strict=True)
    wire_index: int = Field(ge=0, le=4095, strict=True)
    old: list[UInt] = Field(min_length=4, max_length=4)
    source_ref: str = Field(min_length=1, max_length=512, strict=True)
    configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def validate_wire_evidence(edit, guard):
    EffectiveWirePreview.model_validate(edit)
    WireConfigurationGuard.model_validate(guard)


def compile_wire(files, edit, *, fresh=False, expected_guard=None):
    options = EffectiveWirePreview.model_validate(edit)
    compiler = EffectiveWireCompiler(files)
    record = compiler.archive.reader.records.get(options.diagram_ref)
    if (
        options.source_sha256 != sha(files[3])
        or record is None
        or (record["sha256"] != options.record_sha256)
    ):
        raise ValueError(
            "The original native wire archive/record changed; capture and review again."
        )
    selected = compiler.effective.inspect(options.diagram_ref, options.wire_index)
    wire = selected["selected_wire"]
    if wire is None:
        raise ValueError("Select an existing native connection; no wire is allocated.")
    refs = {options.diagram_ref, wire["source_ref"], options.source_ref, wire["target_ref"]}
    if not refs <= compiler.effective.signatures.keys():
        raise ValueError("A selected native wire source/target is no longer present.")
    guard = {
        "profile": "native-wire-source-configuration-guard/1",
        "diagram_ref": options.diagram_ref,
        "wire_index": options.wire_index,
        "old": wire["old"],
        "source_ref": options.source_ref,
        "configuration_sha256": seal(
            {ref: compiler.effective.signatures[ref] for ref in sorted(refs)}
        ),
    }
    if fresh and expected_guard is None:
        raise ValueError("Fresh wire compilation requires its reviewed configuration guard.")
    if expected_guard is not None:
        expected_guard = WireConfigurationGuard.model_validate(expected_guard).model_dump()
    if expected_guard is not None and guard != expected_guard:
        raise ValueError("The selected native wire configuration changed after review.")
    output, compilation = compiler.compile(
        effective_sha256=compiler.effective.editor.source_sha256
        if fresh
        else options.effective_sha256,
        effective_record_sha256=selected["record_sha256"]
        if fresh
        else options.effective_record_sha256,
        **options.model_dump(
            include={"diagram_ref", "property_sha256", "wire_index", "old", "source_ref"}
        ),
    )
    return output, {**compilation, "wire_guard": guard}


def verify_wire_preservation(before, after, edit, guard):
    if set(after) != {3, 11, 12}:
        raise ValueError("Wire verification requires a complete native readback snapshot.")
    expected, compilation = compile_wire(before, edit, fresh=True, expected_guard=guard)
    expected_native, observed = MoiIdentity(expected), MoiIdentity(after[3])
    if observed.data != expected_native.data:
        raise ValueError("Native application bytes differ from the one reviewed wire edit.")
    parameters = ParameterApplication(after[3], after[11], after[12])
    current, counters, calculated = runtime_parameter_changes(observed, parameters)
    effective, _ = parameters.compile()
    selection = MoiWireSources(effective).inspect(edit["diagram_ref"], edit["wire_index"])
    wanted, actual = compilation["wire_edit"], selection["selected_wire"]
    if (
        actual is None
        or actual["old"] != wanted["new"]
        or (actual["source_ref"] != wanted["source_ref"])
    ):
        raise ValueError("The effective saved connection differs from the reviewed wire.")
    old_identity, actual_identity = MoiIdentity(before[3]).summary(), observed.summary()
    return {
        "profile": "native-effective-wire-source-preservation/1",
        "application_identical_except_selected_wire": True,
        "identity_unchanged": all(
            actual_identity[key] == old_identity[key]
            for key in ("instance", "name", "model", "root_class")
        ),
        "selected_wire": {
            "diagram_ref": edit["diagram_ref"],
            "wire_index": edit["wire_index"],
            "old": wanted["old"],
            "new": wanted["new"],
            "old_source_ref": wanted["old_source_ref"],
            "source_ref": actual["source_ref"],
            "target_ref": actual["target_ref"],
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
