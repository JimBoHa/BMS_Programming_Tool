"""Strict local archive and saved-effective native connection-removal copies."""

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field

from .moi_connection_removal import PROFILE as EDIT_PROFILE
from .moi_connection_removal import SCOPE as ARCHIVE_SCOPE
from .moi_connection_removal import MoiConnectionRemoval
from .moi_effective_connection_removal import PROFILE as EFFECTIVE_PROFILE
from .moi_effective_connection_removal import SCOPE as EFFECTIVE_SCOPE
from .moi_effective_connection_removal import compiler_from_snapshot
from .moi_identity import seal, sha
from .native_backup_records import BackupInspectionSource
from .native_connection_copies import Hash, Reference, UInt

PROFILE = "native-archive-connection-removal-copy/1"


class RemovalSource(BackupInspectionSource):
    source_sha256: Hash
    diagram_ref: Reference
    record_sha256: Hash
    wire_index: int = Field(default=0, strict=True, ge=0, le=4095)


class RemovalPreview(RemovalSource):
    property_sha256: Hash
    metadata_property_sha256: Hash | None
    old: list[UInt] = Field(min_length=4, max_length=4)
    connection_count: int = Field(strict=True, ge=1, le=4096)


class RemovalExport(RemovalPreview):
    review_sha256: Hash


class EffectiveRemovalPreview(RemovalPreview):
    effective_sha256: Hash
    effective_record_sha256: Hash


class EffectiveRemovalExport(EffectiveRemovalPreview):
    review_sha256: Hash


class NativeConnectionRemovals:
    def __init__(self, records):
        self.records = records

    def load(self, request):
        options = RemovalSource.model_validate(request)
        snapshot, files, _ = self.records.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        if options.source_sha256 != sha(files[3]):
            raise ValueError("The original native removal archive changed; inspect it again.")
        compiler = MoiConnectionRemoval(files[3])
        record = compiler.wire.reader.records.get(options.diagram_ref)
        if record is None or record["sha256"] != options.record_sha256:
            raise ValueError("The original native removal diagram changed; inspect it again.")
        return (
            options,
            compiler,
            {
                **self.records.envelope(snapshot, files),
                "profile": PROFILE,
                "compiler_profile": EDIT_PROFILE,
                "scope": ARCHIVE_SCOPE,
                "source_sha256": sha(files[3]),
                "source_immutable": True,
                "current_identity_verified": False,
                "saved_settings_merged": False,
                "field_transfer_enabled": False,
                "controller_write": False,
                "can_apply": False,
            },
        )

    def source(self, request):
        options, compiler, envelope = self.load(request)
        return {**envelope, "selection": compiler.inspect(options.diagram_ref, options.wire_index)}

    def preview(self, request):
        options = RemovalPreview.model_validate(request)
        _, compiler, envelope = self.load(
            options.model_dump(include=set(RemovalSource.model_fields))
        )
        output, compilation = compiler.compile(
            **options.model_dump(exclude={"capture_id", "snapshot_sha256"})
        )
        body = {
            **envelope,
            "request": options.model_dump(),
            "compilation": compilation,
            "output_sha256": sha(output),
        }
        return output, {**body, "review_sha256": seal(body)}

    def export(self, request):
        options = RemovalExport.model_validate(request)
        return self.checked_export(options)

    def checked_export(self, options):
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if options.review_sha256 != review["review_sha256"]:
            raise ValueError("The native connection removal review changed; review it again.")
        return output, review


class EffectiveConnectionRemovals(NativeConnectionRemovals):
    def load(self, request):
        options = RemovalSource.model_validate(request)
        snapshot, files, _ = self.records.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        if options.source_sha256 != sha(files[3]):
            raise ValueError("The original native removal archive changed; inspect it again.")
        compiler = compiler_from_snapshot(snapshot, files)
        record = compiler.archive.wire.reader.records.get(options.diagram_ref)
        if record is None or record["sha256"] != options.record_sha256:
            raise ValueError("The original native removal diagram changed; inspect it again.")
        return (
            options,
            compiler,
            {
                **self.records.envelope(snapshot, files),
                "profile": EFFECTIVE_PROFILE,
                "compiler_profile": EDIT_PROFILE,
                "scope": EFFECTIVE_SCOPE,
                "source_sha256": sha(files[3]),
                "archive_record_sha256": options.record_sha256,
                "effective_sha256": compiler.effective.editor.source_sha256,
                "parameter_merge": compiler.parameters,
                "source_immutable": True,
                "current_identity_verified": False,
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
            "selection": compiler.effective.inspect(options.diagram_ref, options.wire_index),
        }

    def preview(self, request):
        options = EffectiveRemovalPreview.model_validate(request)
        _, compiler, envelope = self.load(
            options.model_dump(include=set(RemovalSource.model_fields))
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
        return self.checked_export(EffectiveRemovalExport.model_validate(request))


def exported(service, body, filename):
    output, review = service.export(body.model_dump())
    return Response(
        output,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Studio-Artifact-Sha256": sha(output),
            "X-Studio-Review-Sha256": review["review_sha256"],
            "X-Studio-Snapshot-Sha256": review["snapshot_sha256"],
            "X-Studio-Source-Sha256": review["source_sha256"],
            "X-Studio-Compilation-Sha256": review["compilation"]["compilation_sha256"],
        },
    )


def connection_removal_router(archive, effective):
    router = APIRouter(prefix="/api/bacnet/controller/native-application/inspection")

    @router.post("/connection-removal-copy/source")
    def source(body: RemovalSource):
        return archive.source(body.model_dump())

    @router.post("/connection-removal-copy/preview")
    def preview(body: RemovalPreview):
        return archive.preview(body.model_dump())[1]

    @router.post("/connection-removal-copy/export")
    def export(body: RemovalExport):
        return exported(archive, body, "native-connection-removal.moi")

    @router.post("/effective-connection-removal-copy/source")
    def effective_source(body: RemovalSource):
        return effective.source(body.model_dump())

    @router.post("/effective-connection-removal-copy/preview")
    def effective_preview(body: EffectiveRemovalPreview):
        return effective.preview(body.model_dump())[1]

    @router.post("/effective-connection-removal-copy/export")
    def effective_export(body: EffectiveRemovalExport):
        return exported(effective, body, "native-effective-connection-removal.moi")

    return router
