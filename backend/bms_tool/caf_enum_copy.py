"""Recorded Enumeration Constant copies without inferred enum meanings."""

from .caf_constant_copy import CafConstantCopies, ConstantProfile, _decimal
from .caf_graph import _properties
from .moi_identity import seal

PROFILE = "caf-recorded-enumeration-constant-copy/1"
SCOPE = (
    "One unconnected local Enumeration Constant and its required output object copied "
    "from recorded version 1.0 configuration. Enum data and metadata are retained as "
    "recorded; enum meanings, controller allocation, resources, CCT/PCT acceptance "
    "and field transfer are unverified."
)
_REQUIRED = frozenset({"75", "32527", "74", "931", "3365"})
_STATES_TEXT = frozenset({"351", "886", "405"})
_DEFAULT_SETS = _STATES_TEXT | {"647"}


class CafEnumCopies(CafConstantCopies):
    spec = ConstantProfile(
        PROFILE,
        SCOPE,
        "Enumeration Constant",
        "568",
        "529",
        19,
        frozenset({"12"}),
        "enum",
        (_REQUIRED, _REQUIRED | {"3113"}),
    )

    def _output(self, prototype_ref):
        a = self.archive
        children = [o for ref, o in a.objects.items() if ref.startswith(prototype_ref + ".")]
        if len(children) != 1:
            raise ValueError("A recorded Enumeration Constant requires exactly one output child.")
        obj = children[0]
        props = _properties(obj)
        if (
            obj.get("classid") != "529"
            or obj.get("classVersion") != "1.0"
            or set(obj.attrib) != {"classid", "classVersion", "objectid", "ref"}
            or set(props) not in self.spec.output_schemas
            or len(obj) != len(props)
        ):
            raise ValueError("CAF enumeration output is outside the recorded version 1.0 schemas.")
        instance = _decimal(obj.get("objectid"))
        if obj.get("ref") != f"{prototype_ref}.19_{instance}":
            raise ValueError("CAF enumeration output reference disagrees with its identity.")
        shapes = {
            "75": ("BACoid", {"id": "19"}),
            "32527": ("string", {}),
            "74": ("unsignedShort", {}),
            "931": ("enum", {"set": "802"}),
            "3365": ("enum", {"set": "509"}),
        }
        values = {}
        for pid, prop in props.items():
            value = a.scalar(prop)
            if value is None:
                raise ValueError("CAF enumeration output requires recorded scalar properties.")
            if pid == "3113":
                if (
                    value["type"] != "enum"
                    or set(value["attributes"]) != {"set"}
                    or value["attributes"]["set"] not in _DEFAULT_SETS
                ):
                    raise ValueError(
                        "CAF enumeration default encoding is outside the recorded profile."
                    )
                _decimal(value["text"], 4294967295)
            elif (value["type"], value["attributes"]) != shapes[pid]:
                raise ValueError("Unrecognized CAF enumeration output scalar configuration.")
            self._leaf(prop[0][0], value["text"])
            values[pid] = value
        _decimal(values["74"]["text"], 65535)
        if (
            values["75"]["text"] != str(instance)
            or values["32527"]["text"] != obj.get("ref")
            or values["3365"]["text"] != "85"
            or values["931"]["text"] not in _STATES_TEXT
        ):
            raise ValueError(
                "CAF enumeration identity, attribute or States Text is outside the recorded profile."
            )
        # 3113 encoding-set IDs and 931 States Text codes differ in recorded
        # sources. Their semantic relationship and a code/count bound are not
        # inferred. Copying the original configuration does not authorize edits.
        self._outer(obj)
        return obj

    def inspect(self, diagram_ref, prototype_ref):
        original = super().inspect(diagram_ref, prototype_ref)
        body = {k: v for k, v in original.items() if k != "selection_sha256"}
        props = _properties(self.archive.objects[body["output_ref"]])
        default = self.archive.scalar(props.get("3113"))
        states = self.archive.scalar(props["931"])
        body.update(
            number_of_states=int(self.archive.scalar(props["74"])["text"]),
            states_text_code=int(states["text"]),
            states_text_encoding_set=802,
            default_encoding_set=int(default["attributes"]["set"]) if default else None,
            enum_semantics_verified=False,
        )
        return {**body, "selection_sha256": seal(body)}
