"""Explicit typed analog movement preserving observed terminal-label encoding."""

import math
import struct

from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import Tag, TagClass

from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .moi_terminal_labels import EncodedTerminalCopies
from .native_inputs import CONFIG, ENUM_FIELDS, InputEdit, configuration_guard, raw_property

PROFILE = "native-local-universal-input-transfer/4"
CONFIGURATION_PROFILE = "native-typed-analog-configuration/1"
SCOPE = (
    "Move one existing typed local universal analog input to a free universal terminal on "
    "the same controller, retaining its observed ASCII/UCS-2 label encoding and exact stored "
    "configuration, including paired absent linear output endpoints. Preserve identities, "
    "graph and every other fresh merged byte. No allocation, electrical/scaling edit, "
    "SA/cross-host/dedicated move, general compilation or physical/CCT acceptance. "
    "A separately confirmed Apply transfers File 3 and can restart control."
)
OPTIONAL_OUTPUTS = {1295, 1296}


def configuration(app, record):
    props = record["properties"]
    if record["class_id"] != 240 or not (CONFIG.keys() - OPTIONAL_OUTPUTS) <= props.keys():
        raise ValueError("The selected analog input lacks its observed typed configuration.")
    if bool(1295 in props) != bool(1296 in props):
        raise ValueError("Recorded linear output endpoints must be present or absent together.")
    for pid in CONFIG.keys() & props.keys():
        raw = raw_property(app, record, pid)
        pdu = PDUData(raw)
        value, close = Tag.decode(pdu), Tag.decode(pdu)
        enum = pid in ENUM_FIELDS
        scalar = props[pid].get("scalar") or {}
        actual = app.reader.scalar(record, pid)
        if (
            value.tag_class != TagClass.application
            or value.tag_number != (9 if enum else 4)
            or close.tag_class != TagClass.closing
            or close.tag_number != 2
            or pdu.pduData
            or scalar.get("datatype") != ("Enumerated" if enum else "Real")
            or (not 1 <= len(value.tag_data) <= 4 if enum else len(value.tag_data) != 4)
            or (
                type(actual) is not int
                if enum
                else type(actual) is not float or not math.isfinite(actual)
            )
        ):
            raise ValueError("An analog configuration field lacks its exact finite native type.")
    return {
        "stored_configuration": {
            name: app.reader.scalar(record, pid) for pid, name in CONFIG.items()
        },
        "configuration_storage": {
            "profile": CONFIGURATION_PROFILE,
            "present_properties": sorted(CONFIG.keys() & props.keys()),
            "linear_output_endpoints_present": 1295 in props,
        },
    }


class EncodedAnalogTerminalCompiler:
    def __init__(self, compiler):
        self.compiler, self.app = compiler, compiler.app
        self.copier = EncodedTerminalCopies(self.app.source)

    def source(self):
        rows = []
        inspected = {p["ref"]: p for p in self.copier.inspect()["inputs"]}
        for point in self.compiler.source()["inputs"]:
            record = self.compiler.inputs[point["object_id"]]
            selected = inspected.get(point["record_ref"])
            try:
                if selected is None or selected["class_id"] != 240 or not selected["movable"]:
                    raise ValueError("Choose an existing movable local universal analog input.")
                details = configuration(self.app, record)
                error = None
            except ValueError as exc:
                details, error = {}, str(exc)
            rows.append(
                {
                    **point,
                    **details,
                    "configuration_error": error,
                    "configuration_sha256": point["configuration_sha256"]
                    if error is None
                    else None,
                    "device_type_character_encoding": selected["device_type_character_encoding"]
                    if selected is not None
                    else None,
                }
            )
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "controller": self.app.summary(),
            "hardware": self.compiler.hardware,
            "available_slots": self.copier.inspect()["unassigned_slots"],
            "inputs": rows,
            "controller_queries": False,
            "controller_writes": False,
            "field_transfer_enabled": False,
        }

    def compile(self, edit):
        edit = InputEdit.model_validate(edit)
        if edit.action != "encoded-terminal":
            raise ValueError("Choose the explicit encoding-preserving analog terminal action.")
        obj = f"analog-input,{edit.object_instance}"
        record = self.compiler.inputs.get(obj)
        if record is None or configuration_guard(self.app, record) != edit.configuration_sha256:
            raise ValueError("The existing analog input configuration changed; capture again.")
        details = configuration(self.app, record)
        ref = self.app.reader.scalar(record, 32527)
        selected = self.copier.inputs.get(ref)
        if selected is None or selected["class_id"] != 240 or not selected["movable"]:
            raise ValueError("Choose an existing movable local universal analog input.")
        if edit.slot == selected["slot"]:
            raise ValueError("Choose a different documented free universal terminal.")
        output, proof = self.copier.compile(
            source_sha256=self.app.source_sha256,
            **{
                k: selected[k]
                for k in (
                    "ref",
                    "record_sha256",
                    "slot_property_sha256",
                    "device_type_property_sha256",
                )
            },
            old_slot=selected["slot"],
            destination_slot=edit.slot,
        )
        actual = MoiIdentity(output)
        saved, _ = ParameterApplication(
            output, self.compiler.files[11], self.compiler.files[12]
        ).compile()
        reapplied = MoiIdentity(saved)
        if configuration_guard(actual, actual.reader.records[ref]) != configuration_guard(
            reapplied, reapplied.reader.records[ref]
        ):
            raise ValueError(
                "Retained saved settings would override the requested analog terminal binding."
            )
        return output, {
            "profile": PROFILE,
            "input_edit": edit.model_dump(),
            "object_id": obj,
            "record_ref": ref,
            "configuration_sha256": edit.configuration_sha256,
            **details,
            "changes": [
                {"property": 31, "before": selected["device_type"], "after": f"UI IN{edit.slot}"},
                {"property": 519, "before": selected["slot"], "after": edit.slot},
            ],
            "parameter_merge": self.compiler.parameters,
            "parameter_transfer_qualification": self.compiler.qualification,
            "compiled_native_sha256": sha(actual.data),
            "native_record_count": len(actual.records),
            "original_native_record_count": len(self.app.records),
            "allocated_record_hex": None,
            "other_records_preserved": True,
            "wires_changed": False,
            "terminal_compilation": proof,
        }


def validate_evidence(body):
    if body.get("operation_profile") != PROFILE:
        return
    edit = InputEdit.model_validate(body.get("input_edit"))
    c = body.get("compilation")
    p = c.get("terminal_compilation") if isinstance(c, dict) else None
    if (
        edit.action != "encoded-terminal"
        or not isinstance(p, dict)
        or c.get("profile") != PROFILE
        or seal(c.get("input_edit")) != seal(edit.model_dump())
        or c.get("object_id") != f"analog-input,{edit.object_instance}"
        or c.get("configuration_sha256") != edit.configuration_sha256
        or "allocated_record_hex" not in c
        or c.get("allocated_record_hex") is not None
        or c.get("other_records_preserved") is not True
        or c.get("wires_changed") is not False
        or p.get("profile") != "tagged-moi-local-terminal-copy/3"
        or p.get("object") != c.get("object_id")
        or p.get("ref") != c.get("record_ref")
        or type(p.get("destination_slot")) is not int
        or p.get("destination_slot") != edit.slot
        or type(p.get("old_slot")) is not int
        or p.get("old_slot") == edit.slot
        or p.get("changed") is not True
        or p.get("device_type_encoding_preserved") is not True
        or type(p.get("device_type_character_encoding")) is not int
        or p.get("device_type_character_encoding") not in (0, 4)
        or p.get("other_expanded_bytes_preserved") is not True
        or p.get("identities_modes_graph_and_record_framing_preserved") is not True
        or p.get("native_structure_readback_verified") is not True
        or p.get("controller_write") is not False
        or p.get("field_transfer_enabled") is not False
        or p.get("output_native_sha256") != c.get("compiled_native_sha256")
        or p.get("output_sha256") != body.get("payload_sha256")
        or p.get("compilation_sha256")
        != seal({k: v for k, v in p.items() if k != "compilation_sha256"})
    ):
        raise ValueError(
            "Encoded analog terminal evidence requires its exact action and compiler profile."
        )
    config, storage = c.get("stored_configuration"), c.get("configuration_storage")
    if (
        not isinstance(config, dict)
        or set(config) != set(CONFIG.values())
        or not isinstance(storage, dict)
        or set(storage) != {"profile", "present_properties", "linear_output_endpoints_present"}
    ):
        raise ValueError("Encoded analog configuration storage evidence is incomplete.")
    expected = sorted(
        CONFIG
        if storage.get("linear_output_endpoints_present") is True
        else CONFIG.keys() - OPTIONAL_OUTPUTS
    )
    if (
        storage.get("profile") != CONFIGURATION_PROFILE
        or type(storage.get("linear_output_endpoints_present")) is not bool
        or seal(storage.get("present_properties")) != seal(expected)
    ):
        raise ValueError("Encoded analog configuration field presence changed.")
    for pid, name in CONFIG.items():
        value = config[name]
        if pid not in expected:
            valid = value is None
        elif pid in ENUM_FIELDS:
            valid = type(value) is int and 0 <= value <= 4294967295
        else:
            try:
                valid = (
                    type(value) in (int, float)
                    and math.isfinite(value)
                    and struct.unpack(">f", struct.pack(">f", value))[0] == value
                )
            except (OverflowError, struct.error):
                valid = False
        if not valid:
            raise ValueError("Encoded analog configuration evidence has an unsupported value.")
