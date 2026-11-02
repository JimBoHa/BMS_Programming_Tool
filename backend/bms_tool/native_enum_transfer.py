"""One existing fixed-storage Enum code through the guarded native restore path."""

from pydantic import Field

from .application_preservation import runtime_parameter_changes
from .device_details import DeviceDetailsRequest
from .moi_effective_enum import EffectiveEnumCompiler
from .moi_identity import MoiIdentity, sha
from .moi_parameters import ParameterApplication
from .native_enum_copies import EnumCopyPreview
from .native_parameter_qualification import qualify_parameter_additions

PROFILE = "native-effective-enum-default-transfer/1"
SCOPE = (
    "Transfer one existing class 528/529 Enumerated Default Value with an actual "
    "captured fixed Enum slot. Preserve Device identity and all other fresh merged "
    "application settings. Numeric capacity is not an allowed-state table; code "
    "membership and state meanings remain unverified. Capture/readback can enter/end "
    "backup mode; Apply can interrupt control through one application restore. "
    "No new blocks, executable mapping, general compiler or physical acceptance."
)


class EnumTransferPreview(EnumCopyPreview, DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


def compile_enum_default(files, edit, *, expected_prior_value=None):
    compiler = EffectiveEnumCompiler(files)
    field = next((row for row in compiler.fields() if row["ref"] == edit["record_ref"]), None)
    if field is None:
        raise ValueError("The reviewed native Enum default is no longer present.")
    if field["saved_storage"] is None:
        raise ValueError(
            "Enum transfer requires the selected captured fixed Enum slot. "
            "A UInt32 local copy alone does not qualify transfer."
        )
    if expected_prior_value is not None and (
        type(expected_prior_value) is not int
        or field["effective_value"] != expected_prior_value
        or field["encoded_sha256"] != edit["encoded_sha256"]
    ):
        raise ValueError(
            "The selected effective Enum code changed after review. Capture and review again."
        )
    output, compilation = compiler.compile(**edit)
    compilation["parameter_transfer_qualification"] = qualify_parameter_additions(
        output, compilation["parameter_merge"]
    )
    return output, compilation


class _VerifiedSelectedEnumSettings:
    """Exclude only an already proved equal selected code from other-setting checks.

    The archive writer retains the original tag width, while the saved-value
    serializer uses the minimal width. Complete File 3 bytes are checked before
    this adapter is used, and the selected saved code/datatype is checked below.
    Other saved parameters still pass the unchanged runtime-output classifier.
    """

    def __init__(self, post, selected):
        self.post, self.selected = post, selected

    def compile(self):
        merged, report = self.post.compile()
        report = {
            **report,
            "changed_parameters": [
                row
                for row in report["changed_parameters"]
                if (row["class"], row["instance"], row["property"]) != self.selected
            ],
        }
        return merged, report


def verify_enum_preservation(before, after, edit):
    if set(after) != {3, 11, 12}:
        raise ValueError("Enum verification requires a complete native readback snapshot.")
    expected, compilation = compile_enum_default(before, edit)
    expected_native, observed = MoiIdentity(expected), MoiIdentity(after[3])
    if observed.data != expected_native.data:
        raise ValueError("Native bytes differ from the one reviewed Enum code edit.")
    effective = EffectiveEnumCompiler(after)
    field = next((row for row in effective.fields() if row["ref"] == edit["record_ref"]), None)
    wanted = compilation["selected_edit"]["after_value"]
    if field is None or type(wanted) is not int or field["effective_value"] != wanted:
        raise ValueError("The effective saved Enum code does not match the reviewed value.")
    record, prop = effective.archive.candidates[edit["record_ref"]]
    if prop["scalar"] != {"datatype": "Enumerated", "value": wanted}:
        raise ValueError("The readback archive Enum code differs from the reviewed value.")
    native_id = int.from_bytes(observed.data[record["offset"] + 6 : record["offset"] + 10], "big")
    selected = (record["class_id"], native_id & 4194303, 3113)
    current, counters, calculated = runtime_parameter_changes(
        observed,
        _VerifiedSelectedEnumSettings(
            ParameterApplication(after[3], after[11], after[12]), selected
        ),
    )
    old_identity, actual_identity = MoiIdentity(before[3]).summary(), observed.summary()
    return {
        "profile": "native-effective-enum-default-preservation/1",
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
            "archive_encoding_sha256": prop["encoded_sha256"],
            "saved_encoding_sha256": field["encoded_sha256"],
            "equal_typed_code": True,
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
        "enum_semantics_verified": False,
        "controller_writes": False,
    }
