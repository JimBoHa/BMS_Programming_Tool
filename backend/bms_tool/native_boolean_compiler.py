"""Source-bound local effective Boolean compiler service; no field actions."""

from .moi_effective_boolean import PROFILE, SCOPE, compiler_from_snapshot
from .moi_identity import seal
from .native_backup_records import BackupInspectionSource
from .native_boolean_copies import BooleanCopyExport, BooleanCopyPreview


class EffectiveBooleanService:
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
            "snapshot_sha256": snapshot["evidence_sha256"],
            "source_sha256": compiler.archive.editor.source_sha256,
            "effective_sha256": compiler.effective.editor.source_sha256,
            "target": {**snapshot["target"], "device": snapshot["device"]},
            "captured_at": snapshot["captured_at"],
            "files": compiler.files,
            "source_immutable": True,
            "saved_settings_merged": True,
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
            "parameter_merge": compiler.parameters,
        }

    def preview(self, request):
        options = BooleanCopyPreview.model_validate(request)
        snapshot, compiler = self.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        if options.source_sha256 != compiler.archive.editor.source_sha256:
            raise ValueError("Original archive changed; reopen its effective Boolean source.")
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
        options = BooleanCopyExport.model_validate(request)
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if options.review_sha256 != review["review_sha256"]:
            raise ValueError("Effective Boolean compilation review changed; review it again.")
        return output, review
