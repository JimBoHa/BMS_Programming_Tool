"""Read actual tagged MOI application records, independent of controller model.

Only recognized native graph fields become blocks and wires. Unknown records and
properties retain their source hashes. This reader neither compiles nor writes a
controller application, and does not turn archive defaults into live values.
"""

from __future__ import annotations

import hashlib
import math
import re
import zlib

from bacpypes3.errors import InvalidTag
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Double,
    Enumerated,
    Null,
    ObjectIdentifier,
    Real,
    Tag,
    TagClass,
    TagList,
    Unsigned,
)

from .caf import ATTRIBUTES, BY_CLASS, CLASSES
from .moi_framing import native_frames

MAX_SOURCE = 2 * 1024 * 1024
MAX_EXPANDED = 8 * 1024 * 1024
MAX_RECORDS = 20000
MAX_PROPERTIES = 4096
MAX_TAGS = 20000


def _expect(tag, kind, number):
    if tag.tag_class != kind or tag.tag_number != number:
        raise ValueError("Unrecognized native application framing.")


def _atomic(tag, datatype):
    _expect(
        tag,
        TagClass.application,
        {
            Null: 0,
            Boolean: 1,
            Unsigned: 2,
            Real: 4,
            Double: 5,
            CharacterString: 7,
            Enumerated: 9,
            ObjectIdentifier: 12,
        }[datatype],
    )
    if datatype in (Unsigned, Enumerated) and not 1 <= len(tag.tag_data) <= 4:
        raise ValueError("Native integer exceeds its recognized width.")
    widths = {Real: 4, Double: 8, ObjectIdentifier: 4, Null: 0, Boolean: 0}
    if datatype in widths and len(tag.tag_data) != widths[datatype]:
        raise ValueError("Native scalar width mismatch.")
    if datatype is CharacterString and (not tag.tag_data or len(tag.tag_data) > 4096):
        raise ValueError("Native string exceeds its bounded encoding profile.")
    remaining = TagList([tag])
    value = datatype.decode(remaining)
    if remaining:
        raise ValueError("Trailing native scalar tags.")
    if datatype in (Real, Double) and not math.isfinite(value):
        raise ValueError("Nonfinite native scalar.")
    if datatype is Boolean and tag.tag_lvt not in (0, 1):
        raise ValueError("Noncanonical native Boolean.")
    return value


def _value(tags):
    if len(tags) != 1 or tags[0].tag_class != TagClass.application:
        return None
    datatype = {
        0: Null,
        1: Boolean,
        2: Unsigned,
        4: Real,
        5: Double,
        7: CharacterString,
        9: Enumerated,
        12: ObjectIdentifier,
    }.get(tags[0].tag_number)
    if datatype is None:
        return None
    try:
        value = _atomic(tags[0], datatype)
        return {
            "datatype": datatype.__name__,
            "value": str(value)
            if datatype is ObjectIdentifier
            else None
            if datatype is Null
            else bool(value)
            if datatype is Boolean
            else float(value)
            if datatype in (Real, Double)
            else int(value)
            if datatype in (Unsigned, Enumerated)
            else str(value),
        }
    except (ValueError, TypeError, AttributeError, InvalidTag):
        return None


def _list(tags, datatype):
    return [_atomic(tag, datatype) for tag in tags]


def _structs(tags, datatypes):
    width = len(datatypes) + 2
    if len(tags) % width:
        raise ValueError("Native graph record width differs from the recognized format.")
    rows = []
    for offset in range(0, len(tags), width):
        _expect(tags[offset], TagClass.opening, 3)
        _expect(tags[offset + width - 1], TagClass.closing, 3)
        rows.append(
            [
                _atomic(tag, kind)
                for tag, kind in zip(tags[offset + 1 : offset + width - 1], datatypes, strict=True)
            ]
        )
    return rows


class MoiApplication:
    format = "jci-moi-tagged/1"
    extensions = (".moi",)

    def __init__(self, source):
        if not isinstance(source, bytes) or not 1 <= len(source) <= MAX_SOURCE:
            raise ValueError("Application archive exceeds the 2 MiB source profile.")
        self.sha256 = hashlib.sha256(source).hexdigest()
        data = source
        if source.startswith(b"\x1f\x8b"):
            decoder = zlib.decompressobj(31)
            try:
                data = decoder.decompress(source, MAX_EXPANDED + 1)
                if len(data) > MAX_EXPANDED or decoder.unconsumed_tail:
                    raise ValueError("Expanded native application exceeds 8 MiB.")
                data += decoder.flush(MAX_EXPANDED + 1 - len(data))
            except zlib.error as failure:
                raise ValueError("Invalid compressed native application.") from failure
            if not decoder.eof or decoder.unused_data or len(data) > MAX_EXPANDED:
                raise ValueError(
                    "Native application compression is incomplete or has trailing data."
                )
        if data[:6] != b"\x02\x00MOI\x00":
            raise ValueError(
                "This file does not contain the recognized tagged MOI application format."
            )
        self.data, self.records, self.errors = data, {}, []
        self.metadata_records = []
        frames = native_frames(data)
        if frames is None:
            pattern = rb"(?P<class>.{2})\x02\x00\x0e\x1c(?P<oid>.{4})\x0f\x1e"
            candidates = [
                (m.start(), int.from_bytes(m["class"], "little"), m["oid"], None)
                for m in re.finditer(pattern, data, re.S)
            ]
        else:
            candidates = frames
        accepted_end, count = 0, 0
        for start, cid, oid, declared_end in candidates:
            if (
                start < accepted_end
                or not 0 <= cid <= 1023
                or cid != int.from_bytes(oid, "big") >> 22
            ):
                continue
            count += 1
            if count > MAX_RECORDS:
                raise ValueError("Native application exceeds its record budget.")
            try:
                record = self._record(start, cid, oid)
                if declared_end is not None and record["end_offset"] != declared_end:
                    raise ValueError("Native object does not consume its declared record length.")
                accepted_end = record["end_offset"]
                if frames is not None and 32527 not in record["properties"]:
                    self.metadata_records.append(record)
                    continue
                ref = self.scalar(record, 32527)
                if not isinstance(ref, str) or not ref or len(ref) > 512 or ref in self.records:
                    raise ValueError(
                        "Native application reference is absent, excessive or duplicated."
                    )
                record["ref"] = ref
                self.records[ref] = record
            except (ValueError, TypeError, AttributeError, InvalidTag) as failure:
                self.errors.append({"offset": start, "error": str(failure)[:240]})
        if not self.records:
            raise ValueError("No recognized native application records were found.")

    def _record(self, start, cid, oid):
        pdu = PDUData(self.data[start + 4 : min(len(self.data), start + 1024 * 1024)])
        before = len(pdu.pduData)
        _expect(Tag.decode(pdu), TagClass.opening, 0)
        identity = Tag.decode(pdu)
        _expect(identity, TagClass.context, 1)
        if bytes(identity.tag_data) != oid:
            raise ValueError("Native record identity mismatch.")
        _expect(Tag.decode(pdu), TagClass.closing, 0)
        _expect(Tag.decode(pdu), TagClass.opening, 1)
        properties = {}
        while True:
            tag = Tag.decode(pdu)
            if tag.tag_class == TagClass.closing and tag.tag_number == 1:
                break
            _expect(tag, TagClass.context, 0)
            if not 1 <= len(tag.tag_data) <= 4:
                raise ValueError("Invalid native property identifier.")
            pid = int.from_bytes(tag.tag_data, "big")
            if pid in properties or len(properties) >= MAX_PROPERTIES:
                raise ValueError("Duplicate or excessive native properties.")
            _expect(Tag.decode(pdu), TagClass.opening, 2)
            value_start = start + 4 + before - len(pdu.pduData)
            stack, tags = [2], []
            while stack:
                value = Tag.decode(pdu)
                if value.tag_class == TagClass.opening:
                    stack.append(value.tag_number)
                elif value.tag_class == TagClass.closing:
                    if value.tag_number != stack.pop():
                        raise ValueError("Native property nesting mismatch.")
                    if not stack:
                        break
                tags.append(value)
                if len(tags) > MAX_TAGS or len(stack) > 64:
                    raise ValueError("Native application tag/depth budget reached.")
            value_end = start + 4 + before - len(pdu.pduData)
            properties[pid] = {
                "id": pid,
                "value_start_offset": value_start,
                "value_end_offset": value_end,
                "name": BY_CLASS.get(str(cid), {}).get(
                    str(pid), ATTRIBUTES.get(str(pid), "Unmapped property")
                ),
                "scalar": _value(tags),
                "tags": tags,
                "encoded_sha256": hashlib.sha256(self.data[value_start:value_end]).hexdigest(),
            }
        end = start + 4 + before - len(pdu.pduData)
        return {
            "class_id": cid,
            "class_name": CLASSES.get(str(cid), {}).get("name", f"Unmapped native class {cid}"),
            "offset": start,
            "end_offset": end,
            "sha256": hashlib.sha256(self.data[start:end]).hexdigest(),
            "properties": properties,
        }

    @staticmethod
    def scalar(record, pid):
        return (record["properties"].get(pid, {}).get("scalar") or {}).get("value")

    def _block(self, record, index):
        return {
            "index": index,
            "ref": record["ref"],
            "object": self.scalar(record, 75),
            "class_id": record["class_id"],
            "class_name": record["class_name"],
            "name": self.scalar(record, 2390) or record["class_name"],
            "sha256": record["sha256"],
            "properties": [
                {key: value for key, value in prop.items() if key != "tags"}
                for prop in record["properties"].values()
            ],
        }

    def diagram(self, ref):
        record = self.records.get(ref)
        if record is None or record["class_id"] not in (536, 575):
            raise ValueError("Select an actual native activity or control sequence.")
        props = record["properties"]
        if not {3117, 3118, 3375} <= props.keys():
            raise ValueError(
                "This native graph does not contain the recognized block, wire and order fields."
            )
        identifiers = _list(props[3375]["tags"], ObjectIdentifier)
        if len(identifiers) > 512:
            raise ValueError("Native graph exceeds its 512-block view profile.")
        sequence = [int(value) for value in _list(props[3117]["tags"], Unsigned)]
        if sorted(sequence) != list(range(len(identifiers))):
            raise ValueError("Native graph order does not list each block exactly once.")
        blocks, seen = [], set()
        for index, oid in enumerate(identifiers):
            child = f"{ref}.{int(oid[0])}_{int(oid[1])}"
            found = self.records.get(child)
            if found is None or child in seen or self.scalar(found, 75) != str(oid):
                raise ValueError(
                    "Native block reference is missing, duplicated or does not match its identity."
                )
            seen.add(child)
            blocks.append(self._block(found, index))
        positions = _structs(props[3383]["tags"], (Real, Real, Unsigned)) if 3383 in props else None
        if positions is not None and len(positions) != len(blocks):
            raise ValueError("Native graph positions do not align with its block list.")
        for index, block in enumerate(blocks):
            block["layout"] = (
                {"x": float(positions[index][0]), "y": float(positions[index][1])}
                if positions is not None
                else None
            )
        rows = _structs(props[3118]["tags"], (Unsigned,) * 4)
        if len(rows) > 4096:
            raise ValueError("Native graph exceeds its connection budget.")
        wires = []
        for index, row in enumerate(rows):
            source, source_port, target, target_port = map(int, row)
            if source >= len(blocks) or target >= len(blocks) or max(row) > 65535:
                raise ValueError("Native graph wire points outside its actual block/port range.")
            wires.append(
                {
                    "index": index,
                    "source_ref": blocks[source]["ref"],
                    "source_port": source_port,
                    "target_ref": blocks[target]["ref"],
                    "target_port": target_port,
                }
            )
        return {
            "ref": ref,
            "name": self.scalar(record, 2390) or record["class_name"],
            "blocks": blocks,
            "connections": wires,
            "execution_order": sequence,
            "native_layout": positions is not None,
            "read_only": True,
        }

    def summary(self):
        diagrams, errors = [], list(self.errors)
        for ref, record in self.records.items():
            if record["class_id"] not in (536, 575):
                continue
            try:
                graph = self.diagram(ref)
                diagrams.append(
                    {
                        "ref": ref,
                        "name": graph["name"],
                        "blocks": len(graph["blocks"]),
                        "connections": len(graph["connections"]),
                    }
                )
            except (ValueError, TypeError, AttributeError, InvalidTag) as failure:
                errors.append({"ref": ref, "error": str(failure)[:240]})
        return {
            "metadata_records": len(self.metadata_records),
            "format": self.format,
            "sha256": self.sha256,
            "record_count": len(self.records),
            "diagrams": diagrams,
            "errors": errors,
            "capabilities": {
                "logic_read": bool(diagrams),
                "logic_write": False,
                "native_compile": False,
            },
        }
