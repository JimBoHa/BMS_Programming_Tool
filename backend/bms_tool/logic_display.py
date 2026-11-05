"""Display names for observed graph pins; never an authoring capability check."""

from .caf import ATTRIBUTES, BY_CLASS


def pin_name(class_id, property_id):
    """Expand dynamic I/O names without assigning direction or a native datatype."""
    cid, pid = str(class_id), str(property_id)
    name = BY_CLASS.get(cid, {}).get(pid, ATTRIBUTES.get(pid, ""))
    # The dictionaries identify the first indexed input/output. Subsequent
    # members use that same observed attribute series, not guessed process names.
    number = int(property_id)
    if BY_CLASS.get(cid, {}).get("7000") == "I1" and 7000 <= number < 7100:
        return f"Input {number - 6999}"
    if BY_CLASS.get(cid, {}).get("8000") == "O1" and 8000 <= number < 8100:
        return f"Output {number - 7999}"
    if name in {"", "Unmapped property", "structElementProp", "numericProp"}:
        return f"Property {pid}"
    return name


def function_symbol(class_id, setup):
    """Reference labels for Setup, independent of controller model and write support."""
    labels = {
        "560": {0: "<", 1: ">", 2: "≤", 3: "≥", 4: "≠", 5: "="},
        "561": {12: "÷", 13: "−", 14: "+", 15: "×", 16: "AVG", 17: "MAX", 18: "MIN", 22: "Σ"},
    }
    text = labels.get(str(class_id), {}).get(setup)
    return {"text": text, "source": "Setup attribute reference label"} if text else None


def pin_labels(blocks, wires):
    """Only recorded endpoints become directed pins; labels remain metadata."""
    by_ref = {b["ref"]: b for b in blocks}
    labels = {}
    for wire in wires:
        for end in ("source", "target"):
            block = by_ref[wire[f"{end}_ref"]]
            cid, pid = str(block["class_id"]), wire[f"{end}_port"]
            labels.setdefault(cid, {})[str(pid)] = pin_name(cid, pid)
    return labels
