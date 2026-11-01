"""Pure local copy compilation from freshly reconstructed historical pin evidence."""

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field

from .moi_identity import seal, sha
from .native_historical_wire_recovery import PROFILE
from .native_wire_compiler import EffectiveWirePreview, EffectiveWireService
from .native_wire_copies import WireSourceRequest
from .native_wire_transfer import compile_wire


class HistoricalWirePreview(EffectiveWirePreview):
    recovery_parent_receipt: str = Field(strict=True, pattern=r"^[0-9a-f]{32}$")
    recovery_origin_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")


class HistoricalWireExport(HistoricalWirePreview):
    review_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")


class NativeHistoricalWireCopies:
    def __init__(self, records, recovery):
        self.records, self.recovery = records, recovery
        self.base = EffectiveWireService(records)

    def preview(self, request):
        options = HistoricalWirePreview.model_validate(request)
        _, _, envelope = self.base.load(
            options.model_dump(include=set(WireSourceRequest.model_fields))
        )
        _, files = self.records.load_files(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        prepared = self.recovery.prepare(
            {
                "receipt_id": options.recovery_parent_receipt,
                "capture_id": options.capture_id,
                "snapshot_sha256": options.snapshot_sha256,
            }
        )
        if prepared["profile"] != PROFILE:
            raise ValueError("Use ordinary effective wire compilation for current observed pins.")
        compiler = self.recovery.reviewed_compiler(options, files)
        output, compilation = compile_wire(
            files,
            options.model_dump(include=set(EffectiveWirePreview.model_fields)),
            _compiler=compiler,
        )
        body = {
            **envelope,
            "request": options.model_dump(),
            "compilation": compilation,
            "output_sha256": sha(output),
            "recovery_profile": PROFILE,
            "recovery_origin": prepared["origin"],
            "recovery_origin_sha256": prepared["origin_sha256"],
            "scope": "Local effective wire copy using the verified original pin with current configuration/order/cycle/width guards. No controller query or field transfer.",
        }
        return output, {**body, "review_sha256": seal(body)}

    def export(self, request):
        options = HistoricalWireExport.model_validate(request)
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if options.review_sha256 != review["review_sha256"]:
            raise ValueError("The historical-pin copy review changed; review it again.")
        return output, review


def historical_wire_copy_router(service):
    router = APIRouter(
        prefix="/api/bacnet/controller/native-application/inspection/historical-wire-source"
    )

    @router.post("/preview")
    def preview(body: HistoricalWirePreview):
        return service.preview(body.model_dump())[1]

    @router.post("/export")
    def export(body: HistoricalWireExport):
        output, review = service.export(body.model_dump())
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="native-effective-wire-source.moi"',
                "X-Studio-Artifact-Sha256": sha(output),
                "X-Studio-Review-Sha256": review["review_sha256"],
                "X-Studio-Snapshot-Sha256": review["snapshot_sha256"],
            },
        )

    return router
