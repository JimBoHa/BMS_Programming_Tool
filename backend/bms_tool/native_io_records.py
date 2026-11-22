"""Typed leaves and free-point identity checks shared by saved-effective local I/O edits."""

from bacpypes3.errors import InvalidTag
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import Tag, TagClass

from .moi_terminal_labels import EncodedTerminalCopies
from .native_inputs import raw_property, record_instance

TAGS = {"Unsigned": 2, "Real": 4, "CharacterString": 7, "Enumerated": 9, "ObjectIdentifier": 12}


def scalar_bytes(app, row, pid, dtype):
    prop = row["properties"].get(pid, {})
    if (prop.get("scalar") or {}).get("datatype") != dtype:
        raise ValueError(f"I/O property {pid} lacks its expected {dtype} value.")
    raw = raw_property(app, row, pid)
    data = PDUData(raw)
    try:
        first, closing = Tag.decode(data), Tag.decode(data)
    except (InvalidTag, ValueError, IndexError) as exc:
        raise ValueError(f"I/O property {pid} has invalid scalar framing.") from exc
    if (
        first.tag_class != TagClass.application
        or first.tag_number != TAGS[dtype]
        or closing.tag_class != TagClass.closing
        or closing.tag_number != 2
        or data.pduData
    ):
        raise ValueError(f"I/O property {pid} contains more than one typed value.")
    return raw[:-1]


def terminal_leaf(app, row, pid, value):
    dtype = "CharacterString" if pid == 31 else "Unsigned"
    raw = scalar_bytes(app, row, pid, dtype)
    previous = bytes(Tag.decode(PDUData(raw)).tag_data)
    if pid == 31:
        payload = EncodedTerminalCopies.label_payload(previous, value)
        if len(payload) != len(previous):
            raise ValueError("Unqualified terminal label size.")
    else:
        if not 1 <= len(previous) <= 4:
            raise ValueError("Invalid terminal slot width.")
        payload = value.to_bytes(len(previous), "big")
    return raw[: -len(previous)] + payload


def require_unused_point(app, cid, kind, instance, point_name, oid):
    for row in app.records:
        name = app.reader.scalar(row, 2390)
        if (
            row["class_id"] == cid
            and record_instance(app, row) == instance
            or app.reader.scalar(row, 75) == oid
            or app.reader.scalar(row, 32527) == f"{app.ref}/{kind}_{instance}"
            or isinstance(name, str)
            and name.casefold() == point_name.casefold()
        ):
            raise ValueError("The proposed point name or identifier is in use.")
    # An unresolved reference could begin driving a freshly allocated point.
    suffix = f"/{kind}_{instance}"
    identifiers = [(n << 22 | instance).to_bytes(4, "big") for n in (kind, cid)]
    if any(token in app.data for token in identifiers) or any(
        suffix.encode(charset) in app.data for charset in ("ascii", "utf-16-le", "utf-16-be")
    ):
        raise ValueError(
            "The proposed point identifier occurs in the retained image. Choose an unused identifier."
        )
