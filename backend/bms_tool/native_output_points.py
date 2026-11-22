"""Independent output points and same-mode moves on documented CV output terminals."""

import math
import re

from bacpypes3.errors import InvalidTag
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Tag, TagClass, Unsigned

from .moi_identity import controller_name
from .native_inputs import encoded, native_record, raw_property, record_instance, replace_properties

OUTPUT_ACTIONS = {
    "allocate-binary-output",
    "allocate-proportional-output",
    "proportional-output-terminal",
}
ALLOCATION_ACTIONS = {"allocate-binary-output", "allocate-proportional-output"}
TERMINALS = {"binary": (1, 2, 3), "proportional": (4, 5)}
PUBLIC_TYPES = {"binary": 4, "proportional": 1}
CLASSES = {"binary": 239, "proportional": 241}
TAGS = {"Unsigned": 2, "Real": 4, "CharacterString": 7, "Enumerated": 9, "ObjectIdentifier": 12}


def label(slot):
    return f"BO OUT{slot}" if slot <= 3 else f"CO OUT{slot - 3}"


def scalar_bytes(app, row, pid, dtype):
    prop = row["properties"].get(pid, {})
    if (prop.get("scalar") or {}).get("datatype") != dtype:
        raise ValueError(f"Output property {pid} lacks its expected {dtype} value.")
    raw = raw_property(app, row, pid)
    data = PDUData(raw)
    try:
        first, closing = Tag.decode(data), Tag.decode(data)
    except (InvalidTag, ValueError, IndexError) as exc:
        raise ValueError(f"Output property {pid} has invalid scalar framing.") from exc
    if (
        first.tag_class != TagClass.application
        or first.tag_number != TAGS[dtype]
        or closing.tag_class != TagClass.closing
        or closing.tag_number != 2
        or data.pduData
    ):
        raise ValueError(f"Output property {pid} contains more than one typed value.")
    return raw[:-1]


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
                "unavailable_reason": unavailable,
            }
        )
    return options


def compile_output(app, edit):
    occupied = bindings(app)
    mode = "binary" if edit.action == "allocate-binary-output" else "proportional"
    cid, kind = CLASSES[mode], PUBLIC_TYPES[mode]
    allocate = edit.action in ALLOCATION_ACTIONS
    if edit.slot not in TERMINALS[mode] or edit.slot in occupied:
        raise ValueError("The destination must be a free compatible physical output.")
    source = occupied.get(edit.expected_slot)
    source_id = edit.template_instance if allocate else edit.object_instance
    if source is None or source["class_id"] != cid or record_instance(app, source) != source_id:
        raise ValueError("The selected source output or its original terminal changed.")
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
    }
    terminal = {31: encoded(CharacterString(new_label)), 990: encoded(Unsigned(edit.slot))}
    if 519 in source["properties"]:
        terminal[519] = encoded(Unsigned(edit.slot))
    if not allocate:
        return replace_properties(app, source, terminal), source, change

    for row in app.records:
        name = app.reader.scalar(row, 2390)
        if (
            row["class_id"] == cid
            and record_instance(app, row) == edit.object_instance
            or app.reader.scalar(row, 75) == oid
            or app.reader.scalar(row, 32527) == f"{app.ref}/{kind}_{edit.object_instance}"
            or isinstance(name, str)
            and name.casefold() == edit.name.casefold()
        ):
            raise ValueError("The proposed output name or identifier is in use.")
    # An unresolved reference could begin driving a freshly allocated point.
    suffix = f"/{kind}_{edit.object_instance}"
    identifiers = [(n << 22 | edit.object_instance).to_bytes(4, "big") for n in (kind, cid)]
    if any(token in app.data for token in identifiers) or any(
        suffix.encode(charset) in app.data for charset in ("ascii", "utf-16-le", "utf-16-be")
    ):
        raise ValueError(
            "The proposed output identifier occurs in the retained image. Choose an unused identifier."
        )
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
