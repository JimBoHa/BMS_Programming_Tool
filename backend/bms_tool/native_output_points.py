"""Independent output points and same-mode moves on documented CV output terminals."""

import math
import re

from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Unsigned

from .moi_identity import controller_name
from .native_inputs import encoded, native_record, record_instance, replace_properties
from .native_io_records import require_unused_point, scalar_bytes, terminal_leaf

OUTPUT_MODES = {
    "allocate-discrete-output": "binary",
    "allocate-binary-output": "binary",
    "binary-output-terminal": "binary",
    "allocate-proportional-output": "proportional",
    "proportional-output-terminal": "proportional",
}
OUTPUT_ACTIONS = set(OUTPUT_MODES)
ALLOCATION_ACTIONS = {
    "allocate-binary-output",
    "allocate-proportional-output",
    "allocate-discrete-output",
}
TERMINALS = {"binary": (1, 2, 3, 4, 5), "proportional": (4, 5)}
PUBLIC_TYPES = {"binary": 4, "proportional": 1}
CLASSES = {"binary": 239, "proportional": 241}


def label(slot):
    return f"BO OUT{slot}" if slot <= 3 else f"CO OUT{slot - 3}"


def signal(slot, mode):
    if mode == "proportional":
        return "0–10 VDC proportional"
    return ("internally powered" if slot <= 3 else "externally powered") + " 24 VAC triac"


def bindings(app):
    """Reserve every local or integral output. Ambiguous records cannot establish spare I/O."""
    occupied = {}
    for row in app.records:
        cid = row["class_id"]
        obj = app.reader.scalar(row, 75)
        dtype = app.reader.scalar(row, 31)
        if cid not in (239, 241, 251):
            if (
                (
                    isinstance(obj, str)
                    and obj.split(",")[0]
                    in ("binary-output", "analog-output", "multi-state-output")
                )
                or (
                    isinstance(dtype, str)
                    and re.search(r"\b(?:OUT\s*[-#]?\s*\d|(?:BO|AO|CO)\s*[-#]?\s*\d)", dtype, re.I)
                )
                or any(pid in row["properties"] for pid in (990, 991))
                or (519 in row["properties"] and cid not in (240, 242))
            ):
                raise ValueError("An unrecognized output could own a terminal.")
            continue
        expected_type = 4 if cid == 239 else 1
        for pid, kind in (
            (75, "ObjectIdentifier"),
            (32527, "CharacterString"),
            (31, "CharacterString"),
            (990, "Unsigned"),
        ):
            scalar_bytes(app, row, pid, kind)
        for pid in (991, 519):
            if pid in row["properties"]:
                scalar_bytes(app, row, pid, "Unsigned")
        actual = ObjectIdentifier(obj) if isinstance(obj, str) else None
        instance = record_instance(app, row)
        if (
            actual is None
            or int(actual[0]) != expected_type
            or actual[1] != instance
            or app.reader.scalar(row, 32527) != f"{app.ref}/{expected_type}_{instance}"
        ):
            raise ValueError("A published output has an ambiguous owner or hardware reference.")
        slot = app.reader.scalar(row, 990)
        second = app.reader.scalar(row, 991)
        alias = app.reader.scalar(row, 519)
        if alias not in (None, slot):
            raise ValueError("Output terminal assignments disagree.")
        if cid == 251:
            if (slot, second, dtype) != (6, 7, "BO1-Int,BO2-Int"):
                raise ValueError("An unqualified paired output could occupy either terminal.")
            slots = [6, 7]
        else:
            if slot not in (1, 2, 3, 4, 5) or dtype != label(slot) or second not in (None, 0):
                raise ValueError("An ambiguous external output prevents allocation.")
            if cid == 241 and slot not in TERMINALS["proportional"]:
                raise ValueError("A proportional output has an incompatible physical terminal.")
            slots = [slot]
        for terminal in slots:
            if terminal in occupied:
                raise ValueError("More than one point owns an output terminal.")
            occupied[terminal] = row
    return occupied


def electrical_fields(app, row, mode):
    """Copy only a closed, typed electrical profile. Counters, links and commands never propagate."""
    props = row["properties"]
    common = {32527, 75, 2390, 28, 31, 990, 991, 519}
    if mode == "binary":
        required = {
            4: "CharacterString",
            46: "CharacterString",
            518: "Enumerated",
            931: "Enumerated",
        }
        optional = {84: "Enumerated"}
        allowed = common | required.keys() | optional.keys() | {15, 33}
        if app.reader.scalar(row, 518) != 0 or app.reader.scalar(row, 84) not in (None, 0):
            raise ValueError("The source is outside the normal two-state binary output profile.")
    else:
        required = {117: "Enumerated"}
        optional = {661: "Enumerated", 3478: "Real"}
        allowed = common | required.keys() | optional.keys()
        stroke = app.reader.scalar(row, 3478)
        if app.reader.scalar(row, 117) != 98 or (
            stroke is not None
            and (not isinstance(stroke, float) or not math.isfinite(stroke) or stroke < 0)
        ):
            raise ValueError("Select a percentage-based proportional configurable output.")
    if props.keys() - allowed or not required.keys() <= props.keys():
        raise ValueError("The source has an unqualified output configuration.")
    return {
        pid: scalar_bytes(app, row, pid, dtype)
        for pid, dtype in (required | optional).items()
        if pid in props
    }


def output_options(app):
    occupied = bindings(app)
    options = []
    for slot, row in sorted(occupied.items()):
        if row["class_id"] == 251:
            continue
        mode = "binary" if row["class_id"] == 239 else "proportional"
        try:
            electrical_fields(app, row, mode)
            unavailable = None
        except ValueError as exc:
            unavailable = str(exc)
        options.append(
            {
                "object": app.reader.scalar(row, 75),
                "name": app.reader.scalar(row, 2390),
                "slot": slot,
                "device_type": label(slot),
                "mode": mode,
                "available_slots": [n for n in TERMINALS[mode] if n not in occupied]
                if not unavailable
                else [],
                "terminal_signals": {
                    n: signal(n, mode) for n in TERMINALS[mode] if n not in occupied
                },
                "unavailable_reason": unavailable,
            }
        )
    return options


def discrete_terminals(app):
    occupied = bindings(app)
    return [slot for slot in (1, 2, 3) if slot not in occupied]


def new_discrete_output(app, edit):
    if edit.slot not in discrete_terminals(app):
        raise ValueError("Select a free internally powered binary output.")
    cid, kind = CLASSES["binary"], PUBLIC_TYPES["binary"]
    oid = str(ObjectIdentifier((kind, edit.object_instance)))
    require_unused_point(app, cid, kind, edit.object_instance, edit.name, oid)
    # The normal two-state CV output has no program connection. Its independent
    # publication must subsequently prove zero default, zero output and clear priorities.
    properties = [
        (32527, encoded(CharacterString(f"{app.ref}/{kind}_{edit.object_instance}"))),
        (4, encoded(CharacterString("On"))),
        (28, encoded(CharacterString(edit.description))),
        (31, encoded(CharacterString(label(edit.slot)))),
        (46, encoded(CharacterString("Off"))),
        (75, encoded(ObjectIdentifier(oid))),
        (518, encoded(Enumerated(0))),
        (931, encoded(Enumerated(83))),
        (990, encoded(Unsigned(edit.slot))),
        (2390, encoded(CharacterString(controller_name(edit.name)))),
    ]
    change = {
        "object": oid,
        "operation": "allocate",
        "mode": "binary",
        "name": edit.name,
        "after_slot": edit.slot,
        "after_device_type": label(edit.slot),
        "after_signal": signal(edit.slot, "binary"),
        "has_slot_alias": False,
    }
    return native_record(cid, edit.object_instance, properties), None, change


def compile_output(app, edit):
    if edit.action == "allocate-discrete-output":
        return new_discrete_output(app, edit)
    occupied = bindings(app)
    mode = OUTPUT_MODES[edit.action]
    cid, kind = CLASSES[mode], PUBLIC_TYPES[mode]
    allocate = edit.action in ALLOCATION_ACTIONS
    if edit.slot not in TERMINALS[mode] or edit.slot in occupied:
        raise ValueError("The destination must be a free compatible physical output.")
    source = occupied.get(edit.expected_slot)
    source_id = edit.template_instance if allocate else edit.object_instance
    if source is None or source["class_id"] != cid or record_instance(app, source) != source_id:
        raise ValueError("The selected source output or its original terminal changed.")
    if not allocate and mode == "binary":
        if app.reader.scalar(source, 518) != 0:
            raise ValueError("Select a configured two-state binary output for a terminal move.")
        scalar_bytes(app, source, 518, "Enumerated")
    # A move keeps the complete source record. Unknown configuration is never cloned.
    if allocate or mode == "proportional" or (edit.expected_slot <= 3 < edit.slot):
        fields = electrical_fields(app, source, mode)
    oid = str(ObjectIdentifier((kind, edit.object_instance)))
    old_label = app.reader.scalar(source, 31)
    new_label = label(edit.slot)
    change = {
        "object": oid,
        "operation": "allocate" if allocate else "move",
        "mode": mode,
        "source_object": app.reader.scalar(source, 75),
        "source_name": app.reader.scalar(source, 2390),
        "before_slot": edit.expected_slot,
        "before_device_type": old_label,
        "after_slot": edit.slot,
        "after_device_type": new_label,
        "after_signal": signal(edit.slot, mode),
        "has_slot_alias": 519 in source["properties"],
    }
    terminal = {
        31: terminal_leaf(app, source, 31, new_label),
        990: terminal_leaf(app, source, 990, edit.slot),
    }
    if 519 in source["properties"]:
        terminal[519] = terminal_leaf(app, source, 519, edit.slot)
    if not allocate:
        return replace_properties(app, source, terminal), source, change

    require_unused_point(app, cid, kind, edit.object_instance, edit.name, oid)
    props = {
        32527: encoded(CharacterString(f"{app.ref}/{kind}_{edit.object_instance}")),
        28: encoded(CharacterString(edit.description)),
        75: encoded(ObjectIdentifier(oid)),
        2390: encoded(CharacterString(controller_name(edit.name))),
        **fields,
        **terminal,
    }
    change["name"] = edit.name
    # Native local records put the qualified reference first, followed by configuration fields.
    ordered = [(32527, props.pop(32527)), *sorted(props.items())]
    return native_record(cid, edit.object_instance, ordered), None, change
