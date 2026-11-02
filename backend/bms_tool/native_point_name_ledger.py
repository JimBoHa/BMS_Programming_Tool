"""Project recorded point-name bindings without opening sources or controllers."""

import re

from .native_point_names import PROFILE, PointNameEdit

SCOPE = (
    "Recorded point-name edit and compilation bindings only. No original-backup revalidation, "
    "current published name, controller query or transfer authority."
)
UNAVAILABLE = (
    "Recorded point-name metadata is incomplete or inconsistent; inspect original evidence."
)


def point_name_reference(body):
    unavailable = {"native_point_name": {"state": "unavailable", "scope": UNAVAILABLE}}
    try:
        if type(body) is not dict or body.get("operation_profile") != PROFILE:
            return unavailable
        raw = body.get("point_name_edit")
        edit = PointNameEdit.model_validate(raw)
        report = body.get("compilation")
        if (
            raw != edit.model_dump()
            or type(report) is not dict
            or report.get("profile") != PROFILE
            or report.get("other_merged_bytes_preserved") is not True
            or type(report.get("native_record_count")) is not int
            or not 1 <= report["native_record_count"] <= 100000
            or type(body.get("old_instance")) is not int
            or not 0 <= body["old_instance"] <= 4194302
            or type(body.get("new_instance")) is not int
            or body["new_instance"] != body["old_instance"]
        ):
            return unavailable
        selected = report.get("selected_edit")
        if (
            type(selected) is not dict
            or set(selected) != set(raw) | {"before", "after", "character_encoding", "changed"}
            or any(selected.get(k) != v for k, v in raw.items())
            or selected.get("after") != edit.new_name
            or type(selected.get("before")) is not str
            or selected["before"] == edit.new_name
            or len(selected["before"].encode("utf-8", "strict")) > 4096
            or type(selected.get("character_encoding")) is not int
            or selected["character_encoding"] not in (0, 3, 4, 5)
            or selected.get("changed") is not True
            or not re.fullmatch(r"[a-f0-9]{64}", body.get("native_payload_sha256", ""))
            or report.get("compiled_native_sha256") != body["native_payload_sha256"]
            or "/" not in edit.record_ref
            or any(ord(c) < 32 or ord(c) == 127 for c in edit.record_ref)
        ):
            return unavailable
        edit.record_ref.encode("utf-8", "strict")
        return {
            "object": edit.object_id,
            "native_point_name": {
                "state": "recorded",
                "profile": PROFILE,
                "object_id": edit.object_id,
                "record_ref": edit.record_ref,
                "before": selected["before"],
                "after": edit.new_name,
                "character_encoding": selected["character_encoding"],
                "before_record_sha256": edit.encoded_sha256,
                "compiled_native_sha256": report["compiled_native_sha256"],
                "name_confirmation_recorded": body.get("point_name_confirmed") is True,
                "scope": SCOPE,
            },
        }
    except (ValueError, TypeError, KeyError, AttributeError):
        return unavailable
