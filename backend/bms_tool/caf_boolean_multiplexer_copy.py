"""Strict source-template Boolean Multiplexer copies; no native runtime inference."""

from .caf import Q
from .caf_comparison_copy import CafComparisonCopies
from .caf_constant_copy import ConstantProfile, _decimal
from .caf_graph import _collection, _properties
from .moi_identity import seal, sha

PROFILE = "caf-recorded-boolean-multiplexer-copy/1"
SCOPE = (
    "One unconnected local Boolean Multiplexer with a Boolean selector and four "
    "recorded ports copied from version 1.0 configuration. Bookkeeping, child/exposure "
    "order and absent defaults/setup stay exact. Native mode/assignment/fallback, "
    "runtime, controller allocation, resources, CCT/PCT and transfer are unverified."
)


class CafBooleanMultiplexerCopies(CafComparisonCopies):
    spec = ConstantProfile(
        PROFILE,
        SCOPE,
        "Boolean Multiplexer",
        "562",
        "531",
        5,
        frozenset({"18"}),
        "boolean",
        (frozenset({"75", "32527", "3365"}),),
    )
    enum_selector = False
    configurations = frozenset({(("1", "2"), "0", None, None)})

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
                "Select an actual version 1.0 Boolean Multiplexer with room for a new member."
            )
        obj = a.objects[prototype_ref]
        props = _properties(obj)
        if (
            set(obj.attrib) != {"classid", "classVersion", "ref", "objectid"}
            or set(props) != {"75", "32527", "2381", "3122", "3184", "3670"}
            or len(obj) != 6
        ):
            raise ValueError(
                "Boolean Multiplexer parent is outside its recorded six-property schema."
            )
        standard = self._scalar(props, "3670", "enum", {"set": "432"})
        if (
            standard not in self.spec.standard_codes
            or self._scalar(props, "32527", "string", {}) != prototype_ref
            or self._scalar(props, "75", "BACoid", {"id": "562"}) != obj.get("objectid")
        ):
            raise ValueError(
                "Boolean Multiplexer identity or standard name disagrees with the source profile."
            )
        modes = _collection(props, "2381", "listof")
        if props["2381"].attrib != {"id": "2381"} or props["2381"][0].attrib or modes.attrib:
            raise ValueError("Unrecognized Boolean Multiplexer bookkeeping framing.")
        bookkeeping = tuple(item.text for item in modes)
        retained = self._scalar(props, "3122", "unsignedShort", {})
        if (bookkeeping, retained) not in {(v[0], v[1]) for v in self.configurations}:
            raise ValueError("Boolean Multiplexer bookkeeping is outside the recorded profiles.")
        for item in modes:
            if item.tag != Q + "unsignedShort" or item.attrib or len(item):
                raise ValueError("Boolean Multiplexer bookkeeping requires recorded short fields.")
            self._leaf(item, item.text)
        self._outer(modes)
        exposed = _collection(props, "3184", "array")
        if props["3184"].attrib != {"id": "3184"} or props["3184"][0].attrib or exposed.attrib:
            raise ValueError("Unrecognized Boolean Multiplexer exposure framing.")
        ports = []
        for item in exposed:
            if item.tag != Q + "enum" or item.attrib != {"set": "509"} or len(item):
                raise ValueError("Boolean Multiplexer exposed ports require recorded enum fields.")
            ports.append(_decimal(item.text, 65535))
        if ports != [961, 7000, 7001, 85]:
            raise ValueError("Boolean Multiplexer exposure order is outside the recorded profile.")
        children = [
            child for ref, child in a.objects.items() if ref.startswith(prototype_ref + ".")
        ]
        if len(children) != 4:
            raise ValueError("Boolean Multiplexer requires four direct recorded port objects.")
        rows = []
        selector_states = selector_text = None
        for i, (child, port) in enumerate(zip(children, [85, 961, 7000, 7001], strict=True)):
            enum = self.enum_selector and port == 961
            typ = 19 if enum else 5
            cid = "531" if port == 85 else "528" if enum else "530"
            cp = _properties(child)
            required = {"75", "32527", "3365"}
            if port == 961:
                required |= {"3670"}
            if enum:
                required |= {"74", "931"}
            if self.enum_selector and port == 7001:
                required |= {"3113"}
            if (
                child.get("classid") != cid
                or child.get("classVersion") != "1.0"
                or set(child.attrib) != {"classid", "classVersion", "ref", "objectid"}
                or set(cp) != required
                or len(child) != len(cp)
            ):
                raise ValueError("Boolean Multiplexer child order, type or schema is unrecognized.")
            instance = _decimal(child.get("objectid"))
            if (
                child.get("ref") != f"{prototype_ref}.{typ}_{instance}"
                or self._scalar(cp, "75", "BACoid", {"id": str(typ)}) != str(instance)
                or self._scalar(cp, "32527", "string", {}) != child.get("ref")
                or self._scalar(cp, "3365", "enum", {"set": "509"}) != str(port)
            ):
                raise ValueError(
                    "Boolean Multiplexer child identity or port disagrees with its source."
                )
            if port == 961 and self._scalar(cp, "3670", "enum", {"set": "433"}) != "0":
                raise ValueError("Boolean Multiplexer selector name must remain recorded code0.")
            states = text = value = None
            if enum:
                states = _decimal(self._scalar(cp, "74", "unsignedShort", {}), 65535)
                text = _decimal(self._scalar(cp, "931", "enum", {"set": "802"}), 65535)
                selector_states, selector_text = states, text
            if "3113" in cp:
                value = self._scalar(cp, "3113", "boolean", {})
                if value not in {"true", "false", "1", "0"}:
                    raise ValueError(
                        "Boolean Multiplexer default requires a recorded Boolean spelling."
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
                    "direction": "output" if i == 0 else "input",
                    "exposed": True,
                    "recorded_default": value,
                    "recorded_metadata_661": None,
                    "number_of_states": states,
                    "states_text_code": text,
                    "states_text_encoding_set": 802 if enum else None,
                    "default_encoding_set": None,
                    "recorded_standard_name_code": 0 if port == 961 else None,
                }
            )
        if (bookkeeping, retained, selector_states, selector_text) not in self.configurations:
            raise ValueError(
                "Boolean Multiplexer selector metadata and bookkeeping profile disagree."
            )
        parent = _properties(a.objects[diagram_ref])
        if "3373" in parent and a.scalar(parent["3373"]) not in (
            {"type": "boolean", "text": "true", "attributes": {}},
            {"type": "boolean", "text": "1", "attributes": {}},
        ):
            raise ValueError(
                "Boolean Multiplexer diagram must already record its user-modified state."
            )
        for pid, kind in (("3375", "array"), ("3117", "array"), ("3383", "listof")):
            group = _collection(parent, pid, kind)
            if parent[pid].attrib != {"id": pid} or parent[pid][0].attrib or group.attrib:
                raise ValueError("Unknown Boolean Multiplexer diagram collection bookkeeping.")
            self._outer(group)
        self._outer(obj)
        return graph, block, None, standard, rows

    def inspect(self, diagram_ref, prototype_ref):
        source = super().inspect(diagram_ref, prototype_ref)
        body = {k: v for k, v in source.items() if k != "selection_sha256"}
        props = _properties(self.archive.objects[prototype_ref])
        body.update(
            multiplexer_semantics_verified=False,
            recorded_property_2381=[v.text for v in _collection(props, "2381", "listof")],
            recorded_property_3122=self._scalar(props, "3122", "unsignedShort", {}),
        )
        if self.enum_selector:
            body["enum_semantics_verified"] = False
        return {**body, "selection_sha256": seal(body)}
