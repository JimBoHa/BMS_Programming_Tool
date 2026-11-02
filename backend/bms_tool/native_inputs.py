"""Typed local universal-input allocation and electrical setup in native images."""

import math
import re
import struct
import zlib
from typing import Literal

from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Real, Unsigned
from pydantic import Field, field_validator, model_validator

from .application_preservation import runtime_parameter_changes
from .device_details import DeviceDetailsRequest
from .hardware_survey import model_capacity
from .models import StrictModel
from .moi_identity import MoiIdentity, controller_name, seal, sha
from .moi_parameters import ParameterApplication
from .native_parameter_qualification import qualify_parameter_additions

PROFILE = "native-local-universal-input-transfer/1"
SCOPE = (
    "Allocate one unconnected local universal analog input or edit one existing local input's "
    "electrical mode and reviewed scaling. Preserve other records, wires, controller identity "
    "and fresh saved settings. Apply transfers File 3 and can restart control. No output, "
    "integral sensor, SA module allocation, graph connection or supervisor edit."
)
# Actual native application/data-model pairs; release labels are not these numbers.
FORMATS = {(60, 60), (62, 62), (66, 65)}
# Set 360: user range ohms=0, volts=1, current=2. Set 507 uses native units.
MODES = {
    "voltage": {"setup": 1, "field_units": 5, "label": "0–10 VDC", "low": 0, "high": 10},
    "resistance": {"setup": 0, "field_units": 4, "label": "Resistance", "low": 0, "high": 600000},
    "current": {"setup": 2, "field_units": 2, "label": "4–20 mA", "low": 4, "high": 20},
}
CONFIG = {
    518: "setup",
    2180: "field_units",
    1293: "input_low",
    1294: "input_high",
    1295: "output_low",
    1296: "output_high",
    117: "units",
    69: "minimum",
    65: "maximum",
}
ENUM_FIELDS = {518, 2180, 117}
UINT = dict(ge=0, le=4194302, strict=True)
HASH = r"^[a-f0-9]{64}$"


class InputConfiguration(StrictModel):
    mode: Literal["voltage", "resistance", "current"]
    input_low: float = Field(strict=True, allow_inf_nan=False)
    input_high: float = Field(strict=True, allow_inf_nan=False)
    output_low: float = Field(strict=True, allow_inf_nan=False)
    output_high: float = Field(strict=True, allow_inf_nan=False)
    units: int = Field(ge=0, le=65535, strict=True)
    minimum: float = Field(strict=True, allow_inf_nan=False)
    maximum: float = Field(strict=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self):
        if self.input_low >= self.input_high or self.output_low == self.output_high:
            raise ValueError(
                "The electrical endpoints must increase and engineering endpoints must differ."
            )
        if self.minimum > min(self.output_low, self.output_high) or self.maximum < max(
            self.output_low, self.output_high
        ):
            raise ValueError("Present-value limits must contain the engineering scaling range.")
        rounded = {}
        for key in ("input_low", "input_high", "output_low", "output_high", "minimum", "maximum"):
            try:
                value = struct.unpack(">f", struct.pack(">f", getattr(self, key)))[0]
            except OverflowError as exc:
                raise ValueError("Input scaling exceeds finite native Real32 storage.") from exc
            if not -3.4028234663852886e38 <= value <= 3.4028234663852886e38:
                raise ValueError("Input scaling requires finite native Real32 values.")
            rounded[key] = value
        if (
            rounded["input_low"] >= rounded["input_high"]
            or rounded["output_low"] == rounded["output_high"]
        ):
            raise ValueError("Native Real32 rounding collapses the scaling endpoints.")
        return self


class InputEdit(StrictModel):
    action: Literal["allocate", "mode", "remove-allocated"]
    object_instance: int = Field(**UINT)
    slot: int = Field(ge=1, le=255, strict=True)
    configuration_sha256: str | None = Field(default=None, pattern=HASH)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    configuration: InputConfiguration | None = None
    allocation_receipt: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @field_validator("name")
    @classmethod
    def visible_name(cls, value):
        return controller_name(value) if value is not None else value

    @model_validator(mode="after")
    def action_fields(self):
        if self.action == "allocate":
            if (
                self.name is None
                or self.configuration is None
                or self.configuration_sha256 is not None
                or self.allocation_receipt is not None
            ):
                raise ValueError("Allocation requires a new name and configuration only.")
        elif self.action == "mode":
            if (
                self.configuration_sha256 is None
                or self.configuration is None
                or self.name is not None
                or self.allocation_receipt is not None
            ):
                raise ValueError(
                    "Mode editing requires the captured configuration and its proposed replacement."
                )
        elif (
            self.configuration_sha256 is None
            or self.allocation_receipt is None
            or self.configuration is not None
            or self.name is not None
        ):
            raise ValueError(
                "Removal requires a captured configuration and its original allocation receipt."
            )
        return self


class InputSource(DeviceDetailsRequest):
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    snapshot_sha256: str = Field(pattern=HASH)


class InputSupport(InputSource):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class InputPreview(InputSupport):
    edit: InputEdit


class InputLocalSource(StrictModel):
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    snapshot_sha256: str = Field(pattern=HASH)


class InputCopy(InputLocalSource):
    edit: InputEdit
    expected_review_sha256: str | None = Field(default=None, pattern=HASH)


class InputApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: str = Field(pattern=HASH)
    physical_wiring_confirmed: bool = Field(strict=True)
    input_change_confirmed: bool = Field(strict=True)
    application_transfer_confirmed: bool = Field(strict=True)


def input_capabilities(model):
    capacity = model_capacity(model)
    if capacity is None:
        raise ValueError(
            "The actual controller model has no qualified physical input-capacity evidence."
        )
    modes = {name: dict(value) for name, value in MODES.items() if name != "current"}
    if model.strip().upper() == "FX-PCG2611-0":
        modes["current"] = dict(MODES["current"])
        modes["resistance"]["high"] = 2000
    return {"capacity": capacity, "modes": modes, "host": "local"}


def encoded(value):
    return bytes(value.encode().encode().pduData)


def native_record(cid, instance, props):
    body = bytearray(cid.to_bytes(2, "little") + b"\x02\x00\x0e\x1c")
    body.extend((cid << 22 | instance).to_bytes(4, "big") + b"\x0f\x1e")
    for pid, raw in props:
        width = max(1, (pid.bit_length() + 7) // 8)
        body.extend(bytes([8 | width]) + pid.to_bytes(width, "big") + b"\x2e" + raw + b"\x2f")
    return bytes(body + b"\x1f")


def archive(editor, records):
    if not 1 <= len(records) <= 20000:
        raise ValueError("Input allocation exceeds the native record bound.")
    data = bytearray(editor.data[:14])
    struct.pack_into("<I", data, 10, len(records))
    styles, previous = {}, 14
    for record in editor.records:
        styles[editor.data[record["offset"] + 6 : record["offset"] + 10]] = (
            record["offset"] - previous == 6
        )
        previous = record["end_offset"]
    for raw in records:
        extended = styles.get(raw[6:10], False) or len(raw) + 2 > 65535
        data.extend(
            b"\x00\x00" + struct.pack("<I", len(raw) + 6)
            if extended
            else struct.pack("<H", len(raw) + 2)
        )
        data.extend(raw)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("Input allocation exceeds the expanded native application bound.")
    if not editor.compressed:
        return bytes(data)
    compressor = zlib.compressobj(level=9, wbits=-15)
    return (
        editor.source[:10]
        + compressor.compress(data)
        + compressor.flush()
        + struct.pack("<II", zlib.crc32(data), len(data))
    )


def raw_property(app, record, pid):
    prop = record["properties"].get(pid)
    return app.data[prop["value_start_offset"] : prop["value_end_offset"]] if prop else None


def configuration_guard(app, record):
    return seal(
        {
            str(pid): (raw_property(app, record, pid) or b"").hex()
            for pid in (*CONFIG, 31, 519, 75, 32527, 2390)
        }
    )


def record_instance(app, record):
    return int.from_bytes(app.data[record["offset"] + 6 : record["offset"] + 10], "big") & 4194303


def replace_properties(app, record, replacements):
    """Replace value leaves without reordering/re-encoding unrelated properties."""
    data = bytearray(app.data[record["offset"] : record["end_offset"]])
    for pid in sorted(
        set(replacements) & set(record["properties"]),
        key=lambda p: record["properties"][p]["value_start_offset"],
        reverse=True,
    ):
        prop = record["properties"][pid]
        first, last = (
            prop[k] - record["offset"] for k in ("value_start_offset", "value_end_offset")
        )
        data[first:last] = replacements[pid] + b"\x2f"
    additions = bytearray()
    for pid in sorted(set(replacements) - set(record["properties"])):
        width = max(1, (pid.bit_length() + 7) // 8)
        additions.extend(
            bytes([8 | width]) + pid.to_bytes(width, "big") + b"\x2e" + replacements[pid] + b"\x2f"
        )
    if data[-1:] != b"\x1f":
        raise ValueError("Native input record has unsupported property framing.")
    return bytes(data[:-1] + additions + data[-1:])


class NativeInputCompiler:
    def __init__(self, files):
        if set(files) != {3, 11, 12}:
            raise ValueError("Input editing requires a complete native File 3/11/12 capture.")
        merged, self.parameters = ParameterApplication(files[3], files[11], files[12]).compile()
        self.qualification = qualify_parameter_additions(merged, self.parameters)
        self.app = app = MoiIdentity(merged)
        versions = app.summary()["format_versions"]
        if (versions["acs"], versions["dmcs"]) not in FORMATS:
            raise ValueError(
                "This native application/data-model pair has no qualified local input profile."
            )
        self.hardware = input_capabilities(app.summary()["model"])
        self.inputs, self.occupied, self.external_ids = {}, {}, set()
        for r in app.records:
            obj, ref, label, slot = (app.reader.scalar(r, pid) for pid in (75, 32527, 31, 519))
            if isinstance(obj, str):
                if obj in self.external_ids:
                    raise ValueError(
                        "Duplicate public object identities prevent native input allocation."
                    )
                self.external_ids.add(obj)
            if slot is None and not isinstance(label, str):
                continue
            if app.reader.scalar(r, 3645) not in (None, 0):
                continue  # SA records remain untouched; no base-terminal inference.
            direct = isinstance(ref, str) and re.fullmatch(
                re.escape(app.ref) + r"/[0-9]+_[0-9]+", ref
            )
            if not direct:
                if isinstance(label, str) and re.fullmatch(r"UI IN[0-9]+", label):
                    raise ValueError(
                        "An input has an unresolved host; local terminal availability is ambiguous."
                    )
                continue
            if (
                r["class_id"] == 240
                and label == "AI1-Int"
                and slot == 4
                and app.reader.scalar(r, 518) == 9
            ):
                continue  # An integral DPT is never an editable or spare terminal.
            match = re.fullmatch(r"UI IN([0-9]+)", label or "")
            if not match:
                if slot is not None and r["class_id"] in (240, 242):
                    raise ValueError(
                        "Unknown local hardware assignment prevents terminal allocation."
                    )
                continue
            if type(slot) is not int or int(match[1]) != slot or slot in self.occupied:
                raise ValueError("Duplicate or conflicting local terminal assignments.")
            self.occupied[slot] = obj
            if r["class_id"] != 240:
                continue
            if obj != f"analog-input,{record_instance(app, r)}":
                raise ValueError("Analog input public/native identity is inconsistent.")
            self.inputs[obj] = r

    def source(self):
        app = self.app
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "hardware": self.hardware,
            "available_slots": [
                s for s in self.hardware["capacity"]["universal_inputs"] if s not in self.occupied
            ],
            "inputs": [
                {
                    "object_id": obj,
                    "record_ref": app.reader.scalar(r, 32527),
                    "name": app.reader.scalar(r, 2390),
                    "slot": app.reader.scalar(r, 519),
                    "configuration_sha256": configuration_guard(app, r),
                    "configuration": {
                        label: app.reader.scalar(r, pid) for pid, label in CONFIG.items()
                    },
                }
                for obj, r in self.inputs.items()
            ],
            "format_versions": app.summary()["format_versions"],
            "controller_writes": False,
        }

    def proposed_properties(self, edit):
        config = edit.configuration
        if config is None:
            return {}
        mode = self.hardware["modes"].get(config.mode)
        if mode is None or config.input_low < mode["low"] or config.input_high > mode["high"]:
            raise ValueError(
                "The proposed electrical mode/range exceeds the documented controller input capability."
            )
        values = {**config.model_dump(), "setup": mode["setup"], "field_units": mode["field_units"]}
        return {
            pid: encoded((Enumerated if pid in ENUM_FIELDS else Real)(values[label]))
            for pid, label in CONFIG.items()
        }

    def compile(self, edit, *, allocation_origin=None):
        edit = InputEdit.model_validate(edit)
        app, obj = self.app, f"analog-input,{edit.object_instance}"
        changed, rows = self.proposed_properties(edit), []
        record = self.inputs.get(obj)
        if edit.slot not in self.hardware["capacity"]["universal_inputs"]:
            raise ValueError("Choose a documented local universal-input terminal.")
        if edit.action == "allocate":
            if obj in self.external_ids or edit.slot in self.occupied:
                raise ValueError(
                    "The proposed public object or physical terminal is already configured."
                )
            ref = f"{app.ref}/0_{edit.object_instance}"
            if any(
                app.reader.scalar(r, 32527) == ref
                or (r["class_id"] == 240 and record_instance(app, r) == edit.object_instance)
                for r in app.records
            ):
                raise ValueError("The native object or reference already exists.")
            if any(app.reader.scalar(r, 2390) == edit.name for r in app.records):
                raise ValueError("Another application object already uses the proposed input name.")
            props = {
                32527: encoded(CharacterString(ref)),
                75: encoded(ObjectIdentifier(obj)),
                2390: encoded(CharacterString(edit.name)),
                28: encoded(CharacterString("")),
                31: encoded(CharacterString(f"UI IN{edit.slot}")),
                519: encoded(Unsigned(edit.slot)),
                22: encoded(Real(0.01)),
                118: encoded(Unsigned(100)),
                3407: encoded(Enumerated(2)),
                3422: encoded(Enumerated(18)),
                **changed,
            }
            new_record = native_record(
                240, edit.object_instance, [(32527, props.pop(32527)), *sorted(props.items())]
            )
        else:
            if (
                record is None
                or app.reader.scalar(record, 519) != edit.slot
                or configuration_guard(app, record) != edit.configuration_sha256
            ):
                raise ValueError(
                    "The selected input configuration or terminal changed; capture again."
                )
            ref = app.reader.scalar(record, 32527)
            if edit.action == "remove-allocated":
                if allocation_origin is None:
                    raise ValueError(
                        "Only a verified original allocation receipt can authorize removal."
                    )
                self.check_removal(record, allocation_origin)
                new_record = None
            else:
                replacements = {}
                for pid, raw in changed.items():
                    before = raw_property(app, record, pid)
                    if before is not None and before[0] >> 4 != (9 if pid in ENUM_FIELDS else 4):
                        raise ValueError(
                            "An input configuration field has an unqualified native datatype."
                        )
                    if before == raw + b"\x2f" or (
                        pid in ENUM_FIELDS
                        and app.reader.scalar(record, pid) == int.from_bytes(raw[1:], "big")
                    ):
                        continue
                    rows.append(
                        {
                            "property": pid,
                            "before": app.reader.scalar(record, pid),
                            "after_encoded_hex": raw.hex(),
                        }
                    )
                    replacements[pid] = raw
                if not rows:
                    raise ValueError("Choose a different input configuration.")
                new_record = replace_properties(app, record, replacements)
        # Retain every untouched raw record; insert new hardware before metadata.
        records, inserted = [], False
        for r in app.records:
            raw = app.data[r["offset"] : r["end_offset"]]
            if edit.action == "allocate" and r["class_id"] == 127 and not inserted:
                records.append(new_record)
                inserted = True
            if r is record and edit.action != "allocate":
                if new_record is not None:
                    records.append(new_record)
            else:
                records.append(raw)
        if edit.action == "allocate" and not inserted:
            records.append(new_record)
        output = archive(app, records)
        actual = MoiIdentity(output)
        if actual.summary()["name"] != app.summary()["name"] or actual.instance != app.instance:
            raise ValueError("Input editing changed Device identity.")
        return output, {
            "profile": PROFILE,
            "input_edit": edit.model_dump(),
            "object_id": obj,
            "record_ref": ref,
            "changes": rows,
            "stored_configuration": (
                {
                    label: actual.reader.scalar(
                        next(r for r in actual.records if actual.reader.scalar(r, 75) == obj), pid
                    )
                    for pid, label in CONFIG.items()
                }
                if new_record is not None
                else None
            ),
            "parameter_merge": self.parameters,
            "parameter_transfer_qualification": self.qualification,
            "compiled_native_sha256": sha(actual.data),
            "native_record_count": len(actual.records),
            "original_native_record_count": len(app.records),
            "allocated_record_hex": new_record.hex() if edit.action == "allocate" else None,
            "other_records_preserved": True,
            "wires_changed": False,
        }

    def check_removal(self, record, origin):
        app = self.app
        expected = origin.get("allocated_record_hex")
        if not isinstance(expected, str):
            raise ValueError("Original allocated-record evidence is missing.")
        raw = bytes.fromhex(expected)
        # Only the explicitly supported electrical/scaling leaves may have
        # changed since allocation. All names, bindings and opaque fields match.
        original = MoiIdentity(
            archive(
                app,
                [app.data[r["offset"] : r["end_offset"]] for r in app.records if r is not record]
                + [raw],
            )
        )
        instance = record_instance(app, record)
        wanted = next(
            r
            for r in original.records
            if r["class_id"] == 240 and record_instance(original, r) == instance
        )
        expected_fields = {
            pid: raw_property(original, wanted, pid)
            for pid in set(wanted["properties"]) - set(CONFIG)
        }
        for field in origin.get("initialized_input_parameters", []):
            if (
                field.get("class") != 240
                or field.get("instance") != instance
                or field.get("property") not in (813, 3164, 1302)
            ):
                raise ValueError("Original input initialization evidence is unsupported.")
            expected_fields[field["property"]] = bytes.fromhex(field["encoded_hex"])
        actual_fields = {
            pid: raw_property(app, record, pid) for pid in set(record["properties"]) - set(CONFIG)
        }
        if actual_fields != expected_fields:
            raise ValueError(
                "The allocated input's original non-electrical configuration changed; removal requires review."
            )
        ref = app.reader.scalar(record, 32527)
        needles = [
            encoded(ObjectIdentifier((240, instance))),
            encoded(ObjectIdentifier((0, instance))),
            ((240 << 22) | instance).to_bytes(4, "big"),
            instance.to_bytes(4, "big"),
            ref.encode(),
            ref.encode("utf-16-be"),
        ]
        for r in app.records:
            if r is record:
                continue
            for pid in r["properties"]:
                if any(n in raw_property(app, r, pid) for n in needles):
                    raise ValueError(
                        "The allocated input is referenced; removal must not alter program connections."
                    )


def compile_input(files, edit, *, allocation_origin=None):
    return NativeInputCompiler(files).compile(edit, allocation_origin=allocation_origin)


def verify_input_preservation(before, after, edit, *, allocation_origin=None):
    edit = InputEdit.model_validate(edit)
    expected, report = compile_input(before, edit, allocation_origin=allocation_origin)
    if set(after) != {3, 11, 12} or MoiIdentity(after[3]).data != MoiIdentity(expected).data:
        raise ValueError("Native input readback differs from the reviewed complete application.")
    observed = MoiIdentity(after[3])
    post = ParameterApplication(after[3], after[11], after[12])
    current_archive, current_report = post.compile()
    current_app = MoiIdentity(current_archive)
    initialized = []
    remaining = []
    for row in current_report["changed_parameters"]:
        if (
            edit.action == "allocate"
            and row["class"] == 240
            and row["instance"] == edit.object_instance
            and row.get("added")
            and row["property"] in (813, 3164, 1302)
        ):
            record = next(
                r
                for r in current_app.records
                if r["class_id"] == 240 and record_instance(current_app, r) == edit.object_instance
            )
            pid = row["property"]
            value = current_app.reader.scalar(record, pid)
            valid = (
                type(value) is int and 0 <= value <= 255
                if pid == 813
                else type(value) is float and math.isfinite(value) and value >= 0
                if pid == 3164
                else value is True
            )
            raw = raw_property(current_app, record, pid)
            expected_tag = {813: 2, 3164: 4, 1302: 1}[pid]
            if not valid or raw[0] >> 4 != expected_tag:
                raise ValueError("A newly allocated input has an unqualified initialized default.")
            initialized.append(
                {
                    **row,
                    "property_name": {
                        813: "Calculation default byte",
                        3164: "Time Constant",
                        1302: "Was Present",
                    }[pid],
                    "current_saved_value": value,
                    "encoded_hex": raw.hex(),
                    "reason": "Firmware initialized a previously absent property on the newly created input only.",
                }
            )
        else:
            remaining.append(row)

    # The existing runtime classifier still checks every other change. Only the
    # explicitly typed creation defaults above belong to a newly created record;
    # no pre-existing setting or changed configured value is omitted.
    class ClassifiedPost:
        def compile(self):
            return current_archive, {**current_report, "changed_parameters": remaining}

    current, counters, calculated = runtime_parameter_changes(observed, ClassifiedPost())
    return {
        "profile": PROFILE,
        "identity_unchanged": True,
        "other_configuration_preserved": True,
        "selected_edit": report["input_edit"],
        "saved_application_parameters_verified": report["parameter_merge"]["matched_parameters"],
        "post_saved_parameters": current["matched_parameters"],
        "runtime_counter_changes": counters,
        "device_calculated_changes": calculated,
        "initialized_input_parameters": initialized,
        "controller_writes": False,
    }
