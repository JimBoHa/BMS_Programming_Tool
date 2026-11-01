"""Fixed-width local copies of existing native Boolean signal defaults."""

import struct
import zlib

from .moi_identity import MoiIdentity, seal, sha

PROFILE = "tagged-moi-boolean-default-copy/1"
CLASSES = frozenset({530, 531})
SCOPE = (
    "Local archive copy of one existing class 530/531 Boolean Default Value (3113). "
    "Only its canonical Boolean application-tag byte changes. Saved settings are not "
    "merged. No controller transfer, force, hardware edit, general logic generation "
    "or CCT/physical acceptance is established."
)


class MoiBooleanDefaults:
    def __init__(self, source):
        self.editor = MoiIdentity(source)
        if self.editor.reader.errors:
            raise ValueError("Boolean copies require unambiguous native records and references.")
        self.candidates = {}
        for record in self.editor.records:
            prop = record["properties"].get(3113)
            if record["class_id"] not in CLASSES or not prop:
                continue
            scalar = prop["scalar"]
            start, end = prop["value_start_offset"], prop["value_end_offset"]
            if (
                not scalar
                or scalar["datatype"] != "Boolean"
                or type(scalar["value"]) is not bool
                or self.editor.data[start:end] not in (b"\x10\x2f", b"\x11\x2f")
            ):
                continue
            ref = self.editor.reader.scalar(record, 32527)
            if isinstance(ref, str) and ref in self.editor.reader.records:
                self.candidates[ref] = (record, prop)

    def preview(self, *, source_sha256, record_ref, encoded_sha256, value):
        app = self.editor
        if type(value) is not bool:
            raise ValueError("Choose an explicit Boolean true or false.")
        if source_sha256 != app.source_sha256:
            raise ValueError("The native archive changed; inspect the current source again.")
        if record_ref not in self.candidates:
            raise ValueError("Select an existing supported native Boolean signal default.")
        record, prop = self.candidates[record_ref]
        if encoded_sha256 != prop["encoded_sha256"]:
            raise ValueError("The recorded Boolean encoding changed; inspect it again.")
        offset = prop["value_start_offset"]
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source_sha256": app.source_sha256,
            "native_source_sha256": sha(app.data),
            "record_ref": record_ref,
            "class_id": record["class_id"],
            "property": 3113,
            "datatype": "Boolean",
            "encoded_sha256": encoded_sha256,
            "before_value": prop["scalar"]["value"],
            "after_value": value,
            "native_byte_offset": offset,
            "before_tag": app.data[offset : offset + 1].hex(),
            "after_tag": "11" if value else "10",
            "changed": value != prop["scalar"]["value"],
            "controller_write": False,
            "saved_settings_merged": False,
        }
        return {**body, "plan_sha256": seal(body)}

    def export(self, *, plan_sha256, **request):
        plan = self.preview(**request)
        if plan_sha256 != plan["plan_sha256"]:
            raise ValueError("The Boolean copy review changed; review the current proposal again.")
        app = self.editor
        if not plan["changed"]:
            return app.source, {**plan, "output_sha256": app.source_sha256}
        offset = plan["native_byte_offset"]
        data = bytearray(app.data)
        data[offset] = 0x11 if plan["after_value"] else 0x10
        native = bytes(data)
        if app.compressed:
            compressor = zlib.compressobj(level=9, wbits=-15)
            output = (
                app.source[:10]
                + compressor.compress(native)
                + compressor.flush()
                + struct.pack("<II", zlib.crc32(native), len(native))
            )
        else:
            output = native
        checked = MoiIdentity(output)
        if (
            checked.instance != app.instance
            or len(checked.records) != len(app.records)
            or checked.data[:offset] != app.data[:offset]
            or checked.data[offset + 1 :] != app.data[offset + 1 :]
            or checked.data[offset : offset + 1].hex() != plan["after_tag"]
        ):
            raise ValueError("Native Boolean output failed the exact one-byte preservation check.")
        return output, {**plan, "output_sha256": sha(output)}
