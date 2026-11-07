"""Fixed-width native order copies preserving every recorded wire phase."""

import struct
import zlib

from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import Tag, TagClass

from .moi_identity import MoiIdentity, seal, sha
from .moi_wire_sources import MoiWireSources

PROFILE = "tagged-moi-execution-order-copy/1"
SCOPE = (
    "Local native execution-order copy of existing members. Preserve every recorded wire's "
    "before/same/after relationship, original Unsigned widths and all other expanded bytes. "
    "No new blocks, links, field transfer, native runtime, resources or CCT/physical acceptance."
)


def phases(graph, order):
    rank = {index: position for position, index in enumerate(order)}
    members = {block["ref"]: block["index"] for block in graph["blocks"]}
    return [
        {
            "wire_index": wire["index"],
            "source_index": members[wire["source_ref"]],
            "target_index": members[wire["target_ref"]],
            "relationship": (
                "same"
                if wire["source_ref"] == wire["target_ref"]
                else "before"
                if rank[members[wire["source_ref"]]] < rank[members[wire["target_ref"]]]
                else "after"
            ),
        }
        for wire in graph["connections"]
    ]


class MoiExecutionOrder:
    def __init__(self, content):
        self.wire = MoiWireSources(content)
        self.editor, self.reader = self.wire.editor, self.wire.reader

    def inspect(self, ref):
        graph, record, _, _ = self.wire.graph(ref)
        if not 1 <= len(graph["blocks"]) <= 512:
            raise ValueError("Select a native diagram with 1–512 existing members.")
        prop = record["properties"][3117]
        start, end = prop["value_start_offset"], prop["value_end_offset"]
        pdu = PDUData(self.editor.data[start:end])
        slots = []
        for position, expected in enumerate(graph["execution_order"]):
            before = len(pdu.pduData)
            tag = Tag.decode(pdu)
            consumed = end - len(pdu.pduData)
            if (
                tag.tag_class != TagClass.application
                or tag.tag_number != 2
                or not 1 <= len(tag.tag_data) <= 4
                or int.from_bytes(tag.tag_data, "big") != expected
            ):
                raise ValueError("Native order requires the original bounded Unsigned tags.")
            slots.append(
                {
                    "position": position,
                    "index": expected,
                    "payload_offset": consumed - len(tag.tag_data),
                    "payload_bytes": len(tag.tag_data),
                    "encoded_sha256": sha(self.editor.data[end - before : consumed]),
                }
            )
        closing = Tag.decode(pdu)
        if closing.tag_class != TagClass.closing or closing.tag_number != 2 or pdu.pduData:
            raise ValueError("Native order does not consume its exact property framing.")
        members = [
            {key: b[key] for key in ("index", "ref", "name", "class_id", "object")}
            for b in graph["blocks"]
        ]
        if len(ref) > 512 or any(len(m["ref"]) > 512 or len(m["name"]) > 1024 for m in members):
            raise ValueError("Native order references or labels exceed this bounded profile.")
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source_sha256": self.editor.source_sha256,
            "source_native_sha256": sha(self.editor.data),
            "diagram_ref": ref,
            "diagram_class_id": record["class_id"],
            "record_sha256": record["sha256"],
            "property_sha256": prop["encoded_sha256"],
            "original_order": graph["execution_order"],
            "members": members,
            "slots": slots,
            "edge_relationships": phases(graph, graph["execution_order"]),
        }
        return {**body, "selection_sha256": seal(body)}

    def compile(self, *, diagram_ref, selection_sha256, proposed_order):
        selected = self.inspect(diagram_ref)
        if selection_sha256 != selected["selection_sha256"]:
            raise ValueError("The native order source changed; inspect its current selection.")
        count = len(selected["members"])
        if (
            type(proposed_order) is not list
            or len(proposed_order) != count
            or any(type(v) is not int for v in proposed_order)
            or sorted(proposed_order) != list(range(count))
        ):
            raise ValueError("The native order must contain each existing member exactly once.")
        graph = self.reader.diagram(diagram_ref)
        if phases(graph, proposed_order) != selected["edge_relationships"]:
            raise ValueError("The proposed order changes a recorded wire execution relationship.")
        native = bytearray(self.editor.data)
        edits = []
        for slot, value in zip(selected["slots"], proposed_order, strict=True):
            offset, width = slot["payload_offset"], slot["payload_bytes"]
            if value >= 1 << (8 * width):
                raise ValueError("A reordered index exceeds its original Unsigned payload width.")
            if value != slot["index"]:
                native[offset : offset + width] = value.to_bytes(width, "big")
                edits.append({**slot, "new_index": value})
        if not edits:
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
        expected = {**graph, "execution_order": proposed_order}
        if checked.data != bytes(native) or checked.reader.diagram(diagram_ref) != expected:
            raise ValueError("Native order output failed exact byte and graph readback.")
        if checked.reader.records.keys() != self.reader.records.keys():
            raise ValueError("Native order output changed record identities or membership.")
        for ref, record in self.reader.records.items():
            after = checked.reader.records[ref]
            if ref != diagram_ref and record["sha256"] != after["sha256"]:
                raise ValueError("Native order output changed another record.")
        body = {
            "profile": PROFILE,
            "selection": selected,
            "proposed_order": proposed_order,
            "patches": edits,
            "output_sha256": sha(output),
            "output_native_sha256": sha(checked.data),
            "other_expanded_bytes_preserved": True,
            "native_structure_readback_verified": True,
            "controller_write": False,
            "field_transfer_enabled": False,
        }
        return output, {**body, "compilation_sha256": seal(body)}
