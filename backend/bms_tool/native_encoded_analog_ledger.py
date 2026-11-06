"""Closed historical analog movement metadata; no source, compiler or controller access."""

import copy
import re

from .moi_identity import seal
from .native_encoded_terminal_input import PROFILE as TRANSFER_PROFILE
from .native_encoded_terminal_input import validate_evidence
from .native_inputs import InputEdit

PROFILE = "native-recorded-encoded-analog-terminal/1"
SCOPE = (
    "Recorded analog terminal movement and unchanged typed configuration/field presence "
    "only. No source/parent revalidation, current value, controller query, physical wiring or "
    "new transfer authority."
)
UNAVAILABLE = "Recorded analog terminal metadata unavailable; inspect original evidence."


def explicit_encoded_analog(body):
    edit, compiled = body.get("input_edit"), body.get("compilation")
    return (
        isinstance(edit, dict)
        and edit.get("action") == "encoded-terminal"
        or body.get("operation_profile") == TRANSFER_PROFILE
        and isinstance(compiled, dict)
        and compiled.get("profile") == TRANSFER_PROFILE
    )


def encoded_analog_terminal_reference(body):
    unavailable = {"native_encoded_analog_terminal": {"state": "unavailable", "scope": UNAVAILABLE}}
    try:
        if body.get("change_kind") != "input" or body.get("operation_profile") != TRANSFER_PROFILE:
            return unavailable
        validate_evidence(body)
        edit = InputEdit.model_validate(body["input_edit"])
        c, identity = body["compilation"], body.get("identity")
        p, config = c["terminal_compilation"], c.get("stored_configuration")
        if (
            type(identity) is not dict
            or identity.get("vendor-identifier") != 5
            or type(identity.get("device")) is not str
            or not re.fullmatch(r"device,(0|[1-9][0-9]*)", identity["device"])
            or type(body.get("old_instance")) is not int
            or not 0 <= body["old_instance"] <= 4194302
            or type(body.get("new_instance")) is not int
            or body["new_instance"] != body["old_instance"]
            or identity["device"] != f"device,{body['old_instance']}"
            or type(identity.get("object-name")) is not str
            or body.get("old_name") != identity["object-name"]
            or body.get("new_name") != body["old_name"]
            or any(
                body.get(k) is not True
                for k in (
                    "physical_wiring_confirmed",
                    "input_change_confirmed",
                    "application_transfer_confirmed",
                )
            )
            or type(c.get("record_ref")) is not str
            or not re.fullmatch(rf"[^/\x00-\x1f]+/0_{edit.object_instance}", c["record_ref"])
            or len(c["record_ref"]) > 512
            or not 1 <= p["old_slot"] <= 6
            or not 1 <= edit.slot <= 6
            or p.get("old_device_type") != f"UI IN{p['old_slot']}"
            or p.get("new_device_type") != f"UI IN{edit.slot}"
            or type(c.get("native_record_count")) is not int
            or not 2 <= c["native_record_count"] <= 20000
            or type(c.get("original_native_record_count")) is not int
            or c["original_native_record_count"] != c["native_record_count"]
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
            type(c.get("parameter_merge")) is not dict
            or c["parameter_merge"].get("output_sha256") != p["source_sha256"]
            or c["parameter_merge"].get("native_output_sha256") != p["source_native_sha256"]
            or body.get("native_payload_sha256") != p["output_native_sha256"]
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
        if any(
            type(x["offset"]) is not int or not 14 <= x["offset"] <= 8 * 1024 * 1024
            for x in payloads
        ):
            return unavailable
        if type(slot["before"]) is not str or not re.fullmatch(
            r"(?:[a-f0-9]{2}){1,4}", slot["before"]
        ):
            return unavailable
        width = len(slot["before"]) // 2
        if (
            int(slot["before"], 16) != p["old_slot"]
            or slot["after"] != edit.slot.to_bytes(width, "big").hex()
        ):
            return unavailable
        encoding = p["device_type_character_encoding"]

        def encoded(text):
            return (
                bytes([encoding]) + text.encode("ascii" if encoding == 0 else "utf-16-be")
            ).hex()

        if label["before"] != encoded(p["old_device_type"]) or label["after"] != encoded(
            p["new_device_type"]
        ):
            return unavailable
        if not (
            slot["offset"] + width <= label["offset"]
            or label["offset"] + len(label["before"]) // 2 <= slot["offset"]
        ):
            return unavailable
        return {
            "object": c["object_id"],
            "native_encoded_analog_terminal": {
                "state": "recorded",
                "profile": PROFILE,
                "operation_profile": TRANSFER_PROFILE,
                "action": "encoded-terminal",
                "object_id": c["object_id"],
                "record_ref": c["record_ref"],
                "old_slot": p["old_slot"],
                "slot": edit.slot,
                "old_terminal_label": p["old_device_type"],
                "terminal_label": p["new_device_type"],
                "configuration_sha256": edit.configuration_sha256,
                "stored_configuration": copy.deepcopy(config),
                "configuration_storage": copy.deepcopy(c["configuration_storage"]),
                "device_type_character_encoding": encoding,
                **{
                    k: p[k]
                    for k in (
                        "source_sha256",
                        "source_native_sha256",
                        "output_sha256",
                        "output_native_sha256",
                        "compilation_sha256",
                    )
                },
                "confirmations_recorded": True,
                "transfer_authority": False,
                "scope": SCOPE,
            },
        }
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, UnicodeError):
        return unavailable
