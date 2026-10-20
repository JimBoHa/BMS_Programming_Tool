"""Bounded, loss-explicit BACnet property values for local JSON APIs.

Ordinary finite numeric, text, list and Choice shapes stay compatible with the
point-service API. Protocol Booleans become actual JSON Booleans. Nonfinite,
opaque and integers beyond JavaScript's exact range remain typed evidence.
No proprietary datatype or controller program is guessed from opaque bytes.
"""

from __future__ import annotations

import base64
import hashlib
import math

from bacpypes3.constructeddata import Any, Sequence
from bacpypes3.primitivedata import Boolean, Null, OctetString

MAX_DEPTH = 16
MAX_ITEMS = 4096
MAX_BYTES = 256 * 1024
MAX_OPAQUE_BYTES = 64 * 1024
SAFE_INTEGER = 2**53 - 1


def json_value(value):
    """Convert real BACpypes values without returning object-memory reprs.

    Schema-backed Sequences retain their original field names and optional
    fields remain absent. A BACnet Date/Time tuple keeps its raw field values;
    generic point reads do not infer timezone or invent a device timestamp.
    """
    remaining_items, remaining_bytes, visiting = MAX_ITEMS, MAX_BYTES, set()

    def reserve_bytes(count):
        nonlocal remaining_bytes
        remaining_bytes -= count
        if remaining_bytes < 0:
            raise ValueError("BACnet value exceeds the 256 KiB serialization budget.")

    def encode(current, depth):
        nonlocal remaining_items
        remaining_items -= 1
        if remaining_items < 0:
            raise ValueError("BACnet value exceeds the 4,096-item serialization budget.")
        if depth > MAX_DEPTH:
            raise ValueError("BACnet value exceeds the 16-level serialization depth.")
        if current is None or isinstance(current, Null):
            return None
        if isinstance(current, (Boolean, bool)):
            return bool(current)
        if isinstance(current, int):
            bits = abs(current).bit_length()
            if bits > 4096:
                raise ValueError("BACnet integer exceeds the 4,096-bit serialization profile.")
            if abs(current) > SAFE_INTEGER:
                text = str(int(current))
                reserve_bytes(len(text))
                return {"type": "integer", "encoding": "decimal", "value": text}
            return int(current)
        if isinstance(current, float):
            number = float(current)
            return (
                number
                if math.isfinite(number)
                else {
                    "type": "nonfinite-number",
                    "value": "NaN"
                    if math.isnan(number)
                    else "Infinity"
                    if number > 0
                    else "-Infinity",
                }
            )
        if isinstance(current, str):
            text = str(current)
            reserve_bytes(len(text.encode("utf-8")))
            return text
        if isinstance(current, (OctetString, bytes, bytearray)):
            raw = bytes(current)
            reserve_bytes(len(raw))
            if len(raw) > MAX_OPAQUE_BYTES:
                raise ValueError("BACnet octet string exceeds the 64 KiB serialization profile.")
            return {
                "type": "octet-string",
                "encoding": "base64",
                "value": base64.b64encode(raw).decode("ascii"),
            }
        if id(current) in visiting:
            raise ValueError("BACnet value contains a recursive value reference.")
        visiting.add(id(current))
        try:
            choice = getattr(current, "_choice", None)
            if choice:
                if not isinstance(choice, str):
                    raise ValueError("BACnet Choice selector must be a field name.")
                reserve_bytes(len(choice.encode("utf-8")))
                try:
                    selected = getattr(current, choice)
                except AttributeError as exc:
                    raise ValueError("BACnet Choice selected field is missing.") from exc
                return {"type": choice, "value": encode(selected, depth + 1)}
            if isinstance(current, Any):
                tags = current.tagList
                if tags is None:
                    raise ValueError("BACnet opaque value has no encoded tag list.")
                if len(tags) > remaining_items:
                    raise ValueError("BACnet opaque tag list exceeds the serialization budget.")
                remaining_items -= len(tags)
                # Bound individual tag payloads before allocating encoded data.
                if sum(len(tag.tag_data or b"") for tag in tags) > MAX_OPAQUE_BYTES:
                    raise ValueError(
                        "BACnet opaque value exceeds the 64 KiB serialization profile."
                    )
                raw = bytes(tags.encode().pduData)
                reserve_bytes(len(raw))
                if len(raw) > MAX_OPAQUE_BYTES:
                    raise ValueError(
                        "BACnet opaque value exceeds the 64 KiB serialization profile."
                    )
                return {
                    "type": "bacnet-opaque",
                    "encoded_bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "base64": base64.b64encode(raw[:1024]).decode("ascii"),
                    "truncated": len(raw) > 1024,
                    "meaning": "Encoded BACnet tags; no proprietary semantic interpretation.",
                }
            if isinstance(current, (list, tuple)):
                if len(current) > remaining_items:
                    raise ValueError("BACnet list exceeds the 4,096-item serialization budget.")
                return [encode(item, depth + 1) for item in current]
            if isinstance(current, Sequence):
                result = {}
                for name in current._elements:
                    field = getattr(current, name, None)
                    if field is not None:
                        reserve_bytes(len(name.encode("utf-8")))
                        result[name] = encode(field, depth + 1)
                return result
            if isinstance(current, dict):
                if len(current) > remaining_items:
                    raise ValueError("BACnet mapping exceeds the 4,096-item serialization budget.")
                result = {}
                for name, item in current.items():
                    if not isinstance(name, str):
                        raise ValueError("BACnet mapping keys must be text.")
                    reserve_bytes(len(name.encode("utf-8")))
                    result[str(name)] = encode(item, depth + 1)
                return result
            raise ValueError(
                "Unsupported BACnet value datatype: "
                + type(current).__module__
                + "."
                + type(current).__name__
                + "; no value was converted."
            )
        finally:
            visiting.remove(id(current))

    return encode(value, 0)
