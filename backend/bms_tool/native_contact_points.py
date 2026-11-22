"""Maintained dry contacts on the qualified controller's local universal terminals."""

import re

from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Unsigned

from .native_binary_terminal import configuration
from .native_inputs import encoded, native_record, replace_properties
from .native_io_records import require_unused_point, scalar_bytes, terminal_leaf
from .native_output_points import bindings as output_bindings

CONTACT_ACTIONS = {"allocate-binary", "binary-input-terminal", "binary-input-polarity"}
POLARITIES = ("normal", "reverse")


def contact_bindings(app, capacity):
    occupied = {}
    integral_seen = False
    identities = set()
    if any(r["class_id"] in (239, 241, 251) and 519 in r["properties"] for r in app.records):
        # Some classes use the same property number for their output terminal.
        output_bindings(app)
    for row in app.records:
        cid = row["class_id"]
        obj, ref, label, slot = (app.reader.scalar(row, pid) for pid in (75, 32527, 31, 519))
        if 75 in row["properties"]:
            scalar_bytes(app, row, 75, "ObjectIdentifier")
            if obj in identities:
                raise ValueError("Duplicate published identities prevent contact assignment.")
            identities.add(obj)
        if cid not in (240, 242):
            if (
                (isinstance(obj, str) and obj.split(",")[0] in ("analog-input", "binary-input"))
                or (
                    isinstance(label, str)
                    and re.search(r"\b(?:UI|AI|BI|CI)\s*[-#]?\s*IN\s*\d", label, re.I)
                )
                or (519 in row["properties"] and cid not in (239, 241, 251))
            ):
                raise ValueError("An unrecognized input could own a local terminal.")
            continue
        for pid, dtype in (
            (75, "ObjectIdentifier"),
            (32527, "CharacterString"),
            (31, "CharacterString"),
            (519, "Unsigned"),
        ):
            scalar_bytes(app, row, pid, dtype)
        header = int.from_bytes(app.data[row["offset"] + 6 : row["offset"] + 10], "big")
        kind = 0 if cid == 240 else 3
        oid = ObjectIdentifier(obj)
        if (
            int(oid[0]) != kind
            or header != (cid << 22 | oid[1])
            or ref != f"{app.ref}/{kind}_{oid[1]}"
        ):
            raise ValueError("The physical input identity or terminal host is ambiguous.")
        if (cid, label, slot, app.reader.scalar(row, 518)) == (
            240,
            "AI1-Int",
            4,
            9,
        ) and not integral_seen:
            integral_seen = True
            continue
        if slot not in capacity["universal_inputs"] or label != f"UI IN{slot}" or slot in occupied:
            raise ValueError("An occupied or ambiguous local input prevents assignment.")
        occupied[slot] = row
    return occupied


def contact_options(app, capacity):
    occupied = contact_bindings(app, capacity)
    free = [i for i in capacity["universal_inputs"] if i not in occupied]
    contacts = []
    for slot, row in sorted(occupied.items()):
        if row["class_id"] != 242:
            continue
        try:
            config = configuration(app, row)["configuration"]
            reason = None
        except ValueError as exc:
            config = {}
            reason = str(exc)
        polarity = config.get("polarity")
        contacts.append(
            {
                "object": app.reader.scalar(row, 75),
                "name": app.reader.scalar(row, 2390),
                "slot": slot,
                "polarity": None if polarity is None else POLARITIES[polarity],
                "active_text": config.get("active_text"),
                "inactive_text": config.get("inactive_text"),
                "available_slots": free if not reason else [],
                "unavailable_reason": reason,
            }
        )
    return {"contacts": contacts, "available_slots": free}


def compile_contact(app, capacity, edit):
    occupied = contact_bindings(app, capacity)
    obj = f"binary-input,{edit.object_instance}"
    label = f"UI IN{edit.slot}"
    if edit.action == "allocate-binary":
        if edit.slot not in capacity["universal_inputs"] or edit.slot in occupied:
            raise ValueError("Choose a free local universal input terminal.")
        require_unused_point(app, 242, 3, edit.object_instance, edit.name, obj)
        polarity = edit.polarity or "normal"
        properties = {
            32527: CharacterString(f"{app.ref}/3_{edit.object_instance}"),
            4: CharacterString("On"),
            28: CharacterString(edit.description),
            31: CharacterString(label),
            46: CharacterString("Off"),
            75: ObjectIdentifier(obj),
            84: Enumerated(POLARITIES.index(polarity)),
            519: Unsigned(edit.slot),
            931: Enumerated(83),
            2390: CharacterString(edit.name),
        }
        new = native_record(
            242, edit.object_instance, [(k, encoded(v)) for k, v in properties.items()]
        )
        return (
            new,
            None,
            {
                "object": obj,
                "operation": "allocate",
                "slot": edit.slot,
                "after_slot": edit.slot,
                "name": edit.name,
                "polarity": polarity,
                "states": ["Off", "On"],
                "states_text_index": 83,
            },
        )
    row = occupied.get(edit.expected_slot)
    if row is None or row["class_id"] != 242 or app.reader.scalar(row, 75) != obj:
        raise ValueError("The selected contact or its original terminal changed.")
    config = configuration(app, row)["configuration"]
    before = config["polarity"]
    change = {
        "object": obj,
        "before_slot": edit.expected_slot,
        "after_slot": edit.slot,
        "source_name": app.reader.scalar(row, 2390),
        "before_polarity": None if before is None else POLARITIES[before],
        "states": [config["inactive_text"], config["active_text"]],
        "states_text_index": config["states_text_index"],
    }
    if edit.action == "binary-input-terminal":
        if edit.slot not in capacity["universal_inputs"] or edit.slot in occupied:
            raise ValueError("Choose a free local universal input terminal.")
        leaves = {
            31: terminal_leaf(app, row, 31, label),
            519: terminal_leaf(app, row, 519, edit.slot),
        }
        change.update(operation="move", polarity=change["before_polarity"])
    else:
        if before is not None and POLARITIES[before] == edit.polarity:
            raise ValueError("Choose a different contact polarity.")
        polarity = POLARITIES.index(edit.polarity)
        # Keep the original enum tag and its stored width when the property exists.
        if 84 in row["properties"]:
            previous = scalar_bytes(app, row, 84, "Enumerated")
            leaves = {84: previous[:-1] + bytes([polarity])}
        else:
            leaves = {84: encoded(Enumerated(polarity))}
        change.update(operation="polarity", polarity=edit.polarity)
    return replace_properties(app, row, leaves), row, change
