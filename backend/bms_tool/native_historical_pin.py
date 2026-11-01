"""A private wire compiler can use one retained, verified original output pin."""

from typing import Literal

from pydantic import Field, field_validator

from .models import StrictModel
from .moi_effective_wire import EffectiveWireCompiler
from .moi_identity import seal, sha
from .moi_wire_sources import MoiWireSources
from .native_wire_copies import UInt

PROFILE = "native-recorded-wire-pin/1"


class RecordedWirePin(StrictModel):
    profile: Literal[PROFILE]
    original_capture_id: str = Field(strict=True, pattern=r"^[0-9a-f]{32}$")
    original_snapshot_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    original_native_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    after_native_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    current_archive_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    diagram_ref: str = Field(strict=True, min_length=1, max_length=512)
    diagram_class: int = Field(strict=True)
    wire_index: int = Field(strict=True, ge=0, le=4095)
    old: list[UInt] = Field(min_length=4, max_length=4)
    source_ref: str = Field(strict=True, min_length=1, max_length=512)
    source_class: int = Field(strict=True, ge=0, le=65535)
    source_object: str = Field(strict=True, min_length=1, max_length=80)
    source_configuration_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    target_ref: str = Field(strict=True, min_length=1, max_length=512)
    source_index_bytes: int = Field(strict=True, ge=1, le=4)

    @field_validator("diagram_class")
    @classmethod
    def actual_diagram_class(cls, value):
        if value not in (536, 575):
            raise ValueError("A retained pin needs an actual qualified native diagram class.")
        return value


class _HistoricalSources(MoiWireSources):
    def __init__(self, data, pin):
        super().__init__(data)
        self.pin = pin

    def _refusal(self, graph, wires, wire, source_ref):
        pin = self.pin
        if (
            graph["ref"] == pin.diagram_ref
            and wire["index"] == pin.wire_index
            and source_ref == pin.source_ref
        ):
            # This is the actual original selected connection, not an invented
            # prototype pin. Its same index excludes it from adjacency while
            # the inherited order/cycle/width/configuration checks run.
            original = {
                "index": pin.wire_index,
                "source_ref": pin.source_ref,
                "source_port": pin.old[1],
                "target_ref": pin.target_ref,
                "target_port": pin.old[3],
            }
            return super()._refusal(graph, [*wires, original], wire, source_ref)
        return super()._refusal(graph, wires, wire, source_ref)


class HistoricalWireCompiler(EffectiveWireCompiler):
    def __init__(self, files, evidence):
        super().__init__(files)
        pin = RecordedWirePin.model_validate(evidence)
        if (
            sha(self.archive.editor.data) != pin.after_native_sha256
            or self.archive.editor.source_sha256 != pin.current_archive_sha256
        ):
            raise ValueError("The application differs from the retained pin's verified outcome.")
        graph, record, _, wires = self.effective.graph(pin.diagram_ref)
        if pin.wire_index >= len(wires):
            raise ValueError("The retained pin's existing connection is unavailable.")
        wire = wires[pin.wire_index]
        source = next((row for row in graph["blocks"] if row["ref"] == pin.source_ref), None)
        if (
            record["class_id"] != pin.diagram_class
            or source is None
            or source["index"] != pin.old[0]
            or source["class_id"] != pin.source_class
            or source["object"] != pin.source_object
            or seal(self.effective.signatures[pin.source_ref]) != pin.source_configuration_sha256
            or wire["old"][1:] != pin.old[1:]
            or wire["target_ref"] != pin.target_ref
            or wire["source_index_bytes"] != pin.source_index_bytes
            or any(
                row["source_ref"] == pin.source_ref and row["source_port"] == pin.old[1]
                for row in wires
            )
        ):
            raise ValueError("The retained output pin or its current native configuration changed.")
        self.pin = pin
        self.candidate = {
            key: source[key] for key in ("index", "ref", "name", "class_id", "object")
        } | {"current_source": False}
        self.effective = _HistoricalSources(self.merged, pin)

    def compile(self, **proposal):
        if (
            proposal.get("diagram_ref") != self.pin.diagram_ref
            or proposal.get("wire_index") != self.pin.wire_index
            or proposal.get("source_ref") != self.pin.source_ref
        ):
            raise ValueError("Retained pin evidence qualifies only its exact previous connection.")
        output, compilation = super().compile(**proposal)
        pin = self.pin.model_dump()
        return output, {
            **compilation,
            "historical_pin_evidence": pin,
            "historical_pin_evidence_sha256": seal(pin),
        }


def recorded_pin_matches(origin, body):
    """Check recorded typed proof bindings without claiming the source files still exist."""
    pin = origin.historical_pin
    compilation = body.get("compilation")
    if not isinstance(compilation, dict):
        return False
    selected = compilation.get("wire_edit")
    return (
        isinstance(selected, dict)
        and selected.get("profile") == "tagged-moi-wire-source-copy/1"
        and selected.get("changed") is True
        and origin.historical_pin_sha256 == seal(pin.model_dump())
        and compilation.get("historical_pin_evidence_sha256") == origin.historical_pin_sha256
        and seal(compilation.get("historical_pin_evidence")) == origin.historical_pin_sha256
        and pin.current_archive_sha256 == compilation.get("archive_sha256")
        and pin.original_capture_id == origin.original_backup_id
        and pin.original_snapshot_sha256 == origin.original_snapshot_sha256
        and pin.diagram_ref == origin.diagram_ref
        and pin.diagram_class == origin.class_id
        and pin.wire_index == origin.wire_index
        and pin.old == origin.previous_tuple
        and pin.source_ref == origin.previous_source_ref
        and pin.target_ref == origin.target_ref
        and pin.source_index_bytes == origin.source_index_bytes
        and type(selected.get("source_class")) is int
        and pin.source_class == selected["source_class"]
    )
