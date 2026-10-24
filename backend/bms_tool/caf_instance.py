"""Guarded CAF Device identity edits, preserving the rest of the native archive.

The native CCT CAF update changes the root Device's property 75 BACoid value
and objectid attribute together. Internal refs, peers, points, I/O and logic
remain unchanged. Preparing a file does not transfer it to a controller.
"""

import copy
import hashlib
import io
import json
import re
import zipfile

from pydantic import Field

from .caf import CafArchive, Q
from .models import StrictModel

PROFILE = "native-caf-device-instance/1"


class CafInstanceChange(StrictModel):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_instance: int = Field(ge=0, le=4194302, strict=True)
    new_instance: int = Field(ge=0, le=4194302, strict=True)


class CafInstanceExport(CafInstanceChange):
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def instance(text):
    if not isinstance(text, str) or not re.fullmatch(r"0|[1-9][0-9]{0,6}", text):
        raise ValueError("CAF Device instance requires a canonical decimal integer.")
    number = int(text)
    if number > 4194302:
        raise ValueError("CAF Device instance is outside 0–4194302.")
    return number


class CafInstanceEditor:
    def __init__(self, caf: CafArchive):
        self.caf = caf
        roots = []
        for ref, obj in caf.objects.items():
            if "/" in ref:
                continue
            props = [p for p in obj if p.tag == Q + "property" and int(p.get("id")) == 75]
            scalar = caf.scalar(props[0]) if len(props) == 1 else None
            if scalar and scalar["type"] == "BACoid" and scalar["attributes"] == {"id": "8"}:
                roots.append((ref, obj, props[0], scalar))
        if len(roots) != 1:
            raise ValueError("CAF instance editing requires one unambiguous root Device BACoid.")
        self.ref, self.root, self.prop, scalar = roots[0]
        self.current = instance(scalar["text"])
        if instance(self.root.get("objectid")) != self.current:
            raise ValueError("CAF root objectid and Device BACoid are inconsistent.")
        if any(ref != self.ref and not ref.startswith(self.ref + "/") for ref in caf.objects):
            raise ValueError("CAF contains objects outside the selected controller root.")

    def _text(self, pid):
        props = [p for p in self.root if p.tag == Q + "property" and int(p.get("id")) == pid]
        scalar = self.caf.scalar(props[0]) if len(props) == 1 else None
        if scalar and scalar["type"] == "string" and not scalar["attributes"]:
            return scalar["text"]
        return None

    def summary(self):
        return {
            "profile": PROFILE,
            "source_sha256": self.caf.hash,
            "root_ref": self.ref,
            "instance": self.current,
            "model": self._text(70),
            "application_version": self._text(12),
            "name": self._text(2390) or self._text(77),
            "offline_only": True,
            "controller_write": False,
        }

    def _attribute_span(self):
        """Lex the actual parsed start tag, skipping quoted attribute contents.

        A text search could otherwise edit an objectid lookalike inside another
        attribute's value. Expat supplies the real element's byte position.
        """
        xml = self.caf.xml
        start = self.caf._spans[id(self.root)][0]
        limit = min(len(xml), start + 16384)
        cursor = start + 1
        whitespace = b" \t\r\n"
        while cursor < limit and xml[cursor] not in whitespace + b">/":
            cursor += 1
        found = []
        while cursor < limit:
            while cursor < limit and xml[cursor] in whitespace:
                cursor += 1
            if cursor < limit and xml[cursor] == 62:
                break
            name_start = cursor
            while cursor < limit and xml[cursor] not in whitespace + b"=/>\"'":
                cursor += 1
            name = xml[name_start:cursor]
            while cursor < limit and xml[cursor] in whitespace:
                cursor += 1
            if cursor >= limit or xml[cursor] != 61:
                raise ValueError("Unsupported CAF root attribute serialization.")
            cursor += 1
            while cursor < limit and xml[cursor] in whitespace:
                cursor += 1
            if cursor >= limit or xml[cursor] not in (34, 39):
                raise ValueError("Unsupported CAF root attribute quoting.")
            quote = xml[cursor]
            begin = cursor + 1
            end = xml.find(bytes([quote]), begin, limit)
            if end < 0:
                raise ValueError("CAF root start tag exceeds the editing profile.")
            if name == b"objectid":
                if xml[begin:end] != str(self.current).encode("ascii"):
                    raise ValueError("CAF objectid is not a plain canonical decimal attribute.")
                found.append((begin, end))
            cursor = end + 1
        else:
            raise ValueError("CAF root start tag exceeds the editing profile.")
        if len(found) != 1:
            raise ValueError("CAF root objectid attribute is unavailable or ambiguous.")
        return found[0]

    def _edits(self, new):
        if not self.caf._patchable_xml:
            raise ValueError("CAF identity editing requires UTF-8 or ASCII XML.")
        a, b, prefix, suffix = self.caf._scalar_span(self.prop[0][0])
        c, d = self._attribute_span()
        value = str(new).encode("ascii")
        return [(a, b, prefix + value + suffix), (c, d, value)]

    def preview(self, request):
        request = CafInstanceChange.model_validate(request)
        if request.source_sha256 != self.caf.hash or request.expected_instance != self.current:
            raise ValueError(
                "CAF source or current instance changed; review the original archive again."
            )
        self._edits(request.new_instance)
        plan = {
            **self.summary(),
            "old_instance": self.current,
            "new_instance": request.new_instance,
            "changes": []
            if request.new_instance == self.current
            else [
                {
                    "ref": self.ref,
                    "location": "property/75/data/BACoid[@id=8]",
                    "old": self.current,
                    "value": request.new_instance,
                },
                {
                    "ref": self.ref,
                    "location": "@objectid",
                    "old": self.current,
                    "value": request.new_instance,
                },
            ],
            "unchanged": [
                "internal object references",
                "controller model and release",
                "I/O and expansion configuration",
                "logic and parameters",
                "peer and supervisor references",
                "unknown archive data",
            ],
            "transfer_required": request.new_instance != self.current,
        }
        return {**plan, "plan_sha256": digest(plan)}

    def export(self, request):
        request = CafInstanceExport.model_validate(request)
        plan = self.preview(request.model_dump(exclude={"plan_sha256"}))
        if plan["plan_sha256"] != request.plan_sha256:
            raise ValueError("CAF instance plan changed; review the exact proposal again.")
        if not plan["changes"]:
            return self.caf.original, {**plan, "output_sha256": self.caf.hash}
        xml = self.caf.xml
        for start, end, replacement in sorted(self._edits(request.new_instance), reverse=True):
            xml = xml[:start] + replacement + xml[end:]
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.comment = self.caf.comment
            archive.writestr(copy.copy(self.caf.info), xml)
        data = output.getvalue()
        readback = CafArchive(data)
        actual = CafInstanceEditor(readback)
        if readback.xml != xml or list(readback.objects) != list(self.caf.objects):
            raise ValueError("Edited CAF failed exact archive readback.")
        if actual.current != request.new_instance or actual.ref != self.ref:
            raise ValueError("Edited CAF Device identity failed readback.")
        return data, {**plan, "output_sha256": hashlib.sha256(data).hexdigest()}
