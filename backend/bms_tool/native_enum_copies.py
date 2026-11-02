"""Stateless, source-bound original Enum code copies; no transfer authority."""

from fastapi import APIRouter, Response
from pydantic import Field

from .moi_enum_defaults import SCOPE, MoiEnumDefaults
from .moi_identity import seal, sha
from .native_backup_records import BackupInspectionSource

PROFILE = "native-backup-enum-default-copy/1"


class EnumCopyPreview(BackupInspectionSource):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_ref: str = Field(strict=True, min_length=1, max_length=512)
    encoded_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    value: int = Field(strict=True, ge=0, le=4294967295)


class EnumCopyExport(EnumCopyPreview):
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class NativeEnumCopies:
    def __init__(self, archives):
        self.archives = archives

    def preview(self, request):
        options = EnumCopyPreview.model_validate(request)
        snapshot, files, _ = self.archives.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        editor = MoiEnumDefaults(files[3])
        fields = options.model_dump(
            include={"source_sha256", "record_ref", "encoded_sha256", "value"}
        )
        plan = editor.preview(**fields)
        output, edit = editor.export(**fields, plan_sha256=plan["plan_sha256"])
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "request": options.model_dump(),
            "target": {**snapshot["target"], "device": snapshot["device"]},
            "captured_at": snapshot["captured_at"],
            "source_identity_matches": snapshot.get("source_identity_matches", False),
            "source_identity_error": snapshot.get("source_identity_error"),
            "edit": edit,
            "output_sha256": sha(output),
            "source_immutable": True,
            "controller_queries": False,
            "controller_write": False,
            "field_transfer_enabled": False,
            "enum_semantics_verified": False,
        }
        return output, {**body, "review_sha256": seal(body)}

    def export(self, request):
        options = EnumCopyExport.model_validate(request)
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if options.review_sha256 != review["review_sha256"]:
            raise ValueError("The Enum archive-copy review changed; review it again.")
        return output, review


def native_enum_copy_router(archives):
    service = NativeEnumCopies(archives)
    router = APIRouter(prefix="/api/bacnet/controller/native-application/inspection/enum-default")

    @router.post("/preview")
    def preview(body: EnumCopyPreview):
        return service.preview(body.model_dump())[1]

    @router.post("/export")
    def export(body: EnumCopyExport):
        output, review = service.export(body.model_dump())
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="native-enum-default-copy.moi"',
                "X-Studio-Artifact-Sha256": review["output_sha256"],
                "X-Studio-Review-Sha256": review["review_sha256"],
                "X-Studio-Snapshot-Sha256": body.snapshot_sha256,
            },
        )

    return router
