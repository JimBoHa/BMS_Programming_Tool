"""Local combined native default/connection review and exact artifact export."""

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field

from .moi_default_wire import PROFILE, SCOPE, EffectiveDefaultWireCompiler
from .moi_identity import seal, sha
from .native_backup_records import BackupInspectionSource
from .native_wire_compiler import EffectiveWirePreview
from .native_wire_copies import WireSourceRequest


class CombinedSelection(WireSourceRequest):
    effective_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CombinedPreview(EffectiveWirePreview):
    record_ref: str = Field(min_length=1, max_length=512, strict=True)
    encoded_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    value_text: str = Field(min_length=1, max_length=128, strict=True)


class CombinedExport(CombinedPreview):
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class NativeDefaultWire:
    def __init__(self, records):
        self.records = records

    def load(self, options):
        snapshot, files = self.records.load_files(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        compiler = EffectiveDefaultWireCompiler(files, snapshot=snapshot)
        envelope = {
            **self.records.envelope(snapshot, files),
            "profile": PROFILE,
            "scope": SCOPE,
            "source_sha256": sha(files[3]),
            "effective_sha256": sha(compiler.merged),
            "parameter_merge": compiler.parameters,
            "source_immutable": True,
            "saved_settings_merged": True,
            "current_identity_verified": False,
            "controller_queries": False,
            "controller_write": False,
            "field_transfer_enabled": False,
            "can_apply": False,
        }
        return compiler, envelope

    def source(self, request):
        options = BackupInspectionSource.model_validate(request)
        compiler, envelope = self.load(options)
        return {**envelope, "fields": compiler.signal.fields(), "diagrams": compiler.diagrams()}

    def selection(self, request):
        options = CombinedSelection.model_validate(request)
        compiler, envelope = self.load(options)
        selection = compiler.selection(
            **options.model_dump(exclude={"capture_id", "snapshot_sha256"})
        )
        return {**envelope, "request": options.model_dump(), "selection": selection}

    def preview(self, request):
        options = CombinedPreview.model_validate(request)
        compiler, envelope = self.load(options)
        compiler.selection(
            **options.model_dump(
                include=set(CombinedSelection.model_fields) - {"capture_id", "snapshot_sha256"}
            )
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
        options = CombinedExport.model_validate(request)
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if options.review_sha256 != review["review_sha256"]:
            raise ValueError("The combined native review changed; review both edits again.")
        return output, review


def default_wire_router(service):
    router = APIRouter(prefix="/api/bacnet/controller/native-application/inspection/default-wire")

    @router.post("/source")
    def source(body: BackupInspectionSource):
        return service.source(body.model_dump())

    @router.post("/selection")
    def selection(body: CombinedSelection):
        return service.selection(body.model_dump())

    @router.post("/preview")
    def preview(body: CombinedPreview):
        return service.preview(body.model_dump())[1]

    @router.post("/export")
    def export(body: CombinedExport):
        output, review = service.export(body.model_dump())
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="native-default-wire.moi"',
                "X-Studio-Artifact-Sha256": sha(output),
                "X-Studio-Review-Sha256": review["review_sha256"],
                "X-Studio-Snapshot-Sha256": review["snapshot_sha256"],
            },
        )

    return router
