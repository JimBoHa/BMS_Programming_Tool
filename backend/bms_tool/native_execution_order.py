"""Source-bound saved-effective native order compilation; local APIs only."""

from typing import Annotated

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field

from .moi_effective_wire import EffectiveWireCompiler
from .moi_effective_wire import compiler_from_snapshot as qualified_merge
from .moi_execution_order import MoiExecutionOrder
from .moi_identity import MoiIdentity, seal, sha
from .native_backup_records import BackupInspectionSource

PROFILE = "native-effective-execution-order-compiler/1"
SCOPE = (
    "Local execution-order compilation from an identity-qualified retained File 3/11/12 "
    "saved merge. Preserve original membership, graph, layout and continuation across the "
    "merge, then preserve each recorded wire phase and every other merged expanded byte. "
    "Captured saved values are historical. No fresh-setting guarantee, controller query, "
    "transfer, new identities, general compiler/resources/runtime or CCT/physical acceptance."
)
Hash = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
Index = Annotated[int, Field(strict=True, ge=0, le=511)]


class OrderSource(BackupInspectionSource):
    source_sha256: Hash
    diagram_ref: str = Field(strict=True, min_length=1, max_length=512)
    record_sha256: Hash


class OrderPreview(OrderSource):
    effective_sha256: Hash
    effective_record_sha256: Hash
    selection_sha256: Hash
    proposed_order: list[Index] = Field(min_length=1, max_length=512)


class OrderExport(OrderPreview):
    review_sha256: Hash


class EffectiveOrderCompiler:
    def __init__(self, snapshot, files):
        if type(snapshot.get("identity", {}).get("vendor-identifier")) is not int:
            raise ValueError("Native order compilation requires a typed vendor identifier.")
        merged = qualified_merge(snapshot, files)
        self._initialize(merged, files)

    @classmethod
    def from_files(cls, files):
        """Compile validated native files without inventing acquisition metadata."""
        compiler = cls.__new__(cls)
        compiler._initialize(EffectiveWireCompiler(files), files)
        return compiler

    def _initialize(self, merged, files):
        before, after = merged.archive.reader, merged.effective.reader
        for ref, record in before.records.items():
            if record["class_id"] in (536, 575) and record["properties"].get(3384, {}).get(
                "encoded_sha256"
            ) != after.records[ref]["properties"].get(3384, {}).get("encoded_sha256"):
                raise ValueError("Saved values changed native connection continuation metadata.")
        self.archive = MoiExecutionOrder(files[3])
        self.effective = MoiExecutionOrder(merged.merged)
        self.parameters, self.files = merged.parameters, merged.files

    def compile(self, *, diagram_ref, selection_sha256, proposed_order):
        output, edit = self.effective.compile(
            diagram_ref=diagram_ref,
            selection_sha256=selection_sha256,
            proposed_order=proposed_order,
        )
        checked = MoiIdentity(output)
        expected = bytearray(self.effective.editor.data)
        for patch in edit["patches"]:
            at, width = patch["payload_offset"], patch["payload_bytes"]
            expected[at : at + width] = patch["new_index"].to_bytes(width, "big")
        if checked.data != bytes(expected):
            raise ValueError("Execution-order compilation changed another merged native byte.")
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "files": self.files,
            "parameter_merge": self.parameters,
            "archive_sha256": self.archive.editor.source_sha256,
            "effective_sha256": self.effective.editor.source_sha256,
            "order_edit": edit,
            "compiled_sha256": sha(output),
            "compiled_native_sha256": sha(checked.data),
            "native_record_count": len(checked.records),
            "saved_settings_merged": True,
            "other_merged_bytes_preserved": True,
            "controller_write": False,
            "field_transfer_enabled": False,
        }
        return output, {**body, "compilation_sha256": seal(body)}


class NativeExecutionOrder:
    def __init__(self, records):
        self.records = records

    def load(self, request):
        options = OrderSource.model_validate(request)
        snapshot, files, _ = self.records.load(
            options.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        compiler = EffectiveOrderCompiler(snapshot, files)
        archive = compiler.archive.inspect(options.diagram_ref)
        if (
            options.source_sha256 != sha(files[3])
            or options.record_sha256 != archive["record_sha256"]
        ):
            raise ValueError("The original native order source changed; inspect it again.")
        body = {
            **self.records.envelope(snapshot, files),
            "profile": PROFILE,
            "scope": SCOPE,
            "source_sha256": sha(files[3]),
            "archive_record_sha256": options.record_sha256,
            "effective_sha256": compiler.effective.editor.source_sha256,
            "parameter_merge": compiler.parameters,
            "selection": compiler.effective.inspect(options.diagram_ref),
            "source_immutable": True,
            "saved_settings_merged": True,
            "current_identity_verified": False,
            "controller_write": False,
            "field_transfer_enabled": False,
            "can_apply": False,
        }
        return compiler, {**body, "source_report_sha256": seal(body)}

    def source(self, request):
        return self.load(request)[1]

    def preview(self, request):
        options = OrderPreview.model_validate(request)
        compiler, source = self.load(options.model_dump(include=set(OrderSource.model_fields)))
        selection = source["selection"]
        if (
            options.effective_sha256 != source["effective_sha256"]
            or options.effective_record_sha256 != selection["record_sha256"]
            or options.selection_sha256 != selection["selection_sha256"]
        ):
            raise ValueError("The effective native order changed; inspect it again.")
        output, compilation = compiler.compile(
            diagram_ref=options.diagram_ref,
            selection_sha256=options.selection_sha256,
            proposed_order=options.proposed_order,
        )
        body = {
            "profile": PROFILE,
            "source": source,
            "request": options.model_dump(),
            "compilation": compilation,
            "output_sha256": sha(output),
            "controller_write": False,
            "field_transfer_enabled": False,
            "can_apply": False,
        }
        return output, {**body, "review_sha256": seal(body)}

    def export(self, request):
        options = OrderExport.model_validate(request)
        output, review = self.preview(options.model_dump(exclude={"review_sha256"}))
        if review["review_sha256"] != options.review_sha256:
            raise ValueError("The native execution-order review changed; review it again.")
        return output, review


def execution_order_router(records):
    service = NativeExecutionOrder(records)
    router = APIRouter(
        prefix="/api/bacnet/controller/native-application/inspection/execution-order"
    )

    @router.post("/source")
    def source(body: OrderSource):
        return service.source(body.model_dump())

    @router.post("/preview")
    def preview(body: OrderPreview):
        return service.preview(body.model_dump())[1]

    @router.post("/export")
    def export(body: OrderExport):
        output, review = service.export(body.model_dump())
        return Response(
            output,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="native-effective-execution-order.moi"',
                "X-Studio-Artifact-Sha256": sha(output),
                "X-Studio-Review-Sha256": review["review_sha256"],
                "X-Studio-Source-Sha256": body.source_sha256,
                "X-Studio-Snapshot-Sha256": body.snapshot_sha256,
                "X-Studio-Compilation-Sha256": review["compilation"]["compilation_sha256"],
            },
        )

    return router
