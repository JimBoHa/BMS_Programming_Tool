"""Explicit retained-source terminal witnesses; no field plan or retained edit."""

import math

from .moi_effective_terminals import EffectiveTerminalCopies
from .moi_effective_wire import compiler_from_snapshot as qualified_saved_merge
from .moi_identity import sha
from .moi_terminal_copies import MoiTerminalCopies
from .native_inputs import CONFIG, NativeInputCompiler
from .native_removal_capabilities import removal_capabilities

PROFILE = "native-backup-operation-capabilities/15"
ROWS = (
    "local-terminal-copy",
    "effective-local-terminal-copy",
    "analog-terminal-transfer",
)


def witness(compiler):
    inventory = compiler.inspect()
    slots = inventory["unassigned_slots"]
    selected = next((p for p in inventory["inputs"] if p["movable"]), None)
    if not slots or selected is None:
        raise ValueError("No movable recorded input and free local universal destination coexist.")
    proposal = {
        "source_sha256": inventory["source_sha256"],
        **{
            key: selected[key]
            for key in (
                "ref",
                "record_sha256",
                "slot_property_sha256",
                "device_type_property_sha256",
            )
        },
        "old_slot": selected["slot"],
        "destination_slot": slots[0],
    }
    output, proof = compiler.compile(**proposal)
    return {
        **proposal,
        "object": selected["object"],
        "class_id": selected["class_id"],
        "compiler_profile": compiler.profile,
        "output_sha256": sha(output),
        "compilation_sha256": proof["compilation_sha256"],
        "free_slots": slots,
        "saved_settings_merged": False,
        "field_transfer_enabled": False,
        "physical_terminal_or_wiring_verified": False,
    }


def terminal_capabilities(snapshot, files, application, *, capability_profile=PROFILE):
    if capability_profile != PROFILE:
        raise ValueError("Select the explicit native terminal capability profile.")
    # Keep every prior row and qualification byte-for-byte in the older profile.
    report = removal_capabilities(snapshot, files, application)
    evidence = {}
    for basis in ("archive", "effective", "analog"):
        result = error = None
        try:
            if basis == "archive":
                result = witness(MoiTerminalCopies(files[3]))
            elif basis == "effective":
                compiler = EffectiveTerminalCopies(snapshot, files)
                result = witness(compiler.effective)
                result.update(saved_settings_merged=True, parameter_merge=compiler.parameters)
            else:
                merged = qualified_saved_merge(snapshot, files)
                compiler = NativeInputCompiler(files)
                copier = MoiTerminalCopies(compiler.app.source, output_namespace=True)
                inventory = copier.inspect()
                slots = inventory["unassigned_slots"]
                if not slots:
                    raise ValueError("No recorded free universal destination is available.")
                points = {p["object_id"]: p for p in compiler.source()["inputs"]}
                failure = "No existing analog input passes this source profile."
                for candidate in inventory["inputs"]:
                    if not candidate["movable"] or candidate["class_id"] != 240:
                        continue
                    try:
                        point = points[candidate["object"]]
                        config = point["configuration"]
                        if any(
                            type(config[k]) not in (int, float) or not math.isfinite(config[k])
                            for k in CONFIG.values()
                        ):
                            raise ValueError(
                                "The recorded analog configuration is incomplete or nonnumeric."
                            )
                        edit = {
                            "action": "terminal",
                            "object_instance": int(candidate["object"].split(",")[1]),
                            "slot": slots[0],
                            "configuration_sha256": point["configuration_sha256"],
                        }
                        output, compiled = compiler.compile(edit)
                        result = {
                            "source_sha256": sha(files[3]),
                            "effective_sha256": copier.editor.source_sha256,
                            "parameter_merge": merged.parameters,
                            "object": candidate["object"],
                            "ref": candidate["ref"],
                            "old_slot": candidate["slot"],
                            "destination_slot": slots[0],
                            "configuration_sha256": point["configuration_sha256"],
                            "operation_profile": compiled["profile"],
                            "compiler_profile": compiled["terminal_compilation"]["profile"],
                            "output_sha256": sha(output),
                            "compilation_sha256": compiled["terminal_compilation"][
                                "compilation_sha256"
                            ],
                            "free_slots": slots,
                            "saved_settings_merged": True,
                            "field_transfer_enabled": False,
                            "physical_terminal_or_wiring_verified": False,
                        }
                        break
                    except ValueError as exc:
                        failure = str(exc)[:512]
                if result is None:
                    raise ValueError(failure)
        except (ValueError, StopIteration) as exc:
            error = str(exc)[:512] or "No selected input passes this source profile."
        evidence[basis] = result
        report["qualification"][basis + "_terminal"] = result
        report["qualification"][basis + "_terminal_error"] = error
    rows = []
    for basis, key, title in zip(
        ("archive", "effective", "analog"),
        ROWS,
        (
            "Save a local universal-terminal archive copy",
            "Compile a saved-effective universal-terminal copy",
            "Review an existing analog input terminal transfer",
        ),
        strict=True,
    ):
        q = report["qualification"]
        status = "source-qualified" if evidence[basis] else "unsupported-source"
        if basis == "analog":
            status = (
                "source-mismatch"
                if not q["recorded_identity_verified"]
                else "unsupported-source"
                if not evidence[basis]
                else "preflight-required"
                if q["captured_plain_ipv4"]
                else "transport-unavailable"
            )
        rows.append(
            {
                "id": key,
                "operation": title,
                "status": status,
                "basis": (
                    f"{evidence[basis]['object']}: UI IN{evidence[basis]['old_slot']} to "
                    f"captured unassigned UI IN{evidence[basis]['destination_slot']}. "
                    + {
                        "archive": "The original archive supports a separate local terminal copy.",
                        "effective": "The retained saved settings support a separate effective terminal copy.",
                        "analog": "The saved-effective analog binding supports a new controller review when identity and transport requirements are met.",
                    }[basis]
                    if evidence[basis]
                    else q[basis + "_terminal_error"]
                ),
                "next_step": (
                    "Open Points & I/O and choose Move a configured analog input. Capture the exact "
                    "controller, review fresh settings and terminal availability, confirm wiring, "
                    "unchanged mode/scaling and application transfer, then Apply and read back. "
                    "This analysis grants no plan or transfer authority."
                    if basis == "analog"
                    else "Open Points & I/O, expand Reassign an existing local terminal, choose "
                    + ("Original archive" if basis == "archive" else "Saved-effective")
                    + " and review a separate local file copy. The captured free terminal still "
                    "requires physical wiring and suitability checks."
                ),
            }
        )
    report["capability_profile"] = PROFILE
    report["operations"].extend(rows)
    return report
