"""Recorded Enumeration Comparison subtree copies, without inferred Enum semantics."""

from .caf import Q
from .caf_comparison_copy import CafComparisonCopies
from .caf_constant_copy import ConstantProfile, _decimal
from .caf_graph import _collection, _properties
from .moi_identity import seal, sha

PROFILE = "caf-recorded-enumeration-comparison-copy/1"
SCOPE = (
    "One unconnected local Enumeration Comparison and four recorded port objects "
    "copied from version 1.0 source configuration. Hidden Float input, Enum metadata, "
    "default namespaces and omissions are preserved without inferring operator or "
    "Enum meanings. Controller allocation, resources, CCT/PCT acceptance, execution "
    "and transfer are unverified."
)
_CHILDREN = (("531", 5, 85), ("526", 2, 637), ("528", 19, 50083), ("528", 19, 50084))


class CafEnumComparisonCopies(CafComparisonCopies):
    """Own Enum-input admission, retaining the existing lexical copy verifier."""

    spec = ConstantProfile(
        PROFILE,
        SCOPE,
        "Enumeration Comparison",
        "560",
        "531",
        5,
        frozenset({"34"}),
        "boolean",
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
            or block["class_id"] != "560"
            or block["class_version"] != "1.0"
            or block["bacnet_type"] != 560
        ):
            raise ValueError(
                "Select an actual version 1.0 Enumeration Comparison in a diagram with room for a new member."
            )
        obj = a.objects[prototype_ref]
        props = _properties(obj)
        if (
            set(obj.attrib) != {"classid", "classVersion", "ref", "objectid"}
            or set(props) != {"75", "32527", "518", "3184", "3670"}
            or len(obj) != 5
        ):
            raise ValueError(
                "Enumeration Comparison parent is outside the recorded five-property schema."
            )
        setup = self._scalar(props, "518", "enum", {"set": "287"})
        standard = self._scalar(props, "3670", "enum", {"set": "432"})
        if (setup, standard) != ("5", "34"):
            raise ValueError(
                "Comparison Setup/StandardName is outside the Enumeration-input profile."
            )
        if self._scalar(props, "32527", "string", {}) != prototype_ref or self._scalar(
            props, "75", "BACoid", {"id": "560"}
        ) != obj.get("objectid"):
            raise ValueError(
                "Enumeration Comparison parent identity and Item Reference must agree."
            )
        ports = _collection(props, "3184", "array")
        if props["3184"].attrib != {"id": "3184"} or props["3184"][0].attrib or ports.attrib:
            raise ValueError("Unrecognized Enumeration Comparison exposed-port framing.")
        exposed = []
        for port in ports:
            if port.tag != Q + "enum" or port.attrib != {"set": "509"} or len(port):
                raise ValueError(
                    "Enumeration Comparison requires recorded exposed-port enum fields."
                )
            exposed.append(_decimal(port.text, 65535))
        if exposed != [50083, 50084, 85]:
            raise ValueError(
                "Enumeration Comparison requires its recorded exposure and hidden Float input."
            )
        children = [o for ref, o in a.objects.items() if ref.startswith(prototype_ref + ".")]
        if len(children) != 4:
            raise ValueError(
                "Recorded Enumeration Comparison requires exactly four direct port objects."
            )
        rows = []
        for child, (cid, typ, port) in zip(children, _CHILDREN, strict=True):
            cp = _properties(child)
            base = {"75", "32527", "3365"}
            schemas = (
                (base | {"74", "931"}, base | {"74", "931", "3113"}) if cid == "528" else (base,)
            )
            if (
                child.get("classid") != cid
                or child.get("classVersion") != "1.0"
                or set(child.attrib) != {"classid", "classVersion", "ref", "objectid"}
                or set(cp) not in schemas
                or len(child) != len(cp)
            ):
                raise ValueError(
                    "Enumeration Comparison child order, type or schema is outside the recorded profile."
                )
            instance = _decimal(child.get("objectid"))
            if (
                child.get("ref") != f"{prototype_ref}.{typ}_{instance}"
                or self._scalar(cp, "75", "BACoid", {"id": str(typ)}) != str(instance)
                or self._scalar(cp, "32527", "string", {}) != child.get("ref")
                or self._scalar(cp, "3365", "enum", {"set": "509"}) != str(port)
            ):
                raise ValueError(
                    "Enumeration Comparison child identity, hierarchy or port disagrees with source."
                )
            states = text = encoding = value = None
            if cid == "528":
                states = _decimal(self._scalar(cp, "74", "unsignedShort", {}), 65535)
                text = _decimal(self._scalar(cp, "931", "enum", {"set": "802"}), 4294967295)
                if (states, text) not in {(4, 366), (6, 387)}:
                    raise ValueError(
                        "Enumeration input state metadata is outside the recorded pairs."
                    )
                if "3113" in cp:
                    scalar = a.scalar(cp["3113"])
                    if (
                        scalar is None
                        or scalar["type"] != "enum"
                        or scalar["attributes"] not in ({"set": "647"}, {"set": str(text)})
                    ):
                        raise ValueError(
                            "Enumeration input default requires its recorded encoding namespace."
                        )
                    encoding = int(scalar["attributes"]["set"])
                    value = self._scalar(cp, "3113", "enum", {"set": str(encoding)})
                    _decimal(value, 4294967295)
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
                    "recorded_metadata_661": None,
                    "exposed": port in exposed,
                    "number_of_states": states,
                    "states_text_code": text,
                    "states_text_encoding_set": 802 if states is not None else None,
                    "default_encoding_set": encoding,
                }
            )
        p = _properties(a.objects[diagram_ref])
        if "3373" in p and a.scalar(p["3373"]) not in (
            {"type": "boolean", "text": "true", "attributes": {}},
            {"type": "boolean", "text": "1", "attributes": {}},
        ):
            raise ValueError(
                "Enumeration Comparison diagram must already record its user-modified state."
            )
        for pid, kind in (("3375", "array"), ("3117", "array"), ("3383", "listof")):
            collection = _collection(p, pid, kind)
            if p[pid].attrib != {"id": pid} or p[pid][0].attrib or collection.attrib:
                raise ValueError("Unknown Enumeration Comparison diagram collection bookkeeping.")
            self._outer(collection)
        self._outer(obj)
        return graph, block, setup, standard, rows

    def inspect(self, diagram_ref, prototype_ref):
        source = super().inspect(diagram_ref, prototype_ref)
        body = {k: v for k, v in source.items() if k != "selection_sha256"}
        body["enum_semantics_verified"] = False
        return {**body, "selection_sha256": seal(body)}
