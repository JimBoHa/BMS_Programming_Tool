"""Read-only standard BACnet state-domain evidence, never portable enum binding."""

import json

from bacpypes3.basetypes import BinaryPV
from bacpypes3.primitivedata import ObjectIdentifier, Unsigned

from .bacnet_values import json_value

MAX_LABEL_BYTES = 256


def _label(value, row):
    if row["status"] != "ok" or not isinstance(value, str):
        return None, "unavailable"
    if len(json.dumps(str(value), ensure_ascii=True).encode()) > MAX_LABEL_BYTES:
        return None, "outside_metadata_label_profile"
    return str(value), "read"


def _value_check(kind, value, count=None):
    if isinstance(value, (BinaryPV, Unsigned)) and int(value) > 4294967295:
        return {
            "status": "outside_native_unsigned32_profile",
            "code": None,
            "native_code_evidence": json_value(value),
            "reason": "The native decoder accepted a value outside the standard unsigned32 code profile; no numeric code is substituted.",
        }
    if kind == "binary":
        if not isinstance(value, BinaryPV):
            return {"status": "unknown", "reason": "Native BinaryPV value was not decoded."}
        code = int(value)
        return {
            "status": "within_standard_domain" if code in (0, 1) else "outside_standard_domain",
            "code": code,
            "datatype": "BinaryPV",
            "allowed_codes": [0, 1],
        }
    if not isinstance(value, Unsigned):
        return {"status": "unknown", "reason": "Native Unsigned value was not decoded."}
    code = int(value)
    if count is None:
        return {
            "status": "unknown",
            "datatype": "Unsigned",
            "code": code,
            "reason": "Positive native Number_Of_States is unresolved.",
        }
    return {
        "status": "within_observed_numeric_range"
        if 1 <= code <= count
        else "outside_observed_numeric_range",
        "datatype": "Unsigned",
        "code": code,
        "minimum": 1,
        "maximum": count,
        "basis": "Sequential native count observation; not an atomic state guarantee.",
    }


async def inspect_native_domain(obj, properties, native_value, result, read, *, limit=32):
    kind = int(ObjectIdentifier(obj)[0])
    result.update(
        status="reading",
        read_in_progress=True,
        complete=False,
        states=[],
        findings=[],
        source="native-bacnet-readproperty",
        object=obj,
        meaning="Native BACnet datatype/labels only; no JCI Enum Set ID, portable enum binding or electrical polarity inference.",
    )
    binary = kind in (3, 4, 5)
    if not binary and kind not in (13, 14, 19):
        result.update(
            status="not_applicable",
            read_in_progress=False,
            complete=True,
            reason="Selected standard point is not BinaryPV or multistate.",
        )
        return
    result["datatype"] = "BinaryPV" if binary else "Unsigned"
    if binary:
        result.update(codes_complete=True, code_range={"minimum": 0, "maximum": 1})
        for code, prop in ((0, "inactive-text"), (1, "active-text")):
            value, row = await read(prop)
            properties[prop] = row
            label, state = _label(value, row)
            result["states"].append(
                {
                    "code": code,
                    "label": label,
                    "label_status": state,
                    "property": prop,
                    "array_index": None,
                }
            )
        if kind in (3, 4):
            value, row = await read("polarity")
            properties["polarity"] = row
            result["polarity"] = {
                "status": row["status"],
                "known": row["status"] == "ok" and int(value) in (0, 1),
                "meaning": "Retained native Polarity, never applied to BinaryPV codes or labels.",
            }
            polarity_known = row["status"] == "ok" and int(value) in (0, 1)
        else:
            result["polarity"] = {
                "status": "not_applicable",
                "meaning": "No Polarity property in the selected standard BinaryValue class.",
            }
            polarity_known = True
        result["value_validation"] = _value_check("binary", native_value)
        result["labels_complete"] = all(s["label_status"] == "read" for s in result["states"])
        result["complete"] = (
            result["labels_complete"]
            and polarity_known
            and result["value_validation"]["status"] == "within_standard_domain"
        )
    else:
        count, count_row = await read("number-of-states")
        properties["number-of-states"] = count_row
        native_count = (
            int(count)
            if count_row["status"] == "ok"
            and isinstance(count, Unsigned)
            and 1 <= count <= 4294967295
            else None
        )
        result["number_of_states"] = native_count
        result["codes_complete"] = native_count is not None
        result["code_range"] = {"minimum": 1, "maximum": native_count} if native_count else None
        if native_count is None:
            result["findings"].append({"code": "number_of_states_unresolved_or_outside_profile"})
        array = {
            "status": "reading",
            "read_in_progress": True,
            "complete": False,
            "count_read": None,
            "elements": [],
        }
        properties["state-text"] = array
        texts, text_row = await read("state-text", 0)
        array["count_read"] = text_row
        actual = (
            int(texts)
            if text_row["status"] == "ok"
            and isinstance(texts, Unsigned)
            and 0 <= texts <= 4294967295
            else None
        )
        result["observed_state_text_count"] = actual
        if actual is not None:
            for index in range(1, min(actual, limit) + 1):
                value, row = await read("state-text", index)
                array["elements"].append(row)
                label, state = _label(value, row)
                result["states"].append(
                    {
                        "code": index,
                        "label": label,
                        "label_status": state,
                        "property": "state-text",
                        "array_index": index,
                        "within_observed_number_of_states": None
                        if native_count is None
                        else index <= native_count,
                    }
                )
            array["complete"] = actual <= limit and all(
                r["status"] == "ok" for r in array["elements"]
            )
            array["status"] = (
                "ok" if array["complete"] else "limited" if actual > limit else "partial"
            )
            if actual > limit:
                result["findings"].append(
                    {
                        "code": "state_text_limited",
                        "observed_count": actual,
                        "retained_entries": len(array["elements"]),
                        "limit": limit,
                    }
                )
            if native_count is not None and actual != native_count:
                result["findings"].append(
                    {
                        "code": "state_text_count_mismatch",
                        "number_of_states": native_count,
                        "state_text_count": actual,
                    }
                )
        else:
            array["status"] = (
                text_row["status"] if text_row["status"] != "ok" else "outside_count_profile"
            )
            result["findings"].append({"code": "state_text_count_unresolved_or_outside_profile"})
        array["read_in_progress"] = False
        result["value_validation"] = _value_check("multistate", native_value, native_count)
        result["labels_complete"] = (
            array["complete"]
            and actual == native_count
            and all(s["label_status"] == "read" for s in result["states"])
        )
        result["complete"] = (
            result["labels_complete"]
            and result["value_validation"]["status"] == "within_observed_numeric_range"
        )
    labels = {}
    for state in result["states"]:
        label = state["label"]
        if label is not None:
            labels.setdefault(label, []).append(state["code"])
            if not label.strip():
                result["findings"].append({"code": "blank_native_label", "state": state["code"]})
    for codes in labels.values():
        if len(codes) > 1:
            result["findings"].append(
                {
                    "code": "duplicate_native_label",
                    "states": codes,
                    "meaning": "Codes remain distinct; no label-based mapping inferred.",
                }
            )
    result["status"] = (
        "complete"
        if result["complete"]
        else "invalid_value"
        if result["value_validation"]["status"].startswith("outside_")
        else "partial"
    )
    result["read_in_progress"] = False
