"""Immutable local saved-effective connection compilation; no controller queries."""

from fastapi import APIRouter
from fastapi.responses import Response

from .moi_connection_copies import PROFILE as EDIT_PROFILE
from .moi_effective_connection import PROFILE, SCOPE, compiler_from_snapshot
from .moi_identity import seal, sha
from .native_connection_copies import ConnectionPreview, ConnectionSource, Hash


class EffectiveConnectionPreview(ConnectionPreview):
    effective_sha256: Hash
    effective_record_sha256: Hash


class EffectiveConnectionExport(EffectiveConnectionPreview):
    review_sha256: Hash


class EffectiveConnectionService:
    def __init__(self, records):
        self.records = records

    def load(self, request):
        options = ConnectionSource.model_validate(request)
        snapshot, files, _ = self.records.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        if options.source_sha256 != sha(files[3]):
            raise ValueError("The original native connection archive changed; inspect it again.")
        compiler = compiler_from_snapshot(snapshot, files)
        record = compiler.archive.wire.reader.records.get(options.diagram_ref)
        if record is None or record["sha256"] != options.record_sha256:
            raise ValueError("The original native connection diagram changed; inspect it again.")
        return (
            options,
            compiler,
            {
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
            },
        )

    def source(self, request):
        options, compiler, envelope = self.load(request)
        return {
            **envelope,
            "selection": compiler.effective.inspect(
                options.diagram_ref, options.prototype_index, options.source_ref
            ),
        }

    def preview(self, request):
        options = EffectiveConnectionPreview.model_validate(request)
        _, compiler, envelope = self.load(
            options.model_dump(include=set(ConnectionSource.model_fields))
        )
        output, compilation = compiler.compile(
            **options.model_dump(
                exclude={"capture_id", "snapshot_sha256", "source_sha256", "record_sha256"}
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
        options = EffectiveConnectionExport.model_validate(request)
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if options.review_sha256 != review["review_sha256"]:
            raise ValueError("The saved-effective connection review changed; review it again.")
        return output, review


def effective_connection_router(service):
    router = APIRouter(
        prefix="/api/bacnet/controller/native-application/inspection/effective-connection-copy"
    )

    @router.post("/source")
    def source(body: ConnectionSource):
        return service.source(body.model_dump())

    @router.post("/preview")
    def preview(body: EffectiveConnectionPreview):
        return service.preview(body.model_dump())[1]

    @router.post("/export")
    def export(body: EffectiveConnectionExport):
        output, review = service.export(body.model_dump())
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="native-effective-connection.moi"',
                "X-Studio-Artifact-Sha256": sha(output),
                "X-Studio-Review-Sha256": review["review_sha256"],
                "X-Studio-Snapshot-Sha256": review["snapshot_sha256"],
                "X-Studio-Source-Sha256": review["source_sha256"],
                "X-Studio-Compilation-Sha256": review["compilation"]["compilation_sha256"],
            },
        )

    return router
