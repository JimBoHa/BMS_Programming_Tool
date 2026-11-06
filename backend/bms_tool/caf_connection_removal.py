"""Source-bound deletion of one CAF connection and its paired continuation row."""

import copy
from typing import Annotated

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field

from .caf import CafArchive
from .caf_constant_copy import CafConstantCopies
from .caf_graph import CafGraph, _collection, _properties, _record
from .models import StrictModel
from .moi_identity import seal, sha

PROFILE = "caf-connection-removal-copy/1"
SCOPE = (
    "Local CAF copy removing one recorded connection and its aligned continuation row. "
    "Preserve all other XML bytes, objects, order, layout and destination configuration. "
    "Native execution, unwired fallback, CCT/PCT acceptance and controller transfer remain unverified."
)
FLAGS = {
    "controller_write": False,
    "field_transfer_enabled": False,
    "native_execution_verified": False,
    "vendor_acceptance_verified": False,
    "can_apply": False,
}
Hash = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
Reference = Annotated[str, Field(strict=True, min_length=1, max_length=512)]
UInt = Annotated[int, Field(strict=True, ge=0, le=65535)]
ZIP_METADATA = (
    "filename",
    "date_time",
    "comment",
    "extra",
    "create_system",
    "create_version",
    "extract_version",
    "reserved",
    "flag_bits",
    "volume",
    "internal_attr",
    "external_attr",
    "compress_type",
)


class Continuation(StrictModel):
    flag: bool = Field(strict=True)
    text: str = Field(strict=True, max_length=8192)


class RemovalSource(StrictModel):
    source_sha256: Hash
    diagram_ref: Reference
    wire_index: int = Field(strict=True, ge=0, le=65534)


class RemovalPreview(RemovalSource):
    selection_sha256: Hash
    diagram_sha256: Hash
    connection_property_sha256: Hash
    continuation_property_sha256: Hash
    connection_record_sha256: Hash
    continuation_record_sha256: Hash
    connection_count: int = Field(strict=True, ge=1, le=65535)
    old: list[UInt] = Field(min_length=4, max_length=4)
    continuation: Continuation


class RemovalExport(RemovalPreview):
    review_sha256: Hash


class CafConnectionRemoval:
    def __init__(self, source):
        self.archive = source if isinstance(source, CafArchive) else CafArchive(source)
        self.graph = CafGraph(self.archive)
        # Share parser-owned lexical boundaries, not creation/allocation admission.
        self.lexical = CafConstantCopies(self.archive)

    @staticmethod
    def _space(text):
        if text and text.strip(" \t\r\n"):
            raise ValueError("Unknown mixed text prevents CAF connection removal.")

    def _collection(self, props, pid, kind):
        collection = _collection(props, pid, kind)
        prop, data = props[pid], props[pid][0]
        if prop.attrib != {"id": pid} or data.attrib or collection.attrib:
            raise ValueError("Unknown connection property metadata prevents CAF removal.")
        for element in (prop, data, collection):
            self.lexical._outer(element)
            self._space(element.text)
            for child in element:
                self._space(child.tail)
        return collection

    def _row(self, element, types):
        _record(element, types)
        if element.attrib:
            raise ValueError("Unknown selected connection row metadata prevents CAF removal.")
        raw = self.lexical._raw(element)
        if b"<!" in raw or b"<?" in raw:
            raise ValueError("Selected connection row contains unsupported opaque markup.")
        self._space(element.text)
        for wrapper in element:
            self.lexical._outer(wrapper)
            self._space(wrapper.text)
            self._space(wrapper.tail)
            leaf = wrapper[0]
            self.lexical._outer(leaf)
            self._space(leaf.tail)
            self.archive._scalar_span(leaf)
        return raw

    def _selection(self, diagram_ref, wire_index):
        a = self.archive
        options = RemovalSource(
            source_sha256=a.hash, diagram_ref=diagram_ref, wire_index=wire_index
        )
        if not a._patchable_xml:
            raise ValueError("CAF connection removal requires observed UTF-8/ASCII XML.")
        graph = self.graph.diagram(options.diagram_ref)
        if not graph["observed_version"]:
            raise ValueError("CAF connection removal requires observed diagram version 1.0.")
        count = len(graph["connections"])
        if not 1 <= count <= 65535 or options.wire_index >= count:
            raise ValueError("Select one actual existing CAF connection occurrence.")
        obj = a.objects[options.diagram_ref]
        props = _properties(obj)
        connected = self._collection(props, "3118", "array")
        continuations = self._collection(props, "3384", "listof")
        row, continuation = connected[options.wire_index], continuations[options.wire_index]
        row_raw = self._row(row, ("unsignedShort",) * 4)
        continuation_raw = self._row(continuation, ("boolean", "string"))
        wire = graph["connections"][options.wire_index]
        Continuation.model_validate(wire["continuation"])
        for ref in (wire["source_ref"], wire["target_ref"]):
            if len(ref) > 512:
                raise ValueError("CAF connection references exceed this source-copy profile.")
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source_sha256": a.hash,
            "source_xml_sha256": sha(a.xml),
            "diagram_ref": options.diagram_ref,
            "diagram_class_id": graph["class_id"],
            "diagram_class_version": graph["class_version"],
            "diagram_sha256": sha(self.lexical._raw(obj)),
            "connection_property_sha256": sha(self.lexical._raw(props["3118"])),
            "continuation_property_sha256": sha(self.lexical._raw(props["3384"])),
            "wire_index": options.wire_index,
            "connection_count": count,
            "old": wire["raw"],
            "source_ref": wire["source_ref"],
            "source_port": wire["source_port"],
            "target_ref": wire["target_ref"],
            "target_port": wire["target_port"],
            "continuation": wire["continuation"],
            "connection_record_sha256": sha(row_raw),
            "continuation_record_sha256": sha(continuation_raw),
            "target_remaining_writer_count": sum(
                other["index"] != options.wire_index
                and other["target_ref"] == wire["target_ref"]
                and other["target_port"] == wire["target_port"]
                for other in graph["connections"]
            ),
            **FLAGS,
        }
        return {**body, "selection_sha256": seal(body)}, graph, (row, continuation)

    def inspect(self, diagram_ref, wire_index):
        return self._selection(diagram_ref, wire_index)[0]

    def compile(self, **request):
        options = RemovalPreview.model_validate(request)
        selected, graph, rows = self._selection(options.diagram_ref, options.wire_index)
        if any(selected[key] != value for key, value in options.model_dump().items()):
            raise ValueError(
                "CAF connection removal source or occurrence changed; inspect it again."
            )
        spans = sorted(self.lexical._outer(row) for row in rows)
        if spans[0][1] > spans[1][0]:
            raise ValueError("CAF connection removal row boundaries overlap.")
        a = self.archive
        xml = a.xml
        for start, end in reversed(spans):
            xml = xml[:start] + xml[end:]
        output = a._copy_xml(xml)
        readback = CafArchive(output)
        after = CafGraph(readback).diagram(options.diagram_ref)
        expected = copy.deepcopy(graph)
        del expected["connections"][options.wire_index]
        for index, wire in enumerate(expected["connections"]):
            wire["index"] = index
        # These labels are derived from the remaining wires, not native configuration.
        expected.pop("port_labels")
        actual = {key: value for key, value in after.items() if key != "port_labels"}
        if (
            readback.xml != xml
            or list(readback.objects) != list(a.objects)
            or actual != expected
            or readback.comment != a.comment
            or any(getattr(readback.info, key) != getattr(a.info, key) for key in ZIP_METADATA)
        ):
            raise ValueError("CAF removal failed independent graph, identity or ZIP preservation.")
        verified = CafConstantCopies(readback)
        for ref, obj in a.objects.items():
            if ref != options.diagram_ref and self.lexical._raw(obj) != verified._raw(
                readback.objects[ref]
            ):
                raise ValueError("CAF connection removal changed an unrelated object.")
        old_props = _properties(a.objects[options.diagram_ref])
        new_props = _properties(readback.objects[options.diagram_ref])
        if set(old_props) != set(new_props) or any(
            self.lexical._raw(prop) != verified._raw(new_props[pid])
            for pid, prop in old_props.items()
            if pid not in ("3118", "3384")
        ):
            raise ValueError("CAF connection removal changed unrelated diagram configuration.")
        body = {
            "profile": "caf-connection-removal-result/1",
            "selection": selected,
            "output_sha256": sha(output),
            "output_xml_sha256": sha(xml),
            "removed_connection_count": 1,
            "remaining_connection_count": len(after["connections"]),
            "preserved": {
                "original_object_count": len(a.objects),
                "graph_blocks": True,
                "graph_execution_order": True,
                "graph_layout": True,
                "destination_configuration": True,
                "unrelated_xml_bytes": True,
                "zip_metadata": True,
            },
            **FLAGS,
        }
        return output, {**body, "removal_sha256": seal(body)}


def connection_removal_router(get_caf):
    router = APIRouter(prefix="/api/caf/{id}/connection-removal")

    def load(id, request):
        if id != request.source_sha256:
            raise ValueError("Select the exact original CAF source hash.")
        archive = get_caf(id)
        if archive.hash != id:
            raise ValueError("Opened CAF source does not match the selected hash.")
        return CafConnectionRemoval(archive)

    def preview(id, request):
        output, removal = load(id, request).compile(**request.model_dump())
        body = {
            "profile": "caf-connection-removal-review/1",
            "request": request.model_dump(),
            "removal": removal,
            **FLAGS,
        }
        return output, {**body, "review_sha256": seal(body)}

    @router.post("/source")
    def source(id: str, body: RemovalSource):
        return load(id, body).inspect(body.diagram_ref, body.wire_index)

    @router.post("/preview")
    def review(id: str, body: RemovalPreview):
        return preview(id, body)[1]

    @router.post("/export")
    def export(id: str, body: RemovalExport):
        request = RemovalPreview.model_validate(body.model_dump(exclude={"review_sha256"}))
        output, reviewed = preview(id, request)
        if reviewed["review_sha256"] != body.review_sha256:
            raise ValueError(
                "CAF connection removal review changed; review the current selection again."
            )
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="caf-connection-removal.caf"',
                "X-Studio-Artifact-Sha256": sha(output),
                "X-Studio-Review-Sha256": reviewed["review_sha256"],
                "X-Studio-Source-Sha256": body.source_sha256,
                "X-Studio-Removal-Sha256": reviewed["removal"]["removal_sha256"],
                "X-Studio-Request-Sha256": seal(request.model_dump()),
            },
        )

    return router
