"""Typed batch guards and complete preservation for one native application restore."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from .application_preservation import runtime_parameter_changes
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_default_batch import EffectiveDefaultBatchCompiler
from .moi_identity import MoiIdentity, sha
from .moi_parameters import ParameterApplication
from .native_default_batch import BatchPreview
from .native_parameter_qualification import qualify_parameter_additions

PROFILE = "native-effective-default-batch-transfer/1"
SCOPE = (
    "Transfer 1–16 existing typed native defaults through one guarded application restore. "
    "Require unchanged selected effective values/encodings and actual fixed saved storage "
    "for each selected Enum. Merge other fresh saved settings and verify complete native "
    "bytes and every selected effective value. Capture/readback enter/end backup mode; "
    "Apply can interrupt control. Enum meanings, general logic, package/runtime/CCT and "
    "physical acceptance remain unverified."
)


class BatchTransferPreview(BatchPreview, DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    recovery_parent_receipt: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    recovery_origin_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def recovery_binding(self):
        if (self.recovery_parent_receipt is None) != (self.recovery_origin_sha256 is None):
            raise ValueError("Provide both the recovery parent receipt and prepared origin hash.")
        return self


class BatchTransferApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    defaults_change_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


class _SelectedGuard(StrictModel):
    record_ref: str = Field(min_length=1, max_length=512, strict=True)
    encoded_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    property: Literal[3113]


class RealGuard(_SelectedGuard):
    kind: Literal["real"]
    class_id: Literal[526, 527]
    prior_bits: str = Field(pattern=r"^[0-9a-f]{8}$")


class BooleanGuard(_SelectedGuard):
    kind: Literal["boolean"]
    class_id: Literal[530, 531]
    prior_value: StrictBool


class EnumSlot(StrictModel):
    kind: Literal["captured-fixed-enum-slot"]
    datatype: Literal[9]
    bytes: Literal[2]
    maximum_code: Literal[65535]
    static_record_offset: StrictInt = Field(ge=0, le=2 * 1024 * 1024)
    dynamic_value_offset: StrictInt = Field(ge=0, le=2 * 1024 * 1024)


class EnumGuard(_SelectedGuard):
    kind: Literal["enum"]
    class_id: Literal[528, 529]
    prior_value: StrictInt = Field(ge=0, le=65535)
    saved_storage: EnumSlot
    states_text_encoded_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


SelectedGuard = Annotated[RealGuard | BooleanGuard | EnumGuard, Field(discriminator="kind")]


class BatchConfigurationGuard(StrictModel):
    profile: Literal["native-default-batch-configuration-guard/1"]
    fields: list[SelectedGuard] = Field(min_length=1, max_length=16)


def validate_batch_evidence(edit, guard):
    options = BatchPreview.model_validate(edit)
    checked = BatchConfigurationGuard.model_validate(guard)
    if len(options.changes) != len(checked.fields) or len(
        {f.record_ref for f in checked.fields}
    ) != len(checked.fields):
        raise ValueError("Batch changes and distinct selected guards must agree.")
    for change, field in zip(options.changes, checked.fields, strict=True):
        if any(
            getattr(change, key) != getattr(field, key)
            for key in ("kind", "record_ref", "encoded_sha256")
        ):
            raise ValueError("Batch native edits and configuration guards disagree.")
    return options, checked


def _guard_field(row):
    f, kind = row["field"], row["kind"]
    common = {
        "kind": kind,
        "record_ref": f["ref"],
        "class_id": f["class_id"],
        "property": f["property"],
        "encoded_sha256": f["encoded_sha256"],
    }
    if kind == "real":
        return {**common, "prior_bits": f["effective_bits"]}
    if kind == "boolean":
        return {**common, "prior_value": f["effective_value"]}
    if f["saved_storage"] is None:
        raise ValueError(
            "Every selected Enum requires its actual captured fixed saved slot for transfer."
        )
    return {
        **common,
        "prior_value": f["effective_value"],
        "saved_storage": f["saved_storage"],
        "states_text_encoded_sha256": f["states_text_encoded_sha256"],
    }


def compile_batch_defaults(files, edit, *, fresh=False, expected_guard=None):
    options = BatchPreview.model_validate(edit)
    compiler = EffectiveDefaultBatchCompiler(files)
    if options.source_sha256 != sha(files[3]):
        raise ValueError("The original native batch application changed.")
    if fresh and expected_guard is None:
        raise ValueError("Fresh batch compilation requires its reviewed selected-field guards.")
    if not fresh and options.effective_sha256 != sha(compiler.merged):
        raise ValueError("The original native batch saved merge changed.")
    fields = {(r["kind"], r["field"]["ref"]): r for r in compiler.fields()}
    selected = []
    for change in options.changes:
        row = fields.get((change.kind, change.record_ref))
        if row is None:
            raise ValueError("A selected typed native default is no longer present.")
        selected.append(_guard_field(row))
    guard = {"profile": "native-default-batch-configuration-guard/1", "fields": selected}
    _, checked = validate_batch_evidence(edit, guard)
    if expected_guard is not None:
        _, expected = validate_batch_evidence(edit, expected_guard)
        if checked != expected:
            raise ValueError(
                "A selected effective native default, type, capacity or Enum state metadata changed after review."
            )
    output, compilation = compiler.compile([change.model_dump() for change in options.changes])
    return output, {
        **compilation,
        "batch_guard": guard,
        "parameter_transfer_qualification": qualify_parameter_additions(
            output, compilation["parameter_merge"]
        ),
    }


class _VerifiedSelectedBatchEnums:
    """Omit only already-proved equal Enum codes from tag-width comparisons."""

    def __init__(self, post, selected):
        self.post, self.selected = post, selected

    def compile(self):
        merged, report = self.post.compile()
        return merged, {
            **report,
            "changed_parameters": [
                row
                for row in report["changed_parameters"]
                if (row["class"], row["instance"], row["property"]) not in self.selected
            ],
        }


def verify_batch_preservation(before, after, edit, guard):
    options, checked = validate_batch_evidence(edit, guard)
    if set(after) != {3, 11, 12}:
        raise ValueError(
            "Batch verification requires complete native application/settings readback."
        )
    expected, compilation = compile_batch_defaults(before, edit, fresh=True, expected_guard=guard)
    wanted, observed = MoiIdentity(expected), MoiIdentity(after[3])
    if observed.data != wanted.data:
        raise ValueError("Native application differs from the reviewed batch defaults.")
    effective = EffectiveDefaultBatchCompiler(after)
    fields = {(r["kind"], r["field"]["ref"]): r["field"] for r in effective.fields()}
    verified, enums = [], set()
    for change, old, proof in zip(
        options.changes, checked.fields, compilation["selected"], strict=True
    ):
        field = fields.get((change.kind, change.record_ref))
        if field is None or field["class_id"] != old.class_id:
            raise ValueError(
                "A selected typed native default is missing or reassigned in readback."
            )
        if change.kind == "real":
            if field["effective_bits"] != proof["after_encoding_hex"][2:-2]:
                raise ValueError("A selected saved Real value differs from the reviewed batch.")
            value = {"before_bits": old.prior_bits, "after_bits": field["effective_bits"]}
        else:
            if (
                type(field["effective_value"]) is not type(change.value)
                or field["effective_value"] != change.value
            ):
                raise ValueError("A selected saved typed value differs from the reviewed batch.")
            value = {"before_value": old.prior_value, "after_value": field["effective_value"]}
        if change.kind == "enum":
            if field["states_text_encoded_sha256"] != old.states_text_encoded_sha256:
                raise ValueError("Selected Enum state metadata changed in readback.")
            record = observed.reader.records[change.record_ref]
            oid = int.from_bytes(observed.data[record["offset"] + 6 : record["offset"] + 10], "big")
            enums.add((record["class_id"], oid & 4194303, 3113))
        verified.append(
            {
                "kind": change.kind,
                "record_ref": change.record_ref,
                "class_id": old.class_id,
                "effective_value_verified": True,
                **value,
            }
        )
    current, counters, calculated = runtime_parameter_changes(
        observed,
        _VerifiedSelectedBatchEnums(ParameterApplication(after[3], after[11], after[12]), enums),
    )
    original, actual = MoiIdentity(before[3]).summary(), observed.summary()
    return {
        "profile": "native-effective-default-batch-preservation/1",
        "application_identical_except_selected_defaults": True,
        "identity_unchanged": all(
            actual[k] == original[k] for k in ("instance", "name", "model", "root_class")
        ),
        "selected_defaults": verified,
        "saved_application_parameters_verified": compilation["parameter_merge"][
            "matched_parameters"
        ],
        "post_saved_parameters": current["matched_parameters"],
        "runtime_counter_changes": counters,
        "device_calculated_changes": calculated,
        "source_application_sha256": sha(before[3]),
        "source_saved_parameters_sha256": sha(before[11] + before[12]),
        "verified_application_sha256": sha(after[3]),
        "preserved_native_sha256": sha(wanted.data),
        "enum_semantics_verified": False,
        "controller_writes": False,
    }
