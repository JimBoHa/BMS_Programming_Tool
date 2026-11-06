"""Atomic local CAF scalar + single-wiring copies, using existing native encoders."""

import copy
import html
import json
from typing import Annotated, Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field

from .caf import CafArchive
from .caf_connection_removal import FLAGS, ZIP_METADATA
from .caf_constant_copy import CafConstantCopies
from .caf_graph import CafGraph, _collection, _properties, _record
from .caf_scalar_drafts import ProposalSet, source_fields
from .models import StrictModel
from .moi_identity import seal, sha

Hash = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
Reference = Annotated[str, Field(strict=True, min_length=1, max_length=512)]
UInt = Annotated[int, Field(strict=True, ge=0, le=65535)]
SCOPE = "Local scalar edits plus one rewire or connection addition. Native execution, CCT/PCT acceptance and controller transfer remain unverified."


class Rewire(StrictModel):
    kind: Literal["rewire"]
    diagram_ref: Reference
    wire_index: UInt
    old: list[UInt] = Field(min_length=4, max_length=4)
    source_ref: Reference


class Connect(StrictModel):
    kind: Literal["connect"]
    diagram_ref: Reference
    prototype_diagram_ref: Reference
    prototype_wire_index: UInt
    prototype_old: list[UInt] = Field(min_length=4, max_length=4)
    source_ref: Reference
    target_ref: Reference
    old_connection_count: UInt


class CombinedSource(ProposalSet):
    source_sha256: Hash
    wiring: Annotated[Rewire | Connect, Field(discriminator="kind")]


class CombinedPreview(CombinedSource):
    selection_sha256: Hash


class CombinedExport(CombinedPreview):
    review_sha256: Hash


def _splice(xml, edits):
    ordered = sorted(edits, key=lambda row: (row[0], row[1]))
    if any(a[1] > b[0] or a[0] == b[0] for a, b in zip(ordered, ordered[1:], strict=False)):
        raise ValueError("Combined CAF mutation boundaries overlap.")
    for start, end, value in reversed(ordered):
        xml = xml[:start] + value + xml[end:]
    return xml


def _leaf_edit(archive, leaf, value):
    start, end, before, after = archive._scalar_span(leaf)
    encoding = "ascii" if archive.encoding in {"ascii", "us-ascii"} else "utf-8"
    escaped = html.escape(value, quote=False).replace("\r", "&#13;")
    return start, end, before + escaped.encode(encoding, "xmlcharrefreplace") + after


def _wire(archive, wiring):
    args = wiring.model_dump(exclude={"kind"})
    graph = CafGraph(archive)
    return (
        graph.rewire_sources([args]) if wiring.kind == "rewire" else graph.add_connections([args])
    )


class CafCombinedCopy:
    def __init__(self, source):
        self.archive = source if isinstance(source, CafArchive) else CafArchive(source)

    def _source(self, request):
        a = self.archive
        if request.source_sha256 != a.hash:
            raise ValueError("Combined CAF source differs from the opened original.")
        raw = request.model_dump(include={"source_sha256", "changes", "wiring"})
        if len(json.dumps(raw, ensure_ascii=False).encode()) > 1024 * 1024:
            raise ValueError("Combined CAF request exceeds the 1 MiB limit.")
        fields = source_fields(a, raw["changes"])
        wired, report = _wire(a, request.wiring)
        deltas = self._wiring_deltas(request.wiring)
        if CafArchive(wired).xml != _splice(a.xml, deltas):
            raise ValueError("Original wiring output exceeds its permitted parsed byte deltas.")
        body = {
            "profile": "caf-combined-copy-source/1",
            "scope": SCOPE,
            "source_sha256": a.hash,
            "source_xml_sha256": sha(a.xml),
            "request": raw,
            "request_sha256": seal({"profile": "caf-combined-copy-request/1", "request": raw}),
            "fields": fields,
            "wiring_report": report,
            **FLAGS,
        }
        return {**body, "selection_sha256": seal(body)}, wired, deltas

    def inspect(self, **request):
        return self._source(CombinedSource.model_validate(request))[0]

    def _wiring_deltas(self, wiring):
        a = self.archive
        graph = CafGraph(a).diagram(wiring.diagram_ref)
        props = _properties(a.objects[wiring.diagram_ref])
        lexical = CafConstantCopies(a)
        if wiring.kind == "rewire":
            wire = graph["connections"][wiring.wire_index]
            replacement = next(b for b in graph["blocks"] if b["ref"] == wiring.source_ref)
            if replacement["ref"] == wire["source_ref"]:
                return []
            rows = _collection(props, "3118", "array")
            row = rows[wiring.wire_index]
            _record(row, ("unsignedShort",) * 4)
            return [_leaf_edit(a, row[0][0], str(replacement["index"]))]
        prototype = CafGraph(a).diagram(wiring.prototype_diagram_ref)["connections"][
            wiring.prototype_wire_index
        ]
        by_ref = {b["ref"]: b for b in graph["blocks"]}
        values = [
            by_ref[wiring.source_ref]["index"],
            prototype["source_port"],
            by_ref[wiring.target_ref]["index"],
            prototype["target_port"],
        ]
        row = (
            b"<struct>"
            + b"".join(
                b"<structElement><unsignedShort>"
                + str(v).encode()
                + b"</unsignedShort></structElement>"
                for v in values
            )
            + b"</struct>"
        )
        continuation = b"<struct><structElement><boolean>0</boolean></structElement><structElement><string /></structElement></struct>"
        edits = []
        for pid, tag, added in [("3118", "array", row), ("3384", "listof", continuation)]:
            collection = _collection(props, pid, tag)
            start, end = lexical._outer(collection)
            _, _, empty, _ = lexical._header(collection)
            if empty:
                edits.append(
                    (start, end, b"<" + tag.encode() + b">" + added + b"</" + tag.encode() + b">")
                )
            else:
                closing = a._spans[id(collection)][1]
                edits.append((closing, closing, added))
        return edits

    def compile(self, **request):
        options = CombinedPreview.model_validate(request)
        selection, wired, wiring_deltas = self._source(options)
        if selection["selection_sha256"] != options.selection_sha256:
            raise ValueError("Combined CAF selection changed; review the original again.")
        a = self.archive
        changes = selection["request"]["changes"]
        scalar_bytes, scalar_report = a.patch(changes)
        scalar = CafArchive(scalar_bytes)
        scalar_edits, actual = [], []
        reported = {(r["ref"], r["property"]): r for r in scalar_report}
        for row in changes:
            original_prop = _properties(a.objects[row["ref"]])[row["property"]]
            final_prop = _properties(scalar.objects[row["ref"]])[row["property"]]
            before, after = a.scalar(original_prop), scalar.scalar(final_prop)
            emitted = reported.get((row["ref"], row["property"]))
            if before["type"] != after["type"] or before["attributes"] != after["attributes"]:
                raise ValueError("Combined scalar output changed native type or attributes.")
            if after["text"] != (emitted["value"] if emitted else before["text"]):
                raise ValueError("Combined scalar output disagrees with its admitted report.")
            if emitted:
                scalar_edits.append(_leaf_edit(a, original_prop[0][0], after["text"]))
            old_raw = CafConstantCopies(a)._raw(original_prop[0][0])
            new_raw = CafConstantCopies(scalar)._raw(final_prop[0][0])
            actual.append(
                {
                    **row,
                    "type": before["type"],
                    "exported_value": after["text"],
                    "changed": old_raw != new_raw,
                }
            )
        if scalar.xml != _splice(a.xml, scalar_edits):
            raise ValueError("Scalar output exceeds its permitted parsed byte deltas.")
        left_bytes, left_report = _wire(scalar, options.wiring)
        right_bytes, right_report = CafArchive(wired).patch(changes)
        left, right = CafArchive(left_bytes), CafArchive(right_bytes)
        expected_xml = _splice(a.xml, [*scalar_edits, *wiring_deltas])
        if left.xml != expected_xml or right.xml != expected_xml or right_report != scalar_report:
            raise ValueError("Combined CAF operation orders or independent byte deltas disagree.")
        # Existing reports describe their literal intermediate sources, not one common chain.
        base_report = selection["wiring_report"]
        semantics = {
            "diagram_ref",
            "wire_index",
            "old",
            "new",
            "prototype_diagram_ref",
            "prototype_wire_index",
            "prototype_old",
            "old_connection_count",
            "validation",
        }
        if [{k: v for k, v in r.items() if k in semantics} for r in left_report] != [
            {k: v for k, v in r.items() if k in semantics} for r in base_report
        ] or any(
            set(r) - semantics - {"source_sha256", "result_sha256"}
            for r in [*base_report, *left_report]
        ):
            raise ValueError("Combined CAF wiring semantics changed between operation orders.")
        for report, source_hash, output_hash in [
            (base_report, a.hash, sha(wired)),
            (left_report, scalar.hash, left.hash),
        ]:
            if any(
                r["source_sha256"] != source_hash or r["result_sha256"] != output_hash
                for r in report
            ):
                raise ValueError("Combined CAF intermediate wiring proof differs from its bytes.")
        expected_graph = copy.deepcopy(CafGraph(scalar).diagram(options.wiring.diagram_ref))
        expected_graph["connections"] = CafGraph(wired).diagram(options.wiring.diagram_ref)[
            "connections"
        ]
        after_graph = CafGraph(left).diagram(options.wiring.diagram_ref)
        if {k: v for k, v in expected_graph.items() if k != "port_labels"} != {
            k: v for k, v in after_graph.items() if k != "port_labels"
        }:
            raise ValueError(
                "Combined CAF final graph disagrees with the admitted scalar and wiring changes."
            )
        for verified in (scalar, CafArchive(wired), left, right):
            if (
                list(verified.objects) != list(a.objects)
                or verified.comment != a.comment
                or any(getattr(verified.info, key) != getattr(a.info, key) for key in ZIP_METADATA)
                or any(verified.objects[ref].attrib != obj.attrib for ref, obj in a.objects.items())
            ):
                raise ValueError("Combined CAF identity or ZIP metadata preservation failed.")
        unchanged = expected_xml == a.xml
        output = a.original if unchanged else left_bytes
        body = {
            "profile": "caf-combined-copy-result/1",
            "selection": selection,
            "output_sha256": sha(output),
            "output_xml_sha256": sha(expected_xml),
            "scalar_changes": actual,
            "actual_scalar_change_count": sum(r["changed"] for r in actual),
            "actual_wiring_change_count": len(base_report),
            "legacy_scalar_report": scalar_report,
            "orders": {
                "scalar_then_wiring": {
                    "intermediate_sha256": scalar.hash,
                    "output_sha256": left.hash,
                    "wiring_report": left_report,
                },
                "wiring_then_scalar": {
                    "intermediate_sha256": sha(wired),
                    "output_sha256": right.hash,
                    "scalar_report": right_report,
                },
            },
            "unchanged": unchanged,
            "independent_byte_deltas_verified": True,
            **FLAGS,
        }
        return output, {**body, "combined_sha256": seal(body)}


def combined_copy_router(get_caf):
    router = APIRouter(prefix="/api/caf/{id}/combined-copy")

    def load(id, body):
        if id != body.source_sha256:
            raise ValueError("Select the exact original CAF source hash.")
        return CafCombinedCopy(get_caf(id))

    @router.post("/source")
    def source(id: str, body: CombinedSource):
        return load(id, body).inspect(**body.model_dump())

    def review(id, body):
        output, result = load(id, body).compile(**body.model_dump())
        data = {
            "profile": "caf-combined-copy-review/1",
            "request": body.model_dump(),
            "result": result,
            **FLAGS,
        }
        return output, {**data, "review_sha256": seal(data)}

    @router.post("/preview")
    def preview(id: str, body: CombinedPreview):
        return review(id, body)[1]

    @router.post("/export")
    def export(id: str, body: CombinedExport):
        request = body.model_dump(exclude={"review_sha256"})
        output, data = review(id, CombinedPreview.model_validate(request))
        if body.review_sha256 != data["review_sha256"]:
            raise ValueError("Combined CAF review changed; review the complete copy again.")
        result = data["result"]
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "X-CAF-Source-SHA256": id,
                "X-CAF-Request-SHA256": result["selection"]["request_sha256"],
                "X-CAF-Selection-SHA256": request["selection_sha256"],
                "X-CAF-Review-SHA256": data["review_sha256"],
                "X-CAF-Combined-SHA256": result["combined_sha256"],
                "X-CAF-Output-SHA256": result["output_sha256"],
            },
        )

    return router
