"""Merge captured parameter storage into a native application without vendor code.

PSS selectors use native class metadata, not a controller-model inventory. Values
are read from bounds-checked slots with their per-value CRC. The compiler changes
only application properties represented by the captured parameter directory;
unknown application datatypes prevent a transfer. Non-application slots remain
in the retained original backup and are never invented in the program.
"""

import struct
import zlib

from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import (
    Boolean,
    ClosingTag,
    Enumerated,
    Integer,
    Real,
    Tag,
    TagClass,
    TagList,
    Unsigned,
)

from .moi_identity import MoiIdentity, sha
from .mstp import header_crc

# Native storage types, independent of product code and expansion count.
STORAGE = {
    1: (1, Boolean),
    2: (4, Unsigned),
    4: (4, Real),
    9: (2, Enumerated),
    16: (1, Unsigned),
    17: (2, Integer),
    18: (2, Unsigned),
}


def _encode(tags):
    return bytes(TagList(tags).encode().pduData)


def _inline(data, datatype):
    if datatype not in (7, 24) or not data or data[0] != 0x1E:
        raise ValueError("Unsupported inline application parameter datatype.")
    pdu, tags, depth = PDUData(data), [], []
    while pdu.pduData:
        tag = Tag.decode(pdu)
        tags.append(tag)
        if tag.tag_class == TagClass.opening:
            depth.append(tag.tag_number)
        elif tag.tag_class == TagClass.closing:
            if not depth or depth.pop() != tag.tag_number:
                raise ValueError("Mismatched inline parameter group.")
            if not depth:
                break
        if len(depth) > 16 or len(tags) > 4096:
            raise ValueError("Inline parameter exceeds its framing budget.")
    if depth or any(pdu.pduData):
        raise ValueError("Inline parameter has unsupported trailing data.")
    if not tags or tags[-1].tag_number != 1:
        raise ValueError("Unterminated inline parameter group.")
    return _encode([*tags[1:-1], ClosingTag(2)])


class ParameterApplication:
    def __init__(self, archive, static, dynamic):
        self.application = app = MoiIdentity(archive)
        if not isinstance(static, bytes) or not 1 <= len(static) <= 128 * 1024:
            raise ValueError("Static parameter directory exceeds the capture profile.")
        if not isinstance(dynamic, bytes) or not 1 <= len(dynamic) <= 128 * 1024:
            raise ValueError("Dynamic parameter storage exceeds the capture profile.")
        objects = {}
        for record in app.records:
            oid = int.from_bytes(app.data[record["offset"] + 6 : record["offset"] + 10], "big")
            if oid in objects:
                raise ValueError("Duplicate native object identifiers prevent parameter matching.")
            objects[oid] = record
        self.replacements, self.parameters = {}, []
        used, selectors, offset = {}, set(), 0
        while offset < len(static):
            length = int.from_bytes(static[offset : offset + 2], "big")
            if length < 14 or offset + length > len(static):
                raise ValueError("Static parameter directory has invalid record framing.")
            row = static[offset : offset + length]
            oid, pid = int.from_bytes(row[2:6], "big"), int.from_bytes(row[6:8], "big")
            flags, datatype, cid = row[8], row[9], int.from_bytes(row[10:12], "big")
            if cid > 1023 or (oid, pid) in selectors:
                raise ValueError("Static parameter selector is invalid or duplicated.")
            selectors.add((oid, pid))
            record = objects.get((cid << 22) | (oid & 4194303))
            prop = record["properties"].get(pid) if record else None
            value = None
            if flags in (0x6F, 0xEF, 0x67):
                if length != 16 or datatype not in STORAGE:
                    raise ValueError("Unsupported dynamic parameter storage datatype.")
                width, kind = STORAGE[datatype]
                position = int.from_bytes(row[12:14], "big")
                end = position + width
                if end >= len(dynamic) or any(i in used for i in range(position, end + 1)):
                    raise ValueError("Dynamic parameter offsets overlap or exceed the capture.")
                payload = dynamic[position:end]
                checksum = header_crc(payload) ^ (0 if flags == 0x67 else 0xFF)
                if dynamic[end] != checksum:
                    raise ValueError("Dynamic parameter checksum does not match its value.")
                used.update(dict.fromkeys(range(position, end + 1)))
                if flags == 0x67:
                    if prop is not None:
                        raise ValueError("Application parameter has no valid saved value.")
                    offset += length
                    continue
                if kind is Real:
                    value = b"\x44" + payload + b"\x2f"
                    # Preserve the exact IEEE bits, including signed zero; do not
                    # round trip the value through Python floating point.
                    if (int.from_bytes(payload, "big") & 0x7F800000) == 0x7F800000:
                        raise ValueError("Nonfinite saved application parameter.")
                elif kind is Boolean:
                    if payload not in (b"\x00", b"\x01"):
                        raise ValueError("Saved Boolean is outside its native encoding.")
                    value = _encode([*Boolean(bool(payload[0])).encode(), ClosingTag(2)])
                else:
                    number = int.from_bytes(payload, "big", signed=kind is Integer)
                    value = _encode([*kind(number).encode(), ClosingTag(2)])
            elif flags == 0x4F:
                value = _inline(row[12:-2], datatype)
            else:
                raise ValueError("Unsupported saved parameter storage flags.")
            if prop is not None:
                start, end = prop["value_start_offset"], prop["value_end_offset"]
                # A parameter must keep the property's native BACnet datatype.
                before = app.data[start:end]
                if not before or (before[0] >> 4) != (value[0] >> 4):
                    raise ValueError(
                        "Saved parameter datatype differs from its application property."
                    )
                if start in self.replacements:
                    raise ValueError(
                        "Multiple saved selectors resolve to one application property."
                    )
                self.replacements[start] = (end, value)
                self.parameters.append(
                    {
                        "class": cid,
                        "instance": oid & 4194303,
                        "property": pid,
                        "changed": before != value,
                    }
                )
            offset += length
        if len(used) != len(dynamic):
            raise ValueError("Dynamic parameter storage contains unaccounted values.")
        self.static_sha256, self.dynamic_sha256 = sha(static), sha(dynamic)

    def compile(self):
        app = self.application
        output, previous_end = bytearray(app.data[:14]), 14
        for record in app.records:
            start, end = record["offset"], record["end_offset"]
            prefix = start - previous_end
            raw, cursor = bytearray(), start
            for position in sorted(p for p in self.replacements if start <= p < end):
                old_end, value = self.replacements[position]
                raw.extend(app.data[cursor:position])
                raw.extend(value)
                cursor = old_end
            raw.extend(app.data[cursor:end])
            extended = prefix == 6 or len(raw) + 2 > 65535
            output.extend(
                b"\x00\x00" + struct.pack("<I", len(raw) + 6)
                if extended
                else struct.pack("<H", len(raw) + 2)
            )
            output.extend(raw)
            previous_end = end
        native = bytes(output)
        if app.compressed:
            compressor = zlib.compressobj(level=9, wbits=-15)
            result = (
                app.source[:10]
                + compressor.compress(native)
                + compressor.flush()
                + struct.pack("<II", zlib.crc32(native), len(native))
            )
        else:
            result = native
        checked = MoiIdentity(result)
        if checked.instance != app.instance or len(checked.records) != len(app.records):
            raise ValueError("Parameter merge changed the native application identity or records.")
        return result, {
            "source_sha256": app.source_sha256,
            "output_sha256": sha(result),
            "native_output_sha256": sha(native),
            "static_sha256": self.static_sha256,
            "dynamic_sha256": self.dynamic_sha256,
            "matched_parameters": len(self.parameters),
            "changed_parameters": [p for p in self.parameters if p["changed"]],
            "vendor_runtime_required": False,
        }
