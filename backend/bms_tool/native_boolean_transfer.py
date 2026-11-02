"""One strict effective Boolean-default edit through the native restore path."""

from pydantic import Field, model_validator

from .application_preservation import runtime_parameter_changes
from .device_details import DeviceDetailsRequest
from .moi_effective_boolean import EffectiveBooleanCompiler
from .moi_identity import MoiIdentity, sha
from .moi_parameters import ParameterApplication
from .native_boolean_copies import BooleanCopyPreview
from .native_parameter_qualification import qualify_parameter_additions

PROFILE = "native-effective-boolean-default-transfer/1"
SCOPE = (
    "Transfer one existing class 530/531 Boolean Default Value while preserving "
    "Device identity and all other fresh merged application settings. Capture/readback "
    "can enter/end backup mode; Apply can interrupt control through one application "
    "restore. No new blocks, links, I/O allocation, general logic or physical acceptance."
)


class BooleanTransferPreview(BooleanCopyPreview, DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    recovery_parent_receipt: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    recovery_origin_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def recovery_binding(self):
        if (self.recovery_parent_receipt is None) != (self.recovery_origin_sha256 is None):
            raise ValueError("Provide both the Boolean recovery parent and prepared origin hash.")
        return self


def compile_boolean_default(files, edit, *, expected_prior_value=None):
    compiler = EffectiveBooleanCompiler(files)
    field = next((row for row in compiler.fields() if row["ref"] == edit["record_ref"]), None)
    if field is None:
        raise ValueError("The reviewed native Boolean default is no longer present.")
    if expected_prior_value is not None and (
        type(expected_prior_value) is not bool
        or field["effective_value"] is not expected_prior_value
        or field["encoded_sha256"] != edit["encoded_sha256"]
    ):
        raise ValueError(
            "The selected effective Boolean default changed after review. Capture and review again."
        )
    output, report = compiler.compile(**edit)
    report["parameter_transfer_qualification"] = qualify_parameter_additions(
        output, report["parameter_merge"]
    )
    return output, report


def verify_boolean_preservation(before, after, edit):
    if set(after) != {3, 11, 12}:
        raise ValueError("Boolean verification requires a complete native readback snapshot.")
    expected, compilation = compile_boolean_default(before, edit)
    expected_native, observed = MoiIdentity(expected), MoiIdentity(after[3])
    if observed.data != expected_native.data:
        raise ValueError("Native bytes differ from the one reviewed Boolean default edit.")
    current, counters, calculated = runtime_parameter_changes(
        observed, ParameterApplication(after[3], after[11], after[12])
    )
    effective = EffectiveBooleanCompiler(after)
    field = next((row for row in effective.fields() if row["ref"] == edit["record_ref"]), None)
    wanted = compilation["selected_edit"]["after_value"]
    if field is None or type(wanted) is not bool or field["effective_value"] is not wanted:
        raise ValueError("The effective saved Boolean default does not match the reviewed value.")
    old_identity, actual_identity = MoiIdentity(before[3]).summary(), observed.summary()
    return {
        "profile": "native-effective-boolean-default-preservation/1",
        "application_identical_except_selected_default": True,
        "identity_unchanged": all(
            actual_identity[key] == old_identity[key]
            for key in ("instance", "name", "model", "root_class")
        ),
        "selected_default": {
            "record_ref": edit["record_ref"],
            "before_value": compilation["selected_edit"]["before_value"],
            "after_value": wanted,
            "effective_value": field["effective_value"],
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
