"""Observed class-242 configuration and guarded existing local binary terminal moves."""

from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import Tag, TagClass

from .moi_identity import MoiIdentity, seal, sha
from .moi_terminal_labels import EncodedTerminalCopies

PROFILE = "native-local-universal-input-transfer/3"
SCOPE = (
    "Move one existing observed class-242 local universal binary input to a free universal "
    "terminal on the same controller. Retain recorded label encoding, state texts, states-text "
    "index, optional polarity, identities, graph and other fresh merged bytes. Runtime counters "
    "remain captured values, not electrical configuration. No analog scaling, binary allocation, "
    "electrical/polarity edit, SA/cross-host/dedicated-BI move or physical/CCT acceptance. "
    "A separately confirmed field Apply transfers File 3 and can restart control."
)
REQUIRED = {
    32527: (7, "CharacterString"),
    4: (7, "CharacterString"),
    28: (7, "CharacterString"),
    31: (7, "CharacterString"),
    46: (7, "CharacterString"),
    75: (12, "ObjectIdentifier"),
    519: (2, "Unsigned"),
    931: (9, "Enumerated"),
    2390: (7, "CharacterString"),
}
OPTIONAL = {15: (2, "Unsigned"), 33: (2, "Unsigned"), 84: (9, "Enumerated")}
COUNTERS = {15, 33}


def configuration(app, record):
    props = record["properties"]
    if (
        record["class_id"] != 242
        or not REQUIRED.keys() <= props.keys()
        or props.keys() - REQUIRED.keys() - OPTIONAL.keys()
    ):
        raise ValueError("The selected binary input has no closed observed configuration schema.")
    for pid, prop in props.items():
        tag_type, scalar_type = (REQUIRED | OPTIONAL)[pid]
        raw = app.data[prop["value_start_offset"] : prop["value_end_offset"]]
        pdu = PDUData(raw)
        first, closing = Tag.decode(pdu), Tag.decode(pdu)
        if (
            first.tag_class != TagClass.application
            or first.tag_number != tag_type
            or closing.tag_class != TagClass.closing
            or closing.tag_number != 2
            or pdu.pduData
            or (prop.get("scalar") or {}).get("datatype") != scalar_type
        ):
            raise ValueError("A binary configuration property lacks its exact single typed value.")
        if tag_type in (2, 9) and not 1 <= len(first.tag_data) <= 4:
            raise ValueError(
                "A binary configuration/count field exceeds its recorded Unsigned32 shape."
            )
    if 84 in props and app.reader.scalar(record, 84) not in (0, 1):
        raise ValueError("The recorded binary polarity has no normal/reverse profile.")
    identity = app.summary()
    guard = seal(
        {
            "controller": {
                k: identity[k] for k in ("instance", "name", "model", "root_ref", "format_versions")
            },
            "properties": {
                str(pid): props[pid]["encoded_sha256"] for pid in sorted(props.keys() - COUNTERS)
            },
        }
    )
    return {
        "configuration_sha256": guard,
        "configuration": {
            "active_text": app.reader.scalar(record, 4),
            "inactive_text": app.reader.scalar(record, 46),
            "states_text_index": app.reader.scalar(record, 931),
            "polarity": app.reader.scalar(record, 84),
        },
        "captured_counter_values": {
            str(pid): app.reader.scalar(record, pid) for pid in sorted(props.keys() & COUNTERS)
        },
    }


class BinaryTerminalCompiler:
    def __init__(self, compiler):
        self.compiler = compiler
        self.app = compiler.app
        self.copier = EncodedTerminalCopies(self.app.source)
        self.inputs = {
            p["object"]: p
            for p in self.copier.inspect()["inputs"]
            if p["class_id"] == 242 and p["movable"]
        }

    def source(self):
        rows = []
        for obj, item in self.inputs.items():
            try:
                fields = configuration(self.app, self.app.reader.records[item["ref"]])
                error = None
            except ValueError as exc:
                fields, error = {}, str(exc)
            rows.append(
                {
                    "object_id": obj,
                    "record_ref": item["ref"],
                    "slot": item["slot"],
                    "name": item["name"],
                    "device_type_character_encoding": item["device_type_character_encoding"],
                    **fields,
                    "configuration_error": error,
                }
            )
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "controller": self.app.summary(),
            "hardware": self.compiler.hardware,
            "available_slots": self.copier.inspect()["unassigned_slots"],
            "inputs": rows,
            "counter_values_are_live": False,
            "controller_queries": False,
            "controller_writes": False,
            "field_transfer_enabled": False,
        }

    def compile(self, edit):
        from .native_inputs import InputEdit

        edit = InputEdit.model_validate(edit)
        if edit.action != "binary-terminal":
            raise ValueError("Choose an explicit existing binary-terminal move.")
        obj = f"binary-input,{edit.object_instance}"
        selected = self.inputs.get(obj)
        if selected is None:
            raise ValueError("Choose an existing movable local universal binary input.")
        record = self.app.reader.records[selected["ref"]]
        fields = configuration(self.app, record)
        if fields["configuration_sha256"] != edit.configuration_sha256:
            raise ValueError(
                "The existing binary configuration or terminal changed; capture again."
            )
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
        from .moi_parameters import ParameterApplication

        saved, _ = ParameterApplication(
            output, self.compiler.files[11], self.compiler.files[12]
        ).compile()
        saved_app = MoiIdentity(saved)
        intended = configuration(actual, actual.reader.records[selected["ref"]])
        reapplied = configuration(saved_app, saved_app.reader.records[selected["ref"]])
        if intended["configuration_sha256"] != reapplied["configuration_sha256"]:
            raise ValueError(
                "Retained saved settings would override the requested binary terminal binding."
            )
        return output, {
            "profile": PROFILE,
            "input_edit": edit.model_dump(),
            "object_id": obj,
            "record_ref": selected["ref"],
            "changes": [
                {"property": 31, "before": selected["device_type"], "after": f"UI IN{edit.slot}"},
                {"property": 519, "before": selected["slot"], "after": edit.slot},
            ],
            "stored_configuration": fields["configuration"],
            "configuration_sha256": fields["configuration_sha256"],
            "captured_counter_values": fields["captured_counter_values"],
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
    """Require explicit profile/action/compiler pairing before write or readback."""
    from .native_inputs import InputEdit

    if body.get("operation_profile") != PROFILE:
        return
    edit = InputEdit.model_validate(body.get("input_edit"))
    c = body.get("compilation")
    p = c.get("terminal_compilation") if isinstance(c, dict) else None
    if (
        edit.action != "binary-terminal"
        or not isinstance(p, dict)
        or c.get("profile") != PROFILE
        or seal(c.get("input_edit")) != seal(edit.model_dump())
        or c.get("object_id") != f"binary-input,{edit.object_instance}"
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
        raise ValueError("Binary terminal evidence requires its exact action and compiler profile.")


async def verify_published(service, session, files, edit):
    from bacpypes3.primitivedata import CharacterString, Enumerated, Unsigned

    from .native_inputs import NativeInputCompiler

    compiler = BinaryTerminalCompiler(NativeInputCompiler(files))
    obj = f"binary-input,{edit.object_instance}"
    selected = compiler.inputs.get(obj)
    if selected is None:
        raise ValueError("The recorded binary input is no longer in its local native inventory.")
    record = compiler.app.reader.records[selected["ref"]]
    configuration(compiler.app, record)
    present, evidence = await service.input_presence(session, obj)
    if not present:
        raise ValueError("The configured binary input is absent from the controller.")
    rows = []
    for pid in (77, 28, 31, 519, 4, 46, 931, 84):
        native_pid = 2390 if pid == 77 else pid
        if native_pid not in record["properties"]:
            continue
        expected = compiler.app.reader.scalar(record, native_pid)
        dtype = Unsigned if pid == 519 else Enumerated if pid in (84, 931) else CharacterString
        actual = await service.input_atomic(session, obj, pid, dtype)
        if actual != expected:
            raise ValueError(
                f"Published binary input property {pid} differs from the native application."
            )
        rows.append(
            {
                "property": pid,
                "expected": expected,
                "native_application_value": expected,
                "actual": int(actual) if dtype in (Unsigned, Enumerated) else str(actual),
                "comparison": "stored binary configuration",
                "matches": True,
            }
        )
    return {
        "object_id": obj,
        "present": True,
        "properties": rows,
        "identity_evidence": evidence,
        "runtime_counter_values_compared": False,
        "physical_terminal_or_wiring_verified": False,
    }
