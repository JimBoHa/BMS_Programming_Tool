"""Offline fixed-width Real defaults in existing native signal records.

Only the four existing value bytes change. This profile does not establish
controller writability, saved-storage behavior or CCT/firmware acceptance.
"""

import math
import re
import struct
import zlib
from decimal import Decimal, InvalidOperation

from .moi_identity import MoiIdentity, seal, sha

PROFILE = "tagged-moi-signal-default-copy/1"
CLASSES = frozenset({526, 527})
PROPERTY = 3113
DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
SCOPE = (
    "Local file copies of existing Input Float/Output Float Real Default Value fields only. "
    "No controller write, saved-parameter edit, general logic generation or CCT/physical acceptance."
)


def encoded_value(text):
    if (
        not isinstance(text, str)
        or not 1 <= len(text) <= 128
        or not DECIMAL.fullmatch(text.strip())
    ):
        raise ValueError("Use finite decimal text of at most 128 characters.")
    try:
        decimal = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("The proposed decimal exponent is outside the supported range.") from exc
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("The proposed value is outside the finite numeric range.")
    try:
        encoded = struct.pack(">f", value)
    except OverflowError as exc:
        raise ValueError("The proposed value exceeds the native Real float32 range.") from exc
    actual = struct.unpack(">f", encoded)[0]
    if not math.isfinite(actual) or (decimal != 0 and actual == 0):
        raise ValueError("The proposed value overflows or underflows the native Real range.")
    return encoded, actual


class MoiSignalDefaults:
    def __init__(self, source):
        self.editor = MoiIdentity(source)
        if self.editor.reader.errors:
            raise ValueError("Signal copies require unambiguous native records and references.")
        self.candidates = {}
        for record in self.editor.records:
            prop = record["properties"].get(PROPERTY)
            if record["class_id"] not in CLASSES or not prop:
                continue
            scalar = prop["scalar"]
            if not scalar or scalar["datatype"] != "Real":
                continue
            start, end = prop["value_start_offset"], prop["value_end_offset"]
            if (
                self.editor.data[start:end][:1] != b"\x44"
                or end - start != 6
                or self.editor.data[end - 1] != 0x2F
            ):
                continue
            ref = self.editor.reader.scalar(record, 32527)
            if isinstance(ref, str) and ref in self.editor.reader.records:
                self.candidates[ref] = (record, prop)

    def capabilities(self):
        return {
            "profile": PROFILE,
            "available": bool(self.candidates),
            "candidate_count": len(self.candidates),
            "candidate_refs": sorted(self.candidates),
            "classes": sorted(CLASSES),
            "property": PROPERTY,
            "datatype": "Real",
            "scope": SCOPE,
            "controller_write": False,
        }

    def preview(self, *, source_sha256, record_ref, encoded_sha256, value_text):
        app = self.editor
        if source_sha256 != app.source_sha256:
            raise ValueError("The native source changed; review the current capture.")
        if record_ref not in self.candidates:
            raise ValueError("Select an existing supported native signal Real default.")
        record, prop = self.candidates[record_ref]
        if encoded_sha256 != prop["encoded_sha256"]:
            raise ValueError("The recorded property encoding changed; inspect and review again.")
        payload, actual = encoded_value(value_text)
        start = prop["value_start_offset"] + 1
        before = app.data[start : start + 4]
        plan = {
            "profile": PROFILE,
            "source_sha256": app.source_sha256,
            "native_source_sha256": sha(app.data),
            "record_ref": record_ref,
            "class_id": record["class_id"],
            "property": PROPERTY,
            "encoded_sha256": encoded_sha256,
            "value_text": value_text,
            "before_value": prop["scalar"]["value"],
            "stored_value": actual,
            "before_bits": before.hex(),
            "after_bits": payload.hex(),
            "native_byte_offset": start,
            "changed": before != payload,
            "numeric_policy": "Strict decimal text → finite binary64 → IEEE binary32; rounded stored value and bits are reviewed explicitly.",
            "decimal_precision_changed": Decimal(value_text) != Decimal.from_float(actual),
            "controller_write": False,
            "scope": SCOPE,
        }
        return {**plan, "plan_sha256": seal(plan)}

    def export(self, *, plan_sha256, **request):
        plan = self.preview(**request)
        if plan_sha256 != plan["plan_sha256"]:
            raise ValueError("The local file review changed; review again before saving a copy.")
        app = self.editor
        if not plan["changed"]:
            return app.source, {
                **plan,
                "output_sha256": app.source_sha256,
                "native_output_sha256": sha(app.data),
            }
        data = bytearray(app.data)
        offset = plan["native_byte_offset"]
        data[offset : offset + 4] = bytes.fromhex(plan["after_bits"])
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
            or checked.data[offset + 4 :] != app.data[offset + 4 :]
            or checked.data[offset : offset + 4].hex() != plan["after_bits"]
        ):
            raise ValueError("Native output failed the exact four-byte preservation check.")
        return output, {**plan, "output_sha256": sha(output), "native_output_sha256": sha(native)}
