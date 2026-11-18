"""Reversible, unconnected NetSensor compatibility trials in native applications.

The legacy Net Sensor Device/AI schema is separate from the package-backed
SA Device Integration schema. Existing public points and program references
remain intact. A trial is not an application migration or sensor firmware write.
"""

import math
import re
from typing import Literal

from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    ClosingTag,
    Enumerated,
    ObjectIdentifier,
    OpeningTag,
    Real,
    TagClass,
    TagList,
    Unsigned,
)
from pydantic import Field, field_validator

from .application_preservation import runtime_parameter_changes
from .models import StrictModel
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .native_inputs import archive, encoded, native_record, raw_property, replace_properties
from .native_parameter_qualification import qualify_parameter_additions

PROFILE = "native-netsensor-compatibility-trial/1"
SCOPE = (
    "Temporarily disable one configured NS8000 integration and allocate unconnected "
    "legacy NetSensor temperature readers at up to eight reviewed SA addresses. "
    "Existing point identities, references, logic, supervisor objects and settings remain "
    "unchanged. Apply and Restore transfer File 3 and can interrupt control. A successful "
    "download does not establish sensor communication or physical acceptance."
)
HASH = r"^[a-f0-9]{64}$"
FORMATS = {(66, 65)}


class TrialEdit(StrictModel):
    sensor_ref: str = Field(min_length=1, max_length=512, strict=True)
    sensor_sha256: str = Field(pattern=HASH)
    addresses: list[int] = Field(min_length=1, max_length=8)
    first_instance: int = Field(ge=1, le=4194287, strict=True)
    units: Literal[62, 64] = 64

    @field_validator("addresses", mode="before")
    @classmethod
    def macs(cls, value):
        if (
            not isinstance(value, list)
            or not 1 <= len(value) <= 8
            or any(type(v) is not int or not 199 <= v <= 206 for v in value)
            or value != sorted(set(value))
        ):
            raise ValueError("Choose one sorted, unique page of NetSensor addresses 199–206.")
        return value


def source_app(files):
    if set(files) != {3, 11, 12}:
        raise ValueError("Select a complete native File 3/11/12 snapshot.")
    merged, parameters = ParameterApplication(files[3], files[11], files[12]).compile()
    qualification = qualify_parameter_additions(merged, parameters)
    app, original = MoiIdentity(merged), MoiIdentity(files[3])
    versions = app.summary()["format_versions"]
    if (versions["acs"], versions["dmcs"]) not in FORMATS:
        raise ValueError("This native application/data-model pair has no NetSensor trial profile.")
    if any(app.summary()[k] != original.summary()[k] for k in ("instance", "name", "model")):
        raise ValueError("The saved source changed controller identity; capture again.")
    identifiers = [app.reader.scalar(r, 75) for r in app.records if app.reader.scalar(r, 75)]
    native_ids = [app.data[r["offset"] + 6 : r["offset"] + 10] for r in app.records]
    if len(set(identifiers)) != len(identifiers) or len(set(native_ids)) != len(native_ids):
        raise ValueError("Ambiguous native/public identities prevent a sensor-definition trial.")
    return app, {"saved_parameter_merge": parameters, "parameter_types": qualification}


def effective_guard(app):
    """Guard all configuration; only documented changing runtime fields are omitted."""
    rows = []
    for record in app.records:
        obj = app.reader.scalar(record, 75)
        binary = isinstance(obj, str) and int(ObjectIdentifier(obj)[0]) in (3, 4, 5)
        values = []
        for pid in record["properties"]:
            value = app.reader.scalar(record, pid)
            if (record["class_id"], pid) == (570, 3506):
                if not isinstance(value, float) or not math.isfinite(value):
                    raise ValueError("Calculated flow offset lacks a finite native Real value.")
                continue
            if binary and pid in (15, 33):
                if type(value) is not int or not 0 <= value <= 4294967295:
                    raise ValueError("Runtime binary counter lacks its native Unsigned value.")
                continue
            values.append((pid, raw_property(app, record, pid).hex()))
        rows.append(
            (
                record["class_id"],
                app.data[record["offset"] + 6 : record["offset"] + 10].hex(),
                values,
            )
        )
    return seal({"header": app.data[:14].hex(), "records": rows})


def record_hash(app, record):
    return sha(app.data[record["offset"] : record["end_offset"]])


def sensor_sources(files):
    app, _ = source_app(files)
    result = []
    for record in app.records:
        ref = app.reader.scalar(record, 32527)
        if (
            record["class_id"] != 910
            or not isinstance(ref, str)
            or not re.fullmatch(re.escape(app.ref) + r"/307_2\.910_[0-9]+", ref)
        ):
            continue
        # DeviceInfo is a typed composite. Only an explicit NS8000 family
        # string admits this operation; a display name is not a driver type.
        info = raw_property(app, record, 4872)
        if info is None:
            continue
        tags = list(TagList.decode(PDUData(info[:-1])))
        expected = [
            (0, 9),
            (0, 2),
            (0, 9),
            (0, 7),
            (0, 9),
            (0, 7),
            (0, 7),
            (0, 9),
            (0, 9),
            (0, 2),
            (2, 3),
            (0, 12),
            (0, 9),
            (0, 2),
            (0, 12),
            (3, 3),
            (0, 7),
            (0, 2),
            (0, 7),
        ]
        family = (
            str(tags[16].app_to_object())
            if (
                [(int(t.tag_class), t.tag_number) for t in tags] == expected
                and tags[16].tag_class == TagClass.application
                and tags[16].tag_number == 7
            )
            else None
        )
        mac = app.reader.scalar(record, 2858)
        enabled = app.reader.scalar(record, 673)
        if family != "NS8000" or type(mac) is not int or not 199 <= mac <= 206:
            continue
        instance = int(ref.rsplit("_", 1)[1])
        if not 0 <= instance <= 4194302:
            raise ValueError("The selected NS8000 native identifier is outside the supported range.")
        if (
            app.data[record["offset"] + 6 : record["offset"] + 10]
            != (910 << 22 | instance).to_bytes(4, "big")
            or raw_property(app, record, 75) != encoded(ObjectIdentifier((910, instance))) + b"\x2f"
            or record["properties"][2858]["scalar"]["datatype"] != "Unsigned"
            or (673 in record["properties"] and type(enabled) is not bool)
        ):
            raise ValueError(
                "The NS8000 definition has an unqualified identity/address/enable datatype."
            )
        if enabled not in (None, True) or (enabled is not None and type(enabled) is not bool):
            continue
        result.append(
            {
                "sensor_ref": ref,
                "sensor_sha256": record_hash(app, record),
                "object_id": app.reader.scalar(record, 75),
                "name": app.reader.scalar(record, 2390),
                "address": mac,
                "enabled_in_archive": enabled,
            }
        )
    return result


def trial_rows(app, edit):
    rows = []
    for index, mac in enumerate(edit.addresses):
        parent, point = edit.first_instance + index * 2, edit.first_instance + index * 2 + 1
        ref = f"{app.ref}/307_2.627_{parent}"
        rows.append(
            {
                "address": mac,
                "device_object": f"627,{parent}",
                "temperature_object": f"analog-input,{point}",
                "sensor_ref": ref,
                "temperature_ref": f"{ref}.0_{point}",
                "units": edit.units,
                "device_name": f"NetSensor trial {mac}",
                "temperature_name": f"Sensor trial {mac} temperature",
            }
        )
    return rows


def compile_trial(files, edit):
    edit = TrialEdit.model_validate(edit)
    app, proof = source_app(files)
    sensors = sensor_sources(files)
    selected = next((s for s in sensors if s["sensor_ref"] == edit.sensor_ref), None)
    if selected is None or selected["sensor_sha256"] != edit.sensor_sha256:
        raise ValueError("The selected NS8000 definition changed; capture and review again.")
    record = next(r for r in app.records if app.reader.scalar(r, 32527) == edit.sensor_ref)
    for other in app.records:
        ref, mac = app.reader.scalar(other, 32527), app.reader.scalar(other, 2858)
        if other is not record and isinstance(ref, str) and ref.startswith(app.ref + "/307_2."):
            if "." not in ref.split("/307_2.", 1)[1] and mac in edit.addresses:
                raise ValueError("Another configured SA device already owns a trial address.")
    rows = trial_rows(app, edit)
    public = {app.reader.scalar(r, 75) for r in app.records}
    native = {
        int.from_bytes(app.data[r["offset"] + 6 : r["offset"] + 10], "big") for r in app.records
    }
    names = {app.reader.scalar(r, 2390) for r in app.records}
    created = []
    for row in rows:
        parent, point = (
            int(row[key].split(",")[1]) for key in ("device_object", "temperature_object")
        )
        if (
            (627 << 22 | parent) in native
            or (628 << 22 | point) in native
            or row["device_object"] in public
            or row["temperature_object"] in public
            or row["device_name"] in names
            or row["temperature_name"] in names
        ):
            raise ValueError("A proposed NetSensor trial identity or name is already occupied.")
        reference = bytes(
            TagList(
                [*CharacterString(row["temperature_ref"]).encode(), OpeningTag(3), ClosingTag(3)]
            )
            .encode()
            .pduData
        )
        created.append(
            native_record(
                627,
                parent,
                [
                    (32527, encoded(CharacterString(row["sensor_ref"]))),
                    (75, encoded(ObjectIdentifier((627, parent)))),
                    (2390, encoded(CharacterString(row["device_name"]))),
                    (2858, encoded(Unsigned(row["address"]))),
                    (941, reference),
                    (673, encoded(Boolean(True))),
                    (1396, encoded(Boolean(True))),
                ],
            )
        )
        created.append(
            native_record(
                628,
                point,
                [
                    (32527, encoded(CharacterString(row["temperature_ref"]))),
                    (75, encoded(ObjectIdentifier((0, point)))),
                    (2390, encoded(CharacterString(row["temperature_name"]))),
                    (28, encoded(CharacterString("Unconnected compatibility trial"))),
                    (31, encoded(CharacterString("NetSensor"))),
                    (117, encoded(Enumerated(edit.units))),
                    (22, encoded(Real(0.3 if edit.units == 64 else 0.1))),
                    (69, encoded(Real(32 if edit.units == 64 else 0))),
                    (65, encoded(Real(104 if edit.units == 64 else 40))),
                    (673, encoded(Boolean(True))),
                ],
            )
        )
    records = []
    for old in app.records:
        raw = app.data[old["offset"] : old["end_offset"]]
        if old is record:
            raw = replace_properties(app, old, {673: encoded(Boolean(False))})
        records.append(raw)
    # Insert before opaque trailing metadata, preserving all existing order.
    index = len(records)
    while index and 32527 not in app.records[index - 1]["properties"]:
        index -= 1
    records[index:index] = created
    output = archive(app, records)
    observed = MoiIdentity(output)
    expected = [*records]
    if len(observed.records) != len(expected) or any(
        observed.data[r["offset"] : r["end_offset"]] != raw
        for r, raw in zip(observed.records, expected, strict=True)
    ):
        raise ValueError("NetSensor trial changed an unreviewed native record.")
    compilation = {
        "profile": PROFILE,
        "edit": edit.model_dump(),
        "original_sensor": selected,
        "trial_points": rows,
        "added_native_records": len(created),
        "configuration_guard": effective_guard(app),
        "payload_sha256": sha(output),
        "native_payload_sha256": sha(observed.data),
        "existing_points_and_wires_preserved": True,
        "original_enabled_property_hex": (raw_property(app, record, 673) or b"").hex(),
        **proof,
    }
    return output, compilation


def verify_trial(files, output, *, expected_native_sha256):
    """Image acceptance and saved-configuration verification, not sensor health."""
    app = MoiIdentity(files[3])
    if sha(app.data) != expected_native_sha256 or app.data != MoiIdentity(output).data:
        raise ValueError("Readback differs from the exact reviewed native application.")
    post = ParameterApplication(files[3], files[11], files[12])
    current, counters, calculated = runtime_parameter_changes(app, post)
    return {
        "native_image_matches": True,
        "saved_parameters_verified": current["matched_parameters"],
        "runtime_counter_changes": counters,
        "device_calculated_changes": calculated,
    }


def remove_property(app, record, pid):
    prop = record["properties"].get(pid)
    if prop is None:
        return app.data[record["offset"] : record["end_offset"]]
    width = max(1, (pid.bit_length() + 7) // 8)
    first = prop["value_start_offset"] - (2 + width)
    if (
        app.data[first : prop["value_start_offset"]]
        != bytes([8 | width]) + pid.to_bytes(width, "big") + b"\x2e"
    ):
        raise ValueError("The restored property has unsupported identifier framing.")
    return (
        app.data[record["offset"] : first]
        + app.data[prop["value_end_offset"] : record["end_offset"]]
    )


def compile_trial_restore(current_files, original_files, edit):
    """Remove only the exact owned trial objects; retain all fresh original settings."""
    edit = TrialEdit.model_validate(edit)
    original, _ = source_app(original_files)
    current, proof = source_app(current_files)
    proposed, installation = compile_trial(original_files, edit)
    expected = MoiIdentity(proposed)
    rows = installation["trial_points"]
    created = {row[key] for row in rows for key in ("device_object", "temperature_object")}
    refs = {row[key] for row in rows for key in ("sensor_ref", "temperature_ref")}
    by_oid = {
        current.reader.scalar(r, 75): r for r in current.records if current.reader.scalar(r, 75)
    }
    if not created <= set(by_oid):
        raise ValueError("An owned NetSensor trial object is absent; inspect the retained receipt.")
    original_sensor = next(
        r for r in original.records if original.reader.scalar(r, 32527) == edit.sensor_ref
    )
    records = []
    for record in current.records:
        oid = current.reader.scalar(record, 75)
        if oid in created:
            expected_record = next(
                r for r in expected.records if expected.reader.scalar(r, 75) == oid
            )
            # Trial fields may acquire saved values, but their immutable native
            # class, reference, address and role must remain the owned objects.
            for pid in (75, 32527, 2390, 2858, 941, 31, 117):
                if raw_property(expected, expected_record, pid) != raw_property(
                    current, record, pid
                ):
                    raise ValueError(
                        "The owned trial definition changed; inspect before restoration."
                    )
            continue
        for prop in record["properties"].values():
            for tag in prop["tags"]:
                if tag.tag_class != TagClass.application:
                    continue
                if tag.tag_number == 7 and any(
                    str(tag.app_to_object()).startswith(ref) for ref in refs
                ):
                    raise ValueError("An existing program object now references a trial point.")
                if tag.tag_number == 12 and str(tag.app_to_object()) in created:
                    raise ValueError("An existing program object now links a trial identifier.")
        raw = current.data[record["offset"] : record["end_offset"]]
        if current.reader.scalar(record, 32527) == edit.sensor_ref:
            previous = raw_property(original, original_sensor, 673)
            raw = (
                replace_properties(current, record, {673: previous[:-1]})
                if previous is not None
                else remove_property(current, record, 673)
            )
        records.append(raw)
    output = archive(current, records)
    restored = MoiIdentity(output)
    if effective_guard(restored) != effective_guard(original):
        raise ValueError(
            "Original program/settings changed during the trial; no automatic overwrite is allowed."
        )
    return output, {
        "profile": PROFILE,
        "action": "restore",
        "edit": edit.model_dump(),
        "configuration_guard": effective_guard(current),
        "payload_sha256": sha(output),
        "native_payload_sha256": sha(restored.data),
        "original_sensor": installation["original_sensor"],
        "trial_points": rows,
        "removed_native_records": len(created),
        "existing_points_and_wires_preserved": True,
        **proof,
    }
