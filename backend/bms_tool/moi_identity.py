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
from bacpypes3.primitivedata import ObjectIdentifier

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

    def preview(self, *, source_sha256, expected_instance, new_instance):
        number(expected_instance)
        number(new_instance)
        if source_sha256 != self.source_sha256 or expected_instance != self.instance:
            raise ValueError("Native application source or Device instance changed; capture again.")
        edits = []
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
        return {**plan, "plan_sha256": seal(plan)}

    def export(self, *, plan_sha256, **request):
        plan = self.preview(**request)
        if plan_sha256 != plan["plan_sha256"]:
            raise ValueError("Native application review changed; review again.")
        if not plan["edits"]:
            return self.source, {**plan, "output_sha256": self.source_sha256}
        data = bytearray(self.data)
        for edit in plan["edits"]:
            start = edit["native_byte_offset"]
            data[start : start + 4] = bytes.fromhex(edit["after"])
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
        return output, {**plan, "output_sha256": sha(output), "native_output_sha256": sha(data)}
