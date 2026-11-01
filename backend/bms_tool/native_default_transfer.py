"""One existing effective Real-default edit through the native application path."""

from pydantic import Field, StrictBool, model_validator

from .application_preservation import runtime_parameter_changes
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_identity import MoiIdentity, sha
from .moi_parameters import ParameterApplication
from .native_signal_compiler import EffectiveSignalCompiler, SignalCompilerPreview

PROFILE = "native-effective-default-transfer/1"
SCOPE = (
    "Transfer one existing native class 526/527 Real Default Value. Keep Device identity "
    "and all other fresh merged application settings. Capture and readback can enter/end "
    "backup mode; Apply can interrupt control through one application restore. "
    "No new block, link, I/O allocation, general graph generation or physical acceptance."
)


class DefaultTransferPreview(SignalCompilerPreview, DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    recovery_parent_receipt: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    recovery_origin_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def recovery_binding(self):
        if (self.recovery_parent_receipt is None) != (self.recovery_origin_sha256 is None):
            raise ValueError("Provide both the recovery parent receipt and prepared origin hash.")
        return self


class DefaultTransferApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    default_change_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


def compile_default(files, edit, *, expected_prior_bits=None):
    compiler = EffectiveSignalCompiler(files)
    fields = {row["ref"]: row for row in compiler.fields()}
    field = fields.get(edit["record_ref"])
    if field is None:
        raise ValueError("The reviewed native Real default is no longer present.")
    if expected_prior_bits is not None and (
        field["effective_bits"] != expected_prior_bits
        or field["encoded_sha256"] != edit["encoded_sha256"]
    ):
        raise ValueError(
            "The selected effective default changed after review. Capture and review again."
        )
    return compiler.compile(**edit)


def verify_default_preservation(before, after, edit):
    """Require exact compiled bytes and effective settings, allowing only known runtime outputs."""
    if set(after) != {3, 11, 12}:
        raise ValueError("Default verification requires a complete native readback snapshot.")
    expected, compilation = compile_default(before, edit)
    expected_native, observed = MoiIdentity(expected), MoiIdentity(after[3])
    if observed.data != expected_native.data:
        raise ValueError("Native application bytes differ from the one reviewed default edit.")
    post = ParameterApplication(after[3], after[11], after[12])
    current, counters, calculated = runtime_parameter_changes(observed, post)
    effective = EffectiveSignalCompiler(after)
    field = next((row for row in effective.fields() if row["ref"] == edit["record_ref"]), None)
    wanted = compilation["selected_edit"]["after_bits"]
    if field is None or field["effective_bits"] != wanted:
        raise ValueError("The effective saved default does not match the reviewed value.")
    original_identity, actual_identity = MoiIdentity(before[3]).summary(), observed.summary()
    return {
        "profile": "native-effective-default-preservation/1",
        "application_identical_except_selected_default": True,
        "identity_unchanged": all(
            actual_identity[key] == original_identity[key]
            for key in ("instance", "name", "model", "root_class")
        ),
        "selected_default": {
            "record_ref": edit["record_ref"],
            "before_bits": compilation["selected_edit"]["before_bits"],
            "after_bits": wanted,
            "effective_bits": field["effective_bits"],
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
