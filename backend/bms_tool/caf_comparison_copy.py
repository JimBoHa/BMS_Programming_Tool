"""Source-template copies of recorded Float Comparison primitives, local only."""

import copy
from decimal import Decimal

from .caf import CafArchive, Q
from .caf_constant_copy import (
    MAX_ID,
    CafConstantCopies,
    ConstantProfile,
    _decimal,
    _splice,
    coordinate,
)
from .caf_graph import _collection, _properties, _record
from .moi_identity import seal, sha

PROFILE = "caf-recorded-float-comparison-copy/1"
SCOPE = (
    "One unconnected local Float Comparison and four recorded port objects copied "
    "from version 1.0 source configuration. Setup, standard name and input defaults "
    "are preserved without inferring operator meanings. Controller allocation, "
    "resources, CCT/PCT acceptance, execution and transfer are unverified."
)
_SETUP_STANDARD = {"1": "28", "2": "31", "3": "32"}
_CHILDREN = (("531", 5, 85), ("526", 2, 50083), ("526", 2, 50084), ("526", 2, 637))


class CafComparisonCopies(CafConstantCopies):
    """Reuse lexical/archive helpers, keeping constant profiles unchanged."""

    spec = ConstantProfile(
        PROFILE,
        SCOPE,
        "Float Comparison",
        "560",
        "531",
        5,
        frozenset({"28", "31", "32"}),
        "boolean",
        (frozenset({"75", "32527", "3365"}),),
    )

    def _scalar(self, props, pid, kind, attributes):
        value = self.archive.scalar(props.get(pid))
        if value is None or value["type"] != kind or value["attributes"] != attributes:
            raise ValueError(f"Unrecognized recorded comparison property {pid}.")
        self._leaf(props[pid][0][0], value["text"])
        return value["text"]

    def _prototype(self, diagram_ref, prototype_ref):
        a = self.archive
        graph = self.graph.diagram(diagram_ref)
        block = next((b for b in graph["blocks"] if b["ref"] == prototype_ref), None)
        if (
            not graph["observed_version"]
            or len(graph["blocks"]) >= 65535
            or block is None
            or block["class_id"] != "560"
            or block["class_version"] != "1.0"
            or block["bacnet_type"] != 560
        ):
            raise ValueError(
                "Select an actual version 1.0 Float Comparison in a diagram with room for a new member."
            )
        obj = a.objects[prototype_ref]
        props = _properties(obj)
        if (
            set(obj.attrib) != {"classid", "classVersion", "ref", "objectid"}
            or set(props) != {"75", "32527", "518", "3184", "3670"}
            or len(obj) != 5
        ):
            raise ValueError("Comparison parent is outside the recorded five-property schema.")
        setup = self._scalar(props, "518", "enum", {"set": "287"})
        standard = self._scalar(props, "3670", "enum", {"set": "432"})
        if _SETUP_STANDARD.get(setup) != standard:
            raise ValueError(
                "This comparison Setup/StandardName pair is outside the Float-input profile."
            )
        if self._scalar(props, "32527", "string", {}) != prototype_ref or self._scalar(
            props, "75", "BACoid", {"id": "560"}
        ) != obj.get("objectid"):
            raise ValueError("Comparison parent identity and Item Reference must agree.")
        ports = _collection(props, "3184", "array")
        if props["3184"].attrib != {"id": "3184"} or props["3184"][0].attrib or ports.attrib:
            raise ValueError("Unrecognized comparison exposed-port framing.")
        exposed = []
        for port in ports:
            if port.tag != Q + "enum" or port.attrib != {"set": "509"} or len(port):
                raise ValueError("Comparison exposed ports require recorded native enum fields.")
            exposed.append(_decimal(port.text, 65535))
        if len(exposed) != len(set(exposed)) or set(exposed) not in (
            {85, 50083, 50084},
            {85, 50083, 50084, 637},
        ):
            raise ValueError("Comparison exposed ports are outside the recorded Float profile.")
        children = [o for ref, o in a.objects.items() if ref.startswith(prototype_ref + ".")]
        if len(children) != 4:
            raise ValueError("Recorded Float Comparison requires exactly four direct port objects.")
        rows = []
        for child, (cid, typ, port) in zip(children, _CHILDREN, strict=True):
            cp = _properties(child)
            permitted = (
                ({"75", "32527", "3365"}, {"75", "32527", "3365", "661", "3113"})
                if cid == "526"
                else ({"75", "32527", "3365"},)
            )
            if (
                child.get("classid") != cid
                or child.get("classVersion") != "1.0"
                or set(child.attrib) != {"classid", "classVersion", "ref", "objectid"}
                or set(cp) not in permitted
                or len(child) != len(cp)
            ):
                raise ValueError(
                    "Comparison child order, type or schema is outside the recorded Float profile."
                )
            instance = _decimal(child.get("objectid"))
            if (
                child.get("ref") != f"{prototype_ref}.{typ}_{instance}"
                or self._scalar(cp, "75", "BACoid", {"id": str(typ)}) != str(instance)
                or self._scalar(cp, "32527", "string", {}) != child.get("ref")
                or self._scalar(cp, "3365", "enum", {"set": "509"}) != str(port)
            ):
                raise ValueError(
                    "Comparison child identity, hierarchy or port disagrees with its source."
                )
            value = None
            metadata = None
            if "3113" in cp:
                value = coordinate(self._scalar(cp, "3113", "float", {}))
                metadata = self._scalar(cp, "661", "enum", {"set": "0"})
                _decimal(metadata, 4294967295)
            self._outer(child)
            rows.append(
                {
                    "ref": child.get("ref"),
                    "class_id": cid,
                    "bacnet_type": typ,
                    "instance": instance,
                    "port": port,
                    "sha256": sha(self._raw(child)),
                    "recorded_default": value,
                    "recorded_metadata_661": metadata,
                    "exposed": port in exposed,
                }
            )
        p = _properties(a.objects[diagram_ref])
        if "3373" in p and self.archive.scalar(p["3373"]) not in (
            {"type": "boolean", "text": "true", "attributes": {}},
            {"type": "boolean", "text": "1", "attributes": {}},
        ):
            raise ValueError(
                "Comparison parent diagram must already record its user-modified state."
            )
        for pid, kind in (("3375", "array"), ("3117", "array"), ("3383", "listof")):
            collection = _collection(p, pid, kind)
            if p[pid].attrib != {"id": pid} or p[pid][0].attrib or collection.attrib:
                raise ValueError("Unknown comparison diagram collection bookkeeping.")
            self._outer(collection)
        self._outer(obj)
        return graph, block, setup, standard, rows

    def inspect(self, diagram_ref, prototype_ref):
        first = self._allocation()
        graph, block, setup, standard, children = self._prototype(diagram_ref, prototype_ref)
        if first + len(children) > MAX_ID:
            raise ValueError(
                "Five fresh comparison identities do not fit the local allocation range."
                if self.spec.class_id == "560"
                else f"Fresh {self.spec.label} identities do not fit the local allocation range."
            )
        new_ref = f"{diagram_ref}.{self.spec.class_id}_{first}"
        if any(c in new_ref for c in "\r\n\t"):
            raise ValueError("Unsupported comparison reference framing.")
        for offset, row in enumerate(children, 1):
            row.update(
                new_instance=first + offset,
                new_ref=f"{new_ref}.{row['bacnet_type']}_{first + offset}",
            )
        for ref in [new_ref, *[r["new_ref"] for r in children]]:
            if ref in self.archive.objects or len(ref) > 512:
                raise ValueError("Fresh comparison references are unavailable in this profile.")
        output = next(r for r in children if r["port"] == 85)
        position = {}
        for axis, offset in (("x", 80), ("y", 40)):
            original = coordinate(block["layout"][axis])
            try:
                position[axis] = coordinate(str(Decimal(original.strip()) + offset))
            except ValueError:
                position[axis] = original
        body = {
            "profile": self.spec.profile,
            "scope": self.spec.scope,
            "source_sha256": self.archive.hash,
            "diagram_ref": diagram_ref,
            "diagram_sha256": sha(self._raw(self.archive.objects[diagram_ref])),
            "prototype_ref": prototype_ref,
            "prototype_sha256": sha(self._raw(self.archive.objects[prototype_ref])),
            "prototype_index": block["index"],
            "setup_code": int(setup) if setup is not None else None,
            "standard_name_code": int(standard),
            "exposed_port": 85,
            "member_count": len(graph["blocks"]),
            "execution_order": graph["execution_order"],
            "new_instance": first,
            "new_ref": new_ref,
            "new_output_instance": output["new_instance"],
            "new_output_ref": output["new_ref"],
            "output_ref": output["ref"],
            "output_sha256": output["sha256"],
            "recorded_value": None,
            "new_index": len(graph["blocks"]),
            "execution_after": block["execution_index"],
            "opaque_layout_code": block["layout"]["opaque_code"],
            "suggested_position": position,
            "object_count": len(children) + 1,
            "operator_meaning_verified": False,
            "children": children,
            "controller_write": False,
            "field_transfer_enabled": False,
            "vendor_acceptance_verified": False,
        }
        return {**body, "selection_sha256": seal(body)}

    def compile(self, *, diagram_ref, prototype_ref, selection_sha256, x, y):
        s = self.inspect(diagram_ref, prototype_ref)
        if s["selection_sha256"] != selection_sha256:
            raise ValueError("Comparison source changed; inspect its current prototype again.")
        x, y = coordinate(x), coordinate(y)
        a = self.archive
        parent = self._clone_identity(a.objects[prototype_ref], s["new_ref"], s["new_instance"])
        clones = [
            self._clone_identity(a.objects[r["ref"]], r["new_ref"], r["new_instance"])
            for r in s["children"]
        ]
        p = _properties(a.objects[diagram_ref])
        members = _collection(p, "3375", "array")
        order = _collection(p, "3117", "array")
        layout = _collection(p, "3383", "listof")
        member = members[s["prototype_index"]]
        ms, me = self._outer(member)
        m = self._leaf(member, str(s["new_instance"]))
        member_bytes = _splice(a.xml[ms:me], [(m[0] - ms, m[1] - ms, m[2])])
        ordered = order[s["execution_after"]]
        os, oe = self._outer(ordered)
        o = self._leaf(ordered, str(s["new_index"]))
        order_bytes = _splice(a.xml[os:oe], [(o[0] - os, o[1] - os, o[2])])
        row = layout[s["prototype_index"]]
        _record(row, ("float", "float", "unsignedShort"))
        rs, re = self._outer(row)
        pos = [self._leaf(row[0][0], x), self._leaf(row[1][0], y)]
        layout_bytes = _splice(a.xml[rs:re], [(st - rs, en - rs, b) for st, en, b in pos])
        edits = [
            (a._spans[id(members)][1], a._spans[id(members)][1], member_bytes),
            (oe, oe, order_bytes),
            (a._spans[id(layout)][1], a._spans[id(layout)][1], layout_bytes),
            (a._spans[id(a.root)][1], a._spans[id(a.root)][1], parent + b"".join(clones)),
        ]
        xml = _splice(a.xml, edits)
        output = a._copy_xml(xml)
        read = CafArchive(output)
        v = type(self)(read)
        before = self.graph.diagram(diagram_ref)
        expected = copy.deepcopy(before)
        for block in expected["blocks"]:
            if block["execution_index"] > s["execution_after"]:
                block["execution_index"] += 1
        block = copy.deepcopy(before["blocks"][s["prototype_index"]])
        block.update(
            index=s["new_index"],
            ref=s["new_ref"],
            instance=s["new_instance"],
            execution_index=s["execution_after"] + 1,
            layout={"x": x, "y": y, "opaque_code": s["opaque_layout_code"]},
        )
        expected["blocks"].append(block)
        expected["execution_order"].insert(s["execution_after"] + 1, s["new_index"])
        new_refs = [s["new_ref"], *[r["new_ref"] for r in s["children"]]]
        if (
            read.xml != xml
            or list(read.objects) != [*a.objects, *new_refs]
            or v.graph.diagram(diagram_ref) != expected
        ):
            raise ValueError("Comparison copy failed independent graph and identity readback.")
        for ref, raw in zip(new_refs, [parent, *clones], strict=True):
            if v._raw(read.objects[ref]) != raw:
                raise ValueError("Comparison object bytes failed readback.")
        v._prototype(diagram_ref, s["new_ref"])
        for ref, obj in a.objects.items():
            if ref != diagram_ref and self._raw(obj) != v._raw(read.objects[ref]):
                raise ValueError("Comparison copy changed an unrelated original object.")
        current = _properties(read.objects[diagram_ref])
        for pid in p:
            if pid not in {"3375", "3117", "3383"} and self._raw(p[pid]) != v._raw(current[pid]):
                raise ValueError("Comparison copy changed unrelated parent bookkeeping.")
        report = {
            "selection": s,
            "position": {"x": x, "y": y},
            "output_sha256": sha(output),
            "output_xml_sha256": sha(xml),
            "new_object_sha256": sha(parent),
            "new_output_sha256": sha(
                clones[next(i for i, r in enumerate(s["children"]) if r["ref"] == s["output_ref"])]
            ),
            "new_child_sha256": [sha(b) for b in clones],
            "controller_write": False,
            "field_transfer_enabled": False,
            "vendor_acceptance_verified": False,
        }
        return output, {**report, "creation_sha256": seal(report)}
