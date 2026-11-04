"""Copy recorded Float Multiplexer configuration and its four ports into a local CAF."""

from .caf import Q
from .caf_comparison_copy import CafComparisonCopies
from .caf_constant_copy import ConstantProfile, _decimal
from .caf_graph import _collection, _properties
from .moi_identity import seal, sha

PROFILE = "caf-recorded-float-multiplexer-copy/1"
SCOPE = (
    "One unconnected local Float Multiplexer and four recorded ports copied from "
    "version 1.0 source configuration with a Boolean selector. Original selector "
    "bookkeeping, child/exposure order, omitted defaults and absent parent setup "
    "remain exact. Mode/operator meanings, controller allocation, resources, "
    "CCT/PCT acceptance, execution and transfer are unverified."
)


class CafFloatMultiplexerCopies(CafComparisonCopies):
    spec = ConstantProfile(
        PROFILE,
        SCOPE,
        "Float Multiplexer",
        "562",
        "527",
        2,
        frozenset({"14"}),
        "float",
        (frozenset({"75", "32527", "3365"}),),
    )

    def _prototype(self, diagram_ref, prototype_ref):
        a = self.archive
        graph = self.graph.diagram(diagram_ref)
        block = next((b for b in graph["blocks"] if b["ref"] == prototype_ref), None)
        if (
            not graph["observed_version"]
            or len(graph["blocks"]) >= 65535
            or block is None
            or block["class_id"] != "562"
            or block["class_version"] != "1.0"
            or block["bacnet_type"] != 562
        ):
            raise ValueError(
                "Select an actual version 1.0 Float Multiplexer in a diagram with room for a new member."
            )
        obj = a.objects[prototype_ref]
        props = _properties(obj)
        if (
            set(obj.attrib) != {"classid", "classVersion", "ref", "objectid"}
            or set(props) != {"75", "32527", "2381", "3122", "3184", "3670"}
            or len(obj) != 6
        ):
            raise ValueError(
                "Float Multiplexer parent is outside the recorded six-property schema."
            )
        standard = self._scalar(props, "3670", "enum", {"set": "432"})
        if (
            standard != "14"
            or self._scalar(props, "32527", "string", {}) != prototype_ref
            or self._scalar(props, "75", "BACoid", {"id": "562"}) != obj.get("objectid")
        ):
            raise ValueError(
                "Float Multiplexer standard name, identity and Item Reference must match the recorded source."
            )
        modes = _collection(props, "2381", "listof")
        if (
            props["2381"].attrib != {"id": "2381"}
            or props["2381"][0].attrib
            or modes.attrib
            or len(modes) != 2
        ):
            raise ValueError("Unrecognized Float Multiplexer recorded selector bookkeeping.")
        for item, expected in zip(modes, ("0", "2"), strict=True):
            if item.tag != Q + "unsignedShort" or item.attrib or len(item) or item.text != expected:
                raise ValueError("Float Multiplexer property 2381 is outside the recorded profile.")
            self._leaf(item, expected)
        if self._scalar(props, "3122", "unsignedShort", {}) != "1":
            raise ValueError("Float Multiplexer property 3122 is outside the recorded profile.")
        self._outer(modes)
        ports = _collection(props, "3184", "array")
        if props["3184"].attrib != {"id": "3184"} or props["3184"][0].attrib or ports.attrib:
            raise ValueError("Unrecognized Float Multiplexer exposed-port framing.")
        exposed = []
        for port in ports:
            if port.tag != Q + "enum" or port.attrib != {"set": "509"} or len(port):
                raise ValueError(
                    "Float Multiplexer exposed ports require recorded native enum fields."
                )
            exposed.append(_decimal(port.text, 65535))
        if exposed != [961, 7000, 7001, 85]:
            raise ValueError(
                "Float Multiplexer exposed-port order is outside the recorded profile."
            )
        children = [o for ref, o in a.objects.items() if ref.startswith(prototype_ref + ".")]
        if len(children) != 4:
            raise ValueError("Recorded Float Multiplexer requires its four direct port objects.")
        rows = []
        ports = (("527", 2, 85), ("530", 5, 961), ("526", 2, 7000), ("526", 2, 7001))
        for child, (cid, typ, port) in zip(children, ports, strict=True):
            cp = _properties(child)
            base = {"75", "32527", "3365"}
            if (
                child.get("classid") != cid
                or child.get("classVersion") != "1.0"
                or set(child.attrib) != {"classid", "classVersion", "ref", "objectid"}
                or set(cp) != base
                or len(child) != len(cp)
            ):
                raise ValueError(
                    "Float Multiplexer child order, type or schema is outside the recorded profile."
                )
            instance = _decimal(child.get("objectid"))
            if (
                child.get("ref") != f"{prototype_ref}.{typ}_{instance}"
                or self._scalar(cp, "75", "BACoid", {"id": str(typ)}) != str(instance)
                or self._scalar(cp, "32527", "string", {}) != child.get("ref")
                or self._scalar(cp, "3365", "enum", {"set": "509"}) != str(port)
            ):
                raise ValueError(
                    "Float Multiplexer child identity, hierarchy or port disagrees with its source."
                )
            self._outer(child)
            rows.append(
                {
                    "ref": child.get("ref"),
                    "class_id": cid,
                    "bacnet_type": typ,
                    "instance": instance,
                    "port": port,
                    "sha256": sha(self._raw(child)),
                    "direction": "output" if cid in {"531", "527"} else "input",
                    "recorded_default": None,
                    "recorded_metadata_661": None,
                    "exposed": port in exposed,
                }
            )
        p = _properties(a.objects[diagram_ref])
        if "3373" in p and a.scalar(p["3373"]) not in (
            {"type": "boolean", "text": "true", "attributes": {}},
            {"type": "boolean", "text": "1", "attributes": {}},
        ):
            raise ValueError(
                "Float Multiplexer parent diagram must already record its user-modified state."
            )
        for pid, kind in (("3375", "array"), ("3117", "array"), ("3383", "listof")):
            collection = _collection(p, pid, kind)
            if p[pid].attrib != {"id": pid} or p[pid][0].attrib or collection.attrib:
                raise ValueError("Unknown Float Multiplexer diagram collection bookkeeping.")
            self._outer(collection)
        self._outer(obj)
        return graph, block, None, standard, rows

    def inspect(self, diagram_ref, prototype_ref):
        source = super().inspect(diagram_ref, prototype_ref)
        body = {k: v for k, v in source.items() if k != "selection_sha256"}
        body.update(
            multiplexer_semantics_verified=False,
            recorded_property_2381=["0", "2"],
            recorded_property_3122="1",
        )
        return {**body, "selection_sha256": seal(body)}
