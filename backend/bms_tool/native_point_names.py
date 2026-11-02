"""One existing BACnet point name in a complete native snapshot; no I/O allocation."""

import struct
import zlib

from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import CharacterString, ClosingTag, ObjectIdentifier, Tag, TagList
from pydantic import Field, StrictBool, field_validator

from .application_preservation import runtime_parameter_changes
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_identity import MoiIdentity, controller_name, sha
from .moi_parameters import ParameterApplication

PROFILE = "native-point-name-transfer/1"
SCOPE = (
    "Rename one existing native BACnet value object. Preserve its object identifier, reference, "
    "wires, I/O setup, Device identity and all other fresh merged settings. Backup/readback "
    "enter and end backup mode; Apply transfers File 3 and can interrupt control briefly. "
    "No object creation, supervisor rename, trend/alarm editing or electrical-mode change."
)
POINT_TYPES = {0, 1, 2, 3, 4, 5, 13, 14, 19}


class PointNameEdit(StrictModel):
    object_id: str = Field(min_length=1, max_length=80, strict=True)
    record_ref: str = Field(min_length=1, max_length=512, strict=True)
    encoded_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    new_name: str = Field(min_length=1, max_length=128, strict=True)

    @field_validator("object_id")
    @classmethod
    def point(cls, value):
        oid = ObjectIdentifier(value)
        if int(oid[0]) not in POINT_TYPES or not 0 <= oid[1] <= 4194302:
            raise ValueError("Choose an existing analog, binary or multistate value object.")
        return str(oid)

    @field_validator("new_name")
    @classmethod
    def name(cls, value):
        return controller_name(value)


class PointNameSource(DeviceDetailsRequest):
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PointNamePreview(PointNameEdit, PointNameSource):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class PointNameApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    point_name_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


def replace_name(editor, selected, value):
    """Reframe one record, retaining every other raw record and gzip header."""
    prop = selected["properties"][2390]
    start, end = prop["value_start_offset"], prop["value_end_offset"]
    before = editor.data[start:end]
    tag = Tag.decode(PDUData(before))
    if not tag.tag_data or tag.tag_data[0] not in (0, 3, 4, 5):
        raise ValueError("Unsupported point-name character encoding.")
    original = CharacterString.decode(TagList([tag]))
    if before != bytes(TagList([*original.encode(), ClosingTag(2)]).encode().pduData):
        raise ValueError("Point name lacks a reversible typed string encoding.")
    replacement = CharacterString(controller_name(value), _encoding=tag.tag_data[0])
    after = bytes(TagList([*replacement.encode(), ClosingTag(2)]).encode().pduData)
    data, previous = bytearray(editor.data[:14]), 14
    for record in editor.records:
        a, b = record["offset"], record["end_offset"]
        raw = editor.data[a:b]
        if record is selected:
            raw = editor.data[a:start] + after + editor.data[end:b]
        extended = a - previous == 6 or len(raw) + 2 > 65535
        data.extend(
            b"\x00\x00" + struct.pack("<I", len(raw) + 6)
            if extended
            else struct.pack("<H", len(raw) + 2)
        )
        data.extend(raw)
        previous = b
    output = bytes(data)
    if editor.compressed:
        compressor = zlib.compressobj(level=9, wbits=-15)
        output = (
            editor.source[:10]
            + compressor.compress(output)
            + compressor.flush()
            + struct.pack("<II", zlib.crc32(data), len(data))
        )
    return output, {"before": str(original), "after": value, "character_encoding": tag.tag_data[0]}


class PointNameCompiler:
    def __init__(self, files):
        if set(files) != {3, 11, 12}:
            raise ValueError("Select a complete native File 3/11/12 snapshot.")
        self.merged, self.parameters = ParameterApplication(
            files[3], files[11], files[12]
        ).compile()
        self.editor = MoiIdentity(self.merged)
        original = MoiIdentity(files[3])
        if any(
            self.editor.summary()[k] != original.summary()[k] for k in ("instance", "name", "model")
        ):
            raise ValueError("Saved settings changed Device identity; capture again.")
        self.points = {}
        for record in self.editor.records:
            ref = self.editor.reader.scalar(record, 32527)
            oid = self.editor.reader.scalar(record, 75)
            name = self.editor.reader.scalar(record, 2390)
            if (
                not isinstance(ref, str)
                or "/" not in ref
                or not isinstance(oid, str)
                or not isinstance(name, str)
            ):
                continue
            try:
                obj = ObjectIdentifier(oid)
            except (ValueError, TypeError):
                continue
            if int(obj[0]) not in POINT_TYPES:
                continue
            key = str(obj)
            if key in self.points:
                raise ValueError("Duplicate BACnet point identifiers prevent name matching.")
            self.points[key] = record

    def fields(self):
        return [
            {
                "object_id": key,
                "record_ref": self.editor.reader.scalar(record, 32527),
                "name": self.editor.reader.scalar(record, 2390),
                "encoded_sha256": record["properties"][2390]["encoded_sha256"],
                "native_class": record["class_id"],
            }
            for key, record in sorted(self.points.items())
        ]

    def compile(self, edit):
        edit = PointNameEdit(**edit).model_dump()
        record = self.points.get(edit["object_id"])
        if record is None:
            raise ValueError("This snapshot has no supported native name for that point.")
        if (
            self.editor.reader.scalar(record, 32527) != edit["record_ref"]
            or record["properties"][2390]["encoded_sha256"] != edit["encoded_sha256"]
        ):
            raise ValueError(
                "The selected point reference or name changed; capture and review again."
            )
        old = self.editor.reader.scalar(record, 2390)
        if any(
            row["name"] == edit["new_name"] and row["object_id"] != edit["object_id"]
            for row in self.fields()
        ):
            raise ValueError("Another configured point already uses the proposed name.")
        output, change = replace_name(self.editor, record, edit["new_name"])
        actual = MoiIdentity(output)
        if (
            len(actual.records) != len(self.editor.records)
            or actual.data[:14] != self.editor.data[:14]
        ):
            raise ValueError("Point rename changed the native record inventory.")
        # Compare the payload of every object, including opaque records. Only
        # the selected typed value and its record length prefix may differ.
        for before, after in zip(self.editor.records, actual.records, strict=True):
            expected = self.editor.data[before["offset"] : before["end_offset"]]
            observed = actual.data[after["offset"] : after["end_offset"]]
            if before is record:
                prop, current = before["properties"][2390], after["properties"][2390]
                a, b = (
                    current["value_start_offset"] - after["offset"],
                    current["value_end_offset"] - after["offset"],
                )
                observed = (
                    observed[:a]
                    + self.editor.data[prop["value_start_offset"] : prop["value_end_offset"]]
                    + observed[b:]
                )
                if actual.reader.scalar(after, 2390) != edit["new_name"]:
                    raise ValueError("Compiled native point name differs from the review.")
            if observed != expected:
                raise ValueError("Point rename changed a non-name application byte.")
        return output, {
            "profile": PROFILE,
            "selected_edit": {**edit, **change, "changed": old != edit["new_name"]},
            "parameter_merge": self.parameters,
            "other_merged_bytes_preserved": True,
            "compiled_native_sha256": sha(actual.data),
            "native_record_count": len(actual.records),
        }


def compile_point_name(files, edit):
    return PointNameCompiler(files).compile(edit)


def verify_point_name_preservation(before, after, edit):
    expected, compilation = compile_point_name(before, edit)
    if set(after) != {3, 11, 12} or MoiIdentity(after[3]).data != MoiIdentity(expected).data:
        raise ValueError("Point-name application readback differs from the reviewed image.")
    post = ParameterApplication(after[3], after[11], after[12])
    current, counters, calculated = runtime_parameter_changes(MoiIdentity(after[3]), post)
    return {
        "profile": "native-point-name-preservation/1",
        "application_identical_except_point_name": True,
        "identity_unchanged": True,
        "selected_edit": compilation["selected_edit"],
        "saved_application_parameters_verified": compilation["parameter_merge"][
            "matched_parameters"
        ],
        "post_saved_parameters": current["matched_parameters"],
        "runtime_counter_changes": counters,
        "device_calculated_changes": calculated,
        "controller_writes": False,
    }
