"""Verify native application and saved settings across a reviewed identity edit.

The evidence is byte based and uses each capture's class metadata. Controller
models, program types, parameter names and expansion counts never select a
replacement application or a parameter inventory.
"""

import json
import math
from functools import lru_cache
from pathlib import Path

from .moi_identity import MoiIdentity, sha
from .moi_parameters import ParameterApplication


@lru_cache(maxsize=1)
def _property_names():
    directory = Path(__file__).with_name("data")
    return (
        json.loads((directory / "metasysAttributeNamesByClass.json").read_text()),
        json.loads((directory / "metasysAttributeNames.json").read_text()),
    )


def _records(editor):
    return {
        int.from_bytes(editor.data[row["offset"] + 6 : row["offset"] + 10], "big"): row
        for row in editor.records
    }


def _value(editor, record, property_id):
    prop = record["properties"][property_id]
    return editor.data[prop["value_start_offset"] : prop["value_end_offset"]]


def verify_preservation(before, after, *, old_instance, new_instance, old_name=None, new_name=None):
    """Return evidence or fail closed on a changed program or saved setting.

    Inputs are the actual pre-transfer and verified-readback File 3/11/12 bytes.
    A parameter directory may shrink after values become application defaults;
    its byte equality or selector count is not treated as settings equality.
    """
    if set(before) != {3, 11, 12} or set(after) != {3, 11, 12}:
        raise ValueError("Preservation verification requires both complete native snapshots.")
    parameters = ParameterApplication(before[3], before[11], before[12])
    merged, _ = parameters.compile()
    saved, observed = MoiIdentity(merged), MoiIdentity(after[3])
    if saved.instance != old_instance or observed.instance != new_instance:
        raise ValueError("Preservation snapshot identities differ from the reviewed edit.")
    renaming = new_name is not None or old_name is not None
    if renaming:
        if (
            old_instance != new_instance
            or saved.summary()["name"] != old_name
            or observed.summary()["name"] != new_name
        ):
            raise ValueError(
                "Name-only preservation requires the reviewed names and unchanged instance."
            )
        if saved.data[:14] != observed.data[:14] or len(saved.records) != len(observed.records):
            raise ValueError("Application framing or record membership changed during rename.")
        for source, actual in zip(saved.records, observed.records, strict=True):
            left = saved.data[source["offset"] : source["end_offset"]]
            right = observed.data[actual["offset"] : actual["end_offset"]]
            if source is saved.root:
                if actual is not observed.root:
                    raise ValueError("Root Device record moved during rename.")
                a, b = source["properties"][2390], actual["properties"][2390]
                first = a["value_start_offset"] - source["offset"]
                last = a["value_end_offset"] - source["offset"]
                other_first = b["value_start_offset"] - actual["offset"]
                other_last = b["value_end_offset"] - actual["offset"]
                if left[:first] != right[:other_first] or left[last:] != right[other_last:]:
                    raise ValueError("A non-name root application byte changed during rename.")
            elif left != right:
                raise ValueError("A non-name application record changed during rename.")
    query = {
        "source_sha256": observed.source_sha256,
        "expected_instance": new_instance,
        "new_instance": old_instance,
    }
    if not renaming:
        plan = observed.preview(**query)
        reverted, _ = observed.export(**query, plan_sha256=plan["plan_sha256"])
        if MoiIdentity(reverted).data != saved.data:
            raise ValueError(
                "Non-identity application bytes changed; program/settings preservation failed."
            )

    source_records, actual_records = _records(saved), _records(observed)
    root_class = saved.summary()["root_class"]
    for parameter in parameters.parameters:
        cid, instance, pid = (parameter[k] for k in ("class", "instance", "property"))
        source_id = (cid << 22) | instance
        actual_id = (cid << 22) | (
            new_instance if cid == root_class and instance == old_instance else instance
        )
        if renaming and cid == root_class and instance == old_instance and pid == 2390:
            continue  # The reviewed Device name is the sole permitted setting edit.
        if _value(saved, source_records[source_id], pid) != _value(
            observed, actual_records[actual_id], pid
        ):
            raise ValueError("A saved application parameter changed during the instance edit.")

    post = ParameterApplication(after[3], after[11], after[12])
    current_archive, current = post.compile()
    current_app = MoiIdentity(current_archive)
    current_records = _records(current_app)
    by_class, names = _property_names()
    counters, calculated = [], []
    for parameter in current["changed_parameters"]:
        cid, pid = str(parameter["class"]), str(parameter["property"])
        label = by_class.get(cid, {}).get(pid, names.get(pid, "Unknown"))
        # Flow Primitive's zero-flow offset is a calculated output, recalculated
        # by the application's autocalibration sequence. This is a native module
        # attribute, not a controller-model exception or a manual sensor offset.
        # Johnson Controls, Controller Tool Help: Attributes (Flow Calculation).
        # https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/14.0/Setpoint/Miscellaneous-Modules/Flow-Calculation/Flow-Calculation/Attributes-Flow-Calculation
        if (parameter["class"], parameter["property"], label) == (
            570,
            3506,
            "Autocalibrate Offset",
        ):
            oid = (parameter["class"] << 22) | parameter["instance"]
            previous = observed.reader.scalar(actual_records[oid], parameter["property"])
            value = current_app.reader.scalar(current_records[oid], parameter["property"])
            if not all(isinstance(v, float) and math.isfinite(v) for v in (previous, value)):
                raise ValueError("Calculated flow offset has an unsupported non-real value.")
            calculated.append(
                {
                    **parameter,
                    "property_name": label,
                    "application_value": previous,
                    "current_saved_value": value,
                    "reason": "Flow module calculated zero-flow calibration output",
                }
            )
            continue
        if (parameter["property"], label) not in (
            (15, "COS Count"),
            (33, "Elapsed Active Time"),
        ):
            raise ValueError(
                "A current saved parameter differs beyond documented runtime outputs; "
                "retain the snapshots and review before another write."
            )
        counters.append({**parameter, "property_name": label})
    return {
        "profile": "native-application-preservation/1",
        "application_identical_except_instance": not renaming,
        "application_identical_except_name": renaming,
        "allowed_identity_changes": ["name"] if renaming else ["instance"],
        "saved_application_parameters_verified": len(parameters.parameters),
        "post_saved_parameters": current["matched_parameters"],
        "runtime_counter_changes": counters,
        "device_calculated_changes": calculated,
        "source_application_sha256": sha(before[3]),
        "source_saved_parameters_sha256": sha(before[11] + before[12]),
        "verified_application_sha256": sha(after[3]),
        "preserved_native_sha256": sha(saved.data),
        "controller_writes": False,
    }
