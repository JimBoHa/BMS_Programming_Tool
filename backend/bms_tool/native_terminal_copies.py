"""Strict retained native archive and saved-effective local terminal copy endpoints."""

from typing import Annotated

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field

from .moi_effective_terminals import PROFILE as EFFECTIVE_PROFILE
from .moi_effective_terminals import SCOPE as EFFECTIVE_SCOPE
from .moi_effective_terminals import EffectiveTerminalCopies
from .moi_identity import seal, sha
from .moi_terminal_copies import PROFILE as COMPILER_PROFILE
from .moi_terminal_copies import SCOPE as ARCHIVE_SCOPE
from .moi_terminal_copies import MoiTerminalCopies
from .native_backup_records import BackupInspectionSource
from .native_connection_copies import Hash, Reference

PROFILE = "native-archive-local-terminal-copy/1"
Slot = Annotated[int, Field(strict=True, ge=1, le=255)]


class TerminalSource(BackupInspectionSource):
    source_sha256: Hash


class TerminalPreview(TerminalSource):
    ref: Reference
    record_sha256: Hash
    slot_property_sha256: Hash
    device_type_property_sha256: Hash
    old_slot: Slot
    destination_slot: Slot


class TerminalExport(TerminalPreview):
    review_sha256: Hash


class EffectiveTerminalPreview(TerminalPreview):
    effective_sha256: Hash
    effective_record_sha256: Hash


class EffectiveTerminalExport(EffectiveTerminalPreview):
    review_sha256: Hash


class NativeTerminalCopies:
    def __init__(self, records):
        self.records = records

    def load(self, request):
        options = TerminalSource.model_validate(request)
        snapshot, files, _ = self.records.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        if options.source_sha256 != sha(files[3]):
            raise ValueError("The retained terminal-copy source changed; inspect it again.")
        return (
            options,
            MoiTerminalCopies(files[3]),
            {
                **self.records.envelope(snapshot, files),
                "profile": PROFILE,
                "compiler_profile": COMPILER_PROFILE,
                "scope": ARCHIVE_SCOPE,
                "source_sha256": sha(files[3]),
                "source_immutable": True,
                "current_identity_verified": False,
                "saved_settings_merged": False,
                "controller_write": False,
                "field_transfer_enabled": False,
                "can_apply": False,
            },
        )

    def source(self, request):
        _, compiler, envelope = self.load(request)
        return {**envelope, "inventory": compiler.inspect()}

    def preview(self, request):
        options = TerminalPreview.model_validate(request)
        _, compiler, envelope = self.load(
            options.model_dump(include=set(TerminalSource.model_fields))
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
        return self.checked_export(TerminalExport.model_validate(request))

    def checked_export(self, options):
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if options.review_sha256 != review["review_sha256"]:
            raise ValueError("The local terminal review changed; review this exact copy again.")
        return output, review


class EffectiveNativeTerminalCopies(NativeTerminalCopies):
    def load(self, request):
        options = TerminalSource.model_validate(request)
        snapshot, files, _ = self.records.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        if options.source_sha256 != sha(files[3]):
            raise ValueError("The retained terminal-copy source changed; inspect it again.")
        compiler = EffectiveTerminalCopies(snapshot, files)
        return (
            options,
            compiler,
            {
                **self.records.envelope(snapshot, files),
                "profile": EFFECTIVE_PROFILE,
                "compiler_profile": COMPILER_PROFILE,
                "scope": EFFECTIVE_SCOPE,
                "source_sha256": sha(files[3]),
                "effective_sha256": compiler.effective.editor.source_sha256,
                "parameter_merge": compiler.parameters,
                "source_immutable": True,
                "current_identity_verified": False,
                "saved_settings_merged": True,
                "controller_write": False,
                "field_transfer_enabled": False,
                "can_apply": False,
            },
        )

    def source(self, request):
        _, compiler, envelope = self.load(request)
        inventory = compiler.effective.inspect()
        inventory["inputs"] = [
            {**item, "archive_record_sha256": compiler.archive.inputs[item["ref"]]["record_sha256"]}
            for item in inventory["inputs"]
        ]
        return {**envelope, "inventory": inventory}

    def preview(self, request):
        options = EffectiveTerminalPreview.model_validate(request)
        _, compiler, envelope = self.load(
            options.model_dump(include=set(TerminalSource.model_fields))
        )
        original = compiler.archive.inputs.get(options.ref)
        if original is None or original["record_sha256"] != options.record_sha256:
            raise ValueError("The original local input record changed; inspect it again.")
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
        return self.checked_export(EffectiveTerminalExport.model_validate(request))


def terminal_copy_router(archive, effective):
    router = APIRouter(prefix="/api/bacnet/controller/native-application/inputs")

    def download(service, request, filename):
        output, review = service.export(request.model_dump())
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

    @router.post("/terminal-copy/source")
    def source(body: TerminalSource):
        return archive.source(body.model_dump())

    @router.post("/terminal-copy/preview")
    def preview(body: TerminalPreview):
        return archive.preview(body.model_dump())[1]

    @router.post("/terminal-copy/export")
    def export(body: TerminalExport):
        return download(archive, body, "native-local-terminal-copy.moi")

    @router.post("/effective-terminal-copy/source")
    def effective_source(body: TerminalSource):
        return effective.source(body.model_dump())

    @router.post("/effective-terminal-copy/preview")
    def effective_preview(body: EffectiveTerminalPreview):
        return effective.preview(body.model_dump())[1]

    @router.post("/effective-terminal-copy/export")
    def effective_export(body: EffectiveTerminalExport):
        return download(effective, body, "native-effective-terminal-copy.moi")

    return router
