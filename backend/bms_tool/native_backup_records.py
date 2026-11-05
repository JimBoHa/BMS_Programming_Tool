"""Local inspection of retained native archive bytes, independent of compilation."""

from typing import Literal

from pydantic import Field

from .models import StrictModel
from .moi_application import MoiApplication
from .moi_identity import sha
from .native_backup_capabilities import backup_capabilities
from .native_binary_terminal_capabilities import PROFILE as BINARY_TERMINAL_CAPABILITIES_PROFILE
from .native_binary_terminal_capabilities import binary_terminal_capabilities
from .native_removal_capabilities import PROFILE as REMOVAL_CAPABILITIES_PROFILE
from .native_removal_capabilities import removal_capabilities
from .native_terminal_capabilities import PROFILE as TERMINAL_CAPABILITIES_PROFILE
from .native_terminal_capabilities import terminal_capabilities
from .native_terminal_label_capabilities import PROFILE as TERMINAL_LABEL_CAPABILITIES_PROFILE
from .native_terminal_label_capabilities import terminal_label_capabilities

PROFILE = "native-backup-record-inspection/1"
SCOPE = (
    "Inspect original retained native File 3 archive records. Values are historical archive "
    "properties, not saved-setting-merged values or current live measurements. No controller "
    "query, backup-state command, compilation intent or write is performed."
)


class BackupInspectionSource(StrictModel):
    capture_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BackupRecordsRequest(BackupInspectionSource):
    query: str = Field(default="", max_length=256, strict=True)
    offset: int = Field(default=0, ge=0, le=100000, strict=True)
    limit: int = Field(default=64, ge=1, le=128, strict=True)


class BackupCapabilitiesRequest(BackupInspectionSource):
    capability_profile: Literal[
        "native-backup-operation-capabilities/11",
        "native-backup-operation-capabilities/12",
        "native-backup-operation-capabilities/13",
        "native-backup-operation-capabilities/14",
        "native-backup-operation-capabilities/15",
        "native-backup-operation-capabilities/16",
        "native-backup-operation-capabilities/17",
    ] = "native-backup-operation-capabilities/12"


class BackupRecordRequest(BackupRecordsRequest):
    record_id: str = Field(pattern=r"^record:[0-9]{1,8}$")


class NativeBackupRecords:
    def __init__(self, storage):
        self.storage = storage

    def load_files(self, request):
        options = BackupInspectionSource.model_validate(request)
        if (self.storage.directory / options.capture_id).is_symlink():
            raise ValueError("Inspect native backups in their original storage folder.")
        try:
            snapshot, files = self.storage.load(options.capture_id)
        except OSError as exc:
            raise ValueError("The retained native backup is unavailable.") from exc
        if snapshot["evidence_sha256"] != options.snapshot_sha256:
            raise ValueError("Native backup evidence changed; select its current source again.")
        return snapshot, files

    def load(self, request):
        snapshot, files = self.load_files(request)
        # Readability does not require a recognized saved directory or matching
        # Device root. Keep such acquisition errors visible without inventing a
        # replacement source or granting an operation to the compiler.
        application = MoiApplication(files[3])
        return snapshot, files, application

    @staticmethod
    def envelope(snapshot, files):
        return {
            "profile": PROFILE,
            "source_kind": "native-backup-archive",
            "capture_id": snapshot["id"],
            "snapshot_sha256": snapshot["evidence_sha256"],
            "sha256": sha(files[3]),
            "target": {**snapshot["target"], "device": snapshot["device"]},
            "captured_at": snapshot["captured_at"],
            "identity": snapshot["identity"],
            "source_identity_matches": snapshot.get("source_identity_matches", False),
            "source_identity_error": snapshot.get("source_identity_error"),
            "files": snapshot["files"],
            "scope": SCOPE,
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "identity_verified": False,
        }

    def source(self, request):
        snapshot, files, application = self.load(request)
        return {**self.envelope(snapshot, files), "application": application.summary()}

    def capabilities(self, request):
        options = BackupCapabilitiesRequest.model_validate(request)
        snapshot, files, application = self.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        analyzer = (
            binary_terminal_capabilities
            if options.capability_profile == BINARY_TERMINAL_CAPABILITIES_PROFILE
            else terminal_label_capabilities
            if options.capability_profile == TERMINAL_LABEL_CAPABILITIES_PROFILE
            else terminal_capabilities
            if options.capability_profile == TERMINAL_CAPABILITIES_PROFILE
            else removal_capabilities
            if options.capability_profile == REMOVAL_CAPABILITIES_PROFILE
            else backup_capabilities
        )
        return {
            **self.envelope(snapshot, files),
            **analyzer(
                snapshot,
                files,
                application.summary(),
                capability_profile=options.capability_profile,
            ),
        }

    def records(self, request, *, detail=False):
        model = BackupRecordRequest if detail else BackupRecordsRequest
        options = model.model_validate(request)
        source = options.model_dump(include={"capture_id", "snapshot_sha256"})
        snapshot, files, application = self.load(source)
        paging = options.model_dump(include={"query", "offset", "limit"})
        result = (
            application.record_details(options.record_id, **paging)
            if detail
            else application.record_inventory(**paging)
        )
        return {**result, **self.envelope(snapshot, files)}
