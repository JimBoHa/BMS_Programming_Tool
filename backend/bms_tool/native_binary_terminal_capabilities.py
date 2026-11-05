"""Explicit source-specific binary transfer witness; no retained edits or field authority."""

from .moi_effective_wire import compiler_from_snapshot as qualified_saved_merge
from .moi_identity import sha
from .native_binary_terminal import BinaryTerminalCompiler
from .native_inputs import NativeInputCompiler
from .native_terminal_label_capabilities import terminal_label_capabilities

PROFILE = "native-backup-operation-capabilities/17"
ROW = "binary-terminal-transfer"


def binary_witness(snapshot, files):
    qualified_saved_merge(snapshot, files)
    compiler = BinaryTerminalCompiler(NativeInputCompiler(files))
    source = compiler.source()
    slots = source["available_slots"]
    if not slots:
        raise ValueError("No recorded free universal destination is available.")
    failure = "No existing binary input passes this source profile."
    for selected in source["inputs"]:
        if selected["configuration_error"] is not None:
            failure = selected["configuration_error"][:512]
            continue
        try:
            output, compiled = compiler.compile(
                {
                    "action": "binary-terminal",
                    "object_instance": int(selected["object_id"].split(",")[1]),
                    "slot": slots[0],
                    "configuration_sha256": selected["configuration_sha256"],
                }
            )
            proof = compiled["terminal_compilation"]
            return {
                "source_sha256": sha(files[3]),
                "effective_sha256": compiler.app.source_sha256,
                "source_native_sha256": proof["source_native_sha256"],
                "parameter_merge": compiled["parameter_merge"],
                "object": selected["object_id"],
                "ref": selected["record_ref"],
                "old_slot": selected["slot"],
                "destination_slot": slots[0],
                "configuration_sha256": selected["configuration_sha256"],
                "stored_configuration": compiled["stored_configuration"],
                "captured_counter_values": compiled["captured_counter_values"],
                "counter_values_are_live": False,
                "device_type_character_encoding": proof["device_type_character_encoding"],
                "device_type_encoding_preserved": proof["device_type_encoding_preserved"],
                "operation_profile": compiled["profile"],
                "compiler_profile": proof["profile"],
                "output_sha256": sha(output),
                "output_native_sha256": proof["output_native_sha256"],
                "compilation_sha256": proof["compilation_sha256"],
                "free_slots": slots,
                "saved_settings_merged": True,
                "field_transfer_enabled": False,
                "physical_terminal_or_wiring_verified": False,
            }
        except ValueError as exc:
            failure = str(exc)[:512]
    raise ValueError(failure)


def binary_terminal_capabilities(snapshot, files, application, *, capability_profile=PROFILE):
    if capability_profile != PROFILE:
        raise ValueError("Select the explicit binary terminal capability profile.")
    report = terminal_label_capabilities(snapshot, files, application)
    result = failure = None
    try:
        result = binary_witness(snapshot, files)
    except (ValueError, StopIteration) as exc:
        failure = str(exc)[:512] or "No existing binary input passes this source profile."
    q = report["qualification"]
    q["binary_terminal"], q["binary_terminal_error"] = result, failure
    status = (
        "source-mismatch"
        if not q["recorded_identity_verified"]
        else "unsupported-source"
        if result is None
        else "preflight-required"
        if q["captured_plain_ipv4"]
        else "transport-unavailable"
    )
    report["operations"].append(
        {
            "id": ROW,
            "operation": "Review an existing binary input terminal transfer",
            "status": status,
            "basis": (
                f"{result['object']}: UI IN{result['old_slot']} to captured unassigned "
                f"UI IN{result['destination_slot']}. Saved-effective state configuration and "
                "label encoding stay intact; counters remain historical captured values."
                if result
                else failure
            ),
            "next_step": (
                "Open Points & I/O, expand Move a configured binary input, capture the exact "
                "controller and review fresh settings and terminal availability. Confirm physical "
                "wiring, unchanged binary configuration and application transfer before Apply and "
                "readback. This analysis grants no plan or transfer authority."
            ),
        }
    )
    report["capability_profile"] = PROFILE
    return report
