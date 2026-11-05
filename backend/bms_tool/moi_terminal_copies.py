"""Fixed-length local universal-terminal binding copies in recorded native images."""

import re
import struct
import zlib

from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import ObjectIdentifier, Tag, TagClass

from .moi_identity import MoiIdentity, seal, sha
from .native_inputs import FORMATS, input_capabilities

PROFILE = "tagged-moi-local-terminal-copy/1"
OUTPUT_PROFILE = "tagged-moi-local-terminal-copy/2"
SCOPE = (
    "Move one existing local analog/binary input between documented free universal "
    "terminals in a local native file copy. Change only its existing Slot and Device Type "
    "payloads, preserving original widths, all other expanded bytes, identities, modes, "
    "settings, graph and framing. No SA/cross-host/dedicated-BI move, allocation, electrical "
    "mode change, physical wiring, field transfer or CCT/physical acceptance."
)
OUTPUT_SCOPE = SCOPE + (
    " This explicit version additionally recognizes unchanged local AO/BO output records "
    "with recorded output-only terminal labels. Their Slot namespace does not reserve input "
    "terminals. No output binding is edited."
)


class MoiTerminalCopies:
    @staticmethod
    def label_payload(original, value):
        return b"\0" + value.encode("ascii")

    def __init__(self, source, *, output_namespace=False):
        if type(output_namespace) is not bool:
            raise ValueError("Choose an explicit Boolean output-namespace profile.")
        self.output_namespace = output_namespace
        self.profile = OUTPUT_PROFILE if output_namespace else PROFILE
        self.scope = OUTPUT_SCOPE if output_namespace else SCOPE
        self.editor = app = MoiIdentity(source)
        summary = app.summary()
        versions = summary["format_versions"]
        if (versions["acs"], versions["dmcs"]) not in FORMATS:
            raise ValueError(
                "This native controller/data-model pair has no local terminal profile."
            )
        self.hardware = input_capabilities(summary["model"])
        capacity = self.hardware["capacity"]
        if (
            capacity.get("profile")
            not in {
                "jci-vav-physical-inputs/1",
                "jci-cv-physical-inputs/1",
            }
            and summary["model"].strip().upper() != "FX-PCG2611-0"
        ):
            raise ValueError("This root model has no qualified local controller-terminal profile.")
        self.inputs, self.occupied, identities = {}, {}, set()
        for record in app.records:
            cid, props = record["class_id"], record["properties"]
            if cid in {598, 910, 243, 671, 673}:
                raise ValueError("SA/IOM and other input families require a separate host profile.")
            obj, ref, label, slot = (app.reader.scalar(record, p) for p in (75, 32527, 31, 519))
            if 75 in props:
                if (props[75].get("scalar") or {}).get("datatype") != "ObjectIdentifier":
                    raise ValueError("An untyped public object identity prevents terminal copying.")
                if obj in identities:
                    raise ValueError("Duplicate public object identities prevent terminal copying.")
                identities.add(obj)
            if cid not in {240, 242}:
                if output_namespace and cid in {239, 241} and 519 in props:
                    output_type = 4 if cid == 239 else 1
                    oid = ObjectIdentifier(obj) if isinstance(obj, str) else None
                    header = int.from_bytes(
                        app.data[record["offset"] + 6 : record["offset"] + 10], "big"
                    )
                    labels = r"BO OUT[1-9][0-9]*" if cid == 239 else r"(?:AO|CO) OUT[1-9][0-9]*"
                    if (
                        oid is None
                        or int(oid[0]) != output_type
                        or not 0 <= int(oid[1]) <= 4194302
                        or header != cid << 22 | int(oid[1])
                        or ref != f"{app.ref}/{output_type}_{int(oid[1])}"
                        or type(slot) is not int
                        or not 0 <= slot <= 65535
                        or (props[519].get("scalar") or {}).get("datatype") != "Unsigned"
                        or not isinstance(label, str)
                        or not re.fullmatch(labels, label)
                        or {2577, 3645}.intersection(props)
                    ):
                        raise ValueError(
                            "An output has no exact separate local terminal namespace."
                        )
                    continue
                if 519 in props or (
                    isinstance(label, str)
                    and re.fullmatch(r"(?:UI|BI|CI)\s+IN\s*[0-9]+", label, re.I)
                ):
                    raise ValueError("Unknown hardware records could conceal terminal occupancy.")
                continue
            if {2577, 3645}.intersection(props):
                raise ValueError("Explicit SA/device-host input bindings require another profile.")
            external_type = 0 if cid == 240 else 3
            oid = ObjectIdentifier(obj) if isinstance(obj, str) else None
            instance = int(oid[1]) if oid is not None else None
            header = int.from_bytes(app.data[record["offset"] + 6 : record["offset"] + 10], "big")
            if (
                oid is None
                or int(oid[0]) != external_type
                or header != cid << 22 | instance
                or not 0 <= instance <= 4194302
                or ref != f"{app.ref}/{external_type}_{instance}"
            ):
                raise ValueError(
                    "Input identity or its exact local parent reference is inconsistent."
                )
            internal = (
                cid == 240
                and label == "AI1-Int"
                and slot == 4
                and app.reader.scalar(record, 518) == 9
                and capacity.get("profile")
                in {"jci-vav-physical-inputs/1", "jci-cv-physical-inputs/1"}
            )
            if type(slot) is not int or slot in self.occupied:
                raise ValueError("Duplicate or untyped local input slots prevent terminal copying.")
            if not internal and (
                slot not in capacity["universal_inputs"] or label != f"UI IN{slot}"
            ):
                raise ValueError("Input is not an observed local universal terminal or fixed DPT.")
            self.occupied[slot] = ref
            if not internal:
                self.payload(record, 519, 2, slot)
                self.payload(record, 31, 7, label)
            self.inputs[ref] = {
                "ref": ref,
                "object": obj,
                "name": app.reader.scalar(record, 2390),
                "class_id": cid,
                "slot": slot,
                "device_type": label,
                "movable": not internal,
                "internal": internal,
                "record_sha256": record["sha256"],
                "slot_property_sha256": props[519]["encoded_sha256"],
                "device_type_property_sha256": props[31]["encoded_sha256"],
            }
        if not self.inputs or not any(p["movable"] for p in self.inputs.values()):
            raise ValueError(
                "No existing local universal input is available for this copy profile."
            )

    def payload(self, record, pid, datatype, value):
        prop = record["properties"].get(pid)
        if prop is None:
            raise ValueError("The original terminal property is absent.")
        start, end = prop["value_start_offset"], prop["value_end_offset"]
        raw = self.editor.data[start:end]
        pdu = PDUData(raw)
        first = Tag.decode(pdu)
        consumed = len(raw) - len(pdu.pduData)
        if (
            first.tag_class != TagClass.application
            or first.tag_number != datatype
            or not pdu.pduData
        ):
            raise ValueError("The terminal property has unsupported native framing.")
        closing = Tag.decode(pdu)
        if closing.tag_class != TagClass.closing or closing.tag_number != 2 or pdu.pduData:
            raise ValueError("The terminal property has extra or mismatched native values.")
        payload = bytes(first.tag_data)
        if datatype == 2:
            if not 1 <= len(payload) <= 4 or int.from_bytes(payload, "big") != value:
                raise ValueError(
                    "Slot requires its exact existing one-to-four-byte Unsigned value."
                )
        elif payload != self.label_payload(payload, value):
            raise ValueError("Device Type requires its recorded ASCII universal-terminal label.")
        return start + consumed - len(payload), payload

    def inspect(self):
        return {
            "profile": self.profile,
            "scope": self.scope,
            "source_sha256": self.editor.source_sha256,
            "controller": self.editor.summary(),
            "hardware": self.hardware,
            "inputs": list(self.inputs.values()),
            "unassigned_slots": [
                n for n in self.hardware["capacity"]["universal_inputs"] if n not in self.occupied
            ],
            "controller_write": False,
            "field_transfer_enabled": False,
        }

    def compile(
        self,
        *,
        source_sha256,
        ref,
        record_sha256,
        slot_property_sha256,
        device_type_property_sha256,
        old_slot,
        destination_slot,
    ):
        if source_sha256 != self.editor.source_sha256:
            raise ValueError(
                "Native terminal source changed; inspect the retained application again."
            )
        selected = self.inputs.get(ref)
        if selected is None or not selected["movable"]:
            raise ValueError("Choose an existing local universal input; the integral DPT is fixed.")
        if any(
            selected[k] != v
            for k, v in {
                "record_sha256": record_sha256,
                "slot_property_sha256": slot_property_sha256,
                "device_type_property_sha256": device_type_property_sha256,
            }.items()
        ):
            raise ValueError("The original input record or terminal-property evidence changed.")
        if type(old_slot) is not int or old_slot != selected["slot"]:
            raise ValueError("The selected input no longer has the reviewed original terminal.")
        if (
            type(destination_slot) is not int
            or destination_slot not in self.hardware["capacity"]["universal_inputs"]
        ):
            raise ValueError("Choose a documented local universal terminal on the same controller.")
        if destination_slot != old_slot and destination_slot in self.occupied:
            raise ValueError("The destination terminal already has a configured input.")
        app = self.editor
        record = app.reader.records[ref]
        offset, slot = self.payload(record, 519, 2, old_slot)
        label_offset, label = self.payload(record, 31, 7, selected["device_type"])
        changes = [
            (offset, slot, destination_slot.to_bytes(len(slot), "big")),
            (label_offset, label, self.label_payload(label, f"UI IN{destination_slot}")),
        ]
        if any(len(old) != len(new) for _, old, new in changes):
            raise ValueError("Terminal copying must preserve both original payload widths.")
        data = bytearray(app.data)
        for position, old, new in changes:
            if data[position : position + len(old)] != old:
                raise ValueError("Native terminal offsets no longer match original bytes.")
            data[position : position + len(old)] = new
        output = bytes(data)
        changed = destination_slot != old_slot
        if not changed:
            output = app.source
        elif app.compressed:
            compressor = zlib.compressobj(level=9, wbits=-15)
            output = (
                app.source[:10]
                + compressor.compress(data)
                + compressor.flush()
                + struct.pack("<II", zlib.crc32(data), len(data))
            )
        checked = type(self)(output, output_namespace=self.output_namespace)
        expected = {key: dict(value) for key, value in self.inputs.items()}
        expected[ref].update(slot=destination_slot, device_type=f"UI IN{destination_slot}")
        after = checked.inputs[ref]
        for key in ("record_sha256", "slot_property_sha256", "device_type_property_sha256"):
            expected[ref][key] = after[key]
        if checked.editor.data != data or checked.inputs != expected:
            raise ValueError(
                "Native terminal readback did not preserve the exact requested binding."
            )
        previous = 0
        for position, old, _ in sorted(changes):
            if app.data[previous:position] != data[previous:position]:
                raise ValueError("Terminal copying changed another expanded application byte.")
            previous = position + len(old)
        if app.data[previous:] != data[previous:] or len(app.records) != len(
            checked.editor.records
        ):
            raise ValueError("Terminal copying changed another native record or framing byte.")
        body = {
            "profile": self.profile,
            "scope": self.scope,
            "source_sha256": source_sha256,
            "source_native_sha256": sha(app.data),
            "ref": ref,
            "record_sha256": record_sha256,
            "slot_property_sha256": slot_property_sha256,
            "device_type_property_sha256": device_type_property_sha256,
            "object": selected["object"],
            "old_slot": old_slot,
            "destination_slot": destination_slot,
            "old_device_type": selected["device_type"],
            "new_device_type": f"UI IN{destination_slot}",
            "changed": changed,
            "output_sha256": sha(output),
            "output_native_sha256": sha(data),
            "payloads": [{"offset": p, "before": a.hex(), "after": b.hex()} for p, a, b in changes],
            "other_expanded_bytes_preserved": True,
            "native_structure_readback_verified": True,
            "identities_modes_graph_and_record_framing_preserved": True,
            "saved_settings_merged": False,
            "controller_write": False,
            "field_transfer_enabled": False,
            "physical_terminal_or_wiring_verified": False,
        }
        return output, {**body, "compilation_sha256": seal(body)}
