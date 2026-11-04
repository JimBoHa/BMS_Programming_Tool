"""Source-bound offline review/export of recorded constant creation."""

from typing import Annotated

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .caf_constant_copy import CafConstantCopies
from .moi_identity import seal, sha

Reference = Annotated[str, Field(strict=True, min_length=1, max_length=512)]
Hash = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]


class ConstantSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_sha256: Hash
    diagram_ref: Reference
    prototype_ref: Reference


class ConstantPreview(ConstantSource):
    selection_sha256: Hash
    x: str = Field(strict=True, max_length=80)
    y: str = Field(strict=True, max_length=80)


class ConstantExport(ConstantPreview):
    review_sha256: Hash


def constant_router(
    get_caf, *, compiler=CafConstantCopies, suffix="constant-copy", artifact_suffix=None
):
    router = APIRouter(prefix="/api/caf/{id}/" + suffix)

    def load(id, request):
        archive = get_caf(id)
        if archive.hash != request.source_sha256:
            raise ValueError("CAF creation source changed; open the intended original file.")
        return compiler(archive)

    def preview(id, request):
        source = load(id, request)
        output, creation = source.compile(**request.model_dump(exclude={"source_sha256"}))
        body = {
            "request": request.model_dump(),
            "creation": creation,
            "controller_write": False,
            "field_transfer_enabled": False,
        }
        return output, {**body, "review_sha256": seal(body)}

    @router.post("/source")
    def source(id: str, body: ConstantSource):
        return load(id, body).inspect(body.diagram_ref, body.prototype_ref)

    @router.post("/preview")
    def review(id: str, body: ConstantPreview):
        return preview(id, body)[1]

    @router.post("/export")
    def export(id: str, body: ConstantExport):
        request = ConstantPreview.model_validate(body.model_dump(exclude={"review_sha256"}))
        output, reviewed = preview(id, request)
        if reviewed["review_sha256"] != body.review_sha256:
            raise ValueError("CAF creation review changed; review the current proposal again.")
        filename_suffix = (
            artifact_suffix(reviewed["creation"]["selection"]) if artifact_suffix else suffix
        )
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="caf-{filename_suffix}.caf"',
                "X-Studio-Artifact-Sha256": sha(output),
                "X-Studio-Review-Sha256": reviewed["review_sha256"],
                "X-Studio-Source-Sha256": body.source_sha256,
                "X-Studio-Creation-Sha256": reviewed["creation"]["creation_sha256"],
            },
        )

    return router
