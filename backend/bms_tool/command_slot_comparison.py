"""Compare two retained, independently identified BACnet priority arrays."""

import json
from datetime import datetime

from pydantic import Field

from .models import StrictModel


class CommandSlotComparison(StrictModel):
    baseline_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    current_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    object_id: str = Field(min_length=1, max_length=80)


def _slots(report, object_id):
    item = next((r for r in report["objects"] if r["object"] == object_id), None)
    if not report["identity_verified"] or not item or not item["identity_verified"]:
        raise ValueError("Both reports must verify the same Device and point identifier.")
    props = item["properties"]
    name = props.get("object-name", {})
    if name.get("status") != "ok" or not isinstance(name.get("value"), str) or not name["value"]:
        raise ValueError("Both reports must include a readable point name.")
    array = props.get("priority-array", {})
    count = array.get("count_read", {})
    if not (
        array.get("complete") is True
        and array.get("status") == "ok"
        and count.get("status") == "ok"
        and count.get("value") == 16
        and count.get("object") == object_id
        and count.get("array_index") == 0
        and len(array.get("elements", [])) == 16
    ):
        raise ValueError(
            "Each report needs all 16 command slots. Include commandable properties when inspecting the point."
        )
    for number, slot in enumerate(array["elements"], 1):
        if not (
            slot.get("status") == "ok"
            and slot.get("object") == object_id
            and slot.get("property") == "priority-array"
            and slot.get("array_index") == number
            and slot.get("encoded_value", {}).get("complete") is True
            and bool(slot["encoded_value"].get("hex"))
            and isinstance(slot.get("value"), dict)
            and "type" in slot["value"]
            and "value" in slot["value"]
        ):
            raise ValueError(
                f"Command slot {number} lacks complete, individually identified native evidence."
            )
    return name["value"], array["elements"]


def _display(value):
    if value["type"] == "null":
        return "Empty"
    return (
        value["type"]
        + " "
        + json.dumps(value["value"], sort_keys=True, ensure_ascii=False, allow_nan=False)
    )


def compare_command_slots(baseline, current, object_id):
    if baseline["id"] == current["id"] or datetime.fromisoformat(
        baseline["finished_at"]
    ) > datetime.fromisoformat(current["started_at"]):
        raise ValueError("Choose an earlier, completed baseline and a separate later reading.")
    if (
        baseline["target"] != current["target"]
        or baseline["connector_config"] != current["connector_config"]
    ):
        raise ValueError("The Device, address, route and interface must match in both reports.")
    previous_name, previous = _slots(baseline, object_id)
    name, following = _slots(current, object_id)
    if previous_name != name:
        raise ValueError(
            "The point name changed between reports. Verify its identity before comparing slots."
        )
    changes = []
    for priority, (left, right) in enumerate(zip(previous, following, strict=True), 1):
        if left["encoded_value"]["hex"] == right["encoded_value"]["hex"]:
            continue
        old, new = left["value"], right["value"]
        before, after = _display(old), _display(new)
        if before == after:
            change = "Encoding changed"
        elif old["type"] == "null":
            change = "Filled"
        elif new["type"] == "null":
            change = "Cleared"
        else:
            change = "Changed"
        changes.append({"priority": priority, "change": change, "before": before, "after": after})
    return {
        "baseline_id": baseline["id"],
        "current_id": current["id"],
        "target": current["target"],
        "object": object_id,
        "name": name,
        "baseline_finished_at": baseline["finished_at"],
        "current_finished_at": current["finished_at"],
        "slots_compared": 16,
        "changes": changes,
    }
