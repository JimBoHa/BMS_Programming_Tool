"""Field transfers need an application type, not merely a valid PSS storage type."""

from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import ObjectIdentifier, TagClass, TagList

from .moi_identity import MoiIdentity

PROFILE = "native-omitted-application-field-types/1"
# Native format-family attributes, independently qualified against their
# application definitions. These do not select models, objects or inventories.
MODULE_TYPES = {
    (240, 1302): 1,  # hardware input presence Boolean
    (252, 3413): 1,
    (252, 3414): 4,
    (252, 3415): 4,
    (252, 3545): 4,
    (252, 64587): 2,
    (570, 3506): 4,  # calculated flow calibration Real
    (575, 2305): 7,  # control-sequence database identifier string
}
ROOT_TYPES = {32583: 9, 119: 3, 1017: 3, 1093: 3, 988: "five-unsigned", 1040: "five-unsigned"}
# The input profile declares these application/data-model pairs. Do not infer
# an omitted-field schema for an unqualified release, even from valid PSS bytes.
ANALOG_DEFAULT_FORMATS = {(60, 60), (62, 62), (66, 65)}
ANALOG_DEFAULT_TYPES = {
    (240, 813): "unsigned-byte",  # AI calculation default, not an Enum or Boolean
    (240, 3164): 4,  # AI filter Time Constant (Real seconds)
}


def qualify_parameter_additions(application, parameter_merge):
    added = [row for row in parameter_merge["changed_parameters"] if row.get("added")]
    if not added:
        return {"profile": PROFILE, "qualified_fields": 0, "model_inventory_used": False}
    app = MoiIdentity(application)
    objects = {
        int.from_bytes(app.data[r["offset"] + 6 : r["offset"] + 10], "big"): r for r in app.records
    }
    if len(objects) != len(app.records):
        raise ValueError("Ambiguous native objects prevent omitted-field type qualification.")
    for field in added:
        cid, instance, pid = field["class"], field["instance"], field["property"]
        record = objects.get(cid << 22 | instance)
        if record is None:
            raise ValueError("An omitted saved field no longer has its original native object.")
        expected = ROOT_TYPES.get(pid) if record is app.root else MODULE_TYPES.get((cid, pid))
        versions = app.summary()["format_versions"]
        if (versions["acs"], versions["dmcs"]) in ANALOG_DEFAULT_FORMATS:
            expected = ANALOG_DEFAULT_TYPES.get((cid, pid), expected)
        if (cid, pid) == (251, 978) and app.summary()["format_versions"] == {"acs": 60, "dmcs": 60}:
            # The native 6.0 application definition declares this actuator
            # field as an application-persistent UnsignedLong. Later schemas
            # remove it; do not generalize it to another data-model release.
            expected = 2
        if expected is None and pid in (15, 33):
            declared = app.reader.scalar(record, 75)
            if isinstance(declared, str) and int(ObjectIdentifier(declared)[0]) in (3, 4, 5):
                expected = 2
        if expected is None:
            raise ValueError(
                f"Unqualified omitted application property {cid}:{pid}. Its storage type alone does not establish a transferable application type. Original files are retained."
            )
        prop = record["properties"][pid]
        raw = app.data[prop["value_start_offset"] : prop["value_end_offset"]]
        if raw[-1:] != b"\x2f":
            raise ValueError("Omitted application property has an unclosed value.")
        tags = list(TagList.decode(PDUData(raw[:-1])))
        valid = (
            (
                len(tags) == 1
                and tags[0].tag_class == TagClass.application
                and tags[0].tag_number == 2
                and len(tags[0].tag_data) == 1
            )
            if expected == "unsigned-byte"
            else (
                len(tags) == 5
                and all(
                    t.tag_class == TagClass.application
                    and t.tag_number == 2
                    and len(t.tag_data) == 1
                    for t in tags
                )
            )
            if expected == "five-unsigned"
            else (
                len(tags) == 1
                and tags[0].tag_class == TagClass.application
                and tags[0].tag_number == expected
            )
        )
        if not valid:
            raise ValueError(
                f"Omitted saved property {cid}:{pid} does not match its qualified application datatype."
            )
    return {"profile": PROFILE, "qualified_fields": len(added), "model_inventory_used": False}
