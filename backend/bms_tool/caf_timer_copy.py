"""Copy recorded Timer configuration and all seven ports into a local CAF."""

from .caf import Q
from .caf_comparison_copy import CafComparisonCopies
from .caf_constant_copy import ConstantProfile, _decimal, coordinate
from .caf_graph import _collection, _properties
from .moi_identity import seal, sha

PROFILE = "caf-recorded-timer-copy/1"
SCOPE = (
    "One unconnected local Timer and seven recorded ports copied from version 1.0 "
    "source configuration. Both outputs, hidden ports, stored/omitted values and "
    "metadata remain exact. Timer/Enum/units meanings, restart behavior, controller "
    "allocation, resources, CCT/PCT acceptance, execution and transfer are unverified."
)
_CHILDREN = (
    ("531", 5, 85),
    ("530", 5, 513),
    ("530", 5, 1082),
    ("528", 19, 518),
    ("526", 2, 1080),
    ("528", 19, 1083),
    ("527", 2, 1081),
)


class CafTimerCopies(CafComparisonCopies):
    spec = ConstantProfile(
        PROFILE,
        SCOPE,
        "Timer",
        "558",
        "531",
        5,
        frozenset({"62"}),
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
            or block["class_id"] != "558"
            or block["class_version"] != "1.0"
            or block["bacnet_type"] != 558
        ):
            raise ValueError(
                "Select an actual version 1.0 Timer in a diagram with room for a new member."
            )
        obj = a.objects[prototype_ref]
        props = _properties(obj)
        if (
            set(obj.attrib) != {"classid", "classVersion", "ref", "objectid"}
            or set(props) != {"75", "32527", "3184", "3670"}
            or len(obj) != 4
        ):
            raise ValueError("Timer parent is outside the recorded four-property schema.")
        standard = self._scalar(props, "3670", "enum", {"set": "432"})
        if (
            standard != "62"
            or self._scalar(props, "32527", "string", {}) != prototype_ref
            or self._scalar(props, "75", "BACoid", {"id": "558"}) != obj.get("objectid")
        ):
            raise ValueError(
                "Timer standard name, identity and Item Reference must match the recorded source."
            )
        ports = _collection(props, "3184", "array")
        if props["3184"].attrib != {"id": "3184"} or props["3184"][0].attrib or ports.attrib:
            raise ValueError("Unrecognized Timer exposed-port framing.")
        exposed = []
        for port in ports:
            if port.tag != Q + "enum" or port.attrib != {"set": "509"} or len(port):
                raise ValueError("Timer exposed ports require recorded native enum fields.")
            exposed.append(_decimal(port.text, 65535))
        if exposed != [513, 1080, 85]:
            raise ValueError("Timer exposed-port order is outside the recorded profile.")
        children = [o for ref, o in a.objects.items() if ref.startswith(prototype_ref + ".")]
        if len(children) != 7:
            raise ValueError(
                "Recorded Timer requires all seven direct port objects, including hidden ports."
            )
        rows = []
        for child, (cid, typ, port) in zip(children, _CHILDREN, strict=True):
            cp = _properties(child)
            base = {"75", "32527", "3365"}
            extra = (
                {"74", "931", "3113"}
                if port == 518
                else {"74", "931"}
                if port == 1083
                else {"117", "661", "3113"}
                if port == 1080
                else {"117", "661"}
                if port == 1081
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
                    "Timer child order, type or schema is outside the recorded profile."
                )
            instance = _decimal(child.get("objectid"))
            if (
                child.get("ref") != f"{prototype_ref}.{typ}_{instance}"
                or self._scalar(cp, "75", "BACoid", {"id": str(typ)}) != str(instance)
                or self._scalar(cp, "32527", "string", {}) != child.get("ref")
                or self._scalar(cp, "3365", "enum", {"set": "509"}) != str(port)
            ):
                raise ValueError(
                    "Timer child identity, hierarchy or port disagrees with its source."
                )
            states = text = encoding = units = metadata = value = None
            if typ == 19:
                states = _decimal(self._scalar(cp, "74", "unsignedShort", {}), 65535)
                text = _decimal(self._scalar(cp, "931", "enum", {"set": "802"}), 4294967295)
                if (states, text) != ((9, 21) if port == 518 else (2, 22)):
                    raise ValueError(
                        "Timer Enum state metadata is outside the recorded port profile."
                    )
                if port == 518:
                    scalar = a.scalar(cp["3113"])
                    if (
                        scalar is None
                        or scalar["type"] != "enum"
                        or scalar["attributes"] not in ({"set": "647"}, {"set": "21"})
                    ):
                        raise ValueError(
                            "Timer stored Enum default requires its recorded encoding namespace."
                        )
                    encoding = int(scalar["attributes"]["set"])
                    value = self._scalar(cp, "3113", "enum", {"set": str(encoding)})
                    _decimal(value, 4294967295)
            if typ == 2:
                units = _decimal(self._scalar(cp, "117", "enum", {"set": "507"}), 4294967295)
                metadata = self._scalar(cp, "661", "enum", {"set": "0"})
                if units != 73 or metadata != "6":
                    raise ValueError("Timer Float units/metadata are outside the recorded profile.")
                if port == 1080:
                    value = coordinate(self._scalar(cp, "3113", "float", {}))
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
            raise ValueError("Timer parent diagram must already record its user-modified state.")
        for pid, kind in (("3375", "array"), ("3117", "array"), ("3383", "listof")):
            collection = _collection(p, pid, kind)
            if p[pid].attrib != {"id": pid} or p[pid][0].attrib or collection.attrib:
                raise ValueError("Unknown Timer diagram collection bookkeeping.")
            self._outer(collection)
        self._outer(obj)
        return graph, block, None, standard, rows

    def inspect(self, diagram_ref, prototype_ref):
        source = super().inspect(diagram_ref, prototype_ref)
        body = {k: v for k, v in source.items() if k != "selection_sha256"}
        body.update(timer_semantics_verified=False, enum_semantics_verified=False)
        return {**body, "selection_sha256": seal(body)}
