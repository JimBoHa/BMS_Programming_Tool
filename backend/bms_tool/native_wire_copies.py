"""Immutable native-backup wire copies, independently of saved-setting schemas."""

from typing import Annotated

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field

from .moi_identity import seal, sha
from .moi_wire_sources import PROFILE as COMPILER_PROFILE
from .moi_wire_sources import SCOPE, MoiWireSources
from .native_backup_records import BackupInspectionSource

PROFILE = "native-archive-wire-source-copy/1"
UInt = Annotated[int, Field(strict=True, ge=0, le=65535)]


class WireSourceRequest(BackupInspectionSource):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagram_ref: str = Field(min_length=1, max_length=512, strict=True)
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    wire_index: int = Field(default=0, ge=0, le=4095, strict=True)


class WireCopyPreview(WireSourceRequest):
    property_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    old: list[UInt] = Field(min_length=4, max_length=4)
    source_ref: str = Field(min_length=1, max_length=512, strict=True)


class WireCopyExport(WireCopyPreview):
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class NativeWireCopies:
    def __init__(self, records):
        self.records = records

    def load(self, options):
        snapshot, files, _ = self.records.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        if options.source_sha256 != sha(files[3]):
            raise ValueError("The original native archive changed; inspect it again.")
        compiler = MoiWireSources(files[3])
        record = compiler.reader.records.get(options.diagram_ref)
        if record is None or record["sha256"] != options.record_sha256:
            raise ValueError("The recorded native diagram changed; inspect its current source.")
        envelope = {
            **self.records.envelope(snapshot, files),
            "profile": PROFILE,
            "compiler_profile": COMPILER_PROFILE,
            "scope": SCOPE,
            "source_sha256": sha(files[3]),
            "saved_settings_merged": False,
            "field_transfer_enabled": False,
            "can_apply": False,
        }
        return compiler, envelope

    def source(self, request):
        options = WireSourceRequest.model_validate(request)
        compiler, envelope = self.load(options)
        return {**envelope, "selection": compiler.inspect(options.diagram_ref, options.wire_index)}

    def preview(self, request):
        options = WireCopyPreview.model_validate(request)
        compiler, envelope = self.load(options)
        output, compilation = compiler.compile(
            **options.model_dump(
                include={
                    "source_sha256",
                    "diagram_ref",
                    "record_sha256",
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
            "controller_write": False,
        }
        return output, {**body, "review_sha256": seal(body)}

    def export(self, request):
        options = WireCopyExport.model_validate(request)
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if review["review_sha256"] != options.review_sha256:
            raise ValueError("The native wire copy review changed; review the current proposal.")
        return output, review


def native_wire_router(service):
    router = APIRouter(prefix="/api/bacnet/controller/native-application/inspection/wire-source")

    @router.post("/source")
    def source(body: WireSourceRequest):
        return service.source(body.model_dump())

    @router.post("/preview")
    def preview(body: WireCopyPreview):
        return service.preview(body.model_dump())[1]

    @router.post("/export")
    def export(body: WireCopyExport):
        output, review = service.export(body.model_dump())
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="native-wire-source-copy.moi"',
                "X-Studio-Artifact-Sha256": sha(output),
                "X-Studio-Review-Sha256": review["review_sha256"],
                "X-Studio-Snapshot-Sha256": review["snapshot_sha256"],
            },
        )

    return router
