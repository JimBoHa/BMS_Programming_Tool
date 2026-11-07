"""Bounded recorded batch proposals; no source reads or controller authority."""

import copy
import math
import re
import struct

from .moi_signal_defaults import encoded_value
from .native_default_batch_transfer import PROFILE, validate_batch_evidence

SCOPE = (
    "Recorded typed default proposal only. Original source, current values and controller "
    "state are not revalidated. This reference grants no transfer authority."
)


def batch_reference(body):
    unavailable = {
        "native_default_batch": {
            "state": "unavailable",
            "scope": "Batch metadata is incomplete or inconsistent; inspect original evidence.",
        }
    }
    try:
        if (
            type(body) is not dict
            or body.get("change_kind") != "default-batch"
            or body.get("operation_profile") != PROFILE
        ):
            return unavailable
        if any(
            k in body
            for k in (
                "default_edit",
                "wire_edit",
                "combined_edit",
                "connection_edit",
                "input_edit",
                "recovery_origin",
                "allocation_origin",
            )
        ):
            if body.get("recovery_profile") == "native-default-batch-recovery-transfer/1":
                unavailable["native_default_batch"]["scope"] = (
                    "This ordinary-batch view does not project previous-value recovery lineage. "
                    "Inspect the original recovery receipt in History."
                )
            return unavailable
        edit, guard = validate_batch_evidence(body.get("batch_edit"), body.get("batch_guard"))
        if body["batch_edit"] != edit.model_dump() or body["batch_guard"] != guard.model_dump():
            return unavailable
        c = body["compilation"]
        if (
            type(c) is not dict
            or c.get("profile") != "native-effective-default-batch-compiler/1"
            or c.get("batch_guard") != guard.model_dump()
            or type(c.get("edit_count")) is not int
            or c.get("edit_count") != len(edit.changes)
            or type(c.get("changed_count")) is not int
            or not 1 <= c["changed_count"] <= 16
            or any(
                c.get(k) is not True
                for k in (
                    "both_orders_identical",
                    "other_merged_bytes_preserved",
                    "saved_settings_merged",
                )
            )
            or any(
                c.get(k) is not False
                for k in (
                    "controller_queries",
                    "controller_write",
                    "field_transfer_enabled",
                    "enum_semantics_verified",
                )
            )
            or body.get("defaults_change_confirmed") is not True
            or body.get("application_transfer_confirmed") is not True
            or type(body.get("old_instance")) is not int
            or not 0 <= body["old_instance"] <= 4194302
            or type(body.get("new_instance")) is not int
            or body["new_instance"] != body["old_instance"]
            or body.get("new_name") != body.get("old_name")
        ):
            return unavailable
        for key, compiled in (
            ("payload_sha256", "compiled_sha256"),
            ("native_payload_sha256", "compiled_native_sha256"),
        ):
            if (
                not isinstance(body.get(key), str)
                or not re.fullmatch(r"[a-f0-9]{64}", body[key])
                or c.get(compiled) != body[key]
            ):
                return unavailable
        rows = c.get("selected")
        if type(rows) is not list or len(rows) != len(edit.changes):
            return unavailable
        recorded = []
        for change, field, selected in zip(edit.changes, guard.fields, rows, strict=True):
            ref = change.record_ref
            if any(ord(ch) < 32 or ord(ch) == 127 for ch in ref):
                return unavailable
            ref.encode("utf-8", "strict")
            if type(selected) is not dict or any(
                selected.get(k) != getattr(field, k)
                for k in ("kind", "record_ref", "class_id", "property", "encoded_sha256")
            ):
                return unavailable
            before, after = selected["before_encoding_hex"], selected["after_encoding_hex"]
            if change.kind == "real":
                expected = "44" + encoded_value(change.value_text)[0].hex() + "2f"
                if (
                    not math.isfinite(struct.unpack(">f", bytes.fromhex(field.prior_bits))[0])
                    or before != "44" + field.prior_bits + "2f"
                    or after != expected
                ):
                    return unavailable
            elif change.kind == "boolean":
                if before != ("112f" if field.prior_value else "102f") or after != (
                    "112f" if change.value else "102f"
                ):
                    return unavailable
            else:
                for text, value in ((before, field.prior_value), (after, change.value)):
                    if (
                        not isinstance(text, str)
                        or not re.fullmatch(r"9[1-4](?:[a-f0-9]{2}){1,4}2f", text)
                        or len(text) != (int(text[1]) + 2) * 2
                        or int(text[2:-2], 16) != value
                    ):
                        return unavailable
            if selected.get("changed") is not (before != after):
                return unavailable
            recorded.append(
                {
                    "kind": change.kind,
                    "record_ref": ref,
                    "class_id": field.class_id,
                    "before_encoding_hex": before,
                    "after_encoding_hex": after,
                }
            )
        if c["changed_count"] != sum(row["changed"] for row in rows):
            return unavailable
        return {
            "object": f"{len(recorded)} typed defaults",
            "native_default_batch": {
                "state": "recorded",
                "profile": PROFILE,
                "selected": copy.deepcopy(recorded),
                "compiled_native_sha256": body["native_payload_sha256"],
                "transfer_confirmation_recorded": True,
                "field_authority": False,
                "scope": SCOPE,
            },
        }
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return unavailable
