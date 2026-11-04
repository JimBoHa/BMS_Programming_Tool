"""Copy recorded Enum Multiplexer configuration and its four ports into a local CAF."""

from .caf import Q
from .caf_comparison_copy import CafComparisonCopies
from .caf_constant_copy import ConstantProfile, _decimal
from .caf_graph import _collection, _properties
from .moi_identity import seal, sha

PROFILE = "caf-recorded-enum-multiplexer-copy/1"
SCOPE = (
    "One unconnected local Enum Multiplexer with a Boolean selector and four recorded "
    "ports copied from version 1.0 source configuration. Raw bookkeeping, Enum state "
    "metadata, default namespaces, stored/omitted values and child/exposure order "
    "remain exact. Enum membership, selector meanings, controller allocation, resources, "
    "CCT/PCT acceptance, execution and transfer are unverified."
)


class CafEnumMultiplexerCopies(CafComparisonCopies):
    spec = ConstantProfile(
        PROFILE,
        SCOPE,
        "Enum Multiplexer",
        "562",
        "529",
        19,
        frozenset({"16"}),
        "enum",
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
                "Select an actual version 1.0 Enum Multiplexer in a diagram with room for a new member."
            )
        obj = a.objects[prototype_ref]
        props = _properties(obj)
        if (
            set(obj.attrib) != {"classid", "classVersion", "ref", "objectid"}
            or set(props) != {"75", "32527", "2381", "3122", "3184", "3670"}
            or len(obj) != 6
        ):
            raise ValueError("Enum Multiplexer parent is outside the recorded six-property schema.")
        standard = self._scalar(props, "3670", "enum", {"set": "432"})
        if (
            standard != "16"
            or self._scalar(props, "32527", "string", {}) != prototype_ref
            or self._scalar(props, "75", "BACoid", {"id": "562"}) != obj.get("objectid")
        ):
            raise ValueError(
                "Enum Multiplexer standard name, identity and Item Reference must match the recorded source."
            )
        modes = _collection(props, "2381", "listof")
        if (
            props["2381"].attrib != {"id": "2381"}
            or props["2381"][0].attrib
            or modes.attrib
            or len(modes) != 2
        ):
            raise ValueError("Unrecognized Enum Multiplexer recorded selector bookkeeping.")
        bookkeeping = tuple(item.text for item in modes)
        retained = self._scalar(props, "3122", "unsignedShort", {})
        if (bookkeeping, retained) not in {(("0", "2"), "1"), (("1", "2"), "0")}:
            raise ValueError("Enum Multiplexer bookkeeping is outside the recorded profile.")
        for item, expected in zip(modes, bookkeeping, strict=True):
            if item.tag != Q + "unsignedShort" or item.attrib or len(item):
                raise ValueError("Enum Multiplexer property 2381 requires recorded short fields.")
            self._leaf(item, expected)
        self._outer(modes)
        ports = _collection(props, "3184", "array")
        if props["3184"].attrib != {"id": "3184"} or props["3184"][0].attrib or ports.attrib:
            raise ValueError("Unrecognized Enum Multiplexer exposed-port framing.")
        exposed = []
        for port in ports:
            if port.tag != Q + "enum" or port.attrib != {"set": "509"} or len(port):
                raise ValueError(
                    "Enum Multiplexer exposed ports require recorded native enum fields."
                )
            exposed.append(_decimal(port.text, 65535))
        if exposed != [961, 7000, 7001, 85]:
            raise ValueError("Enum Multiplexer exposed-port order is outside the recorded profile.")
        children = [o for ref, o in a.objects.items() if ref.startswith(prototype_ref + ".")]
        if len(children) != 4:
            raise ValueError("Recorded Enum Multiplexer requires four direct port objects.")
        rows = []
        ports = (("529", 19, 85), ("530", 5, 961), ("528", 19, 7000), ("528", 19, 7001))
        for child, (cid, typ, port) in zip(children, ports, strict=True):
            cp = _properties(child)
            base = {"75", "32527", "3365"} | ({"74"} if typ == 19 else set())
            optional = ({"931"} | ({"3113"} if port != 85 else set())) if typ == 19 else {"3670"}
            if (
                child.get("classid") != cid
                or child.get("classVersion") != "1.0"
                or set(child.attrib) != {"classid", "classVersion", "ref", "objectid"}
                or not base <= set(cp) <= base | optional
                or len(child) != len(cp)
            ):
                raise ValueError("Enum Multiplexer child order, type or schema is unrecognized.")
            instance = _decimal(child.get("objectid"))
            if (
                child.get("ref") != f"{prototype_ref}.{typ}_{instance}"
                or self._scalar(cp, "75", "BACoid", {"id": str(typ)}) != str(instance)
                or self._scalar(cp, "32527", "string", {}) != child.get("ref")
                or self._scalar(cp, "3365", "enum", {"set": "509"}) != str(port)
            ):
                raise ValueError(
                    "Enum Multiplexer child identity or port disagrees with its source."
                )
            states = text_code = default_set = standard_code = value = None
            if typ == 19:
                states = _decimal(self._scalar(cp, "74", "unsignedShort", {}), 65535)
                text_code = (
                    _decimal(self._scalar(cp, "931", "enum", {"set": "802"}), 65535)
                    if "931" in cp
                    else None
                )
                if (states, text_code) not in {(2, 418), (4, 366), (2, None)}:
                    raise ValueError(
                        "Enum Multiplexer state metadata is outside the recorded profiles."
                    )
                if "3113" in cp:
                    default = a.scalar(cp["3113"])
                    encodings = {"647"} | ({str(text_code)} if text_code is not None else set())
                    if (
                        default is None
                        or default["type"] != "enum"
                        or set(default["attributes"]) != {"set"}
                        or default["attributes"]["set"] not in encodings
                    ):
                        raise ValueError(
                            "Enum Multiplexer default encoding is outside its recorded namespace."
                        )
                    value = self._scalar(cp, "3113", "enum", default["attributes"])
                    _decimal(value, 4294967295)
                    default_set = int(default["attributes"]["set"])
            elif "3670" in cp:
                if self._scalar(cp, "3670", "enum", {"set": "433"}) != "0":
                    raise ValueError(
                        "Enum Multiplexer selector name is outside its recorded profile."
                    )
                standard_code = 0
            self._outer(child)
            rows.append(
                {
                    "ref": child.get("ref"),
                    "class_id": cid,
                    "bacnet_type": typ,
                    "instance": instance,
                    "port": port,
                    "sha256": sha(self._raw(child)),
                    "direction": "output" if port == 85 else "input",
                    "recorded_default": value,
                    "recorded_metadata_661": None,
                    "exposed": True,
                    "number_of_states": states,
                    "states_text_code": text_code,
                    "states_text_encoding_set": 802 if text_code is not None else None,
                    "default_encoding_set": default_set,
                    "recorded_standard_name_code": standard_code,
                }
            )
        enum_metadata = {
            (r["number_of_states"], r["states_text_code"]) for r in rows if r["bacnet_type"] == 19
        }
        if len(enum_metadata) != 1:
            raise ValueError(
                "Enum Multiplexer ports disagree with the recorded state metadata shape."
            )
        states, text_code = next(iter(enum_metadata))
        if (bookkeeping, retained, states, text_code) not in {
            (("0", "2"), "1", 4, 366),
            (("1", "2"), "0", 2, 418),
            (("1", "2"), "0", 2, None),
        }:
            raise ValueError("Enum Multiplexer bookkeeping/state profile is unrecognized.")
        p = _properties(a.objects[diagram_ref])
        if "3373" in p and a.scalar(p["3373"]) not in (
            {"type": "boolean", "text": "true", "attributes": {}},
            {"type": "boolean", "text": "1", "attributes": {}},
        ):
            raise ValueError(
                "Enum Multiplexer parent diagram must already record its user-modified state."
            )
        for pid, kind in (("3375", "array"), ("3117", "array"), ("3383", "listof")):
            collection = _collection(p, pid, kind)
            if p[pid].attrib != {"id": pid} or p[pid][0].attrib or collection.attrib:
                raise ValueError("Unknown Enum Multiplexer diagram collection bookkeeping.")
            self._outer(collection)
        self._outer(obj)
        return graph, block, None, standard, rows

    def inspect(self, diagram_ref, prototype_ref):
        source = super().inspect(diagram_ref, prototype_ref)
        body = {k: v for k, v in source.items() if k != "selection_sha256"}
        body.update(
            multiplexer_semantics_verified=False,
            enum_semantics_verified=False,
            recorded_property_2381=[
                v.text
                for v in _collection(
                    _properties(self.archive.objects[prototype_ref]), "2381", "listof"
                )
            ],
            recorded_property_3122=self._scalar(
                _properties(self.archive.objects[prototype_ref]), "3122", "unsignedShort", {}
            ),
        )
        return {**body, "selection_sha256": seal(body)}
