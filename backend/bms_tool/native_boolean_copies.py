"""Source-bound archive copies only; no native transfer service or journal."""

from pydantic import Field

from .moi_boolean_defaults import SCOPE, MoiBooleanDefaults
from .moi_identity import seal, sha
from .native_backup_records import BackupInspectionSource

PROFILE = "native-backup-boolean-default-copy/1"


class BooleanCopyPreview(BackupInspectionSource):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_ref: str = Field(min_length=1, max_length=512, strict=True)
    encoded_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    value: bool = Field(strict=True)


class BooleanCopyExport(BooleanCopyPreview):
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class NativeBooleanCopies:
    def __init__(self, archives):
        self.archives = archives

    def preview(self, request):
        options = BooleanCopyPreview.model_validate(request)
        snapshot, files, _ = self.archives.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        editor = MoiBooleanDefaults(files[3])
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
        }
        return output, {**body, "review_sha256": seal(body)}

    def export(self, request):
        options = BooleanCopyExport.model_validate(request)
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if options.review_sha256 != review["review_sha256"]:
            raise ValueError("The Boolean archive-copy review changed; review it again.")
        return output, review
