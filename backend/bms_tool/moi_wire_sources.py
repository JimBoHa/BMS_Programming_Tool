"""Fixed-width copies of one recorded native wire source; no field compiler grant."""

import struct
import zlib

from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import ObjectIdentifier, Tag, TagClass

from .moi_identity import MoiIdentity, seal, sha

PROFILE = "tagged-moi-wire-source-copy/1"
SCOPE = (
    "Local archive copy of one existing native connection's source index. Require an existing "
    "same-class/configuration source and observed outgoing pin, execution before destination, "
    "no introduced cycle and unchanged UInt width. Preserve all other expanded bytes, IDs, "
    "membership, order, positions and metadata. No saved-setting merge, new blocks/I/O, "
    "general logic generation, field transfer, native runtime or CCT/physical acceptance."
)
IDENTITY_PROPERTIES = frozenset({75, 32527, 2390, 28})


class MoiWireSources:
    def __init__(self, data):
        self.editor = MoiIdentity(data)
        self.reader = self.editor.reader
        if self.reader.errors:
            raise ValueError("Native wire copies require unambiguous complete native records.")
        if any(
            record["properties"][32527]["scalar"]["datatype"] != "CharacterString"
            for record in self.reader.records.values()
        ):
            raise ValueError("Native wire copies require typed engineering reference strings.")
        self.signatures = {}
        for ref, record in self.reader.records.items():
            signature = []
            for pid, prop in record["properties"].items():
                if pid in IDENTITY_PROPERTIES:
                    continue
                scalar = prop["scalar"]
                if pid == 3113 and scalar and scalar["datatype"] in ("Real", "Boolean"):
                    signature.append((pid, "default-type", scalar["datatype"]))
                else:
                    signature.append((pid, "encoded", prop["encoded_sha256"]))
            self.signatures[ref] = (record["class_id"], tuple(signature))

    def graph(self, ref):
        graph = self.reader.diagram(ref)
        record = self.reader.records[ref]
        prop = record["properties"][3118]
        start, end = prop["value_start_offset"], prop["value_end_offset"]
        pdu = PDUData(self.editor.data[start:end])
        tokens = []
        while pdu.pduData:
            before = len(pdu.pduData)
            tag = Tag.decode(pdu)
            offset = end - before
            tokens.append((tag, offset, end - len(pdu.pduData)))
        if (
            len(tokens) != len(graph["connections"]) * 6 + 1
            or tokens[-1][0].tag_class != TagClass.closing
            or tokens[-1][0].tag_number != 2
        ):
            raise ValueError("Native wire property does not consume its recognized framing.")
        blocks = {row["ref"]: row for row in graph["blocks"]}
        for block in graph["blocks"]:
            member = self.reader.records[block["ref"]]
            identity = member["properties"].get(75, {}).get("scalar") or {}
            if identity.get("datatype") != "ObjectIdentifier":
                raise ValueError("Native wire members require typed ObjectIdentifier values.")
            oid = ObjectIdentifier(identity["value"])
            native_id = (
                int.from_bytes(
                    self.editor.data[member["offset"] + 6 : member["offset"] + 10], "big"
                )
                & 0x3FFFFF
            )
            if native_id != int(oid[1]):
                raise ValueError("Native wire member header and object instance disagree.")
        wires = []
        for index, wire in enumerate(graph["connections"]):
            tags = tokens[index * 6 : index * 6 + 6]
            if (
                tags[0][0].tag_class != TagClass.opening
                or tags[0][0].tag_number != 3
                or tags[-1][0].tag_class != TagClass.closing
                or tags[-1][0].tag_number != 3
            ):
                raise ValueError("Native connection struct framing differs from the profile.")
            fields = tags[1:5]
            if any(
                tag.tag_class != TagClass.application
                or tag.tag_number != 2
                or not 1 <= len(tag.tag_data) <= 4
                for tag, _, _ in fields
            ):
                raise ValueError("Native connection fields require four bounded Unsigned tags.")
            old = [int.from_bytes(tag.tag_data, "big") for tag, _, _ in fields]
            expected = [
                blocks[wire["source_ref"]]["index"],
                wire["source_port"],
                blocks[wire["target_ref"]]["index"],
                wire["target_port"],
            ]
            if old != expected:
                raise ValueError("Native wire bytes disagree with its actual diagram.")
            tag, _, tag_end = fields[0]
            wires.append(
                {
                    **wire,
                    "old": old,
                    "source_index_offset": tag_end - len(tag.tag_data),
                    "source_index_bytes": len(tag.tag_data),
                }
            )
        return graph, record, prop, wires

    def _refusal(self, graph, wires, wire, source_ref):
        blocks = {row["ref"]: row for row in graph["blocks"]}
        source = blocks.get(source_ref)
        if source is None:
            return "Choose an existing source in this exact diagram."
        if source_ref == wire["source_ref"]:
            return None
        if self.signatures[source_ref] != self.signatures[wire["source_ref"]]:
            return "Native source class/configuration differs from the recorded prototype."
        if (source_ref, wire["source_port"]) not in {
            (row["source_ref"], row["source_port"]) for row in wires
        }:
            return "The candidate pin has no observed outgoing connection in this diagram."
        positions = {block: position for position, block in enumerate(graph["execution_order"])}
        if positions[source["index"]] >= positions[blocks[wire["target_ref"]]["index"]]:
            return "The replacement source must execute before the destination."
        adjacency = {}
        for row in wires:
            if row["index"] != wire["index"]:
                adjacency.setdefault(row["source_ref"], []).append(row["target_ref"])
        pending, visited = [wire["target_ref"]], set()
        while pending:
            ref = pending.pop()
            if ref == source_ref:
                return "The replacement source would introduce a cycle."
            if ref in visited:
                continue
            visited.add(ref)
            pending.extend(adjacency.get(ref, []))
        if source["index"] >= 1 << (8 * wire["source_index_bytes"]):
            return "The candidate index exceeds the original Unsigned payload width."
        return None

    def inspect(self, diagram_ref, wire_index=0):
        if type(wire_index) is not int or not 0 <= wire_index <= 4095:
            raise ValueError("Select an actual bounded nonnegative native wire index.")
        graph, record, prop, wires = self.graph(diagram_ref)
        if (not wires and wire_index != 0) or (wires and wire_index >= len(wires)):
            raise ValueError("Select an actual existing native wire index.")
        wire = wires[wire_index] if wires else None
        candidates = []
        if wire:
            for block in graph["blocks"]:
                if self._refusal(graph, wires, wire, block["ref"]) is None:
                    candidates.append(
                        {key: block[key] for key in ("index", "ref", "name", "class_id", "object")}
                        | {"current_source": block["ref"] == wire["source_ref"]}
                    )
        return {
            "diagram_ref": diagram_ref,
            "record_sha256": record["sha256"],
            "property_sha256": prop["encoded_sha256"],
            "wire_index": wire_index,
            "wires": wires,
            "selected_wire": wire,
            "candidates": candidates,
            "block_count": len(graph["blocks"]),
            "execution_order": graph["execution_order"],
            "native_layout": graph["native_layout"],
            "recorded_name": graph["name"],
            "available": bool(wire) and len(candidates) > 1,
        }

    def compile(
        self,
        *,
        source_sha256,
        diagram_ref,
        record_sha256,
        property_sha256,
        wire_index,
        old,
        source_ref,
    ):
        if source_sha256 != self.editor.source_sha256:
            raise ValueError("The native archive changed; inspect the current source again.")
        if type(wire_index) is not int or wire_index < 0:
            raise ValueError("Select an actual nonnegative native wire index.")
        if not isinstance(source_ref, str):
            raise ValueError("Choose an existing native source reference.")
        if not isinstance(old, list) or len(old) != 4 or any(type(v) is not int for v in old):
            raise ValueError("Native wire copies require the four exact original Unsigned values.")
        graph, record, prop, wires = self.graph(diagram_ref)
        if record_sha256 != record["sha256"] or property_sha256 != prop["encoded_sha256"]:
            raise ValueError("The native graph record or wire property changed; inspect it again.")
        if wire_index >= len(wires):
            raise ValueError("Select an existing native wire; no connection is allocated.")
        wire = wires[wire_index]
        if old != wire["old"]:
            raise ValueError("The native connection no longer matches the reviewed tuple.")
        if failure := self._refusal(graph, wires, wire, source_ref):
            raise ValueError(failure)
        selected = next(row for row in graph["blocks"] if row["ref"] == source_ref)
        new = [selected["index"], *old[1:]]
        offset, width = wire["source_index_offset"], wire["source_index_bytes"]
        changed = new != old
        native = bytearray(self.editor.data)
        native[offset : offset + width] = new[0].to_bytes(width, "big")
        if not changed:
            output = self.editor.source
        elif self.editor.compressed:
            compressor = zlib.compressobj(level=9, wbits=-15)
            output = (
                self.editor.source[:10]
                + compressor.compress(native)
                + compressor.flush()
                + struct.pack("<II", zlib.crc32(native), len(native))
            )
        else:
            output = bytes(native)
        checked = MoiIdentity(output)
        observed = checked.reader.diagram(diagram_ref)
        expected_wires = [dict(row) for row in graph["connections"]]
        expected_wires[wire_index]["source_ref"] = source_ref
        if (
            checked.data[:offset] != self.editor.data[:offset]
            or checked.data[offset + width :] != self.editor.data[offset + width :]
            or checked.data[offset : offset + width] != new[0].to_bytes(width, "big")
            or observed != {**graph, "connections": expected_wires}
            or checked.summary()["instance"] != self.editor.instance
        ):
            raise ValueError("Native wire output failed exact byte/diagram preservation.")
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source_sha256": self.editor.source_sha256,
            "source_native_sha256": sha(self.editor.data),
            "diagram_ref": diagram_ref,
            "record_sha256": record_sha256,
            "property_sha256": property_sha256,
            "wire_index": wire_index,
            "old": old,
            "new": new,
            "old_source_ref": wire["source_ref"],
            "source_ref": source_ref,
            "source_class": selected["class_id"],
            "target_ref": wire["target_ref"],
            "source_index_offset": offset,
            "source_index_bytes": width,
            "changed": changed,
            "output_sha256": sha(output),
            "output_native_sha256": sha(checked.data),
            "other_expanded_bytes_preserved": True,
            "native_structure_readback_verified": True,
            "saved_settings_merged": False,
            "controller_write": False,
            "field_transfer_enabled": False,
        }
        return output, {**body, "compilation_sha256": seal(body)}
