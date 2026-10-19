"""Loss-preserving inspection and narrow scalar editing of observed JCI CAF ZIP/XML.

The observed XML is not a published JCI interchange specification. Keeping unknown
objects is essential. This adapter does not manufacture firmware or claim native
compiler/device validation. No sample building files are distributed with this code.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import math
import re
import struct
import zipfile
from collections import Counter
from pathlib import Path

from defusedxml import ElementTree as ET

NS = "http://johnsoncontrols.com/MetasysIII/2002/3/Core"
Q = "{" + NS + "}"
MAX_ARCHIVE = 8 * 1024 * 1024
MAX_XML = 32 * 1024 * 1024
EDITABLE = {
    "28": "Description",
    "2390": "Name",
    "3113": "Stored numeric value (meaning depends on object class)",
}
DATA = Path(__file__).parent / "data"
ATTRIBUTES = json.loads((DATA / "metasysAttributeNames.json").read_text())
BY_CLASS = json.loads((DATA / "metasysAttributeNamesByClass.json").read_text())
CLASSES = json.loads((DATA / "jciClasses.json").read_text())
LIMITS = {
    "short": (-32768, 32767),
    "unsignedByte": (0, 255),
    "unsignedShort": (0, 65535),
    "unsignedLong": (0, 4294967295),
}


class CafArchive:
    def __init__(self, content: bytes):
        if len(content) > MAX_ARCHIVE:
            raise ValueError("CAF exceeds 8 MiB archive limit.")
        self.original = content
        self.hash = hashlib.sha256(content).hexdigest()
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                infos = z.infolist()
                if len(infos) != 1:
                    raise ValueError(
                        "Only the observed single-XML CAF container is supported; no entries will be silently discarded."
                    )
                self.info = infos[0]
                if self.info.flag_bits & 1:
                    raise ValueError("Encrypted CAF archives are not supported.")
                if not self.info.filename.lower().endswith(".xml") or self.info.file_size > MAX_XML:
                    raise ValueError("CAF requires one XML entry under 32 MiB.")
                self.xml = z.read(self.info)
                self.comment = z.comment
        except zipfile.BadZipFile as exc:
            raise ValueError("CAF must be a valid ZIP/XML container.") from exc
        if b"<!DOCTYPE" in self.xml.upper() or b"<!ENTITY" in self.xml.upper():
            raise ValueError("XML entities and DTDs are forbidden.")
        try:
            self.root = ET.fromstring(self.xml)
        except Exception as exc:
            raise ValueError("Invalid or unsafe CAF XML: " + str(exc)) from exc
        if self.root.tag != Q + "objects":
            raise ValueError("Unrecognized CAF XML namespace/root.")
        self.objects = {e.get("ref"): e for e in self.root if e.tag == Q + "object"}
        object_entries = [e for e in self.root if e.tag == Q + "object"]
        if len(self.objects) != len(object_entries) or None in self.objects:
            raise ValueError("CAF contains duplicate/missing object references.")
        self.extra_entries = [e.tag.removeprefix(Q) for e in self.root if e.tag != Q + "object"]

    @staticmethod
    def scalar(prop):
        data = prop.find(Q + "data")
        if data is None or len(data) != 1 or len(data[0]):
            return None
        value = data[0]
        return {
            "type": value.tag.removeprefix(Q),
            "text": value.text or "",
            "attributes": dict(value.attrib),
        }

    def properties(self, ref):
        if ref not in self.objects:
            raise ValueError("CAF object reference not found.")
        obj = self.objects[ref]
        return [
            {
                "id": p.get("id"),
                "kind": p.tag.removeprefix(Q),
                "name": BY_CLASS.get(obj.get("classid"), {}).get(
                    p.get("id"), ATTRIBUTES.get(p.get("id"), "Unmapped property")
                ),
                "scalar": self.scalar(p),
                "xml": ET.tostring(p, encoding="unicode") if self.scalar(p) is None else None,
                "editable": p.tag == Q + "property"
                and p.get("id") in EDITABLE
                and self.scalar(p) is not None
                and self.scalar(p)["type"]
                in (
                    "string",
                    "float",
                    "short",
                    "unsignedByte",
                    "unsignedShort",
                    "unsignedLong",
                    "boolean",
                ),
            }
            for p in self.objects[ref]
        ]

    def inventory(self, query=""):
        rows = []
        for ref, obj in self.objects.items():
            props = {p.get("id"): self.scalar(p) for p in obj if p.tag == Q + "property"}

            def text(key, properties=props):
                return (properties.get(key) or {}).get("text", "")

            row = {
                "ref": ref,
                "class_id": obj.get("classid"),
                "class_version": obj.get("classVersion"),
                "object_id": obj.get("objectid"),
                "class_name": CLASSES.get(obj.get("classid"), {}).get("name", "Unknown class"),
                "name": text("2390"),
                "description": text("28"),
                "properties": len(obj),
                "stored_value": text("3113"),
            }
            if not query or query.casefold() in " ".join(str(v) for v in row.values()).casefold():
                rows.append(row)
        return rows

    def summary(self):
        first = next(iter(self.objects.values()), None)
        props = {p.get("id"): self.scalar(p) for p in first} if first is not None else {}
        return {
            "sha256": self.hash,
            "entry": self.info.filename,
            "xml_bytes": len(self.xml),
            "objects": len(self.objects),
            "model": (props.get("70") or {}).get("text", ""),
            "release_mode": (props.get("12") or {}).get("text", ""),
            "classes": dict(Counter(e.get("classid") for e in self.objects.values())),
            "preserved_root_metadata": self.extra_entries,
            "validation": "Container/XML validated. Opening edited output in the matching licensed CCT/PCT and downloading to hardware remain unverified.",
            "capabilities": {
                "inspect": True,
                "unchanged_byte_exact_export": True,
                "scalar_patch": True,
                "new_native_program": False,
                "full_logic_simulation": False,
                "native_download": False,
            },
        }

    def patch(self, changes):
        if not changes:
            return self.original, []
        if len(changes) > 1000:
            raise ValueError("Too many CAF changes.")
        xml = self.xml
        report = []
        seen = set()
        for change in changes:
            if set(change) != {"ref", "property", "old", "value"}:
                raise ValueError("CAF changes require exactly ref, property, old and value.")
            ref, pid = change["ref"], str(change["property"])
            if (ref, pid) in seen:
                raise ValueError("Duplicate CAF change.")
            seen.add((ref, pid))
            if pid not in EDITABLE:
                raise ValueError(
                    "Identity, resource, enum and wiring properties cannot be patched by this adapter."
                )
            props = [p for p in self.properties(ref) if p["id"] == pid and p["kind"] == "property"]
            if len(props) != 1 or not props[0]["editable"]:
                raise ValueError("Property is not an editable scalar.")
            scalar = props[0]["scalar"]
            old = scalar["text"]
            kind = scalar["type"]
            if str(change["old"]) != old:
                raise ValueError("CAF edit conflict: original value no longer matches.")
            value = str(change["value"])
            if kind in LIMITS:
                number = int(value)
                low, high = LIMITS[kind]
                if not low <= number <= high:
                    raise ValueError("Integer outside CAF type range.")
                value = str(number)
            elif kind == "float":
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError("CAF floating-point value must be finite.")
                try:
                    encoded = struct.unpack(">f", struct.pack(">f", number))[0]
                except OverflowError as exc:
                    raise ValueError("CAF value exceeds its 32-bit floating-point range.") from exc
                if number != 0 and encoded == 0:
                    raise ValueError("CAF value underflows its 32-bit floating-point range.")
                value = format(number, ".9g")
            elif kind == "boolean":
                if value not in ("0", "1"):
                    raise ValueError("CAF booleans use 0 or 1.")
            elif kind == "string":
                if len(value) > 1000 or any(ord(c) < 32 and c not in "\t\n\r" for c in value):
                    raise ValueError("Invalid CAF string.")
            # Locate the exact object and scalar text in original UTF-8 bytes. Preserve
            # namespaces, attribute order, floating-point spellings, and every other byte.
            spans = []
            for start in re.finditer(rb"<object\b[^>]*>", xml):
                attrs = start.group().decode("utf-8")
                found = re.search(r'\bref="([^"]*)"', attrs)
                if found and html.unescape(found.group(1)) == ref:
                    end = xml.find(b"</object>", start.end())
                    if end < 0:
                        raise ValueError("Cannot locate CAF object boundary.")
                    spans.append((start.start(), end + len(b"</object>")))
            if len(spans) != 1:
                raise ValueError("Unrecognized CAF XML serialization; refusing to rewrite.")
            a, b = spans[0]
            section = xml[a:b]
            pat = (
                rb'(<property\s+id="'
                + pid.encode()
                + rb'"\s*>\s*<data>\s*)<'
                + kind.encode()
                + rb"(?:\s*/>|>([^<]*)</"
                + kind.encode()
                + rb">)"
            )
            matches = list(re.finditer(pat, section))
            if len(matches) != 1:
                raise ValueError("Unrecognized CAF scalar serialization; refusing to rewrite.")
            m = matches[0]
            if html.unescape((m.group(2) or b"").decode("utf-8")) != old:
                raise ValueError("CAF scalar representation mismatch.")
            replacement = (
                m.group(1)
                + b"<"
                + kind.encode()
                + b">"
                + html.escape(value, quote=False).encode("utf-8")
                + b"</"
                + kind.encode()
                + b">"
            )
            section = section[: m.start()] + replacement + section[m.end() :]
            xml = xml[:a] + section + xml[b:]
            report.append({"ref": ref, "property": pid, "type": kind, "old": old, "value": value})
        ET.fromstring(xml)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.comment = self.comment
            z.writestr(self.info, xml)
        edited = out.getvalue()
        verified = CafArchive(edited)
        if len(verified.objects) != len(self.objects):
            raise ValueError("CAF object count changed unexpectedly.")
        return edited, report
