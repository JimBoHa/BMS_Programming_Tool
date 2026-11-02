"""Source-bound, local effective Enum compilation without field authority."""

from fastapi import APIRouter, Response

from .moi_effective_enum import PROFILE, SCOPE, compiler_from_snapshot
from .moi_identity import seal
from .native_backup_records import BackupInspectionSource
from .native_enum_copies import EnumCopyExport, EnumCopyPreview


class EffectiveEnumService:
    def __init__(self, archives):
        self.archives = archives

    def load(self, request):
        options = BackupInspectionSource.model_validate(request)
        snapshot, files, _ = self.archives.load(options.model_dump())
        return snapshot, compiler_from_snapshot(snapshot, files)

    @staticmethod
    def envelope(snapshot, compiler):
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "capture_id": snapshot["id"],
            "device": snapshot["device"],
            "identity": snapshot["identity"],
            "snapshot_sha256": snapshot["evidence_sha256"],
            "source_sha256": compiler.archive.editor.source_sha256,
            "effective_sha256": compiler.effective.editor.source_sha256,
            "target": {**snapshot["target"], "device": snapshot["device"]},
            "captured_at": snapshot["captured_at"],
            "files": compiler.files,
            "parameter_merge": compiler.parameters,
            "source_identity_matches": snapshot.get("source_identity_matches", False),
            "source_identity_error": snapshot.get("source_identity_error"),
            "source_immutable": True,
            "saved_settings_merged": True,
            "enum_semantics_verified": False,
            "current_identity_verified": False,
            "controller_queries": False,
            "controller_write": False,
            "field_transfer_enabled": False,
        }

    def source(self, request):
        snapshot, compiler = self.load(request)
        return {
            **self.envelope(snapshot, compiler),
            "fields": compiler.fields(),
        }

    def preview(self, request):
        options = EnumCopyPreview.model_validate(request)
        snapshot, compiler = self.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        if options.source_sha256 != compiler.archive.editor.source_sha256:
            raise ValueError("Original archive changed; reopen its effective Enum source.")
        output, compilation = compiler.compile(
            **options.model_dump(include={"record_ref", "encoded_sha256", "value"})
        )
        body = {
            **self.envelope(snapshot, compiler),
            "request": options.model_dump(),
            "compilation": compilation,
            "archive_value": compiler.archive.candidates[options.record_ref][1]["scalar"]["value"],
            "edit": compilation["selected_edit"],
            "output_sha256": compilation["compiled_sha256"],
        }
        return output, {**body, "review_sha256": seal(body)}

    def export(self, request):
        options = EnumCopyExport.model_validate(request)
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if options.review_sha256 != review["review_sha256"]:
            raise ValueError("Effective Enum compilation review changed; review it again.")
        return output, review


def native_enum_compiler_router(archives):
    service = EffectiveEnumService(archives)
    router = APIRouter(prefix="/api/bacnet/controller/native-application/enum-default-compiler")

    @router.post("/source")
    def source(body: BackupInspectionSource):
        return service.source(body.model_dump())

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
                "Content-Disposition": 'attachment; filename="native-effective-enum-default.moi"',
                "X-Studio-Artifact-Sha256": review["output_sha256"],
                "X-Studio-Review-Sha256": review["review_sha256"],
                "X-Studio-Snapshot-Sha256": body.snapshot_sha256,
            },
        )

    return router
