"""Source-bound local review/export for several existing native typed defaults."""

from typing import Annotated, Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field, StrictBool, StrictInt

from .models import StrictModel
from .moi_default_batch import LIMIT, PROFILE, SCOPE, EffectiveDefaultBatchCompiler
from .moi_identity import seal, sha
from .native_backup_records import BackupInspectionSource


class DefaultChange(StrictModel):
    record_ref: str = Field(min_length=1, max_length=512, strict=True)
    encoded_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RealDefaultChange(DefaultChange):
    kind: Literal["real"]
    value_text: str = Field(min_length=1, max_length=128, strict=True)


class BooleanDefaultChange(DefaultChange):
    kind: Literal["boolean"]
    value: StrictBool


class EnumDefaultChange(DefaultChange):
    kind: Literal["enum"]
    value: StrictInt = Field(ge=0, le=4294967295)


Change = Annotated[
    RealDefaultChange | BooleanDefaultChange | EnumDefaultChange, Field(discriminator="kind")
]


class BatchPreview(BackupInspectionSource):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    changes: list[Change] = Field(min_length=1, max_length=LIMIT)


class BatchExport(BatchPreview):
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class NativeDefaultBatch:
    def __init__(self, records):
        self.records = records

    def load(self, options):
        snapshot, files = self.records.load_files(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        compiler = EffectiveDefaultBatchCompiler(files, snapshot=snapshot)
        envelope = {
            **self.records.envelope(snapshot, files),
            "profile": PROFILE,
            "scope": SCOPE,
            "source_sha256": sha(files[3]),
            "effective_sha256": sha(compiler.merged),
            "parameter_merge": compiler.parameters,
            "edit_limit": LIMIT,
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
        compiler, envelope = self.load(BackupInspectionSource.model_validate(request))
        return {**envelope, "fields": compiler.fields()}

    def preview(self, request):
        options = BatchPreview.model_validate(request)
        compiler, envelope = self.load(options)
        if (
            options.source_sha256 != envelope["source_sha256"]
            or options.effective_sha256 != envelope["effective_sha256"]
        ):
            raise ValueError("The original native source or saved merge changed; reopen it.")
        output, compilation = compiler.compile([change.model_dump() for change in options.changes])
        body = {
            **envelope,
            "request": options.model_dump(),
            "compilation": compilation,
            "output_sha256": sha(output),
        }
        return output, {**body, "review_sha256": seal(body)}

    def export(self, request):
        options = BatchExport.model_validate(request)
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if options.review_sha256 != review["review_sha256"]:
            raise ValueError("The native batch review changed; review the intended fields again.")
        return output, review


def default_batch_router(service):
    router = APIRouter(prefix="/api/bacnet/controller/native-application/inspection/default-batch")

    @router.post("/source")
    def source(body: BackupInspectionSource):
        return service.source(body.model_dump())

    @router.post("/preview")
    def preview(body: BatchPreview):
        return service.preview(body.model_dump())[1]

    @router.post("/export")
    def export(body: BatchExport):
        output, review = service.export(body.model_dump())
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="native-default-batch.moi"',
                "X-Studio-Artifact-Sha256": sha(output),
                "X-Studio-Review-Sha256": review["review_sha256"],
                "X-Studio-Snapshot-Sha256": review["snapshot_sha256"],
            },
        )

    return router
