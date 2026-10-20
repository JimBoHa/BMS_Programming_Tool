"""Archive-bound editing of observed native CAF saved simulation values.

This module changes existing simulationProperty records only. It neither runs
JCI logic nor changes the ordinary property with the same native identifier.
Unknown types, enum domains and unobserved class versions remain read-only.
"""

from __future__ import annotations

import copy
import io
import json
import math
import re
import struct
import zipfile
from collections import Counter
from decimal import Decimal

from .caf import CLASSES, CafArchive, Q

FORMAT = "bms.caf-simulation-profile"
VERSION = 1
MAX_RECORDS = 10000
MAX_PROFILE_BYTES = 2 * 1024 * 1024
VALIDATION = (
    "Offline native saved simulation values only. JCI execution, startup behavior, "
    "CCT/PCT acceptance and controller transfer remain unverified."
)
OBSERVED = {("526", "float"), ("527", "float"), ("530", "boolean")}
DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def _value(text: str, kind: str) -> str:
    """Validate a native scalar spelling and preserve that exact spelling."""
    if not isinstance(text, str) or len(text) > 128:
        raise ValueError("Simulation values require native scalar text under 129 characters.")
    if kind == "boolean":
        if text not in {"0", "1", "false", "true"}:
            raise ValueError("Simulation booleans require 0, 1, false or true.")
    elif kind == "float":
        value = text.strip(" \t\r\n")
        if not DECIMAL.fullmatch(value):
            raise ValueError("Simulation floats require finite decimal native text.")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Simulation floats require finite decimal native text.")
        try:
            rounded = struct.unpack(">f", struct.pack(">f", number))[0]
        except OverflowError as exc:
            raise ValueError("Simulation value exceeds the native float32 range.") from exc
        if Decimal(value) != 0 and rounded == 0:
            raise ValueError("Simulation value underflows the native float32 range.")
    else:
        raise ValueError("The native simulation scalar type is read-only.")
    return text


class CafSimulationProfile:
    """Export and apply a complete, exact-source profile without creating objects."""

    def __init__(self, content: bytes | CafArchive):
        self.archive = content if isinstance(content, CafArchive) else CafArchive(content)

    def _records(self) -> list[dict]:
        rows = []
        # Reserve space for the profile header, separators and the API wrapper.
        size = 1024
        for ref, obj in self.archive.objects.items():
            names = [p for p in obj if p.tag == Q + "property" and p.get("id") == "2390"]
            name = self.archive.scalar(names[0]) if len(names) == 1 else None
            for prop in obj:
                if prop.tag != Q + "simulationProperty":
                    continue
                if len(rows) >= MAX_RECORDS:
                    raise ValueError("CAF exceeds the 10000-record simulation profile limit.")
                scalar = self.archive.scalar(prop)
                kind = (scalar or {}).get("type")
                reason = "Unobserved native simulation representation; preserved read-only."
                editable = False
                if kind == "enum":
                    reason = "Matching release-specific enum domain is unavailable; read-only."
                elif (
                    self.archive._patchable_xml
                    and prop.get("id") == "3113"
                    and obj.get("classVersion") == "1.0"
                    and (obj.get("classid"), kind) in OBSERVED
                    and not scalar["attributes"]
                ):
                    try:
                        _value(scalar["text"], kind)
                        self.archive._scalar_span(prop[0][0])
                    except ValueError as exc:
                        reason = str(exc)
                    else:
                        editable = True
                        reason = "Observed existing native simulation scalar; guarded offline edit."
                elif not self.archive._patchable_xml:
                    reason = "Editing requires observed UTF-8/ASCII XML serialization."
                old = (scalar or {}).get("text")
                row = {
                    "ref": ref,
                    "class_id": obj.get("classid"),
                    "class_version": obj.get("classVersion"),
                    "class_name": CLASSES.get(obj.get("classid"), {}).get("name", "Unknown class"),
                    "name": (name or {}).get("text", ""),
                    "property_id": prop.get("id"),
                    "kind": "simulationProperty",
                    "native_type": kind,
                    "attributes": (scalar or {}).get("attributes"),
                    "old": old,
                    "value": old,
                    "editable": editable,
                    "reason": reason,
                }
                # Refuse a single huge scalar before serializing duplicate old/value text.
                if any(
                    len(value) > MAX_PROFILE_BYTES
                    for value in row.values()
                    if isinstance(value, str)
                ):
                    raise ValueError("CAF simulation profile exceeds the 2 MiB serialized limit.")
                size += (
                    len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                    + 1
                )
                if size > MAX_PROFILE_BYTES:
                    raise ValueError("CAF simulation profile exceeds the 2 MiB serialized limit.")
                rows.append(row)
        return rows

    def summary(self) -> dict:
        rows = self._records()
        return {
            "sha256": self.archive.hash,
            "records": rows,
            "counts": {
                "total": len(rows),
                "editable": sum(row["editable"] for row in rows),
                "read_only": sum(not row["editable"] for row in rows),
                "types": dict(Counter(row["native_type"] or "opaque" for row in rows)),
            },
            "validation": VALIDATION,
        }

    def export_profile(self) -> dict:
        return {
            "format": FORMAT,
            "version": VERSION,
            "source_sha256": self.archive.hash,
            "entries": self._records(),
        }

    def apply(self, profile: dict) -> tuple[bytes, list[dict]]:
        if (
            not isinstance(profile, dict)
            or set(profile) != {"format", "version", "source_sha256", "entries"}
            or profile["format"] != FORMAT
            or type(profile["version"]) is not int
            or profile["version"] != VERSION
            or not isinstance(profile["source_sha256"], str)
            or profile["source_sha256"] != self.archive.hash
        ):
            raise ValueError("Simulation profile format, version or source SHA-256 does not match.")
        try:
            encoded_size = len(
                json.dumps(
                    profile, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                ).encode("utf-8")
            )
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError("Simulation profile must contain bounded JSON values.") from exc
        if encoded_size + 1024 > MAX_PROFILE_BYTES:
            raise ValueError("CAF simulation profile exceeds the 2 MiB serialized limit.")
        rows = self._records()
        entries = profile["entries"]
        if not isinstance(entries, list) or len(entries) != len(rows):
            raise ValueError("Simulation profile must contain every original record exactly once.")
        expected = {(row["ref"], row["property_id"]): row for row in rows}
        seen, edits, report = set(), [], []
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("ref"), str)
                or not isinstance(entry.get("property_id"), str)
            ):
                raise ValueError("Simulation profile requires explicit native record identities.")
            key = entry["ref"], entry["property_id"]
            old = expected.get(key)
            if key in seen or old is None:
                raise ValueError("Simulation profile has duplicate or unknown native records.")
            seen.add(key)
            if set(entry) != set(old) or any(
                entry[field] != old[field] or type(entry[field]) is not type(old[field])
                for field in old
                if field != "value"
            ):
                raise ValueError(
                    "Simulation profile identity, native type or old-value guard changed."
                )
            if entry["value"] == old["old"] and type(entry["value"]) is type(old["old"]):
                continue
            if not old["editable"]:
                raise ValueError("Simulation profile attempted to edit a read-only native record.")
            value = _value(entry["value"], old["native_type"])
            prop = next(
                p
                for p in self.archive.objects[key[0]]
                if p.tag == Q + "simulationProperty" and p.get("id") == key[1]
            )
            start, end, before, after = self.archive._scalar_span(prop[0][0])
            # Values contain only validated native numeric/boolean text and XML whitespace.
            encoded = value.replace("\r", "&#13;").encode("ascii")
            edits.append((start, end, before + encoded + after))
            report.append(
                {
                    "ref": key[0],
                    "property_id": key[1],
                    "kind": "simulationProperty",
                    "native_type": old["native_type"],
                    "old": old["old"],
                    "value": value,
                    "validation": VALIDATION,
                }
            )
        if not edits:
            return self.archive.original, []
        xml = self.archive.xml
        for start, end, replacement in sorted(edits, reverse=True):
            xml = xml[:start] + replacement + xml[end:]
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.comment = self.archive.comment
            archive.writestr(copy.copy(self.archive.info), xml)
        result = output.getvalue()
        verified = CafSimulationProfile(result)
        if list(verified.archive.objects) != list(self.archive.objects):
            raise ValueError("CAF object identities changed during simulation profile editing.")
        actual = {(row["ref"], row["property_id"]): row for row in verified.summary()["records"]}
        for row in report:
            readback = actual.get((row["ref"], row["property_id"]))
            if (
                readback is None
                or readback["native_type"] != row["native_type"]
                or readback["old"] != row["value"]
                or not readback["editable"]
            ):
                raise ValueError("Native simulation value readback does not match the profile.")
        return result, report
