"""Source-bound effective wire compilation; no controller queries or transfer."""

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field

from .moi_effective_wire import PROFILE, SCOPE, compiler_from_snapshot
from .moi_identity import seal, sha
from .moi_wire_sources import PROFILE as EDIT_PROFILE
from .native_wire_copies import WireCopyPreview, WireSourceRequest


class EffectiveWirePreview(WireCopyPreview):
    effective_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EffectiveWireExport(EffectiveWirePreview):
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EffectiveWireService:
    def __init__(self, records):
        self.records = records

    def load(self, request):
        options = WireSourceRequest.model_validate(request)
        snapshot, files, _ = self.records.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        compiler = compiler_from_snapshot(snapshot, files)
        if options.source_sha256 != compiler.archive.editor.source_sha256:
            raise ValueError("The original native archive changed; inspect it again.")
        record = compiler.archive.reader.records.get(options.diagram_ref)
        if record is None or record["sha256"] != options.record_sha256:
            raise ValueError("The original native diagram changed; inspect it again.")
        envelope = {
            **self.records.envelope(snapshot, files),
            "profile": PROFILE,
            "compiler_profile": EDIT_PROFILE,
            "scope": SCOPE,
            "source_sha256": sha(files[3]),
            "archive_record_sha256": options.record_sha256,
            "effective_sha256": compiler.effective.editor.source_sha256,
            "source_immutable": True,
            "current_identity_verified": False,
            "parameter_merge": compiler.parameters,
            "saved_settings_merged": True,
            "field_transfer_enabled": False,
            "controller_write": False,
            "can_apply": False,
        }
        return options, compiler, envelope

    def source(self, request):
        options, compiler, envelope = self.load(request)
        return {
            **envelope,
            "selection": compiler.effective.inspect(options.diagram_ref, options.wire_index),
            "archive_wire": compiler.archive.inspect(options.diagram_ref, options.wire_index)[
                "selected_wire"
            ],
        }

    def preview(self, request):
        options = EffectiveWirePreview.model_validate(request)
        _, compiler, envelope = self.load(
            options.model_dump(include=set(WireSourceRequest.model_fields))
        )
        output, compilation = compiler.compile(
            **options.model_dump(
                include={
                    "effective_sha256",
                    "effective_record_sha256",
                    "diagram_ref",
                    "property_sha256",
                    "wire_index",
                    "old",
                    "source_ref",
                }
            )
        )
        body = {
            **envelope,
            "request": options.model_dump(),
            "compilation": compilation,
            "output_sha256": sha(output),
        }
        return output, {**body, "review_sha256": seal(body)}

    def export(self, request):
        options = EffectiveWireExport.model_validate(request)
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if review["review_sha256"] != options.review_sha256:
            raise ValueError("Effective wire compilation review changed; review it again.")
        return output, review


def effective_wire_router(service):
    router = APIRouter(
        prefix="/api/bacnet/controller/native-application/inspection/effective-wire-source"
    )

    @router.post("/source")
    def source(body: WireSourceRequest):
        return service.source(body.model_dump())

    @router.post("/preview")
    def preview(body: EffectiveWirePreview):
        return service.preview(body.model_dump())[1]

    @router.post("/export")
    def export(body: EffectiveWireExport):
        output, review = service.export(body.model_dump())
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="native-effective-wire-source.moi"',
                "X-Studio-Artifact-Sha256": sha(output),
                "X-Studio-Review-Sha256": review["review_sha256"],
                "X-Studio-Snapshot-Sha256": review["snapshot_sha256"],
            },
        )

    return router
