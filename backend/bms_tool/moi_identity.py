"""Identity edits in a captured MCE application, with no vendor runtime.

Every native record is length-checked, including extended records without an
engineering reference. Two typed ObjectIdentifiers change; other bytes survive.
Connection, allocation, transfer and physical acceptance belong to the service.
"""

import hashlib
import json
import struct
import zlib

from bacpypes3.errors import InvalidTag
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import CharacterString, ClosingTag, ObjectIdentifier, Tag, TagList

from .moi_application import MoiApplication
from .moi_framing import native_frames

PROFILE = "tagged-moi-device-identity/1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def seal(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def number(value):
    if type(value) is not int or not 0 <= value <= 4194302:
        raise ValueError("Use an actual Device instance from 0 through 4194302.")
    return value


def controller_name(value):
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value.encode("utf-8")) > 128
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError(
            "Use a nonempty controller name of at most 128 UTF-8 bytes, without control characters or surrounding whitespace."
        )
    return value


class MoiIdentity:
    def __init__(self, content):
        self.source, self.reader = content, MoiApplication(content)
        self.data = self.reader.data
        self.source_sha256 = sha(content)
        self.compressed = content.startswith(b"\x1f\x8b")
        if self.compressed and (len(content) < 18 or content[2:4] != b"\x08\x00"):
            raise ValueError("Identity editing requires an ordinary single-member gzip header.")
        self.records = []
        for start, cid, oid, end in native_frames(self.data, required=True):
            try:
                record = self.reader._record(start, cid, oid)
            except (InvalidTag, TypeError, AttributeError, IndexError) as exc:
                raise ValueError("Unsupported native application value framing.") from exc
            if record["end_offset"] != end:
                raise ValueError("Native object does not consume its declared record length.")
            self.records.append(record)
        roots = []
        for record in self.records:
            ref, value = self.reader.scalar(record, 32527), self.reader.scalar(record, 75)
            if isinstance(ref, str) and "/" not in ref and isinstance(value, str):
                oid = ObjectIdentifier(value)
                if int(oid[0]) == 8:
                    roots.append((ref, record, int(oid[1])))
        if len(roots) != 1:
            raise ValueError("Native application requires one unambiguous root Device identity.")
        self.ref, self.root, self.instance = roots[0]
        number(self.instance)
        cid = self.root["class_id"]
        if int.from_bytes(self.data[6:8], "little") != cid:
            raise ValueError("Native application header and root Device class disagree.")
        self.header_start = self.root["offset"] + 6
        if int.from_bytes(self.data[self.header_start : self.header_start + 4], "big") != (
            cid << 22 | self.instance
        ):
            raise ValueError("Root object header and Device Object_Identifier disagree.")
        prop = self.root["properties"][75]
        self.value_start, self.value_end = prop["value_start_offset"], prop["value_end_offset"]
        expected = b"\xc4" + ((8 << 22) | self.instance).to_bytes(4, "big") + b"\x2f"
        if self.data[self.value_start : self.value_end] != expected:
            raise ValueError("Device identity has an unsupported native value encoding.")

    def summary(self):
        return {
            "profile": PROFILE,
            "source_sha256": self.source_sha256,
            "native_sha256": sha(self.data),
            "encoding": "gzip-moi-v2" if self.compressed else "moi-v2",
            "root_ref": self.ref,
            "root_class": self.root["class_id"],
            "instance": self.instance,
            "name": self.reader.scalar(self.root, 2390),
            "model": self.reader.scalar(self.root, 70),
            "record_count": len(self.records),
            "format_versions": {
                "acs": self.reader.scalar(self.root, 4128),
                "dmcs": self.reader.scalar(self.root, 4129),
            },
            "vendor_runtime_required": False,
            "controller_write": False,
        }

    def preview(
        self, *, source_sha256, expected_instance, new_instance, expected_name=None, new_name=None
    ):
        number(expected_instance)
        number(new_instance)
        if source_sha256 != self.source_sha256 or expected_instance != self.instance:
            raise ValueError("Native application source or Device instance changed; capture again.")
        edits = []
        if new_name is not None:
            controller_name(new_name)
            if expected_name != self.summary()["name"]:
                raise ValueError("Native application name changed; capture again.")
            if new_instance != self.instance:
                raise ValueError("Review a name-only or instance-only change, not both together.")
            prop = self.root["properties"].get(2390)
            if prop is None:
                raise ValueError("The application does not expose a typed Device name.")
            start, end = prop["value_start_offset"], prop["value_end_offset"]
            pdu = PDUData(self.data[start:end])
            tag = Tag.decode(pdu)
            if not tag.tag_data or tag.tag_data[0] not in (0, 3, 4, 5):
                raise ValueError("Unsupported native Device-name character encoding.")
            original = CharacterString.decode(TagList([tag]))
            replacement = CharacterString(new_name, _encoding=tag.tag_data[0])
            encoded_name = bytes(TagList([*replacement.encode(), ClosingTag(2)]).encode().pduData)
            if str(original) != expected_name or self.data[start:end] != bytes(
                TagList([*original.encode(), ClosingTag(2)]).encode().pduData
            ):
                raise ValueError("Device name does not have a reversible native string encoding.")
            if new_name != expected_name:
                edits.append(
                    {
                        "location": "Device.Object_Name",
                        "native_byte_offset": start,
                        "before": self.data[start:end].hex(),
                        "after": encoded_name.hex(),
                        "native_property": 2390,
                        "character_encoding": tag.tag_data[0],
                    }
                )
        if new_instance != self.instance:
            for location, start, kind in (
                ("root-object-header", self.header_start, self.root["class_id"]),
                ("Device.Object_Identifier", self.value_start + 1, 8),
            ):
                edits.append(
                    {
                        "location": location,
                        "native_byte_offset": start,
                        "before": self.data[start : start + 4].hex(),
                        "after": ((kind << 22) | new_instance).to_bytes(4, "big").hex(),
                    }
                )
        plan = {
            **self.summary(),
            "old_instance": self.instance,
            "new_instance": new_instance,
            "edits": edits,
        }
        if new_name is not None:
            plan.update(old_name=expected_name, new_name=new_name, change_kind="name")
        return {**plan, "plan_sha256": seal(plan)}

    def export(self, *, plan_sha256, **request):
        plan = self.preview(**request)
        if plan_sha256 != plan["plan_sha256"]:
            raise ValueError("Native application review changed; review again.")
        if not plan["edits"]:
            return self.source, {**plan, "output_sha256": self.source_sha256}
        data = bytearray(self.data)
        for edit in sorted(
            plan["edits"], key=lambda edit: edit["native_byte_offset"], reverse=True
        ):
            start = edit["native_byte_offset"]
            data[start : start + len(bytes.fromhex(edit["before"]))] = bytes.fromhex(edit["after"])
        if request.get("new_name") is not None:
            # Only the root property's encoded value can change. Reframe that
            # record if its string length changes; retain every other raw record.
            edit = plan["edits"][0]
            delta = (len(edit["after"]) - len(edit["before"])) // 2
            framed, previous = bytearray(self.data[:14]), 14
            for record in self.records:
                start, end = record["offset"], record["end_offset"]
                if record is self.root:
                    raw = bytes(data[start : end + delta])
                else:
                    shift = delta if start > self.root["offset"] else 0
                    raw = bytes(data[start + shift : end + shift])
                extended = start - previous == 6 or len(raw) + 2 > 65535
                framed.extend(
                    b"\x00\x00" + struct.pack("<I", len(raw) + 6)
                    if extended
                    else struct.pack("<H", len(raw) + 2)
                )
                framed.extend(raw)
                previous = end
            data = framed
        output = bytes(data)
        if self.compressed:
            compressor = zlib.compressobj(level=9, wbits=-15)
            output = (
                self.source[:10]
                + compressor.compress(output)
                + compressor.flush()
                + struct.pack("<II", zlib.crc32(data), len(data))
            )
        actual = MoiIdentity(output)
        if actual.instance != request["new_instance"] or len(actual.records) != len(self.records):
            raise ValueError("Native application identity failed exact output readback.")
        if request.get("new_name") is not None and actual.summary()["name"] != request["new_name"]:
            raise ValueError("Native application name failed exact output readback.")
        return output, {**plan, "output_sha256": sha(output), "native_output_sha256": sha(data)}
