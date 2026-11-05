"""Recorded matching-connection metadata; no source or controller operations."""

import re

from .moi_connection_copies import PROFILE as EDIT_PROFILE
from .moi_effective_connection import PROFILE as COMPILER_PROFILE
from .moi_identity import seal
from .native_connection_compiler import EffectiveConnectionPreview
from .native_connection_transfer import PROFILE, validate_connection_evidence

SCOPE = (
    "Recorded connection proposal and compilation bindings only. No original-backup "
    "revalidation, current graph reading, controller query or transfer authority."
)


def connection_reference(body):
    unavailable = {
        "native_connection": {
            "state": "unavailable",
            "scope": "Recorded connection metadata is incomplete or inconsistent; inspect original evidence.",
        }
    }
    try:
        if type(body) is not dict or body.get("operation_profile") != PROFILE:
            return unavailable
        edit, guard = body.get("connection_edit"), body.get("connection_guard")
        validate_connection_evidence(edit, guard)
        options = EffectiveConnectionPreview.model_validate(edit)
        report = body.get("compilation")
        if (
            edit != options.model_dump()
            or type(report) is not dict
            or report.get("profile") != COMPILER_PROFILE
            or report.get("connection_guard") != guard
            or report.get("other_merged_bytes_preserved") is not True
            or report.get("saved_settings_merged") is not True
            or report.get("archive_sha256") != edit["source_sha256"]
            or not isinstance(body.get("native_payload_sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", body["native_payload_sha256"]) is None
            or not isinstance(body.get("payload_sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", body["payload_sha256"]) is None
            or type(report.get("native_record_count")) is not int
            or not 1 <= report["native_record_count"] <= 100000
            or report.get("compiled_native_sha256") != body.get("native_payload_sha256")
            or report.get("compiled_sha256") != body.get("payload_sha256")
            or type(body.get("old_instance")) is not int
            or not 0 <= body["old_instance"] <= 4194302
            or type(body.get("new_instance")) is not int
            or body["new_instance"] != body["old_instance"]
            or report.get("compilation_sha256")
            != seal(
                {
                    key: value
                    for key, value in report.items()
                    if key
                    not in (
                        "compilation_sha256",
                        "connection_guard",
                        "parameter_transfer_qualification",
                        "connection_compilation_sha256",
                    )
                }
            )
            or report.get("connection_compilation_sha256")
            != seal(
                {
                    key: value
                    for key, value in report.items()
                    if key != "connection_compilation_sha256"
                }
            )
        ):
            return unavailable
        selected = report.get("connection_edit")
        if type(selected) is not dict or selected.get("profile") != EDIT_PROFILE:
            return unavailable
        for key in ("diagram_ref", "prototype_index", "prototype_old", "source_ref", "target_ref"):
            if selected.get(key) != edit[key]:
                return unavailable
        new = selected.get("new")
        if (
            type(new) is not list
            or len(new) != 4
            or any(type(v) is not int or not 0 <= v <= 65535 for v in new)
            or new[1::2] != edit["prototype_old"][1::2]
            or selected.get("connection_count_before") != edit["connection_count"]
            or type(selected.get("connection_count_before")) is not int
            or selected.get("connection_count_after") != edit["connection_count"] + 1
            or type(selected.get("connection_count_after")) is not int
            or selected.get("output_native_sha256") != body["native_payload_sha256"]
            or selected.get("native_structure_readback_verified") is not True
            or selected.get("other_expanded_bytes_preserved") is not True
        ):
            return unavailable
        for ref in (edit["diagram_ref"], edit["source_ref"], edit["target_ref"]):
            ref.encode("utf-8", "strict")
            if any(ord(c) < 32 or ord(c) == 127 for c in ref):
                return unavailable
        return {
            "object": edit["diagram_ref"],
            "native_connection": {
                "state": "recorded",
                "profile": PROFILE,
                "diagram_ref": edit["diagram_ref"],
                "prototype_index": edit["prototype_index"],
                "prototype_old": list(edit["prototype_old"]),
                "index": edit["connection_count"],
                "new": list(new),
                "source_ref": edit["source_ref"],
                "target_ref": edit["target_ref"],
                "connection_count_before": edit["connection_count"],
                "connection_count_after": edit["connection_count"] + 1,
                "compiled_native_sha256": report["compiled_native_sha256"],
                "connection_confirmation_recorded": body.get("connection_change_confirmed") is True,
                "scope": SCOPE,
            },
        }
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return unavailable
