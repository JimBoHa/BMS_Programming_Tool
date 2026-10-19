"""Inspect and narrowly edit native connection records in observed JCI CAFs.

This is an archive editor, not a CCT compiler or a firmware loader. The graph
encoding was observed in seven authorized local CAFs; those files are never
distributed. Unknown properties and every unrelated XML byte are preserved.
An edited file still needs acceptance by the matching CCT/PCT and target device.
"""

from __future__ import annotations

import copy
import hashlib
import html
import io
import re
import zipfile
from typing import Any

from .caf import ATTRIBUTES, BY_CLASS, CLASSES, CafArchive, Q

GRAPH_CLASSES = {"536", "575"}
MAX_REWIRES = 1000
VALIDATION = (
    "Observed native CAF graph records only. CCT/PCT acceptance, firmware execution, "
    "and controller transfer remain unverified."
)


def _integer(text: str | None, maximum: int = 65535) -> int:
    value = (text or "").strip()
    if not re.fullmatch(r"[0-9]{1,10}", value) or not 0 <= int(value) <= maximum:
        raise ValueError("CAF graph index or identifier is outside its unsigned range.")
    return int(value)


def _shape(element: Any) -> tuple:
    """Compare all opaque configuration, without relying on dictionary labels."""
    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        element.text or "",
        element.tail or "",
        tuple(_shape(child) for child in element),
    )


def _properties(obj: Any) -> dict:
    props = {}
    for prop in obj:
        if prop.tag != Q + "property":
            continue
        pid = prop.get("id")
        if pid in props:
            raise ValueError("CAF graph object has duplicate property identifiers.")
        props[pid] = prop
    return props


def _collection(props: dict, pid: str, kind: str) -> Any:
    prop = props.get(pid)
    if prop is None or len(prop) != 1 or prop[0].tag != Q + "data" or len(prop[0]) != 1:
        raise ValueError(f"CAF graph property {pid} requires one data value.")
    value = prop[0][0]
    if value.tag != Q + kind:
        raise ValueError(f"CAF graph property {pid} requires {kind}.")
    return value


def _record(record: Any, types: tuple[str, ...]) -> list[Any]:
    if record.tag != Q + "struct" or len(record) != len(types):
        raise ValueError("Unrecognized CAF graph record structure.")
    values = []
    for field, kind in zip(record, types, strict=True):
        if (
            field.tag != Q + "structElement"
            or len(field) != 1
            or field[0].tag != Q + kind
            or len(field[0])
            or field.attrib
            or field[0].attrib
        ):
            raise ValueError("Unrecognized CAF graph record field.")
        values.append(field[0].text or "")
    return values


class CafGraph:
    """A native archive view. No graph is converted to a different file format."""

    def __init__(self, content: bytes | CafArchive):
        self.archive = content if isinstance(content, CafArchive) else CafArchive(content)

    def diagrams(self) -> dict:
        rows, errors = [], []
        for ref, obj in self.archive.objects.items():
            if obj.get("classid") not in GRAPH_CLASSES:
                continue
            try:
                graph = self.diagram(ref)
                rows.append(
                    {
                        "ref": ref,
                        "class_id": graph["class_id"],
                        "name": graph["name"],
                        "blocks": len(graph["blocks"]),
                        "connections": len(graph["connections"]),
                        "observed_version": graph["observed_version"],
                    }
                )
            except ValueError as exc:
                errors.append({"ref": ref, "error": str(exc)})
        return {
            "sha256": self.archive.hash,
            "diagrams": rows,
            "errors": errors,
            "validation": VALIDATION,
            "capabilities": {
                "native_graph_inspection": True,
                "guarded_existing_source_rewire": True,
                "guarded_existing_block_connection_creation": True,
                "new_object_creation": False,
                "native_compile": False,
                "native_download": False,
            },
        }

    def diagram(self, ref: str) -> dict:
        obj = self.archive.objects.get(ref)
        if obj is None or obj.get("classid") not in GRAPH_CLASSES:
            raise ValueError("CAF object is not an observed Control Activity or Control Sequence.")
        props = _properties(obj)
        listed = _collection(props, "3375", "array")
        positions = _collection(props, "3383", "listof")
        continuations = _collection(props, "3384", "listof")
        ordered = _collection(props, "3117", "array")
        connected = _collection(props, "3118", "array")
        if len(listed) > 65535:
            raise ValueError("CAF graph block list exceeds unsigned-short indices.")
        if len(positions) != len(listed) or len(continuations) != len(connected):
            raise ValueError("CAF graph parallel position/continuation records do not align.")
        blocks, seen = [], set()
        for index, (entry, position) in enumerate(zip(listed, positions, strict=True)):
            if entry.tag != Q + "BACoid" or len(entry) or set(entry.attrib) != {"id"}:
                raise ValueError("CAF graph block list contains an unrecognized object identifier.")
            type_id = _integer(entry.get("id"))
            instance = _integer(entry.text, 4294967295)
            block_ref = f"{ref}.{type_id}_{instance}"
            block = self.archive.objects.get(block_ref)
            if block is None or block_ref in seen:
                raise ValueError("CAF graph block is missing, ambiguous, or listed more than once.")
            seen.add(block_ref)
            block_props = _properties(block)
            identity = self.archive.scalar(block_props.get("75")) if "75" in block_props else None
            if (
                identity is None
                or identity["type"] != "BACoid"
                or identity["attributes"] != {"id": str(type_id)}
                or _integer(identity["text"], 4294967295) != instance
                or _integer(block.get("objectid"), 4294967295) != instance
            ):
                raise ValueError("CAF graph block identity disagrees with its native reference.")
            x, y, opaque_code = _record(position, ("float", "float", "unsignedShort"))
            # Preserve coordinate spellings and the third field. Its meaning is not
            # inferred from its location in the record.
            layout = {"x": x, "y": y, "opaque_code": _integer(opaque_code)}
            name = self.archive.scalar(block_props.get("2390")) if "2390" in block_props else None
            ports = []
            if "3184" in block_props:
                for port in _collection(block_props, "3184", "array"):
                    if port.tag != Q + "enum" or len(port) or port.get("set") != "509":
                        raise ValueError("Unrecognized CAF graph exposed-port representation.")
                    port_id = _integer(port.text)
                    ports.append(
                        {
                            "id": port_id,
                            "name": BY_CLASS.get(block.get("classid"), {}).get(
                                str(port_id), ATTRIBUTES.get(str(port_id), "Unmapped property")
                            ),
                        }
                    )
            blocks.append(
                {
                    "index": index,
                    "ref": block_ref,
                    "bacnet_type": type_id,
                    "instance": instance,
                    "class_id": block.get("classid"),
                    "class_version": block.get("classVersion"),
                    "class_name": CLASSES.get(block.get("classid"), {}).get(
                        "name", "Unknown class"
                    ),
                    "name": (name or {}).get("text", ""),
                    "layout": layout,
                    "exposed_ports": ports,
                }
            )
        sequence = []
        for item in ordered:
            if item.tag != Q + "unsignedShort" or len(item) or item.attrib:
                raise ValueError("Unrecognized CAF graph execution-order representation.")
            sequence.append(_integer(item.text))
        if sorted(sequence) != list(range(len(blocks))):
            raise ValueError("CAF graph execution order must list each block exactly once.")
        ranks = {block_index: rank for rank, block_index in enumerate(sequence)}
        for block in blocks:
            block["execution_index"] = ranks[block["index"]]
        wires = []
        for index, (wire, continuation) in enumerate(zip(connected, continuations, strict=True)):
            fields = [_integer(v) for v in _record(wire, ("unsignedShort",) * 4)]
            source, source_port, target, target_port = fields
            if source >= len(blocks) or target >= len(blocks):
                raise ValueError("CAF graph connection points outside its block list.")
            flag, text = _record(continuation, ("boolean", "string"))
            if flag not in ("0", "1", "false", "true"):
                raise ValueError("CAF graph continuation flag requires a native boolean value.")
            wires.append(
                {
                    "index": index,
                    "raw": fields,
                    "source_ref": blocks[source]["ref"],
                    "source_port": source_port,
                    "target_ref": blocks[target]["ref"],
                    "target_port": target_port,
                    "continuation": {"flag": flag in ("1", "true"), "text": text},
                }
            )
        name = self.archive.scalar(props.get("2390")) if "2390" in props else None
        return {
            "ref": ref,
            "class_id": obj.get("classid"),
            "class_version": obj.get("classVersion"),
            "observed_version": obj.get("classVersion") == "1.0",
            "name": (name or {}).get("text", ""),
            "blocks": blocks,
            "connections": wires,
            "execution_order": sequence,
            "validation": VALIDATION,
        }

    def _source_signature(self, ref: str) -> tuple:
        obj = self.archive.objects[ref]
        items = []
        for prop in obj:
            pid = prop.get("id")
            if prop.tag == Q + "property" and pid in {"75", "32527", "2390", "28"}:
                continue
            if prop.tag == Q + "property" and pid == "3113":
                scalar = self.archive.scalar(prop)
                if scalar is None:
                    raise ValueError("CAF source default value has an unrecognized structure.")
                # Values can differ; their exact native type and attributes cannot.
                items.append(
                    ("default_type", scalar["type"], tuple(sorted(scalar["attributes"].items())))
                )
            else:
                items.append(_shape(prop))
        return obj.get("classid"), obj.get("classVersion"), tuple(items)

    def rewire_sources(self, changes: list[dict]) -> tuple[bytes, list[dict]]:
        """Replace an existing wire's source with a matching, already used source.

        The destination, property IDs, block list, execution order, identities,
        continuation records, and every other XML byte stay unchanged. A new
        source must have identical opaque configuration/type information, except
        names/identities and the text of an existing typed default value. This is
        deliberately narrower than adding blocks or choosing arbitrary ports.
        """
        if not isinstance(changes, list) or len(changes) > MAX_REWIRES:
            raise ValueError("CAF rewires require a list of at most 1000 changes.")
        if not changes:
            return self.archive.original, []
        graphs, edits, used, observed_outgoing = {}, [], set(), {}
        for change in changes:
            if not isinstance(change, dict) or set(change) != {
                "diagram_ref",
                "wire_index",
                "old",
                "source_ref",
            }:
                raise ValueError("CAF rewires require diagram_ref, wire_index, old and source_ref.")
            ref, index = change["diagram_ref"], change["wire_index"]
            if not isinstance(ref, str) or type(index) is not int or index < 0:
                raise ValueError("CAF rewire diagram/index is invalid.")
            if (ref, index) in used:
                raise ValueError("Duplicate CAF connection change.")
            used.add((ref, index))
            if ref not in graphs:
                graphs[ref] = self.diagram(ref)
                observed_outgoing[ref] = {
                    (wire["source_ref"], wire["source_port"]) for wire in graphs[ref]["connections"]
                }
            graph = graphs[ref]
            if not graph["observed_version"]:
                raise ValueError("CAF rewiring supports only the observed class version 1.0.")
            if index >= len(graph["connections"]):
                raise ValueError("CAF connection index was not found.")
            wire = graph["connections"][index]
            old = change["old"]
            if (
                not isinstance(old, list)
                or len(old) != 4
                or any(type(v) is not int for v in old)
                or old != wire["raw"]
            ):
                raise ValueError("CAF rewire conflict: original connection no longer matches.")
            sources = [b for b in graph["blocks"] if b["ref"] == change["source_ref"]]
            if len(sources) != 1:
                raise ValueError("CAF source must be an existing block in the same diagram.")
            source = sources[0]
            if source["ref"] == wire["source_ref"]:
                continue
            if self._source_signature(source["ref"]) != self._source_signature(wire["source_ref"]):
                raise ValueError(
                    "CAF replacement source has different native configuration/type information."
                )
            if (source["ref"], wire["source_port"]) not in observed_outgoing[ref]:
                raise ValueError(
                    "CAF source port must already be used by an observed outgoing connection."
                )
            target = graph["blocks"][wire["raw"][2]]
            if source["execution_index"] >= target["execution_index"]:
                raise ValueError("CAF replacement source must execute before the destination.")
            new = [source["index"], *wire["raw"][1:]]
            edits.append({"diagram_ref": ref, "wire_index": index, "old": list(old), "new": new})
            wire["raw"] = new
            wire["source_ref"] = source["ref"]
        # A new dependency must not introduce feedback through existing wires.
        for edit in edits:
            graph = graphs[edit["diagram_ref"]]
            start, goal = edit["new"][2], edit["new"][0]
            adjacency: dict[int, set[int]] = {}
            for wire in graph["connections"]:
                s, _, t, _ = wire["raw"]
                adjacency.setdefault(s, set()).add(t)
            pending, visited = [start], set()
            while pending:
                node = pending.pop()
                if node == goal:
                    raise ValueError("CAF rewire would create or join a feedback cycle.")
                if node not in visited:
                    visited.add(node)
                    pending.extend(adjacency.get(node, set()) - visited)
        if not edits:
            return self.archive.original, []
        xml = self.archive.xml
        for edit in edits:
            xml = self._patch_source_index(xml, edit)
        return self._export_edits(xml, graphs, edits)

    def add_connections(self, changes: list[dict]) -> tuple[bytes, list[dict]]:
        """Add native connection records between existing blocks from a prototype.

        Both endpoint configurations must match those of an observed connection
        in this same archive. Ports come from that prototype, never from guessed
        identifiers. The target must be unwired, the source must precede it, and
        adding the dependency must not create or join feedback. No block or
        identity is created, and native vendor acceptance remains unverified.
        """
        if not isinstance(changes, list) or len(changes) > MAX_REWIRES:
            raise ValueError("CAF connections require a list of at most 1000 changes.")
        if not changes:
            return self.archive.original, []
        originals, graphs, edits = {}, {}, []

        def original(ref):
            if ref not in originals:
                originals[ref] = self.diagram(ref)
            return originals[ref]

        for change in changes:
            if not isinstance(change, dict) or set(change) != {
                "diagram_ref",
                "prototype_diagram_ref",
                "prototype_wire_index",
                "prototype_old",
                "source_ref",
                "target_ref",
                "old_connection_count",
            }:
                raise ValueError(
                    "CAF connections require diagram_ref, prototype_diagram_ref, "
                    "prototype_wire_index, prototype_old, source_ref, target_ref and old_connection_count."
                )
            ref, proto_ref = change["diagram_ref"], change["prototype_diagram_ref"]
            index, expected_count = change["prototype_wire_index"], change["old_connection_count"]
            if (
                not all(
                    isinstance(change[key], str)
                    for key in ("diagram_ref", "prototype_diagram_ref", "source_ref", "target_ref")
                )
                or type(index) is not int
                or index < 0
                or type(expected_count) is not int
                or not 0 <= expected_count <= 65535
            ):
                raise ValueError(
                    "CAF connection references, prototype index or original count are invalid."
                )
            observed = original(ref)
            proto = original(proto_ref)
            if (
                not observed["observed_version"]
                or not proto["observed_version"]
                or observed["class_id"] != proto["class_id"]
            ):
                raise ValueError(
                    "CAF connection prototype requires the same observed diagram class/version 1.0."
                )
            if expected_count != len(observed["connections"]):
                raise ValueError(
                    "CAF connection conflict: original connection count no longer matches."
                )
            if index >= len(proto["connections"]):
                raise ValueError("CAF connection prototype index was not found.")
            prototype = proto["connections"][index]
            old = change["prototype_old"]
            if (
                not isinstance(old, list)
                or len(old) != 4
                or any(type(value) is not int for value in old)
                or old != prototype["raw"]
            ):
                raise ValueError(
                    "CAF connection conflict: original prototype tuple no longer matches."
                )
            if ref not in graphs:
                graphs[ref] = copy.deepcopy(observed)
            graph = graphs[ref]
            by_ref = {block["ref"]: block for block in graph["blocks"]}
            source = by_ref.get(change["source_ref"])
            target = by_ref.get(change["target_ref"])
            if source is None or target is None:
                raise ValueError(
                    "CAF connection endpoints must be existing blocks in the destination diagram."
                )
            if self._source_signature(source["ref"]) != self._source_signature(
                prototype["source_ref"]
            ) or self._source_signature(target["ref"]) != self._source_signature(
                prototype["target_ref"]
            ):
                raise ValueError(
                    "CAF connection endpoints differ from the prototype's native configuration/type information."
                )
            if any(
                wire["target_ref"] == target["ref"]
                and wire["target_port"] == prototype["target_port"]
                for wire in graph["connections"]
            ):
                raise ValueError("CAF connection destination property already has a writer.")
            if source["execution_index"] >= target["execution_index"]:
                raise ValueError("CAF connection source must execute before the destination.")
            if len(graph["connections"]) >= 65535:
                raise ValueError("CAF connection list exceeds the conservative 65535-record limit.")
            values = [
                source["index"],
                prototype["source_port"],
                target["index"],
                prototype["target_port"],
            ]
            new_index = len(graph["connections"])
            graph["connections"].append(
                {
                    "index": new_index,
                    "raw": values,
                    "source_ref": source["ref"],
                    "source_port": values[1],
                    "target_ref": target["ref"],
                    "target_port": values[3],
                    "continuation": {"flag": False, "text": ""},
                }
            )
            edits.append(
                {
                    "diagram_ref": ref,
                    "wire_index": new_index,
                    "new": values,
                    "prototype_diagram_ref": proto_ref,
                    "prototype_wire_index": index,
                    "prototype_old": list(old),
                    "old_connection_count": expected_count,
                }
            )
        for edit in edits:
            graph = graphs[edit["diagram_ref"]]
            start, goal = edit["new"][2], edit["new"][0]
            adjacency: dict[int, set[int]] = {}
            for wire in graph["connections"]:
                source, _, target, _ = wire["raw"]
                adjacency.setdefault(source, set()).add(target)
            pending, visited = [start], set()
            while pending:
                node = pending.pop()
                if node == goal:
                    raise ValueError("CAF connection would create or join a feedback cycle.")
                if node not in visited:
                    visited.add(node)
                    pending.extend(adjacency.get(node, set()) - visited)
        xml = self.archive.xml
        for edit in edits:
            fields = b"".join(
                b"<structElement><unsignedShort>"
                + str(value).encode("ascii")
                + b"</unsignedShort></structElement>"
                for value in edit["new"]
            )
            xml = self._append_record(
                xml, edit["diagram_ref"], "3118", "array", b"<struct>" + fields + b"</struct>"
            )
            continuation = (
                b"<struct><structElement><boolean>0</boolean></structElement>"
                b"<structElement><string /></structElement></struct>"
            )
            xml = self._append_record(xml, edit["diagram_ref"], "3384", "listof", continuation)
        return self._export_edits(xml, graphs, edits)

    def _export_edits(
        self, xml: bytes, graphs: dict, edits: list[dict]
    ) -> tuple[bytes, list[dict]]:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.comment = self.archive.comment
            archive.writestr(copy.copy(self.archive.info), xml)
        result = out.getvalue()
        verified = CafGraph(result)
        if list(verified.archive.objects) != list(self.archive.objects) or any(
            verified.archive.objects[ref].attrib != obj.attrib
            for ref, obj in self.archive.objects.items()
        ):
            raise ValueError("CAF graph patch unexpectedly changed object identities.")
        for ref, expected in graphs.items():
            actual = verified.diagram(ref)
            if actual != expected:
                raise ValueError("CAF graph patch readback did not match its staged graph.")
        for edit in edits:
            edit["validation"] = VALIDATION
            edit["source_sha256"] = self.archive.hash
            edit["result_sha256"] = hashlib.sha256(result).hexdigest()
        return result, edits

    @staticmethod
    def _append_record(xml: bytes, ref: str, pid: str, collection: str, record: bytes) -> bytes:
        spans = []
        for start in re.finditer(rb"<object\b[^>]*>", xml):
            found = re.search(rb'\bref="([^"]*)"', start.group())
            if found and html.unescape(found[1].decode("utf-8")) == ref:
                end = xml.find(b"</object>", start.end())
                if end < 0:
                    raise ValueError("Cannot locate CAF graph object boundary.")
                spans.append((start.start(), end + len(b"</object>")))
        if len(spans) != 1:
            raise ValueError("Unrecognized CAF graph XML serialization; refusing to rewrite.")
        begin, end = spans[0]
        section = xml[begin:end]
        expression = rb'<property\s+id="' + pid.encode("ascii") + rb'"\s*>\s*<data>\s*'
        tag = collection.encode("ascii")
        expression += (
            rb"(?P<value><"
            + tag
            + rb"\s*/>|<"
            + tag
            + rb">.*?</"
            + tag
            + rb">)\s*</data>\s*</property>"
        )
        matches = list(re.finditer(expression, section, re.S))
        if len(matches) != 1:
            raise ValueError(
                "Unrecognized CAF collection serialization; refusing to append native records."
            )
        value = matches[0]
        a, b = begin + value.start("value"), begin + value.end("value")
        if value["value"].endswith(b"/>"):
            replacement = b"<" + tag + b">" + record + b"</" + tag + b">"
            return xml[:a] + replacement + xml[b:]
        insert = b - len(b"</" + tag + b">")
        return xml[:insert] + record + xml[insert:]

    @staticmethod
    def _patch_source_index(xml: bytes, edit: dict) -> bytes:
        spans = []
        for start in re.finditer(rb"<object\b[^>]*>", xml):
            found = re.search(rb'\bref="([^"]*)"', start.group())
            if found and html.unescape(found[1].decode("utf-8")) == edit["diagram_ref"]:
                end = xml.find(b"</object>", start.end())
                if end < 0:
                    raise ValueError("Cannot locate CAF graph object boundary.")
                spans.append((start.start(), end + len(b"</object>")))
        if len(spans) != 1:
            raise ValueError("Unrecognized CAF graph XML serialization; refusing to rewrite.")
        begin, end = spans[0]
        section = xml[begin:end]
        properties = list(re.finditer(rb'<property\s+id="3118"\s*>.*?</property>', section, re.S))
        if len(properties) != 1:
            raise ValueError("Unrecognized CAF connection-list serialization; refusing to rewrite.")
        prop = properties[0]
        rows = list(re.finditer(rb"<struct>.*?</struct>", prop[0], re.S))
        if edit["wire_index"] >= len(rows):
            raise ValueError("Cannot locate CAF connection record.")
        row = rows[edit["wire_index"]]
        fields = list(re.finditer(rb"<unsignedShort>([0-9]+)</unsignedShort>", row[0]))
        if len(fields) != 4 or [int(field[1]) for field in fields] != edit["old"]:
            raise ValueError("CAF connection bytes do not match the observed tuple serialization.")
        field = fields[0]
        start = begin + prop.start() + row.start() + field.start(1)
        stop = begin + prop.start() + row.start() + field.end(1)
        return xml[:start] + str(edit["new"][0]).encode("ascii") + xml[stop:]
