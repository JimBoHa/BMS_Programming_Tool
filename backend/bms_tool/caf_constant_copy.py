"""Local creation of one unconnected block from an observed CAF constant.

This profile copies recorded configuration; it neither invents a constant value
nor qualifies vendor allocation, CCT reopening, native compilation or transfer.
Original lexical XML outside the three graph additions is retained verbatim.
"""

from __future__ import annotations

import copy
import html
import math
import re
import struct
from decimal import Decimal

from .caf import NS, CafArchive, Q
from .caf_graph import CafGraph, _collection, _coordinate, _properties, _record
from .moi_identity import seal, sha

PROFILE = "caf-recorded-float-constant-copy/1"
SCOPE = (
    "One unconnected local Float Constant and its required output object copied from "
    "recorded version 1.0 configuration. Recorded standard name and output value are retained. "
    "Controller allocation, resources, CCT/PCT acceptance and field transfer are unverified."
)
MAX_ID = 4194302
_ATTR = re.compile(rb"\s+([A-Za-z_][\w.:-]*)\s*=\s*([\"'])(.*?)\2", re.S)


def coordinate(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("Use a finite Float32 coordinate of at most 80 characters.")
    _coordinate(value)
    try:
        finite = math.isfinite(struct.unpack("!f", struct.pack("!f", float(value)))[0])
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        raise ValueError("Use a finite Float32 coordinate.")
    return value


def _decimal(value, maximum=MAX_ID):
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,9}", value):
        raise ValueError("Local CAF allocation requires canonical decimal identities.")
    number = int(value)
    if number > maximum:
        raise ValueError("CAF identity exceeds the supported local allocation range.")
    return number


def _splice(content, edits):
    last = len(content) + 1
    for start, end, value in sorted(edits, reverse=True):
        if not 0 <= start <= end < last:
            raise ValueError("Overlapping CAF creation patches are not supported.")
        content = content[:start] + value + content[end:]
        last = start
    return content


class CafConstantCopies:
    def __init__(self, source):
        self.archive = source if isinstance(source, CafArchive) else CafArchive(source)
        self.graph = CafGraph(self.archive)

    def _header(self, element):
        """Locate actual parsed attributes, including single quotes and embedded >."""
        a = self.archive
        start, _ = a._spans[id(element)]
        tag = element.tag.removeprefix(Q).encode()
        opening = re.match(rb"<" + tag + rb"(?=[\s/>])", a.xml[start:])
        if opening is None:
            raise ValueError("CAF creation requires the observed unprefixed XML framing.")
        position = start + opening.end()
        attrs = {}
        while match := _ATTR.match(a.xml, position):
            key = match[1].decode()
            if key in attrs:
                raise ValueError("Ambiguous CAF object attributes.")
            attrs[key] = (match.start(3), match.end(3), html.unescape(match[3].decode()))
            position = match.end()
        close = re.match(rb"\s*(/?)>", a.xml[position:])
        parsed = {k: v[2] for k, v in attrs.items()}
        if element is a.root and parsed.get("xmlns") == NS:
            parsed.pop("xmlns")
            if parsed.get("xmlns:xsi") == "http://www.w3.org/2001/XMLSchema-instance":
                parsed.pop("xmlns:xsi")
        if close is None or parsed != element.attrib:
            raise ValueError("Unrecognized CAF creation attribute framing.")
        return start, position + close.end(), bool(close[1]), attrs

    def _outer(self, element):
        start, opening_end, empty, _ = self._header(element)
        closing = self.archive._spans[id(element)][1]
        if empty:
            if closing != opening_end:
                raise ValueError("Ambiguous empty CAF element.")
            return start, opening_end
        tag = element.tag.removeprefix(Q).encode()
        match = re.match(rb"</" + tag + rb"\s*>", self.archive.xml[closing:])
        if match is None:
            raise ValueError("Unrecognized CAF creation closing tag.")
        return start, closing + match.end()

    def _raw(self, element):
        start, end = self._outer(element)
        return self.archive.xml[start:end]

    def _leaf(self, element, value):
        self._outer(element)
        start, end, before, after = self.archive._scalar_span(element)
        encoded = html.escape(value, quote=False).replace("\r", "&#13;").encode()
        return start, end, before + encoded + after

    def _allocation(self):
        a = self.archive
        if not a._patchable_xml or a.root.attrib:
            raise ValueError("CAF creation requires the observed UTF-8 root framing.")
        self._outer(a.root)
        for extra in a.root:
            if extra.tag != Q + "object" and (
                extra.tag not in {Q + "jobInfo", "jobInfo"}
                or extra.attrib
                or len(extra)
                or (extra.text or "").strip()
            ):
                raise ValueError("Unknown root bookkeeping prevents local CAF allocation.")
        high = max((_decimal(obj.get("objectid")) for obj in a.objects.values()), default=0)
        for entry in a.root.iter(Q + "BACoid"):
            if len(entry) or set(entry.attrib) != {"id"}:
                raise ValueError("Unknown typed reference prevents local CAF allocation.")
            _decimal(entry.get("id"), 1023)
            high = max(high, _decimal(entry.text))
        if high >= MAX_ID - 1:
            raise ValueError(
                "No fresh local CAF identity remains above recorded identities and references."
            )
        return high + 1

    def inspect(self, diagram_ref, prototype_ref):
        a = self.archive
        new_id = self._allocation()
        graph = self.graph.diagram(diagram_ref)
        parent = a.objects[diagram_ref]
        if not graph["observed_version"] or len(graph["blocks"]) >= 65535:
            raise ValueError(
                "CAF creation requires version 1.0 and a free unsigned-short member index."
            )
        block = next((b for b in graph["blocks"] if b["ref"] == prototype_ref), None)
        if block is None or block["class_id"] != "551" or block["class_version"] != "1.0":
            raise ValueError("Select an actual version 1.0 Float Constant in this diagram.")
        if block["bacnet_type"] != 551 or any(
            w["target_ref"] == prototype_ref for w in graph["connections"]
        ):
            raise ValueError(
                "CAF constant prototypes must have recorded type 551 and no incoming connections."
            )
        output = self._output(prototype_ref)
        obj = a.objects[prototype_ref]
        props = _properties(obj)
        if (
            set(obj.attrib) != {"classid", "classVersion", "objectid", "ref"}
            or set(props) != {"75", "3184", "32527", "3670"}
            or len(obj) != 4
        ):
            raise ValueError(
                "CAF constant configuration is outside the recorded four-property schema."
            )
        for pid in ("75", "32527", "3670"):
            scalar = a.scalar(props[pid])
            if scalar is None:
                raise ValueError("CAF constant requires the recorded scalar configuration.")
            self._leaf(props[pid][0][0], scalar["text"])
        if a.scalar(props["32527"]) != {"type": "string", "text": prototype_ref, "attributes": {}}:
            raise ValueError("CAF constant Item Reference disagrees with its object reference.")
        standard = a.scalar(props["3670"])
        if (
            standard["type"] != "enum"
            or standard["attributes"] != {"set": "432"}
            or standard["text"] not in {"11", "796"}
        ):
            raise ValueError("CAF constant standard name is outside the recorded profile.")
        ports = _collection(props, "3184", "array")
        if (
            props["3184"].attrib != {"id": "3184"}
            or props["3184"][0].attrib
            or ports.attrib
            or len(ports) != 1
            or ports[0].tag != Q + "enum"
            or ports[0].attrib != {"set": "509"}
            or len(ports[0])
            or ports[0].text != "85"
        ):
            raise ValueError("CAF constant requires the recorded exposed port 85.")
        p = _properties(parent)
        if "3373" in p and a.scalar(p["3373"]) not in (
            {"type": "boolean", "text": "1", "attributes": {}},
            {"type": "boolean", "text": "true", "attributes": {}},
        ):
            raise ValueError("CAF parent must already record its user-modified state.")
        for pid, kind in (("3375", "array"), ("3117", "array"), ("3383", "listof")):
            collection = _collection(p, pid, kind)
            if p[pid].attrib != {"id": pid} or p[pid][0].attrib or collection.attrib:
                raise ValueError("Unrecognized CAF parent collection bookkeeping.")
            self._outer(collection)
        self._outer(obj)
        new_ref = f"{diagram_ref}.551_{new_id}"
        if (
            new_ref in a.objects
            or f"{new_ref}.2_{new_id + 1}" in a.objects
            or len(f"{new_ref}.2_{new_id + 1}") > 512
            or any(c in new_ref for c in "\r\n\t")
        ):
            raise ValueError("Fresh local CAF reference is unavailable in this profile.")
        suggested = {}
        for axis, offset in (("x", 80), ("y", 40)):
            coordinate(block["layout"][axis])
            candidate = str(Decimal(block["layout"][axis].strip()) + offset)
            try:
                suggested[axis] = coordinate(candidate)
            except ValueError:
                suggested[axis] = block["layout"][axis]
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source_sha256": a.hash,
            "diagram_ref": diagram_ref,
            "diagram_sha256": sha(self._raw(parent)),
            "prototype_ref": prototype_ref,
            "prototype_sha256": sha(self._raw(obj)),
            "prototype_index": block["index"],
            "standard_name_code": int(standard["text"]),
            "exposed_port": 85,
            "member_count": len(graph["blocks"]),
            "execution_order": graph["execution_order"],
            "new_instance": new_id,
            "new_ref": new_ref,
            "output_ref": output.get("ref"),
            "output_sha256": sha(self._raw(output)),
            "new_output_instance": new_id + 1,
            "new_output_ref": f"{new_ref}.2_{new_id + 1}",
            "recorded_value": (a.scalar(_properties(output).get("3113")) or {}).get("text"),
            "new_index": len(graph["blocks"]),
            "execution_after": block["execution_index"],
            "opaque_layout_code": block["layout"]["opaque_code"],
            "suggested_position": suggested,
            "controller_write": False,
            "field_transfer_enabled": False,
            "vendor_acceptance_verified": False,
        }
        return {**body, "selection_sha256": seal(body)}

    def _output(self, prototype_ref):
        a = self.archive
        children = [obj for ref, obj in a.objects.items() if ref.startswith(prototype_ref + ".")]
        if len(children) != 1:
            raise ValueError("A recorded Float Constant requires exactly one output child object.")
        obj = children[0]
        props = _properties(obj)
        required = {"75", "32527", "3365"}
        schemas = (
            required,
            required | {"3113"},
            required | {"117", "3113"},
            required | {"661", "3113"},
            required | {"117", "661", "2390", "3113", "3807"},
        )
        if (
            obj.get("classid") != "527"
            or obj.get("classVersion") != "1.0"
            or set(obj.attrib) != {"classid", "classVersion", "objectid", "ref"}
            or set(props) not in schemas
            or len(obj) != len(props)
        ):
            raise ValueError("CAF constant output is outside the recorded version 1.0 schemas.")
        instance = _decimal(obj.get("objectid"))
        if obj.get("ref") != f"{prototype_ref}.2_{instance}":
            raise ValueError("CAF constant output reference disagrees with its identity.")
        expected = {
            "75": ("BACoid", {"id": "2"}),
            "32527": ("string", {}),
            "3365": ("enum", {"set": "509"}),
            "3113": ("float", {}),
            "117": ("enum", {"set": "507"}),
            "661": ("enum", {"set": "0"}),
            "2390": ("string", {}),
            "3807": ("boolean", {}),
        }
        for pid, prop in props.items():
            value = a.scalar(prop)
            if value is None or (value["type"], value["attributes"]) != expected[pid]:
                raise ValueError("Unrecognized CAF constant output scalar configuration.")
            self._leaf(prop[0][0], value["text"])
            if pid in {"117", "661"}:
                _decimal(value["text"], 4294967295)
            if pid == "3113":
                coordinate(value["text"])
            if pid == "3807" and value["text"] not in {"true", "false", "0", "1"}:
                raise ValueError("Unrecognized CAF constant output Boolean configuration.")
        if (
            a.scalar(props["75"])["text"] != str(instance)
            or a.scalar(props["32527"])["text"] != obj.get("ref")
            or a.scalar(props["3365"])["text"] != "85"
        ):
            raise ValueError("CAF constant output identity or exposed property is incoherent.")
        self._outer(obj)
        return obj

    def _clone_identity(self, obj, ref, instance):
        a = self.archive
        props = _properties(obj)
        start, end = self._outer(obj)
        attrs = self._header(obj)[3]
        edits = [
            (*attrs["ref"][:2], html.escape(ref, quote=True).encode()),
            (*attrs["objectid"][:2], str(instance).encode()),
            self._leaf(props["75"][0][0], str(instance)),
            self._leaf(props["32527"][0][0], ref),
        ]
        return _splice(a.xml[start:end], [(s - start, e - start, v) for s, e, v in edits])

    def compile(self, *, diagram_ref, prototype_ref, selection_sha256, x, y):
        selection = self.inspect(diagram_ref, prototype_ref)
        if selection["selection_sha256"] != selection_sha256:
            raise ValueError("CAF creation source changed; inspect the current prototype again.")
        x, y = coordinate(x), coordinate(y)
        a = self.archive
        obj = a.objects[prototype_ref]
        cloned = self._clone_identity(obj, selection["new_ref"], selection["new_instance"])
        cloned_output = self._clone_identity(
            a.objects[selection["output_ref"]],
            selection["new_output_ref"],
            selection["new_output_instance"],
        )
        p = _properties(a.objects[diagram_ref])
        members = _collection(p, "3375", "array")
        order = _collection(p, "3117", "array")
        layout = _collection(p, "3383", "listof")
        index = selection["prototype_index"]
        member = members[index]
        ms, me = self._outer(member)
        patch = self._leaf(member, str(selection["new_instance"]))
        new_member = _splice(a.xml[ms:me], [(patch[0] - ms, patch[1] - ms, patch[2])])
        ordered = order[selection["execution_after"]]
        os, oe = self._outer(ordered)
        patch = self._leaf(ordered, str(selection["new_index"]))
        new_order = _splice(a.xml[os:oe], [(patch[0] - os, patch[1] - os, patch[2])])
        row = layout[index]
        _record(row, ("float", "float", "unsignedShort"))
        rs, re_ = self._outer(row)
        patches = [self._leaf(row[0][0], x), self._leaf(row[1][0], y)]
        new_layout = _splice(a.xml[rs:re_], [(s - rs, e - rs, v) for s, e, v in patches])
        edits = [
            (a._spans[id(members)][1], a._spans[id(members)][1], new_member),
            (oe, oe, new_order),
            (a._spans[id(layout)][1], a._spans[id(layout)][1], new_layout),
            (a._spans[id(a.root)][1], a._spans[id(a.root)][1], cloned + cloned_output),
        ]
        xml = _splice(a.xml, edits)
        output = a._copy_xml(xml)
        readback = CafArchive(output)
        verifier = CafConstantCopies(readback)
        before = self.graph.diagram(diagram_ref)
        expected = copy.deepcopy(before)
        for block in expected["blocks"]:
            if block["execution_index"] > selection["execution_after"]:
                block["execution_index"] += 1
        new_block = copy.deepcopy(before["blocks"][index])
        new_block.update(
            index=selection["new_index"],
            ref=selection["new_ref"],
            instance=selection["new_instance"],
            execution_index=selection["execution_after"] + 1,
            layout={"x": x, "y": y, "opaque_code": selection["opaque_layout_code"]},
        )
        expected["blocks"].append(new_block)
        expected["execution_order"].insert(selection["execution_after"] + 1, selection["new_index"])
        if (
            readback.xml != xml
            or verifier.graph.diagram(diagram_ref) != expected
            or list(readback.objects)
            != [*a.objects, selection["new_ref"], selection["new_output_ref"]]
            or verifier._raw(readback.objects[selection["new_ref"]]) != cloned
            or verifier._raw(readback.objects[selection["new_output_ref"]]) != cloned_output
            or verifier._output(selection["new_ref"]).get("ref") != selection["new_output_ref"]
        ):
            raise ValueError("CAF creation failed independent graph and identity readback.")
        for ref, old in a.objects.items():
            if ref != diagram_ref and self._raw(old) != verifier._raw(readback.objects[ref]):
                raise ValueError("CAF creation changed an unrelated original object.")
        for pid in p:
            if pid not in {"3375", "3117", "3383"} and self._raw(p[pid]) != verifier._raw(
                _properties(readback.objects[diagram_ref])[pid]
            ):
                raise ValueError("CAF creation changed unrelated graph bookkeeping.")
        report = {
            "selection": selection,
            "position": {"x": x, "y": y},
            "output_sha256": sha(output),
            "output_xml_sha256": sha(xml),
            "new_object_sha256": sha(cloned),
            "new_output_sha256": sha(cloned_output),
            "controller_write": False,
            "field_transfer_enabled": False,
            "vendor_acceptance_verified": False,
        }
        return output, {**report, "creation_sha256": seal(report)}
