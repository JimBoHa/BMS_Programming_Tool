"""Local typed Enum code copies preserve every unrelated native record byte."""

import struct
import zlib

from .moi_identity import MoiIdentity, seal, sha

PROFILE = "tagged-moi-enum-default-copy/1"
CLASSES = frozenset({528, 529})
SCOPE = (
    "Local archive copy of one existing class 528/529 Enumerated Default Value (3113). "
    "Preserve every unrelated native byte, original value width when sufficient and "
    "all captured enum/state metadata. Code membership and state meanings are not "
    "verified; saved settings are not merged. No controller transfer, force, hardware "
    "edit, semantic conversion, general logic generation or CCT/physical acceptance."
)


class MoiEnumDefaults:
    def __init__(self, source):
        self.editor = MoiIdentity(source)
        if self.editor.reader.errors:
            raise ValueError("Enum copies require unambiguous native records and references.")
        self.candidates = {}
        for record in self.editor.records:
            prop = record["properties"].get(3113)
            if record is self.editor.root or record["class_id"] not in CLASSES or not prop:
                continue
            scalar = prop["scalar"]
            start, end = prop["value_start_offset"], prop["value_end_offset"]
            raw = self.editor.data[start:end]
            width = len(raw) - 2
            if (
                not scalar
                or scalar["datatype"] != "Enumerated"
                or type(scalar["value"]) is not int
                or not 0 <= scalar["value"] <= 4294967295
                or not 1 <= width <= 4
                or raw[0] != 0x90 | width
                or raw[-1] != 0x2F
                or int.from_bytes(raw[1:-1], "big") != scalar["value"]
            ):
                continue
            ref = self.editor.reader.scalar(record, 32527)
            if isinstance(ref, str) and ref in self.editor.reader.records:
                self.candidates[ref] = record, prop

    def preview(self, *, source_sha256, record_ref, encoded_sha256, value):
        app = self.editor
        if type(value) is not int or not 0 <= value <= 4294967295:
            raise ValueError(
                "Use an actual unsigned32 Enum code, not a Boolean, label or coercion."
            )
        if source_sha256 != app.source_sha256:
            raise ValueError("The native Enum source changed; inspect the current original again.")
        if record_ref not in self.candidates:
            raise ValueError("Select an existing class 528/529 Enumerated Default Value.")
        record, prop = self.candidates[record_ref]
        if encoded_sha256 != prop["encoded_sha256"]:
            raise ValueError("The selected native Enum encoding changed; inspect it again.")
        start, end = prop["value_start_offset"], prop["value_end_offset"]
        before = app.data[start:end]
        width = max(len(before) - 2, max(1, (value.bit_length() + 7) // 8))
        after = bytes([0x90 | width]) + value.to_bytes(width, "big") + b"\x2f"
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source_sha256": app.source_sha256,
            "native_source_sha256": sha(app.data),
            "record_ref": record_ref,
            "class_id": record["class_id"],
            "property": 3113,
            "datatype": "Enumerated",
            "encoded_sha256": encoded_sha256,
            "before_value": prop["scalar"]["value"],
            "after_value": value,
            "before_encoding_hex": before.hex(),
            "after_encoding_hex": after.hex(),
            "before_value_width": len(before) - 2,
            "after_value_width": width,
            "changed": value != prop["scalar"]["value"],
            "states_text_evidence": record["properties"].get(931, {}).get("scalar"),
            "enum_semantics_verified": False,
            "controller_write": False,
            "saved_settings_merged": False,
        }
        return {**body, "plan_sha256": seal(body)}

    def export(self, *, plan_sha256, **request):
        plan = self.preview(**request)
        if plan_sha256 != plan["plan_sha256"]:
            raise ValueError("The Enum copy review changed; review the current proposal again.")
        app = self.editor
        if not plan["changed"]:
            return app.source, {
                **plan,
                "output_sha256": app.source_sha256,
                "unrelated_native_bytes_preserved": True,
            }
        selected, prop = self.candidates[request["record_ref"]]
        a, b = prop["value_start_offset"], prop["value_end_offset"]
        data = bytearray(app.data[:14])
        previous = 14
        for record in app.records:
            start, end = record["offset"], record["end_offset"]
            prefix, raw = app.data[previous:start], app.data[start:end]
            if record is selected:
                raw = (
                    app.data[start:a] + bytes.fromhex(plan["after_encoding_hex"]) + app.data[b:end]
                )
                prefix = (
                    b"\x00\x00" + struct.pack("<I", len(raw) + 6)
                    if len(prefix) == 6 or len(raw) + 2 > 65535
                    else struct.pack("<H", len(raw) + 2)
                )
            data.extend(prefix + raw)
            previous = end
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
        if checked.data[:14] != app.data[:14] or len(checked.records) != len(app.records):
            raise ValueError("Native Enum copy changed the application record header or count.")
        old_previous = new_previous = 14
        for before, after in zip(app.records, checked.records, strict=True):
            old_prefix = app.data[old_previous : before["offset"]]
            new_prefix = checked.data[new_previous : after["offset"]]
            old_raw = app.data[before["offset"] : before["end_offset"]]
            new_raw = checked.data[after["offset"] : after["end_offset"]]
            if before is selected:
                current = after["properties"][3113]
                c = current["value_start_offset"] - after["offset"]
                d = current["value_end_offset"] - after["offset"]
                if (
                    current["scalar"] != {"datatype": "Enumerated", "value": request["value"]}
                    or checked.data[
                        current["value_start_offset"] : current["value_end_offset"]
                    ].hex()
                    != plan["after_encoding_hex"]
                ):
                    raise ValueError("Reparsed native Enum code differs from its typed review.")
                new_raw = new_raw[:c] + app.data[a:b] + new_raw[d:]
            elif old_prefix != new_prefix:
                raise ValueError("Native Enum copy changed another record length prefix.")
            if old_raw != new_raw:
                raise ValueError("Native Enum copy changed a non-selected native byte.")
            old_previous, new_previous = before["end_offset"], after["end_offset"]
        return output, {
            **plan,
            "output_sha256": sha(output),
            "unrelated_native_bytes_preserved": True,
        }
