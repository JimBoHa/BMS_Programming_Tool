"""Local execution-order copies with unchanged recorded wire phase relationships."""

import copy
import re
from typing import Annotated

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field

from .caf import CafArchive, Q
from .caf_connection_removal import ZIP_METADATA
from .caf_constant_copy import CafConstantCopies
from .caf_graph import CafGraph, _collection, _properties
from .models import StrictModel
from .moi_identity import seal, sha

PROFILE = "caf-execution-order-copy/1"
SCOPE = (
    "Local CAF copy reordering existing blocks while preserving every recorded wire's "
    "before/same/after execution relationship. All other XML bytes, objects, membership, "
    "connections, continuation and layout remain unchanged. Native execution, resources, "
    "CCT/PCT acceptance and controller transfer remain unverified."
)
FLAGS = {
    "controller_write": False,
    "field_transfer_enabled": False,
    "native_execution_verified": False,
    "vendor_acceptance_verified": False,
    "can_apply": False,
}
Hash = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
Index = Annotated[int, Field(strict=True, ge=0, le=511)]
Order = Annotated[list[Index], Field(min_length=1, max_length=512)]


class OrderSource(StrictModel):
    source_sha256: Hash
    diagram_ref: str = Field(strict=True, min_length=1, max_length=512)


class OrderPreview(OrderSource):
    selection_sha256: Hash
    diagram_sha256: Hash
    order_property_sha256: Hash
    original_order: Order
    proposed_order: Order


class OrderExport(OrderPreview):
    review_sha256: Hash


def relationship(order, source, target):
    ranks = {index: rank for rank, index in enumerate(order)}
    return "before" if ranks[source] < ranks[target] else "same" if source == target else "after"


class CafExecutionOrder:
    def __init__(self, source):
        self.archive = source if isinstance(source, CafArchive) else CafArchive(source)
        self.graph = CafGraph(self.archive)
        self.lexical = CafConstantCopies(self.archive)

    def _selection(self, diagram_ref):
        a = self.archive
        OrderSource(source_sha256=a.hash, diagram_ref=diagram_ref)
        if not a._patchable_xml:
            raise ValueError("Execution-order copies require observed UTF-8/ASCII XML.")
        graph = self.graph.diagram(diagram_ref)
        if not graph["observed_version"] or not 1 <= len(graph["blocks"]) <= 512:
            raise ValueError("Select an observed version1.0 diagram with 1–512 existing blocks.")
        if len(graph["connections"]) > 6000:
            raise ValueError("This execution-order profile supports at most 6,000 recorded wires.")
        props = _properties(a.objects[diagram_ref])
        if "3373" in props and a.scalar(props["3373"]) not in (
            {"type": "boolean", "text": "1", "attributes": {}},
            {"type": "boolean", "text": "true", "attributes": {}},
        ):
            raise ValueError("The diagram must already record its user-modified state.")
        ordered = _collection(props, "3117", "array")
        prop, data = props["3117"], props["3117"][0]
        if prop.attrib != {"id": "3117"} or data.attrib or ordered.attrib:
            raise ValueError("Unknown execution-order property metadata prevents editing.")
        for element in (prop, data, ordered):
            self.lexical._outer(element)
            if (element.text or "").strip(" \t\r\n") or any(
                (child.tail or "").strip(" \t\r\n") for child in element
            ):
                raise ValueError("Unknown execution-order mixed text prevents editing.")
        spans = []
        for index, leaf in zip(graph["execution_order"], ordered, strict=True):
            self.lexical._outer(leaf)
            start, end, before, after = a._scalar_span(leaf)
            raw = a.xml[start:end]
            match = re.fullmatch(rb"[ \t\r\n]*([0-9]{1,10})[ \t\r\n]*", raw)
            if leaf.tag != Q + "unsignedShort" or before or after or not match:
                raise ValueError("Unsupported execution-order numeric serialization.")
            if int(match[1]) != index:
                raise ValueError("Execution-order lexical and parsed indices disagree.")
            spans.append((start + match.start(1), start + match.end(1)))
        members = [{"index": b["index"], "ref": b["ref"]} for b in graph["blocks"]]
        if any(len(m["ref"]) > 512 for m in members):
            raise ValueError("Execution-order member references exceed this profile.")
        edges = [
            {
                "wire_index": w["index"],
                "source_index": w["raw"][0],
                "target_index": w["raw"][2],
                "relationship": relationship(graph["execution_order"], w["raw"][0], w["raw"][2]),
            }
            for w in graph["connections"]
        ]
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source_sha256": a.hash,
            "source_xml_sha256": sha(a.xml),
            "diagram_ref": diagram_ref,
            "diagram_class_id": graph["class_id"],
            "diagram_class_version": graph["class_version"],
            "diagram_sha256": sha(self.lexical._raw(a.objects[diagram_ref])),
            "order_property_sha256": sha(self.lexical._raw(prop)),
            "original_order": graph["execution_order"],
            "members": members,
            "edge_relationships": edges,
            **FLAGS,
        }
        return {**body, "selection_sha256": seal(body)}, graph, spans

    def inspect(self, diagram_ref):
        return self._selection(diagram_ref)[0]

    def compile(self, **request):
        options = OrderPreview.model_validate(request)
        selected, graph, spans = self._selection(options.diagram_ref)
        if any(
            selected[key] != value
            for key, value in options.model_dump(exclude={"proposed_order"}).items()
        ):
            raise ValueError("Execution-order source changed; inspect the exact diagram again.")
        proposed = options.proposed_order
        if sorted(proposed) != list(range(len(graph["blocks"]))):
            raise ValueError("The proposed order must contain every existing block exactly once.")
        for edge in selected["edge_relationships"]:
            if (
                relationship(proposed, edge["source_index"], edge["target_index"])
                != edge["relationship"]
            ):
                raise ValueError(
                    f"Wire {edge['wire_index']} would change its recorded execution relationship."
                )
        a = self.archive
        xml = a.xml
        changed = sum(x != y for x, y in zip(proposed, options.original_order, strict=True))
        for (start, end), old, new in reversed(
            list(zip(spans, options.original_order, proposed, strict=True))
        ):
            if old != new:
                xml = xml[:start] + str(new).encode("ascii") + xml[end:]
        output = a._copy_xml(xml) if changed else a.original
        readback = CafArchive(output)
        after = CafGraph(readback).diagram(options.diagram_ref)
        expected = copy.deepcopy(graph)
        expected["execution_order"] = proposed
        ranks = {index: rank for rank, index in enumerate(proposed)}
        for block in expected["blocks"]:
            block["execution_index"] = ranks[block["index"]]
        verified = CafConstantCopies(readback)
        old_props = _properties(a.objects[options.diagram_ref])
        new_props = _properties(readback.objects[options.diagram_ref])
        if (
            readback.xml != xml
            or after != expected
            or list(readback.objects) != list(a.objects)
            or readback.comment != a.comment
            or any(getattr(readback.info, k) != getattr(a.info, k) for k in ZIP_METADATA)
            or any(
                self.lexical._raw(obj) != verified._raw(readback.objects[ref])
                for ref, obj in a.objects.items()
                if ref != options.diagram_ref
            )
            or set(old_props) != set(new_props)
            or any(
                self.lexical._raw(prop) != verified._raw(new_props[pid])
                for pid, prop in old_props.items()
                if pid != "3117"
            )
        ):
            raise ValueError("Execution-order copy failed independent preservation/readback.")
        body = {
            "profile": "caf-execution-order-result/1",
            "selection": selected,
            "proposed_order": proposed,
            "changed_positions": changed,
            "output_sha256": sha(output),
            "output_xml_sha256": sha(xml),
            "preserved": {
                "original_object_count": len(a.objects),
                "membership_and_identities": True,
                "wire_relationships": True,
                "connections_and_continuation": True,
                "layout_and_configuration": True,
                "unrelated_xml_bytes": True,
                "zip_metadata": True,
            },
            **FLAGS,
        }
        return output, {**body, "order_sha256": seal(body)}


def execution_order_router(get_caf):
    router = APIRouter(prefix="/api/caf/{id}/execution-order")

    def load(id, request):
        if id != request.source_sha256:
            raise ValueError("Select the exact original CAF source hash.")
        archive = get_caf(id)
        if archive.hash != id:
            raise ValueError("Opened CAF source does not match the selected hash.")
        return CafExecutionOrder(archive)

    def preview(id, request):
        output, result = load(id, request).compile(**request.model_dump())
        body = {
            "profile": "caf-execution-order-review/1",
            "request": request.model_dump(),
            "result": result,
            **FLAGS,
        }
        return output, {**body, "review_sha256": seal(body)}

    @router.post("/source")
    def source(id: str, body: OrderSource):
        return load(id, body).inspect(body.diagram_ref)

    @router.post("/preview")
    def review(id: str, body: OrderPreview):
        return preview(id, body)[1]

    @router.post("/export")
    def export(id: str, body: OrderExport):
        request = OrderPreview.model_validate(body.model_dump(exclude={"review_sha256"}))
        output, reviewed = preview(id, request)
        if reviewed["review_sha256"] != body.review_sha256:
            raise ValueError("Execution-order review changed; review the proposal again.")
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="caf-execution-order.caf"',
                "X-Studio-Artifact-Sha256": sha(output),
                "X-Studio-Source-Sha256": id,
                "X-Studio-Review-Sha256": reviewed["review_sha256"],
                "X-Studio-Order-Sha256": reviewed["result"]["order_sha256"],
                "X-Studio-Request-Sha256": seal(request.model_dump()),
            },
        )

    return router
