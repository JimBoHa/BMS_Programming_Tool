"""Bounded combined-edit receipt references, without original-file or field access."""

import math
import re
import struct

from .moi_default_wire import PROFILE as COMPILER_PROFILE
from .moi_signal_defaults import encoded_value
from .native_default_wire_transfer import PROFILE, validate_evidence

SCOPE = (
    "Recorded Real default and connection proposal only. Original source, current values "
    "and controller state are not revalidated. This reference grants no transfer authority."
)


def combined_reference(body):
    unavailable = {
        "native_default_wire": {
            "state": "unavailable",
            "scope": "Combined native metadata is incomplete or inconsistent; inspect original evidence.",
        }
    }
    try:
        if (
            type(body) is not dict
            or body.get("operation_profile") != PROFILE
            or body.get("change_kind") != "default-wire"
        ):
            return unavailable
        if any(
            key in body
            for key in (
                "default_edit",
                "wire_edit",
                "connection_edit",
                "input_edit",
                "recovery_origin",
                "allocation_origin",
            )
        ):
            return unavailable
        edit, guard = body.get("combined_edit"), body.get("combined_guard")
        options, checked = validate_evidence(edit, guard)
        if edit != options.model_dump() or guard != checked.model_dump():
            return unavailable
        c = body.get("compilation")
        if type(c) is not dict or c.get("profile") != COMPILER_PROFILE:
            return unavailable
        real, wire = c.get("selected_default"), c.get("selected_wire")
        if type(real) is not dict or type(wire) is not dict:
            return unavailable
        if (
            c.get("combined_guard") != guard
            or any(
                c.get(k) is not True
                for k in (
                    "other_merged_bytes_preserved",
                    "both_orders_identical",
                    "disjoint_fields",
                    "saved_settings_merged",
                )
            )
            or c.get("controller_write") is not False
            or c.get("field_transfer_enabled") is not False
            or any(
                body.get(k) is not True
                for k in (
                    "default_change_confirmed",
                    "wire_change_confirmed",
                    "application_transfer_confirmed",
                )
            )
            or any(
                not isinstance(body.get(k), str) or re.fullmatch(r"[a-f0-9]{64}", body[k]) is None
                for k in ("payload_sha256", "native_payload_sha256")
            )
            or c.get("compiled_sha256") != body["payload_sha256"]
            or c.get("compiled_native_sha256") != body["native_payload_sha256"]
            or type(body.get("old_instance")) is not int
            or not 0 <= body["old_instance"] <= 4194302
            or type(body.get("new_instance")) is not int
            or body.get("new_instance") != body["old_instance"]
            or body.get("old_name") != body.get("new_name")
            or real.get("record_ref") != options.record_ref
            or real.get("encoded_sha256") != options.encoded_sha256
            or real.get("value_text") != options.value_text
            or real.get("before_bits") != checked.prior_bits
            or real.get("after_bits") != encoded_value(options.value_text)[0].hex()
            or real.get("class_id") not in (526, 527)
            or real.get("profile") != "tagged-moi-signal-default-copy/1"
            or wire.get("profile") != "tagged-moi-wire-source-copy/1"
            or not math.isfinite(struct.unpack(">f", bytes.fromhex(checked.prior_bits))[0])
            or real.get("property") != 3113
            or wire.get("diagram_ref") != options.diagram_ref
            or wire.get("wire_index") != options.wire_index
            or wire.get("old") != options.old
            or wire.get("source_ref") != options.source_ref
        ):
            return unavailable
        new = wire.get("new")
        if (
            type(new) is not list
            or len(new) != 4
            or any(type(v) is not int or not 0 <= v <= 65535 for v in new)
            or new[1:] != options.old[1:]
        ):
            return unavailable
        for value in (
            options.record_ref,
            options.diagram_ref,
            options.source_ref,
            wire.get("old_source_ref"),
            wire.get("target_ref"),
        ):
            if (
                not isinstance(value, str)
                or not 1 <= len(value) <= 512
                or any(ord(c) < 32 or ord(c) == 127 for c in value)
            ):
                return unavailable
            value.encode("utf-8", "strict")
        return {
            "object": options.record_ref,
            "native_default_wire": {
                "state": "recorded",
                "profile": PROFILE,
                "record_ref": options.record_ref,
                "before_bits": real["before_bits"],
                "after_bits": real["after_bits"],
                "diagram_ref": options.diagram_ref,
                "wire_index": options.wire_index,
                "old": list(options.old),
                "new": list(new),
                "old_source_ref": wire["old_source_ref"],
                "source_ref": options.source_ref,
                "target_ref": wire["target_ref"],
                "compiled_native_sha256": body["native_payload_sha256"],
                "transfer_confirmation_recorded": True,
                "field_authority": False,
                "scope": SCOPE,
            },
        }
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return unavailable
