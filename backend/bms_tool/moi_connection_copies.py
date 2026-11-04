"""Prototype-qualified local native connection additions between existing members."""

import copy
import struct
import zlib

from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import Boolean, CharacterString, Tag, TagClass, Unsigned

from .moi_application import MAX_EXPANDED, MAX_SOURCE, MAX_TAGS, _structs
from .moi_identity import MoiIdentity, seal, sha
from .moi_wire_sources import MoiWireSources

PROFILE = "tagged-moi-connection-copy/1"
SCOPE = (
    "Local native archive copy adding one prototype-matched connection between existing "
    "members. Require recorded compatible classes/configuration, an observed output pin, "
    "an unused matching input, execution before destination and no introduced cycle. "
    "Retain other expanded bytes, IDs, membership, order and layout; copy recorded optional "
    "Boolean/String continuation metadata. No saved-setting merge, new blocks/I/O, field "
    "transfer, general resource/compiler/runtime or CCT/physical acceptance is granted."
)


class MoiConnectionCopies:
    def __init__(self, source):
        self.wire = MoiWireSources(source)
        self.editor = self.wire.editor

    def _parts(self, prop, kinds):
        values = _structs(prop["tags"], kinds)
        start, end = prop["value_start_offset"], prop["value_end_offset"]
        pdu, tokens = PDUData(self.editor.data[start:end]), []
        while pdu.pduData:
            before = len(pdu.pduData)
            tag = Tag.decode(pdu)
            tokens.append((tag, end - before, end - len(pdu.pduData)))
        width = len(kinds) + 2
        if (
            not tokens
            or len(tokens) != len(values) * width + 1
            or tokens[-1][0].tag_class != TagClass.closing
            or tokens[-1][0].tag_number != 2
            or _structs([x[0] for x in tokens[:-1]], kinds) != values
        ):
            raise ValueError("Connection copy requires exact known native property framing.")
        return (
            values,
            [tokens[i : i + width] for i in range(0, len(tokens) - 1, width)],
            tokens[-1][1],
        )

    def _load(self, diagram_ref):
        graph, record, prop, wires = self.wire.graph(diagram_ref)
        values, rows, wire_end = self._parts(prop, (Unsigned,) * 4)
        if values != [row["old"] for row in wires]:
            raise ValueError("Connection prototype bytes disagree with the actual native graph.")
        ports = {(row["target_ref"], row["target_port"]) for row in wires}
        if len(ports) != len(wires):
            raise ValueError("Existing native graph has ambiguous input ownership.")
        metadata = record["properties"].get(3384)
        meta_values, meta_rows, meta_end = (None, None, None)
        if metadata is not None:
            meta_values, meta_rows, meta_end = self._parts(metadata, (Boolean, CharacterString))
            if len(meta_rows) != len(wires):
                raise ValueError("Native continuation metadata does not align with the wire list.")
        return (
            graph,
            record,
            prop,
            wires,
            rows,
            wire_end,
            metadata,
            meta_values,
            meta_rows,
            meta_end,
        )

    @staticmethod
    def _index(value, count):
        if type(value) is not int or not 0 <= value <= 4095:
            raise ValueError("Choose an actual bounded native connection prototype index.")
        if value >= count and (count or value != 0):
            raise ValueError("Choose an actual recorded native connection prototype.")

    def _sources(self, graph, wires, prototype):
        observed = {(row["source_ref"], row["source_port"]) for row in wires}
        return [
            row
            for row in graph["blocks"]
            if self.wire.signatures[row["ref"]] == self.wire.signatures[prototype["source_ref"]]
            and (row["ref"], prototype["source_port"]) in observed
        ]

    def _targets(self, graph, wires, prototype, source_ref):
        positions = {index: pos for pos, index in enumerate(graph["execution_order"])}
        blocks = {row["ref"]: row for row in graph["blocks"]}
        occupied = {(row["target_ref"], row["target_port"]) for row in wires}
        reverse = {}
        for row in wires:
            reverse.setdefault(row["target_ref"], []).append(row["source_ref"])
        pending, ancestors = [source_ref], set()
        while pending:
            ref = pending.pop()
            if ref in ancestors:
                continue
            ancestors.add(ref)
            pending.extend(reverse.get(ref, []))
        return [
            row
            for row in graph["blocks"]
            if self.wire.signatures[row["ref"]] == self.wire.signatures[prototype["target_ref"]]
            and (row["ref"], prototype["target_port"]) not in occupied
            and positions[blocks[source_ref]["index"]] < positions[row["index"]]
            and row["ref"] not in ancestors
        ]

    def inspect(self, diagram_ref, prototype_index=0, source_ref=None):
        graph, record, prop, wires, *_ = self._load(diagram_ref)
        self._index(prototype_index, len(wires))
        prototype = wires[prototype_index] if wires else None
        if source_ref is not None and not isinstance(source_ref, str):
            raise ValueError("Select an exact existing native output member.")
        sources = self._sources(graph, wires, prototype) if prototype else []
        selected = (
            source_ref if source_ref is not None else prototype["source_ref"] if prototype else None
        )
        if selected is not None and selected not in {row["ref"] for row in sources}:
            raise ValueError("The output lacks matching recorded configuration or an observed pin.")
        targets = self._targets(graph, wires, prototype, selected) if prototype else []
        metadata = record["properties"].get(3384)
        budget = len(wires) < 4096 and (len(wires) + 1) * 6 + 1 <= MAX_TAGS

        def brief(row):
            return {key: row[key] for key in ("index", "ref", "name", "class_id", "object")}

        return {
            "diagram_ref": diagram_ref,
            "record_sha256": record["sha256"],
            "property_sha256": prop["encoded_sha256"],
            "metadata_property_sha256": metadata["encoded_sha256"] if metadata else None,
            "prototype_index": prototype_index,
            "prototype": prototype,
            "wires": wires,
            "sources": [brief(row) for row in sources],
            "source_ref": selected,
            "targets": [brief(row) for row in targets],
            "connection_count": len(wires),
            "block_count": len(graph["blocks"]),
            "available": bool(prototype and targets and budget),
            "budget_available": budget,
            "continuation_metadata": "recorded-boolean-string" if metadata else "not-recorded",
        }

    def compile(
        self,
        *,
        source_sha256,
        diagram_ref,
        record_sha256,
        property_sha256,
        metadata_property_sha256,
        prototype_index,
        prototype_old,
        connection_count,
        source_ref,
        target_ref,
    ):
        if source_sha256 != self.editor.source_sha256:
            raise ValueError("The original native archive changed; inspect its current source.")
        if not isinstance(source_ref, str) or not isinstance(target_ref, str):
            raise ValueError("Choose exact existing native source and destination references.")
        selection = self.inspect(diagram_ref, prototype_index, source_ref)
        if (
            record_sha256 != selection["record_sha256"]
            or property_sha256 != selection["property_sha256"]
            or metadata_property_sha256 != selection["metadata_property_sha256"]
        ):
            raise ValueError("The native record, wire or continuation property changed.")
        if (
            type(connection_count) is not int
            or connection_count != selection["connection_count"]
            or type(prototype_old) is not list
            or len(prototype_old) != 4
            or any(type(value) is not int or not 0 <= value <= 65535 for value in prototype_old)
            or not selection["prototype"]
            or prototype_old != selection["prototype"]["old"]
        ):
            raise ValueError("The original native connection count or prototype tuple changed.")
        if not selection["budget_available"]:
            raise ValueError("New native connection exceeds the existing connection/tag budget.")
        if target_ref not in {row["ref"] for row in selection["targets"]}:
            raise ValueError(
                "Destination configuration, input ownership, execution order or cycle guard refuses this connection."
            )
        graph, record, prop, wires, rows, wire_end, metadata, meta_values, meta_rows, meta_end = (
            self._load(diagram_ref)
        )
        blocks = {row["ref"]: row for row in graph["blocks"]}
        new = [
            blocks[source_ref]["index"],
            prototype_old[1],
            blocks[target_ref]["index"],
            prototype_old[3],
        ]
        prototype = rows[prototype_index]
        data = self.editor.data
        chunks = [data[prototype[0][1] : prototype[0][2]]]
        for i, (tag, start, end) in enumerate(prototype[1:-1]):
            width = len(tag.tag_data)
            if i in (1, 3):
                chunks.append(data[start:end])
            elif new[i] < 1 << (8 * width):
                chunks.append(data[start : end - width] + new[i].to_bytes(width, "big"))
            else:
                width = max(1, (new[i].bit_length() + 7) // 8)
                chunks.append(bytes([0x20 | width]) + new[i].to_bytes(width, "big"))
        chunks.append(data[prototype[-1][1] : prototype[-1][2]])
        wire_bytes = b"".join(chunks)
        inserts = [(wire_end, wire_bytes)]
        metadata_bytes = None
        if metadata:
            row = meta_rows[prototype_index]
            metadata_bytes = data[row[0][1] : row[-1][2]]
            inserts.append((meta_end, metadata_bytes))
        start, end = record["offset"], record["end_offset"]
        raw = data[start:end]
        for offset, extra in sorted(inserts, reverse=True):
            raw = raw[: offset - start] + extra + raw[offset - start :]
        framed, previous = bytearray(data[:14]), 14
        prefix_growth = 0
        for item in self.editor.records:
            a, b = item["offset"], item["end_offset"]
            prefix, body = data[previous:a], data[a:b]
            if a == start:
                body = raw
                old_prefix_bytes = len(prefix)
                prefix = (
                    b"\x00\x00" + struct.pack("<I", len(body) + 6)
                    if len(prefix) == 6 or len(body) + 2 > 65535
                    else struct.pack("<H", len(body) + 2)
                )
                prefix_growth = len(prefix) - old_prefix_bytes
            framed.extend(prefix + body)
            previous = b
        native = bytes(framed)
        if len(native) > MAX_EXPANDED or (not self.editor.compressed and len(native) > MAX_SOURCE):
            raise ValueError("New connection exceeds the existing native file size budget.")
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
        if checked.data[:14] != data[:14] or len(checked.records) != len(self.editor.records):
            raise ValueError("Connection copy changed native application header or record count.")
        old_previous = new_previous = 14
        growth = len(raw) - (end - start) + prefix_growth
        for before, after in zip(self.editor.records, checked.records, strict=True):
            expected_offset = before["offset"] + (
                prefix_growth
                if before["offset"] == start
                else growth
                if before["offset"] > start
                else 0
            )
            if after["offset"] != expected_offset:
                raise ValueError(
                    "Connection copy moved a native record beyond its exact append delta."
                )
            old_raw = data[before["offset"] : before["end_offset"]]
            new_raw = checked.data[after["offset"] : after["end_offset"]]
            if new_raw != (raw if before["offset"] == start else old_raw):
                raise ValueError("Connection copy changed an unrelated native record byte.")
            if (
                before["offset"] != start
                and data[old_previous : before["offset"]]
                != checked.data[new_previous : after["offset"]]
            ):
                raise ValueError("Connection copy changed another native record prefix.")
            old_previous, new_previous = before["end_offset"], after["end_offset"]
        new_wire = {
            "index": len(wires),
            "source_ref": source_ref,
            "source_port": new[1],
            "target_ref": target_ref,
            "target_port": new[3],
        }
        expected = copy.deepcopy(graph)
        expected["connections"].append(new_wire)
        # These are inspection offsets into the expanded file, not stored native values.
        # The original member bytes stay exact while their location follows record growth.
        for block in expected["blocks"]:
            shift = growth if self.wire.reader.records[block["ref"]]["offset"] > start else 0
            for field in block["properties"]:
                for key in ("value_start_offset", "value_end_offset"):
                    field[key] += shift
        if (
            checked.reader.diagram(diagram_ref) != expected
            or checked.instance != self.editor.instance
        ):
            raise ValueError("Connection copy failed exact native diagram/identity readback.")
        if metadata:
            actual_values = _structs(
                checked.reader.records[diagram_ref]["properties"][3384]["tags"],
                (Boolean, CharacterString),
            )
            if actual_values != [*meta_values, meta_values[prototype_index]]:
                raise ValueError(
                    "Connection continuation readback differs from its recorded prototype."
                )
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source_sha256": self.editor.source_sha256,
            "source_native_sha256": sha(data),
            "diagram_ref": diagram_ref,
            "record_sha256": record_sha256,
            "property_sha256": property_sha256,
            "metadata_property_sha256": metadata_property_sha256,
            "prototype_index": prototype_index,
            "prototype_old": prototype_old,
            "prototype_encoding_hex": data[prototype[0][1] : prototype[-1][2]].hex(),
            "new": new,
            "new_encoding_hex": wire_bytes.hex(),
            "source_ref": source_ref,
            "target_ref": target_ref,
            "connection_count_before": len(wires),
            "connection_count_after": len(wires) + 1,
            "continuation_prototype_sha256": sha(metadata_bytes) if metadata_bytes else None,
            "record_bytes_before": end - start,
            "record_bytes_after": len(raw),
            "record_prefix_growth": prefix_growth,
            "native_bytes_growth": growth,
            "output_sha256": sha(output),
            "output_native_sha256": sha(checked.data),
            "other_expanded_bytes_preserved": True,
            "native_structure_readback_verified": True,
            "saved_settings_merged": False,
            "controller_write": False,
            "field_transfer_enabled": False,
        }
        return output, {**body, "compilation_sha256": seal(body)}
