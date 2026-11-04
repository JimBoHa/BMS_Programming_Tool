"""Strict offline API for prototype-qualified immutable native connection copies."""

from typing import Annotated

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field

from .moi_connection_copies import PROFILE as COMPILER_PROFILE
from .moi_connection_copies import SCOPE, MoiConnectionCopies
from .moi_identity import seal, sha
from .native_backup_records import BackupInspectionSource

PROFILE = "native-archive-connection-copy/1"
UInt = Annotated[int, Field(strict=True, ge=0, le=65535)]
Hash = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
Reference = Annotated[str, Field(strict=True, min_length=1, max_length=512)]


class ConnectionSource(BackupInspectionSource):
    source_sha256: Hash
    diagram_ref: Reference
    record_sha256: Hash
    prototype_index: int = Field(default=0, ge=0, le=4095, strict=True)
    source_ref: Reference | None = None


class ConnectionPreview(ConnectionSource):
    source_ref: Reference
    target_ref: Reference
    property_sha256: Hash
    metadata_property_sha256: Hash | None
    prototype_old: list[UInt] = Field(min_length=4, max_length=4)
    connection_count: int = Field(ge=0, le=4095, strict=True)


class ConnectionExport(ConnectionPreview):
    review_sha256: Hash


class NativeConnectionCopies:
    def __init__(self, records):
        self.records = records

    def load(self, options):
        snapshot, files, _ = self.records.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        if options.source_sha256 != sha(files[3]):
            raise ValueError("The original native connection source changed; inspect it again.")
        compiler = MoiConnectionCopies(files[3])
        record = compiler.wire.reader.records.get(options.diagram_ref)
        if record is None or record["sha256"] != options.record_sha256:
            raise ValueError("The native diagram record changed; inspect its current source.")
        return compiler, {
            **self.records.envelope(snapshot, files),
            "profile": PROFILE,
            "compiler_profile": COMPILER_PROFILE,
            "scope": SCOPE,
            "source_sha256": sha(files[3]),
            "saved_settings_merged": False,
            "field_transfer_enabled": False,
            "can_apply": False,
        }

    def source(self, request):
        options = ConnectionSource.model_validate(request)
        compiler, envelope = self.load(options)
        return {
            **envelope,
            "selection": compiler.inspect(
                options.diagram_ref, options.prototype_index, options.source_ref
            ),
        }

    def preview(self, request):
        options = ConnectionPreview.model_validate(request)
        compiler, envelope = self.load(options)
        output, compilation = compiler.compile(
            **options.model_dump(exclude={"capture_id", "snapshot_sha256"})
        )
        body = {
            **envelope,
            "request": options.model_dump(),
            "compilation": compilation,
            "output_sha256": sha(output),
            "controller_write": False,
        }
        return output, {**body, "review_sha256": seal(body)}

    def export(self, request):
        options = ConnectionExport.model_validate(request)
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if review["review_sha256"] != options.review_sha256:
            raise ValueError("The native connection review changed; review the current proposal.")
        return output, review


def native_connection_router(service):
    router = APIRouter(
        prefix="/api/bacnet/controller/native-application/inspection/connection-copy"
    )

    @router.post("/source")
    def source(body: ConnectionSource):
        return service.source(body.model_dump())

    @router.post("/preview")
    def preview(body: ConnectionPreview):
        return service.preview(body.model_dump())[1]

    @router.post("/export")
    def export(body: ConnectionExport):
        output, review = service.export(body.model_dump())
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="native-connection-copy.moi"',
                "X-Studio-Artifact-Sha256": sha(output),
                "X-Studio-Review-Sha256": review["review_sha256"],
                "X-Studio-Snapshot-Sha256": review["snapshot_sha256"],
                "X-Studio-Source-Sha256": review["source_sha256"],
                "X-Studio-Compilation-Sha256": review["compilation"]["compilation_sha256"],
            },
        )

    return router
