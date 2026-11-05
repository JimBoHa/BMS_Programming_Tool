"""Explicit encoding-preserving local witnesses appended to unchanged profile 15."""

from .moi_terminal_labels import EncodedEffectiveTerminalCopies, EncodedTerminalCopies
from .native_terminal_capabilities import terminal_capabilities, witness

PROFILE = "native-backup-operation-capabilities/16"
ROWS = ("encoded-local-terminal-copy", "encoded-effective-local-terminal-copy")


def encoded_witness(compiler):
    result = witness(compiler)
    selected = next(p for p in compiler.inspect()["inputs"] if p["ref"] == result["ref"])
    return {
        **result,
        "device_type_character_encoding": selected["device_type_character_encoding"],
        "device_type_encoding_preserved": True,
    }


def terminal_label_capabilities(snapshot, files, application, *, capability_profile=PROFILE):
    if capability_profile != PROFILE:
        raise ValueError("Select the explicit encoded terminal capability profile.")
    report = terminal_capabilities(snapshot, files, application)
    for basis, operation, title in zip(
        ("archive", "effective"),
        ROWS,
        (
            "Save a local terminal archive copy",
            "Compile a saved-effective terminal copy",
        ),
        strict=True,
    ):
        result = failure = None
        try:
            if basis == "archive":
                compiler = EncodedTerminalCopies(files[3])
            else:
                compiler_merge = EncodedEffectiveTerminalCopies(snapshot, files)
                compiler = compiler_merge.effective
            result = encoded_witness(compiler)
            if basis == "effective":
                # Preserve the exact qualified merge evidence, not a second merge.
                result.update(saved_settings_merged=True, parameter_merge=compiler_merge.parameters)
        except (ValueError, StopIteration) as exc:
            failure = str(exc)[:512] or "No recorded input passes this encoded terminal profile."
        key = "encoded_" + basis + "_terminal"
        report["qualification"][key] = result
        report["qualification"][key + "_error"] = failure
        report["operations"].append(
            {
                "id": operation,
                "operation": title,
                "status": "source-qualified" if result else "unsupported-source",
                "basis": (
                    f"{result['object']}: UI IN{result['old_slot']} to captured unassigned "
                    f"UI IN{result['destination_slot']}. Recorded labels and other settings "
                    "stay intact in a separate local copy."
                    if result
                    else failure
                ),
                "next_step": (
                    "Open Points & I/O, expand Reassign an existing local terminal, choose "
                    + ("Original archive" if basis == "archive" else "Saved-effective")
                    + " and review a separate local native file. Captured availability still "
                    "requires physical wiring and suitability checks; this analysis grants no "
                    "field plan or transfer authority."
                ),
            }
        )
    report["capability_profile"] = PROFILE
    return report
