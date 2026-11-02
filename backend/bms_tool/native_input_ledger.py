"""Recorded input bindings only; never reopen backups, parents or a controller."""

import copy
import math
import re
import struct

from .native_inputs import CONFIG, MODES, PROFILE, InputEdit

SCOPE = (
    "Recorded input edit and compilation bindings only. No backup/parent revalidation, "
    "controller query, live value, wiring/accuracy verification or transfer authority."
)
UNAVAILABLE = "Recorded input metadata is incomplete or inconsistent; inspect original evidence."


def input_reference(body):
    unavailable = {"native_input": {"state": "unavailable", "scope": UNAVAILABLE}}
    if body.get("operation_profile") != PROFILE:
        return unavailable
    try:
        edit = InputEdit.model_validate(body.get("input_edit"))
        compilation = body.get("compilation")
        if (
            type(compilation) is not dict
            or compilation.get("profile") != PROFILE
            or compilation.get("input_edit") != edit.model_dump()
            or compilation.get("object_id") != f"analog-input,{edit.object_instance}"
            or compilation.get("other_records_preserved") is not True
            or compilation.get("wires_changed") is not False
            or not re.fullmatch(r"[a-f0-9]{64}", body.get("native_payload_sha256", ""))
            or compilation.get("compiled_native_sha256") != body["native_payload_sha256"]
        ):
            return unavailable
        reference = compilation.get("record_ref")
        if isinstance(reference, str):
            reference.encode("utf-8", "strict")
        if (
            type(reference) is not str
            or not 1 <= len(reference) <= 512
            or "/" not in reference
            or any(ord(c) < 32 for c in reference)
        ):
            return unavailable
        stored = compilation.get("stored_configuration")
        if edit.configuration is None:
            origin = body.get("allocation_origin")
            original = InputEdit.model_validate(origin.get("input_edit"))
            if (
                stored is not None
                or origin.get("profile") != PROFILE
                or original.action != "allocate"
                or original.slot != edit.slot
                or original.object_instance != edit.object_instance
                or origin.get("object_id") != compilation["object_id"]
                or origin.get("record_ref") != reference
                or edit.allocation_receipt == body.get("id")
            ):
                return unavailable
        else:
            if type(stored) is not dict or set(stored) != set(CONFIG.values()):
                return unavailable
            requested = edit.configuration
            expected_enums = {
                "setup": MODES[requested.mode]["setup"],
                "field_units": MODES[requested.mode]["field_units"],
                "units": requested.units,
            }
            for name, expected in expected_enums.items():
                if type(stored[name]) is not int or stored[name] != expected:
                    return unavailable
            for name in set(stored) - set(expected_enums):
                value = stored[name]
                if (
                    type(value) not in (int, float)
                    or not math.isfinite(value)
                    or struct.pack(">d", value)
                    != struct.pack(
                        ">d", struct.unpack(">f", struct.pack(">f", getattr(requested, name)))[0]
                    )
                ):
                    return unavailable
        return {
            "object": compilation["object_id"],
            "native_input": {
                "state": "recorded",
                "profile": PROFILE,
                "action": edit.action,
                "object_id": compilation["object_id"],
                "record_ref": reference,
                "slot": edit.slot,
                "terminal_label": f"UI IN{edit.slot}",
                "requested_name": edit.name,
                "requested_configuration": edit.configuration.model_dump()
                if edit.configuration
                else None,
                "stored_configuration": copy.deepcopy(stored),
                "allocation_receipt_id": edit.allocation_receipt,
                "wiring_confirmation_recorded": body.get("physical_wiring_confirmed") is True,
                "scope": SCOPE,
            },
        }
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, struct.error):
        return unavailable
