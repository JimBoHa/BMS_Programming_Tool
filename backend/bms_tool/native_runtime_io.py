"""Source-pinned local I/O copies, including saved-effective factory identities.

No field authority is created by this compiler. A separate transfer service must
bind the original capture, actual identity, interface, fresh settings and review.
"""

import math
import re

from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import (
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    TagClass,
    TagList,
    Unsigned,
)
from pydantic import Field, model_validator

from .hardware_survey import model_capacity
from .models import StrictModel
from .moi_identity import MoiIdentity, controller_name, seal, sha
from .moi_parameters import ParameterApplication
from .native_inputs import archive, encoded, native_record, replace_properties
from .native_parameter_qualification import qualify_parameter_additions

PROFILE = "native-saved-effective-local-io/1"
FORMATS = {(66, 65)}
CV_MODELS = {
    "M4-CVM03050-0",
    "M4-CVM03050-0P",
    "M4-CVE03050-0P",
    "F4-CVM03050-0",
    "F4-CVM03050-0P",
    "F4-CVE03050-0P",
}


def effective_source(files, identity):
    if set(files) != {3, 11, 12} or identity.get("vendor-identifier") != 5:
        raise ValueError("A complete native capture and exact native-family identity are required.")
    original = MoiIdentity(files[3])
    summary = original.summary()
    versions = summary["format_versions"]
    if (versions["acs"], versions["dmcs"]) not in FORMATS:
        raise ValueError("Saved-effective I/O requires a separately qualified format pair.")
    device = ObjectIdentifier(identity["device"])
    if int(device[0]) != 8 or not 1 <= device[1] <= 4194302:
        raise ValueError("Use an actual responding Device identity.")
    source = files[3]
    factory = original.instance != device[1]
    if factory:
        if original.instance != 1 or original.ref != "8-1" or original.root["class_id"] != 194:
            raise ValueError("An unmatched native root is not a qualified factory identity.")
        query = dict(
            source_sha256=original.source_sha256, expected_instance=1, new_instance=device[1]
        )
        review = original.preview(**query)
        source, _ = original.export(**query, plan_sha256=review["plan_sha256"])
    parameters = ParameterApplication(source, files[11], files[12])
    output, merge = parameters.compile()
    actual = MoiIdentity(output)
    matched = {(r["class"], r["instance"], r["property"]) for r in parameters.parameters}
    if (
        factory
        and not {
            (194, device[1], 75),
            (194, device[1], 2390),
            (194, device[1], 70),
        }
        <= matched
    ):
        raise ValueError("Factory identity requires saved Device identifier, name and model.")
    if (
        actual.instance != device[1]
        or actual.summary()["name"] != identity["object-name"]
        or actual.summary()["model"] != identity["model-name"]
        or actual.summary()["format_versions"] != versions
    ):
        raise ValueError("Saved-effective source differs from the independently read identity.")
    qualified = qualify_parameter_additions(output, merge)
    return actual, {
        "profile": PROFILE,
        "original_file_sha256": {str(k): sha(v) for k, v in files.items()},
        "original_identity": summary,
        "effective_identity": actual.summary(),
        "factory_identity_materialized": factory,
        "saved_parameter_merge": merge,
        "parameter_type_qualification": qualified,
        "controller_queries": False,
        "controller_writes": False,
    }


class RuntimeIOEdit(StrictModel):
    action: str
    object_instance: int = Field(ge=1, le=4194302, strict=True)
    slot: int = Field(ge=1, le=3, strict=True)
    name: str | None = None
    description: str = Field(default="", max_length=128)
    expected_slot: int | None = Field(default=None, ge=1, le=5, strict=True)

    @model_validator(mode="after")
    def shape(self):
        if self.description:
            controller_name(self.description)
        if self.action == "allocate-binary":
            if self.name is None or self.expected_slot is not None:
                raise ValueError("Binary allocation requires a new name and no old slot.")
            controller_name(self.name)
        elif self.action == "binary-output-terminal":
            if (
                self.name is not None
                or self.description
                or self.expected_slot is None
                or self.expected_slot == self.slot
            ):
                raise ValueError("Output movement requires distinct old/new slots and no rename.")
        else:
            raise ValueError("Select binary input allocation or binary output terminal movement.")
        return self


def _local(app, row, kind):
    ref = app.reader.scalar(row, 32527)
    return isinstance(ref, str) and bool(re.fullmatch(re.escape(app.ref) + rf"/{kind}_[0-9]+", ref))


def configuration_guard(app):
    """Bind every effective field except separately documented runtime outputs."""
    rows = []
    for r in app.records:
        props = []
        public = app.reader.scalar(r, 75)
        binary = isinstance(public, str) and int(ObjectIdentifier(public)[0]) in (3, 4, 5)
        for pid, p in sorted(r["properties"].items()):
            value = app.reader.scalar(r, pid)
            if r["class_id"] == 570 and pid == 3506:
                if not isinstance(value, float) or not math.isfinite(value):
                    raise ValueError("Calculated airflow offset has no finite Real type.")
                continue
            if binary and pid in (15, 33):
                if type(value) is not int or not 0 <= value <= 4294967295:
                    raise ValueError("Runtime binary counter has no Unsigned32 type.")
                continue
            props.append((pid, app.data[p["value_start_offset"] : p["value_end_offset"]].hex()))
        rows.append((r["class_id"], app.data[r["offset"] + 6 : r["offset"] + 10].hex(), props))
    return seal({"header": app.data[:14].hex(), "records": rows})


def _network_only_sa(app, row):
    """Admit explicit mapped network values, never physical SA I/O maps."""
    prop = row["properties"].get(1248)
    if prop is None:
        raise ValueError("An SA device has no qualified mapped-value declaration.")
    raw = app.data[prop["value_start_offset"] : prop["value_end_offset"]]
    if raw[-1:] != b"\x2f":
        raise ValueError("Unclosed SA mapped-value declaration.")
    tags = TagList.decode(PDUData(raw[:-1]))
    stack, mapped, first = [], set(), False
    for tag in tags:
        if tag.tag_class == TagClass.opening:
            if not stack:
                if tag.tag_number != 3:
                    raise ValueError("Unknown SA mapped-value group.")
                first = True
            stack.append(tag.tag_number)
        elif tag.tag_class == TagClass.closing:
            if not stack or stack.pop() != tag.tag_number or first:
                raise ValueError("Invalid SA mapped-value framing.")
        elif not stack:
            raise ValueError("Unexpected SA mapped-value content.")
        elif first:
            if len(stack) != 1 or tag.tag_class != TagClass.application or tag.tag_number != 12:
                raise ValueError("SA mapping lacks an explicit local Object Identifier.")
            obj = tag.app_to_object()
            if int(obj[0]) not in (2, 5, 19, 40) or str(obj) in mapped:
                raise ValueError("Physical/duplicate SA mappings require another host profile.")
            if sum(app.reader.scalar(r, 75) == str(obj) for r in app.records) != 1:
                raise ValueError("SA mapped value has no unique native owner.")
            mapped.add(str(obj))
            first = False
        elif len(stack) == 1 and tag.tag_class == TagClass.application and tag.tag_number == 12:
            raise ValueError("Ambiguous local SA mapping identifier.")
        if len(stack) > 8 or len(mapped) > 64:
            raise ValueError("SA mapped-value declaration exceeds this profile.")
    if stack or not mapped:
        raise ValueError("Incomplete SA mapped-value declaration.")
    return {"declaration_sha256": sha(raw), "mapped_network_values": sorted(mapped)}


def compile_io(files, identity, edit):
    edit = RuntimeIOEdit.model_validate(edit)
    app, proof = effective_source(files, identity)
    capacity = model_capacity(identity["model-name"])
    if capacity is None or identity["model-name"] not in CV_MODELS:
        raise ValueError(
            "This local I/O profile requires separately documented CV terminal capacity."
        )
    if any(r["class_id"] in (598, 243, 671, 673) for r in app.records):
        raise ValueError(
            "Configured expansion modules require a separately qualified host profile."
        )
    sa_proof = [_network_only_sa(app, r) for r in app.records if r["class_id"] == 910]
    for r in app.records:
        if r["class_id"] in (240, 242, 239, 241, 251) and (
            2577 in r["properties"] or app.reader.scalar(r, 3645) not in (None, 0)
        ):
            raise ValueError("A physical I/O device reference needs another host profile.")
    new, replaced = None, None
    if edit.action == "allocate-binary":
        if edit.slot not in capacity["universal_inputs"]:
            raise ValueError("Select a documented local universal input.")
        for r in app.records:
            if (
                r["class_id"] == 242
                and int.from_bytes(app.data[r["offset"] + 6 : r["offset"] + 10], "big") & 4194303
                == edit.object_instance
            ):
                raise ValueError("The native input identifier already exists.")
            if app.reader.scalar(r, 75) == f"binary-input,{edit.object_instance}":
                raise ValueError("The proposed public input identifier already exists.")
            if app.reader.scalar(r, 2390) == edit.name:
                raise ValueError("The proposed input name already exists.")
            if r["class_id"] in (240, 242):
                slot = app.reader.scalar(r, 519)
                label = app.reader.scalar(r, 31)
                if slot in capacity["universal_inputs"] and label != f"UI IN{slot}":
                    raise ValueError("Unknown physical input binding prevents allocation.")
                if slot == edit.slot:
                    raise ValueError("The proposed input terminal is already allocated.")
                if not _local(app, r, 0 if r["class_id"] == 240 else 3):
                    raise ValueError("An ambiguous hardware host prevents local input allocation.")
        oid = f"binary-input,{edit.object_instance}"
        props = {
            32527: CharacterString(f"{app.ref}/3_{edit.object_instance}"),
            4: CharacterString("On"),
            28: CharacterString(edit.description),
            31: CharacterString(f"UI IN{edit.slot}"),
            46: CharacterString("Off"),
            75: ObjectIdentifier(oid),
            84: Enumerated(0),
            519: Unsigned(edit.slot),
            931: Enumerated(83),
            2390: CharacterString(edit.name),
        }
        new = native_record(242, edit.object_instance, [(k, encoded(v)) for k, v in props.items()])
        changes = [
            {
                "object": oid,
                "operation": "allocate",
                "slot": edit.slot,
                "name": edit.name,
                "polarity": "normal",
                "states": ["Off", "On"],
            }
        ]
    else:
        oid = f"binary-output,{edit.object_instance}"
        matches = [
            r for r in app.records if r["class_id"] == 239 and app.reader.scalar(r, 75) == oid
        ]
        if len(matches) != 1 or not _local(app, matches[0], 4):
            raise ValueError("Select one unambiguous local configured binary output.")
        replaced = matches[0]
        old = app.reader.scalar(replaced, 990)
        label = app.reader.scalar(replaced, 31)
        if (
            old != edit.expected_slot
            or label != (f"BO OUT{old}" if old <= 3 else f"CO OUT{old - 3}")
            or app.reader.scalar(replaced, 518) != 0
        ):
            raise ValueError("The current binary output allocation/setup differs from the review.")
        for r in app.records:
            if r is replaced or r["class_id"] not in (239, 241, 251):
                continue
            if any(app.reader.scalar(r, pid) == edit.slot for pid in (990, 991, 519)):
                raise ValueError("The destination output terminal is already allocated.")
        new = replace_properties(
            app,
            replaced,
            {
                31: encoded(CharacterString(f"BO OUT{edit.slot}")),
                990: encoded(Unsigned(edit.slot)),
            },
        )
        changes = [
            {
                "object": oid,
                "operation": "move",
                "before_slot": old,
                "after_slot": edit.slot,
                "before_device_type": label,
                "after_device_type": f"BO OUT{edit.slot}",
            }
        ]
    records = [
        new if r is replaced else app.data[r["offset"] : r["end_offset"]] for r in app.records
    ]
    if replaced is None:
        records.append(new)
    output = archive(app, records)
    checked = MoiIdentity(output)
    expected_count = len(app.records) + (replaced is None)
    if len(checked.records) != expected_count or checked.instance != app.instance:
        raise ValueError("Compiled I/O copy changed unrelated membership or Device identity.")
    for before, after in zip(app.records, checked.records[: len(app.records)], strict=True):
        if before is replaced:
            continue
        if (
            app.data[before["offset"] : before["end_offset"]]
            != checked.data[after["offset"] : after["end_offset"]]
        ):
            raise ValueError("An unrelated native record changed during I/O compilation.")
    return output, {
        **proof,
        "edit": edit.model_dump(),
        "changes": changes,
        "effective_source_sha256": app.source_sha256,
        "configuration_guard": configuration_guard(app),
        "output_sha256": sha(output),
        "native_output_sha256": sha(checked.data),
        "object_id": oid,
        "object_name": edit.name if replaced is None else app.reader.scalar(replaced, 2390),
        "all_other_effective_records_preserved": True,
        "graph_wires_changed": False,
        "original_record_count": len(app.records),
        "output_record_count": len(checked.records),
        "hardware_reference": capacity["source"],
        "network_only_sa_devices": sa_proof,
    }
