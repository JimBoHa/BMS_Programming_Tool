"""Source-specific typed analog transfer witness without retained edits or field authority."""

from .moi_effective_wire import compiler_from_snapshot as qualified_saved_merge
from .moi_identity import sha
from .native_binary_terminal_capabilities import binary_terminal_capabilities
from .native_encoded_terminal_input import EncodedAnalogTerminalCompiler
from .native_inputs import NativeInputCompiler

PROFILE = "native-backup-operation-capabilities/18"
ROW = "encoded-analog-terminal-transfer"


def encoded_analog_witness(snapshot, files):
    qualified_saved_merge(snapshot, files)
    compiler = EncodedAnalogTerminalCompiler(NativeInputCompiler(files))
    source = compiler.source()
    slots = source["available_slots"]
    if not slots:
        raise ValueError("No recorded free universal destination is available.")
    failure = "No existing analog input passes this typed source profile."
    for selected in source["inputs"]:
        if selected["configuration_error"] is not None:
            failure = selected["configuration_error"][:512]
            continue
        try:
            output, compiled = compiler.compile(
                {
                    "action": "encoded-terminal",
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
                "configuration_storage": compiled["configuration_storage"],
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


def encoded_analog_capabilities(snapshot, files, application, *, capability_profile=PROFILE):
    if capability_profile != PROFILE:
        raise ValueError("Select the explicit typed analog terminal capability profile.")
    report = binary_terminal_capabilities(snapshot, files, application)
    result = failure = None
    try:
        result = encoded_analog_witness(snapshot, files)
    except (ValueError, StopIteration) as exc:
        failure = str(exc)[:512] or "No existing analog input passes this typed source profile."
    q = report["qualification"]
    q["encoded_analog_terminal"], q["encoded_analog_terminal_error"] = result, failure
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
            "operation": "Review a configured analog input terminal transfer",
            "status": status,
            "basis": (
                f"{result['object']}: UI IN{result['old_slot']} to captured unassigned "
                f"UI IN{result['destination_slot']}. Stored electrical configuration, scaling "
                "and label encoding stay intact; unstored output endpoints remain absent."
                if result
                else failure
            ),
            "next_step": (
                "Open Points & I/O, expand Move a configured analog input, capture the exact "
                "controller and review fresh settings and terminal availability. Confirm physical "
                "wiring, unchanged analog configuration and application transfer before Apply and "
                "readback. This analysis grants no plan or transfer authority."
            ),
        }
    )
    report["capability_profile"] = PROFILE
    return report
