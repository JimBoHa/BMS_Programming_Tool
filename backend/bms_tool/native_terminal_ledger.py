"""Recorded terminal movement only; never reopen a source or contact a controller."""

import copy
import math
import re
import struct

from .moi_identity import seal
from .moi_terminal_copies import OUTPUT_PROFILE
from .native_inputs import CONFIG, TERMINAL_PROFILE, InputEdit

SCOPE = (
    "Recorded analog terminal movement and preserved configuration only. No source/parent "
    "revalidation, controller query, current value, wiring/accuracy verification or transfer authority."
)
UNAVAILABLE = "Recorded terminal metadata is incomplete or inconsistent; inspect original evidence."


def terminal_reference(body):
    unavailable = {"native_terminal": {"state": "unavailable", "scope": UNAVAILABLE}}
    try:
        edit = InputEdit.model_validate(body.get("input_edit"))
        c = body.get("compilation")
        if (
            body.get("change_kind") != "input"
            or body.get("operation_profile") != TERMINAL_PROFILE
            or edit.action != "terminal"
            or type(c) is not dict
            or c.get("profile") != TERMINAL_PROFILE
            or type(c.get("input_edit")) is not dict
            or seal(c["input_edit"]) != seal(edit.model_dump())
            or c.get("object_id") != f"analog-input,{edit.object_instance}"
            or c.get("other_records_preserved") is not True
            or c.get("wires_changed") is not False
            or c.get("allocated_record_hex") is not None
            or "allocated_record_hex" not in c
        ):
            return unavailable
        p = c.get("terminal_compilation")
        if type(p) is not dict or p.get("profile") != OUTPUT_PROFILE:
            return unavailable
        ref = c.get("record_ref")
        if (
            type(ref) is not str
            or not 1 <= len(ref) <= 512
            or not re.fullmatch(rf"[^/\x00-\x1f]+/0_{edit.object_instance}", ref)
        ):
            return unavailable
        ref.encode("utf-8", "strict")
        if (
            p.get("ref") != ref
            or p.get("object") != c["object_id"]
            or p.get("destination_slot") != edit.slot
            or type(p.get("destination_slot")) is not int
            or type(p.get("old_slot")) is not int
            or not 1 <= p["old_slot"] <= 6
            or not 1 <= edit.slot <= 6
            or p["old_slot"] == edit.slot
            or p.get("old_device_type") != f"UI IN{p['old_slot']}"
            or p.get("new_device_type") != f"UI IN{edit.slot}"
            or p.get("changed") is not True
        ):
            return unavailable
        for key in (
            "source_sha256",
            "source_native_sha256",
            "record_sha256",
            "slot_property_sha256",
            "device_type_property_sha256",
            "output_sha256",
            "output_native_sha256",
            "compilation_sha256",
        ):
            if type(p.get(key)) is not str or not re.fullmatch(r"[a-f0-9]{64}", p[key]):
                return unavailable
        if (
            c.get("compiled_native_sha256") != p["output_native_sha256"]
            or type(c.get("parameter_merge")) is not dict
            or c["parameter_merge"].get("output_sha256") != p["source_sha256"]
            or c["parameter_merge"].get("native_output_sha256") != p["source_native_sha256"]
            or body.get("native_payload_sha256") != p["output_native_sha256"]
            or body.get("payload_sha256") != p["output_sha256"]
            or seal({k: v for k, v in p.items() if k != "compilation_sha256"})
            != p["compilation_sha256"]
        ):
            return unavailable
        if any(
            p.get(k) is not True
            for k in (
                "other_expanded_bytes_preserved",
                "native_structure_readback_verified",
                "identities_modes_graph_and_record_framing_preserved",
            )
        ) or any(
            p.get(k) is not False
            for k in (
                "saved_settings_merged",
                "controller_write",
                "field_transfer_enabled",
                "physical_terminal_or_wiring_verified",
            )
        ):
            return unavailable
        if (
            type(c.get("native_record_count")) is not int
            or not 2 <= c["native_record_count"] <= 20000
            or c.get("original_native_record_count") != c["native_record_count"]
            or type(c.get("original_native_record_count")) is not int
        ):
            return unavailable
        if seal(c.get("changes")) != seal(
            [
                {"property": 31, "before": p["old_device_type"], "after": p["new_device_type"]},
                {"property": 519, "before": p["old_slot"], "after": edit.slot},
            ]
        ):
            return unavailable
        payloads = p.get("payloads")
        if (
            type(payloads) is not list
            or len(payloads) != 2
            or any(type(x) is not dict or set(x) != {"offset", "before", "after"} for x in payloads)
        ):
            return unavailable
        slot, label = payloads
        if (
            any(
                type(x["offset"]) is not int or not 14 <= x["offset"] <= 8 * 1024 * 1024
                for x in payloads
            )
            or type(slot["before"]) is not str
            or not re.fullmatch(r"(?:[a-f0-9]{2}){1,4}", slot["before"])
            or int(slot["before"], 16) != p["old_slot"]
            or slot["after"] != edit.slot.to_bytes(len(slot["before"]) // 2, "big").hex()
            or label["before"] != (b"\0" + p["old_device_type"].encode("ascii")).hex()
            or label["after"] != (b"\0" + p["new_device_type"].encode("ascii")).hex()
        ):
            return unavailable
        if not (
            slot["offset"] + len(slot["before"]) // 2 <= label["offset"]
            or label["offset"] + len(label["before"]) // 2 <= slot["offset"]
        ):
            return unavailable
        stored = c.get("stored_configuration")
        if type(stored) is not dict or set(stored) != set(CONFIG.values()):
            return unavailable
        for key, value in stored.items():
            if key in {"setup", "field_units", "units"}:
                if type(value) is not int or not 0 <= value <= 65535:
                    return unavailable
            elif (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or struct.pack(">d", value)
                != struct.pack(">d", struct.unpack(">f", struct.pack(">f", value))[0])
            ):
                return unavailable
        return {
            "object": c["object_id"],
            "native_terminal": {
                "state": "recorded",
                "profile": TERMINAL_PROFILE,
                "action": "terminal",
                "object_id": c["object_id"],
                "record_ref": ref,
                "old_slot": p["old_slot"],
                "slot": edit.slot,
                "old_terminal_label": p["old_device_type"],
                "terminal_label": p["new_device_type"],
                "configuration_sha256": edit.configuration_sha256,
                "stored_configuration": copy.deepcopy(stored),
                "source_sha256": p["source_sha256"],
                "source_native_sha256": p["source_native_sha256"],
                "output_sha256": p["output_sha256"],
                "output_native_sha256": p["output_native_sha256"],
                "compilation_sha256": p["compilation_sha256"],
                "wiring_confirmation_recorded": body.get("physical_wiring_confirmed") is True,
                "scope": SCOPE,
            },
        }
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, struct.error):
        return unavailable
