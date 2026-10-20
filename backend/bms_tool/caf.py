"""Loss-preserving inspection and narrow scalar editing of observed JCI CAF ZIP/XML.

The observed XML is not a published JCI interchange specification. Keeping unknown
objects is essential. This adapter does not manufacture firmware or claim native
compiler/device validation. No sample building files are distributed with this code.
"""

from __future__ import annotations

import copy
import hashlib
import html
import io
import json
import lzma
import math
import re
import struct
import zipfile
import zlib
from collections import Counter
from pathlib import Path
from xml.etree.ElementTree import TreeBuilder

from defusedxml import ElementTree as ET
from defusedxml.common import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden

NS = "http://johnsoncontrols.com/MetasysIII/2002/3/Core"
Q = "{" + NS + "}"
MAX_ARCHIVE = 8 * 1024 * 1024
MAX_XML = 32 * 1024 * 1024
MAX_DEPTH = 64
MAX_ELEMENTS = 500000
MAX_XML_NAME = 4096
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


class _BoundedTreeBuilder(TreeBuilder):
    """Bound allocation and retain Expat's actual element positions, not lookalikes."""

    def __init__(self):
        super().__init__()
        self.parser = None
        self.depth, self.count = 0, 0
        self.spans = {}

    def start(self, tag, attrs):
        self.depth += 1
        self.count += 1
        if self.depth > MAX_DEPTH or self.count > MAX_ELEMENTS:
            raise ValueError("CAF XML exceeds depth/element limits.")
        if len(tag) > MAX_XML_NAME or any(len(key) > MAX_XML_NAME for key in attrs):
            raise ValueError("CAF XML name exceeds the 4096-character resource profile.")
        element = super().start(tag, attrs)
        self.spans[id(element)] = [self.parser.CurrentByteIndex, None]
        return element

    def end(self, tag):
        element = super().end(tag)
        self.spans[id(element)][1] = self.parser.CurrentByteIndex
        self.depth -= 1
        return element


class CafArchive:
    def __init__(self, content: bytes):
        if not isinstance(content, bytes) or not content or len(content) > MAX_ARCHIVE:
            raise ValueError("CAF requires 1 byte through the 8 MiB archive limit.")
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
        except (
            zipfile.BadZipFile,
            RuntimeError,
            NotImplementedError,
            OSError,
            EOFError,
            zlib.error,
            lzma.LZMAError,
        ) as exc:
            raise ValueError("CAF must be a valid ZIP/XML container.") from exc
        self.encoding = "utf-8"

        def declaration(version, encoding, standalone):
            self.encoding = (encoding or "utf-8").lower()

        try:
            builder = _BoundedTreeBuilder()
            parser = ET.DefusedXMLParser(
                target=builder, forbid_dtd=True, forbid_entities=True, forbid_external=True
            )
            builder.parser = parser.parser
            parser.parser.XmlDeclHandler = declaration

            def namespace(prefix, uri):
                if len(prefix or "") > MAX_XML_NAME or len(uri or "") > MAX_XML_NAME:
                    raise ValueError(
                        "CAF XML namespace exceeds the 4096-character resource profile."
                    )

            parser.parser.StartNamespaceDeclHandler = namespace
            parser.feed(self.xml)
            self.root = parser.close()
            self._spans = builder.spans
        except (DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden) as exc:
            raise ValueError("XML entities and DTDs are forbidden.") from exc
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Invalid or unsafe CAF XML.") from exc
        try:
            self.xml.decode("utf-8")
            self._patchable_xml = self.encoding in {"utf-8", "utf8", "us-ascii", "ascii"}
        except UnicodeError:
            self._patchable_xml = False
        if self.root.tag != Q + "objects":
            raise ValueError("Unrecognized CAF XML namespace/root.")
        self.objects = {e.get("ref"): e for e in self.root if e.tag == Q + "object"}
        object_entries = [e for e in self.root if e.tag == Q + "object"]
        if len(self.objects) != len(object_entries) or any(not ref for ref in self.objects):
            raise ValueError("CAF contains duplicate/missing object references.")
        for obj in self.objects.values():
            identifiers = set()
            for prop in obj:
                if prop.tag not in {Q + "property", Q + "simulationProperty"}:
                    continue
                pid = prop.get("id", "")
                if not re.fullmatch(r"[0-9]{1,10}", pid) or int(pid) > 4294967295:
                    raise ValueError("CAF property has a missing or invalid native identifier.")
                key = prop.tag, int(pid)
                if key in identifiers:
                    raise ValueError(
                        "CAF object contains duplicate property identifiers of the same kind."
                    )
                identifiers.add(key)
        self.extra_entries = [e.tag.removeprefix(Q) for e in self.root if e.tag != Q + "object"]

    @staticmethod
    def scalar(prop):
        if prop is None:
            return None
        data = prop.findall(Q + "data")
        if (
            len(prop) != 1
            or set(prop.attrib) != {"id"}
            or len(data) != 1
            or data[0].attrib
            or len(data[0]) != 1
            or len(data[0][0])
            or (prop.text or "").strip()
            or (data[0].text or "").strip()
            or (data[0][0].tail or "").strip()
        ):
            return None
        value = data[0][0]
        return {
            "type": value.tag.removeprefix(Q),
            "text": value.text or "",
            "attributes": dict(value.attrib),
        }

    def _editable(self, prop):
        scalar = self.scalar(prop)
        return (
            self._patchable_xml
            and prop.tag == Q + "property"
            and prop.get("id") in EDITABLE
            and set(prop.attrib) == {"id"}
            and len(prop) == 1
            and prop[0].tag == Q + "data"
            and not prop[0].attrib
            and scalar is not None
            and not scalar["attributes"]
            and scalar["type"] in {"string", "float", "boolean", *LIMITS}
        )

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
                "editable": self._editable(p),
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
        props = (
            {p.get("id"): self.scalar(p) for p in first if p.tag == Q + "property"}
            if first is not None
            else {}
        )
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
                "scalar_patch": self._patchable_xml,
                "new_native_program": False,
                "full_logic_simulation": False,
                "native_download": False,
            },
        }

    def patch(self, changes):
        if not isinstance(changes, list):
            raise ValueError("CAF changes must be a list of guarded scalar edits.")
        if not changes:
            return self.original, []
        if len(changes) > 1000:
            raise ValueError("Too many CAF changes.")
        if not self._patchable_xml:
            raise ValueError("CAF scalar editing requires observed UTF-8/ASCII XML serialization.")
        edits, report, seen = [], [], set()
        for change in changes:
            if not isinstance(change, dict) or set(change) != {"ref", "property", "old", "value"}:
                raise ValueError("CAF changes require exactly ref, property, old and value.")
            if (
                not isinstance(change["ref"], str)
                or type(change["property"]) not in (str, int)
                or not isinstance(change["old"], str)
                or type(change["value"]) not in (str, int, float, bool)
            ):
                raise ValueError(
                    "CAF edit identifiers, original text and replacement scalar require explicit types."
                )
            ref, pid = change["ref"], str(change["property"])
            if (ref, pid) in seen:
                raise ValueError("Duplicate CAF change.")
            seen.add((ref, pid))
            if pid not in EDITABLE:
                raise ValueError(
                    "Identity, resource, enum and wiring properties cannot be patched by this adapter."
                )
            if ref not in self.objects:
                raise ValueError("CAF object reference not found.")
            props = [p for p in self.objects[ref] if p.get("id") == pid and p.tag == Q + "property"]
            if len(props) != 1 or not self._editable(props[0]):
                raise ValueError("Property is not an editable scalar.")
            prop = props[0]
            scalar = self.scalar(prop)
            old, kind = scalar["text"], scalar["type"]
            if change["old"] != old:
                raise ValueError("CAF edit conflict: original value no longer matches.")
            value = str(change["value"])
            if kind in LIMITS:
                if not re.fullmatch(r"[-+]?[0-9]+", value):
                    raise ValueError("CAF integer replacement requires a decimal integer.")
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
                if (
                    not isinstance(change["value"], str)
                    or len(value) > 1000
                    or any(
                        c not in "\t\n\r"
                        and not (
                            0x20 <= ord(c) <= 0xD7FF
                            or 0xE000 <= ord(c) <= 0xFFFD
                            or 0x10000 <= ord(c) <= 0x10FFFF
                        )
                        for c in value
                    )
                ):
                    raise ValueError("Invalid CAF string.")
            if str(change["value"]) == old:
                continue
            element = prop[0][0]
            a, b, before, after = self._scalar_span(element)
            escaped = html.escape(value, quote=False).replace("\r", "&#13;")
            encoding = "ascii" if self.encoding in {"ascii", "us-ascii"} else "utf-8"
            edits.append((a, b, before + escaped.encode(encoding, "xmlcharrefreplace") + after))
            report.append({"ref": ref, "property": pid, "type": kind, "old": old, "value": value})
        if not edits:
            return self.original, []
        xml = self.xml
        for a, b, replacement in sorted(edits, reverse=True):
            xml = xml[:a] + replacement + xml[b:]
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.comment = self.comment
            archive.writestr(copy.copy(self.info), xml)
        edited = out.getvalue()
        verified = CafArchive(edited)
        if list(verified.objects) != list(self.objects):
            raise ValueError("CAF object references changed unexpectedly.")
        for row in report:
            matches = [
                p
                for p in verified.objects[row["ref"]]
                if p.tag == Q + "property" and p.get("id") == row["property"]
            ]
            actual = self.scalar(matches[0]) if len(matches) == 1 else None
            if actual is None or actual["type"] != row["type"] or actual["text"] != row["value"]:
                raise ValueError("CAF scalar readback does not match the requested edit.")
        return edited, report

    def _scalar_span(self, element):
        """Splice only an actual parsed leaf, preserving surrounding original bytes."""
        start, closing = self._spans[id(element)]
        quote = None
        for index in range(start, len(self.xml)):
            byte = self.xml[index]
            if quote is not None:
                if byte == quote:
                    quote = None
            elif byte in (34, 39):
                quote = byte
            elif byte == 62:
                opening_end = index + 1
                break
        else:
            raise ValueError("Unrecognized CAF scalar serialization; refusing to rewrite.")
        opening = self.xml[start:opening_end]
        if opening.endswith(b"/>"):
            name = re.match(rb"<([^\s/>]+)", opening)
            if closing != opening_end or name is None:
                raise ValueError("Unrecognized CAF scalar serialization; refusing to rewrite.")
            return start, opening_end, opening[:-2] + b">", b"</" + name[1] + b">"
        if (
            closing < opening_end
            or self.xml[closing : closing + 2] != b"</"
            or b"<" in self.xml[opening_end:closing]
        ):
            raise ValueError(
                "Unrecognized CAF scalar serialization; refusing to rewrite opaque leaf markup."
            )
        return opening_end, closing, b"", b""
