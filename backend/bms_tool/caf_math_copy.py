"""Preserve recorded Math configuration while copying its local object subtree."""

from .caf import Q
from .caf_comparison_copy import CafComparisonCopies
from .caf_constant_copy import ConstantProfile, _decimal, coordinate
from .caf_graph import _collection, _properties
from .moi_identity import sha

PROFILE = "caf-recorded-math-copy/1"
SCOPE = (
    "One unconnected local Math primitive and its three or four recorded port objects "
    "copied from version 1.0 source configuration. Setup, standard names, child order "
    "and input defaults are preserved without inferring operator meanings. Controller "
    "allocation, resources, CCT/PCT acceptance, execution and transfer are unverified."
)
_SETUP_STANDARD = {"12": "42", "13": "43", "14": "41", "15": "40", "17": "58", "18": "59"}
_ORDERS = ((85, 7000, 7001), (85, 7000, 7002, 7001), (7002, 85, 7000, 7001), (85, 7002, 7000, 7001))


class CafMathCopies(CafComparisonCopies):
    """Own Math schema admission; share the loss-preserving lexical clone path."""

    spec = ConstantProfile(
        PROFILE,
        SCOPE,
        "Math",
        "561",
        "527",
        2,
        frozenset(_SETUP_STANDARD.values()),
        "float",
        (frozenset({"75", "32527", "3365"}),),
    )

    def _scalar(self, props, pid, kind, attributes):
        value = self.archive.scalar(props.get(pid))
        if value is None or value["type"] != kind or value["attributes"] != attributes:
            raise ValueError(f"Unrecognized recorded Math property {pid}.")
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
            or block["class_id"] != "561"
            or block["class_version"] != "1.0"
            or block["bacnet_type"] != 561
        ):
            raise ValueError(
                "Select an actual version 1.0 Math primitive in a diagram with room for a new member."
            )
        obj = a.objects[prototype_ref]
        props = _properties(obj)
        if (
            set(obj.attrib) != {"classid", "classVersion", "ref", "objectid"}
            or set(props) != {"75", "32527", "518", "3184", "3670"}
            or len(obj) != 5
        ):
            raise ValueError("Math parent is outside the recorded five-property schema.")
        setup = self._scalar(props, "518", "enum", {"set": "288"})
        standard = self._scalar(props, "3670", "enum", {"set": "432"})
        if _SETUP_STANDARD.get(setup) != standard:
            raise ValueError("This Math Setup/StandardName pair is outside the recorded profile.")
        if self._scalar(props, "32527", "string", {}) != prototype_ref or self._scalar(
            props, "75", "BACoid", {"id": "561"}
        ) != obj.get("objectid"):
            raise ValueError("Math parent identity and Item Reference must agree.")
        ports = _collection(props, "3184", "array")
        if props["3184"].attrib != {"id": "3184"} or props["3184"][0].attrib or ports.attrib:
            raise ValueError("Unrecognized Math exposed-port framing.")
        exposed = []
        for port in ports:
            if port.tag != Q + "enum" or port.attrib != {"set": "509"} or len(port):
                raise ValueError("Math exposed ports require recorded native enum fields.")
            exposed.append(_decimal(port.text, 65535))
        if exposed not in ([7000, 7001, 85], [7000, 7001, 85, 7002]) or (
            7002 in exposed and setup not in {"15", "17"}
        ):
            raise ValueError("Math exposed ports are outside the recorded setup profile.")
        children = [o for ref, o in a.objects.items() if ref.startswith(prototype_ref + ".")]
        if len(children) != len(exposed):
            raise ValueError(
                "Recorded Math requires exactly its three or four direct port objects."
            )
        rows = []
        for child in children:
            cp = _properties(child)
            port = _decimal(self._scalar(cp, "3365", "enum", {"set": "509"}), 65535)
            base = {"75", "32527", "3365"}
            schemas = (
                (base,)
                if port == 85
                else (base, base | {"3113"})
                if port == 7000
                else (base, base | {"3113"}, base | {"661", "3113"})
                if port == 7001
                else (base | {"3670"},)
                if port == 7002
                else ()
            )
            cid = "527" if port == 85 else "526"
            if (
                child.get("classid") != cid
                or child.get("classVersion") != "1.0"
                or set(child.attrib) != {"classid", "classVersion", "ref", "objectid"}
                or set(cp) not in schemas
                or len(child) != len(cp)
            ):
                raise ValueError("Math child type or schema is outside the recorded port profile.")
            instance = _decimal(child.get("objectid"))
            if (
                child.get("ref") != f"{prototype_ref}.2_{instance}"
                or self._scalar(cp, "75", "BACoid", {"id": "2"}) != str(instance)
                or self._scalar(cp, "32527", "string", {}) != child.get("ref")
            ):
                raise ValueError(
                    "Math child identity, hierarchy or port disagrees with its source."
                )
            value = coordinate(self._scalar(cp, "3113", "float", {})) if "3113" in cp else None
            metadata = self._scalar(cp, "661", "enum", {"set": "0"}) if "661" in cp else None
            if metadata is not None:
                _decimal(metadata, 4294967295)
            name = self._scalar(cp, "3670", "enum", {"set": "433"}) if "3670" in cp else None
            if name is not None and name != "0":
                raise ValueError(
                    "Additional Math input has an unrecognized recorded standard name."
                )
            self._outer(child)
            rows.append(
                {
                    "ref": child.get("ref"),
                    "class_id": cid,
                    "bacnet_type": 2,
                    "instance": instance,
                    "port": port,
                    "sha256": sha(self._raw(child)),
                    "recorded_default": value,
                    "recorded_metadata_661": metadata,
                    "recorded_standard_name_code": int(name) if name is not None else None,
                    "exposed": port in exposed,
                }
            )
        if tuple(r["port"] for r in rows) not in _ORDERS or set(r["port"] for r in rows) != set(
            exposed
        ):
            raise ValueError("Math child order and exposed ports do not match a recorded profile.")
        p = _properties(a.objects[diagram_ref])
        if "3373" in p and a.scalar(p["3373"]) not in (
            {"type": "boolean", "text": "true", "attributes": {}},
            {"type": "boolean", "text": "1", "attributes": {}},
        ):
            raise ValueError("Math parent diagram must already record its user-modified state.")
        for pid, kind in (("3375", "array"), ("3117", "array"), ("3383", "listof")):
            collection = _collection(p, pid, kind)
            if p[pid].attrib != {"id": pid} or p[pid][0].attrib or collection.attrib:
                raise ValueError("Unknown Math diagram collection bookkeeping.")
            self._outer(collection)
        self._outer(obj)
        return graph, block, setup, standard, rows
