"""Guarded native Real-default and existing-wire transfer compilation/readback."""

from typing import Literal

from pydantic import Field, StrictBool

from .application_preservation import runtime_parameter_changes
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_default_wire import EffectiveDefaultWireCompiler
from .moi_identity import MoiIdentity, sha
from .moi_parameters import ParameterApplication
from .moi_wire_sources import MoiWireSources
from .native_default_wire import CombinedPreview
from .native_parameter_qualification import qualify_parameter_additions
from .native_signal_compiler import EffectiveSignalCompiler
from .native_wire_compiler import EffectiveWirePreview
from .native_wire_transfer import WireConfigurationGuard, compile_wire

PROFILE = "native-effective-default-wire-transfer/1"
SCOPE = (
    "Transfer one existing native Real default and one existing connection source through "
    "one guarded application restore. Keep identity, all other fresh merged settings, "
    "graph structure and configuration. Capture/readback enter/end backup mode; Apply can "
    "interrupt control. No new blocks/IDs/connections/I/O, general compiler, package/resource "
    "qualification, native execution proof or CCT/physical acceptance."
)


class CombinedTransferPreview(CombinedPreview, DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class CombinedTransferApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    default_change_confirmed: StrictBool
    wire_change_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


class CombinedConfigurationGuard(StrictModel):
    profile: Literal["native-default-wire-configuration-guard/1"]
    record_ref: str = Field(min_length=1, max_length=512, strict=True)
    encoded_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prior_bits: str = Field(pattern=r"^[0-9a-f]{8}$")
    wire_guard: WireConfigurationGuard


def validate_evidence(edit, guard):
    options = CombinedPreview.model_validate(edit)
    checked = CombinedConfigurationGuard.model_validate(guard)
    if (
        checked.record_ref != options.record_ref
        or checked.encoded_sha256 != options.encoded_sha256
        or checked.wire_guard.diagram_ref != options.diagram_ref
        or checked.wire_guard.wire_index != options.wire_index
        or checked.wire_guard.old != options.old
        or checked.wire_guard.source_ref != options.source_ref
    ):
        raise ValueError("Combined native edit and configuration guard disagree.")
    return options, checked


def compile_combined(files, edit, *, fresh=False, expected_guard=None):
    options = CombinedPreview.model_validate(edit)
    compiler = EffectiveDefaultWireCompiler(files)
    original = compiler.wire.archive.reader.records.get(options.diagram_ref)
    if (
        options.source_sha256 != sha(files[3])
        or original is None
        or original["sha256"] != options.record_sha256
    ):
        raise ValueError("The original combined native archive/diagram changed.")
    if fresh and expected_guard is None:
        raise ValueError("Fresh combined compilation requires its reviewed configuration guard.")
    if expected_guard is not None:
        _, expected = validate_evidence(edit, expected_guard)
    else:
        expected = None
    field = next((f for f in compiler.signal.fields() if f["ref"] == options.record_ref), None)
    if field is None:
        raise ValueError("The reviewed combined Real default is no longer present.")
    if expected is not None and (
        field["effective_bits"] != expected.prior_bits
        or field["encoded_sha256"] != expected.encoded_sha256
    ):
        raise ValueError("The selected combined effective default changed after review.")
    _, wire_compilation = compile_wire(
        files,
        options.model_dump(include=set(EffectiveWirePreview.model_fields)),
        fresh=fresh,
        expected_guard=expected.wire_guard.model_dump() if expected else None,
        _compiler=compiler.wire,
    )
    guard = {
        "profile": "native-default-wire-configuration-guard/1",
        "record_ref": field["ref"],
        "encoded_sha256": field["encoded_sha256"],
        "prior_bits": field["effective_bits"],
        "wire_guard": wire_compilation["wire_guard"],
    }
    if expected is not None and guard != expected.model_dump():
        raise ValueError("The combined native configuration changed after review.")
    request = options.model_dump(
        exclude={"capture_id", "snapshot_sha256", "source_sha256", "record_sha256"}
    )
    if fresh:
        selected = compiler.wire.effective.inspect(options.diagram_ref, options.wire_index)
        request.update(
            effective_sha256=compiler.wire.effective.editor.source_sha256,
            effective_record_sha256=selected["record_sha256"],
        )
    output, compilation = compiler.compile(**request)
    return output, {
        **compilation,
        "combined_guard": guard,
        "parameter_transfer_qualification": qualify_parameter_additions(
            output, compilation["parameter_merge"]
        ),
    }


def verify_combined_preservation(before, after, edit, guard):
    validate_evidence(edit, guard)
    if set(after) != {3, 11, 12}:
        raise ValueError("Combined verification requires a complete native readback snapshot.")
    expected, compilation = compile_combined(before, edit, fresh=True, expected_guard=guard)
    wanted, observed = MoiIdentity(expected), MoiIdentity(after[3])
    if observed.data != wanted.data:
        raise ValueError("Native application differs from the two reviewed combined edits.")
    parameters = ParameterApplication(after[3], after[11], after[12])
    current, counters, calculated = runtime_parameter_changes(observed, parameters)
    effective = EffectiveSignalCompiler(after)
    field = next((f for f in effective.fields() if f["ref"] == edit["record_ref"]), None)
    real = compilation["selected_default"]
    if field is None or field["effective_bits"] != real["after_bits"]:
        raise ValueError("The effective combined Real default differs from the reviewed value.")
    selection = MoiWireSources(effective.merged).inspect(edit["diagram_ref"], edit["wire_index"])
    wire, actual = compilation["selected_wire"], selection["selected_wire"]
    if actual is None or actual["old"] != wire["new"] or actual["source_ref"] != wire["source_ref"]:
        raise ValueError("The effective combined connection differs from the reviewed source.")
    original_identity, actual_identity = MoiIdentity(before[3]).summary(), observed.summary()
    return {
        "profile": "native-effective-default-wire-preservation/1",
        "application_identical_except_selected_default_and_wire": True,
        "identity_unchanged": all(
            actual_identity[k] == original_identity[k]
            for k in ("instance", "name", "model", "root_class")
        ),
        "selected_default": {
            "record_ref": edit["record_ref"],
            "before_bits": real["before_bits"],
            "after_bits": real["after_bits"],
            "effective_bits": field["effective_bits"],
        },
        "selected_wire": {
            "diagram_ref": edit["diagram_ref"],
            "wire_index": edit["wire_index"],
            "old": wire["old"],
            "new": wire["new"],
            "old_source_ref": wire["old_source_ref"],
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
        "preserved_native_sha256": sha(wanted.data),
        "controller_writes": False,
    }
