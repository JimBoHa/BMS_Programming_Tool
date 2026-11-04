"""Copy recorded Float Multiplexer configuration with an Enum selector, local only."""

from .caf import Q
from .caf_comparison_copy import CafComparisonCopies
from .caf_constant_copy import ConstantProfile, _decimal, coordinate
from .caf_graph import _collection, _properties
from .moi_identity import seal, sha

PROFILE = "caf-recorded-float-enum-selector-multiplexer-copy/1"
SCOPE = (
    "One unconnected local Float Multiplexer with an Enum selector and six recorded "
    "ports copied from version 1.0 source configuration. Raw selector bookkeeping, "
    "input defaults, Enum metadata, extra input names, child/exposure order and absent "
    "parent setup remain exact. Mode/Enum meanings, controller allocation, resources, "
    "CCT/PCT acceptance, execution and transfer are unverified."
)


class CafEnumSelectorMultiplexerCopies(CafComparisonCopies):
    spec = ConstantProfile(
        PROFILE,
        SCOPE,
        "Float Multiplexer with Enum selector",
        "562",
        "527",
        2,
        frozenset({"15"}),
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
            standard != "15"
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
            or len(modes) != 6
        ):
            raise ValueError("Unrecognized Float Multiplexer recorded selector bookkeeping.")
        for item, expected in zip(modes, ("0", "2", "0", "0", "3", "4"), strict=True):
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
        if exposed != [961, 7000, 7001, 85, 7002, 7003]:
            raise ValueError(
                "Float Multiplexer exposed-port order is outside the recorded profile."
            )
        children = [o for ref, o in a.objects.items() if ref.startswith(prototype_ref + ".")]
        if len(children) != 6:
            raise ValueError("Recorded Float Multiplexer requires its six direct port objects.")
        rows = []
        ports = (
            ("527", 2, 85),
            ("526", 2, 7002),
            ("526", 2, 7003),
            ("526", 2, 7000),
            ("526", 2, 7001),
            ("528", 19, 961),
        )
        for child, (cid, typ, port) in zip(children, ports, strict=True):
            cp = _properties(child)
            base = {"75", "32527", "3365"}
            extra = (
                {"3670"}
                if port in {7002, 7003}
                else {"3113"}
                if port == 7001
                else {"74", "931", "3670"}
                if port == 961
                else set()
            )
            if (
                child.get("classid") != cid
                or child.get("classVersion") != "1.0"
                or set(child.attrib) != {"classid", "classVersion", "ref", "objectid"}
                or set(cp) != base | extra
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
            name = self._scalar(cp, "3670", "enum", {"set": "433"}) if "3670" in cp else None
            if name is not None and name != "0":
                raise ValueError("Unrecognized recorded Enum-selector Multiplexer input name.")
            value = coordinate(self._scalar(cp, "3113", "float", {})) if port == 7001 else None
            states = text = None
            if port == 961:
                states = _decimal(self._scalar(cp, "74", "unsignedShort", {}), 65535)
                text = _decimal(self._scalar(cp, "931", "enum", {"set": "802"}), 4294967295)
                if (states, text) != (6, 900):
                    raise ValueError("Unrecognized Enum-selector Multiplexer state metadata.")
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
                    "recorded_default": value,
                    "recorded_metadata_661": None,
                    "exposed": port in exposed,
                    "recorded_standard_name_code": int(name) if name is not None else None,
                    "number_of_states": states,
                    "states_text_code": text,
                    "states_text_encoding_set": 802 if states is not None else None,
                    "default_encoding_set": None,
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
            recorded_property_2381=["0", "2", "0", "0", "3", "4"],
            enum_semantics_verified=False,
            recorded_property_3122="1",
        )
        return {**body, "selection_sha256": seal(body)}
