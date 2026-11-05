"""Separately versioned analog terminal movement under native input transfer gates."""

from .moi_identity import MoiIdentity, sha
from .moi_terminal_copies import MoiTerminalCopies
from .native_inputs import CONFIG, TERMINAL_PROFILE, configuration_guard


def compile_terminal_input(compiler, edit, record):
    app = compiler.app
    if record is None or configuration_guard(app, record) != edit.configuration_sha256:
        raise ValueError("The existing analog input configuration changed; capture again.")
    old_slot = app.reader.scalar(record, 519)
    if edit.slot == old_slot:
        raise ValueError("Choose a different documented free universal terminal.")
    copier = MoiTerminalCopies(app.source, output_namespace=True)
    ref = app.reader.scalar(record, 32527)
    selected = copier.inputs.get(ref)
    if selected is None or selected["class_id"] != 240 or not selected["movable"]:
        raise ValueError("This field profile requires one existing movable local analog input.")
    output, proof = copier.compile(
        source_sha256=app.source_sha256,
        ref=ref,
        record_sha256=selected["record_sha256"],
        slot_property_sha256=selected["slot_property_sha256"],
        device_type_property_sha256=selected["device_type_property_sha256"],
        old_slot=old_slot,
        destination_slot=edit.slot,
    )
    actual = MoiIdentity(output)
    changed = actual.reader.records[ref]
    return output, {
        "profile": TERMINAL_PROFILE,
        "input_edit": edit.model_dump(),
        "object_id": selected["object"],
        "record_ref": ref,
        "changes": [
            {"property": 31, "before": selected["device_type"], "after": f"UI IN{edit.slot}"},
            {"property": 519, "before": old_slot, "after": edit.slot},
        ],
        "stored_configuration": {
            label: actual.reader.scalar(changed, pid) for pid, label in CONFIG.items()
        },
        "parameter_merge": compiler.parameters,
        "parameter_transfer_qualification": compiler.qualification,
        "compiled_native_sha256": sha(actual.data),
        "native_record_count": len(actual.records),
        "original_native_record_count": len(app.records),
        "allocated_record_hex": None,
        "other_records_preserved": True,
        "wires_changed": False,
        "terminal_compilation": proof,
    }
