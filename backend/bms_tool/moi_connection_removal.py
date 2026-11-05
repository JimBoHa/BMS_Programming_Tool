"""Loss-preserving local removal of one recorded native connection and continuation."""

import copy
import struct
import zlib

from bacpypes3.primitivedata import Boolean, CharacterString

from .moi_application import _structs
from .moi_connection_copies import MoiConnectionCopies
from .moi_identity import MoiIdentity, seal, sha

PROFILE = "tagged-moi-connection-removal-copy/1"
SCOPE = (
    "Local native archive copy removing one exact recorded connection and its aligned "
    "optional Boolean/String continuation. Preserve every other expanded byte, record "
    "prefix width, identity, member, execution order, layout and destination configuration. "
    "The destination is left unwired; native default/fallback/retention behavior is not "
    "inferred. No saved-setting merge, new blocks/I/O, field transfer, inverse-recovery "
    "authority, general compiler/resource/runtime or CCT/physical acceptance."
)


class MoiConnectionRemoval:
    def __init__(self, source):
        self.original = MoiConnectionCopies(source)
        self.wire, self.editor = self.original.wire, self.original.editor

    def inspect(self, diagram_ref, wire_index=0):
        graph, record, prop, wires, *_ = self.original._load(diagram_ref)
        self.original._index(wire_index, len(wires))
        metadata = record["properties"].get(3384)
        selected = wires[wire_index] if wires else None
        return {
            "diagram_ref": diagram_ref,
            "record_sha256": record["sha256"],
            "property_sha256": prop["encoded_sha256"],
            "metadata_property_sha256": metadata["encoded_sha256"] if metadata else None,
            "wire_index": wire_index,
            "wires": wires,
            "selected_wire": selected,
            "connection_count": len(wires),
            "block_count": len(graph["blocks"]),
            "continuation_metadata": "recorded-boolean-string" if metadata else "not-recorded",
            "available": selected is not None,
        }

    def compile(
        self,
        *,
        source_sha256,
        diagram_ref,
        record_sha256,
        property_sha256,
        metadata_property_sha256,
        wire_index,
        old,
        connection_count,
    ):
        if source_sha256 != self.editor.source_sha256:
            raise ValueError("The original native removal source changed; inspect it again.")
        selection = self.inspect(diagram_ref, wire_index)
        if (
            record_sha256 != selection["record_sha256"]
            or property_sha256 != selection["property_sha256"]
            or metadata_property_sha256 != selection["metadata_property_sha256"]
        ):
            raise ValueError("The native record, connection or continuation property changed.")
        if (
            type(connection_count) is not int
            or connection_count != selection["connection_count"]
            or not 1 <= connection_count <= 4096
            or type(old) is not list
            or len(old) != 4
            or any(type(v) is not int or not 0 <= v <= 65535 for v in old)
            or selection["selected_wire"] is None
            or old != selection["selected_wire"]["old"]
        ):
            raise ValueError("Select the exact existing connection count, index and native tuple.")
        (
            graph,
            record,
            _,
            wires,
            rows,
            _,
            metadata,
            meta_values,
            meta_rows,
            _,
        ) = self.original._load(diagram_ref)
        data = self.editor.data
        row = rows[wire_index]
        removed = data[row[0][1] : row[-1][2]]
        spans = [(row[0][1], row[-1][2])]
        continuation = None
        if metadata is not None:
            entry = meta_rows[wire_index]
            continuation = data[entry[0][1] : entry[-1][2]]
            spans.append((entry[0][1], entry[-1][2]))
        start, end = record["offset"], record["end_offset"]
        raw = data[start:end]
        for a, b in sorted(spans, reverse=True):
            raw = raw[: a - start] + raw[b - start :]
        growth = len(raw) - (end - start)
        if growth != -len(removed) - len(continuation or b"") or growth >= 0:
            raise ValueError("Native removal did not consume only its exact selected rows.")
        framed, previous, selected_width = bytearray(data[:14]), 14, None
        for item in self.editor.records:
            a, b = item["offset"], item["end_offset"]
            prefix, body = data[previous:a], data[a:b]
            if a == start:
                selected_width = len(prefix)
                if selected_width not in (2, 6):
                    raise ValueError("Native removal requires the original known record prefix.")
                body = raw
                # Preserve wide framing even when the reduced record would fit a short prefix.
                prefix = (
                    b"\0\0" + struct.pack("<I", len(body) + 6)
                    if selected_width == 6
                    else struct.pack("<H", len(body) + 2)
                )
            framed.extend(prefix + body)
            previous = b
        native = bytes(framed)
        output = native
        if self.editor.compressed:
            compressor = zlib.compressobj(level=9, wbits=-15)
            output = (
                self.editor.source[:10]
                + compressor.compress(native)
                + compressor.flush()
                + struct.pack("<II", zlib.crc32(native), len(native))
            )
        checked = MoiIdentity(output)
        if checked.data != native or len(checked.records) != len(self.editor.records):
            raise ValueError("Native removal failed full application framing readback.")
        old_previous = new_previous = 14
        for before, after in zip(self.editor.records, checked.records, strict=True):
            expected_offset = before["offset"] + (growth if before["offset"] > start else 0)
            if after["offset"] != expected_offset:
                raise ValueError("Native removal moved another record beyond its exact delta.")
            before_body = data[before["offset"] : before["end_offset"]]
            after_body = checked.data[after["offset"] : after["end_offset"]]
            if after_body != (raw if before["offset"] == start else before_body):
                raise ValueError("Native removal changed an unrelated record byte.")
            before_prefix = data[old_previous : before["offset"]]
            after_prefix = checked.data[new_previous : after["offset"]]
            if (
                len(before_prefix) != len(after_prefix)
                or before["offset"] != start
                and before_prefix != after_prefix
            ):
                raise ValueError("Native removal changed another prefix or its original width.")
            old_previous, new_previous = before["end_offset"], after["end_offset"]
        expected = copy.deepcopy(graph)
        del expected["connections"][wire_index]
        for index, wire in enumerate(expected["connections"]):
            wire["index"] = index
        for block in expected["blocks"]:
            shift = growth if self.wire.reader.records[block["ref"]]["offset"] > start else 0
            for prop in block["properties"]:
                for key in ("value_start_offset", "value_end_offset"):
                    prop[key] += shift
        if (
            checked.reader.diagram(diagram_ref) != expected
            or checked.instance != self.editor.instance
        ):
            raise ValueError(
                "Native removal changed diagram membership, identity, order or layout."
            )
        if metadata is not None:
            actual = _structs(
                checked.reader.records[diagram_ref]["properties"][3384]["tags"],
                (Boolean, CharacterString),
            )
            if actual != meta_values[:wire_index] + meta_values[wire_index + 1 :]:
                raise ValueError("Native removal changed another continuation row.")
        selected = wires[wire_index]
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source_sha256": self.editor.source_sha256,
            "source_native_sha256": sha(data),
            "diagram_ref": diagram_ref,
            "record_sha256": record_sha256,
            "property_sha256": property_sha256,
            "metadata_property_sha256": metadata_property_sha256,
            "wire_index": wire_index,
            "old": old,
            "source_ref": selected["source_ref"],
            "target_ref": selected["target_ref"],
            "removed_encoding_hex": removed.hex(),
            "removed_continuation_sha256": sha(continuation) if continuation else None,
            "removed_continuation_bytes": len(continuation or b""),
            "connection_count_before": connection_count,
            "connection_count_after": connection_count - 1,
            "record_bytes_before": end - start,
            "record_bytes_after": len(raw),
            "record_prefix_bytes": selected_width,
            "record_prefix_growth": 0,
            "native_bytes_growth": growth,
            "output_sha256": sha(output),
            "output_native_sha256": sha(native),
            "other_expanded_bytes_preserved": True,
            "native_structure_readback_verified": True,
            "destination_configuration_preserved": True,
            "native_fallback_or_retention_verified": False,
            "saved_settings_merged": False,
            "controller_write": False,
            "field_transfer_enabled": False,
        }
        return output, {**body, "compilation_sha256": seal(body)}
