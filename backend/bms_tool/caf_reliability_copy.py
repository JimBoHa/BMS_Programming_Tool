"""Copy recorded Reliability Check configuration and its two ports into a local CAF."""

from .caf import Q
from .caf_comparison_copy import CafComparisonCopies
from .caf_constant_copy import ConstantProfile, _decimal
from .caf_graph import _collection, _properties
from .moi_identity import seal, sha

PROFILE = "caf-recorded-reliability-copy/1"
SCOPE = (
    "One unconnected local Reliability Check and two recorded ports copied from "
    "version 1.0 source configuration. Boolean output spelling and omitted defaults, "
    "Enum metadata and absent parent setup remain exact. Reliability/Enum meanings, "
    "restart behavior, controller allocation, resources, CCT/PCT acceptance, execution "
    "and transfer are unverified."
)


class CafReliabilityCopies(CafComparisonCopies):
    spec = ConstantProfile(
        PROFILE,
        SCOPE,
        "Reliability Check",
        "539",
        "531",
        5,
        frozenset({"21", "22"}),
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
            or block["class_id"] != "539"
            or block["class_version"] != "1.0"
            or block["bacnet_type"] != 539
        ):
            raise ValueError(
                "Select an actual version 1.0 Reliability Check in a diagram with room for a new member."
            )
        obj = a.objects[prototype_ref]
        props = _properties(obj)
        if (
            set(obj.attrib) != {"classid", "classVersion", "ref", "objectid"}
            or set(props) != {"75", "32527", "3184", "3670"}
            or len(obj) != 4
        ):
            raise ValueError(
                "Reliability Check parent is outside the recorded four-property schema."
            )
        standard = self._scalar(props, "3670", "enum", {"set": "432"})
        if (
            standard not in {"21", "22"}
            or self._scalar(props, "32527", "string", {}) != prototype_ref
            or self._scalar(props, "75", "BACoid", {"id": "539"}) != obj.get("objectid")
        ):
            raise ValueError(
                "Reliability Check standard name, identity and Item Reference must match the recorded source."
            )
        ports = _collection(props, "3184", "array")
        if props["3184"].attrib != {"id": "3184"} or props["3184"][0].attrib or ports.attrib:
            raise ValueError("Unrecognized Reliability Check exposed-port framing.")
        exposed = []
        for port in ports:
            if port.tag != Q + "enum" or port.attrib != {"set": "509"} or len(port):
                raise ValueError(
                    "Reliability Check exposed ports require recorded native enum fields."
                )
            exposed.append(_decimal(port.text, 65535))
        if exposed != [513, 85]:
            raise ValueError(
                "Reliability Check exposed-port order is outside the recorded profile."
            )
        children = [o for ref, o in a.objects.items() if ref.startswith(prototype_ref + ".")]
        if len(children) != 2:
            raise ValueError("Recorded Reliability Check requires its two direct port objects.")
        rows = []
        ports = (("531", 5, 85), ("526", 2, 513) if standard == "21" else ("528", 19, 513))
        for child, (cid, typ, port) in zip(children, ports, strict=True):
            cp = _properties(child)
            base = {"75", "32527", "3365"}
            extra = (
                {"3113"}
                if port == 85 and standard == "21"
                else {"74", "931"}
                if typ == 19
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
                    "Reliability Check child order, type or schema is outside the recorded profile."
                )
            instance = _decimal(child.get("objectid"))
            if (
                child.get("ref") != f"{prototype_ref}.{typ}_{instance}"
                or self._scalar(cp, "75", "BACoid", {"id": str(typ)}) != str(instance)
                or self._scalar(cp, "32527", "string", {}) != child.get("ref")
                or self._scalar(cp, "3365", "enum", {"set": "509"}) != str(port)
            ):
                raise ValueError(
                    "Reliability Check child identity, hierarchy or port disagrees with its source."
                )
            states = text = encoding = units = metadata = value = None
            if port == 85 and standard == "21":
                value = self._scalar(cp, "3113", "boolean", {})
                if value not in {"true", "1"}:
                    raise ValueError(
                        "Reliability Check output default is outside the recorded profile."
                    )
            if typ == 19:
                states = _decimal(self._scalar(cp, "74", "unsignedShort", {}), 65535)
                text = _decimal(self._scalar(cp, "931", "enum", {"set": "802"}), 4294967295)
                if (states, text) != (2, 349):
                    raise ValueError(
                        "Reliability Check Enum metadata is outside the recorded profile."
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
                    "recorded_default": value,
                    "recorded_metadata_661": metadata,
                    "exposed": port in exposed,
                    "number_of_states": states,
                    "states_text_code": text,
                    "states_text_encoding_set": 802 if states is not None else None,
                    "default_encoding_set": encoding,
                    "units_code": units,
                    "units_encoding_set": 507 if units is not None else None,
                }
            )
        p = _properties(a.objects[diagram_ref])
        if "3373" in p and a.scalar(p["3373"]) not in (
            {"type": "boolean", "text": "true", "attributes": {}},
            {"type": "boolean", "text": "1", "attributes": {}},
        ):
            raise ValueError(
                "Reliability Check parent diagram must already record its user-modified state."
            )
        for pid, kind in (("3375", "array"), ("3117", "array"), ("3383", "listof")):
            collection = _collection(p, pid, kind)
            if p[pid].attrib != {"id": pid} or p[pid][0].attrib or collection.attrib:
                raise ValueError("Unknown Reliability Check diagram collection bookkeeping.")
            self._outer(collection)
        self._outer(obj)
        return graph, block, None, standard, rows

    def inspect(self, diagram_ref, prototype_ref):
        source = super().inspect(diagram_ref, prototype_ref)
        body = {k: v for k, v in source.items() if k != "selection_sha256"}
        body.update(reliability_semantics_verified=False, enum_semantics_verified=False)
        return {**body, "selection_sha256": seal(body)}
